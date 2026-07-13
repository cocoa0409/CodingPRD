"""Access control and optimistic concurrency: authentication, role authorisation,
entity-backed ownership, segregation of duties on capital projects, and the two
version-guarded writes.
"""

import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiErrorId,
    assert_capital_project,
    building_payload,
    capital_project_payload,
    create_building,
    is_iso8601_timestamp,
    make_finance_controller_headers,
    make_tenant_rep_headers,
    make_vendor_tech_headers,
    propose_capital_project,
    read_dispatch,
    read_lease_version,
    read_statement,
    read_work_order,
    setup_active_lease,
    setup_building_and_vendor,
    setup_two_janitorial_vendors_with_shift,
    setup_two_leases_with_issued_statement,
    setup_work_order_dispatched,
    create_statement,
    create_vendor,
    create_work_order,
    dispatch_work_order,
    statement_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
FC = TEST_USERS["finance_controller_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-05-31T23:59:59Z"
JUNE_START = "2026-06-01T00:00:00Z"
JUNE_END = "2026-06-30T23:59:59Z"


# ---------------------------------------------------------------------------
# Authentication and role authorisation
# ---------------------------------------------------------------------------
def test_request_without_auth_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the caller, and `X-User-Role`, naming the caller's role. If either header
    is absent, or if `X-User-Role` is not one of the six declared role names, the request
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    response = api.create_building(
        building_payload(name="Tower One", code="BLD-1", gross_area_sqm=1000),
        NO_AUTH_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
    assert response.status_code == 401

    _, meta = validate_paginated(api.list_work_orders(FM))
    assert meta["total_count"] == 0, "nothing may be created by an unauthenticated call"


def test_facility_manager_may_not_accept_a_dispatch(api):
    """PRD §2.1: "If both headers are present and well-formed but the caller's role is
    not among the roles authorised for the endpoint being addressed (see the table in
    §4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.5: "A `VendorTech` may **accept** an offer, which moves the dispatch
    `OFFERED → ACCEPTED` and the work order `DISPATCHED → IN_PROGRESS`."

    Design: Corner/rbac/facility_manager_cannot_accept_dispatch_forbidden_role
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 1,
                      "estimated_parts_cost": 0},
    )

    response = api.accept_dispatch(ctx["dispatch"]["id"], FM)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    assert response.status_code == 403

    assert read_dispatch(ctx["dispatch"]["id"])["status"] == "OFFERED"
    assert read_work_order(ctx["work_order"]["id"])["status"] == "DISPATCHED"


# ---------------------------------------------------------------------------
# Entity-backed ownership
# ---------------------------------------------------------------------------
def test_vendor_tech_may_only_complete_its_own_shift(api):
    """PRD §2.1: "Concretely, a `VendorTech` may accept, decline, or complete only a
    dispatch whose `vendor_id` equals its `X-User-ID`, and may complete only a
    soft-service shift whose `vendor_id` equals its `X-User-ID`."
    PRD §2.1: "In every one of these five cases, an ownership mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — the role is right, the resource is not theirs."
    PRD §3.7: "A `VendorTech` reports a shift as delivered by supplying the
    `actual_headcount` that turned up; the shift moves to `COMPLETED` from either
    `SCHEDULED` or `IN_PROGRESS`."

    Design: Corner/rbac/vendor_tech_cannot_complete_another_vendors_shift
    """
    ctx = setup_two_janitorial_vendors_with_shift()

    stranger = api.complete_shift(
        ctx["shift"]["id"], {"actual_headcount": 3},
        make_vendor_tech_headers(ctx["other_vendor"]["id"]),
    )
    validate_error(stranger, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert stranger.status_code == 403

    still_scheduled = validate_success(api.get_shift(ctx["shift"]["id"], FM))
    assert still_scheduled["status"] == "SCHEDULED"

    owner = validate_success(
        api.complete_shift(
            ctx["shift"]["id"], {"actual_headcount": 2},
            make_vendor_tech_headers(ctx["owner_vendor"]["id"]),
        )
    )
    assert owner["status"] == "COMPLETED"
    assert owner["actual_headcount"] == 2


def test_tenant_rep_may_only_dispute_its_own_statement(api):
    """PRD §2.1: "When `X-User-Role` is `TenantRep`, `X-User-ID` is the `id` of the
    acting `Lease`; a `TenantRep` may dispute only a chargeback statement whose `lease_id`
    equals its `X-User-ID`. In every one of these five cases, an ownership mismatch is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) — the role is right, the resource is
    not theirs."
    PRD §3.9: "A `TenantRep` — and only the one whose lease this is — may dispute an
    `ISSUED` statement by supplying a `dispute_reason`, moving it `ISSUED → DISPUTED` and
    recording the reason."

    Design: Corner/rbac/tenant_rep_cannot_dispute_another_leases_statement
    """
    ctx = setup_two_leases_with_issued_statement()

    response = api.dispute_statement(
        ctx["statement"]["id"], {"dispute_reason": "Not my bill"},
        make_tenant_rep_headers(ctx["other_lease"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert response.status_code == 403

    statement = read_statement(ctx["statement"]["id"])
    assert statement["status"] == "ISSUED"
    assert statement["dispute_reason"] is None


# ---------------------------------------------------------------------------
# Segregation of duties on capital projects
# ---------------------------------------------------------------------------
def test_a_controller_may_not_approve_the_project_it_proposed(api):
    """PRD §2.6: "The segregation-of-duties rule at step 7 governs capital-project
    decisions only: the `FinanceController` deciding a project must not be the user who
    proposed it, that is, the decider's `X-User-ID` must differ from the project's
    `proposed_by_user_id`. If they are the same, the decision is refused with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and — because it is judged at step 7 — it is
    refused before the project's own status is even examined."
    PRD §3.3: "On `APPROVE`, the project moves `PROPOSED → APPROVED`,
    `approved_by_user_id` records the deciding `X-User-ID`, and the budget becomes
    drawable by work orders."

    Design: Corner/rbac/finance_controller_cannot_approve_own_proposal
    """
    building = create_building()
    project = propose_capital_project(building["id"], proposer_id="fc-1",
                                      title="Lobby refit", base_cost=1000.00)
    assert project["proposed_by_user_id"] == "fc-1"

    self_approval = api.approve_capital_project(
        project["id"], {"decision": "APPROVE"},
        make_finance_controller_headers("fc-1"),
    )
    validate_error(self_approval, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert self_approval.status_code == 403

    peer_approval = validate_success(
        api.approve_capital_project(
            project["id"], {"decision": "APPROVE"},
            make_finance_controller_headers("fc-2"),
        )
    )
    assert_capital_project(peer_approval)
    assert peer_approval["status"] == "APPROVED"
    assert peer_approval["approved_by_user_id"] == "fc-2"


def test_deciding_an_already_rejected_project_is_refused(api):
    """PRD §3.3: "On `REJECT`, the project moves `PROPOSED → REJECTED`,
    `approved_by_user_id` likewise records the deciding `X-User-ID`, and `budget_amount`,
    `committed_amount`, and `spent_amount` are frozen where they stand; a rejected project
    can never fund a work order. Deciding a project that is not in `PROPOSED` is refused
    with `ERR_PROJECT_NOT_PROPOSED`."
    PRD §3.3: "First it selects a `contingency_pct` from the base cost alone: 0.10 if
    `base_cost` is at most 100,000; otherwise 0.07 if it is at most 500,000; otherwise
    0.05."

    Design: Corner/rbac/approve_already_decided_project_rejected
    """
    building = create_building()
    project = propose_capital_project(building["id"], proposer_id="fc-1",
                                      title="Lobby refit", base_cost=600000.00)
    # 600,000 is above the 500,000 edge, so the top tier of 0.05 applies.
    assert project["contingency_pct"] == pytest.approx(0.05, abs=0.0001)
    assert project["budget_amount"] == pytest.approx(630000.00, abs=0.01)

    validate_success(
        api.approve_capital_project(
            project["id"], {"decision": "REJECT"},
            make_finance_controller_headers("fc-2"),
        )
    )

    response = api.approve_capital_project(
        project["id"], {"decision": "APPROVE"},
        make_finance_controller_headers("fc-3"),
    )
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_PROPOSED.value)
    assert response.status_code == 409

    final = validate_success(api.get_capital_project(project["id"], FC))
    assert final["status"] == "REJECTED"
    assert final["approved_by_user_id"] == "fc-2"


# ---------------------------------------------------------------------------
# Optimistic concurrency
# ---------------------------------------------------------------------------
def test_stale_work_order_version_on_dispatch_create_is_rejected(api):
    """PRD §2.7: "A request to dispatch a work order must carry a non-optional field
    `expected_work_order_version` holding the `version` of that work order as the client
    last read it. If the value does not equal the work order's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.5: "Creating a dispatch supersedes any earlier dispatch of the same order still
    sitting in `OFFERED`, which moves `OFFERED → CANCELLED`."
    PRD §3.5: "Dispatch creation increments the work order's `version` by 1 — which is
    precisely why the next dispatch attempt needs a freshly-read
    `expected_work_order_version`."

    Design: Corner/cross_cutting_layers/occ_stale_work_order_version_on_dispatch_create_rejected
    """
    ctx = setup_building_and_vendor(clock="2026-05-04T09:00:00Z")
    building, first_vendor = ctx["building"], ctx["vendor"]
    second_vendor = create_vendor(name="WarmAir", trade="HVAC", hourly_rate=120.00,
                                  sla_response_minutes=60, sla_resolve_minutes=240)
    work_order = create_work_order(building["id"], priority="P3",
                                   estimated_labor_hours=2, estimated_parts_cost=0)
    stale_version = work_order["version"]
    first_dispatch = dispatch_work_order(work_order["id"], first_vendor["id"])

    stale = api.create_dispatch(
        work_order["id"],
        {"vendor_id": second_vendor["id"],
         "expected_work_order_version": stale_version},
        FM,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    assert stale.status_code == 412

    assert read_dispatch(first_dispatch["id"])["status"] == "OFFERED", (
        "the rejected create must not have superseded the standing offer"
    )
    fresh_version = read_work_order(work_order["id"])["version"]
    assert fresh_version == stale_version + 1

    retry = validate_success(
        api.create_dispatch(
            work_order["id"],
            {"vendor_id": second_vendor["id"],
             "expected_work_order_version": fresh_version},
            FM,
        ),
        201,
    )
    assert retry["status"] == "OFFERED"
    assert read_dispatch(first_dispatch["id"])["status"] == "CANCELLED", (
        "a dispatch created on a fresh version legitimately supersedes the earlier offer"
    )
    # Re-priced with the superseding vendor's rate: 2h * 120.00, no P3 surcharge.
    assert read_work_order(work_order["id"])["estimated_amount"] == pytest.approx(
        240.00, abs=0.01
    )


def test_stale_lease_version_on_statement_create_is_rejected(api):
    """PRD §2.7: "A request to draft a chargeback statement for a lease must carry a
    non-optional field `expected_lease_version` holding the `version` of that lease as the
    client last read it. If it does not equal the lease's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §2.7: "Note also that both of these operations advance their parent's `version` on
    success, so a client that drafts two statements for the same lease must re-read the
    lease between them."

    Design: Corner/cross_cutting_layers/occ_stale_lease_version_on_statement_create_rejected
    """
    ctx = setup_active_lease(clock="2026-06-15T09:00:00Z", gross_area_sqm=1000,
                             space_area_sqm=100, share_pct=100)
    lease_id = ctx["lease"]["id"]
    stale_version = read_lease_version(lease_id)

    first = create_statement(lease_id, MAY_START, MAY_END)
    assert first["status"] == "DRAFT"

    stale = api.create_statement(
        lease_id, statement_payload(JUNE_START, JUNE_END, stale_version), FC
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    assert stale.status_code == 412

    statements, meta = validate_paginated(api.list_lease_statements(lease_id, FC))
    assert meta["total_count"] == 1, "the rejected create must not have left a row"
    assert statements[0]["id"] == first["id"]
    assert read_statement(first["id"])["status"] == "DRAFT"


def test_work_order_version_increments_once_per_mutation(api):
    """PRD §2.4: "Almost every resource additionally carries an `updated_at` timestamp in
    the same format and an integer `version` that starts at 1 on creation and increments
    by 1 on every mutation of that resource; `updated_at` is refreshed on every mutation as
    well."
    PRD §3.5: "Dispatch creation increments the work order's `version` by 1 — which is
    precisely why the next dispatch attempt needs a freshly-read
    `expected_work_order_version`."
    PRD §3.5: "A `VendorTech` may **accept** an offer, which moves the dispatch
    `OFFERED → ACCEPTED` and the work order `DISPATCHED → IN_PROGRESS`."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation_of_work_order
    """
    ctx = setup_work_order_dispatched(
        clock="2026-05-04T09:00:00Z",
        wo_overrides={"priority": "P3", "estimated_labor_hours": 2,
                      "estimated_parts_cost": 0},
    )
    assert ctx["work_order_at_create"]["version"] == 1, "version starts at 1 on creation"

    validate_success(
        api.accept_dispatch(ctx["dispatch"]["id"],
                            make_vendor_tech_headers(ctx["vendor"]["id"]))
    )

    work_order = read_work_order(ctx["work_order"]["id"])
    assert work_order["version"] == 3, (
        "one bump for the dispatch creation, one for the acceptance that moved the "
        "order DISPATCHED -> IN_PROGRESS"
    )
    # updated_at is refreshed on every mutation, but it is stamped from the logical
    # clock — which has not moved here — so only its presence and format are pinned.
    assert is_iso8601_timestamp(work_order["updated_at"])
