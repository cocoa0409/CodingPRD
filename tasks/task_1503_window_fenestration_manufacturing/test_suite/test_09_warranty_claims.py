"""Warranty claims: coverage variants, adjudication workflow, gating (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_repair_part,
    assert_warranty_claim,
    create_claim,
    get_success_data,
    list_claim_shipments,
    set_clock,
    setup_claim_under_review,
    setup_delivered_order,
    setup_shipped_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
WA = TEST_USERS["warranty_adjuster_headers"]


def test_component_hardware_full_coverage_at_eight_years(api):
    """PRD §3.7: "`HARDWARE` and `GRID` carry 10-year windows: 100 percent while
    fewer than ten years have elapsed, zero thereafter."
    PRD §3.7: "Coverage is measured in whole years: `years_elapsed` is the
    number of complete 365-day years between the order's `delivered_at` and the
    claim's `failure_date`."

    Design: Difficulty/dual_variant_calc/warranty_component_vs_whole_unit_coverage_divergence
    """
    env = setup_delivered_order()
    set_clock("2034-09-06T00:00:00Z")  # 8 full years after 2026-09-05 delivery
    claim = create_claim(env["order"]["id"], env["line"]["id"],
                         component="HARDWARE", coverage_variant="COMPONENT",
                         failure_date="2034-09-06T00:00:00Z",
                         description="lock failed")
    assert_warranty_claim(claim)
    assert claim["coverage_pct"] == 100
    assert claim["status"] == "SUBMITTED"


def test_whole_unit_grid_prorated_at_eight_years(api):
    """PRD §3.7: "Under the `WHOLE_UNIT` variant a single blanket 15-year window
    covers any component: 100 percent while fewer than five years have elapsed,
    then one hundred minus twenty times the number of elapsed years beyond
    five, never below zero, and zero once fifteen or more years have elapsed.
    Identical failure dates can therefore produce very different `coverage_pct`
    values under the two variants."

    Design: Difficulty/dual_variant_calc/warranty_component_vs_whole_unit_coverage_divergence
    """
    env = setup_delivered_order()
    set_clock("2034-09-06T00:00:00Z")
    claim = create_claim(env["order"]["id"], env["line"]["id"],
                         component="GRID", coverage_variant="WHOLE_UNIT",
                         failure_date="2034-09-06T00:00:00Z",
                         description="grid detached")
    assert claim["status"] == "SUBMITTED"
    # 8 years elapsed -> 100 - 20 * (8 - 5) = 40
    assert claim["coverage_pct"] == 40


def test_claim_blocked_until_order_delivered(api):
    """PRD §3.7: "The order must be `DELIVERED` (`ERR_ORDER_NOT_DELIVERED`); the
    `failure_date` must be on or after the order's `delivered_at` and not later
    than the current logical time, and violations return `ERR_INVALID_REQUEST`."

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_until_order_delivered
    """
    env = setup_shipped_order()  # SHIPPED but never delivery-confirmed
    set_clock("2026-09-06T00:00:00Z")
    res = api.create_warranty_claim({
        "order_id": env["order"]["id"],
        "order_line_id": env["line"]["id"],
        "component": "FRAME",
        "coverage_variant": "COMPONENT",
        "failure_date": "2026-09-06T00:00:00Z",
        "description": "premature claim",
    }, PM)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_DELIVERED, expected_status=409)


def test_rejected_claim_is_not_persisted(api):
    """PRD §3.7: "The order must be `DELIVERED` (`ERR_ORDER_NOT_DELIVERED`)"
    PRD §3.7: "Claims can be listed per order, or plant-wide filtered by
    `order_id`, `order_line_id`, or `status`."

    Design: Difficulty/cross_entity_state_dependency/claim_blocked_until_order_delivered
    """
    env = setup_shipped_order()
    set_clock("2026-09-06T00:00:00Z")
    validate_error(api.create_warranty_claim({
        "order_id": env["order"]["id"],
        "order_line_id": env["line"]["id"],
        "component": "FRAME",
        "coverage_variant": "COMPONENT",
        "failure_date": "2026-09-06T00:00:00Z",
        "description": "premature claim",
    }, PM), ApiErrorId.ERR_ORDER_NOT_DELIVERED)

    data, meta = validate_paginated(api.list_order_warranty_claims(env["order"]["id"], PM))
    assert data == []
    assert meta["total_count"] == 0


def test_warranty_claim_review_appeal_cycle(api):
    """PRD §3.7: "A `WarrantyAdjuster` (or `PlantManager`) takes a `SUBMITTED`
    claim into `UNDER_REVIEW`, and may bounce it to `INFO_REQUESTED`; the dealer
    answers — `DealerRep` on their own dealership's claim, or a `PlantManager` —
    returning it `INFO_REQUESTED → UNDER_REVIEW`. Denial moves `UNDER_REVIEW →
    DENIED` and records the supplied `denial_reason`; the dealer may appeal,
    moving `DENIED → UNDER_REVIEW`."
    PRD §3.7: "A `REFUND` remedy fulfills the claim immediately, moving it
    straight to `FULFILLED`."
    PRD §3.7: "Either way, `remedy_value_cents` is set to the line's frozen
    `line_total_cents` multiplied by `coverage_pct` and divided by one hundred,
    rounded half-up to whole cents — prorated first, rounded once."

    Design: Difficulty/non_linear_state_machine/warranty_claim_review_appeal_cycle
    """
    env = setup_claim_under_review(component="FRAME", coverage_variant="COMPONENT")
    claim_id = env["claim"]["id"]

    requested = validate_success(api.request_info_claim(claim_id, WA), 200)
    assert requested["status"] == "INFO_REQUESTED"
    provided = validate_success(api.provide_info_claim(claim_id, PM), 200)
    assert provided["status"] == "UNDER_REVIEW"
    denied = validate_success(api.deny_claim(
        claim_id, {"denial_reason": "insufficient evidence"}, WA), 200)
    assert denied["status"] == "DENIED"
    appealed = validate_success(api.appeal_claim(claim_id, PM), 200)
    assert appealed["status"] == "UNDER_REVIEW"

    approved = validate_success(api.approve_claim(claim_id, {"remedy": "REFUND"}, WA), 200)
    assert approved["status"] == "FULFILLED", "REFUND approve auto-fulfills"
    # coverage 100 x frozen line_total 165003
    assert approved["remedy_value_cents"] == 165003
    assert approved["denial_reason"] == "insufficient evidence"


def test_denial_records_reason_and_appeal_reopens(api):
    """PRD §3.7: "Denial moves `UNDER_REVIEW → DENIED` and records the supplied
    `denial_reason`; the dealer may appeal, moving `DENIED → UNDER_REVIEW`."
    PRD §3.7: "A `WarrantyAdjuster` (or `PlantManager`) takes a `SUBMITTED`
    claim into `UNDER_REVIEW`, and may bounce it to `INFO_REQUESTED`; the dealer
    answers — `DealerRep` on their own dealership's claim, or a `PlantManager` —
    returning it `INFO_REQUESTED → UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/warranty_claim_review_appeal_cycle
    """
    env = setup_claim_under_review(component="FRAME", coverage_variant="COMPONENT")
    claim_id = env["claim"]["id"]
    assert env["claim"]["status"] == "UNDER_REVIEW"

    requested = validate_success(api.request_info_claim(claim_id, WA), 200)
    assert requested["status"] == "INFO_REQUESTED"
    back = validate_success(api.provide_info_claim(claim_id, PM), 200)
    assert back["status"] == "UNDER_REVIEW"

    denied = validate_success(api.deny_claim(
        claim_id, {"denial_reason": "insufficient evidence"}, WA), 200)
    assert denied["status"] == "DENIED"
    fetched = validate_success(api.get_warranty_claim(claim_id, WA), 200)
    assert fetched["denial_reason"] == "insufficient evidence"

    appealed = validate_success(api.appeal_claim(claim_id, PM), 200)
    assert appealed["status"] == "UNDER_REVIEW"


def test_warranty_expired_zero_coverage_blocks_approve(api):
    """PRD §3.7: "`GLASS` carries a 2-year window: 100 percent while fewer than
    two years have elapsed, zero thereafter."
    PRD §3.7: "Approval is the adjudicator's final act and requires
    `coverage_pct` greater than zero — approving an expired claim is rejected
    with `ERR_WARRANTY_EXPIRED`."

    Design: Corner/validations/warranty_expired_zero_coverage_blocks_approve
    """
    env = setup_claim_under_review(
        component="GLASS", coverage_variant="COMPONENT",
        failure_date="2029-10-01T00:00:00Z", clock="2029-10-01T00:00:00Z",
        description="spontaneous breakage",
    )
    claim = validate_success(api.get_warranty_claim(env["claim"]["id"], WA), 200)
    assert claim["coverage_pct"] == 0, "3 elapsed years is beyond the 2-year GLASS window"

    res = api.approve_claim(claim["id"], {"remedy": "REFUND"}, WA)
    validate_error(res, ApiErrorId.ERR_WARRANTY_EXPIRED, expected_status=409)
    after = validate_success(api.get_warranty_claim(claim["id"], WA), 200)
    assert after["status"] == "UNDER_REVIEW"


def test_claim_failure_date_window_enforced(api):
    """PRD §3.7: "The order must be `DELIVERED` (`ERR_ORDER_NOT_DELIVERED`); the
    `failure_date` must be on or after the order's `delivered_at` and not later
    than the current logical time, and violations return `ERR_INVALID_REQUEST`."

    Design: Corner/validations/claim_failure_date_window_enforced
    """
    env = setup_delivered_order()  # delivered_at 2026-09-05
    set_clock("2026-09-06T00:00:00Z")

    too_early = api.create_warranty_claim({
        "order_id": env["order"]["id"], "order_line_id": env["line"]["id"],
        "component": "FRAME", "coverage_variant": "COMPONENT",
        "failure_date": "2026-09-01T00:00:00Z", "description": "too early",
    }, PM)
    validate_error(too_early, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    future = api.create_warranty_claim({
        "order_id": env["order"]["id"], "order_line_id": env["line"]["id"],
        "component": "FRAME", "coverage_variant": "COMPONENT",
        "failure_date": "2026-09-07T00:00:00Z", "description": "future",
    }, PM)
    validate_error(future, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    in_window = validate_success(api.create_warranty_claim({
        "order_id": env["order"]["id"], "order_line_id": env["line"]["id"],
        "component": "FRAME", "coverage_variant": "COMPONENT",
        "failure_date": "2026-09-06T00:00:00Z", "description": "in window",
    }, PM), 201)
    assert in_window["coverage_pct"] == 100


def test_duplicate_active_claim_rejected_until_closed(api):
    """PRD §3.7: "One active claim per line and component is the limit: if
    another claim for the same `order_line_id` and `component` exists in
    `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED`, the filing is
    rejected with `ERR_DUPLICATE_ACTIVE_CLAIM`."
    PRD §3.7: "A claim may be closed out from `SUBMITTED`, `UNDER_REVIEW`,
    `INFO_REQUESTED`, or `DENIED` by the owning `DealerRep`, a
    `WarrantyAdjuster`, or a `PlantManager`, moving it to `CLOSED`."

    Design: Corner/validations/duplicate_active_claim_rejected_until_closed
    """
    env = setup_delivered_order()
    set_clock("2027-09-01T00:00:00Z")
    claim1 = create_claim(env["order"]["id"], env["line"]["id"], component="FRAME")

    dup = api.create_warranty_claim({
        "order_id": env["order"]["id"], "order_line_id": env["line"]["id"],
        "component": "FRAME", "coverage_variant": "COMPONENT",
        "failure_date": "2027-09-01T00:00:00Z", "description": "dup",
    }, PM)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_ACTIVE_CLAIM, expected_status=409)

    validate_success(api.close_claim(claim1["id"], PM), 200)
    claim2 = validate_success(api.create_warranty_claim({
        "order_id": env["order"]["id"], "order_line_id": env["line"]["id"],
        "component": "FRAME", "coverage_variant": "COMPONENT",
        "failure_date": "2027-09-01T00:00:00Z", "description": "after close",
    }, PM), 201)
    assert claim2["status"] == "SUBMITTED"


def test_claim_take_review_wrong_state_returns_not_reviewable(api):
    """PRD §3.7: "The review actions — take-review, request-info, approve, deny —
    are only defined from their respective review states; calling them from any
    other state is rejected with `ERR_CLAIM_NOT_REVIEWABLE`."

    Design: Corner/validations/claim_take_review_wrong_state_returns_not_reviewable
    """
    env = setup_claim_under_review(component="HARDWARE", coverage_variant="COMPONENT")
    res = api.take_review_claim(env["claim"]["id"], WA)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_REVIEWABLE, expected_status=409)


def test_claim_close_then_reclose_terminal_lockdown(api):
    """PRD §3.8: "Terminal states close out each aggregate: an order ends at
    `DELIVERED` or `CANCELLED`; a line at `SHIPPED` or `CANCELLED`; a wave at
    `CLOSED` or `CANCELLED`; a claim at `FULFILLED` or `CLOSED`; a shipment at
    `DELIVERED`."
    PRD §2.10: "Any transition attempted from a state in which it is not defined
    is rejected with `ERR_INVALID_STATE` unless a more specific state error
    applies."

    Design: Corner/state_machines/claim_close_then_reclose_terminal_lockdown
    """
    env = setup_delivered_order()
    set_clock("2027-09-01T00:00:00Z")
    claim = create_claim(env["order"]["id"], env["line"]["id"], component="FRAME",
                         description="frame issue")
    closed = validate_success(api.close_claim(claim["id"], PM), 200)
    assert closed["status"] == "CLOSED"

    res = api.close_claim(claim["id"], PM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
