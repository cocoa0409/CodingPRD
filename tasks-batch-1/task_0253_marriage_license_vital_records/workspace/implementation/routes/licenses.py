"""MarriageLicense endpoints (PRD 3.3)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import success
from util import serialize, touch
from services.common import lookup
from services import ledger as ledger_svc
from services import license_ops

bp = Blueprint("licenses", __name__)


@bp.route("/licenses/<license_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_license(license_id):
    lic = lookup("license", license_id)
    return success(serialize(lic), status=200)


@bp.route("/licenses/<license_id>/expire-check", methods=["POST"])
@require_roles("Clerk", "Registrar")
def expire_check(license_id):
    lic = lookup("license", license_id)
    if lic["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "License is not in ISSUED")
    now = store.now()
    if not (now > lic["expires_at"]):
        raise ApiError("ERR_LICENSE_NOT_EXPIRED", "License has not yet passed expires_at")
    if license_ops.has_accepted_return(lic["id"]):
        # A consummated license cannot be expired this way; treat as not-expirable.
        raise ApiError("ERR_LICENSE_NOT_EXPIRED", "License has an accepted return")
    license_ops.expire_license(lic)
    return success(serialize(lic), status=200)


@bp.route("/licenses/<license_id>/void", methods=["POST"])
@require_roles("Registrar")
def void_license(license_id):
    lic = lookup("license", license_id)
    # PRD 3.3: a license consummated by an accepted return cannot be voided —
    # this is reported as ERR_LICENSE_ALREADY_USED and takes precedence over the
    # generic non-ISSUED state rejection (a USED license is exactly one with an
    # accepted return).
    if license_ops.has_accepted_return(lic["id"]):
        raise ApiError("ERR_LICENSE_ALREADY_USED", "License has an accepted return")
    if lic["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "License is not in ISSUED")
    lic["status"] = "VOID"
    touch(lic)

    # Reverse the license CHARGE with a matching REFUND.
    app = store.applications.get(lic["application_id"])
    charge_amount = 0
    for e in store.ledger.values():
        if (e["source_entity"] == "LICENSE" and e["source_entity_id"] == lic["id"]
                and e["kind"] == "CHARGE"):
            charge_amount += e["amount_cents"]
    ledger_svc.append_entry(lic["application_id"], "REFUND", charge_amount, "LICENSE", lic["id"])
    if app is not None:
        ledger_svc.recompute_total_charged(app)
    return success(serialize(lic), status=200)
