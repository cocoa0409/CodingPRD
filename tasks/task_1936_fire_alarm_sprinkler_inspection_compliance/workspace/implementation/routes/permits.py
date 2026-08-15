"""ModificationPermit endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, MARSHAL_AND_ADMIN,
    ROLE_CONTRACTOR_ADMIN, ROLE_FIRE_MARSHAL,
)
from response import success_object, list_response
from util import get_body, check_unknown_fields, req_int
from errors import (
    invalid_state, stale_version, posture_blocked, system_impaired,
    permit_expired, open_items_block, post_mod_inspection_required,
    invalid_request,
)
from services.core import (
    base_record, public, touch,
    get_system, get_permit,
    contractor_of_system, property_of_system,
    require_contractor_active, require_property_active,
)
from services import calc
from routes.impairments import create_impairment_record

bp = Blueprint("permits", __name__)


@bp.route("/fire-compliance/systems/<sid>/modification-permits", methods=["POST"])
def create_permit(sid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    sys = get_system(sid)
    body = get_body()
    check_unknown_fields(body, {"project_valuation_cents", "expected_system_version"})
    valuation = req_int(body, "project_valuation_cents", min_v=0)
    expected_version = req_int(body, "expected_system_version")
    prop = property_of_system(sys)
    con = contractor_of_system(sys)
    require_contractor_active(con)
    require_property_active(prop)
    if sys["status"] != "IN_SERVICE":
        raise invalid_state("ProtectedSystem is DECOMMISSIONED")
    # OCC (17): expected_system_version must equal the system's current version
    if expected_version != sys["version"]:
        raise stale_version("expected_system_version does not match the system's current version")

    rec = base_record()
    rec.update({
        "system_id": sys["id"],
        "project_valuation_cents": valuation,
        "permit_fee_cents": calc.permit_fee_cents(valuation),
        "work_commenced_at": None,
        "status": "APPLIED",
        "_issued_date": None,
        "_impairment_id": None,
    })
    store.permits[rec["id"]] = rec
    # the application itself increments the parent system's version
    touch(sys)
    return success_object(public(rec), status=201)


@bp.route("/fire-compliance/systems/<sid>/modification-permits", methods=["GET"])
def list_permits(sid):
    require_roles(MARSHAL_AND_ADMIN)
    sys = get_system(sid)
    rows = [p for p in store.permits.values() if p["system_id"] == sys["id"]]
    return list_response(rows, request.args, public)


@bp.route("/fire-compliance/modification-permits/<pid>", methods=["GET"])
def fetch_permit(pid):
    require_roles(MARSHAL_AND_ADMIN)
    return success_object(public(get_permit(pid)))


@bp.route("/fire-compliance/modification-permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    require_roles([ROLE_FIRE_MARSHAL])
    perm = get_permit(pid)
    if perm["status"] != "APPLIED":
        raise invalid_state("ModificationPermit is not APPLIED")
    sys = store.systems.get(perm["system_id"])
    con = contractor_of_system(sys) if sys else None
    # issuance requires GOOD_STANDING
    if con is None or con["posture"] != "GOOD_STANDING":
        raise posture_blocked("Permit issuance requires GOOD_STANDING posture")
    # system impairment gate (8): impairment_status exactly NORMAL
    if sys is not None and sys["impairment_status"] != "NORMAL":
        raise system_impaired("System impairment status is not NORMAL")

    perm["status"] = "ISSUED"
    perm["_issued_date"] = store.today()
    touch(perm)
    return success_object(public(perm))


@bp.route("/fire-compliance/modification-permits/<pid>/commence-work", methods=["POST"])
def commence_work(pid):
    require_roles([ROLE_CONTRACTOR_ADMIN])
    perm = get_permit(pid)
    if perm["status"] != "ISSUED":
        raise invalid_state("ModificationPermit is not ISSUED")
    sys = store.systems.get(perm["system_id"])
    prop = property_of_system(sys) if sys else None
    con = contractor_of_system(sys) if sys else None
    require_contractor_active(con)
    require_property_active(prop)
    today = store.today()
    if perm["_issued_date"] is None or \
            today > perm["_issued_date"] + timedelta(days=calc.PERMIT_VALIDITY_DAYS):
        raise permit_expired("Permit validity window (90 days from issue) has elapsed")

    now = store.now()
    perm["work_commenced_at"] = now
    perm["status"] = "WORK_COMMENCED"
    touch(perm)
    # cascade: commencing work auto-creates an UNPLANNED impairment on the
    # system, itself requiring authority notification within 2h
    if sys is not None:
        imp = create_impairment_record(
            sys, "UNPLANNED", now, now + timedelta(hours=8))
        perm["_impairment_id"] = imp["id"]
    return success_object(public(perm))


@bp.route("/fire-compliance/modification-permits/<pid>/close", methods=["POST"])
def close_permit(pid):
    require_roles([ROLE_FIRE_MARSHAL])
    perm = get_permit(pid)
    if perm["status"] != "WORK_COMMENCED":
        raise invalid_state("ModificationPermit is not WORK_COMMENCED")
    sys = store.systems.get(perm["system_id"])
    # the auto-created impairment for this permit must be CLOSED
    imp = store.impairments.get(perm.get("_impairment_id") or "")
    if imp is None or imp["status"] != "CLOSED":
        raise open_items_block("The auto-created impairment for this permit is not CLOSED")
    # a passing post-modification inspection on the system must be COMPLETED
    # after work_commenced_at
    found = False
    for ev in store.events.values():
        if (ev["system_id"] == perm["system_id"] and ev["status"] == "COMPLETED"
                and ev["completed_at"] is not None
                and perm["work_commenced_at"] is not None
                and ev["completed_at"] > perm["work_commenced_at"]):
            found = True
            break
    if not found:
        raise post_mod_inspection_required(
            "No post-commencement COMPLETED inspection on the system")

    # device frequency re-seed: the device-type mapping is static, so no
    # device's mapping can have changed; nothing to recompute here
    perm["status"] = "CLOSED"
    touch(perm)
    con = contractor_of_system(sys) if sys else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(perm))


@bp.route("/fire-compliance/modification-permits/<pid>/cite-unpermitted-work", methods=["POST"])
def cite_unpermitted_work(pid):
    require_roles([ROLE_FIRE_MARSHAL])
    perm = get_permit(pid)
    # state legality (5) before body shape (18)
    if perm["status"] not in ("APPLIED", "ISSUED"):
        raise invalid_state("ModificationPermit is not APPLIED or ISSUED")
    body = get_body()
    check_unknown_fields(body, {"unpermitted_work_detected"})
    if body.get("unpermitted_work_detected") is not True:
        raise invalid_request("unpermitted_work_detected must be true")

    perm["permit_fee_cents"] = perm["permit_fee_cents"] * 2
    perm["status"] = "FINED"
    touch(perm)
    sys = store.systems.get(perm["system_id"])
    con = contractor_of_system(sys) if sys else None
    if con is not None:
        calc.recompute_contractor(con)
    return success_object(public(perm))
