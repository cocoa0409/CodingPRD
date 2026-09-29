"""EHR study calendars, their visits, and visit charge routes."""

from flask import Blueprint, request

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import ALL_ROLES, require
from errors import ApiError

bp = Blueprint("calendars", __name__, url_prefix="/research-billing")


@bp.post("/study-calendars")
@require("CoverageAnalyst")
def create_calendar():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    source_analysis_id = v.req_id(body, "source_analysis_id")

    study = lookup.study(study_id)
    analysis = lookup.analysis(source_analysis_id)

    existing = derive.calendars_of(study["id"])
    generation = 1 + max([c["build_generation"] for c in existing], default=0)

    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "source_analysis_id": analysis["id"],
        "build_generation": generation,
        "status": "DRAFT",
        "published_at": None,
    })
    store.calendars[rec["id"]] = rec
    return envelope.created(serializers.calendar(rec))


@bp.get("/study-calendars")
@require(*ALL_ROLES)
def list_calendars():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.calendars.values())
    for key in ("study_id", "source_analysis_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.calendar(r) for r in page], limit, offset, total)


@bp.get("/study-calendars/<calendar_id>")
@require(*ALL_ROLES)
def get_calendar(calendar_id):
    return envelope.ok(serializers.calendar(lookup.calendar(calendar_id)))


@bp.get("/study-calendars/<calendar_id>/visits")
@require(*ALL_ROLES)
def list_calendar_visits(calendar_id):
    limit, offset = envelope.read_pagination(request.args)
    rec = lookup.calendar(calendar_id)
    rows = derive.visits_of_calendar(rec["id"])
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.calendar_visit(r) for r in page],
                            limit, offset, total)


@bp.post("/calendar-visits")
@require("CoverageAnalyst")
def create_calendar_visit():
    body = v.body()
    calendar_id = v.req_id(body, "study_calendar_id")
    visit_name = v.req_str(body, "visit_name")
    sequence_index = v.req_int(body, "sequence_index", minimum=1)
    target_day_offset = v.req_int(body, "target_day_offset", minimum=0)
    window_before_days = v.req_int(body, "window_before_days", minimum=0)
    window_after_days = v.req_int(body, "window_after_days", minimum=0)

    calendar = lookup.calendar(calendar_id)
    if calendar["status"] != "DRAFT":
        raise ApiError("ERR_CALENDAR_NOT_DRAFT")

    siblings = derive.visits_of_calendar(calendar["id"])
    for sibling in siblings:
        if sibling["sequence_index"] == sequence_index:
            raise ApiError("ERR_DUPLICATE_SEQUENCE_INDEX")

    window_start_day = target_day_offset - window_before_days
    window_end_day = target_day_offset + window_after_days
    for sibling in siblings:
        if (window_start_day <= sibling["window_end_day"]
                and sibling["window_start_day"] <= window_end_day):
            raise ApiError("ERR_VISIT_WINDOW_OVERLAP")

    rec = store.base_record(versioned=False)
    rec.update({
        "study_calendar_id": calendar["id"],
        "visit_name": visit_name,
        "sequence_index": sequence_index,
        "target_day_offset": target_day_offset,
        "window_before_days": window_before_days,
        "window_after_days": window_after_days,
        "window_start_day": window_start_day,
        "window_end_day": window_end_day,
    })
    store.calendar_visits[rec["id"]] = rec
    store.touch(calendar)
    return envelope.created(serializers.calendar_visit(rec))


@bp.post("/visit-charge-routes")
@require("CoverageAnalyst")
def create_route():
    body = v.body()
    calendar_visit_id = v.req_id(body, "calendar_visit_id")
    coverage_item_id = v.req_id(body, "coverage_item_id")
    occurrences = v.opt_int(body, "occurrences", default=1, minimum=1)

    visit = lookup.calendar_visit(calendar_visit_id)
    item = lookup.coverage_item(coverage_item_id)

    calendar = lookup.calendar(visit["study_calendar_id"])
    if calendar["status"] != "DRAFT":
        raise ApiError("ERR_CALENDAR_NOT_DRAFT")

    if item["coverage_analysis_id"] != calendar["source_analysis_id"]:
        raise ApiError("ERR_ITEM_ANALYSIS_MISMATCH")

    for existing in derive.routes_of_visit(visit["id"]):
        if existing["coverage_item_id"] == item["id"]:
            raise ApiError("ERR_DUPLICATE_VISIT_ROUTE")

    if item["budget_category"] == "INVOICEABLE":
        raise ApiError("ERR_INVOICEABLE_ITEM_NOT_VISIT_ROUTABLE")

    routing_target = item["billable_to"]
    rec = store.base_record(versioned=False)
    rec.update({
        "calendar_visit_id": visit["id"],
        "coverage_item_id": item["id"],
        "occurrences": occurrences,
        "routing_target": routing_target,
        "expected_amount_cents": derive.route_expected_amount(item, routing_target, occurrences),
    })
    store.routes[rec["id"]] = rec
    store.touch(calendar)
    return envelope.created(serializers.route(rec))


@bp.get("/visit-charge-routes")
@require(*ALL_ROLES)
def list_routes():
    limit, offset = envelope.read_pagination(request.args)
    rows = store.by_created(store.routes.values())
    for key in ("calendar_visit_id", "coverage_item_id"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    page, total = envelope.page(rows, limit, offset)
    return envelope.listing([serializers.route(r) for r in page], limit, offset, total)


@bp.get("/visit-charge-routes/<route_id>")
@require(*ALL_ROLES)
def get_route(route_id):
    return envelope.ok(serializers.route(lookup.route(route_id)))


@bp.post("/study-calendars/<calendar_id>/publish")
@require("ComplianceReviewer")
def publish_calendar(calendar_id):
    rec = lookup.calendar(calendar_id)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_CALENDAR_NOT_DRAFT")

    analysis = store.analyses.get(rec["source_analysis_id"])
    if analysis is None or analysis["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    counters = derive.calendar_counters(rec)
    if counters["visit_count"] == 0 or counters["unrouted_per_patient_item_count"] > 0:
        raise ApiError("ERR_UNROUTED_PER_PATIENT_ITEM")

    rec["status"] = "PUBLISHED"
    rec["published_at"] = store.now()
    store.touch(rec)

    for other in derive.calendars_of(rec["study_id"]):
        if other["id"] == rec["id"]:
            continue
        if other["status"] in ("PUBLISHED", "REBUILD_REQUIRED"):
            other["status"] = "RETIRED"
            store.touch(other)

    study = store.studies.get(rec["study_id"])
    if study is not None:
        store.touch(study)
    return envelope.ok(serializers.calendar(rec))
