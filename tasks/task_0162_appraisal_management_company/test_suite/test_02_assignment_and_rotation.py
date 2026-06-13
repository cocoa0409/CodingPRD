"""Assignment creation, the rotation selector, reassignment, and OCC on assign.

Covers queue B (Corner) instances in state_machines, endpoints, rbac, and
cross_cutting that exercise the assignment lifecycle and order versioning, plus
the no-eligible-appraiser boundary from queue A.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


def test_new_assignment_starts_offered_with_selected_appraiser(api):
    """PRD §3.2: "It creates an `Assignment` in `OFFERED` whose `appraiser_id` is the
    selector's pick, copies the order's `sla_hours` onto the assignment's own `sla_hours`,
    advances the order from `PLACED` to `ASSIGNED`, and increments the order's `version`
    by one."

    Design: Corner/state_machines/new_assignment_starts_in_offered_initial_state
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    data = validate_success(
        api.create_assignment(order["id"], factories.assignment_create_payload(order["version"]), COORD),
        201,
    )
    assert data["status"] == "OFFERED", f"new assignment must be OFFERED, got {data['status']}"
    assert data["appraiser_id"] == base["appraiser"]["id"], "selector must pick the only eligible appraiser"


def test_reassign_after_decline_creates_superseding_assignment(api):
    """PRD §3.2: "It creates a superseding `Assignment` in `OFFERED` whose
    `supersedes_assignment_id` points at the prior assignment, leaves the order in
    `ASSIGNED` (an `ASSIGNED → ASSIGNED` self-transition), and increments the order's
    `version` by one. The first assignment on an order has a null `supersedes_assignment_id`."

    Design: Corner/state_machines/reassign_after_decline_supersedes_prior_assignment
    """
    a1 = fixtures.create_appraiser(license_state="CA", full_name="Sup A1")
    a2 = fixtures.create_appraiser(license_state="CA", full_name="Sup A2")
    lender = fixtures.create_lender(panel_ids=[a1["id"], a2["id"]])
    prop = fixtures.create_property(state_code="CA")
    order = fixtures.create_order(lender["id"], prop["id"])
    asg1 = fixtures.assign_order(order["id"], order["version"])
    # First offer goes to A1 (both fresh 0.3000, created_at tie-break -> older A1).
    fixtures.api_client.decline_assignment(asg1["id"], fixtures.make_appraiser_headers(a1["id"]))

    v1 = fixtures.current_order_version(order["id"])
    data = validate_success(
        api.create_assignment(order["id"], factories.assignment_create_payload(v1), COORD),
        201,
    )
    assert data["supersedes_assignment_id"] == asg1["id"], (
        f"superseding assignment must point at the declined one {asg1['id']}, "
        f"got {data['supersedes_assignment_id']}"
    )
    assert data["appraiser_id"] == a2["id"], "the remaining eligible appraiser A2 must be selected"


def test_assign_no_eligible_appraiser_suspended_panel(api):
    """PRD §3.2: "It first builds a candidate set of appraisers, admitting an appraiser
    only when all of the following hold: the appraiser's `status` is `ACTIVE`; the
    appraiser's `license_state` equals the subject property's `state_code`; the appraiser's
    `id` is a member of the lender's `approved_panel_appraiser_ids`; the appraiser's `id` is
    not among the appraisers who have already declined an assignment on this order; and the
    appraiser's `active_assignment_count` is strictly less than the maximum active load of
    five concurrent assignments."
    PRD §3.2: "If the candidate set is empty after this filter, assignment fails with
    `ERR_NO_ELIGIBLE_APPRAISER`."

    Design: Difficulty/boundary_precision_check/no_eligible_appraiser_empty_candidate_set_on_assign
    """
    appraiser = fixtures.create_appraiser(license_state="CA", full_name="Susp A")
    validate_success(
        api.set_appraiser_status(appraiser["id"], factories.set_appraiser_status_payload("SUSPENDED"), COORD),
        200,
    )
    lender = fixtures.create_lender(panel_ids=[appraiser["id"]])
    prop = fixtures.create_property(state_code="CA")
    order = fixtures.create_order(lender["id"], prop["id"])
    resp = api.create_assignment(order["id"], factories.assignment_create_payload(order["version"]), COORD)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_APPRAISER.value, 422)


def test_assign_no_eligible_appraiser_empty_panel(api):
    """PRD §3.2: "It first builds a candidate set of appraisers, admitting an appraiser
    only when all of the following hold: the appraiser's `status` is `ACTIVE`; the
    appraiser's `license_state` equals the subject property's `state_code`; the appraiser's
    `id` is a member of the lender's `approved_panel_appraiser_ids`; the appraiser's `id` is
    not among the appraisers who have already declined an assignment on this order; and the
    appraiser's `active_assignment_count` is strictly less than the maximum active load of
    five concurrent assignments."
    PRD §3.2: "If the candidate set is empty after this filter, assignment fails with
    `ERR_NO_ELIGIBLE_APPRAISER`."

    Design: Difficulty/boundary_precision_check/no_eligible_appraiser_empty_candidate_set_on_assign
    """
    fixtures.create_appraiser(license_state="CA", full_name="Off Panel A")
    lender = fixtures.create_lender(panel_ids=[])  # empty panel -> no candidate
    prop = fixtures.create_property(state_code="CA")
    order = fixtures.create_order(lender["id"], prop["id"])
    resp = api.create_assignment(order["id"], factories.assignment_create_payload(order["version"]), COORD)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_APPRAISER.value, 422)


def test_list_assignments_filtered_by_appraiser(api):
    """PRD §4 (GET /amc/assignments): "List assignments, filterable".
    PRD §2.1: "ownership checks on any resource that references an `Appraiser` compare
    the resource's appraiser foreign key to `X-User-ID`."

    Design: Corner/endpoints/list_assignments_filtered_by_appraiser
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    asg = fixtures.assign_order(order["id"], order["version"])
    data, meta = validate_paginated(api.list_assignments(COORD, params={"appraiser_id": base["appraiser"]["id"]}))
    assert len(data) == 1, f"expected exactly 1 assignment for the appraiser, got {len(data)}"
    assert data[0]["appraiser_id"] == base["appraiser"]["id"]
    assert data[0]["id"] == asg["id"]


def test_appraiser_cannot_place_order_unauthorized(api):
    """PRD §2.1: "When the headers are well formed but the declared role is not permitted
    to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §4 (POST /amc/orders): authorized roles are `LenderUser`, `AMCCoordinator`,
    `PlatformAdmin` — Appraiser is not among them.

    Design: Corner/rbac/appraiser_cannot_place_order_unauthorized
    """
    appraiser = fixtures.create_appraiser(license_state="CA", full_name="Rb A")
    lender = fixtures.create_lender(panel_ids=[appraiser["id"]])
    prop = fixtures.create_property(state_code="CA")
    resp = api.create_order(
        factories.create_order_payload(lender["id"], prop["id"], order_fee_cents=50000, product_type="URAR_1004"),
        fixtures.make_appraiser_headers(appraiser["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_compliance_reviewer_cannot_assign(api):
    """PRD §2.1: "`ComplianceReviewer` is the USPAP/UAD compliance reviewer, kept
    independent of loan production and of order assignment as a segregation-of-duties
    measure."
    PRD §2.10: "**Generic authorization** against the role matrix follows, yielding
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/compliance_reviewer_cannot_assign_segregation_of_duties
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    resp = api.create_assignment(order["id"], factories.assignment_create_payload(order["version"]), REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_order_version_increments_by_one_on_assignment(api):
    """PRD §2.6: "`version`: an integer that starts at creation and increments by one on
    every modification."
    PRD §3.2: "It creates an `Assignment` in `OFFERED` whose `appraiser_id` is the
    selector's pick, copies the order's `sla_hours` onto the assignment's own `sla_hours`,
    advances the order from `PLACED` to `ASSIGNED`, and increments the order's `version` by
    one."

    Design: Corner/cross_cutting/order_version_increments_on_each_mutation
    """
    base = fixtures.setup_order_ready_to_assign()
    order = base["order"]
    before = order["version"]
    validate_success(
        api.create_assignment(order["id"], factories.assignment_create_payload(before), COORD),
        201,
    )
    after = validate_success(api.get_order(order["id"], COORD), 200)["version"]
    assert after == before + 1, f"order version must increment by exactly 1: {before} -> {after}"
