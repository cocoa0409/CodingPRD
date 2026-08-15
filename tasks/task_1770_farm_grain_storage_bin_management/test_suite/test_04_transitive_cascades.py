"""Difficulty Rule 4: transitive cascades.

Covers:
- hotspot_cascade_depth4 (reading -> alert -> posture -> hold -> committed)
- settlement_cascade_depth3 (confirm -> waterfall -> lot DEPLETED -> bin inventory)
"""
import pytest

from test_helpers import (
    get_success_data,
    TEST_USERS,
    create_bin, create_lot, create_contract,
    setup_bin_lot_contract_loadout, setup_dispatched_loadout,
    get_lot, get_contract, get_loadout, get_bin,
    create_hotspot_reading, get_first_alert_for_bin,
)
from test_helpers.api_client import api_client
from test_helpers.factories import deliver_payload

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


# ============================================================
# Instance: hotspot_cascade_depth4
# ============================================================

def _setup_loadout_scheduled(bin_name="BIN-X"):
    return setup_bin_lot_contract_loadout(
        bin_name=bin_name, original_bu=800.00, fill_moisture_pct=15.0,
        contracted_bu=2000.00, planned_bu=400.00,
    )


def test_hotspot_cascade_link1_alert_created_and_link2_posture_alert(api):
    """PRD section 3.2: "A hotspot reading automatically raises a
    `SpoilageAlert` in `OPEN` status whose `source` is `AUTO_HOTSPOT`
    (alerts are only ever system-raised), linked to its bin and to the
    triggering `reading_id`".
    PRD section 2.7: "if any spoilage alert on the bin is `OPEN`, the
    posture is `ALERT`."

    A reading at ambient 60.0, cable 90.0 hits the hotspot delta exactly
    (30.0 >= 30.0) and yields OPEN alert + posture ALERT.

    Design: Difficulty/transitive_cascade/hotspot_cascade_depth4
    """
    b, lot, con, lo = _setup_loadout_scheduled()
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    assert alert["status"] == "OPEN"
    assert alert["source"] == "AUTO_HOTSPOT"
    assert alert["bin_id"] == b["id"]
    bin_after = get_bin(b["id"])
    assert bin_after["posture"] == "ALERT"


def test_hotspot_cascade_link3_hold_and_link4_committed_release(api):
    """PRD section 2.7: "every load-out of the bin in `SCHEDULED` transport
    status moves to `HELD` with `held_reason` set to `POSTURE`, and each held
    load-out reduces its contract's `committed_bu` by its `planned_bu` and
    increments the contract's `version`".
    PRD section 2.7: "every lot of the bin in `STORED` or `PARTIALLY_DRAWN`
    status moves to `SUSPENDED`".

    Link 3: SCHEDULED -> HELD, lot SUSPENDED.
    Link 4: contract.committed_bu drops by planned_bu.

    Design: Difficulty/transitive_cascade/hotspot_cascade_depth4
    """
    b, lot, con, lo = _setup_loadout_scheduled()
    # Pre-condition: loadout creation committed 400.00 to the contract
    con_pre = get_contract(con["id"])
    assert con_pre["committed_bu"] == pytest.approx(400.00, abs=1e-9)

    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")

    lo_after = get_loadout(lo["id"])
    assert lo_after["transport_status"] == "HELD"
    assert lo_after["held_reason"] == "POSTURE"

    lot_after = get_lot(lot["id"])
    assert lot_after["status"] == "SUSPENDED"

    con_after = get_contract(con["id"])
    assert con_after["committed_bu"] == pytest.approx(0.00, abs=1e-9)


# ============================================================
# Instance: settlement_cascade_depth3
# ============================================================

def _setup_two_lot_settle():
    """Two corn lots on BIN-Y (A 500.00 fill 08-01, B 800.00 fill 08-03);
    contract 2000; loadout 650.00 delivered net 650.00."""
    b = create_bin(name="BIN-Y")
    lot_a = create_lot(b["id"], original_bu=500.00, fill_moisture_pct=15.0,
                       fill_date="2026-08-01T00:00:00Z")
    lot_b = create_lot(b["id"], original_bu=800.00, fill_moisture_pct=15.0,
                       fill_date="2026-08-03T00:00:00Z")
    con = create_contract(contracted_bu=2000.00)
    from test_helpers.factories import create_loadout_payload
    lo = get_success_data(api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=650.00,
    ), SM))
    get_success_data(api_client.dispatch_loadout(lo["id"], SM))
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 650.00, "moisture_pct": 15.0},
        ],
    ), SM))
    return b, lot_a, lot_b, con, lo


def test_waterfall_fifo_depletes_earlier_lot_first(api):
    """PRD section 3.6: "The **allocation waterfall** then debits lots from
    the load-out's bin: eligible lots are those in `STORED` or
    `PARTIALLY_DRAWN` status with `current_bu` greater than zero ...
    ordered by `fill_date` ascending with `created_at` ascending as the
    tie-break, never by identifier."
    And: "A lot drawn to exactly 0.00 becomes `DEPLETED`; any lot from which
    a positive amount was taken without depletion becomes `PARTIALLY_DRAWN`."

    Settling 650.00 against lots A (500.00, fill 08-01) then B (800.00,
    fill 08-03) depletes A entirely and draws 150.00 from B.

    Design: Difficulty/transitive_cascade/settlement_cascade_depth3
    """
    b, lot_a, lot_b, con, lo = _setup_two_lot_settle()
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    a = get_lot(lot_a["id"])
    bl = get_lot(lot_b["id"])
    assert a["current_bu"] == pytest.approx(0.00, abs=1e-9)
    assert a["status"] == "DEPLETED"
    assert bl["current_bu"] == pytest.approx(650.00, abs=1e-9)
    assert bl["status"] == "PARTIALLY_DRAWN"


def test_confirm_cascade_updates_bin_inventory_and_contract_delivered(api):
    """PRD section 3.6: "Confirmation accumulates onto the contract:
    `delivered_bu` increases by the `settled_net_bu` ... The bin's
    `current_inventory_bu` and posture are recomputed to close the loop."
    PRD section 3.1: "The `current_inventory_bu` of a bin is at all times
    the sum of `current_bu` over every lot assigned to that bin".

    After settling 650.00 across A(500) + B(150), the bin inventory is
    650.00 and the contract's delivered_bu is 650.00.

    Design: Difficulty/transitive_cascade/settlement_cascade_depth3
    """
    b, lot_a, lot_b, con, lo = _setup_two_lot_settle()
    get_success_data(api_client.confirm_settlement(lo["id"], SM))
    bin_after = get_bin(b["id"])
    assert bin_after["current_inventory_bu"] == pytest.approx(650.00, abs=1e-9)
    con_after = get_contract(con["id"])
    assert con_after["delivered_bu"] == pytest.approx(650.00, abs=1e-9)
