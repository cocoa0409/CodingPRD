"""Cold-chain accumulation and the three-hop violation cascade (PRD §3.3, §3.6)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_customer,
    create_ordered_lot,
    create_pending_order,
    confirm_order,
    get_lot,
    get_order,
    setup_accepted_lot,
    setup_confirmed_order_on_accepted_lot,
    setup_market_day,
    validate_error,
    validate_success,
)
from test_helpers import BILLING_HEADERS, RECEIVER_HEADERS, SALES_HEADERS


def _post_reading(lot_id, temp_f, duration_minutes, recorded_at="2026-05-01T09:00:00Z"):
    return api_client.create_temperature_reading(
        {"purchase_lot_id": lot_id, "recorded_at": recorded_at,
         "temp_f": temp_f, "duration_minutes": duration_minutes}, RECEIVER_HEADERS)


def test_cumulative_minutes_at_or_below_tolerance_stay_ok(api):
    """PRD §3.3: "the lot's `cold_chain_status` becomes `VIOLATED` only when
    `violation_minutes` becomes strictly greater than the commodity's
    `max_violation_minutes`."
    PRD §3.3: "The lot's `violation_minutes` is the cumulative sum of
    `duration_minutes` across all out-of-range readings on that lot."

    Design: Difficulty/transitive_cascade/cold_chain_violation_three_hop_cascade
    """
    base = setup_confirmed_order_on_accepted_lot(line_quantity=10, line_unit_price=10.00)
    lot_id = base["lot"]["id"]
    reading = validate_success(_post_reading(lot_id, temp_f=70, duration_minutes=50), 201)
    assert reading["out_of_range"] is True, "70F is strictly above the 55F band top"

    lot = get_lot(lot_id)
    assert lot["violation_minutes"] == 50
    assert lot["cold_chain_status"] == "OK", "50 <= 60 tolerance: no flip (strict >)"
    assert lot["reserved_units"] == 10
    assert lot["available_units"] == 90
    order = get_order(base["order"]["id"])
    assert order["status"] == "CONFIRMED"


def test_violation_flip_holds_confirmed_orders_and_releases_reservations(api):
    """PRD §3.3: "Hop two: every `SalesOrder` that has a line on this lot and is
    currently `CONFIRMED` moves to `ON_HOLD` with `hold_reason` set to `COLD_CHAIN`."
    PRD §3.3: "Hop three: each held order releases its line reservations — for every
    line, the lot's `reserved_units` decreases by the line quantity and
    `available_units` is recomputed."

    Design: Difficulty/transitive_cascade/cold_chain_violation_three_hop_cascade
    """
    base = setup_confirmed_order_on_accepted_lot(line_quantity=10, line_unit_price=10.00)
    lot_id = base["lot"]["id"]
    _post_reading(lot_id, temp_f=70, duration_minutes=50,
                  recorded_at="2026-05-01T09:00:00Z")
    second = validate_success(
        _post_reading(lot_id, temp_f=70, duration_minutes=20,
                      recorded_at="2026-05-01T10:00:00Z"), 201)
    assert second["out_of_range"] is True

    lot = get_lot(lot_id)
    assert lot["violation_minutes"] == 70
    assert lot["cold_chain_status"] == "VIOLATED", "70 > 60 tolerance: flip"
    order = get_order(base["order"]["id"])
    assert order["status"] == "ON_HOLD"
    assert order["hold_reason"] == "COLD_CHAIN"
    assert lot["reserved_units"] == 0, "the hold releases the line reservation"
    assert lot["available_units"] == 100


def test_temperature_reading_in_band_not_out_of_range(api):
    """PRD §3.3: "a reading is out of range when `temp_f` is strictly below
    `temp_min_f` or strictly above `temp_max_f`"
    PRD §3.3: "The lot's `violation_minutes` is the cumulative sum of
    `duration_minutes` across all out-of-range readings on that lot."

    Design: Corner/entities/temperature_reading_in_band_not_out_of_range
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=10)
    reading = validate_success(_post_reading(lot["id"], temp_f=50, duration_minutes=30),
                               201)
    assert reading["out_of_range"] is False, "50F sits inside the 45-55F band"
    refreshed = get_lot(lot["id"])
    assert refreshed["violation_minutes"] == 0
    assert refreshed["cold_chain_status"] == "OK"


def test_temperature_reading_is_immutable_without_version(api):
    """PRD §2.4: "The two exceptions are `TemperatureReading` and `Payment`: both are
    append-only ledger-style rows and carry only `id` and `created_at`; they have
    neither `updated_at` nor `version`."

    Design: Corner/entities/temperature_reading_is_immutable_without_version
    """
    base = setup_market_day()
    lot = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                             quantity_units=10)
    reading = validate_success(_post_reading(lot["id"], temp_f=50, duration_minutes=15),
                               201)
    assert isinstance(reading.get("id"), str)
    assert isinstance(reading.get("created_at"), str)
    assert "version" not in reading, "append-only row must not expose version"
    assert "updated_at" not in reading, "append-only row must not expose updated_at"


def test_pick_order_on_violated_lot_returns_cold_chain_violation(api):
    """PRD §3.6: "Picking requires that every line lot's `cold_chain_status` is `OK`;
    a violated lot blocks the pick with `ERR_COLD_CHAIN_VIOLATION`."

    Design: Corner/errors/pick_order_on_violated_lot_returns_cold_chain_violation
    """
    base = setup_accepted_lot(defect_pct=0)
    lot_id = base["lot"]["id"]
    # Violate the lot BEFORE any order references it, so no cascade target exists.
    validate_success(_post_reading(lot_id, temp_f=70, duration_minutes=70), 201)
    assert get_lot(lot_id)["cold_chain_status"] == "VIOLATED"

    customer = create_customer(credit_limit_cents=1000000)
    order = create_pending_order(customer["id"], lot_id, quantity=1, unit_price=10.00)
    confirm_order(order["id"])  # confirm gates on lot status/quantity, not cold chain

    resp = api.pick_order(order["id"], RECEIVER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_COLD_CHAIN_VIOLATION)
    order_after = get_order(order["id"])
    assert order_after["status"] == "CONFIRMED"
    assert get_lot(lot_id)["reserved_units"] == 1, "the rejected pick must not fire"
