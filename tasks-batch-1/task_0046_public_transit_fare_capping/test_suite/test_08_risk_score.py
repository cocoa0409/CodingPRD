"""Rider behavioral risk score: the gross vs trailing_week divergence and the
weighted-signal composition.

Covers Difficulty queue (A) rule dual_variant_calc (the risk-score instance).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_tap_payload,
    TEST_USERS, make_rider_headers,
    set_clock, make_fare_product, register_rider, add_funding_source, load_balance,
    open_week, record_tap,
    ApiErrorId,
)


def _build_two_reject_world():
    """A rider whose default source holds 200 cents (< 500) with two REJECTED taps:
    one old (2026-06-02) and one recent (2026-06-16). Clock ends at 2026-06-20.
    Each settle attempt rejects because 200 < the 300 base fare. Returns rider id.
    """
    make_fare_product(zone_code="ZONEX", base_fare_cents=300, daily_cap_cents=500,
                      weekly_cap_cents=2500)
    set_clock("2026-06-02T00:00:00Z")
    rider = register_rider(home_zone_code="ZONEX", email="r2@x.com")
    fs = add_funding_source(rider["id"])
    fs = load_balance(rider["id"], fs["id"], 200)
    w_old = open_week(rider["id"], week_start_date="2026-06-01", zone_code="ZONEX")
    t_old = record_tap(rider["id"], w_old["id"], fs["id"], "2026-06-02T08:00:00Z")
    # Settle rejects (200 < 300) — persisted as REJECTED.
    api_client.settle_tap(t_old["id"], TEST_USERS["payment_gateway_headers"])
    set_clock("2026-06-16T00:00:00Z")
    w_new = open_week(rider["id"], week_start_date="2026-06-15", zone_code="ZONEX")
    t_new = record_tap(rider["id"], w_new["id"], fs["id"], "2026-06-16T08:00:00Z")
    api_client.settle_tap(t_new["id"], TEST_USERS["payment_gateway_headers"])
    set_clock("2026-06-20T00:00:00Z")
    return rider["id"]


def test_risk_gross_vs_trailing_week_diverge(api):
    """PRD §3.2: "each tap recorded in `REJECTED` status (an insufficient-funds
    rejection) contributes 15 points ... and a low-balance flag contributes 20
    points. The low-balance flag is 1 when the rider's default active funding source
    holds a `prepaid_balance_cents` below 500".
    PRD §3.2: "In `gross` mode it counts every rejected and every reversed tap ever
    recorded for the rider. In `trailing_week` mode ... it counts only rejected and
    reversed taps whose `tapped_at` falls within the seven days ending at the current
    clock instant, which produces a different number than `gross` whenever older
    incidents exist."

    Design: Difficulty/dual_variant_calc/rider_risk_gross_vs_trailing_week_diverge
    """
    rider_id = _build_two_reject_world()
    gross = validate_success(api.get_rider_risk(
        rider_id, TEST_USERS["fare_admin_headers"], params={"mode": "gross"}), 200)
    tw = validate_success(api.get_rider_risk(
        rider_id, TEST_USERS["fare_admin_headers"], params={"mode": "trailing_week"}), 200)
    # gross: 2 rejects * 15 + low-balance 20 == 50.
    assert gross["rider_risk_score"] == 50
    # trailing_week: 1 reject in window (06-16) * 15 + low-balance 20 == 35.
    assert tw["rider_risk_score"] == 35
    assert gross["rider_risk_score"] != tw["rider_risk_score"]


def test_risk_gross_mode_counts_all_rejects(api):
    """PRD §3.2: "In `gross` mode it counts every rejected and every reversed tap
    ever recorded for the rider."
    PRD §3.2: "The response reports the `rider_id`, the computed `rider_risk_score`,
    and the `mode` that was applied."

    Design: Difficulty/dual_variant_calc/rider_risk_gross_vs_trailing_week_diverge
    """
    rider_id = _build_two_reject_world()
    gross = validate_success(api.get_rider_risk(
        rider_id, TEST_USERS["fare_admin_headers"], params={"mode": "gross"}), 200)
    assert gross["rider_id"] == rider_id
    assert gross["mode"] == "gross"
    assert gross["rider_risk_score"] == 50
