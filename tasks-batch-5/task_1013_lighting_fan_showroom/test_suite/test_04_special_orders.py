"""Special orders: supplier lead-time projection and cross-entity confirm guard (PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_fixture, create_order, add_line, quote, confirm,
    create_special_order, set_clock,
)

SM = TEST_USERS["sm_headers"]


def _confirmed_order_with_line(api, sku_base, base_price_cents=9000):
    fx = create_fixture(api, sku_base=sku_base, category="PENDANT",
                        base_price_cents=base_price_cents, base_wattage=40, special_order_only=True)
    order = create_order(api, customer_name="SO")
    line = add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    confirm(api, order["id"])
    return order, line


def test_special_order_confirm_projects_estimated_ready_date(api):
    """PRD §3.5: "Confirmation moves the special order to `CONFIRMED`, stamps `confirmed_at`
    with the current clock, and projects an `estimated_ready_date` equal to `confirmed_at`
    plus the promised `supplier_lead_days`."
    PRD §3.10: "At server startup the clock reads exactly `2026-07-01T00:00:00Z`".

    Design: Difficulty/dual_variant_calc/special_order_estimated_vs_actual_ready
    """
    order, line = _confirmed_order_with_line(api, "F-SO", base_price_cents=50000)
    so = create_special_order(api, order["id"], line["id"], supplier_lead_days=30)
    confirmed = validate_success(api.confirm_special_order(so["id"], SM), 200)
    assert confirmed["estimated_ready_date"] == "2026-07-31T00:00:00.000Z"


def test_special_order_complete_records_actual_and_variance(api):
    """PRD §3.5: "Completing a confirmed special order moves it to `READY`, stamps
    `actual_ready_date` with the current clock, and computes `variance_days` as the whole-day
    floor of the difference between `actual_ready_date` and the projected `estimated_ready_date`
    — a positive variance meaning the supplier ran late and a negative one meaning early."

    Design: Difficulty/dual_variant_calc/special_order_estimated_vs_actual_ready
    """
    order, line = _confirmed_order_with_line(api, "F-SO2", base_price_cents=50000)
    so = create_special_order(api, order["id"], line["id"], supplier_lead_days=30)
    api.confirm_special_order(so["id"], SM)  # estimated 2026-07-31
    set_clock(api, "2026-08-05T00:00:00Z")
    completed = validate_success(api.complete_special_order(so["id"], SM), 200)
    assert completed["actual_ready_date"] == "2026-08-05T00:00:00.000Z"
    assert completed["variance_days"] == 5


def test_special_order_confirm_requires_parent_order_confirmed(api):
    """PRD §3.5: "A fulfillment coordinator confirms it, which is allowed only while it is
    `REQUESTED` and only when the parent order named by its `order_id` has `fulfillment_status`
    of `CONFIRMED`; a parent that is not confirmed causes rejection with `ERR_ORDER_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/special_order_confirm_requires_order_confirmed
    """
    fx = create_fixture(api, sku_base="F-CE", category="PENDANT", base_price_cents=9000,
                        base_wattage=40, special_order_only=True)
    order = create_order(api, customer_name="CE")
    line = add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])  # order left QUOTED, never confirmed
    so = create_special_order(api, order["id"], line["id"], supplier_lead_days=20)
    resp = api.confirm_special_order(so["id"], SM)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONFIRMED.value)


def test_special_order_confirm_rejected_leaves_it_requested(api):
    """PRD §3.5: "A fulfillment coordinator confirms it, which is allowed only while it is
    `REQUESTED` and only when the parent order named by its `order_id` has `fulfillment_status`
    of `CONFIRMED`; a parent that is not confirmed causes rejection with `ERR_ORDER_NOT_CONFIRMED`."

    Design: Difficulty/cross_entity_state_dependency/special_order_confirm_requires_order_confirmed
    """
    fx = create_fixture(api, sku_base="F-CE2", category="PENDANT", base_price_cents=9000,
                        base_wattage=40, special_order_only=True)
    order = create_order(api, customer_name="CE")
    line = add_line(api, order["id"], fx["id"], quantity=1)
    quote(api, order["id"])
    so = create_special_order(api, order["id"], line["id"], supplier_lead_days=20)
    api.confirm_special_order(so["id"], SM)
    data = validate_success(api.get_special_order(so["id"], SM), 200)
    assert data["status"] == "REQUESTED"


def test_complete_special_order_from_requested_returns_invalid_state(api):
    """PRD §3.5: "Completing a confirmed special order moves it to `READY`, stamps
    `actual_ready_date` with the current clock".
    PRD §2.8: "the generic "resource is not in a state that permits this transition" guard
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/special_order_complete_from_requested_returns_invalid_state
    """
    order, line = _confirmed_order_with_line(api, "F-SR", base_price_cents=9000)
    so = create_special_order(api, order["id"], line["id"], supplier_lead_days=15)
    resp = api.complete_special_order(so["id"], SM)  # still REQUESTED, never confirmed
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
