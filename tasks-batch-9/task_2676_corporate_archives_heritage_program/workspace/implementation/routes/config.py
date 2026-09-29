"""Retention schedules, the record series register, legal holds, appraisals."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, g

from core import add_calendar_years, clock, register, sorted_rows, store, touch
from errors import ApiError
from middleware import endpoint
from response import apply_filters, collection_response, object_response
from services import calc
from services.lookup import (
    accessions_of_series,
    active_holds_of_series,
    fetch,
    finding_aids_of_accession,
    items_of_series,
    refresh_current_screening_pointer,
    schedule_of_series,
    screenings_of_request,
)
from validation import (
    DISPOSITION_ACTIONS,
    SENSITIVITY_LEVELS,
    body,
    vbool,
    venum,
    vid,
    vinstant,
    vint,
    vnum,
    vstr,
)

bp = Blueprint("config", __name__)

READERS = ("ArchivesDirector", "Archivist", "LegalCounsel", "AccessServicesOfficer", "PreservationOfficer")
HOLD_READERS = ("ArchivesDirector", "Archivist", "LegalCounsel", "AccessServicesOfficer")
APPRAISAL_READERS = ("ArchivesDirector", "Archivist", "LegalCounsel")


# --- retention schedules ---------------------------------------------------


@bp.post("/retention-schedules")
@endpoint(("ArchivesDirector",))
def create_retention_schedule():
    payload = body()
    code = vstr(payload, "code", 3, 32)
    retention_years = vint(payload, "retention_years", 0, 200)
    disposition_action = venum(payload, "disposition_action", DISPOSITION_ACTIONS)
    legal_citation = vstr(payload, "legal_citation", 1, 200)
    # "a number from 0.00 to 100.00 carried to exactly two decimal places"
    threshold = float(calc.round_half_up(vnum(payload, "min_appraisal_score_for_permanent", 0, 100), 2))
    for existing in store.retention_schedules.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE_KEY", "Schedule code '%s' already exists." % code)
    row = register(
        store.retention_schedules,
        {
            "code": code,
            "retention_years": retention_years,
            "disposition_action": disposition_action,
            "legal_citation": legal_citation,
            "min_appraisal_score_for_permanent": threshold,
        },
        versioned=False,
    )
    return object_response(row, 201)


@bp.get("/retention-schedules")
@endpoint(READERS)
def list_retention_schedules():
    rows = apply_filters(
        sorted_rows(store.retention_schedules), {"disposition_action": "disposition_action"}
    )
    return collection_response(rows)


@bp.get("/retention-schedules/<resource_id>")
@endpoint(READERS)
def get_retention_schedule(resource_id):
    return object_response(fetch("retention_schedules", resource_id))


# --- record series ---------------------------------------------------------


def _retention_expiry(latest_record_year, retention_years):
    base = datetime(
        int(latest_record_year), 12, 31, 23, 59, 59, 0, tzinfo=timezone.utc
    )
    return add_calendar_years(base, retention_years)


@bp.post("/record-series")
@endpoint(("Archivist",))
def create_record_series():
    payload = body()
    title = vstr(payload, "title", 1, 200)
    business_unit = vstr(payload, "business_unit", 1, 64)
    retention_schedule_id = vid(payload, "retention_schedule_id")
    sensitivity_ceiling = venum(payload, "sensitivity_ceiling", SENSITIVITY_LEVELS)
    annual_volume_linear_feet = vint(payload, "annual_volume_linear_feet", 0, None)
    earliest = vint(payload, "earliest_record_year", 1800, 2100)
    latest = vint(payload, "latest_record_year", 1800, 2100)
    if earliest > latest:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'earliest_record_year' must not exceed 'latest_record_year'.",
        )
    schedule = fetch("retention_schedules", retention_schedule_id)
    row = register(
        store.record_series,
        {
            "title": title,
            "business_unit": business_unit,
            "retention_schedule_id": schedule["id"],
            "sensitivity_ceiling": sensitivity_ceiling,
            "annual_volume_linear_feet": annual_volume_linear_feet,
            "earliest_record_year": earliest,
            "latest_record_year": latest,
            "disposition_state": "ACTIVE",
            "legal_hold_active": False,
            "current_appraisal_id": None,
            "pre_hold_disposition_state": None,
            "disposition_certificate_reference": None,
            "blocked_access_request_count": 0,
            "retention_expiry_utc": _retention_expiry(latest, schedule["retention_years"]),
        },
    )
    return object_response(row, 201)


@bp.get("/record-series")
@endpoint(READERS)
def list_record_series():
    rows = apply_filters(
        sorted_rows(store.record_series),
        {
            "retention_schedule_id": "retention_schedule_id",
            "current_appraisal_id": "current_appraisal_id",
            "disposition_state": "disposition_state",
            "business_unit": "business_unit",
        },
    )
    return collection_response(rows)


@bp.get("/record-series/<resource_id>")
@endpoint(READERS)
def get_record_series(resource_id):
    return object_response(fetch("record_series", resource_id))


@bp.post("/record-series/<resource_id>/dispose")
@endpoint(("ArchivesDirector",))
def dispose_record_series(resource_id):
    payload = body()
    certificate = vstr(payload, "disposition_certificate_reference", 1, None)
    series = fetch("record_series", resource_id)
    # rung 12 state guard
    if series["disposition_state"] != "ELIGIBLE_FOR_DISPOSITION":
        raise ApiError("ERR_SERIES_STATE_INVALID")
    # rung 15 series not frozen
    if series["legal_hold_active"] or series["disposition_state"] == "SUSPENDED":
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")
    # rung 16 series not permanent
    if series["disposition_state"] == "PERMANENT":
        raise ApiError("ERR_SERIES_PERMANENT")
    # rung 19 retention elapsed
    if clock.now() < series["retention_expiry_utc"]:
        raise ApiError("ERR_RETENTION_PERIOD_NOT_ELAPSED")
    for item in items_of_series(series["id"]):
        if item["status"] == "ON_LOAN":
            raise ApiError(
                "ERR_ITEM_STATE_INVALID",
                "An archival item under this series is still ON_LOAN.",
            )
    series["disposition_certificate_reference"] = certificate
    series["disposition_state"] = "DISPOSED"
    touch(series)
    for accession in accessions_of_series(series["id"]):
        for aid in finding_aids_of_accession(accession["id"]):
            if aid["status"] == "PUBLISHED":
                aid["status"] = "WITHDRAWN"
                touch(aid)
    return object_response(series)


# --- legal holds -----------------------------------------------------------


@bp.post("/legal-holds")
@endpoint(("LegalCounsel",))
def create_legal_hold():
    payload = body()
    matter_number = vstr(payload, "matter_number", 3, 64)
    record_series_id = vid(payload, "record_series_id")
    effective = vinstant(payload, "effective_from")
    series = fetch("record_series", record_series_id)
    for existing in store.legal_holds.values():
        if existing["matter_number"] == matter_number:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE_KEY",
                "Matter number '%s' already exists." % matter_number,
            )
    row = register(
        store.legal_holds,
        {
            "matter_number": matter_number,
            "record_series_id": series["id"],
            "effective_from": effective,
            "status": "DRAFT",
            "issued_by": g.user_id,
            "activated_at": None,
            "released_at": None,
            "release_note": None,
            "suspended_access_request_count": 0,
        },
    )
    return object_response(row, 201)


@bp.get("/legal-holds")
@endpoint(HOLD_READERS)
def list_legal_holds():
    rows = apply_filters(
        sorted_rows(store.legal_holds),
        {"record_series_id": "record_series_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/legal-holds/<resource_id>")
@endpoint(HOLD_READERS)
def get_legal_hold(resource_id):
    return object_response(fetch("legal_holds", resource_id))


BLOCKABLE_REQUEST_STATUSES = ("SUBMITTED", "SCREENING", "CHANGES_REQUESTED")


@bp.post("/legal-holds/<resource_id>/activate")
@endpoint(("LegalCounsel",))
def activate_legal_hold(resource_id):
    hold = fetch("legal_holds", resource_id)
    if hold["status"] != "DRAFT":
        raise ApiError("ERR_HOLD_STATE_INVALID")
    if active_holds_of_series(hold["record_series_id"], exclude_id=hold["id"]):
        raise ApiError("ERR_SERIES_ALREADY_ON_HOLD")
    series = store.record_series[hold["record_series_id"]]
    hold["status"] = "ACTIVE"
    hold["activated_at"] = clock.now()

    # hop one: suspend the series, capturing the state it was in.
    series["pre_hold_disposition_state"] = series["disposition_state"]
    series["disposition_state"] = "SUSPENDED"
    series["legal_hold_active"] = True
    touch(series)

    # hop two: block the series' live access requests.
    blocked = []
    requests = [
        row
        for row in sorted_rows(store.access_requests)
        if row["record_series_id"] == series["id"]
        and row["status"] in BLOCKABLE_REQUEST_STATUSES
    ]
    for request_row in requests:
        was_screening = request_row["status"] == "SCREENING"
        request_row["status"] = "BLOCKED"
        request_row["legal_hold_blocked"] = True
        series["blocked_access_request_count"] += 1
        touch(request_row)
        blocked.append((request_row, was_screening))
    hold["suspended_access_request_count"] = len(blocked)

    # hop three: supersede the open screenings under requests left mid-screening.
    for request_row, was_screening in blocked:
        if not was_screening:
            continue
        for screening in screenings_of_request(request_row["id"]):
            if screening["status"] == "OPEN":
                screening["status"] = "SUPERSEDED"
                screening["superseded_reason"] = "LEGAL_HOLD_BLOCK"
                touch(screening)
        refresh_current_screening_pointer(request_row)

    touch(hold)
    return object_response(hold)


@bp.post("/legal-holds/<resource_id>/release")
@endpoint(("LegalCounsel",))
def release_legal_hold(resource_id):
    payload = body()
    release_note = vstr(payload, "release_note", 1, None)
    hold = fetch("legal_holds", resource_id)
    if hold["status"] != "ACTIVE":
        raise ApiError("ERR_HOLD_STATE_INVALID")
    series = store.record_series[hold["record_series_id"]]
    hold["status"] = "RELEASED"
    hold["release_note"] = release_note
    hold["released_at"] = clock.now()
    touch(hold)
    if not active_holds_of_series(series["id"], exclude_id=hold["id"]):
        restored = series["pre_hold_disposition_state"]
        if restored is not None:
            series["disposition_state"] = restored
        series["pre_hold_disposition_state"] = None
        series["legal_hold_active"] = False
        for request_row in sorted_rows(store.access_requests):
            if request_row["record_series_id"] != series["id"]:
                continue
            if request_row["status"] != "BLOCKED" or not request_row["legal_hold_blocked"]:
                continue
            request_row["status"] = "SUBMITTED"
            request_row["legal_hold_blocked"] = False
            series["blocked_access_request_count"] -= 1
            touch(request_row)
        touch(series)
    return object_response(hold)


# --- appraisals ------------------------------------------------------------

SUPERSEDABLE_APPRAISAL_STATUSES = ("DRAFT", "SCREENED", "FINAL")


@bp.post("/appraisals")
@endpoint(("Archivist",))
def create_appraisal():
    payload = body()
    record_series_id = vid(payload, "record_series_id")
    informational_value = vint(payload, "informational_value", 0, 10)
    evidential_value = vint(payload, "evidential_value", 0, 10)
    brand_heritage_value = vint(payload, "brand_heritage_value", 0, 10)
    uniqueness_factor = vint(payload, "uniqueness_factor", 0, 10)
    provenance_verified = vbool(payload, "provenance_verified")
    expected_series_version = vint(payload, "expected_series_version", None, None)
    series = fetch("record_series", record_series_id)
    if expected_series_version != series["version"]:
        raise ApiError("ERR_STALE_SERIES_VERSION")
    row = register(
        store.appraisals,
        {
            "record_series_id": series["id"],
            "informational_value": informational_value,
            "evidential_value": evidential_value,
            "brand_heritage_value": brand_heritage_value,
            "uniqueness_factor": uniqueness_factor,
            "provenance_verified": provenance_verified,
            "status": "DRAFT",
            "appraised_by": g.user_id,
            "screening_score": None,
            "final_score": None,
            "recommended_disposition": None,
            "brand_heritage_counted": False,
            "superseded_by_appraisal_id": None,
        },
    )
    superseded_final = False
    for other in sorted_rows(store.appraisals):
        if other["id"] == row["id"] or other["record_series_id"] != series["id"]:
            continue
        if other["status"] not in SUPERSEDABLE_APPRAISAL_STATUSES:
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_appraisal_id"] = row["id"]
        touch(other)
        if series["current_appraisal_id"] == other["id"]:
            superseded_final = True
    if superseded_final:
        series["current_appraisal_id"] = None
    touch(series)
    return object_response(row, 201)


@bp.get("/appraisals")
@endpoint(APPRAISAL_READERS)
def list_appraisals():
    rows = apply_filters(
        sorted_rows(store.appraisals),
        {"record_series_id": "record_series_id", "status": "status"},
    )
    return collection_response(rows)


@bp.get("/appraisals/<resource_id>")
@endpoint(APPRAISAL_READERS)
def get_appraisal(resource_id):
    return object_response(fetch("appraisals", resource_id))


def _guard_series_not_frozen(series):
    if series["disposition_state"] == "SUSPENDED" or series["legal_hold_active"]:
        raise ApiError("ERR_SERIES_DISPOSITION_SUSPENDED")


@bp.post("/appraisals/<resource_id>/screen")
@endpoint(("Archivist",))
def screen_appraisal(resource_id):
    appraisal = fetch("appraisals", resource_id)
    if appraisal["status"] != "DRAFT":
        raise ApiError("ERR_APPRAISAL_STATE_INVALID")
    series = store.record_series[appraisal["record_series_id"]]
    _guard_series_not_frozen(series)
    score = calc.appraisal_score(appraisal, series, "SCREENING", appraisal["brand_heritage_value"])
    appraisal["screening_score"] = float(score)
    appraisal["status"] = "SCREENED"
    touch(appraisal)
    return object_response(appraisal)


@bp.post("/appraisals/<resource_id>/finalize")
@endpoint(("ArchivesDirector",))
def finalize_appraisal(resource_id):
    appraisal = fetch("appraisals", resource_id)
    if appraisal["status"] != "SCREENED":
        raise ApiError("ERR_APPRAISAL_STATE_INVALID")
    series = store.record_series[appraisal["record_series_id"]]
    _guard_series_not_frozen(series)
    schedule = schedule_of_series(series)
    admitted = calc.series_has_certified_package(series["id"])
    brand_value = appraisal["brand_heritage_value"] if admitted else 0
    score = calc.appraisal_score(appraisal, series, "FINAL", brand_value)
    appraisal["final_score"] = float(score)
    appraisal["brand_heritage_counted"] = admitted
    threshold = calc.dec(schedule["min_appraisal_score_for_permanent"])
    if Decimal(score) >= threshold:
        recommendation = "PERMANENT"
    else:
        recommendation = schedule["disposition_action"]
    appraisal["recommended_disposition"] = recommendation
    appraisal["status"] = "FINAL"
    touch(appraisal)
    series["current_appraisal_id"] = appraisal["id"]
    if series["disposition_state"] == "ACTIVE":
        if recommendation == "PERMANENT":
            series["disposition_state"] = "PERMANENT"
        elif clock.now() >= series["retention_expiry_utc"]:
            series["disposition_state"] = "ELIGIBLE_FOR_DISPOSITION"
    touch(series)
    return object_response(appraisal)
