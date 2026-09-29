"""Transitive and compensating cascades (PRD 2.8 / 2.9).

Every link is caused by the mutation the previous link performed, every link
walks its own set in ascending created_at order, and every record a link
mutates gets its updated_at refreshed and its version incremented by one.
"""

from db import db, sorted_records, touch
from services.lookup import (
    cert_pack_units,
    children,
    lot_certificates,
)


def _wire_lots_of_heat(heat_id):
    return children("wire_lots", "steel_heat_id", heat_id)


def _lots_of_wire_lots(wire_lot_ids):
    ids = set(wire_lot_ids)
    return sorted_records(
        [r for r in db.production_lots.values() if r.get("wire_lot_id") in ids]
    )


def cascade_heat_counterfeit(heat):
    """Link 1..4 of the counterfeit freeze."""
    # link 1 - wire lots of the heat
    frozen_wire = []
    for wire in _wire_lots_of_heat(heat["id"]):
        if wire["status"] in ("DRAWN", "RELEASED"):
            wire["status"] = "QUARANTINED"
            wire["quarantine_source"] = "HEAT_COUNTERFEIT"
            touch(wire)
            frozen_wire.append(wire)

    # link 2 - production lots fed by those wire lots
    frozen_lots = []
    for lot in _lots_of_wire_lots([w["id"] for w in frozen_wire]):
        if lot["process_state"] == "ABORTED":
            continue
        if lot["disposition"] not in ("IN_PROCESS", "HOLD"):
            continue
        lot["disposition"] = "QUARANTINED"
        lot["hold_source"] = "HEAT_COUNTERFEIT"
        touch(lot)
        frozen_lots.append(lot)

    # link 3 - certificates of those lots
    revoked_certs = []
    for lot in frozen_lots:
        for cert in lot_certificates(lot["id"]):
            if cert["status"] in ("DRAFT", "ISSUED", "REISSUE_PENDING"):
                revoked_certs.append(cert)
    for cert in sorted_records(revoked_certs):
        cert["status"] = "REVOKED"
        cert["revoked_reason"] = "HEAT_COUNTERFEIT"
        touch(cert)

    # link 4 - pack units of those certificates
    recalled = []
    for cert in revoked_certs:
        for pack in cert_pack_units(cert["id"]):
            if pack["status"] in ("SEALED", "SHIPPED"):
                recalled.append(pack)
    for pack in sorted_records(recalled):
        pack["status"] = "RECALLED"
        pack["recall_reason"] = "HEAT_COUNTERFEIT"
        touch(pack)


def cascade_heat_rejected(heat):
    """Two-link freeze applied when a PENDING heat is rejected outright."""
    frozen_wire = []
    for wire in _wire_lots_of_heat(heat["id"]):
        if wire["status"] in ("DRAWN", "RELEASED"):
            wire["status"] = "QUARANTINED"
            wire["quarantine_source"] = "HEAT_REJECTED"
            touch(wire)
            frozen_wire.append(wire)

    for lot in _lots_of_wire_lots([w["id"] for w in frozen_wire]):
        if lot["process_state"] in ("SHIPPED", "ABORTED"):
            continue
        if lot["disposition"] not in ("IN_PROCESS", "HOLD"):
            continue
        lot["disposition"] = "QUARANTINED"
        lot["hold_source"] = "HEAT_COUNTERFEIT"
        touch(lot)


def cascade_heat_cleared(heat):
    """Compensating cascade: a suspected heat is cleared to VERIFIED."""
    restored_wire = []
    for wire in _wire_lots_of_heat(heat["id"]):
        if wire.get("quarantine_source") == "HEAT_COUNTERFEIT":
            wire["status"] = "DRAWN"
            wire["quarantine_source"] = "NONE"
            wire["inspected_at"] = None
            touch(wire)
            restored_wire.append(wire)

    restored_ids = {w["id"] for w in restored_wire}
    for lot in _lots_of_wire_lots(restored_ids):
        if lot["disposition"] == "QUARANTINED" and lot.get("hold_source") == "HEAT_COUNTERFEIT":
            lot["disposition"] = "IN_PROCESS"
            lot["hold_source"] = "NONE"
            touch(lot)


def cascade_tool_worn(tool):
    """Hold every lot still in SETUP on a tool that has just been condemned."""
    lots = sorted_records(
        [
            r
            for r in db.production_lots.values()
            if r.get("heading_tool_id") == tool["id"]
        ]
    )
    for lot in lots:
        if lot["process_state"] != "SETUP":
            continue
        if lot["disposition"] != "IN_PROCESS":
            continue
        lot["disposition"] = "HOLD"
        lot["hold_source"] = "TOOL_WEAR"
        touch(lot)


def cascade_certificate_revoked(cert, reason, from_operator):
    """Recall the certificate's sealed / shipped pack units."""
    for pack in cert_pack_units(cert["id"]):
        if pack["status"] in ("SEALED", "SHIPPED"):
            pack["status"] = "RECALLED"
            pack["recall_reason"] = reason
            touch(pack)

    if from_operator:
        lot = db.production_lots.get(cert["production_lot_id"])
        if lot is not None and lot["disposition"] == "IN_PROCESS":
            lot["disposition"] = "HOLD"
            lot["hold_source"] = "QUALITY"
            touch(lot)
