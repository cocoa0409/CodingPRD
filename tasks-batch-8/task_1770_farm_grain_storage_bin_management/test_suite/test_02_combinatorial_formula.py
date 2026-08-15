"""Difficulty Rule 2: combinatorial formulas.

Covers three instances:
- risk_score_multi_input_threshold (mode a: multi-input threshold)
- shrink_per_ticket_rounding_order (mode b: nested rounding order)
- settlement_fee_tier_evaluation_order (mode c: pinned evaluation order)
"""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    TEST_USERS,
    create_bin, create_lot, create_contract,
    setup_bin_with_lot, setup_bin_lot_contract_loadout, setup_dispatched_loadout,
    get_bin, get_lot, get_loadout,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_reading_payload, deliver_payload, create_loadout_payload,
    create_contract_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: risk_score_multi_input_threshold
# ============================================================

def _setup_two_bins_with_corn_lots():
    bin_h = create_bin(name="BIN-H")
    bin_l = create_bin(name="BIN-L")
    for b in (bin_h, bin_l):
        create_lot(b["id"], original_bu=1000.00, fill_moisture_pct=17.0,
                   grade="GRADE_2")
    return bin_h, bin_l


def test_risk_score_exactly_70_alerts(api):
    """PRD section 3.2: "The temperature term takes the excess of the hottest
    cable over ambient, subtracts a 10.0-degree-Fahrenheit allowance, divides
    the result by 20, clamps it to the range from zero to one inclusive, and
    multiplies by 50. The moisture term ... multiplies by 25. The staleness
    term ... multiplies by 15. ... The insect term adds 10 points when the
    latest reading reports insect activity, and zero otherwise."
    PRD section 2.7: "if the bin's current `risk_score` is at least 70.00,
    the posture is `ALERT` — a score of exactly 70.00 alerts."

    Inputs: T_max 86.0, ambient 60.0 -> temp term ((26 - 10)/20)*50 = 40;
    moisture 17.0 vs std 15.0 -> ((2/4))*25 = 12.5; 15 days staleness
    -> (15/30)*15 = 7.5; insect true -> 10. Total 70.00 exactly.
    Hotspot rule independent: delta 26.0 < 30 and 86.0 < 110 -> false.

    Design: Difficulty/combinatorial_formula/risk_score_multi_input_threshold
    """
    bin_h, _ = _setup_two_bins_with_corn_lots()
    r = get_success_data(api_client.create_reading(create_reading_payload(
        bin_h["id"], recorded_at="2026-08-16T00:00:00Z",
        ambient_temp_f=60.0, cable_temps_f=[70.0, 86.0, 80.0],
        insect_activity=True), SM))
    assert r["score_after"] == pytest.approx(70.00, abs=1e-9)
    assert r["hotspot_triggered"] is False
    b = get_bin(bin_h["id"])
    assert b["posture"] == "ALERT"


def test_risk_score_just_below_70_stays_watch_and_no_alert_entity(api):
    """PRD section 2.7: "Otherwise, if the `risk_score` is at least 40.00,
    the posture is `WATCH` — a score of exactly 40.00 watches. Otherwise the
    posture is `SOUND`."
    PRD section 3.2: "A reading is a **hotspot** when the hottest cable
    exceeds ambient by at least 30.0 degrees Fahrenheit, or when the hottest
    cable reaches at least 110.0 degrees Fahrenheit — the two tests are
    independent of the numeric score."

    T_max 85.9 -> temp term ((25.9 - 10)/20)*50 = 39.75; total 69.75 -> WATCH.
    No hotspot is triggered (delta 25.9 < 30), so no SpoilageAlert row is
    created even though the bin lands at ALERT-eligible scores elsewhere.

    Design: Difficulty/combinatorial_formula/risk_score_multi_input_threshold
    """
    _, bin_l = _setup_two_bins_with_corn_lots()
    r = get_success_data(api_client.create_reading(create_reading_payload(
        bin_l["id"], recorded_at="2026-08-16T00:00:00Z",
        ambient_temp_f=60.0, cable_temps_f=[70.0, 85.9, 80.0],
        insect_activity=True), SM))
    assert r["score_after"] == pytest.approx(69.75, abs=1e-9)
    assert r["hotspot_triggered"] is False
    b = get_bin(bin_l["id"])
    assert b["posture"] == "WATCH"
    # Score-driven posture changes do not raise alert entities
    alerts = get_success_data(api_client.list_alerts(
        SM, params={"bin_id": bin_l["id"]}))
    assert isinstance(alerts, list) and len(alerts) == 0


# ============================================================
# Instance: shrink_per_ticket_rounding_order
# ============================================================

def test_settlement_shrink_rounds_per_ticket_then_sums(api):
    """PRD section 3.6: "**Settlement shrink** is then computed per ticket and
    the rounding order is pinned: for each ticket, in array order, the shrink
    is the ticket's gross bushels multiplied by the excess of its moisture
    over the contract crop's standard moisture — floored at zero, so
    at-or-below-standard moisture shrinks nothing — multiplied by 1.35 and
    divided by 100, rounded half up to 2 decimal places; each ticket's net is
    its gross minus its own shrink, itself rounded half up to 2 decimal
    places. The load-out's `ticket_shrink_bu` is the sum of the per-ticket
    shrinks, its `settled_net_bu` is the sum of the per-ticket nets, and its
    `gross_bu` is the sum of the ticket grosses — rounding each ticket before
    summing is mandatory, because summing first and rounding the load-out
    total produces a different number and is forbidden."

    Two 100.00 bu tickets at 16.5% -> per-ticket shrink 100 * 1.5 * 1.35 / 100
    = 2.025 -> round_half_up 2.03 each, sum 4.06; net per ticket 97.97, sum
    195.94. Sum-then-round of the whole would give 4.05 / 195.95 — forbidden.

    Design: Difficulty/combinatorial_formula/shrink_per_ticket_rounding_order
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-R", original_bu=500.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=195.94,
    )
    d = get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 16.5},
            {"ticket_no": "T2", "gross_bu": 100.00, "moisture_pct": 16.5},
        ],
    ), SM))
    assert d["gross_bu"] == pytest.approx(200.00, abs=1e-9)
    assert d["ticket_shrink_bu"] == pytest.approx(4.06, abs=1e-9)
    assert d["settled_net_bu"] == pytest.approx(195.94, abs=1e-9)


def test_settlement_shrink_at_or_below_standard_shrinks_nothing(api):
    """PRD section 3.6: "the shrink is the ticket's gross bushels multiplied
    by the excess of its moisture over the contract crop's standard moisture
    — floored at zero, so at-or-below-standard moisture shrinks nothing".

    A 200.00 bu ticket at 15.0% (corn standard exactly) -> shrink 0.00 and
    net equals gross. The per-ticket rounding order degenerates cleanly.

    Design: Difficulty/combinatorial_formula/shrink_per_ticket_rounding_order
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-R2", original_bu=500.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=200.00,
    )
    d = get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 200.00, "moisture_pct": 15.0},
        ],
    ), SM))
    assert d["ticket_shrink_bu"] == pytest.approx(0.00, abs=1e-9)
    assert d["settled_net_bu"] == pytest.approx(200.00, abs=1e-9)


# ============================================================
# Instance: settlement_fee_tier_evaluation_order
# ============================================================

def test_fee_tier_keyed_on_pre_fee_grain_value(api):
    """PRD section 3.6: "The money side of confirmation — **settlement
    charges** — has a pinned evaluation order keyed on the pre-fee grain
    value. First, `grain_value_cents` is the load-out's `settled_net_bu`
    multiplied by the contract's `contract_unit_price_cents`, rounded half
    up to whole cents. Second, the service-fee rate is selected by where
    that pre-fee value falls: below 200,000 cents the rate is 150 basis
    points; from 200,000 cents up to but not including 500,000 cents the
    rate is 100 basis points; at or above 500,000 cents the rate is 75
    basis points — a grain value of exactly 500,000 cents takes the
    75-basis-point tier."

    Net 1000.40 bu at unit 500 -> grain_value 500200 -> 75bps tier even
    though post-fee net is below the 500000 floor. Fee 3752, net 496448.

    Design: Difficulty/combinatorial_formula/settlement_fee_tier_evaluation_order
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-F", original_bu=1500.00, fill_moisture_pct=15.0,
        contracted_bu=5000.00, planned_bu=1000.40,
        basis_cents_per_bu=0, futures_ref_cents_per_bu=500,
        early_bonus_cents_per_bu=0,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 1000.40, "moisture_pct": 15.0},
        ],
    ), SM))
    conf = get_success_data(api_client.confirm_settlement(lo["id"], SM))
    assert conf["grain_value_cents"] == 500200
    assert conf["service_fee_cents"] == 3752
    assert conf["early_bonus_cents"] == 0
    assert conf["settlement_net_cents"] == 496448


def test_settlement_net_equals_value_minus_fee_plus_bonus(api):
    """PRD section 3.6: "Fifth, `settlement_net_cents` is the grain value
    minus the service fee plus the early bonus."

    Confirm a small settle: net 100.00 bu at unit 430 -> grain_value 43000,
    fee tier 150bps -> 645, no early bonus -> net 42355.

    Design: Difficulty/combinatorial_formula/settlement_fee_tier_evaluation_order
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-F2", original_bu=500.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=100.00,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    ), SM))
    conf = get_success_data(api_client.confirm_settlement(lo["id"], SM))
    assert conf["grain_value_cents"] == 43000
    assert conf["service_fee_cents"] == 645
    assert conf["early_bonus_cents"] == 0
    assert conf["settlement_net_cents"] == 42355
    assert conf["settlement_net_cents"] == (
        conf["grain_value_cents"] - conf["service_fee_cents"]
        + conf["early_bonus_cents"]
    )
