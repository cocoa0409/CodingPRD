"""SitePlanDocument endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_VALIDATION, ERR_INCOMPLETE_COVERAGE
from middleware import authorized, ALL_ROLES, ROLE_OFFICER
from response import success_object
from services.core import new_record, public, apply_changes
from util import CLOCK, parse_date
from validate import get_body, reject_unknown, req_date, req_str, req_str_list
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("site_plans", __name__)

COVERAGE_TAGS = {"FLOOR_PLANS", "ACCESS_POINTS", "UTILITY_SHUTOFFS", "ASSEMBLY_AREAS"}
REQUIRED_TAGS = {"FLOOR_PLANS", "ACCESS_POINTS"}


@bp.post("/site-plan-documents")
def create_site_plan():
    authorized([ROLE_OFFICER])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "document_title", "issued_on",
                          "review_by_date", "coverage_tags"])
    site_id = req_str(body, "site_id")
    title = req_str(body, "document_title")
    issued_on = req_date(body, "issued_on")
    review_by = req_date(body, "review_by_date")
    tags = req_str_list(body, "coverage_tags")
    bad = [t for t in tags if t not in COVERAGE_TAGS]
    if bad:
        raise_error(ERR_VALIDATION, f"invalid coverage tag(s): {', '.join(bad)}")
    if not REQUIRED_TAGS.issubset(set(tags)):
        raise_error(ERR_INCOMPLETE_COVERAGE,
                    "coverage_tags must include FLOOR_PLANS and ACCESS_POINTS")
    if parse_date(review_by) <= CLOCK.today():
        raise_error(ERR_VALIDATION, "review_by_date must be later than today")

    # Cascade: prior CURRENT document at the site -> SUPERSEDED
    for doc in db["site_plan_documents"].values():
        if doc["site_id"] == site_id and doc["status"] == "CURRENT":
            apply_changes(doc, {"status": "SUPERSEDED"})

    rec = new_record("site_plan_documents", {
        "site_id": site_id,
        "document_title": title,
        "issued_on": issued_on,
        "review_by_date": review_by,
        "coverage_tags": list(tags),
        "status": "CURRENT",
    })
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/site-plan-documents")
def list_site_plans(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {"site_id": rid, "status": request.args.get("status")}
    return list_query("site_plan_documents", filters)
