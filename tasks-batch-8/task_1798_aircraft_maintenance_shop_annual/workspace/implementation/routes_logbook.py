"""Logbook entries: append-only and immutable (PRD 3.7)."""

from flask import Blueprint

import clock as clockmod
import db
import envelope
import ops
from errors import ApiError
from middleware import require_roles
from validate import apply_filters, body, get_row, paginate, req_enum, req_str

bp = Blueprint("logbook", __name__)


@bp.post("/api/logbook-entries")
@require_roles("Mechanic")
def create_logbook_entry():
    b = body()
    aircraft_id = req_str(b, "aircraft_id")
    work_order_id = req_str(b, "work_order_id")
    entry_type = req_enum(
        b, "entry_type", ("INSPECTION_SIGNOFF", "REPAIR_RECORD", "RTS_STATEMENT")
    )
    narrative = req_str(b, "narrative")
    signed_by = req_str(b, "signed_by_mechanic_id")
    get_row(db.AIRCRAFT, aircraft_id)
    wo = get_row(db.WORK_ORDERS, work_order_id)
    signatory = get_row(db.MECHANICS, signed_by)
    if wo["aircraft_id"] != aircraft_id:
        raise ApiError(
            "ERR_VALIDATION", "work_order_id does not belong to the given aircraft."
        )
    # Regulatory gate: ANNUAL scope requires an IA signatory (priority 5).
    if wo["scope_type"] == "ANNUAL" and signatory["certificate_class"] != "IA":
        raise ApiError(
            "ERR_AIRWORTHINESS_BLOCKED",
            "ANNUAL-scope logbook signoff requires an IA certificate.",
        )
    entry = {
        "aircraft_id": aircraft_id,
        "work_order_id": work_order_id,
        "entry_type": entry_type,
        "narrative": narrative,
        "signed_by_mechanic_id": signed_by,
        "signed_at": clockmod.now_iso(),
    }
    db.stamp_new(entry, versioned=False)
    db.LOGBOOK_ENTRIES[entry["id"]] = entry
    return envelope.created(ops.pub(entry, ops.LOGBOOK_F))


@bp.get("/api/logbook-entries")
@require_roles("ShopManager", "Mechanic", "Owner")
def list_logbook_entries():
    rows = apply_filters(
        list(db.LOGBOOK_ENTRIES.values()),
        {
            "aircraft_id": "aircraft_id",
            "work_order_id": "work_order_id",
            "signed_by_mechanic_id": "signed_by_mechanic_id",
        },
    )
    return paginate(rows, ops.LOGBOOK_F)


@bp.get("/api/logbook-entries/<rid>")
@require_roles("ShopManager", "Mechanic", "Owner")
def get_logbook_entry(rid):
    entry = get_row(db.LOGBOOK_ENTRIES, rid)
    return envelope.ok(ops.pub(entry, ops.LOGBOOK_F))
