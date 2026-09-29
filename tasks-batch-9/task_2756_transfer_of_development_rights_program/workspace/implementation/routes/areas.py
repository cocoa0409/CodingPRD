"""Sending area, receiving area and appraisal schedule endpoints (PRD 3.2, 3.3)."""

from flask import Blueprint

import serializers
from core import db, new_record, q2, respond_object, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, require_roles
from services.derive import close_sending_area
from validators import (body, field_bool, field_cents, field_datetime, field_decimal, field_enum,
                        field_int, field_str, field_str_list, filter_bool, filter_enum, filter_str)

bp = Blueprint("areas", __name__)

FORMULAS = ("V1_NET_ACRE", "V2_GROSS_DISCOUNTED")
EQUITY_TIERS = ("HIGH_VALUE", "MODERATE", "UNDERSERVED")
SENDING_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
RECEIVING_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED")
SCHEDULE_STATUSES = ("ACTIVE", "SUPERSEDED")


def get_sending_area_or_404(area_id):
    area = db.sending_areas.get(area_id)
    if area is None:
        fail("ERR_SENDING_AREA_NOT_FOUND", "sending area %s does not exist" % area_id)
    return area


def get_receiving_area_or_404(area_id):
    area = db.receiving_areas.get(area_id)
    if area is None:
        fail("ERR_RECEIVING_AREA_NOT_FOUND", "receiving area %s does not exist" % area_id)
    return area


def _assert_code_free(code):
    for row in db.sending_areas.values():
        if row["code"] == code:
            fail("ERR_DUPLICATE_AREA_CODE", "area code %s is already in use" % code)
    for row in db.receiving_areas.values():
        if row["code"] == code:
            fail("ERR_DUPLICATE_AREA_CODE", "area code %s is already in use" % code)


# ---------------------------------------------------------------------------
# Sending areas
# ---------------------------------------------------------------------------
@bp.post("/tdr/sending-areas")
def create_sending_area():
    require_roles(ADMIN)
    data = body()
    code = field_str(data, "code", min_len=3, max_len=16)
    name = field_str(data, "name", min_len=1)
    neighborhood_code = field_str(data, "neighborhood_code", min_len=1, max_len=24)
    formula = field_enum(data, "allocation_formula_version", FORMULAS)
    base_rate = field_decimal(data, "base_rate_units_per_acre", minimum=0, maximum=4, places=2, exclusive_min=True)
    discount = field_decimal(data, "gross_discount_factor", required=False, default="0.80",
                             minimum=0, maximum=1, places=2, exclusive_min=True)
    equity_tier = field_enum(data, "equity_tier", EQUITY_TIERS)
    cap_units = field_int(data, "sending_cap_units", minimum=1)

    _assert_code_free(code)

    rec = new_record(
        {
            "code": code,
            "name": name,
            "neighborhood_code": neighborhood_code,
            "allocation_formula_version": formula,
            "base_rate_units_per_acre": base_rate,
            "gross_discount_factor": discount,
            "equity_tier": equity_tier,
            "sending_cap_units": cap_units,
            "severed_units_total": 0,
            "issued_certificate_count": 0,
            "status": "DRAFT",
        }
    )
    db.sending_areas[rec["id"]] = rec
    return respond_object(serializers.sending_area(rec), 201)


@bp.post("/tdr/sending-areas/<area_id>/activate")
def activate_sending_area(area_id):
    require_roles(ADMIN)
    area = get_sending_area_or_404(area_id)
    body()
    if area["status"] != "DRAFT":
        fail("ERR_AREA_NOT_DRAFT", "sending area is %s" % area["status"])
    area["status"] = "ACTIVE"
    touch(area)
    return respond_object(serializers.sending_area(area))


@bp.post("/tdr/sending-areas/<area_id>/close")
def close_area(area_id):
    require_roles(ADMIN)
    area = get_sending_area_or_404(area_id)
    data = body()
    field_str(data, "reason", required=False)
    if area["status"] != "ACTIVE":
        fail("ERR_SENDING_AREA_NOT_ACTIVE", "sending area is %s" % area["status"])
    close_sending_area(area)
    return respond_object(serializers.sending_area(area))


@bp.get("/tdr/sending-areas/<area_id>")
def get_sending_area(area_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.sending_area(get_sending_area_or_404(area_id)))


@bp.get("/tdr/sending-areas")
def list_sending_areas():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.sending_areas.values()),
        status=filter_enum("status", SENDING_STATUSES),
        neighborhood_code=filter_str("neighborhood_code"),
        equity_tier=filter_enum("equity_tier", EQUITY_TIERS),
        allocation_formula_version=filter_enum("allocation_formula_version", FORMULAS),
    )
    return paged(rows, serializers.sending_area)


# ---------------------------------------------------------------------------
# Receiving areas
# ---------------------------------------------------------------------------
@bp.post("/tdr/receiving-areas")
def create_receiving_area():
    require_roles(ADMIN)
    data = body()
    code = field_str(data, "code", min_len=3, max_len=16)
    name = field_str(data, "name", min_len=1)
    neighborhood_code = field_str(data, "neighborhood_code", min_len=1, max_len=24)
    base_density = field_decimal(data, "base_density_units_per_acre", minimum=0, maximum=40,
                                 places=2, exclusive_min=True)
    max_bonus_pct = field_decimal(data, "max_bonus_pct", minimum=0, maximum=1, places=2, exclusive_min=True)
    cap_units = field_int(data, "absorption_cap_units", minimum=1)
    design_review_required = field_bool(data, "design_review_required", required=False, default=True)
    eligible = field_str_list(data, "eligible_sending_area_codes", required=False, default=[],
                              min_len=3, max_len=16)

    _assert_code_free(code)

    rec = new_record(
        {
            "code": code,
            "name": name,
            "neighborhood_code": neighborhood_code,
            "base_density_units_per_acre": base_density,
            "max_bonus_pct": max_bonus_pct,
            "absorption_cap_units": cap_units,
            "design_review_required": design_review_required,
            "eligible_sending_area_codes": eligible,
            "absorbed_units": 0,
            "reserved_units": 0,
            "status": "DRAFT",
        }
    )
    db.receiving_areas[rec["id"]] = rec
    return respond_object(serializers.receiving_area(rec), 201)


@bp.post("/tdr/receiving-areas/<area_id>/activate")
def activate_receiving_area(area_id):
    require_roles(ADMIN)
    area = get_receiving_area_or_404(area_id)
    body()
    if area["status"] != "DRAFT":
        fail("ERR_AREA_NOT_DRAFT", "receiving area is %s" % area["status"])
    area["status"] = "ACTIVE"
    touch(area)
    return respond_object(serializers.receiving_area(area))


@bp.get("/tdr/receiving-areas/<area_id>")
def get_receiving_area(area_id):
    require_roles(*ALL_ROLES)
    return respond_object(serializers.receiving_area(get_receiving_area_or_404(area_id)))


@bp.get("/tdr/receiving-areas")
def list_receiving_areas():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.receiving_areas.values()),
        status=filter_enum("status", RECEIVING_STATUSES),
        neighborhood_code=filter_str("neighborhood_code"),
        design_review_required=filter_bool("design_review_required"),
    )
    return paged(rows, serializers.receiving_area)


# ---------------------------------------------------------------------------
# Appraisal schedules
# ---------------------------------------------------------------------------
@bp.post("/tdr/appraisal-schedules")
def create_appraisal_schedule():
    require_roles(ADMIN)
    data = body()
    neighborhood_code = field_str(data, "neighborhood_code", min_len=1, max_len=24)
    per_unit_value_cents = field_cents(data, "per_unit_value_cents", minimum=1)
    equity_adjustment_bps = field_int(data, "equity_adjustment_bps", required=False, default=0,
                                      minimum=-5000, maximum=5000)
    effective_from = field_datetime(data, "effective_from")
    effective_to = field_datetime(data, "effective_to", required=False, nullable=True)
    if effective_to is not None and not (effective_from < effective_to):
        fail("ERR_INVALID_REQUEST", "effective_from must be strictly before effective_to")

    # A same-neighborhood ACTIVE row with an identical effective_from is superseded
    # rather than treated as an overlap.
    superseded = [
        row
        for row in db.appraisal_schedules.values()
        if row["neighborhood_code"] == neighborhood_code
        and row["status"] == "ACTIVE"
        and row["effective_from"] == effective_from
    ]
    superseded_ids = {row["id"] for row in superseded}

    for row in db.appraisal_schedules.values():
        if row["neighborhood_code"] != neighborhood_code or row["status"] != "ACTIVE":
            continue
        if row["id"] in superseded_ids:
            continue
        starts_before_other_ends = row["effective_to"] is None or effective_from < row["effective_to"]
        other_starts_before_end = effective_to is None or row["effective_from"] < effective_to
        if starts_before_other_ends and other_starts_before_end:
            fail("ERR_APPRAISAL_PERIOD_OVERLAP", "window overlaps schedule %s" % row["id"])

    for row in superseded:
        row["status"] = "SUPERSEDED"
        touch(row)

    rec = new_record(
        {
            "neighborhood_code": neighborhood_code,
            "per_unit_value_cents": per_unit_value_cents,
            "equity_adjustment_bps": equity_adjustment_bps,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "status": "ACTIVE",
        }
    )
    db.appraisal_schedules[rec["id"]] = rec
    return respond_object(serializers.appraisal_schedule(rec), 201)


@bp.get("/tdr/appraisal-schedules/<schedule_id>")
def get_appraisal_schedule(schedule_id):
    require_roles(*ALL_ROLES)
    row = db.appraisal_schedules.get(schedule_id)
    if row is None:
        fail("ERR_APPRAISAL_SCHEDULE_NOT_FOUND", "appraisal schedule %s does not exist" % schedule_id)
    return respond_object(serializers.appraisal_schedule(row))


@bp.get("/tdr/appraisal-schedules")
def list_appraisal_schedules():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.appraisal_schedules.values()),
        neighborhood_code=filter_str("neighborhood_code"),
        status=filter_enum("status", SCHEDULE_STATUSES),
    )
    return paged(rows, serializers.appraisal_schedule)
