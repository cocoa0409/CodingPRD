"""Site visits with weighted scoring and the MODELED<->SCORED bubble."""

from decimal import Decimal

from flask import Blueprint

from db import db
from errors import not_found, invalid_state
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import new_record, touch, visit_total_score, ser_visit
from util import get_body, req_int, req_date, fk_exists, list_response

bp = Blueprint("visits", __name__)

PASS_MIN = Decimal("70.00")


@bp.post("/api/site-visits")
def create_visit():
    require_roles("RealEstateAnalyst")
    body = get_body(required=True)
    site = fk_exists(body, "site_id", db.sites)
    visited_raw, _ = req_date(body, "visited_on")
    visibility = req_int(body, "visibility_score", min_v=0, max_v=100)
    access = req_int(body, "access_score", min_v=0, max_v=100)
    parking = req_int(body, "parking_score", min_v=0, max_v=100)
    cotenancy = req_int(body, "cotenancy_score", min_v=0, max_v=100)
    if site["site_status"] not in ("MODELED", "SCORED"):
        raise invalid_state(
            f"Site in {site['site_status']} does not accept site visits")
    total = visit_total_score(visibility, access, parking, cotenancy)
    # Only one visit stands per site: supersede the prior SUBMITTED visit.
    for v in db.visits.values():
        if v["site_id"] == site["id"] and v["visit_status"] == "SUBMITTED":
            v["visit_status"] = "SUPERSEDED"
            touch(v)
    rec = new_record()
    rec.update({
        "site_id": site["id"],
        "visited_on": visited_raw,
        "visibility_score": visibility,
        "access_score": access,
        "parking_score": parking,
        "cotenancy_score": cotenancy,
        "total_score": total,
        "visit_status": "SUBMITTED",
    })
    db.visits[rec["id"]] = rec
    # The advance gate compares against the rounded 2dp value.
    if total >= PASS_MIN and site["site_status"] == "MODELED":
        site["site_status"] = "SCORED"
        touch(site)
    elif total < PASS_MIN and site["site_status"] == "SCORED":
        # Conditional regression: visit recorded, site loses SCORED standing.
        site["site_status"] = "MODELED"
        touch(site)
    return ok_object(ser_visit(rec), status=201)


@bp.get("/api/site-visits")
def list_visits():
    require_roles(*ALL_API_ROLES)
    return list_response(db.visits.values(), ser_visit,
                         filters=["site_id", "visit_status"])


@bp.get("/api/site-visits/<vid>")
def get_visit(vid):
    require_roles(*ALL_API_ROLES)
    rec = db.visits.get(vid)
    if rec is None:
        raise not_found(f"SiteVisit not found: {vid}")
    return ok_object(ser_visit(rec))
