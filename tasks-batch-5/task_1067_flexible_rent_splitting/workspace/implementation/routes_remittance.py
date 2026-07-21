from flask import Blueprint
from core import db, ApiError, auth, caller, ok, touch
from domain import append_ledger
import serial

bp = Blueprint("remittance", __name__)


def get_remittance_or_404(rid):
    r = db.remittances.get(rid)
    if r is None:
        raise ApiError("ERR_REMITTANCE_NOT_FOUND", 404, "Remittance not found.")
    return r


@bp.get("/api/remittances/<rid>")
@auth("PlatformAdmin", "PropertyManager")
def get_remittance(rid):
    r = get_remittance_or_404(rid)
    uid, role = caller()
    if role == "PropertyManager" and r["property_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your remittance.")
    return ok(serial.remittance_out(r))


@bp.post("/api/remittances/<rid>/reverse")
@auth("PlatformAdmin")
def reverse(rid):
    r = get_remittance_or_404(rid)
    c = db.billing_cycles.get(r["cycle_id"])
    if r["status"] != "SENT" or c is None or c["status"] != "REMITTED" \
            or c["repaid_amount_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE", 409, "Remittance cannot be reversed.")

    r["status"] = "REVERSED"
    touch(r)
    append_ledger(c["id"], "REVERSAL", -c["full_rent_cents"], "Remittance reversal")
    append_ledger(c["id"], "FEE_REFUND", -c["fee_provisional_cents"],
                  "Provisional fee refund on reversal")
    c["net_remitted_cents"] = 0
    c["status"] = "SCHEDULED"
    touch(c)
    return ok(serial.remittance_out(r))
