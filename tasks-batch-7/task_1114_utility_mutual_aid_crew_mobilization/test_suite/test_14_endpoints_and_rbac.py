"""Corner tests for endpoint filtering, the logical clock default, RBAC
exclusivity and supervisor scope, optimistic concurrency on schedule
supersession, and immediate-consistency of create responses
(PRD §2.1, §2.3, §2.4, §2.7, §2.10, §3.2, §3.3, §3.6)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID,
    make_program_admin_headers, make_responding_coordinator_headers,
    make_crew_supervisor_headers, make_responding_finance_headers,
    set_clock, create_company, create_event, create_and_publish_schedule,
    create_accepted_request, commit_crew, setup_event_active,
    setup_event_with_accepted_request,
    create_utility_company_payload, create_billing_rate_schedule_payload,
    create_crew_payload, create_timesheet_payload,
)


# --- endpoints --------------------------------------------------------------

def test_filtered_crew_list_by_mobility_status():
    """PRD §2.3: "List endpoints also accept optional equality filters drawn
    from the resource's own fields: events filter by `host_utility_id` and
    `status`; rate schedules by `event_id`, `responding_utility_id`,
    `supersedes_schedule_id`, and `status`; assistance requests by `event_id`,
    `responding_utility_id`, and `status`; crews by `request_id`,
    `owning_utility_id`, `mobility_status`, and `readiness_status`; briefings
    by `crew_id`, `event_id`, and `status`; timesheets by `crew_id`, `status`,
    `certified_schedule_id`, and `billed_invoice_id`; lodging blocks by
    `event_id`; lodging assignments by `block_id`, `crew_id`, and `status`;
    per-diem claims by `crew_id` and `status`; invoices by `request_id`,
    `rate_schedule_id`, and `status`; and after-action reports by `event_id`
    and `status`."

    Design: Corner/endpoints/ep_filtered_list_by_status
    """
    ctx = setup_event_with_accepted_request()
    crew1 = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    crew2 = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"], crew_type="TREE",
                        home_base="Depot 9",
                        roster=[{"member_ref": "M2", "member_role": "foreman"}])
    resp = api_client.withdraw_crew(crew1["id"],
                                    make_responding_coordinator_headers(ctx["rsp"]["id"]))
    assert resp.status_code == 200, f"Setup failed withdrawing crew: {resp.text}"
    resp = api_client.list_crews(
        make_program_admin_headers(),
        params={"request_id": ctx["request"]["id"], "mobility_status": "WITHDRAWN"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert len(data) == 1
    assert data[0]["id"] == crew1["id"]


def test_clock_default_time_before_any_set():
    """PRD §2.4: "Before any operator touches it, the clock stands at exactly
    `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time
    thereafter." PRD §2.5: "`created_at` (string): an ISO 8601 UTC timestamp
    with three fractional digits recording when the resource was created."

    Design: Corner/endpoints/ep_clock_default_time_2026_05_01
    """
    resp = api_client.create_utility_company(
        create_utility_company_payload(), make_program_admin_headers())
    company = validate_success(resp, expected_status=201)
    assert company["created_at"].startswith("2026-05-01T00:00:00"), (
        f"created_at must reflect the logical clock startup default, "
        f"got {company['created_at']}"
    )


# --- rbac -------------------------------------------------------------------

def test_supervisor_cannot_certify():
    """PRD §2.1: "Each endpoint admits a fixed set of roles; a caller whose
    role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    Timesheet certification is HostCoordinator-only (§4), and §2.9 orders role
    admission (2) before existence (4), so a supervisor's attempt fails with
    403 even on a fabricated timesheet id.

    Design: Corner/rbac/rbac_supervisor_cannot_certify
    """
    resp = api_client.certify_timesheet(
        NON_EXISTENT_UUID, {"certifier_operator_ref": "X"},
        make_crew_supervisor_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_responding_role_cannot_approve_invoice():
    """PRD §2.1: "Each endpoint admits a fixed set of roles; a caller whose
    role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    Invoice approval is HostFinance-only (§4).

    Design: Corner/rbac/rbac_responding_role_cannot_approve_invoice
    """
    rsp = create_company(name="Responder Electric", company_code="RSP",
                         role_capability="RESPONDING", home_region="Inland")
    resp = api_client.approve_invoice(
        NON_EXISTENT_UUID, {"approver_operator_ref": "FIN-1"},
        make_responding_finance_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_supervisor_scope_other_crew_rejected():
    """PRD §2.1: "When `X-User-Role` is `CrewSupervisor`, `X-User-ID` is the
    `id` of the acting `Crew`, so a supervisor's authority extends only to that
    crew's timesheets and briefing acknowledgments. Any mismatch between an
    entity-backed caller's `X-User-ID` and the resource's owning scope is
    rejected with `ERR_SCOPE_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/rbac_supervisor_scope_other_crew_rejected
    """
    ctx = setup_event_with_accepted_request()
    crew_a = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"])
    crew_b = commit_crew(ctx["request"]["id"], ctx["rsp"]["id"], crew_type="TREE",
                         home_base="Depot 9",
                         roster=[{"member_ref": "M2", "member_role": "foreman"}])
    resp = api_client.create_timesheet(
        create_timesheet_payload(crew_id=crew_b["id"], work_date="2026-05-04"),
        make_crew_supervisor_headers(crew_a["id"]))
    validate_error(resp, ApiErrorId.ERR_SCOPE_MISMATCH)


# --- optimistic concurrency -------------------------------------------------

def test_occ_stale_supersede_version_rejected():
    """PRD §2.7: "If the predecessor's current `version` no longer equals the
    presented value, the publication is rejected with
    `ERR_STALE_SCHEDULE_VERSION` (HTTP 412) and nothing is mutated" and "when a
    predecessor was named it moves that predecessor from `PUBLISHED` to
    `SUPERSEDED` and increments the predecessor's `version` by one — the bump a
    stale reader will trip over at their own publication attempt."

    Design: Corner/cross_cutting_layers/layer_occ_stale_supersede_version_rejected
    """
    host, rsp, event = setup_event_active()
    s1 = create_and_publish_schedule(event["id"], rsp["id"])
    resp = api_client.get_billing_rate_schedule(s1["id"], make_program_admin_headers())
    s1_v = validate_success(resp)["version"]
    # S2 supersedes S1 with the correct version; S1's version bumps by one.
    resp = api_client.create_billing_rate_schedule(
        create_billing_rate_schedule_payload(event_id=event["id"],
                                             supersedes_schedule_id=s1["id"],
                                             rate_lines=[{"crew_type": "LINE",
                                                          "hourly_rate_cents": 12100}]),
        make_responding_coordinator_headers(rsp["id"]))
    s2 = get_success_data(resp)
    resp = api_client.publish_billing_rate_schedule(
        s2["id"], {"expected_superseded_schedule_version": s1_v},
        make_responding_coordinator_headers(rsp["id"]))
    s2 = validate_success(resp)
    assert s2["status"] == "PUBLISHED"
    resp = api_client.get_billing_rate_schedule(s2["id"], make_program_admin_headers())
    s2_v = validate_success(resp)["version"]
    # S3 names S2 as predecessor but presents a stale version for S2.
    resp = api_client.create_billing_rate_schedule(
        create_billing_rate_schedule_payload(event_id=event["id"],
                                             supersedes_schedule_id=s2["id"],
                                             rate_lines=[{"crew_type": "LINE",
                                                          "hourly_rate_cents": 12200}]),
        make_responding_coordinator_headers(rsp["id"]))
    s3 = get_success_data(resp)
    resp = api_client.publish_billing_rate_schedule(
        s3["id"], {"expected_superseded_schedule_version": s2_v - 1},
        make_responding_coordinator_headers(rsp["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_SCHEDULE_VERSION)
    resp = api_client.get_billing_rate_schedule(s3["id"], make_program_admin_headers())
    assert validate_success(resp)["status"] == "DRAFT"
    resp = api_client.get_billing_rate_schedule(s2["id"], make_program_admin_headers())
    s2_after = validate_success(resp)
    assert s2_after["status"] == "PUBLISHED"
    assert s2_after["version"] == s2_v


# --- consistency model ------------------------------------------------------

def test_create_response_carries_post_mutation_state():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.3: "A crew is born with `mobility_status` `COMMITTED` and
    `readiness_status` `AWAITING_BRIEFING`" and "The server derives
    `roster_size` from the roster's length" and "stamps `owning_utility_id`
    from the caller's `X-User-ID`"

    Design: Corner/consistency_model/consistency_immediate_mutation_visible
    """
    ctx = setup_event_with_accepted_request()
    resp = api_client.create_crew(
        create_crew_payload(request_id=ctx["request"]["id"]),
        make_responding_coordinator_headers(ctx["rsp"]["id"]))
    crew = validate_success(resp, expected_status=201)
    assert crew["mobility_status"] == "COMMITTED"
    assert crew["readiness_status"] == "AWAITING_BRIEFING"
    assert crew["roster_size"] == 1
    assert crew["version"] == 1
    assert crew["owning_utility_id"] == ctx["rsp"]["id"]
