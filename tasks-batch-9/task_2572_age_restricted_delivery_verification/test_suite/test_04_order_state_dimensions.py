"""The order's two independent dimensions, and the empty-restriction shortcut."""

from test_helpers import (
    ADMIN_HEADERS,
    assert_cents,
    assert_score_equal,
    assert_units_equal,
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)

DOORSTEP = "2026-08-20T16:00:00Z"
UNRESTRICTED_DOORSTEP = "2026-08-21T04:00:00Z"


def _order_out_for_delivery(api):
    """A restricted order at `PREVERIFIED` with a courier standing at the door."""
    world = fx.build_restricted_world(api, policy_overrides={"unit_scale_factor": 1.15})
    built = fx.build_open_attempt(
        api,
        world,
        quantity=3,
        started_at=DOORSTEP,
        scheduled_delivery_at=DOORSTEP,
        delivery_fee_cents=600,
    )
    built["world"] = world
    return built


def test_01_the_fulfilment_dimension_walks_on_while_compliance_stands_still(api):
    """PRD 3.3: "Submission is where the two state dimensions part company. On
    every successful submission — whatever the compliance outcome — the physical
    dimension advances `CREATED → SUBMITTED` and `submitted_at` is stamped from the
    logical clock, `item_subtotal_cents` is frozen as the sum of `line_total_cents`
    across **all** of the order's lines regardless of their `line_state`, and
    `charged_cents` is frozen as `item_subtotal_cents` plus `delivery_fee_cents`."

    Design: Difficulty/non_linear_state_machine/order_compliance_and_fulfillment_dimensions_move_independently
    """
    built = _order_out_for_delivery(api)
    world = built["world"]
    order_id = built["order"]["id"]

    out_for_delivery = fx.read_order(api, order_id)
    assert out_for_delivery["compliance_state"] == "PREVERIFIED"
    assert out_for_delivery["fulfillment_state"] == "OUT_FOR_DELIVERY"

    fx.record_refusal(api, built["attempt"], world["courier"]["id"], "RECIPIENT_ABSENT")
    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert settled["fulfillment_state"] == "RETURN_COMPLETED"
    assert settled["compliance_state"] == "PREVERIFIED", (
        "nothing in the refusal or the settlement touches the compliance dimension, so "
        f"it is still PREVERIFIED; got {settled['compliance_state']}"
    )
    attempt = fx.read_attempt(api, built["attempt"]["id"])
    assert attempt["state"] == "REFUSED"


def test_02_an_absent_recipient_refusal_opens_no_case_and_moves_no_posture(api):
    """PRD 3.7: "A refusal for `COURIER_FAULT` or `RECIPIENT_ABSENT` therefore
    stops after link one — no case is opened, so no counters change, so no posture
    moves and no orders are held."

    Design: Difficulty/non_linear_state_machine/order_compliance_and_fulfillment_dimensions_move_independently
    """
    built = _order_out_for_delivery(api)
    world = built["world"]

    fx.record_refusal(api, built["attempt"], world["courier"]["id"], "RECIPIENT_ABSENT")

    cases, _meta = validate_paginated(
        api.list_violation_cases(
            ADMIN_HEADERS, {"delivery_attempt_id": built["attempt"]["id"]}
        )
    )
    assert cases == [], (
        "`RECIPIENT_ABSENT` is not one of the four compliance refusal reasons, so the "
        f"automatic case link never fires; got {len(cases)} case rows"
    )
    partner = fx.read_partner(api, world["partner"]["id"])
    assert partner["open_case_count"] == 0
    assert partner["open_critical_case_count"] == 0
    assert partner["posture"] == "OPEN"


def test_03_the_returned_order_still_settles_its_money_in_full(api):
    """PRD 3.7: "Whichever route sent the goods back, a `PlatformAdmin` closes the
    loop with a return settlement, admissible only while the order's
    `fulfillment_state` is `RETURN_IN_TRANSIT` and otherwise reporting
    `ERR_INVALID_ORDER_STATE`."

    Design: Difficulty/non_linear_state_machine/order_compliance_and_fulfillment_dimensions_move_independently
    """
    built = _order_out_for_delivery(api)
    world = built["world"]
    order_id = built["order"]["id"]

    fx.record_refusal(api, built["attempt"], world["courier"]["id"], "RECIPIENT_ABSENT")
    in_transit = fx.read_order(api, order_id)
    assert in_transit["fulfillment_state"] == "RETURN_IN_TRANSIT"

    fx.settle_return(api, order_id)

    settled = fx.read_order(api, order_id)
    assert_cents(settled["refunded_cents"], 18768, "refunded_cents")
    assert settled["fulfillment_state"] == "RETURN_COMPLETED"


# ===========================================================================
# The empty-restriction shortcut: nothing in the box is age restricted
# ===========================================================================
def _unrestricted_order_at_the_door(api):
    """A four-item grocery order whose every line is classified `NONE`.

    The jurisdiction deliberately publishes no policy at all, which proves the
    empty restriction set never reaches policy resolution.
    """
    world = fx.build_unrestricted_world(
        api,
        scheduled_delivery_at=UNRESTRICTED_DOORSTEP,
        quantity=4,
        delivery_fee_cents=0,
    )
    submitted = fx.submit_order(api, world["order"])
    fx.dispatch_order(api, submitted)
    attempt = fx.open_attempt(api, submitted, world["courier"], UNRESTRICTED_DOORSTEP)
    courier_id = world["courier"]["id"]
    fx.add_capture(
        api, attempt, courier_id, "SIGNATURE", f.SIGNATURE_HASH,
        captured_at="2026-08-21T04:05:00Z",
    )
    fx.add_capture(
        api, attempt, courier_id, "PHOTO_HANDOFF", f.PHOTO_HANDOFF_HASH,
        captured_at="2026-08-21T04:06:00Z",
    )
    world["submitted"] = submitted
    world["attempt"] = attempt
    return world


def test_04_an_order_with_no_restricted_line_auto_clears_with_no_policy(api):
    """PRD 3.3: "The first branch is the unrestricted shortcut. When the order's
    `restriction_types` is empty — every line's product is classified `NONE` — the
    compliance dimension moves `DRAFT_UNVERIFIED → AUTO_CLEARED`,
    `provisional_restricted_units` is set to 0.00 and `applied_policy_ids` stays
    empty."

    Design: Difficulty/boundary_precision_check/empty_restriction_set_order_hands_over_with_zero_units_and_no_credit
    """
    world = _unrestricted_order_at_the_door(api)

    submitted = fx.read_order(api, world["submitted"]["id"])
    assert submitted["restriction_types"] == []
    assert submitted["applied_policy_ids"] == []
    assert submitted["compliance_state"] == "AUTO_CLEARED"
    assert_units_equal(
        submitted["provisional_restricted_units"], 0.00, "provisional_restricted_units"
    )
    assert_cents(submitted["item_subtotal_cents"], 2000, "item_subtotal_cents")
    assert_cents(submitted["charged_cents"], 2000, "charged_cents")
    line = validate_success(api.get_order_line(world["line"]["id"], ADMIN_HEADERS))
    assert_units_equal(line["line_restricted_units"], 0.00, "line_restricted_units")


def test_05_the_empty_restriction_edge_hands_over_straight_from_initiated(api):
    """PRD 3.6: "The second path is the empty-restriction edge `INITIATED →
    HANDED_OVER`, available only when the order's `restriction_types` is empty —
    nothing in the box is age-restricted, so no door-side identification is demanded
    at all — and requiring only the `SIGNATURE` and `PHOTO_HANDOFF` captures."

    Design: Difficulty/boundary_precision_check/empty_restriction_set_order_hands_over_with_zero_units_and_no_credit
    """
    world = _unrestricted_order_at_the_door(api)

    response = api.record_handover(
        world["attempt"]["id"],
        f.handover_payload(recipient_name=world["customer"]["full_name"]),
        world["courier_headers"],
    )
    validate_success(response)

    attempt = fx.read_attempt(api, world["attempt"]["id"])
    assert attempt["state"] == "HANDED_OVER"
    assert attempt["id_check_compliant"] is False
    order = fx.read_order(api, world["submitted"]["id"])
    assert order["fulfillment_state"] == "DELIVERED"
    assert_units_equal(order["final_restricted_units"], 0.00, "final_restricted_units")


def test_06_the_empty_restriction_handover_earns_no_compliance_credit(api):
    """PRD 3.6: "On the empty-restriction path, `final_restricted_units` is set to
    0.00, and because `id_check_compliant` remains false the courier's
    `compliant_handover_count` does **not** increase and no compliance credit is
    earned."

    Design: Difficulty/boundary_precision_check/empty_restriction_set_order_hands_over_with_zero_units_and_no_credit
    """
    world = _unrestricted_order_at_the_door(api)
    before = fx.read_courier(api, world["courier"]["id"])
    assert before["compliant_handover_count"] == 0
    assert before["certification_state"] == "CERTIFIED"

    validate_success(
        api.record_handover(
            world["attempt"]["id"],
            f.handover_payload(recipient_name=world["customer"]["full_name"]),
            world["courier_headers"],
        )
    )

    courier = fx.read_courier(api, world["courier"]["id"])
    assert courier["compliant_handover_count"] == 0, (
        "the good-behaviour bonus counts compliant handovers only, and this handover "
        f"left `id_check_compliant` false; got {courier['compliant_handover_count']}"
    )
    assert_score_equal(courier["compliance_score"], 100.00, "compliance_score")
