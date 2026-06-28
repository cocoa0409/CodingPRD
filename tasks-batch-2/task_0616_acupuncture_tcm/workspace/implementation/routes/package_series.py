"""PackageSeries routes (PRD 3.4)."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_int_min,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_package, get_patient
from middleware import get_auth, require_role
from response import success

bp = Blueprint("package_series", __name__)


@bp.route("/package-series", methods=["POST"])
def purchase_package():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_fields(body, ["patient_id", "total_credits", "price_paid_cents"])
    patient = get_patient(body["patient_id"])
    total_credits = require_int_min(body, "total_credits", 1)
    price_paid_cents = require_int_min(body, "price_paid_cents", 0)
    rec = {
        "patient_id": patient["id"],
        "total_credits": total_credits,
        "price_paid_cents": price_paid_cents,
        "reserved_credits": 0,
        "consumed_credits": 0,
        "provisional_remaining_credits": total_credits,
        "finalized_remaining_credits": total_credits,
        "status": "ACTIVE",
    }
    stamp_new(rec)
    db.package_series[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/package-series", methods=["GET"])
def list_packages():
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    items = list(db.package_series.values())
    if role == "Patient":
        items = [p for p in items if p["patient_id"] == user_id]
    else:
        pf = request.args.get("patient_id")
        if pf is not None:
            items = [p for p in items if p["patient_id"] == pf]
    data, pg = paginate(items, public)
    return success(data, status=200, pagination=pg)


@bp.route("/package-series/<rid>", methods=["GET"])
def get_package_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_package(rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own packages.")
    return success(public(rec), status=200)


@bp.route("/package-series/<rid>/cancel", methods=["POST"])
def cancel_package(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    rec = get_package(rid)
    # Cancellation requires no realized or outstanding obligations.
    # consumed_credits == 0 then reserved_credits == 0 (priority 16 ordering).
    if rec["consumed_credits"] != 0:
        raise err(
            "ERR_PACKAGE_HAS_CONSUMED_CREDITS",
            "Package cancel requires consumed_credits == 0.",
        )
    if rec["reserved_credits"] != 0:
        raise err(
            "ERR_PACKAGE_HAS_RESERVED_CREDITS",
            "Package cancel requires reserved_credits == 0.",
        )
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(public(rec), status=200)
