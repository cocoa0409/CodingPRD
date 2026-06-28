"""Cross-aggregate cascade helpers shared by deal funding and auction settlement.

Each cascade leg refreshes updated_at and bumps version on every first-class
resource it touches (PRD §2.5).
"""
from db import db, make_common, touch


def payoff_floor_plan_for_unit(unit):
    """If the unit has an ACTIVE or CURTAILMENT_DUE floor-plan note, move it to
    PAID_OFF, freeze interest at its final value, and clear floor_planned."""
    for note in db.floor_plan_notes.values():
        if note["unit_id"] == unit["id"] and note["status"] in ("ACTIVE", "CURTAILMENT_DUE"):
            note["status"] = "PAID_OFF"
            touch(note)
    unit["floor_planned"] = False


def mint_unit_from_tradein(tradein):
    """Mint a new used Unit from an accepted trade-in (PRD §3.4)."""
    unit = {
        "stock_number": "TRADE-" + tradein["id"][:8] + "-" + tradein["serial_number"],
        "condition": "USED",
        "model_code": tradein["model_code"],
        "serial_number": "TRADE-" + tradein["id"][:8] + "-" + tradein["serial_number"],
        "dealer_cost_cents": tradein["appraised_value_cents"],
        "list_price_cents": tradein["appraised_value_cents"],
        "engine_hours": tradein["engine_hours"],
        "acquired_from_tradein_id": tradein["id"],
        "floor_planned": False,
        "status": "AVAILABLE",
    }
    make_common(unit)
    db.units[unit["id"]] = unit
    return unit


def accept_tradein_and_mint(tradein):
    """Cascade: OFFERED -> ACCEPTED, mint a used Unit, link both ways."""
    unit = mint_unit_from_tradein(tradein)
    tradein["status"] = "ACCEPTED"
    tradein["minted_unit_id"] = unit["id"]
    touch(tradein)
    return unit


def revert_tradein_on_unwind(tradein):
    """Cascade from unwind: minted Unit RETIRED, trade ACCEPTED -> DECLINED."""
    minted_id = tradein.get("minted_unit_id")
    if minted_id:
        minted = db.units.get(minted_id)
        if minted is not None:
            minted["status"] = "RETIRED"
            touch(minted)
    tradein["status"] = "DECLINED"
    touch(tradein)
