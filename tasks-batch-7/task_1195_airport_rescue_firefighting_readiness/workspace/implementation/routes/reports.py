"""Incident reports (review loop) and post-incident reviews."""
from datetime import timedelta

from flask import Blueprint, g

from db import store, base_entity, touch, serialize
from errors import (
    ApiError, ERR_INCIDENT_NOT_FOUND, ERR_VEHICLE_NOT_FOUND,
    ERR_REPORT_NOT_FOUND, ERR_REVIEW_NOT_FOUND, ERR_VALIDATION_FAILED,
    ERR_INCIDENT_NOT_CONTROLLED, ERR_REPORT_WINDOW_EXPIRED,
    ERR_NARRATIVE_TOO_SHORT, ERR_NOT_REPORT_AUTHOR, ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_REPORT_NOT_SUBMITTABLE, ERR_REPORT_NOT_REVIEWABLE, ERR_REPORT_NOT_EDITABLE,
    ERR_REPORT_NOT_ACCEPTED, ERR_REVIEW_ALREADY_OPEN, ERR_REVIEW_NOT_CLOSABLE,
    ERR_ACTIONS_STILL_OPEN, ERR_REVIEW_NOT_EDITABLE,
)
from middleware import require, json_body, need_str, ALL_ROLES
from response import success, paginated
from services import calc

bp = Blueprint("reports", __name__)

REPORT_WINDOW_DAYS = 10
NARRATIVE_MIN_CHARS = 200


def get_report_or_404(rid):
    r = store.reports.get(rid)
    if r is None:
        raise ApiError(ERR_REPORT_NOT_FOUND, 404, "Incident report id does not exist")
    return r


def get_review_or_404(rid):
    r = store.reviews.get(rid)
    if r is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND, 404, "Post-incident review id does not exist")
    return r


def validate_expenditure_lines(data, required=False):
    """Validate agent_expenditure_lines structure; returns normalized list.

    FK existence (priority 3) is checked before structural field validation
    (priority 3.5) for extractable vehicle ids.
    """
    lines = data.get("agent_expenditure_lines")
    if lines is None:
        if required:
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "'agent_expenditure_lines' must be an array")
        return None
    if not isinstance(lines, list):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'agent_expenditure_lines' must be an array")
    # Body-FK existence first (priority 3), for well-formed line entries.
    for ln in lines:
        if isinstance(ln, dict):
            lv = ln.get("vehicle_id")
            if isinstance(lv, str) and lv not in store.vehicles:
                raise ApiError(ERR_VEHICLE_NOT_FOUND, 404, "Vehicle id does not exist")
    normalized = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "Each expenditure line must be an object")
        vid = ln.get("vehicle_id")
        if not isinstance(vid, str) or vid == "":
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "Each line requires 'vehicle_id'")
        water = ln.get("water_gal_used")
        chem = ln.get("dry_chem_lb_used")
        if isinstance(water, bool) or not isinstance(water, (int, float)) or water < 0:
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "'water_gal_used' must be a number >= 0")
        if isinstance(chem, bool) or not isinstance(chem, (int, float)) or chem < 0:
            raise ApiError(ERR_VALIDATION_FAILED, 400,
                           "'dry_chem_lb_used' must be a number >= 0")
        normalized.append({
            "vehicle_id": vid,
            "water_gal_used": water,
            "dry_chem_lb_used": chem,
        })
    return normalized


@bp.post("/arff/incidents/<iid>/reports")
def create_report(iid):
    require(["SafetyOfficer"])
    inc = store.incidents.get(iid)
    if inc is None:
        raise ApiError(ERR_INCIDENT_NOT_FOUND, 404, "Incident id does not exist")
    data = json_body()
    lines = validate_expenditure_lines(data)
    narrative = need_str(data, "narrative")
    if inc["status"] not in ("CONTROLLED", "CLOSED"):
        raise ApiError(ERR_INCIDENT_NOT_CONTROLLED, 409,
                       "Incident must be CONTROLLED or CLOSED for report creation")
    if store.clock > inc["_controlled_dt"] + timedelta(days=REPORT_WINDOW_DAYS):
        raise ApiError(ERR_REPORT_WINDOW_EXPIRED, 422,
                       "Report creation is more than 10 days after controlled_at")
    if len(narrative) < NARRATIVE_MIN_CHARS:
        raise ApiError(ERR_NARRATIVE_TOO_SHORT, 422,
                       "Report narrative must be at least 200 characters")
    lines = lines if lines is not None else []
    r = base_entity()
    r.update({
        "incident_id": iid,
        "author_user_id": g.user_id,
        "narrative": narrative,
        "agent_expenditure_lines": lines,
        "agent_expense_total_cents": calc.agent_expense_total_cents(lines),
        "review_cycle_count": 0,
        "status": "DRAFT",
    })
    store.reports[r["id"]] = r
    return success(serialize(r), "object", 201)


@bp.get("/arff/incident-reports/<rid>")
def get_report(rid):
    require(ALL_ROLES)
    return success(serialize(get_report_or_404(rid)), "object", 200)


@bp.patch("/arff/incident-reports/<rid>")
def patch_report(rid):
    require(["SafetyOfficer"])
    r = get_report_or_404(rid)
    data = json_body()
    lines = validate_expenditure_lines(data)
    narrative = data.get("narrative")
    if "narrative" in data and not isinstance(narrative, str):
        raise ApiError(ERR_VALIDATION_FAILED, 400, "'narrative' must be a string")
    if r["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_REPORT_NOT_EDITABLE, 409,
                       "Only a DRAFT or RETURNED report can be edited")
    if g.user_id != r["author_user_id"]:
        raise ApiError(ERR_NOT_REPORT_AUTHOR, 403,
                       "Only the report author may edit the report")
    was_returned = r["status"] == "RETURNED"
    if "narrative" in data:
        r["narrative"] = narrative
    if lines is not None:
        r["agent_expenditure_lines"] = lines
    r["agent_expense_total_cents"] = calc.agent_expense_total_cents(
        r["agent_expenditure_lines"])
    if was_returned:
        r["status"] = "DRAFT"
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/incident-reports/<rid>/submit")
def submit_report(rid):
    require(["SafetyOfficer"])
    r = get_report_or_404(rid)
    if r["status"] != "DRAFT":
        raise ApiError(ERR_REPORT_NOT_SUBMITTABLE, 409,
                       "Only a DRAFT report can be submitted")
    if g.user_id != r["author_user_id"]:
        raise ApiError(ERR_NOT_REPORT_AUTHOR, 403,
                       "Only the report author may submit the report")
    r["status"] = "SUBMITTED"
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/incident-reports/<rid>/accept")
def accept_report(rid):
    require(["AirportManager"])
    r = get_report_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_REPORT_NOT_REVIEWABLE, 409,
                       "Only a SUBMITTED report can be accepted")
    if g.user_id == r["author_user_id"]:
        raise ApiError(ERR_SELF_APPROVAL_FORBIDDEN, 403,
                       "The report author may not accept their own report")
    r["status"] = "ACCEPTED"
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/incident-reports/<rid>/return")
def return_report(rid):
    require(["AirportManager"])
    r = get_report_or_404(rid)
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_REPORT_NOT_REVIEWABLE, 409,
                       "Only a SUBMITTED report can be returned")
    if g.user_id == r["author_user_id"]:
        raise ApiError(ERR_SELF_APPROVAL_FORBIDDEN, 403,
                       "The report author may not return their own report")
    r["status"] = "RETURNED"
    r["review_cycle_count"] += 1
    touch(r)
    return success(serialize(r), "object", 200)


@bp.post("/arff/incident-reports/<rid>/post-incident-reviews")
def create_review(rid):
    require(["SafetyOfficer"])
    r = get_report_or_404(rid)
    data = json_body()
    findings = need_str(data, "findings")
    cao = data.get("corrective_actions_open")
    if isinstance(cao, bool) or not isinstance(cao, int) or cao < 0:
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'corrective_actions_open' must be an integer >= 0")
    if r["status"] != "ACCEPTED":
        raise ApiError(ERR_REPORT_NOT_ACCEPTED, 409,
                       "Report must be ACCEPTED to open a post-incident review")
    if any(rv["incident_report_id"] == rid and rv["status"] == "OPEN"
           for rv in store.reviews.values()):
        raise ApiError(ERR_REVIEW_ALREADY_OPEN, 409,
                       "An OPEN post-incident review already exists for this report")
    rv = base_entity()
    rv.update({
        "incident_report_id": rid,
        "findings": findings,
        "corrective_actions_open": cao,
        "status": "OPEN",
    })
    store.reviews[rv["id"]] = rv
    return success(serialize(rv), "object", 201)


@bp.get("/arff/incident-reports/<rid>/post-incident-reviews")
def list_reviews(rid):
    require(ALL_ROLES)
    get_report_or_404(rid)
    items = [rv for rv in store.reviews.values() if rv["incident_report_id"] == rid]
    return paginated(items)


@bp.patch("/arff/post-incident-reviews/<rid>")
def patch_review(rid):
    require(["SafetyOfficer"])
    rv = get_review_or_404(rid)
    data = json_body()
    findings = data.get("findings")
    if "findings" in data and not isinstance(findings, str):
        raise ApiError(ERR_VALIDATION_FAILED, 400, "'findings' must be a string")
    cao = data.get("corrective_actions_open")
    if "corrective_actions_open" in data and (
            isinstance(cao, bool) or not isinstance(cao, int) or cao < 0):
        raise ApiError(ERR_VALIDATION_FAILED, 400,
                       "'corrective_actions_open' must be an integer >= 0")
    if rv["status"] != "OPEN":
        raise ApiError(ERR_REVIEW_NOT_EDITABLE, 409,
                       "Only an OPEN review can be edited")
    if "findings" in data:
        rv["findings"] = findings
    if "corrective_actions_open" in data:
        rv["corrective_actions_open"] = cao
    touch(rv)
    return success(serialize(rv), "object", 200)


@bp.post("/arff/post-incident-reviews/<rid>/close")
def close_review(rid):
    require(["SafetyOfficer"])
    rv = get_review_or_404(rid)
    if rv["status"] != "OPEN":
        raise ApiError(ERR_REVIEW_NOT_CLOSABLE, 409, "Review must be OPEN to close")
    if rv["corrective_actions_open"] != 0:
        raise ApiError(ERR_ACTIONS_STILL_OPEN, 422,
                       "corrective_actions_open must equal 0 to close")
    rv["status"] = "CLOSED"
    touch(rv)
    return success(serialize(rv), "object", 200)
