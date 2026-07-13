"""NPS surveys: issue, list, read, public submission."""

from datetime import timedelta

from flask import Blueprint, g, request

import calc
import store
import validation as v
from auth import endpoint, resolve_location, resolve_survey
from envelope import created, ok, paginate
from errors import err
from services import add_alert, assert_not_frozen, recompute_nps, touch

bp = Blueprint("surveys", __name__)

SURVEY_STATUSES = ("PENDING", "SUBMITTED")
SURVEY_TTL_DAYS = 14


@bp.post("/reputation/locations/<location_id>/surveys")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def create_survey(location_id):
    loc = resolve_location(location_id)
    data = v.body()

    # priority 5 -- body-reference existence and tenancy
    contact = None
    raw_contact_id = data.get("contact_id")
    if isinstance(raw_contact_id, str):
        contact = store.contacts.get(raw_contact_id)
        if contact is None or contact["business_id"] != loc["business_id"]:
            raise err("ERR_CONTACT_NOT_FOUND")

    v.req_str(data, "contact_id")
    if contact is None:
        raise err("ERR_INVALID_REQUEST", "Field 'contact_id' must be a string.")

    assert_not_frozen(loc)

    rec = store.base_record()
    rec.update({
        "location_id": location_id,
        "contact_id": contact["id"],
        "status": "PENDING",
        "nps_score": None,
        "nps_category": None,
        "comment": None,
        "submitted_at": None,
        "expires_at": rec["created_at"] + timedelta(days=SURVEY_TTL_DAYS),
    })
    store.surveys[rec["id"]] = rec
    return created(store.survey_out(rec))


@bp.get("/reputation/surveys")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_surveys():
    status = v.enum_filter("status", SURVEY_STATUSES)
    location_id = request.args.get("location_id")
    contact_id = request.args.get("contact_id")

    rows = list(store.surveys.values())
    if location_id is not None:
        if location_id not in store.locations:
            raise err("ERR_LOCATION_NOT_FOUND")
        rows = [s for s in rows if s["location_id"] == location_id]
    if contact_id is not None:
        if contact_id not in store.contacts:
            raise err("ERR_CONTACT_NOT_FOUND")
        rows = [s for s in rows if s["contact_id"] == contact_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]

    if g.role == "BusinessOwner":
        rows = [s for s in rows
                if store.locations[s["location_id"]]["business_id"] == g.user_id]
    elif g.role == "LocationManager":
        rows = [s for s in rows if s["location_id"] == g.user_id]

    return paginate(store.by_created(rows), store.survey_out)


@bp.get("/reputation/surveys/<survey_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "Anonymous"])
def get_survey(survey_id):
    survey, _loc = resolve_survey(survey_id)
    return ok(store.survey_out(survey))


@bp.post("/reputation/surveys/<survey_id>/submit")
@endpoint(["Anonymous", "PlatformAdmin"])
def submit_survey(survey_id):
    survey, loc = resolve_survey(survey_id)
    data = v.body()
    score = v.req_int(data, "nps_score", minimum=0, maximum=10)
    comment = v.opt_str(data, "comment")

    # priority 8 -- FROZEN
    assert_not_frozen(loc)

    # priority 10 -- state legality
    if survey["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")

    # priority 11 -- expiry: submission must happen strictly before expires_at
    if store.now() >= survey["expires_at"]:
        raise err("ERR_SURVEY_EXPIRED")

    survey["status"] = "SUBMITTED"
    survey["nps_score"] = score
    survey["nps_category"] = calc.nps_category(score)
    survey["comment"] = comment
    survey["submitted_at"] = store.now()
    touch(survey)

    if survey["nps_category"] == "DETRACTOR":
        add_alert(loc["id"], "NPS_DETRACTOR",
                  "detractor survey submitted (score %d)" % score, survey["id"])

    recompute_nps(loc)
    return ok(store.survey_out(survey))
