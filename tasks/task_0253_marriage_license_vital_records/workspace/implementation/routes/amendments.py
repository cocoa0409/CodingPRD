"""AmendmentRequest endpoints (PRD 3.7)."""
from flask import Blueprint, g

from db import store
from errors import ApiError
from middleware import require_roles
from response import success
from util import new_common, serialize, touch
from services.common import (
    get_body, require_fields, require_str, require_enum, lookup,
)
from services import calculations as calc
from services import ledger as ledger_svc
from services import derived

bp = Blueprint("amendments", __name__)

AMENDMENT_TYPES = {"CLERICAL", "SUBSTANTIVE"}


def _owning_application(record):
    lic = store.licenses.get(record["license_id"])
    if lic is None:
        return None
    return store.applications.get(lic["application_id"])


@bp.route("/amendments", methods=["POST"])
@require_roles("Clerk", "Applicant")
def create_amendment():
    body = get_body()
    require_fields(body, "record_id", "amendment_type", "field_path", "new_value")
    require_str(body["record_id"], "record_id")
    require_enum(body["amendment_type"], AMENDMENT_TYPES, "amendment_type")
    require_str(body["field_path"], "field_path")
    if not isinstance(body["new_value"], str):
        raise ApiError("ERR_INVALID_REQUEST", "new_value must be a string")
    lookup("record", body["record_id"])

    ent = new_common("amendment")
    ent.update({
        "record_id": body["record_id"],
        "amendment_type": body["amendment_type"],
        "field_path": body["field_path"],
        "new_value": body["new_value"],
        "status": "SUBMITTED",
        "resubmit_count": 0,
        "adjudicated_by_user_id": None,
    })
    store.amendments[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/amendments/<amendment_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Applicant")
def get_amendment(amendment_id):
    ent = lookup("amendment", amendment_id)
    return success(serialize(ent), status=200)


@bp.route("/amendments/<amendment_id>/decide", methods=["POST"])
@require_roles("Registrar")
def decide_amendment(amendment_id):
    amd = lookup("amendment", amendment_id)
    body = get_body()
    require_fields(body, "decision")
    require_enum(body["decision"], {"APPLY", "RETURN", "REJECT"}, "decision")
    decision = body["decision"]

    if amd["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Amendment is not SUBMITTED")

    record = store.records.get(amd["record_id"])

    if decision == "RETURN":
        amd["status"] = "RETURNED_FOR_INFO"
        touch(amd)
        return success(serialize(amd), status=200)

    if decision == "REJECT":
        amd["status"] = "REJECTED"
        amd["adjudicated_by_user_id"] = g.user_id
        touch(amd)
        return success(serialize(amd), status=200)

    # APPLY — cross-entity seal check, then segregation for SUBSTANTIVE.
    if record["status"] == "SEALED":
        raise ApiError("ERR_RECORD_SEALED", "Record is sealed")
    if amd["amendment_type"] == "SUBSTANTIVE":
        app = _owning_application(record)
        approved_by = app["approved_by_user_id"] if app else None
        if approved_by is not None and g.user_id == approved_by:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "Registrar cannot be the approving clerk for a substantive amendment")

    amd["status"] = "APPLIED"
    amd["adjudicated_by_user_id"] = g.user_id
    touch(amd)

    fee = calc.amendment_fee(amd["amendment_type"], amd["resubmit_count"])
    app = _owning_application(record)
    app_id = app["id"] if app else None
    ledger_svc.append_entry(app_id, "CHARGE", fee, "AMENDMENT", amd["id"])

    # Record cascades to AMENDED; amendment_count recomputed.
    if record["status"] == "REGISTERED":
        record["status"] = "AMENDED"
        touch(record)
    derived.recompute_and_store_amendment_count(record)

    if app is not None:
        ledger_svc.recompute_total_charged(app)

    return success(serialize(amd), status=200)


@bp.route("/amendments/<amendment_id>/resubmit", methods=["POST"])
@require_roles("Applicant", "Clerk")
def resubmit_amendment(amendment_id):
    amd = lookup("amendment", amendment_id)
    if amd["status"] != "RETURNED_FOR_INFO":
        raise ApiError("ERR_INVALID_STATE", "Amendment is not RETURNED_FOR_INFO")
    from constants import MAX_AMENDMENT_RESUBMITS
    if amd["resubmit_count"] >= MAX_AMENDMENT_RESUBMITS:
        raise ApiError("ERR_RESUBMIT_LIMIT_REACHED", "Resubmit limit reached")
    amd["status"] = "SUBMITTED"
    amd["resubmit_count"] += 1
    touch(amd)
    return success(serialize(amd), status=200)
