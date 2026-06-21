"""OfficiantReturn endpoints (PRD 3.4, 3.8)."""
from flask import Blueprint, g, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from util import new_common, serialize, parse_dt, touch
from services.common import (
    get_body, require_fields, require_str, lookup,
    parse_pagination, sort_by_created,
)
from services import calculations as calc
from services import ledger as ledger_svc
from services import derived
from services import license_ops

bp = Blueprint("returns", __name__)


@bp.route("/returns", methods=["POST"])
@require_roles("Officiant", "Clerk")
def create_return():
    body = get_body()
    require_fields(body, "license_id", "officiant_id", "ceremony_date")
    require_str(body["license_id"], "license_id")
    require_str(body["officiant_id"], "officiant_id")
    ceremony_date = parse_dt(body["ceremony_date"], "ceremony_date")
    # Existence: body FKs (license then officiant).
    lookup("license", body["license_id"])
    lookup("officiant", body["officiant_id"])

    ent = new_common("return")
    ent.update({
        "license_id": body["license_id"],
        "officiant_id": body["officiant_id"],
        "ceremony_date": ceremony_date,
        "status": "SUBMITTED",
        "accepted_by_user_id": None,
        "filing_deadline": calc.filing_deadline(ceremony_date),
        "rejection_reason_code": None,
    })
    store.returns[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.route("/returns/<return_id>", methods=["GET"])
@require_roles("Clerk", "Registrar", "Officiant")
def get_return(return_id):
    ent = lookup("return", return_id)
    return success(serialize(ent), status=200)


@bp.route("/returns", methods=["GET"])
@require_roles("Clerk", "Registrar")
def list_returns():
    limit, offset = parse_pagination()
    license_filter = request.args.get("license_id")
    items = list(store.returns.values())
    if license_filter is not None:
        items = [r for r in items if r["license_id"] == license_filter]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(r) for r in page], limit, offset, total)


def _check_double_booked(ret):
    """officiant_ceremony_overlap: |gap| < OFFICIANT_BUFFER_MINUTES strict (PRD 3.8)."""
    from datetime import timedelta
    from constants import OFFICIANT_BUFFER_MINUTES
    buffer = timedelta(minutes=OFFICIANT_BUFFER_MINUTES)
    for other in store.returns.values():
        if other["id"] == ret["id"]:
            continue
        if other["status"] != "ACCEPTED":
            continue
        if other["officiant_id"] != ret["officiant_id"]:
            continue
        gap = abs(ret["ceremony_date"] - other["ceremony_date"])
        if gap < buffer:
            raise ApiError("ERR_OFFICIANT_DOUBLE_BOOKED", "Officiant is double-booked")


@bp.route("/returns/<return_id>/accept", methods=["POST"])
@require_roles("Registrar")
def accept_return(return_id):
    ret = lookup("return", return_id)
    # State gate.
    if ret["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Return is not SUBMITTED")

    lic = store.licenses.get(ret["license_id"])
    officiant = store.officiants.get(ret["officiant_id"])

    # Precondition sequence per PRD 3.4 (prose order is authoritative).
    if lic is None or lic["status"] != "ISSUED":
        raise ApiError("ERR_LICENSE_NOT_USABLE", "License is not in ISSUED")
    if ret["ceremony_date"] < lic["valid_from"]:
        raise ApiError("ERR_CEREMONY_BEFORE_VALID", "Ceremony before the license valid_from")
    if ret["ceremony_date"] > lic["expires_at"]:
        raise ApiError("ERR_CEREMONY_AFTER_EXPIRY", "Ceremony after the license expires_at")
    if officiant is None or officiant["status"] != "REGISTERED" \
            or ret["ceremony_date"] > officiant["registration_expires_on"]:
        raise ApiError("ERR_OFFICIANT_NOT_AUTHORIZED", "Officiant not authorized for this ceremony")
    _check_double_booked(ret)

    owning_app = store.applications.get(lic["application_id"])
    approved_by = owning_app["approved_by_user_id"] if owning_app else None
    if approved_by is not None and g.user_id == approved_by:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Registrar cannot be the approving clerk of this application")

    # Success: accept and run cascades.
    ret["status"] = "ACCEPTED"
    ret["accepted_by_user_id"] = g.user_id
    touch(ret)

    # License ISSUED -> USED.
    lic["status"] = "USED"
    touch(lic)

    # USED creates a MarriageRecord REGISTERED.
    now = store.now()
    record = new_common("record")
    record.update({
        "return_id": ret["id"],
        "license_id": lic["id"],
        "is_confidential": lic["is_confidential"],
        "registered_at": now,
        "status": "REGISTERED",
        "amendment_count": 0,
        "certified_copies_issued": 0,
    })
    store.records[record["id"]] = record

    # Officiant.returns_filed_count recomputed (+1).
    derived.recompute_and_store_returns_filed_count(officiant)

    # Late surcharge if the return was filed after its filing_deadline.
    if ret["created_at"] > ret["filing_deadline"]:
        from constants import LATE_RETURN_SURCHARGE_CENTS
        app_id = owning_app["id"] if owning_app else None
        ledger_svc.append_entry(app_id, "CHARGE", LATE_RETURN_SURCHARGE_CENTS, "RETURN", ret["id"])
        if owning_app is not None:
            ledger_svc.recompute_total_charged(owning_app)

    return success(serialize(ret), status=200)


@bp.route("/returns/<return_id>/reject", methods=["POST"])
@require_roles("Registrar")
def reject_return(return_id):
    ret = lookup("return", return_id)
    if ret["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Return is not SUBMITTED")
    body = get_body()
    ret["status"] = "REJECTED"
    ret["rejection_reason_code"] = body.get("rejection_reason_code")
    touch(ret)
    return success(serialize(ret), status=200)
