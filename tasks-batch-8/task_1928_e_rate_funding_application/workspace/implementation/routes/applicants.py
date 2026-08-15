"""Applicant endpoints: registration, budget summary, audit hold (PRD 3.1, 3.2, 2.8)."""
from flask import Blueprint, request

from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_DISCOUNT_SNAPSHOT_MISSING,
)
from middleware import get_caller, check_role
from response import success_object
from routes.helpers import public, list_collection, get_one
from services.core import (
    new_record, touch, latest_snapshot, c2_cap_cents, c2_committed_cents,
)
from services.calcs import discount_rate
from validate import (
    get_body, check_allowed, req_str, req_enum, opt_int, req_bool,
    require_path_resource,
)

bp = Blueprint("applicants", __name__, url_prefix="/erate")


@bp.post("/applicants")
def create_applicant():
    caller = get_caller()
    check_role(caller, ["ProgramAdmin"])
    body = get_body()
    check_allowed(body, {"name", "entity_type", "urban_rural", "student_count",
                         "square_feet"})
    name = req_str(body, "name")
    entity_type = req_enum(body, "entity_type", ("SCHOOL", "LIBRARY"))
    urban_rural = req_enum(body, "urban_rural", ("URBAN", "RURAL"))
    student_count = opt_int(body, "student_count", positive=True)
    square_feet = opt_int(body, "square_feet", positive=True)
    if entity_type == "SCHOOL" and student_count is None:
        raise_error(ERR_INVALID_REQUEST,
                    "student_count is required when entity_type is SCHOOL")
    if entity_type == "LIBRARY" and square_feet is None:
        raise_error(ERR_INVALID_REQUEST,
                    "square_feet is required when entity_type is LIBRARY")
    rec = new_record("applicants", {
        "name": name,
        "entity_type": entity_type,
        "urban_rural": urban_rural,
        "student_count": student_count,
        "square_feet": square_feet,
        "audit_hold_active": False,
    })
    return success_object(public(rec), 201)


@bp.get("/applicants")
def list_applicants():
    return list_collection("applicants", {
        "entity_type": request.args.get("entity_type"),
    })


@bp.get("/applicants/<rid>")
def get_applicant(rid):
    return get_one("applicants", rid)


@bp.get("/applicants/<rid>/budget-summary")
def budget_summary(rid):
    """Computed read: live C2 budget + discount rates for a cycle (PRD 3.2).
    Nothing is pinned by this read."""
    get_caller()
    applicant = require_path_resource("applicants", rid)
    funding_cycle_id = request.args.get("funding_cycle_id")
    if funding_cycle_id is None or funding_cycle_id.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "funding_cycle_id query parameter is required")
    snapshot = latest_snapshot(rid, funding_cycle_id)
    if snapshot is None:
        raise_error(ERR_DISCOUNT_SNAPSHOT_MISSING,
                    "no NSLP snapshot exists for this applicant and funding cycle")
    share = snapshot["effective_share_pct"]
    cap = c2_cap_cents(applicant)
    committed = c2_committed_cents(rid)
    return success_object({
        "c2_cap_cents": cap,
        "c2_committed_cents": committed,
        "c2_available_cents": cap - committed,
        "discount_rate_c1_pct": discount_rate("CATEGORY_ONE", applicant["urban_rural"], share),
        "discount_rate_c2_pct": discount_rate("CATEGORY_TWO", applicant["urban_rural"], share),
        "nslp_share_pct": share,
    })


@bp.post("/applicants/<rid>/set-audit-hold")
def set_audit_hold(rid):
    caller = get_caller()
    check_role(caller, ["Auditor"])
    body = get_body()
    check_allowed(body, {"active"})
    active = req_bool(body, "active")
    applicant = require_path_resource("applicants", rid)
    applicant["audit_hold_active"] = active
    touch(applicant)
    return success_object(public(applicant))
