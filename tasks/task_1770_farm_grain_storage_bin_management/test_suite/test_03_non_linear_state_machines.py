"""Difficulty Rule 3: non-linear state machines.

Covers two instances:
- loadout_parallel_dimensions_hold_cycle (parallel dimensions on LoadOut)
- contract_fulfilled_reverts_to_delivering (cyclic revert on StorageContract)
"""
import pytest

from test_helpers import (
    get_success_data,
    TEST_USERS,
    setup_bin_lot_contract_loadout, setup_settled_loadout,
    get_lot, get_contract, get_loadout, get_bin,
    create_hotspot_reading, get_first_alert_for_bin,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_loadout_payload, deliver_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: loadout_parallel_dimensions_hold_cycle
# ============================================================

def test_hold_cycle_keeps_settlement_unsettled(api):
    """PRD section 3.5: "A created load-out starts with `transport_status`
    `SCHEDULED` and `settlement_status` `UNSETTLED` — two independent,
    parallel dimensions".
    PRD section 3.6: "a bin entering `ALERT` or `FUMIGATION_LOCKOUT` holds
    its `SCHEDULED` load-outs (transport to `HELD`, `held_reason` set to
    `POSTURE`, each subtracting its `planned_bu` from the contract's
    `committed_bu` and incrementing the contract's `version`)".

    Posture cascade flips transport to HELD while settlement stays UNSETTLED.

    Design: Difficulty/non_linear_state_machine/loadout_parallel_dimensions_hold_cycle
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-P", original_bu=1000.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=400.00,
    )
    create_hotspot_reading(b["id"], recorded_at="2026-08-02T00:00:00Z")
    lo_mid = get_loadout(lo["id"])
    lot_mid = get_lot(lot["id"])
    assert lo_mid["transport_status"] == "HELD"
    assert lo_mid["settlement_status"] == "UNSETTLED"
    assert lo_mid["held_reason"] == "POSTURE"
    assert lot_mid["status"] == "SUSPENDED"


def test_release_then_deliver_lets_dimensions_move_independently(api):
    """PRD section 3.6: "a bin releasing back to `SOUND` or `WATCH` returns
    them (transport to `SCHEDULED`, `held_reason` cleared, commitment and
    version restored symmetrically)".
    PRD section 3.6: "The transport dimension is unaffected: a load-out whose
    transport is `DELIVERED` stays `DELIVERED` while its settlement moves
    from `UNSETTLED` to `SETTLED` to `VOIDED`."

    After the alert is RESOLVED, transport cycles back to SCHEDULED while
    settlement stays UNSETTLED; a subsequent dispatch+deliver moves only the
    transport dimension to DELIVERED while settlement remains UNSETTLED.

    Design: Difficulty/non_linear_state_machine/loadout_parallel_dimensions_hold_cycle
    """
    b, lot, con, lo = setup_bin_lot_contract_loadout(
        bin_name="BIN-P", original_bu=1000.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=400.00,
    )
    create_hotspot_reading(b["id"], recorded_at="2026-08-02T00:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    get_success_data(api_client.close_alert(alert["id"], {"outcome": "RESOLVED"}, SM))

    lo_after = get_loadout(lo["id"])
    lot_after = get_lot(lot["id"])
    bin_after = get_bin(b["id"])
    assert lo_after["transport_status"] == "SCHEDULED"
    assert lo_after["held_reason"] is None
    assert lo_after["settlement_status"] == "UNSETTLED"
    assert lot_after["status"] == "STORED"
    # Score 50.50 (hotspot reading) keeps the bin in WATCH after release
    assert bin_after["posture"] == "WATCH"

    get_success_data(api_client.dispatch_loadout(lo["id"], SM))
    d = get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 400.00, "moisture_pct": 15.0},
        ],
    ), SM))
    assert d["transport_status"] == "DELIVERED"
    assert d["settlement_status"] == "UNSETTLED"


# ============================================================
# Instance: contract_fulfilled_reverts_to_delivering
# ============================================================

def _setup_fulfilled_cycle():
    """Lot 1000.00 @15.0%; contract 1000 bu; loadout 980.00 delivered net
    980.00 and settled -> FULFILLED. Returns (b, lot, con, lo1)."""
    b, lot, con, lo1 = setup_settled_loadout(
        bin_name="BIN-CY", original_bu=1000.00, fill_moisture_pct=15.0,
        contracted_bu=1000.00, planned_bu=980.00,
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 980.00, "moisture_pct": 15.0},
        ],
    )
    return b, lot, con, lo1


def test_first_confirm_at_exactly_98pct_fulfills(api):
    """PRD section 3.6: "Fulfillment is judged in bushels, not ratio points:
    when the contract's `delivered_bu` reaches at least 98 percent of its
    `contracted_bu` — exactly 98.00 percent fulfills, 97.99 percent does not
    — the contract moves from `DELIVERING` to `FULFILLED`".

    Delivering exactly 980.00 of 1000.00 fulfills.

    Design: Difficulty/non_linear_state_machine/contract_fulfilled_reverts_to_delivering
    """
    _, _, con, _ = _setup_fulfilled_cycle()
    got = get_contract(con["id"])
    assert got["status"] == "FULFILLED"
    assert got["delivered_bu"] == pytest.approx(980.00, abs=1e-9)


def test_void_reverts_fulfilled_to_delivering_then_second_settle_refills(api):
    """PRD section 3.6: "a contract that had reached `FULFILLED` falls back
    to `DELIVERING` when the reversal drops its delivered bushels below the
    98-percent threshold".
    PRD section 3.6: "Voiding is a compensating reversal that restores every
    invariant: each recorded draw is reversed — the lot's `current_bu` is
    credited back and its `drawn_bu` debited, so a `DEPLETED` lot revives to
    `PARTIALLY_DRAWN`".

    After void-settlement the contract reverts to DELIVERING with
    delivered_bu == 0 and the lot's draw is reversed back to 1000.00; a
    second settle cycle returns the contract to FULFILLED and re-draws
    980.00 from the restored lot, leaving 20.00 as PARTIALLY_DRAWN.

    Design: Difficulty/non_linear_state_machine/contract_fulfilled_reverts_to_delivering
    """
    b, lot, con, lo1 = _setup_fulfilled_cycle()
    get_success_data(api_client.void_settlement(lo1["id"], SM))
    con_mid = get_contract(con["id"])
    assert con_mid["status"] == "DELIVERING"
    assert con_mid["delivered_bu"] == pytest.approx(0.00, abs=1e-9)

    # Second settle cycle on a new loadout (next-day window)
    con_v = con_mid["version"]
    lo2 = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con_v, planned_bu=980.00,
        scheduled_start="2026-08-11T08:00:00Z",
        scheduled_end="2026-08-11T12:00:00Z",
    ), SM))
    get_success_data(api_client.dispatch_loadout(lo2["id"], SM))
    get_success_data(api_client.deliver_loadout(lo2["id"], deliver_payload(
        delivered_at="2026-08-11T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 980.00, "moisture_pct": 15.0},
        ],
    ), SM))
    get_success_data(api_client.confirm_settlement(lo2["id"], SM))

    con_end = get_contract(con["id"])
    assert con_end["status"] == "FULFILLED"

    # The void restored the lot to 1000.00 ("each recorded draw is
    # reversed"); the second settle re-draws 980.00, leaving 20.00.
    lot_end = get_lot(lot["id"])
    assert lot_end["current_bu"] == pytest.approx(20.00, abs=1e-9)
    assert lot_end["drawn_bu"] == pytest.approx(980.00, abs=1e-9)
    assert lot_end["status"] == "PARTIALLY_DRAWN"
