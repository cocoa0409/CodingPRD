"""Difficulty Rule 1: dual-variant calculations — shrink and indemnity.

Each instance carries two tests (per-instance coverage >= 2).
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_farm_owner_headers,
    create_bin, create_lot, create_contract, set_clock,
    setup_bin_lot_contract_loadout,
    get_lot, get_contract, get_loadout,
    create_hotspot_reading, get_first_alert_for_bin,
    setup_confirmed_loss_claim,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_loadout_payload, deliver_payload, create_contract_payload,
    create_policy_payload, create_claim_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: shrink_provisional_vs_settlement_divergence
# ============================================================

def test_provisional_shrink_computed_once_at_fill(api):
    """PRD section 3.1: "When the lot's fill moisture is strictly greater than
    its crop's standard, each point of excess (including fractional points)
    removes 1.35 percent of the original bushels: the shrink is the
    `original_bu` multiplied by the excess points multiplied by 1.35 and
    divided by 100, rounded half up to 2 decimal places, and recorded on the
    lot as `provisional_shrink_bu`."

    For a 1000.00 bu corn lot at 17.0% vs standard 15.0, the provisional
    variant yields 1000 * 2.0 * 1.35 / 100 = 27.00 bu and book 973.00.

    Design: Difficulty/dual_variant_calc/shrink_provisional_vs_settlement_divergence
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-A", original_bu=1000.00, fill_moisture_pct=17.0,
        contracted_bu=2000.00, planned_bu=800.00,
    )
    lot_after = get_lot(lot["id"])
    assert lot_after["provisional_shrink_bu"] == pytest.approx(27.00, abs=1e-9)
    assert lot_after["current_bu"] == pytest.approx(973.00, abs=1e-9)
    assert lot_after["status"] == "STORED"


def test_settlement_shrink_diverges_from_provisional(api):
    """PRD section 3.6: "for each ticket, in array order, the shrink is the
    ticket's gross bushels multiplied by the excess of its moisture over the
    contract crop's standard moisture — floored at zero, so at-or-below-standard
    moisture shrinks nothing — multiplied by 1.35 and divided by 100, rounded
    half up to 2 decimal places; each ticket's net is its gross minus its own
    shrink, itself rounded half up to 2 decimal places."

    Two 400.00 bu tickets at 16.5% vs corn std 15.0 give per-ticket shrink
    400 * 1.5 * 1.35/100 = 8.10 -> total 16.20, net 783.80. The lot's
    provisional shrink for the same physical grain was 27.00, and the
    waterfall debit of 783.80 from 973.00 leaves 189.20 — proving the
    variants diverge.

    Design: Difficulty/dual_variant_calc/shrink_provisional_vs_settlement_divergence
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-A", original_bu=1000.00, fill_moisture_pct=17.0,
        contracted_bu=2000.00, planned_bu=800.00,
    )
    get_success_data(api.dispatch_loadout(lo["id"], SM))
    d = get_success_data(api.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 400.00, "moisture_pct": 16.5},
            {"ticket_no": "T2", "gross_bu": 400.00, "moisture_pct": 16.5},
        ],
    ), SM))
    assert d["ticket_shrink_bu"] == pytest.approx(16.20, abs=1e-9)
    assert d["settled_net_bu"] == pytest.approx(783.80, abs=1e-9)

    get_success_data(api.confirm_settlement(lo["id"], SM))
    lot_after = get_lot(lot["id"])
    # Provisional shrink (book, at fill) != settlement shrink (delivery tickets)
    assert lot_after["provisional_shrink_bu"] == pytest.approx(27.00, abs=1e-9)
    assert d["ticket_shrink_bu"] != lot_after["provisional_shrink_bu"]
    # Waterfall debit: 973.00 - 783.80 == 189.20
    assert lot_after["current_bu"] == pytest.approx(189.20, abs=1e-9)


# ============================================================
# Instance: indemnity_spot_vs_contract_avg_divergence
# ============================================================

def _setup_two_confirmed_loss_alerts():
    """Two bins, each with a CONFIRMED_LOSS alert of 100.00 bu closed at
    2026-08-05T12:00:00Z. Returns (alert_s, alert_c)."""
    from test_helpers import create_bin, create_policy
    bin_s = create_bin(name="BIN-S")
    bin_c = create_bin(name="BIN-C")
    # Hotspot readings (no lots on the bins; hotspot is score-independent)
    get_success_data(api_client.create_reading(
        {
            "bin_id": bin_s["id"], "recorded_at": "2026-08-05T10:00:00Z",
            "ambient_temp_f": 60.0, "cable_temps_f": [85.0, 90.0, 88.0],
            "insect_activity": False,
        }, SM))
    get_success_data(api_client.create_reading(
        {
            "bin_id": bin_c["id"], "recorded_at": "2026-08-05T10:00:00Z",
            "ambient_temp_f": 60.0, "cable_temps_f": [85.0, 90.0, 88.0],
            "insect_activity": False,
        }, SM))
    alert_s = get_first_alert_for_bin(bin_s["id"])
    alert_c = get_first_alert_for_bin(bin_c["id"])
    set_clock("2026-08-05T12:00:00Z")
    get_success_data(api_client.close_alert(
        alert_s["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 100.00}, SM))
    get_success_data(api_client.close_alert(
        alert_c["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 100.00}, SM))
    return alert_s, alert_c


def test_indemnity_spot_variant_values_loss_at_spot(api):
    """PRD section 3.8: "Under `SPOT`, the claim's `unit_value_cents` is the
    supplied spot price."
    And: "The `gross_indemnity_cents` is the `loss_bu` multiplied by the
    `unit_value_cents`, rounded half up to whole cents. The payable
    `indemnity_cents` applies the coverage cap before the deductible: it is
    the lesser of the gross indemnity and the policy's
    `remaining_coverage_cents`, minus the `deductible_cents`, floored at zero."

    A 100.00 bu loss at spot 420 with limit 1000000 and deductible 5000
    yields unit 420.00, gross 42000, indemnity 37000.

    Design: Difficulty/dual_variant_calc/indemnity_spot_vs_contract_avg_divergence
    """
    alert_s, _ = _setup_two_confirmed_loss_alerts()
    pol_s = get_success_data(api_client.create_policy(create_policy_payload(
        valuation_clause="SPOT"), FO))
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol_s["id"], alert_s["id"]), SM))
    get_success_data(api_client.approve_claim(
        claim["id"], {"spot_price_cents_per_bu": 420}, FO))
    got = get_success_data(api_client.get_claim(claim["id"], FO))
    assert got["loss_bu"] == pytest.approx(100.00, abs=1e-9)
    assert got["unit_value_cents"] == pytest.approx(420.00, abs=1e-9)
    assert got["gross_indemnity_cents"] == 42000
    assert got["indemnity_cents"] == 37000


def test_indemnity_contract_avg_variant_uses_weighted_average(api):
    """PRD section 3.8: "Under `CONTRACT_AVG`, the valuation pool is every
    contract of the policy's crop in `OPEN` or `DELIVERING` status whose
    delivery window contains the alert's `closed_at`, both bounds inclusive;
    ... otherwise the `unit_value_cents` is the contracted-bushel-weighted
    average of the pool's unit prices — the sum over the pool of each
    contract's `contract_unit_price_cents` multiplied by its `contracted_bu`,
    divided by the sum of the pool's `contracted_bu` — carried at 2 decimal
    places."

    Pool: 430c x 10000 bu + 470c x 20000 bu -> 430*10000+470*20000 = 13700000
    / 30000 = 456.67 cents/bu. Identical 100.00 bu loss then indemnifies
    45667 - 5000 = 40667, distinct from the SPOT result of 37000.

    Design: Difficulty/dual_variant_calc/indemnity_spot_vs_contract_avg_divergence
    """
    _, alert_c = _setup_two_confirmed_loss_alerts()
    pol_c = get_success_data(api_client.create_policy(create_policy_payload(
        valuation_clause="CONTRACT_AVG"), FO))
    # Two OPEN corn contracts whose windows contain 2026-08-05T12:00:00Z
    get_success_data(api_client.create_contract(create_contract_payload(
        contracted_bu=10000.00, basis_cents_per_bu=-20,
        futures_ref_cents_per_bu=450), FO))  # unit 430
    get_success_data(api_client.create_contract(create_contract_payload(
        contracted_bu=20000.00, basis_cents_per_bu=10,
        futures_ref_cents_per_bu=460), FO))  # unit 470
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(pol_c["id"], alert_c["id"]), SM))
    # CONTRACT_AVG approves with no spot price (clause forbids it)
    get_success_data(api_client.approve_claim(claim["id"], {}, FO))
    got = get_success_data(api_client.get_claim(claim["id"], FO))
    assert got["loss_bu"] == pytest.approx(100.00, abs=1e-9)
    assert got["unit_value_cents"] == pytest.approx(456.67, abs=1e-9)
    assert got["gross_indemnity_cents"] == 45667
    assert got["indemnity_cents"] == 40667
