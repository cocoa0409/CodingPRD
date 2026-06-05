"""MadridApplication routes (PRD §3.7)."""

from flask import Blueprint

from db import db, parse_iso, iso_from_datetime
from errors import raise_api
from middleware import require_roles
from response import success
from services import models, calc
from services.body import get_json_body, require_nonempty_string, require_string_array
from services.dateutil import add_years

bp = Blueprint("madrid", __name__)

CERTIFIABLE_BASIC_STATES = {
    "FILED",
    "UNDER_EXAMINATION",
    "OFFICE_ACTION_ISSUED",
    "PUBLISHED",
    "ALLOWED",
    "REGISTERED",
}


@bp.post("/madrid-applications")
@require_roles("Attorney", "Applicant")
def create_madrid(_user_id, _role):
    body = get_json_body()
    basic_application_id = require_nonempty_string(body, "basic_application_id")
    designated_countries = require_string_array(body, "designated_countries")

    app = models.get_or_404(db.applications, basic_application_id, "TrademarkApplication")

    # Business constraint (priority 17): non-empty, no duplicates, excludes 'US',
    # each a 2-uppercase-letter code.
    if len(designated_countries) == 0:
        raise_api("ERR_MADRID_COUNTRIES_INVALID", "designated_countries must be non-empty")
    if len(set(designated_countries)) != len(designated_countries):
        raise_api("ERR_MADRID_COUNTRIES_INVALID", "designated_countries has duplicates")
    for c in designated_countries:
        if not (len(c) == 2 and c.isalpha() and c.isupper()):
            raise_api(
                "ERR_MADRID_COUNTRIES_INVALID",
                "each designated country must be 2 uppercase letters",
            )
    if "US" in designated_countries:
        raise_api("ERR_MADRID_COUNTRIES_INVALID", "designated_countries must not include US")

    # dependency_end_at = basic_application.filed_at + DEPENDENCY_YEARS.
    if app.get("filed_at") is None:
        raise_api("ERR_MADRID_COUNTRIES_INVALID", "basic application has not been filed")
    dep_end = add_years(parse_iso(app["filed_at"]), calc.DEPENDENCY_YEARS)

    rec = models.make_record({
        "basic_application_id": basic_application_id,
        "designated_countries": list(designated_countries),
        "status": "PENDING_CERTIFICATION",
        "dependency_end_at": iso_from_datetime(dep_end),
        "fee_cents": 0,
    })
    db.madrid_applications[rec["id"]] = rec
    return success(models.ser_madrid(rec), 201)


@bp.get("/madrid-applications/<rid>")
@require_roles("Attorney", "Applicant", "Examiner")
def get_madrid(rid, _user_id, _role):
    rec = models.get_or_404(db.madrid_applications, rid, "MadridApplication")
    return success(models.ser_madrid(rec), 200)


@bp.post("/madrid-applications/<rid>/certify")
@require_roles("Examiner")
def certify_madrid(rid, _user_id, _role):
    rec = models.get_or_404(db.madrid_applications, rid, "MadridApplication")
    if rec["status"] != "PENDING_CERTIFICATION":
        raise_api("ERR_INVALID_STATE", "Madrid application is not PENDING_CERTIFICATION")
    basic = db.applications.get(rec["basic_application_id"])
    if basic is None or basic["status"] not in CERTIFIABLE_BASIC_STATES:
        raise_api("ERR_INVALID_STATE", "Basic application is not in a certifiable state")

    rec["fee_cents"] = calc.madrid_fee(rec["designated_countries"])
    rec["status"] = "CERTIFIED"
    models.touch(rec)
    return success(models.ser_madrid(rec), 200)


@bp.post("/madrid-applications/<rid>/forward")
@require_roles("Examiner")
def forward_madrid(rid, _user_id, _role):
    rec = models.get_or_404(db.madrid_applications, rid, "MadridApplication")
    if rec["status"] != "CERTIFIED":
        raise_api("ERR_INVALID_STATE", "Madrid application is not CERTIFIED")
    rec["status"] = "FORWARDED_TO_WIPO"
    models.touch(rec)
    return success(models.ser_madrid(rec), 200)
