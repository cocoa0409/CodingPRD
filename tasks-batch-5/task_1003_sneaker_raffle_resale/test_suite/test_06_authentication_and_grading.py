"""Consignment intake, grading, inspection fork, scheduling overlap, and the
order's parallel status axes."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    setup_fixed_order, setup_order_through_authentication,
    create_consignment, create_authenticator, receive_item, schedule_item, complete_fail,
    make_authenticator_headers, make_buyer_headers, make_seller_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------- #
# grade_score declared vs authenticated (Difficulty)
# --------------------------------------------------------------------------- #
def test_declared_grade_score_computed_at_intake(api):
    """PRD §3.6: "Multiply the condition value by 0.6, the box value by 0.25, and
    the accessories value by 0.15, sum the three products, and round that sum half
    up to four decimal places. The `declared_grade_score` uses the declared
    fields; the `authenticated_grade_score` computed later uses the
    authenticator-verified fields."

    Design: Difficulty/dual_variant_calc/consignment_grade_declared_vs_authenticated
    """
    ctx = setup_fixed_order(api, ask_price_cents=25000, size="9")
    ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"],
                            declared_condition="DEADSTOCK", declared_box="PERFECT", declared_acc=True)
    # 0.6*1.0 + 0.25*1.0 + 0.15*1.0 = 1.0
    assert ci["declared_grade_score"] == 1.0


def test_authenticated_grade_score_diverges_from_declared(api):
    """PRD §3.6: "A condition value is drawn from the grade — 1.0 for `DEADSTOCK`,
    0.85 for `VNDS`, 0.6 for `USED` — a box value is drawn from the box grade —
    1.0 for `PERFECT`, 0.8 for `GOOD`, 0.5 for `DAMAGED`, 0.0 for `MISSING` — and
    an accessories value is 1.0 when accessories are complete and 0.0 otherwise."

    Design: Difficulty/dual_variant_calc/consignment_grade_declared_vs_authenticated
    """
    ctx = setup_order_through_authentication(
        api, ask_price_cents=25000, size="9",
        auth_condition="USED", auth_box="GOOD", auth_acc=True,
    )
    ci = ctx["consignment"]
    assert ci["declared_grade_score"] == 1.0
    # 0.6*0.6 + 0.25*0.8 + 0.15*1.0 = 0.36 + 0.20 + 0.15 = 0.71
    assert ci["authenticated_grade_score"] == 0.71


# --------------------------------------------------------------------------- #
# Order parallel axes on receive (Difficulty)
# --------------------------------------------------------------------------- #
def _fixed_order_received(api):
    ctx = setup_fixed_order(api, ask_price_cents=30000, size="11")
    auth = create_authenticator(api)
    ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"])
    receive_item(api, ci["id"], auth["id"])
    order = get_success_data(api.get_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])))
    return order


def test_receive_advances_fulfillment_axis(api):
    """PRD §3.6: "advances the linked order's `fulfillment_status` from
    `AWAITING_SHIPMENT` to `IN_AUTHENTICATION` (the order's `payment_status` stays
    `AUTHORIZED`, since the two axes move independently)".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_vs_fulfillment_axes
    """
    order = _fixed_order_received(api)
    assert order["fulfillment_status"] == "IN_AUTHENTICATION"


def test_receive_leaves_payment_axis_authorized(api):
    """PRD §3.6: "advances the linked order's `fulfillment_status` from
    `AWAITING_SHIPMENT` to `IN_AUTHENTICATION` (the order's `payment_status` stays
    `AUTHORIZED`, since the two axes move independently)".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_vs_fulfillment_axes
    """
    order = _fixed_order_received(api)
    assert order["payment_status"] == "AUTHORIZED"


# --------------------------------------------------------------------------- #
# Inspection FAIL fork (Difficulty)
# --------------------------------------------------------------------------- #
def _fixed_order_failed_inspection(api):
    ctx = setup_fixed_order(api, ask_price_cents=30000, size="9.5")
    auth = create_authenticator(api)
    ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"])
    receive_item(api, ci["id"], auth["id"])
    schedule_item(api, ci["id"], auth["id"], "2026-07-01T11:00:00Z", "2026-07-01T11:30:00Z")
    ci = complete_fail(api, ci["id"], auth["id"])
    order = get_success_data(api.get_order(ctx["order"]["id"], make_buyer_headers(ctx["buyer"]["id"])))
    seller = get_success_data(api.get_account(ctx["seller"]["id"], ADMIN))
    return ci, order, seller


def test_inspection_fail_rejects_item_and_voids_order(api):
    """PRD §3.6: "When the `inspection_result` is `FAIL`, the item moves from
    `UNDER_AUTHENTICATION` to `REJECTED`, and the divergent cascade differs sharply
    from the pass branch: the linked order's `fulfillment_status` is set to
    `FAILED_AUTH` and its `payment_status` is set to `VOIDED`, and the shipping
    seller's `Account.strikes` counter is incremented by one."

    Design: Difficulty/non_linear_state_machine/consignment_fork_authenticated_vs_rejected
    """
    ci, order, _seller = _fixed_order_failed_inspection(api)
    assert ci["status"] == "REJECTED"
    assert order["fulfillment_status"] == "FAILED_AUTH"
    assert order["payment_status"] == "VOIDED"


def test_inspection_fail_increments_seller_strikes(api):
    """PRD §3.6: "the shipping seller's `Account.strikes` counter is incremented
    by one."

    Design: Difficulty/non_linear_state_machine/consignment_fork_authenticated_vs_rejected
    """
    _ci, _order, seller = _fixed_order_failed_inspection(api)
    assert seller["strikes"] == 1


# --------------------------------------------------------------------------- #
# Ship gated on linked item AUTHENTICATED (Difficulty)
# --------------------------------------------------------------------------- #
def test_ship_rejected_while_item_under_authentication(api):
    """PRD §3.7: "For a resale order the order must be in fulfillment status
    `AUTHENTICATED` and its linked consignment item must have reached
    `AUTHENTICATED`; if the linked item is not authenticated the shipment is
    rejected with `ERR_ITEM_NOT_AUTHENTICATED`."

    Design: Difficulty/cross_entity_state_dependency/ship_gated_on_consignment_authenticated
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    auth = create_authenticator(api)
    ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"])
    receive_item(api, ci["id"], auth["id"])
    schedule_item(api, ci["id"], auth["id"], "2026-07-01T14:00:00Z", "2026-07-01T14:30:00Z")
    resp = api.ship_order(ctx["order"]["id"], ADMIN)  # item still UNDER_AUTHENTICATION
    validate_error(resp, ApiErrorId.ERR_ITEM_NOT_AUTHENTICATED.value)


def test_ship_succeeds_once_item_authenticated(api):
    """PRD §3.7: "Shipping advances the order's `fulfillment_status` to
    `SHIPPED_TO_BUYER` and stamps a `dispute_deadline` equal to the current
    logical clock plus a fixed dispute window of 3 days."

    Design: Difficulty/cross_entity_state_dependency/ship_gated_on_consignment_authenticated
    """
    ctx = setup_order_through_authentication(api, ask_price_cents=30000)
    resp = api.ship_order(ctx["order"]["id"], ADMIN)
    order = validate_success(resp, expected_status=200)
    assert order["fulfillment_status"] == "SHIPPED_TO_BUYER"


# --------------------------------------------------------------------------- #
# Authenticator half-open slot overlap (Difficulty)
# --------------------------------------------------------------------------- #
def _two_received_items_one_authenticator(api):
    auth = create_authenticator(api)
    items = []
    for size in ("9", "9.5"):
        ctx = setup_fixed_order(api, ask_price_cents=5000, size=size)
        ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"])
        receive_item(api, ci["id"], auth["id"])
        items.append(ci)
    return auth, items[0], items[1]


def test_overlapping_inspection_slot_rejected(api):
    """PRD §3.6: "The requested slot is a half-open interval and must not overlap
    any other `UNDER_AUTHENTICATION` item's slot on the same authenticator;
    back-to-back slots that merely touch at an endpoint are allowed, but a genuine
    overlap is rejected with `ERR_AUTHENTICATOR_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/authenticator_slot_half_open_overlap_rejected
    """
    auth, ci1, ci2 = _two_received_items_one_authenticator(api)
    schedule_item(api, ci1["id"], auth["id"], "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z")
    resp = api.schedule_inspection(ci2["id"], {
        "authenticator_id": auth["id"],
        "inspection_window_start": "2026-07-01T09:15:00Z",
        "inspection_window_end": "2026-07-01T09:45:00Z",
    }, make_authenticator_headers(auth["id"]))
    validate_error(resp, ApiErrorId.ERR_AUTHENTICATOR_UNAVAILABLE.value)


def test_back_to_back_inspection_slot_allowed(api):
    """PRD §3.6: "back-to-back slots that merely touch at an endpoint are allowed,
    but a genuine overlap is rejected with `ERR_AUTHENTICATOR_UNAVAILABLE`."

    Design: Difficulty/resource_temporal_overlap/authenticator_slot_half_open_overlap_rejected
    """
    auth, ci1, ci2 = _two_received_items_one_authenticator(api)
    schedule_item(api, ci1["id"], auth["id"], "2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z")
    resp = api.schedule_inspection(ci2["id"], {
        "authenticator_id": auth["id"],
        "inspection_window_start": "2026-07-01T09:30:00Z",
        "inspection_window_end": "2026-07-01T10:00:00Z",
    }, make_authenticator_headers(auth["id"]))
    item = validate_success(resp, expected_status=200)
    assert item["status"] == "UNDER_AUTHENTICATION"


# --------------------------------------------------------------------------- #
# Schedule before receive (Corner)
# --------------------------------------------------------------------------- #
def test_schedule_before_receive_rejected(api):
    """PRD §3.6: "An `Authenticator` walks each item through a short lifecycle,
    and each transition must start from the correct status or it is rejected with
    `ERR_CONSIGNMENT_NOT_RECEIVED`."

    Design: Corner/state_machines/schedule_before_receive_returns_not_received
    """
    ctx = setup_fixed_order(api, ask_price_cents=30000)
    auth = create_authenticator(api)
    ci = create_consignment(api, ctx["order"]["id"], ctx["seller"]["id"], ctx["sku"]["id"])
    resp = api.schedule_inspection(ci["id"], {
        "authenticator_id": auth["id"],
        "inspection_window_start": "2026-07-01T09:00:00Z",
        "inspection_window_end": "2026-07-01T09:30:00Z",
    }, make_authenticator_headers(auth["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSIGNMENT_NOT_RECEIVED.value)
