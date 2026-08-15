"""Complaints (reopen loop, terminal lockdown), site-mass conservation,
RBAC cross-role denials."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_accept_drop,
    create_complaint_payload,
    create_contamination_report_payload,
    create_drop_at_site,
    get_success_data,
    make_participant_headers,
    make_processing_partner_headers,
    setup_closed_accepted_batch,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    create_partner_payload,
    create_route_payload,
    create_stop_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
AUDITOR = TEST_USERS["municipal_auditor_headers"]
HOST = TEST_USERS["site_host_headers"]
OPERATOR = TEST_USERS["route_operator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / complaint_ticket_cyclic_reopen_loop
# (2 tests)
# ---------------------------------------------------------------------------

def _setup_complaint_reopened_twice(api):
    """Complaint driven through resolve -> reopen -> resolve -> reopen ->
    resolve; reopen_count is now 2."""
    ids = setup_program_with_operational_site()
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    c = validate_success(api.create_complaint(
        prog_id, site_id, create_complaint_payload(
            reporter_contact="n1", kind="ODOR", description="smell",
            reported_at="2026-08-01T09:00:00Z"),
        ANON), expected_status=201)
    c_id = c["id"]

    for _ in range(2):
        get_success_data(api.resolve_complaint(prog_id, site_id, c_id, ADMIN))
        get_success_data(api.reopen_complaint(prog_id, site_id, c_id, AUDITOR))
    get_success_data(api.resolve_complaint(prog_id, site_id, c_id, ADMIN))
    return prog_id, site_id, c_id


def test_third_reopen_attempt_hits_reopen_limit(api):
    """PRD §3.7: "A `MunicipalAuditor` may reopen a resolved ticket, but only
    twice over a ticket's lifetime: reopening requires `reopen_count` below 2,
    failing with `ERR_COMPLAINT_REOPEN_LIMIT` (HTTP 409) at the limit"

    Design: Difficulty/non_linear_state_machine/complaint_ticket_cyclic_reopen_loop
    """
    prog_id, site_id, c_id = _setup_complaint_reopened_twice(api)

    resp = api.reopen_complaint(prog_id, site_id, c_id, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_REOPEN_LIMIT)


def test_reopen_counter_stuck_at_two_after_failed_reopen(api):
    """PRD §3.7: "on success increments `reopen_count` by 1, clears
    `resolved_at`, moves the ticket to `REOPENED`, and recomputes posture."
    PRD §3.7: "reopening requires `reopen_count` below 2, failing with
    `ERR_COMPLAINT_REOPEN_LIMIT` (HTTP 409) at the limit"

    Design: Difficulty/non_linear_state_machine/complaint_ticket_cyclic_reopen_loop
    """
    prog_id, site_id, c_id = _setup_complaint_reopened_twice(api)

    resp = api.reopen_complaint(prog_id, site_id, c_id, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_REOPEN_LIMIT)

    data, _meta = validate_paginated(api.list_complaints(prog_id, site_id, ADMIN))
    ticket = [t for t in data if t["id"] == c_id][0]
    assert ticket["reopen_count"] == 2
    assert ticket["status"] == "RESOLVED", (
        "a failed reopen must leave the ticket RESOLVED with no drift")


# ---------------------------------------------------------------------------
# Corner: state_machines/complaint_terminal_close_lockdown (1 test)
# ---------------------------------------------------------------------------

def test_closed_complaint_rejects_further_transitions(api):
    """PRD §3.7: "Closure requires demonstrated stability: a ticket may move
    from `RESOLVED` to `CLOSED` only after it has remained `RESOLVED` through
    at least one full ops-run checkpoint — tracked by comparing the program's
    `ops_run_index` at resolve time against the current one — failing with
    `ERR_COMPLAINT_NOT_STABLE` (HTTP 409) if no ops run has intervened.
    `CLOSED` is terminal."
    PRD §2.9: "From-state: the target resource is in a valid from-state for
    the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/complaint_terminal_close_lockdown
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    c = validate_success(api.create_complaint(
        prog_id, site_id, create_complaint_payload(
            reporter_contact="n1", kind="ODOR", description="smell",
            reported_at="2026-08-01T09:00:00Z"),
        ANON), expected_status=201)
    c_id = c["id"]
    get_success_data(api.resolve_complaint(prog_id, site_id, c_id, ADMIN))
    get_success_data(api.run_ops(prog_id, ADMIN))
    closed = validate_success(api.close_complaint(prog_id, site_id, c_id, ADMIN))
    assert closed["status"] == "CLOSED"

    resp = api.resolve_complaint(prog_id, site_id, c_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / site_mass_conservation_pickup_and_reject
# (2 tests)
# ---------------------------------------------------------------------------

def _setup_mass_conservation(api):
    """Drop A 10.00/0.00 ACCEPTED; drop B 5.00/0.00 PENDING_AUDIT; route
    collects 8.00 kg; batch CLOSED_ACCEPTED with 0.00 measured; CRITICAL
    report opened on drop B."""
    ids = setup_program_with_operational_site()
    prog_id, site_id, mat_id = ids["prog_id"], ids["site_id"], ids["mat_id"]
    part = setup_verified_participant_with_grant(prog_id, site_id)

    create_and_accept_drop(prog_id, site_id, part["part_id"], part["grant_id"],
                           mat_id, gross_weight_kg=10.00,
                           occurred_at="2026-07-01T10:00:00Z")
    drop_b = create_drop_at_site(prog_id, site_id, part["part_id"],
                                 part["grant_id"], mat_id,
                                 gross_weight_kg=5.00,
                                 occurred_at="2026-07-01T11:00:00Z")

    setup_closed_accepted_batch(
        prog_id, site_id, planned_pickup_kg=8, actual_pickup_kg=8.00,
        measured_contamination_kg=0.00, yield_ratio=0.5)

    rep = validate_success(api.create_contamination_report(
        prog_id, site_id,
        create_contamination_report_payload(
            drop_event_id=drop_b["id"], severity="CRITICAL",
            finding_note="all plastic"),
        AUDITOR), expected_status=201)
    return ids, drop_b, rep["id"]


def test_critical_dismissal_rejects_flagged_drop(api):
    """PRD §3.4: "Dismissal, a `MunicipalAuditor` prerogative, moves a report
    from `OPEN` to `DISMISSED`; when the dismissed report has severity
    `CRITICAL` and references a drop, the linked drop transitions to
    `REJECTED`."
    PRD §3.4: "Rejection — whether by dismissal of a `CRITICAL` report or by a
    `SiteHost` explicitly rejecting a flagged drop — moves
    `verification_state` to `REJECTED`, subtracts the drop's
    `provisional_net_kg` from the site's `stored_kg` (the mass was never truly
    accepted), and flips `credit_state` to `REVOKED`."

    Design: Difficulty/compensating_invariant/site_mass_conservation_pickup_and_reject
    """
    ids, drop_b, rep_id = _setup_mass_conservation(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    validate_success(api.dismiss_contamination_report(
        prog_id, site_id, rep_id, AUDITOR))

    got = validate_success(api.get_drop(prog_id, site_id, drop_b["id"], ADMIN))
    assert got["verification_state"] == "REJECTED"
    assert got["credit_state"] == "REVOKED"


def test_site_mass_ledger_conserved_across_pickup_and_reject(api):
    """PRD §2.8: "A site's `stored_kg` equals the sum of the net mass of every
    live drop event at the site — provisional net while a drop is pending or
    accepted-but-unreconciled, final net once a batch has reconciled it —
    minus the sum of `actual_pickup_kg` over all `COLLECTED` stops at the
    site. A drop that is rejected subtracts its provisional mass, because that
    mass was counted at drop time but is never accepted."

    Design: Difficulty/compensating_invariant/site_mass_conservation_pickup_and_reject
    """
    ids, drop_b, rep_id = _setup_mass_conservation(api)
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    get_success_data(api.dismiss_contamination_report(
        prog_id, site_id, rep_id, AUDITOR))

    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    # PRD §2.8: once the batch reconciles drop A it contributes its final net
    # (8.00), not its provisional 10.00: 8.00 (A final) + 5.00 (B pending)
    # - 8.00 (collected) - 5.00 (B rejected) = 0.00
    assert site["stored_kg"] == pytest.approx(0.00), (
        f"mass ledger must conserve: expected 0.00, got {site['stored_kg']}")


# ---------------------------------------------------------------------------
# Corner: rbac/sitehost_cannot_create_contamination_report (1 test)
# ---------------------------------------------------------------------------

def test_sitehost_cannot_open_contamination_report(api):
    """PRD §3.4: "Contamination findings come from `MunicipalAuditor`
    operators, never site staff."
    PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/sitehost_cannot_create_contamination_report
    """
    ids = setup_program_with_operational_site()

    resp = api.create_contamination_report(
        ids["prog_id"], ids["site_id"],
        create_contamination_report_payload(auditor_id="x", severity="MINOR",
                                            finding_note="test"),
        HOST)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


# ---------------------------------------------------------------------------
# Corner: rbac/participant_cannot_dispatch_route (1 test)
# ---------------------------------------------------------------------------

def test_participant_cannot_dispatch_route(api):
    """PRD §2.1: "If the role is recognized but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §3.5: "Getting material off site is the `RouteOperator`'s domain"

    Design: Corner/rbac/participant_cannot_dispatch_route
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    partner = validate_success(api.create_partner(
        prog_id, create_partner_payload(), ADMIN), expected_status=201)
    route = validate_success(api.create_route(
        prog_id, create_route_payload(partner["id"]), OPERATOR),
        expected_status=201)
    validate_success(api.create_stop(
        prog_id, route["id"],
        create_stop_payload(site_id, route["version"]), OPERATOR),
        expected_status=201)

    part = setup_verified_participant_with_grant(prog_id, site_id)
    resp = api.dispatch_route(prog_id, route["id"],
                              make_participant_headers(part["part_id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
