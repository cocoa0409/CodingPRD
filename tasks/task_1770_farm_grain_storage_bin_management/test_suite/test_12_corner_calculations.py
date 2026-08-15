"""Corner queue / calculations section — boundary, correct result,
input-set filtering, variant divergence, constants applied."""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    TEST_USERS, make_applicator_headers,
    create_bin, create_lot, create_contract, create_applicator, create_policy,
    set_clock,
    setup_bin_with_lot, setup_dispatched_loadout,
    get_bin, get_lot,
    create_hotspot_reading, get_first_alert_for_bin,
    setup_confirmed_loss_claim,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_lot_payload, create_fumigation_payload, create_contract_payload,
    create_policy_payload, create_claim_payload, create_loadout_payload,
    deliver_payload, create_reading_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_provisional_shrink_zero_at_or_below_standard(api):
    """PRD section 3.1: "When the lot's fill moisture is strictly greater
    than its crop's standard, each point of excess (including fractional
    points) removes 1.35 percent of the original bushels ... When the fill
    moisture is at or below the standard, no shrink is booked and
    `provisional_shrink_bu` is 0.00."
    PRD section 3.1: "whenever the shrink is greater than zero the system
    posts a `ShrinkEvent` of `kind` `PROVISIONAL` against the lot".

    Corn at exactly 15.0 shrinks 0.00; at 14.0 also 0.00 (no negative
    credit). No PROVISIONAL ShrinkEvent is posted when shrink is zero.

    Design: Corner/calculations/provisional_shrink_zero_at_or_below_standard
    """
    b = create_bin(name="BIN-Z")
    lot1 = get_success_data(api_client.create_lot(create_lot_payload(
        b["id"], original_bu=100.00, fill_moisture_pct=15.0), SM))
    lot2 = get_success_data(api_client.create_lot(create_lot_payload(
        b["id"], original_bu=100.00, fill_moisture_pct=14.0), SM))
    assert lot1["provisional_shrink_bu"] == pytest.approx(0.00, abs=1e-9)
    assert lot1["current_bu"] == pytest.approx(100.00, abs=1e-9)
    assert lot2["provisional_shrink_bu"] == pytest.approx(0.00, abs=1e-9)
    events = get_success_data(api_client.list_shrink_events(lot1["id"], SM))
    assert isinstance(events, list) and len(events) == 0


def test_waterfall_fifo_tiebreak_created_at(api):
    """PRD section 3.6: "ordered by `fill_date` ascending with `created_at`
    ascending as the tie-break, never by identifier."
    PRD section 3.6: "each take is subtracted from the lot's `current_bu`,
    added to its `drawn_bu`, and recorded on the load-out's `draws` array
    as a lot-and-bushels entry."

    Two lots share fill_date; the earlier-created lot A is drawn first and
    is the sole entry in draws for a 100.00 settle.

    Design: Corner/calculations/waterfall_fifo_tiebreak_created_at
    """
    b = create_bin(name="BIN-W")
    lot_a = create_lot(b["id"], original_bu=500.00, fill_moisture_pct=15.0,
                       fill_date="2026-08-01T00:00:00Z")
    lot_b = create_lot(b["id"], original_bu=800.00, fill_moisture_pct=15.0,
                       fill_date="2026-08-01T00:00:00Z")
    con = create_contract(contracted_bu=2000.00)
    lo = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=100.00), SM))
    get_success_data(api_client.dispatch_loadout(lo["id"], SM))
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ],
    ), SM))
    conf = get_success_data(api_client.confirm_settlement(lo["id"], SM))
    draws = conf["draws"]
    assert isinstance(draws, list) and len(draws) == 1
    assert draws[0]["lot_id"] == lot_a["id"]
    assert draws[0]["bu"] == pytest.approx(100.00, abs=1e-9)
    a = get_lot(lot_a["id"])
    bl = get_lot(lot_b["id"])
    assert a["current_bu"] == pytest.approx(400.00, abs=1e-9)
    assert a["status"] == "PARTIALLY_DRAWN"
    assert bl["current_bu"] == pytest.approx(800.00, abs=1e-9)
    assert bl["status"] == "STORED"


def test_posture_precedence_lockout_over_alert(api):
    """PRD section 2.7: "Recomputation follows a strict ladder, evaluated in
    this order. First, if any fumigation record on the bin is `ACTIVE` with
    an `application_start` at or before now, the posture is
    `FUMIGATION_LOCKOUT`. Otherwise, if any spoilage alert on the bin is
    `OPEN`, the posture is `ALERT`."

    With both an OPEN alert and an ACTIVE fumigation on the same bin,
    posture is FUMIGATION_LOCKOUT — the fumigation clause outranks the
    alert clause.

    Design: Corner/calculations/posture_precedence_lockout_over_alert
    """
    b, lot = setup_bin_with_lot(bin_name="BIN-PP", original_bu=100.00)
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    # bin is ALERT now
    assert get_bin(b["id"])["posture"] == "ALERT"
    app = create_applicator()
    get_success_data(api_client.create_fumigation(create_fumigation_payload(
        b["id"], app["id"]), make_applicator_headers(app["id"])))
    assert get_bin(b["id"])["posture"] == "FUMIGATION_LOCKOUT"


def test_posture_score_relief_drops_alert_to_sound(api):
    """PRD section 3.2: "whenever two readings disagree about which is
    latest, the system resolves the question by `recorded_at`, never by
    arrival order."
    PRD section 2.7: "if the bin's current `risk_score` is at least 70.00,
    the posture is `ALERT` — a score of exactly 70.00 alerts. Otherwise, if
    the `risk_score` is at least 40.00, the posture is `WATCH` — a score of
    exactly 40.00 watches. Otherwise the posture is `SOUND`."

    First reading lands the score at exactly 70.00 -> ALERT. A second
    reading (later recorded_at) recomputes the score to 20.50 -> SOUND.

    Design: Corner/calculations/posture_score_relief_drops_alert_to_sound
    """
    b = create_bin(name="BIN-SR")
    create_lot(b["id"], original_bu=1000.00, fill_moisture_pct=17.0)
    r1 = get_success_data(api_client.create_reading(create_reading_payload(
        b["id"], recorded_at="2026-08-16T00:00:00Z",
        ambient_temp_f=60.0, cable_temps_f=[70.0, 86.0, 80.0],
        insect_activity=True), SM))
    assert r1["score_after"] == pytest.approx(70.00, abs=1e-9)
    assert get_bin(b["id"])["posture"] == "ALERT"

    r2 = get_success_data(api_client.create_reading(create_reading_payload(
        b["id"], recorded_at="2026-08-17T00:00:00Z",
        ambient_temp_f=70.0, cable_temps_f=[75.0],
        insect_activity=False), SM))
    # temp term 0 (delta 5.0 < 10 allowance); moisture 12.5; staleness
    # 16 days -> 16/30*15 = 8.0; insect 0 -> total 20.5
    assert r2["score_after"] == pytest.approx(20.50, abs=1e-9)
    assert get_bin(b["id"])["posture"] == "SOUND"


def test_fee_tier_boundary_exact_200k(api):
    """PRD section 3.6: "below 200,000 cents the rate is 150 basis points;
    from 200,000 cents up to but not including 500,000 cents the rate is
    100 basis points; at or above 500,000 cents the rate is 75 basis
    points".

    grain_value 200000 exactly -> 100bps -> fee 2000. grain_value 199600
    -> 150bps -> fee 2994.

    Design: Corner/calculations/fee_tier_boundary_exact_200k
    """
    b = create_bin(name="BIN-FT2")
    create_lot(b["id"], original_bu=1500.00, fill_moisture_pct=15.0)
    con1 = create_contract(contracted_bu=2000.00, basis_cents_per_bu=0,
                           futures_ref_cents_per_bu=400)
    con2 = create_contract(contracted_bu=2000.00, basis_cents_per_bu=0,
                           futures_ref_cents_per_bu=400)
    lo1 = get_success_data(api_client.create_loadout(create_loadout_payload(
        con1["id"], b["id"], con1["version"], planned_bu=500.00), SM))
    get_success_data(api_client.dispatch_loadout(lo1["id"], SM))
    get_success_data(api_client.deliver_loadout(lo1["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 500.00, "moisture_pct": 15.0},
        ],
    ), SM))
    lo2 = get_success_data(api_client.create_loadout(create_loadout_payload(
        con2["id"], b["id"], con2["version"], planned_bu=499.00,
        scheduled_start="2026-08-11T08:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
    ), SM))
    get_success_data(api_client.dispatch_loadout(lo2["id"], SM))
    get_success_data(api_client.deliver_loadout(lo2["id"], deliver_payload(
        delivered_at="2026-08-11T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 499.00, "moisture_pct": 15.0},
        ],
    ), SM))

    c1 = get_success_data(api_client.confirm_settlement(lo1["id"], SM))
    assert c1["grain_value_cents"] == 200000
    assert c1["service_fee_cents"] == 2000
    c2 = get_success_data(api_client.confirm_settlement(lo2["id"], SM))
    assert c2["grain_value_cents"] == 199600
    assert c2["service_fee_cents"] == 2994


def test_storage_tier_boundaries_and_invisible_loss(api):
    """PRD section 3.7: "the rate is 3 cents per bushel per month when that
    figure is 3 or less, 4 cents when it is 4 to 6 inclusive, and 5 cents
    when it is 7 or more; the charge is the lot's pre-loss `current_bu`
    multiplied by the rate, rounded half up to whole cents. The charge
    accumulates into the lot's `cumulative_storage_charge_cents`, and its
    `months_assessed` increments by one. Then the month's **invisible
    loss** comes out of the same pre-loss balance: the loss is the pre-loss
    `current_bu` multiplied by 0.20 percent, rounded half up to 2 decimal
    places".

    Lot filled 2026-01-10: 2026-04 (diff 3 -> 3c): charge 2400, loss 1.60;
    2026-05 (diff 4 -> 4c on 798.40): 3194, loss 1.60; 2026-08 (diff 7 ->
    5c on 796.80): 3984, loss 1.59. months_assessed 3, charges 9578,
    invisible loss 4.79, current_bu 795.21; three INVISIBLE_LOSS events, no
    PROVISIONAL.

    Design: Corner/calculations/storage_tier_boundaries_and_invisible_loss
    """
    b = create_bin(name="BIN-ST")
    lot = create_lot(b["id"], original_bu=800.00, fill_moisture_pct=15.0,
                     fill_date="2026-01-10T00:00:00Z")
    a1 = get_success_data(api_client.create_assessment(
        {"period": "2026-04"}, SM))
    assert a1["lots_assessed"] == 1
    assert a1["total_storage_charge_cents"] == 2400
    assert a1["total_invisible_loss_bu"] == pytest.approx(1.60, abs=1e-9)

    a2 = get_success_data(api_client.create_assessment(
        {"period": "2026-05"}, SM))
    assert a2["total_storage_charge_cents"] == 3194
    assert a2["total_invisible_loss_bu"] == pytest.approx(1.60, abs=1e-9)

    a3 = get_success_data(api_client.create_assessment(
        {"period": "2026-08"}, SM))
    assert a3["total_storage_charge_cents"] == 3984
    assert a3["total_invisible_loss_bu"] == pytest.approx(1.59, abs=1e-9)

    lot_now = get_lot(lot["id"])
    assert lot_now["months_assessed"] == 3
    assert lot_now["cumulative_storage_charge_cents"] == 9578
    assert lot_now["cumulative_invisible_loss_bu"] == pytest.approx(
        4.79, abs=1e-9)
    assert lot_now["current_bu"] == pytest.approx(795.21, abs=1e-9)

    events = get_success_data(api_client.list_shrink_events(lot["id"], SM))
    kinds = sorted(e["kind"] for e in events)
    assert kinds == ["INVISIBLE_LOSS", "INVISIBLE_LOSS", "INVISIBLE_LOSS"]


def test_carry_analysis_cash_vs_economic(api):
    """PRD section 3.9: "The `interest_cents` depends on the variant: under
    `CASH` it is zero, excluding financing opportunity cost entirely; under
    `ECONOMIC` it is the lot's `current_bu` multiplied by its
    `reference_price_cents_per_bu`, multiplied by 6 percent per annum,
    multiplied by the whole days between `fill_date` and now (any partial
    day discarded) divided by 365, rounded half up to whole cents. The
    `net_carry_cents` is the basis gain minus the storage already paid,
    minus the projected month charge, minus the interest. The
    `recommendation` is `HOLD` when the net is strictly greater than zero
    and `SELL` when it is zero or negative — an exactly break-even carry
    sells. Because the `ECONOMIC` variant subtracts a financing term that
    `CASH` ignores, identical inputs can legitimately produce `HOLD` under
    one variant and `SELL` under the other."

    Lot 1000.00 @17.0% filled 2026-08-01; assessments 2026-08 and 2026-09
    run; clock 2026-10-01. CASH nets +952 (HOLD); ECONOMIC subtracts 4179
    for -3227 (SELL).

    Design: Corner/calculations/carry_analysis_cash_vs_economic
    """
    b = create_bin(name="BIN-CA")
    lot = create_lot(b["id"], original_bu=1000.00, fill_moisture_pct=17.0,
                     fill_basis_cents=-25, reference_price_cents_per_bu=430)
    get_success_data(api_client.create_assessment({"period": "2026-08"}, SM))
    get_success_data(api_client.create_assessment({"period": "2026-09"}, SM))
    set_clock("2026-10-01T00:00:00Z")

    cash = get_success_data(api_client.get_carry_analysis(
        lot["id"], FO, params={"current_basis_cents": -15, "variant": "CASH"}))
    assert cash["storage_paid_cents"] == 5832
    assert cash["projected_month_charge_cents"] == 2907
    assert cash["basis_gain_cents"] == 9691
    assert cash["interest_cents"] == 0
    assert cash["net_carry_cents"] == 952
    assert cash["recommendation"] == "HOLD"

    econ = get_success_data(api_client.get_carry_analysis(
        lot["id"], FO,
        params={"current_basis_cents": -15, "variant": "ECONOMIC"}))
    assert econ["interest_cents"] == 4179
    assert econ["net_carry_cents"] == -3227
    assert econ["recommendation"] == "SELL"


def test_indemnity_deductible_applied_after_cap(api):
    """PRD section 3.8: "The payable `indemnity_cents` applies the coverage
    cap before the deductible: it is the lesser of the gross indemnity and
    the policy's `remaining_coverage_cents`, minus the `deductible_cents`,
    floored at zero."

    gross 42000 on limit 40000 -> capped to 40000; minus deductible 5000
    -> 35000 (not 37000, not 40000).

    Design: Corner/calculations/indemnity_deductible_applied_after_cap
    """
    b = create_bin(name="BIN-DC")
    create_hotspot_reading(b["id"], recorded_at="2026-08-01T06:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 100.00}, SM))
    pol = create_policy(coverage_limit_cents=40000, deductible_cents=5000,
                        valuation_clause="SPOT")
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM))
    approved = get_success_data(api_client.approve_claim(
        claim["id"], {"spot_price_cents_per_bu": 420}, FO))
    assert approved["gross_indemnity_cents"] == 42000
    assert approved["indemnity_cents"] == 35000


def test_indemnity_contract_avg_empty_pool_falls_back_to_spot(api):
    """PRD section 3.8: "when the pool is empty the clause falls back to
    `SPOT` behavior and the spot price input is then required".

    CONTRACT_AVG policy with no qualifying contracts -> unit_value_cents
    equals the supplied spot price 415.00.

    Design: Corner/calculations/indemnity_contract_avg_empty_pool_falls_back_to_spot
    """
    b = create_bin(name="BIN-EP")
    create_hotspot_reading(b["id"], recorded_at="2026-08-01T06:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 100.00}, SM))
    pol = create_policy(valuation_clause="CONTRACT_AVG")
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM))
    approved = get_success_data(api_client.approve_claim(
        claim["id"], {"spot_price_cents_per_bu": 415}, FO))
    assert approved["unit_value_cents"] == pytest.approx(415.00, abs=1e-9)
    assert approved["gross_indemnity_cents"] == 41500
    assert approved["indemnity_cents"] == 36500


def test_settlement_early_bonus_cutoff(api):
    """PRD section 3.6: "Fourth, `early_bonus_cents` is the `settled_net_bu`
    multiplied by the contract's `early_bonus_cents_per_bu` when the
    contract has a non-null `early_cutoff` and the `delivered_at` is at or
    before that cutoff, and zero otherwise."

    Delivered exactly at cutoff 2026-08-15T00:00:00Z -> bonus 1000, net
    40400. Delivered 1s later -> bonus 0, net 39400.

    Design: Corner/calculations/settlement_early_bonus_cutoff
    """
    b = create_bin(name="BIN-EB")
    create_lot(b["id"], original_bu=500.00, fill_moisture_pct=15.0)
    con1 = create_contract(
        contracted_bu=500.00, basis_cents_per_bu=0,
        futures_ref_cents_per_bu=400,
        early_bonus_cents_per_bu=10, early_cutoff="2026-08-15T00:00:00Z")
    con2 = create_contract(
        contracted_bu=500.00, basis_cents_per_bu=0,
        futures_ref_cents_per_bu=400,
        early_bonus_cents_per_bu=10, early_cutoff="2026-08-15T00:00:00Z")
    lo1 = get_success_data(api_client.create_loadout(create_loadout_payload(
        con1["id"], b["id"], con1["version"], planned_bu=100.00,
        scheduled_start="2026-08-10T08:00:00Z",
        scheduled_end="2026-08-10T12:00:00Z"), SM))
    get_success_data(api_client.dispatch_loadout(lo1["id"], SM))
    get_success_data(api_client.deliver_loadout(lo1["id"], deliver_payload(
        delivered_at="2026-08-15T00:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ]), SM))
    lo2 = get_success_data(api_client.create_loadout(create_loadout_payload(
        con2["id"], b["id"], con2["version"], planned_bu=100.00,
        scheduled_start="2026-08-16T08:00:00Z",
        scheduled_end="2026-08-16T12:00:00Z"), SM))
    get_success_data(api_client.dispatch_loadout(lo2["id"], SM))
    get_success_data(api_client.deliver_loadout(lo2["id"], deliver_payload(
        delivered_at="2026-08-15T00:00:01Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 100.00, "moisture_pct": 15.0},
        ]), SM))

    c1 = get_success_data(api_client.confirm_settlement(lo1["id"], SM))
    assert c1["early_bonus_cents"] == 1000
    assert c1["settlement_net_cents"] == 40400
    c2 = get_success_data(api_client.confirm_settlement(lo2["id"], SM))
    assert c2["early_bonus_cents"] == 0
    assert c2["settlement_net_cents"] == 39400
