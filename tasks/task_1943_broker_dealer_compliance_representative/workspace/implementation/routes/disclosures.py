"""DisclosureEvent endpoints (PRD 3.6): filing, timeliness, the SD cascade."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DISCLOSURE_INVALID_STATE,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.cascade import sd_ack_cascade
from services.core import new_record, public, touch
from util import add_days, clock_ts, parse_date, today
from validate import (
    get_body, opt_str, req_date, req_enum, require_path_resource, require_ref,
)

bp = Blueprint("disclosures", __name__)

EVENT_TYPES = ("FELONY_CONVICTION", "SECURITIES_MISDEMEANOR", "REGULATORY_BAR",
               "CUSTOMER_AWARD", "CIVIL_JUDGMENT", "BANKRUPTCY")
SD_TRIGGER_TYPES = ("FELONY_CONVICTION", "SECURITIES_MISDEMEANOR", "REGULATORY_BAR")


@bp.post("/disclosure-events")
def create_disclosure():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: FK existence
    rep = require_ref("representatives", body.get("rep_id"), "rep_id")
    # Priority 8: schema
    event_type = req_enum(body, "event_type", EVENT_TYPES)
    event_date = req_date(body, "event_date")
    description = opt_str(body, "description", default="")
    if rep is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: rep_id")

    rec = new_record("disclosure_events", {
        "rep_id": rep["id"],
        "event_type": event_type,
        "event_date": event_date,
        "description": description,
        "is_sd_trigger": event_type in SD_TRIGGER_TYPES,
        "filing_deadline": add_days(parse_date(event_date), 30).isoformat(),
        "filed_at": None,
        "is_late": None,
        "source_complaint_id": None,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/disclosure-events")
def list_disclosures():
    return list_response("disclosure_events", filters={
        "rep_id": request.args.get("rep_id"),
        "event_type": request.args.get("event_type"),
        "status": request.args.get("status"),
    })


@bp.get("/disclosure-events/<rid>")
def get_disclosure(rid):
    return get_one("disclosure_events", rid)


@bp.post("/disclosure-events/<rid>/file")
def file_disclosure(rid):
    authorized(["CompliancePrincipal"])
    disc = require_path_resource("disclosure_events", rid)
    if disc["status"] != "DRAFT":
        raise_error(ERR_DISCLOSURE_INVALID_STATE, "file is allowed only from DRAFT")
    disc["filed_at"] = clock_ts()
    disc["is_late"] = today() > parse_date(disc["filing_deadline"])
    disc["status"] = "FILED"
    touch(disc)
    return success_object(public(disc))


@bp.post("/disclosure-events/<rid>/acknowledge")
def acknowledge_disclosure(rid):
    authorized(["CompliancePrincipal"])
    disc = require_path_resource("disclosure_events", rid)
    if disc["status"] != "FILED":
        raise_error(ERR_DISCLOSURE_INVALID_STATE,
                    "acknowledge is allowed only from FILED")
    disc["status"] = "ACKNOWLEDGED"
    touch(disc)
    # Non-trigger events acknowledge quietly; SD triggers fire the cascade
    if disc["is_sd_trigger"]:
        rep = db["representatives"].get(disc["rep_id"])
        if rep is not None:
            sd_ack_cascade(rep)
    return success_object(public(disc))
