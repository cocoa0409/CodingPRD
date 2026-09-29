"""Construction sites: two independent state dimensions on one row."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, CLOCK, new_row, touch
from errors import ApiError
from middleware import body, get_enum, get_number, get_str, require
from routes.common import find, listing, one, require_active, settle, snapshot
from services import calc, derive
from services.calc import D

bp = Blueprint("construction_sites", __name__)

READERS = mw.OPERATIONAL_ROLES


def _not_closed(site):
    if site.get("field_status") == "CLOSED":
        raise ApiError("ERR_SITE_CLOSED")
    return site


@bp.post("/construction-sites")
def create_site():
    require([mw.INSPECTOR, mw.MANAGER])
    payload = body()
    term_id = get_str(payload, "permit_term_id")
    site_name = get_str(payload, "site_name")
    operator = get_str(payload, "operator_name")
    acres = get_number(payload, "disturbed_acres", minimum=1.00)

    term = find("permit_terms", term_id)
    row = new_row(
        {
            "permit_term_id": term["id"],
            "site_name": site_name,
            "operator_name": operator,
            "disturbed_acres": calc.num(acres, 2),
            "esc_plan_reference": None,
            "plan_status": "SUBMITTED",
            "field_status": "PRE_CONSTRUCTION",
            "plan_review_round": 0,
            "post_construction_control_required": D(acres) >= D("2.00"),
            "stop_work_reason": None,
            "stop_work_count": 0,
            "open_deficiency_score": 0,
            "open_enforcement_count": 0,
            "closed_at": None,
        }
    )
    DB.sites[row["id"]] = row
    return one(row, 201)


@bp.get("/construction-sites/<site_id>")
def read_site(site_id):
    require(READERS)
    return one(find("sites", site_id))


@bp.post("/construction-sites/<site_id>/submit-esc-plan")
def submit_esc_plan(site_id):
    require([mw.INSPECTOR])
    payload = body()
    reference = get_str(payload, "esc_plan_reference")
    site = _not_closed(find("sites", site_id))

    site["plan_status"] = "ESC_REVIEW"
    site["esc_plan_reference"] = reference
    touch(site)
    settle(derive.term_of_site(site))
    return one(site)


@bp.post("/construction-sites/<site_id>/esc-review")
def esc_review(site_id):
    require([mw.INSPECTOR])
    payload = body()
    decision = get_enum(payload, "decision", enums.ESC_DECISION)
    get_str(payload, "review_notes", required=False, default=None, min_len=None)
    site = _not_closed(find("sites", site_id))
    if site["plan_status"] != "ESC_REVIEW":
        raise ApiError("ERR_PLAN_NOT_IN_REVIEW")
    term = derive.term_of_site(site)
    require_active(term)

    site["plan_review_round"] = int(site.get("plan_review_round") or 0) + 1
    if decision == "APPROVE":
        site["plan_status"] = "APPROVED"
        if site["field_status"] == "PRE_CONSTRUCTION":
            site["field_status"] = "ACTIVE_DISTURBANCE"
    else:
        site["plan_status"] = "RETURNED"
    touch(site)
    settle(term)
    return one(site)


@bp.post("/construction-sites/<site_id>/stop-work")
def stop_work(site_id):
    require([mw.OFFICER])
    payload = body()
    reason = get_str(payload, "reason")
    site = _not_closed(find("sites", site_id))
    if site["field_status"] != "ACTIVE_DISTURBANCE":
        raise ApiError("ERR_SITE_NOT_ACTIVE_DISTURBANCE")
    term = derive.term_of_site(site)
    require_active(term)

    site["field_status"] = "STOP_WORK"
    site["stop_work_reason"] = reason
    site["stop_work_count"] = int(site.get("stop_work_count") or 0) + 1
    touch(site)
    settle(term)
    return one(site)


@bp.post("/construction-sites/<site_id>/release-stop-work")
def release_stop_work(site_id):
    require([mw.OFFICER])
    payload = body()
    get_str(payload, "corrective_action_note")
    site = _not_closed(find("sites", site_id))
    if site["field_status"] != "STOP_WORK":
        raise ApiError("ERR_SITE_NOT_STOPPED")
    if int(site.get("open_enforcement_count") or 0) != 0:
        raise ApiError("ERR_SITE_HAS_OPEN_ENFORCEMENT")
    if site["plan_status"] != "APPROVED":
        raise ApiError("ERR_ESC_PLAN_NOT_APPROVED")

    site["field_status"] = "ACTIVE_DISTURBANCE"
    site["stop_work_reason"] = None
    site["open_deficiency_score"] = 0
    touch(site)
    settle(derive.term_of_site(site))
    return one(site)


@bp.post("/construction-sites/<site_id>/close")
def close_site(site_id):
    require([mw.INSPECTOR])
    payload = body()
    get_str(payload, "final_stabilization_note")
    site = _not_closed(find("sites", site_id))
    if site["field_status"] != "ACTIVE_DISTURBANCE":
        raise ApiError("ERR_SITE_NOT_ACTIVE_DISTURBANCE")
    if int(site.get("open_enforcement_count") or 0) != 0:
        raise ApiError("ERR_SITE_HAS_OPEN_ENFORCEMENT")
    if site.get("post_construction_control_required"):
        covered = [
            f
            for f in derive.facilities_of_site(site["id"])
            if f.get("agreement_status") in ("RECORDED", "NOT_REQUIRED")
        ]
        if not covered:
            raise ApiError("ERR_CLOSE_REQUIRES_MAINTENANCE_AGREEMENT")

    site["field_status"] = "CLOSED"
    site["closed_at"] = CLOCK.stamp()
    touch(site)
    settle(derive.term_of_site(site))
    return one(site)


@bp.get("/construction-sites/<site_id>/post-construction-facilities")
def list_site_facilities(site_id):
    require(mw.ALL_ROLES)
    spec = {
        "ownership": ("ownership", enums.OWNERSHIP),
        "agreement_status": ("agreement_status", enums.AGREEMENT_STATUS),
    }
    return listing(
        spec,
        lambda: derive.facilities_of_site(find("sites", site_id)["id"]),
    )
