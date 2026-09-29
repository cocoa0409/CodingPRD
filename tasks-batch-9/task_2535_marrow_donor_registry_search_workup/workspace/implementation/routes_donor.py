"""Donor profiles, calendar windows and follow-ups (PRD 3.2, 3.9)."""

from flask import Blueprint

import calc
import cascades
import serializers
import validate as v
from auth import (ROLE_CENTER, ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_LIAISON,
                  ROLE_OPS, authenticate)
from envelope import read_pagination, success
from errors import ApiError
from guards import arg, find, render_list
from store import db, new_append_only_row, new_row, ordered, touch

bp = Blueprint("registry_donors", __name__)

AVAILABILITY = ("AVAILABLE", "TEMPORARILY_DEFERRED", "PERMANENTLY_DEFERRED",
                "WITHDRAWN")
METHODS = ("PBSC", "MARROW")
CLIENT_WINDOW_REASONS = ("PERSONAL", "MEDICAL_HOLD")
EVENT_TYPES = ("DAY_7_CONTACT", "DAY_30_CONTACT", "ONE_YEAR_CONTACT",
               "ADVERSE_EVENT")


@bp.get("/registry/donors")
def list_donors():
    authenticate(ROLE_OPS, ROLE_LIAISON, ROLE_COORDINATOR, ROLE_DIRECTOR)
    limit, offset = read_pagination()
    registry_id = arg("registry_id")
    availability = arg("availability_status")
    rows = []
    for row in db.donors.values():
        if registry_id is not None and row["registry_id"] != registry_id:
            continue
        if availability is not None and row["availability_status"] != availability:
            continue
        rows.append(row)
    return render_list(rows, serializers.donor_dict, limit, offset)


@bp.get("/registry/donors/<did>")
def get_donor(did):
    authenticate(ROLE_OPS, ROLE_LIAISON, ROLE_COORDINATOR, ROLE_DIRECTOR)
    row = find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    return success(serializers.donor_dict(row))


@bp.post("/registry/donors")
def create_donor():
    actor = authenticate(ROLE_LIAISON)
    body = v.read_body()
    registry_id = v.req_str(body, "registry_id", 1)
    donor_code = v.req_str(body, "donor_code", 1, 24)
    age_years = v.req_int(body, "age_years", 17, 75)
    sex = v.req_enum(body, "sex", ("M", "F"))
    weight_kg = v.req_num(body, "weight_kg", gt=0, max_dp=1)
    cmv_status = v.req_enum(body, "cmv_status", ("NEGATIVE", "POSITIVE"))
    ambiguous = v.req_enum_list(body, "ambiguous_loci", v.LOCI, allow_empty=True,
                                default=[], required=False)
    typing = v.hla_typing(body, "hla_typing_registry", tuple(ambiguous))
    methods = v.req_enum_list(body, "consented_methods", METHODS)
    priors = v.opt_int(body, "prior_donation_count", 0, 5, 0)
    availability = v.opt_enum(body, "availability_status", AVAILABILITY,
                              "AVAILABLE")

    registry = find(db.registries, registry_id, "ERR_REGISTRY_NOT_FOUND")
    if registry["id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    for existing in db.donors.values():
        if existing["registry_id"] == registry_id and \
                existing["donor_code"] == donor_code:
            raise ApiError("ERR_DONOR_CODE_ALREADY_EXISTS")

    row = new_row(
        registry_id=registry_id,
        donor_code=donor_code,
        age_years=age_years,
        sex=sex,
        weight_kg=weight_kg,
        cmv_status=cmv_status,
        hla_typing_registry=typing,
        ambiguous_loci=ambiguous,
        consented_methods=methods,
        prior_donation_count=priors,
        availability_status=availability,
        deferral_until=None,
        last_followup_at=None,
    )
    db.donors[row["id"]] = row
    return success(serializers.donor_dict(row), 201)


@bp.get("/registry/donors/<did>/unavailability-windows")
def list_windows(did):
    authenticate(ROLE_OPS, ROLE_LIAISON, ROLE_CENTER, ROLE_DIRECTOR)
    limit, offset = read_pagination()
    find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    status = arg("status")
    reason = arg("reason")
    rows = []
    for row in db.windows.values():
        if row["donor_id"] != did:
            continue
        if status is not None and row["status"] != status:
            continue
        if reason is not None and row["reason"] != reason:
            continue
        rows.append(row)
    return render_list(rows, serializers.window_dict, limit, offset)


@bp.post("/registry/donors/<did>/unavailability-windows")
def create_window(did):
    actor = authenticate(ROLE_LIAISON)
    body = v.read_body()
    date_from = v.req_date(body, "date_from")
    date_to = v.req_date(body, "date_to")
    reason = v.req_enum(body, "reason", CLIENT_WINDOW_REASONS)

    donor = find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    if donor["registry_id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    if date_to < date_from:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    for window in cascades.active_windows(donor["id"]):
        if calc.windows_conflict(date_from, date_to,
                                 window["date_from"], window["date_to"]):
            raise ApiError("ERR_DONOR_CALENDAR_CONFLICT")

    row = cascades.create_window(donor, date_from, date_to, reason)
    return success(serializers.window_dict(row), 201)


@bp.delete("/registry/donors/<did>/unavailability-windows/<wid>")
def release_window(did, wid):
    actor = authenticate(ROLE_LIAISON)
    donor = find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    window = db.windows.get(wid)
    if window is None or window["donor_id"] != donor["id"]:
        raise ApiError("ERR_UNAVAILABILITY_WINDOW_NOT_FOUND")
    if donor["registry_id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    if window["status"] != "ACTIVE":
        raise ApiError("ERR_WINDOW_NOT_RELEASABLE")
    if window["reason"] == "COLLECTION_WINDOW":
        raise ApiError("ERR_WINDOW_NOT_RELEASABLE")
    if window["reason"] == "DEFERRAL":
        until = donor["deferral_until"]
        if until is None or db.today() <= until:
            raise ApiError("ERR_WINDOW_NOT_RELEASABLE")

    was_deferral = window["reason"] == "DEFERRAL"
    cascades.release_window(window)

    if was_deferral and donor["availability_status"] == "TEMPORARILY_DEFERRED":
        remaining = [w for w in cascades.active_windows(donor["id"])
                     if w["reason"] == "DEFERRAL"]
        if not remaining:
            donor["availability_status"] = "AVAILABLE"
            donor["deferral_until"] = None
            touch(donor)
    return "", 204


@bp.get("/registry/donors/<did>/follow-ups")
def list_followups(did):
    authenticate(ROLE_OPS, ROLE_LIAISON, ROLE_DIRECTOR)
    limit, offset = read_pagination()
    find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    event_type = arg("event_type")
    rows = []
    for row in db.followups.values():
        if row["donor_id"] != did:
            continue
        if event_type is not None and row["event_type"] != event_type:
            continue
        rows.append(row)
    return render_list(rows, serializers.followup_dict, limit, offset)


@bp.post("/registry/donors/<did>/follow-ups")
def create_followup(did):
    actor = authenticate(ROLE_LIAISON, ROLE_DIRECTOR)
    body = v.read_body()
    event_type = v.req_enum(body, "event_type", EVENT_TYPES)
    severity = v.req_int(body, "severity_grade", 0, 5)
    description = v.opt_str(body, "description", 0, 400, None, None)

    donor = find(db.donors, did, "ERR_DONOR_NOT_FOUND")
    if actor.is_liaison and donor["registry_id"] != actor.user_id:
        raise ApiError("ERR_REGISTRY_SCOPE_VIOLATION")

    if event_type == "ADVERSE_EVENT":
        if severity < 1:
            raise ApiError("ERR_ADVERSE_EVENT_GRADE_INVALID")
    elif severity != 0:
        raise ApiError("ERR_ADVERSE_EVENT_GRADE_INVALID")

    triggered = (event_type == "ADVERSE_EVENT"
                 and severity >= calc.ADVERSE_EVENT_DEFERRAL_GRADE)

    row = new_append_only_row(
        donor_id=donor["id"],
        event_type=event_type,
        severity_grade=severity,
        description=description,
        reported_at=db.now(),
        triggered_permanent_deferral=triggered,
    )
    db.followups[row["id"]] = row

    latest = None
    for existing in db.followups.values():
        if existing["donor_id"] != donor["id"]:
            continue
        if latest is None or existing["reported_at"] > latest:
            latest = existing["reported_at"]
    donor["last_followup_at"] = latest
    touch(donor)

    if triggered:
        donor["availability_status"] = "PERMANENTLY_DEFERRED"
        donor["deferral_until"] = None
        touch(donor)
        cascades.exclude_donor_candidates(donor)

    return success(serializers.followup_dict(row), 201)


@bp.get("/registry/collection-bookings/<bid>/unavailability-windows")
def list_booking_windows(bid):
    authenticate(ROLE_CENTER, ROLE_OPS, ROLE_LIAISON, ROLE_DIRECTOR)
    limit, offset = read_pagination()
    find(db.bookings, bid, "ERR_BOOKING_NOT_FOUND")
    status = arg("status")
    rows = []
    for row in ordered(list(db.windows.values())):
        if row["source_booking_id"] != bid:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return render_list(rows, serializers.window_dict, limit, offset)
