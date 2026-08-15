"""PublicHearing and Objection endpoints (§3.4)."""
from datetime import timedelta

from flask import Blueprint

import errors
import shape
import services
from envelope import ok_object
from helpers import get_or_404, list_response, sort_created
from security import ALL_ROLES, OWNER_READ_ROLES, authenticate, require_role
from serializers import ser_hearing, ser_objection
from store import STORE, new_id, now, touch

bp = Blueprint("hearings", __name__)


def _hearing_or_404(hid):
    return get_or_404("hearings", hid, errors.HEARING_NOT_FOUND, "Hearing not found")


def _objection_or_404(oid):
    return get_or_404("objections", oid, errors.OBJECTION_NOT_FOUND, "Objection not found")


@bp.route("/hearings", methods=["POST"])
def create_hearing():
    body = shape.get_body()
    district_id = shape.req_str(body, "district_id")
    hearing_date = shape.req_iso_datetime(body, "hearing_date")
    venue = shape.req_str(body, "venue")
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    d = get_or_404("districts", district_id, errors.DISTRICT_NOT_FOUND,
                   "District not found")
    if d["status"] != "SCOPING":
        errors.raise_err(errors.DISTRICT_NOT_IN_SCOPING,
                         "A hearing may only be scheduled while the district is in SCOPING")
    approved = next((e for e in STORE.estimates.values()
                     if e["district_id"] == district_id and e["status"] == "APPROVED"),
                    None)
    if approved is None:
        errors.raise_err(errors.NO_APPROVED_ESTIMATE,
                         "An APPROVED cost estimate is required before scheduling a hearing")
    if hearing_date < now() + timedelta(days=10):
        errors.raise_err(errors.HEARING_NOTICE_TOO_SHORT,
                         "hearing_date must be at least 10 days in the future")
    new_day = hearing_date.date()
    for h in STORE.hearings.values():
        if (h["status"] in ("SCHEDULED", "HELD") and h["venue"] == venue
                and h["hearing_date"].date() == new_day):
            errors.raise_err(errors.VENUE_DATE_CONFLICT,
                             "The venue already hosts a hearing on that date")
    # lock the approved estimate and build the preliminary roll
    d["approved_estimate_id"] = approved["id"]
    services.run_preliminary_allocation(d)
    ts = now()
    h = {
        "id": new_id(),
        "district_id": district_id,
        "hearing_date": hearing_date,
        "venue": venue,
        "status": "SCHEDULED",
        "objection_window_end": hearing_date + timedelta(days=15),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("hearings", h)
    d["status"] = "HEARING_SCHEDULED"
    touch(d)
    return ok_object(ser_hearing(h), 201)


@bp.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    return ok_object(ser_hearing(_hearing_or_404(hid)))


@bp.route("/hearings/<hid>/record-held", methods=["POST"])
def record_held(hid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    h = _hearing_or_404(hid)
    if h["status"] != "SCHEDULED":
        errors.raise_err(errors.HEARING_NOT_SCHEDULED,
                         "Only a SCHEDULED hearing can be recorded as held")
    if now() < h["hearing_date"]:
        errors.raise_err(errors.HEARING_DATE_NOT_REACHED,
                         "The hearing date has not been reached")
    h["status"] = "HELD"
    touch(h)
    d = STORE.districts[h["district_id"]]
    if d["status"] == "HEARING_SCHEDULED":
        d["status"] = "OBJECTION_WINDOW"
    touch(d)
    return ok_object(ser_hearing(h))


@bp.route("/hearings/<hid>/objections", methods=["GET"])
def hearing_objections(hid):
    ctx = authenticate()
    require_role(ctx, OWNER_READ_ROLES)
    _hearing_or_404(hid)
    records = [o for o in STORE.objections.values() if o["hearing_id"] == hid]
    return list_response(sort_created(records), ser_objection, paginated=False)


# --- objections ---

@bp.route("/objections", methods=["POST"])
def create_objection():
    body = shape.get_body()
    hearing_id = shape.req_str(body, "hearing_id")
    parcel_id = shape.req_str(body, "parcel_id")
    grounds = shape.req_str(body, "grounds")
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    h = _hearing_or_404(hearing_id)
    parcel = get_or_404("parcels", parcel_id, errors.PARCEL_NOT_FOUND,
                        "Parcel not found")
    if parcel["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the parcel's owner of record may file an objection")
    if now() > h["objection_window_end"]:
        errors.raise_err(errors.OBJECTION_WINDOW_CLOSED,
                         "The objection window has closed")
    if parcel["district_id"] != h["district_id"]:
        errors.raise_err(errors.PARCEL_NOT_IN_DISTRICT,
                         "Parcel does not belong to the hearing's district")
    if parcel["exempt"] or parcel["status"] != "ACTIVE":
        errors.raise_err(errors.INELIGIBLE_PARCEL,
                         "Exempt or removed parcels cannot be objected")
    if any(o["hearing_id"] == hearing_id and o["parcel_id"] == parcel_id
           and o["status"] in ("FILED", "UNDER_REVIEW")
           for o in STORE.objections.values()):
        errors.raise_err(errors.DUPLICATE_OBJECTION,
                         "Parcel already has a live objection on this hearing")
    ts = now()
    o = {
        "id": new_id(),
        "district_id": h["district_id"],
        "hearing_id": hearing_id,
        "parcel_id": parcel_id,
        "owner_id": ctx.user_id,
        "grounds": grounds,
        "status": "FILED",
        "filed_at": ts,
        "reviewed_by": None,
        "adjudicated_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    STORE.put("objections", o)
    return ok_object(ser_objection(o), 201)


@bp.route("/objections/<oid>", methods=["GET"])
def get_objection(oid):
    ctx = authenticate()
    require_role(ctx, ALL_ROLES)
    return ok_object(ser_objection(_objection_or_404(oid)))


@bp.route("/objections/<oid>/start-review", methods=["POST"])
def start_review(oid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    o = _objection_or_404(oid)
    if o["status"] != "FILED":
        errors.raise_err(errors.OBJECTION_NOT_FILED,
                         "Objection must be FILED to start review")
    o["status"] = "UNDER_REVIEW"
    o["reviewed_by"] = ctx.user_id
    touch(o)
    return ok_object(ser_objection(o))


@bp.route("/objections/<oid>/sustain", methods=["POST"])
def sustain(oid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    o = _objection_or_404(oid)
    if o["status"] != "UNDER_REVIEW":
        errors.raise_err(errors.OBJECTION_NOT_UNDER_REVIEW,
                         "Objection must be UNDER_REVIEW to sustain")
    d = STORE.districts[o["district_id"]]
    if d["status"] != "OBJECTION_WINDOW":
        errors.raise_err(errors.DISTRICT_NOT_IN_OBJECTION_WINDOW,
                         "District must be in OBJECTION_WINDOW")
    # 3-hop cascade: parcel REMOVED -> its PRELIMINARY assessment REMOVED
    # -> roll reallocated over the remaining ACTIVE non-exempt parcels
    parcel = STORE.parcels.get(o["parcel_id"])
    if parcel and parcel["status"] == "ACTIVE":
        parcel["status"] = "REMOVED"
        touch(parcel)
        for a in STORE.assessments.values():
            if a["parcel_id"] == parcel["id"] and a["status"] == "PRELIMINARY":
                a["status"] = "REMOVED"
                touch(a)
    services.rerun_preliminary_allocation(d)
    o["status"] = "SUSTAINED"
    o["adjudicated_at"] = now()
    touch(o)
    return ok_object(ser_objection(o))


@bp.route("/objections/<oid>/overrule", methods=["POST"])
def overrule(oid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["CityClerk"])
    o = _objection_or_404(oid)
    if o["status"] != "UNDER_REVIEW":
        errors.raise_err(errors.OBJECTION_NOT_UNDER_REVIEW,
                         "Objection must be UNDER_REVIEW to overrule")
    d = STORE.districts[o["district_id"]]
    if d["status"] != "OBJECTION_WINDOW":
        errors.raise_err(errors.DISTRICT_NOT_IN_OBJECTION_WINDOW,
                         "District must be in OBJECTION_WINDOW")
    o["status"] = "OVERRULED"
    o["adjudicated_at"] = now()
    touch(o)
    return ok_object(ser_objection(o))


@bp.route("/objections/<oid>/withdraw", methods=["POST"])
def withdraw_objection(oid):
    shape.get_body()
    ctx = authenticate()
    require_role(ctx, ["PropertyOwner"])
    o = _objection_or_404(oid)
    if o["owner_id"] != ctx.user_id:
        errors.raise_err(errors.NOT_RESOURCE_OWNER,
                         "Only the filing owner may withdraw the objection")
    if o["status"] != "FILED":
        errors.raise_err(errors.OBJECTION_NOT_FILED,
                         "Only a FILED objection may be withdrawn")
    o["status"] = "WITHDRAWN"
    touch(o)
    return ok_object(ser_objection(o))
