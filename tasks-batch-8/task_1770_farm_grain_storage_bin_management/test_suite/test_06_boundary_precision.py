"""Difficulty Rule 6: boundary-precision checks.

Covers:
- rei_boundary_exact_72h (PHOSPHINE REI elapsed-time boundary)
- fulfillment_ratio_boundary_98pct (98% bushel-comparison boundary)
"""
import pytest

from test_helpers import (
    get_success_data, validate_error, validate_success,
    ApiErrorId,
    TEST_USERS, make_applicator_headers,
    create_bin, create_lot, create_contract, set_clock,
    setup_active_fumigation, setup_dispatched_loadout,
    get_bin, get_contract, get_fumigation,
    assert_instant_equal,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_loadout_payload, deliver_payload,
    create_fumigation_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: rei_boundary_exact_72h
# ============================================================

def test_phosphine_clear_one_second_before_rei_fails(api):
    """PRD section 3.3: "clearance before the restricted-entry interval has
    elapsed is rejected with `ERR_REI_NOT_ELAPSED` — the logical clock must
    be at or after `lockout_until`, and a clearance arriving exactly at
    `lockout_until` passes."
    PRD section 3.3: "`PHOSPHINE`, which carries a 72-hour restricted-entry
    interval".

    At 2026-08-03T23:59:59Z (one second before lockout_until
    2026-08-04T00:00:00Z), clearing fails with ERR_REI_NOT_ELAPSED.

    Design: Difficulty/boundary_precision_check/rei_boundary_exact_72h
    """
    b, app_a, fum = setup_active_fumigation(
        bin_name="BIN-T", product="PHOSPHINE",
        application_start="2026-08-01T00:00:00Z",
        application_end="2026-08-01T06:00:00Z",
    )
    app_b = get_success_data(api_client.create_applicator(
        {"name": "Bob B", "license_no": "LIC-B",
         "cert_expires_at": "2027-06-01T00:00:00Z"}, SM))
    # Confirm pinned lockout_until = application_start + 72h
    fum_now = get_fumigation(fum["id"])
    assert_instant_equal(fum_now["lockout_until"], "2026-08-04T00:00:00Z")

    set_clock("2026-08-03T23:59:59Z")
    resp = api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"]))
    validate_error(resp, ApiErrorId.ERR_REI_NOT_ELAPSED, expected_status=409)


def test_phosphine_clear_at_exactly_rei_succeeds(api):
    """PRD section 3.3: "the logical clock must be at or after
    `lockout_until`, and a clearance arriving exactly at `lockout_until`
    passes."
    PRD section 3.3: "Clearing stamps `cleared_at` with now, records the
    caller as `cleared_by_applicator_id`, moves the record to `CLEARED`, and
    recomputes the bin's posture; when the lockout lifts the bin to `SOUND`
    or `WATCH`, the release cascade runs."

    At exactly 2026-08-04T00:00:00Z clearing succeeds; posture returns to
    SOUND (no alerts, no contributing lots).

    Design: Difficulty/boundary_precision_check/rei_boundary_exact_72h
    """
    b, app_a, fum = setup_active_fumigation(
        bin_name="BIN-T2", product="PHOSPHINE",
        application_start="2026-08-01T00:00:00Z",
        application_end="2026-08-01T06:00:00Z",
    )
    app_b = get_success_data(api_client.create_applicator(
        {"name": "Bob B", "license_no": "LIC-B",
         "cert_expires_at": "2027-06-01T00:00:00Z"}, SM))
    set_clock("2026-08-04T00:00:00Z")
    resp = api_client.clear_fumigation(
        fum["id"], make_applicator_headers(app_b["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "CLEARED"
    assert_instant_equal(data["cleared_at"], "2026-08-04T00:00:00Z")
    assert data["cleared_by_applicator_id"] == app_b["id"]
    assert get_bin(b["id"])["posture"] == "SOUND"


# ============================================================
# Instance: fulfillment_ratio_boundary_98pct
# ============================================================

def _setup_two_contracts_each_10000():
    """Bin cap 30000, two corn lots (9800.00 and 9799.99) and two 10000-bu
    contracts; two delivered loadouts (9800.00 and 9799.99 net)."""
    b = create_bin(name="BIN-98", capacity_bu=30000.00)
    lot_a = create_lot(b["id"], original_bu=9800.00, fill_moisture_pct=15.0)
    lot_b = create_lot(b["id"], original_bu=9799.99, fill_moisture_pct=15.0)
    con_a = create_contract(contracted_bu=10000.00)
    con_b = create_contract(contracted_bu=10000.00)
    lo_a = get_success_data(api_client.create_loadout(create_loadout_payload(
        con_a["id"], b["id"], con_a["version"], planned_bu=9800.00,
        scheduled_start="2026-08-10T08:00:00Z",
        scheduled_end="2026-08-10T12:00:00Z",
    ), SM))
    get_success_data(api_client.dispatch_loadout(lo_a["id"], SM))
    get_success_data(api_client.deliver_loadout(lo_a["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 9800.00, "moisture_pct": 15.0},
        ],
    ), SM))
    lo_b = get_success_data(api_client.create_loadout(create_loadout_payload(
        con_b["id"], b["id"], con_b["version"], planned_bu=9799.99,
        scheduled_start="2026-08-11T08:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
    ), SM))
    get_success_data(api_client.dispatch_loadout(lo_b["id"], SM))
    get_success_data(api_client.deliver_loadout(lo_b["id"], deliver_payload(
        delivered_at="2026-08-11T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 9799.99, "moisture_pct": 15.0},
        ],
    ), SM))
    return b, lot_a, lot_b, con_a, con_b, lo_a, lo_b


def test_delivered_exactly_9800_of_10000_fulfills(api):
    """PRD section 3.6: "Fulfillment is judged in bushels, not ratio points:
    when the contract's `delivered_bu` reaches at least 98 percent of its
    `contracted_bu` — exactly 98.00 percent fulfills, 97.99 percent does not
    — the contract moves from `DELIVERING` to `FULFILLED`".

    delivered_bu 9800.00 >= 10000.00 * 0.98 = 9800.00 -> FULFILLED.

    Design: Difficulty/boundary_precision_check/fulfillment_ratio_boundary_98pct
    """
    b, lot_a, lot_b, con_a, con_b, lo_a, lo_b = _setup_two_contracts_each_10000()
    get_success_data(api_client.confirm_settlement(lo_a["id"], SM))
    got = get_contract(con_a["id"])
    assert got["delivered_bu"] == pytest.approx(9800.00, abs=1e-9)
    assert got["status"] == "FULFILLED"


def test_delivered_9799_99_of_10000_stays_delivering(api):
    """PRD section 3.6: "Fulfillment is judged in bushels, not ratio points:
    when the contract's `delivered_bu` reaches at least 98 percent of its
    `contracted_bu` — exactly 98.00 percent fulfills, 97.99 percent does not
    — the contract moves from `DELIVERING` to `FULFILLED`, with the
    `fulfillment_ratio` maintained at 4 decimal places as delivered divided
    by contracted."

    delivered_bu 9799.99 < 9800.00 -> stays DELIVERING, even though the 4dp
    ratio display 0.9800 matches the fulfilling contract's display.

    Design: Difficulty/boundary_precision_check/fulfillment_ratio_boundary_98pct
    """
    b, lot_a, lot_b, con_a, con_b, lo_a, lo_b = _setup_two_contracts_each_10000()
    get_success_data(api_client.confirm_settlement(lo_b["id"], SM))
    got = get_contract(con_b["id"])
    assert got["delivered_bu"] == pytest.approx(9799.99, abs=1e-9)
    assert got["status"] == "DELIVERING"
    # 4dp display rounds to 0.9800 — identical to the fulfilling case —
    # but the bushel comparison is authoritative
    assert got["fulfillment_ratio"] == pytest.approx(0.9800, abs=1e-9)
