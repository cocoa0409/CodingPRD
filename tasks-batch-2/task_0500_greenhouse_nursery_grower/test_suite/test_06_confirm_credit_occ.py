"""Order confirmation: business preconditions, the state-vs-credit priority pair,
and optimistic-concurrency version checks.

Queue A (difficulty) — priority_pair_validation_conflict.
Queue B (corner) — validations (confirm guards), cross_cutting (OCC).
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    set_clock, create_active_variety, create_zone, create_planned_batch, zone_version,
    create_broker, create_draft_order, add_line, confirm_order,
    setup_multi_line_order, setup_published_lot, setup_growing_batch,
)

SC = TEST_USERS["sales_coordinator_headers"]
PT = TEST_USERS["production_tech_headers"]


# ─── A9: state legality pre-empts the credit-limit business rule ──────────
def test_first_confirm_succeeds_within_credit(api):
    """PRD 3.11: "The broker's `open_balance_cents` plus this order's
    `order_total_cents` must be at most the broker's `credit_limit_cents`, or the
    confirm is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_credit_limit
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 500}],
        ship_to_state="OR", credit_limit_cents=110000, confirm=False, cultivar_code="ASTJ1")
    confirmed = confirm_order(api, s["order"]["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["order_total_cents"] == 104900, f"got {confirmed['order_total_cents']}"
    broker = validate_success(api.get_broker(s["broker"]["id"], SC))
    assert broker["open_balance_cents"] == 104900


def test_reconfirm_returns_invalid_state_not_credit(api):
    """PRD 2.8: "After those universal checks, state legality is evaluated: the
    target resource must be in a state from which the requested transition is
    defined, failing which the request is rejected with `ERR_INVALID_STATE`. Only
    then are the operation-specific business rules applied."

    Design: Difficulty/priority_pair_validation_conflict/confirm_invalid_state_beats_credit_limit
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 500}],
        ship_to_state="OR", credit_limit_cents=110000, confirm=False, cultivar_code="ASTJ2")
    confirmed = confirm_order(api, s["order"]["id"])
    # Re-confirm with the current (post-confirm) version: OCC passes, but the order
    # is no longer DRAFT, so state legality must reject before the credit rule.
    resp = api.confirm_order(
        s["order"]["id"], {"expected_order_version": confirmed["version"]}, SC)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)


# ─── B29-B32: confirm / publish business guards ──────────────────────────
def test_confirm_broker_on_hold_rejected(api):
    """PRD 3.11: "The broker must be `ACTIVE`, or it is rejected with
    `ERR_BROKER_ON_HOLD`."

    Design: Corner/validations/confirm_broker_on_hold_rejected
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 50, "started": 50, "unit_price_cents": 300}],
        ship_to_state="OR", confirm=False, cultivar_code="BHR1")
    validate_success(api.hold_broker(s["broker"]["id"], SC))
    ov = validate_success(api.get_order(s["order"]["id"], SC))["version"]
    resp = api.confirm_order(s["order"]["id"], {"expected_order_version": ov}, SC)
    validate_error(resp, "ERR_BROKER_ON_HOLD", expected_status=409)


def test_confirm_empty_order_rejected(api):
    """PRD 3.11: "The order must have at least one line, or it is rejected with
    `ERR_EMPTY_ORDER`."

    Design: Corner/validations/confirm_empty_order_rejected
    """
    broker = create_broker(api, ship_to_state="OR")
    order = create_draft_order(api, broker["id"])
    resp = api.confirm_order(order["id"], {"expected_order_version": order["version"]}, SC)
    validate_error(resp, "ERR_EMPTY_ORDER", expected_status=409)


def test_confirm_insufficient_availability_rejected(api):
    """PRD 3.11: "For each line, the requested `quantity` must not exceed the
    drawn-on entry's `available_quantity`, or the confirm is rejected with
    `ERR_INSUFFICIENT_AVAILABILITY`."

    Design: Corner/validations/confirm_insufficient_availability_rejected
    """
    lot = setup_published_lot(api, unit_price_cents=300, sourced=30, started=30, cultivar_code="AVR1")
    broker = create_broker(api, ship_to_state="OR")
    order = create_draft_order(api, broker["id"])
    add_line(api, order["id"], lot["entry"]["id"], 50)  # 50 > published 30
    ov = validate_success(api.get_order(order["id"], SC))["version"]
    resp = api.confirm_order(order["id"], {"expected_order_version": ov}, SC)
    validate_error(resp, "ERR_INSUFFICIENT_AVAILABILITY", expected_status=409)


def test_publish_non_saleable_batch_rejected(api):
    """PRD 3.8: "The batch must be `SALEABLE`, or the publish is rejected with
    `ERR_BATCH_NOT_SALEABLE`."

    Design: Corner/validations/publish_non_saleable_batch_rejected
    """
    base = setup_growing_batch(api, sourced=30, capacity=100, cultivar_code="NSR1")
    resp = api.create_availability({"batch_id": base["batch"]["id"], "unit_price_cents": 300}, SC)
    validate_error(resp, "ERR_BATCH_NOT_SALEABLE", expected_status=409)


# ─── B41 / B42: optimistic concurrency on the zone / order version ────────
def test_transplant_with_stale_zone_version_rejected(api):
    """PRD 2.9: "If `expected_zone_version` does not match the zone's current
    `version`, the transplant is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_transplant_stale_zone_version_excluded
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    variety = create_active_variety(api, cultivar_code="OCR1", propagation_form="PLUG",
                                    container_footprint_units=1)
    zone = create_zone(api, capacity_units=1000)
    b1 = create_planned_batch(api, variety["id"], zone["id"], sourced_count=100)
    b2 = create_planned_batch(api, variety["id"], zone["id"], sourced_count=100)
    zv_pre = zone_version(api, zone["id"])
    validate_success(api.transplant_batch(
        b1["id"], {"started_count": 100, "expected_zone_version": zv_pre}, PT))
    resp = api.transplant_batch(
        b2["id"], {"started_count": 100, "expected_zone_version": zv_pre}, PT)
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)


def test_confirm_with_current_version_succeeds_and_increments(api):
    """PRD 3.11: "The broker's `open_balance_cents` is increased by the order's
    `order_total_cents` — a cascade onto the broker — and the order's `version` is
    incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_correct_version_succeeds_and_increments
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 50, "started": 50, "unit_price_cents": 300}],
        ship_to_state="OR", confirm=False, cultivar_code="CVR1")
    ov = validate_success(api.get_order(s["order"]["id"], SC))["version"]
    data = validate_success(api.confirm_order(s["order"]["id"], {"expected_order_version": ov}, SC))
    assert data["status"] == "CONFIRMED"
    assert data["version"] == ov + 1, f"version must increment to {ov + 1}, got {data['version']}"
