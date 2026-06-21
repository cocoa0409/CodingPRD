"""Reconsideration of value: the resolve fork, the depth-2 value->fee-split cascade,
the delta-threshold boundary, the second-review gate, and ordering constraints.

Covers queue A (Difficulty) non_linear_state_machine (ROV fork), transitive_cascade
(depth-2), boundary_precision_check (delta), cross_entity_state_dependency (ROV
requires DELIVERED), plus queue B validations/endpoints.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, factories, fixtures,
)

COORD = TEST_USERS["coordinator_headers"]


def test_rov_resolve_value_upheld_leaves_value_unchanged(api):
    """PRD §3.7 (Value upheld): "When the coordinator supplies no `new_value_cents`, the
    reconsideration resolves to `VALUE_UPHELD`. The value does not change and no fee-split
    recompute occurs."

    Design: Difficulty/non_linear_state_machine/rov_branching_fork_changed_vs_upheld
    """
    # delivered 500000, requested 505000 (delta 1.00% -> no second review).
    base = fixtures.setup_rov_under_review(requested_value_cents=505000, opinion_of_value_cents=500000)
    rov = validate_success(
        api.resolve_reconsideration(base["rov"]["id"], factories.resolve_reconsideration_payload(), COORD),
        200,
    )
    assert rov["resolution"] == "VALUE_UPHELD", f"resolve without new value must UPHELD, got {rov['resolution']}"
    order = validate_success(api.get_order(base["order"]["id"], COORD), 200)
    assert order["appraised_value_cents"] == 500000, (
        f"upheld resolution must leave appraised_value_cents at the delivered 500000, "
        f"got {order['appraised_value_cents']}"
    )


def test_rov_resolve_value_changed_updates_order_value(api):
    """PRD §3.7 (Value changed): "When the coordinator supplies a `new_value_cents` present
    and strictly greater than zero, the reconsideration resolves to `VALUE_CHANGED`."
    PRD §3.7: "On success the order's `appraised_value_cents` is set to the
    `new_value_cents`, and that change cascades a fee-split recompute (a depth-two effect)."

    Design: Difficulty/non_linear_state_machine/rov_branching_fork_changed_vs_upheld
    """
    # delivered 500000, requested 505000 (delta 1.00% -> no second review needed for change).
    base = fixtures.setup_rov_under_review(requested_value_cents=505000, opinion_of_value_cents=500000)
    rov = validate_success(
        api.resolve_reconsideration(
            base["rov"]["id"], factories.resolve_reconsideration_payload(new_value_cents=505000), COORD,
        ),
        200,
    )
    assert rov["resolution"] == "VALUE_CHANGED", f"resolve with new value must CHANGE, got {rov['resolution']}"
    order = validate_success(api.get_order(base["order"]["id"], COORD), 200)
    assert order["appraised_value_cents"] == 505000, (
        f"changed resolution must set appraised_value_cents to 505000, got {order['appraised_value_cents']}"
    )


def test_rov_value_change_cascades_value_then_feesplit_depth2(api):
    """PRD §3.7: "On success the order's `appraised_value_cents` is set to the
    `new_value_cents`, and that change cascades a fee-split recompute (a depth-two effect)."
    PRD §2.7: "The AMC share is therefore never computed independently; it is always the
    residual obtained by subtracting `appraiser_fee_cents` from the order's `order_fee_cents`."

    Design: Difficulty/transitive_cascade/rov_value_change_cascades_order_value_then_feesplit_depth2
    """
    # delivered 500000, fee 50000 share 0.60 (appraiser 30000); requested 540000 (delta 8.00% ->
    # does not exceed the 10% threshold, so no second review is required and VALUE_CHANGED is
    # reachable through the PRD §3.5 review flow that opens reviews only from SUBMITTED/RESUBMITTED).
    base = fixtures.setup_rov_under_review(
        requested_value_cents=540000, opinion_of_value_cents=500000,
        order_fee_cents=50000, base_fee_share_pct=0.60,
    )
    rov = validate_success(
        api.resolve_reconsideration(
            base["rov"]["id"], factories.resolve_reconsideration_payload(new_value_cents=540000), COORD,
        ),
        200,
    )
    assert rov["resolution"] == "VALUE_CHANGED", f"got {rov['resolution']}"
    order = validate_success(api.get_order(base["order"]["id"], COORD), 200)
    assert order["appraised_value_cents"] == 540000, (
        f"value-change must set appraised_value_cents to 540000 (link 1), got {order['appraised_value_cents']}"
    )
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    # base_fee_share_pct is value-independent, so the share stays 30000 and conservation holds.
    assert fee_split["appraiser_fee_cents"] == 30000, f"appraiser share must stay 30000, got {fee_split['appraiser_fee_cents']}"
    assert fee_split["amc_fee_cents"] == 20000, f"amc residual must stay 20000, got {fee_split['amc_fee_cents']}"


def test_rov_value_change_feesplit_recompute_conserves_fee(api):
    """PRD §3.7: "On success the order's `appraised_value_cents` is set to the
    `new_value_cents`, and that change cascades a fee-split recompute (a depth-two effect)."
    PRD §2.7: "the appraiser's share and the AMC's share must always sum to the order's
    fee. The AMC share is therefore never computed independently; it is always the residual
    obtained by subtracting `appraiser_fee_cents` from the order's `order_fee_cents`."

    Design: Difficulty/transitive_cascade/rov_value_change_cascades_order_value_then_feesplit_depth2
    """
    # delta 8.00% (540000 vs 500000) does not exceed the 10% threshold, so no second review is
    # required and the VALUE_CHANGED success path is reachable under the PRD §3.5 review flow.
    base = fixtures.setup_rov_under_review(
        requested_value_cents=540000, opinion_of_value_cents=500000,
        order_fee_cents=50000, base_fee_share_pct=0.60,
    )
    validate_success(
        api.resolve_reconsideration(
            base["rov"]["id"], factories.resolve_reconsideration_payload(new_value_cents=540000), COORD,
        ),
        200,
    )
    fee_split = validate_success(api.get_order_fee_split(base["order"]["id"], COORD), 200)[0]
    # The recomputed split (link 2) must still conserve the order fee exactly.
    assert fee_split["appraiser_fee_cents"] + fee_split["amc_fee_cents"] == 50000, (
        f"recomputed fee split must conserve the 50000 order fee, "
        f"got {fee_split['appraiser_fee_cents']} + {fee_split['amc_fee_cents']}"
    )


def test_rov_delta_exactly_threshold_no_second_review(api):
    """PRD §3.7: "From it the system derives `requires_second_review`, which is true exactly
    when the `value_delta_pct` is strictly greater than the reconsideration delta threshold
    of ten percent".
    PRD §3.7: "the system computes the `value_delta_pct`: the absolute difference between
    the `requested_value_cents` and the order's delivered `appraised_value_cents`, divided
    by that delivered value, multiplied by one hundred, and rounded half-up to two decimal
    places."

    Design: Difficulty/boundary_precision_check/rov_delta_exactly_threshold_does_not_require_second_review
    """
    # requested 550000 vs delivered 500000 = exactly 10.00% -> not strictly greater.
    base = fixtures.setup_order_delivered_with_value(opinion_of_value_cents=500000)
    rov = validate_success(
        api.create_reconsideration(
            base["order"]["id"], factories.reconsideration_payload(550000),
            fixtures.make_lender_user_headers(base["lender"]["id"]),
        ),
        201,
    )
    assert rov["value_delta_pct"] == 10.00, f"delta must be exactly 10.00, got {rov['value_delta_pct']}"
    assert rov["requires_second_review"] is False, (
        f"10.00% does not exceed the 10.0 threshold (strict >), so requires_second_review must be false, "
        f"got {rov['requires_second_review']}"
    )


def test_rov_delta_below_threshold_no_second_review(api):
    """PRD §3.7: "From it the system derives `requires_second_review`, which is true exactly
    when the `value_delta_pct` is strictly greater than the reconsideration delta threshold
    of ten percent".

    Design: Difficulty/boundary_precision_check/rov_delta_exactly_threshold_does_not_require_second_review
    """
    # requested 505000 vs delivered 500000 = 1.00% -> well below the 10.0 threshold.
    base = fixtures.setup_order_delivered_with_value(opinion_of_value_cents=500000)
    rov = validate_success(
        api.create_reconsideration(
            base["order"]["id"], factories.reconsideration_payload(505000),
            fixtures.make_lender_user_headers(base["lender"]["id"]),
        ),
        201,
    )
    assert rov["value_delta_pct"] == 1.00, f"delta must be 1.00, got {rov['value_delta_pct']}"
    assert rov["requires_second_review"] is False, (
        f"1.00% is below the 10.0 threshold, so requires_second_review must be false, "
        f"got {rov['requires_second_review']}"
    )


def test_rov_value_change_without_second_review_rejected(api):
    """PRD §3.7: "If `requires_second_review` is true, this branch additionally demands that
    a second, post-delivery `ComplianceReview` on the order's report be in `PASS` or
    `CONDITIONAL`; if no such passing second review exists, the resolution is rejected with
    `ERR_SECOND_REVIEW_REQUIRED`."

    Design: Corner/validations/rov_value_change_without_second_review_rejected
    """
    # requested 560000 vs delivered 500000 = 12% -> requires second review; none performed.
    base = fixtures.setup_rov_under_review(
        requested_value_cents=560000, opinion_of_value_cents=500000, second_review=False,
    )
    resp = api.resolve_reconsideration(
        base["rov"]["id"], factories.resolve_reconsideration_payload(new_value_cents=560000), COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SECOND_REVIEW_REQUIRED.value, 409)


def test_open_rov_requires_order_delivered(api):
    """PRD §3.7: "After an order is delivered, a lender may contest the appraised value."
    PRD §2.10: "**State legality** — the target resource must be in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/rov_requires_order_delivered_pair_rov_order
    """
    # Order in IN_QC (review opened, not finalized) -> not yet DELIVERED.
    base = fixtures.setup_order_in_qc(comparable_count=5)
    resp = api.create_reconsideration(
        base["order"]["id"], factories.reconsideration_payload(520000),
        fixtures.make_lender_user_headers(base["lender"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_open_rov_on_placed_order_rejected(api):
    """PRD §3.7: "After an order is delivered, a lender may contest the appraised value."
    PRD §2.10: "**State legality** — the target resource must be in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/rov_requires_order_delivered_pair_rov_order
    """
    # Order still PLACED (no assignment yet) -> ROV creation depends on DELIVERED state.
    lender = fixtures.create_lender(panel_ids=[], name="L RovPlaced")
    prop = fixtures.create_property(state_code="CA")
    order = fixtures.create_order(lender["id"], prop["id"], as_lender_id=lender["id"])
    resp = api.create_reconsideration(
        order["id"], factories.reconsideration_payload(520000),
        fixtures.make_lender_user_headers(lender["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_complete_blocked_by_open_reconsideration(api):
    """PRD §3.7: "An order cannot be completed while it has an open contest. Completion
    (see §3.8) is blocked while any reconsideration on the order is in `REQUESTED` or
    `UNDER_REVIEW`."

    Design: Corner/endpoints/order_complete_blocked_by_open_rov
    """
    # Delivered order with an ROV still in REQUESTED (not started/resolved).
    base = fixtures.setup_order_delivered_with_value(opinion_of_value_cents=500000)
    validate_success(
        api.create_reconsideration(
            base["order"]["id"], factories.reconsideration_payload(505000),
            fixtures.make_lender_user_headers(base["lender"]["id"]),
        ),
        201,
    )
    v = fixtures.current_order_version(base["order"]["id"])
    resp = api.complete_order(base["order"]["id"], factories.assignment_create_payload(v), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
