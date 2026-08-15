from flask import Blueprint

import db
import services
from errors import ApiError
from middleware import require_roles
from response import ok
from validation import body, is_int, req_enum, req_int, req_str

bp = Blueprint("pharmacies", __name__)


@bp.route("/pharmacies", methods=["POST"])
def create_pharmacy():
    require_roles("PbmAdmin")
    b = body()
    ncpdp_id = req_str(b, "ncpdp_id")
    name = req_str(b, "name")
    channel = req_enum(b, "channel", ("RETAIL", "SPECIALTY", "MAIL_ORDER"))
    threshold = req_int(b, "auto_suspend_threshold_cents", minimum=1)
    if any(p["ncpdp_id"] == ncpdp_id for p in db.pharmacies.values()):
        raise ApiError("ERR_INVALID_REQUEST", "A pharmacy with this ncpdp_id already exists", 400)
    rec = db.base_record()
    rec.update(
        {
            "ncpdp_id": ncpdp_id,
            "name": name,
            "channel": channel,
            "auto_suspend_threshold_cents": threshold,
            "balance_cents": 0,
            "status": "ACTIVE",
        }
    )
    db.pharmacies[rec["id"]] = rec
    return ok(db.public(rec), 201)


def get_pharmacy_or_404(pharmacy_id):
    pharmacy = db.pharmacies.get(pharmacy_id)
    if pharmacy is None:
        raise ApiError("ERR_PHARMACY_NOT_FOUND", "Pharmacy not found", 404)
    return pharmacy


@bp.route("/pharmacies/<pharmacy_id>", methods=["GET"])
def get_pharmacy(pharmacy_id):
    require_roles("PbmAdmin", "Pharmacist", "Auditor")
    return ok(db.public(get_pharmacy_or_404(pharmacy_id)), 200)


@bp.route("/pharmacies/<pharmacy_id>/balance-adjustments", methods=["POST"])
def balance_adjustment(pharmacy_id):
    require_roles("PbmAdmin")
    pharmacy = get_pharmacy_or_404(pharmacy_id)
    b = body()
    amount = b.get("amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'amount_cents' is required and must be an integer", 400)
    req_str(b, "reason")
    pharmacy["balance_cents"] += amount
    db.touch(pharmacy)
    services.maybe_suspend(pharmacy)
    return ok(db.public(pharmacy), 200)


@bp.route("/pharmacies/<pharmacy_id>/reinstate", methods=["POST"])
def reinstate_pharmacy(pharmacy_id):
    require_roles("PbmAdmin")
    pharmacy = get_pharmacy_or_404(pharmacy_id)
    # Pinned stage-5 order: SUSPENDED state before the balance check.
    if pharmacy["status"] != "SUSPENDED":
        raise ApiError("ERR_PHARMACY_NOT_SUSPENDED", "Pharmacy is not SUSPENDED", 409)
    if pharmacy["balance_cents"] <= -pharmacy["auto_suspend_threshold_cents"]:
        raise ApiError(
            "ERR_PHARMACY_DEBT_OUTSTANDING",
            "Pharmacy balance has not been restored above the negative threshold",
            409,
        )
    pharmacy["status"] = "ACTIVE"
    db.touch(pharmacy)
    return ok(db.public(pharmacy), 200)
