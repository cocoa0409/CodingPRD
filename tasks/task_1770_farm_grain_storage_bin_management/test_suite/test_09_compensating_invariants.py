"""Difficulty Rule 9: compensating invariants.

Covers:
- bushel_conservation_settle_void
- money_conservation_settle_void
"""
import pytest

from test_helpers import (
    get_success_data, validate_success,
    TEST_USERS,
    setup_dispatched_loadout,
    get_lot, get_contract,
)
from test_helpers.api_client import api_client
from test_helpers.factories import deliver_payload, create_contract_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: bushel_conservation_settle_void
# ============================================================

def _setup_bushel_invariant_scenario(bin_name="BIN-I"):
    """Lot 1000.00 @17.0% (provisional shrink 27.00, current 973.00);
    contract 2000; loadout 476.65 dispatched and delivered with a ticket
    486.50 @16.5% -> per-ticket shrink 486.50 * 1.5 * 1.35 / 100 = 9.85125
    -> round 9.85, net 476.65."""
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name=bin_name, original_bu=1000.00, fill_moisture_pct=17.0,
        contracted_bu=2000.00, planned_bu=476.65,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 486.50, "moisture_pct": 16.5},
        ],
    ), SM))
    return b, lot, con, lo


def test_bushel_conservation_holds_forward_after_confirm(api):
    """PRD section 3.1: "The lot's book bushels `current_bu` are its
    `original_bu` minus this provisional shrink, and whenever the shrink is
    greater than zero the system posts a `ShrinkEvent` of `kind`
    `PROVISIONAL` against the lot, with its `shrink_bu` equal to the booked
    shrink and its `period` null."
    PRD section 3.6: "each take is subtracted from the lot's `current_bu`,
    added to its `drawn_bu`, and recorded on the load-out's `draws` array".

    After confirm: current_bu 496.35 + settled_net 476.65 + PROVISIONAL
    shrink 27.00 == original 1000.00.

    Design: Difficulty/compensating_invariant/bushel_conservation_settle_void
    """
    b, lot, con, lo = _setup_bushel_invariant_scenario()
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    lot_now = get_lot(lot["id"])
    assert lot_now["current_bu"] == pytest.approx(496.35, abs=1e-9)
    shrink_events = get_success_data(api_client.list_shrink_events(lot["id"], SM))
    assert len(shrink_events) == 1
    assert shrink_events[0]["kind"] == "PROVISIONAL"
    assert shrink_events[0]["shrink_bu"] == pytest.approx(27.00, abs=1e-9)
    # Bushel conservation identity (per bin):
    #   original == current + settled_net (of SETTLED loadouts) + shrink events
    settled_net = 476.65
    total = lot_now["current_bu"] + settled_net + shrink_events[0]["shrink_bu"]
    assert total == pytest.approx(1000.00, abs=1e-9)


def test_bushel_conservation_restored_exactly_after_void(api):
    """PRD section 3.6: "Voiding is a compensating reversal that restores
    every invariant: each recorded draw is reversed — the lot's `current_bu`
    is credited back and its `drawn_bu` debited".

    After void-settlement: current_bu returns to 973.00 and the identity
    973.00 + 0 (no SETTLED loadouts) + 27.00 == 1000.00 holds exactly.

    Design: Difficulty/compensating_invariant/bushel_conservation_settle_void
    """
    b, lot, con, lo = _setup_bushel_invariant_scenario()
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    get_success_data(api_client.void_settlement(lo["id"], SM))
    lot_now = get_lot(lot["id"])
    assert lot_now["current_bu"] == pytest.approx(973.00, abs=1e-9)
    assert lot_now["drawn_bu"] == pytest.approx(0.00, abs=1e-9)
    shrink_events = get_success_data(api_client.list_shrink_events(lot["id"], SM))
    total_shrink = sum(e["shrink_bu"] for e in shrink_events)
    assert lot_now["current_bu"] + 0.00 + total_shrink == pytest.approx(
        1000.00, abs=1e-9)


# ============================================================
# Instance: money_conservation_settle_void
# ============================================================

def _setup_money_invariant_scenario(bin_name="BIN-M"):
    """Lot 9800.00 @15.0%; contract 10000 bu, futures 450 basis -20 (unit
    430), early bonus 5c before 2026-09-01; loadout 9800.00 delivered net
    9800.00 at 2026-08-10T10:00:00Z (<= cutoff)."""
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name=bin_name, capacity_bu=12000.00,
        original_bu=9800.00, fill_moisture_pct=15.0,
        contracted_bu=10000.00, planned_bu=9800.00,
        early_bonus_cents_per_bu=5, early_cutoff="2026-09-01T00:00:00Z",
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 9800.00, "moisture_pct": 15.0},
        ],
    ), SM))
    return b, lot, con, lo


def test_money_conservation_confirm_accumulates_settled_value(api):
    """PRD section 3.6: "Confirmation accumulates onto the contract:
    `delivered_bu` increases by the `settled_net_bu`,
    `settled_value_cents` increases by the `settlement_net_cents`, the
    contract's `version` increments, and the settlement dimension moves to
    `SETTLED`."

    grain_value 9800 * 430 = 4214000; tier at 4214000 >= 500000 -> 75bps
    fee 31605; early bonus 9800 * 5 = 49000; net = 4214000 - 31605 + 49000
    = 4231395. The contract mirrors this value.

    Design: Difficulty/compensating_invariant/money_conservation_settle_void
    """
    b, lot, con, lo = _setup_money_invariant_scenario()
    conf = get_success_data(api_client.confirm_settlement(lo["id"], SM))
    assert conf["grain_value_cents"] == 4214000
    assert conf["service_fee_cents"] == 31605
    assert conf["early_bonus_cents"] == 49000
    assert conf["settlement_net_cents"] == 4231395
    con_now = get_contract(con["id"])
    assert con_now["settled_value_cents"] == 4231395
    assert con_now["delivered_bu"] == pytest.approx(9800.00, abs=1e-9)
    assert con_now["status"] == "FULFILLED"


def test_money_conservation_void_returns_to_zero(api):
    """PRD section 3.6: "the contract's `delivered_bu` and
    `settled_value_cents` are reduced by the load-out's settled quantities,
    the contract's `version` increments, a contract that had reached
    `FULFILLED` falls back to `DELIVERING` when the reversal drops its
    delivered bushels below the 98-percent threshold".

    After void, settled_value_cents returns to exactly 0, delivered_bu to
    0.00, and the contract drops back to DELIVERING — no monetary drift.

    Design: Difficulty/compensating_invariant/money_conservation_settle_void
    """
    b, lot, con, lo = _setup_money_invariant_scenario()
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    get_success_data(api_client.void_settlement(lo["id"], SM))
    con_now = get_contract(con["id"])
    assert con_now["settled_value_cents"] == 0
    assert con_now["delivered_bu"] == pytest.approx(0.00, abs=1e-9)
    assert con_now["status"] == "DELIVERING"
