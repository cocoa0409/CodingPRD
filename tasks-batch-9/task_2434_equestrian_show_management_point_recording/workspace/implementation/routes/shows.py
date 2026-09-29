"""Show creation, licensing, rings, divisions and coverage windows."""

from flask import Blueprint

import calc
import serializers as ser
import services
import validate as v
from auth import endpoint
from core import (
    COMPETITION_LEVELS,
    COVERAGE_TYPES,
    DISCIPLINES,
    AGE_GROUPS,
    LICENSE_DECISIONS,
    MAX_LICENSE_REVISIONS,
    SURFACE_TYPES,
    classes_of_show,
    db,
    divisions_of_show,
    find,
    new_row,
    set_value,
    touch,
)
from errors import ApiError
from response import object_response

bp = Blueprint("shows", __name__)

EDITABLE_LICENSE_STATES = ("DRAFT", "RETURNED_FOR_CORRECTION")


def _class_list_substantive(show):
    has_active_division = any(
        d["status"] == "ACTIVE" for d in divisions_of_show(show["id"])
    )
    has_class = len(classes_of_show(show["id"])) > 0
    return has_active_division and has_class


@bp.post("/shows")
@endpoint("ShowSecretary")
def create_show():
    payload = v.body()
    name = v.req_str(payload, "name")
    federation_show_id = v.req_str(payload, "federation_show_id")
    venue = v.req_str(payload, "venue")
    competition_level = v.req_enum(payload, "competition_level", COMPETITION_LEVELS)
    start_utc = v.req_dt(payload, "start_utc")
    end_utc = v.req_dt(payload, "end_utc")
    entry_close_utc = v.req_dt(payload, "entry_close_utc")
    prize_money_pool_cents = v.req_int(payload, "prize_money_pool_cents", minimum=0)
    stall_capacity = v.req_int(payload, "stall_capacity", minimum=0)
    stall_fee_cents = v.req_int(payload, "stall_fee_cents", minimum=0)

    show = new_row(
        db.shows,
        name=name,
        federation_show_id=federation_show_id,
        venue=venue,
        competition_level=competition_level,
        start_utc=start_utc,
        end_utc=end_utc,
        entry_close_utc=entry_close_utc,
        license_status="DRAFT",
        revision_count=0,
        correction_note=None,
        prize_money_pool_cents=prize_money_pool_cents,
        allocated_prize_cents=0,
        stall_capacity=stall_capacity,
        stall_fee_cents=stall_fee_cents,
        reserved_stall_count=0,
        division_share_bp_total=0,
        welfare_strike_count=0,
    )
    return object_response(ser.ser_show(show), 201)


@bp.post("/shows/<show_id>/license-submission")
@endpoint("ShowSecretary")
def submit_license(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    if show["license_status"] not in EDITABLE_LICENSE_STATES:
        raise ApiError("ERR_SHOW_LICENSE_NOT_DRAFT")
    if not _class_list_substantive(show):
        raise ApiError("ERR_CLASS_LIST_INCOMPLETE")
    total_bp = services.active_division_share(show)
    if total_bp > 10000:
        raise ApiError("ERR_DIVISION_SHARE_OVERSUBSCRIBED")

    show["division_share_bp_total"] = total_bp
    if show["license_status"] == "RETURNED_FOR_CORRECTION":
        show["revision_count"] = int(show["revision_count"]) + 1
    show["license_status"] = "SUBMITTED"
    touch(show)
    return object_response(ser.ser_show(show))


def _deny_show(show):
    show["license_status"] = "DENIED"
    for division in divisions_of_show(show["id"]):
        if division["status"] != "ACTIVE":
            continue
        division["status"] = "CLOSED"
        touch(division)
        for cls in db.classes.values():
            if cls["division_id"] != division["id"]:
                continue
            if cls["status"] == "PLANNED":
                cls["status"] = "VOIDED"
                touch(cls)


def _approve_show(show):
    show["license_status"] = "APPROVED"
    for division in divisions_of_show(show["id"]):
        set_value(division, "division_allotment_cents", calc.division_allotment(show, division))
        for cls in db.classes.values():
            if cls["division_id"] != division["id"]:
                continue
            set_value(cls, "class_purse_cents", calc.class_purse(division, cls))


@bp.post("/shows/<show_id>/license-decision")
@endpoint("FederationOfficer")
def decide_license(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    payload = v.body()
    decision = v.req_enum(payload, "decision", LICENSE_DECISIONS)
    correction_note = v.opt_str(payload, "correction_note")

    if show["license_status"] != "SUBMITTED":
        raise ApiError("ERR_SHOW_LICENSE_NOT_SUBMITTED")

    if decision == "APPROVE":
        if not _class_list_substantive(show):
            raise ApiError("ERR_CLASS_LIST_INCOMPLETE")
        _approve_show(show)
    elif decision == "DENY":
        _deny_show(show)
    else:
        if int(show["revision_count"]) < MAX_LICENSE_REVISIONS:
            show["license_status"] = "RETURNED_FOR_CORRECTION"
            show["correction_note"] = correction_note
        else:
            _deny_show(show)
    touch(show)
    return object_response(ser.ser_show(show))


@bp.post("/shows/<show_id>/rings")
@endpoint("ShowSecretary")
def create_ring(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    payload = v.body()
    name = v.req_str(payload, "name")
    surface_type = v.req_enum(payload, "surface_type", SURFACE_TYPES)
    footing = v.opt_int(payload, "footing_condition_score", 100, minimum=0, maximum=100)
    buffer_minutes = v.opt_int(payload, "turnover_buffer_minutes", 10, minimum=0)
    warmup_capacity = v.opt_int(payload, "warmup_capacity_horses", 12, minimum=1)

    ring = new_row(
        db.rings,
        show_id=show["id"],
        name=name,
        surface_type=surface_type,
        footing_condition_score=footing,
        turnover_buffer_minutes=buffer_minutes,
        warmup_capacity_horses=warmup_capacity,
        status="AVAILABLE",
        scheduled_minutes_total=0,
        slot_count=0,
    )
    touch(show)
    return object_response(ser.ser_ring(ring), 201)


@bp.post("/shows/<show_id>/divisions")
@endpoint("ShowSecretary")
def create_division(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    payload = v.body()
    name = v.req_str(payload, "name")
    discipline = v.req_enum(payload, "discipline", DISCIPLINES)
    age_group = v.req_enum(payload, "age_group", AGE_GROUPS)
    min_height = v.req_int(payload, "min_jump_height_cm", minimum=0)
    max_height = v.req_int(payload, "max_jump_height_cm", minimum=0)
    share_bp = v.req_int(payload, "division_share_bp", minimum=0, maximum=10000)
    jumpoff_enabled = v.opt_bool(payload, "jumpoff_enabled", False)
    if max_height < min_height:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'max_jump_height_cm' must be at least 'min_jump_height_cm'.",
        )

    if show["license_status"] not in EDITABLE_LICENSE_STATES:
        raise ApiError("ERR_SHOW_LICENSE_LOCKED")
    if services.active_division_share(show, share_bp) > 10000:
        raise ApiError("ERR_DIVISION_SHARE_OVERSUBSCRIBED")

    division = new_row(
        db.divisions,
        show_id=show["id"],
        name=name,
        discipline=discipline,
        age_group=age_group,
        min_jump_height_cm=min_height,
        max_jump_height_cm=max_height,
        division_share_bp=share_bp,
        jumpoff_enabled=jumpoff_enabled,
        status="ACTIVE",
        division_allotment_cents=0,
    )
    services.recompute_division_share(show)
    touch(show)
    return object_response(ser.ser_division(division), 201)


@bp.post("/shows/<show_id>/coverage-shifts")
@endpoint("GroundsManager")
def create_coverage_shift(show_id):
    show = find(db.shows, show_id, "ERR_SHOW_NOT_FOUND")
    payload = v.body()
    coverage_type = v.req_enum(payload, "coverage_type", COVERAGE_TYPES)
    provider_name = v.req_str(payload, "provider_name")
    start_utc = v.req_dt(payload, "start_utc")
    end_utc = v.req_dt(payload, "end_utc")

    shift = new_row(
        db.coverage_shifts,
        show_id=show["id"],
        coverage_type=coverage_type,
        provider_name=provider_name,
        start_utc=start_utc,
        end_utc=end_utc,
        status="SCHEDULED",
    )
    return object_response(ser.ser_coverage(shift), 201)
