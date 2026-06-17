"""All API routes. Behaviors trace to PRD §2-§3."""
from flask import Blueprint, request

import errors
import calculations as calc
from db import store
from middleware import authenticate, authorize
from response import success, list_success
from serializers import crew_out, plain_out
from helpers import (
    get_json_body, require_fields, require_enum, require_string, require_number,
    require_int, require_bool_optional, require_datetime, lookup_or_404,
    parse_pagination, paginate, crew_open_assignment_count,
)

bp = Blueprint("api", __name__)

ROLE_TYPES = {"COORDINATOR", "PLS", "TECH", "RESEARCHER", "DRAFTER", "BILLING_CLERK"}
INSTRUMENT_TYPES = {"TOTAL_STATION", "GPS_RTK", "LEVEL", "DRONE", "SCANNER"}
SURVEY_TYPES = {"BOUNDARY", "TOPO", "ALTA", "ELEVATION"}
REVISION_REASONS = {"CLIENT_CHANGE", "FIELD_ERROR", "DEED_DISCREPANCY"}
DELIVERABLE_FORMATS = {"PDF", "DWG", "PAPER"}


def _filter_list(records, fields):
    """Apply equality filters from query params for the given field names."""
    out = list(records)
    for f in fields:
        val = request.args.get(f)
        if val is not None:
            if f == "active":
                want = val.lower() == "true"
                out = [r for r in out if r.get("active") == want]
            else:
                out = [r for r in out if str(r.get(f)) == val]
    return out


def _bump_order(order):
    """Mutate an order: refresh updated_at + increment version (PRD §2.5)."""
    store.touch(order)


# =====================================================================
# CrewMember
# =====================================================================
@bp.route("/crew-members", methods=["POST"])
def create_crew_member():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["full_name", "role_type"])
    require_string(body, "full_name")
    require_enum(body, "role_type", ROLE_TYPES)
    require_bool_optional(body, "active")

    role_type = body["role_type"]
    fields = {
        "full_name": body["full_name"],
        "role_type": role_type,
        "license_number": body.get("license_number") if role_type == "PLS" else None,
        "license_state": body.get("license_state") if role_type == "PLS" else None,
        "license_expires_on": body.get("license_expires_on") if role_type == "PLS" else None,
        "active": body.get("active", True) if body.get("active") is not None else True,
    }
    rec = store.insert(store.crew_members, fields)
    return success(crew_out(rec), status=201)


@bp.route("/crew-members/<rid>", methods=["GET"])
def get_crew_member(rid):
    authorize(authenticate()[1],
              {"Coordinator", "Researcher", "FieldTech", "Drafter", "Surveyor", "BillingClerk"})
    rec = lookup_or_404(store.crew_members, rid)
    return success(crew_out(rec))


@bp.route("/crew-members", methods=["GET"])
def list_crew_members():
    authorize(authenticate()[1],
              {"Coordinator", "Researcher", "FieldTech", "Drafter", "Surveyor", "BillingClerk"})
    limit, offset = parse_pagination()
    records = _filter_list(store.crew_members.values(), ["role_type", "active"])
    window, total = paginate(records, limit, offset)
    return list_success([crew_out(r) for r in window], limit, offset, total)


@bp.route("/crew-members/<rid>/risk-score", methods=["GET"])
def crew_risk_score(rid):
    authorize(authenticate()[1], {"Coordinator"})
    rec = lookup_or_404(store.crew_members, rid)
    out = crew_out(rec)
    out["risk_score"] = calc.crew_risk_score(out)
    return success(out)


# =====================================================================
# Instrument
# =====================================================================
@bp.route("/instruments", methods=["POST"])
def create_instrument():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["asset_tag", "instrument_type", "calibration_due_on"])
    require_string(body, "asset_tag")
    require_enum(body, "instrument_type", INSTRUMENT_TYPES)
    require_datetime(body, "calibration_due_on")

    # Priority 17: asset_tag uniqueness (case-sensitive exact match).
    for inst in store.instruments.values():
        if inst["asset_tag"] == body["asset_tag"]:
            raise errors.err(errors.ERR_DUPLICATE_ASSET_TAG, "asset_tag already exists")

    fields = {
        "asset_tag": body["asset_tag"],
        "instrument_type": body["instrument_type"],
        "calibration_due_on": body["calibration_due_on"],
        "status": "AVAILABLE",
    }
    rec = store.insert(store.instruments, fields)
    return success(plain_out(rec), status=201)


@bp.route("/instruments/<rid>", methods=["GET"])
def get_instrument(rid):
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    rec = lookup_or_404(store.instruments, rid)
    return success(plain_out(rec))


@bp.route("/instruments", methods=["GET"])
def list_instruments():
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    limit, offset = parse_pagination()
    records = _filter_list(store.instruments.values(), ["instrument_type", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


# =====================================================================
# SurveyOrder
# =====================================================================
@bp.route("/survey-orders", methods=["POST"])
def create_survey_order():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["client_name", "survey_type", "parcel_apn", "county_fips",
                          "acreage", "requested_due_date"])
    require_string(body, "client_name")
    require_enum(body, "survey_type", SURVEY_TYPES)
    require_string(body, "parcel_apn")
    require_string(body, "county_fips")
    require_number(body, "acreage", gt=0)
    require_bool_optional(body, "rush")
    require_datetime(body, "requested_due_date")

    rush = body.get("rush", False) if body.get("rush") is not None else False
    base, field, rush_fee, estimate = calc.estimate_fee_cents(body["survey_type"], body["acreage"], rush)

    fields = {
        "client_name": body["client_name"],
        "survey_type": body["survey_type"],
        "parcel_apn": body["parcel_apn"],
        "county_fips": body["county_fips"],
        "acreage": body["acreage"],
        "rush": rush,
        "requested_due_date": body["requested_due_date"],
        "status": "INTAKE",
        "research_clear": False,
        "base_fee_cents": base,
        "estimated_fee_cents": estimate,
        "final_fee_cents": 0,
        "revision_count": 0,
    }
    rec = store.insert(store.survey_orders, fields)
    return success(plain_out(rec), status=201)


@bp.route("/survey-orders/<rid>", methods=["GET"])
def get_survey_order(rid):
    authorize(authenticate()[1],
              {"Coordinator", "Researcher", "FieldTech", "Drafter", "Surveyor", "BillingClerk"})
    rec = lookup_or_404(store.survey_orders, rid)
    return success(plain_out(rec))


@bp.route("/survey-orders", methods=["GET"])
def list_survey_orders():
    authorize(authenticate()[1],
              {"Coordinator", "Researcher", "FieldTech", "Drafter", "Surveyor", "BillingClerk"})
    limit, offset = parse_pagination()
    records = _filter_list(store.survey_orders.values(), ["status", "survey_type"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/survey-orders/<rid>/start-research", methods=["POST"])
def start_research(rid):
    authorize(authenticate()[1], {"Coordinator"})
    order = lookup_or_404(store.survey_orders, rid)
    # Priority 5: transition defined only from INTAKE.
    if order["status"] != "INTAKE":
        raise errors.err(errors.ERR_INVALID_STATE, "start-research requires INTAKE")
    # Precondition: exactly one ResearchPacket exists for this order.
    packets = [p for p in store.research_packets.values() if p["order_id"] == rid]
    if len(packets) != 1:
        raise errors.err(errors.ERR_VALIDATION, "exactly one ResearchPacket must exist for this order")
    order["status"] = "RESEARCH"
    _bump_order(order)
    return success(plain_out(order))


@bp.route("/survey-orders/<rid>/clear-research", methods=["POST"])
def clear_research(rid):
    authorize(authenticate()[1], {"Coordinator"})
    order = lookup_or_404(store.survey_orders, rid)
    if order["status"] != "RESEARCH":
        raise errors.err(errors.ERR_INVALID_STATE, "clear-research requires RESEARCH")
    if not order["research_clear"]:
        raise errors.err(errors.ERR_VALIDATION, "research_clear must be true")
    order["status"] = "FIELD_READY"
    _bump_order(order)
    return success(plain_out(order))


@bp.route("/survey-orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    authorize(authenticate()[1], {"Coordinator"})
    order = lookup_or_404(store.survey_orders, rid)
    # Cancellable from any pre-SEALED state (not SEALED/DELIVERED, not already CANCELLED).
    if order["status"] in ("SEALED", "DELIVERED", "CANCELLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "order cannot be cancelled from %s" % order["status"])
    # Depth-3 release cascade (PRD §3.4).
    for assignment in store.field_assignments.values():
        if assignment["order_id"] == rid and assignment["status"] == "SCHEDULED":
            _cancel_assignment_cascade(assignment)
    order["status"] = "CANCELLED"
    _bump_order(order)
    return success(plain_out(order))


def _cancel_assignment_cascade(assignment):
    """Cancel a SCHEDULED assignment: release reservations, free instruments,
    decrement crew open_assignment_count. (PRD §3.3 / §3.4)"""
    assignment["status"] = "CANCELLED"
    _release_reservations_for_assignment(assignment["id"])
    store.touch(assignment)


def _release_reservations_for_assignment(assignment_id):
    for res in store.instrument_reservations.values():
        if res["assignment_id"] == assignment_id and res["status"] == "HELD":
            res["status"] = "RELEASED"
            store.touch(res)
            inst = store.instruments.get(res["instrument_id"])
            if inst is not None and inst["status"] == "RESERVED":
                inst["status"] = "AVAILABLE"
                store.touch(inst)


# =====================================================================
# ResearchPacket
# =====================================================================
@bp.route("/research-packets", methods=["POST"])
def create_research_packet():
    authorize(authenticate()[1], {"Coordinator", "Researcher"})
    body = get_json_body()
    require_fields(body, ["order_id", "assigned_researcher_id"])
    if "encumbrance_count" in body and body["encumbrance_count"] is not None:
        require_int(body, "encumbrance_count", ge=0)
    # Existence (priority 3), left-to-right.
    lookup_or_404(store.survey_orders, body["order_id"])
    researcher = lookup_or_404(store.crew_members, body["assigned_researcher_id"])
    # Priority 19: at most one ResearchPacket per order.
    if any(p["order_id"] == body["order_id"] for p in store.research_packets.values()):
        raise errors.err(errors.ERR_DUPLICATE_CHILD, "order already has a research packet")
    # Priority 7: assigned researcher must be RESEARCHER.
    if researcher["role_type"] != "RESEARCHER":
        raise errors.err(errors.ERR_ROLE_MISMATCH, "assigned_researcher_id must be a RESEARCHER")

    fields = {
        "order_id": body["order_id"],
        "assigned_researcher_id": body["assigned_researcher_id"],
        "deed_book": body.get("deed_book"),
        "deed_page": body.get("deed_page"),
        "encumbrance_count": body.get("encumbrance_count", 0) if body.get("encumbrance_count") is not None else 0,
        "status": "OPEN",
    }
    rec = store.insert(store.research_packets, fields)
    return success(plain_out(rec), status=201)


@bp.route("/research-packets/<rid>", methods=["GET"])
def get_research_packet(rid):
    authorize(authenticate()[1], {"Coordinator", "Researcher"})
    rec = lookup_or_404(store.research_packets, rid)
    return success(plain_out(rec))


@bp.route("/research-packets", methods=["GET"])
def list_research_packets():
    authorize(authenticate()[1], {"Coordinator", "Researcher"})
    limit, offset = parse_pagination()
    records = _filter_list(store.research_packets.values(),
                           ["order_id", "assigned_researcher_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/research-packets/<rid>/begin", methods=["POST"])
def begin_research_packet(rid):
    authorize(authenticate()[1], {"Researcher"})
    packet = lookup_or_404(store.research_packets, rid)
    # Priority 5: begin defined from OPEN or TITLE_HOLD.
    if packet["status"] not in ("OPEN", "TITLE_HOLD"):
        raise errors.err(errors.ERR_INVALID_STATE, "begin requires OPEN or TITLE_HOLD")
    # Priority 7: assigned researcher RESEARCHER and active.
    researcher = store.crew_members.get(packet["assigned_researcher_id"])
    if researcher is None or researcher["role_type"] != "RESEARCHER" or not researcher["active"]:
        raise errors.err(errors.ERR_ROLE_MISMATCH, "assigned researcher must be active RESEARCHER")
    # Parent order must be in RESEARCH.
    order = store.survey_orders.get(packet["order_id"])
    if order is None or order["status"] != "RESEARCH":
        raise errors.err(errors.ERR_VALIDATION, "parent order must be in RESEARCH")
    packet["status"] = "IN_PROGRESS"
    store.touch(packet)
    return success(plain_out(packet))


@bp.route("/research-packets/<rid>/clear", methods=["POST"])
def clear_research_packet(rid):
    authorize(authenticate()[1], {"Researcher"})
    packet = lookup_or_404(store.research_packets, rid)
    if packet["status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "clear requires IN_PROGRESS")
    # Priority 12: clear permitted only at exactly zero encumbrances.
    if packet["encumbrance_count"] != 0:
        raise errors.err(errors.ERR_TITLE_NOT_CLEAR, "encumbrance_count must be 0 to clear")
    packet["status"] = "CLEARED"
    store.touch(packet)
    order = store.survey_orders.get(packet["order_id"])
    if order is not None:
        order["research_clear"] = True
        _bump_order(order)
    return success(plain_out(packet))


@bp.route("/research-packets/<rid>/hold", methods=["POST"])
def hold_research_packet(rid):
    authorize(authenticate()[1], {"Researcher"})
    packet = lookup_or_404(store.research_packets, rid)
    if packet["status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "hold requires IN_PROGRESS")
    # Precondition: encumbrance_count >= 1.
    if packet["encumbrance_count"] < 1:
        raise errors.err(errors.ERR_VALIDATION, "encumbrance_count must be >= 1 to hold")
    packet["status"] = "TITLE_HOLD"
    store.touch(packet)
    return success(plain_out(packet))


# =====================================================================
# FieldAssignment
# =====================================================================
@bp.route("/field-assignments", methods=["POST"])
def create_field_assignment():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["order_id", "crew_member_id", "scheduled_start", "scheduled_end"])
    require_datetime(body, "scheduled_start")
    require_datetime(body, "scheduled_end")
    # Existence left-to-right.
    lookup_or_404(store.survey_orders, body["order_id"])
    crew = lookup_or_404(store.crew_members, body["crew_member_id"])
    # Priority 8: crew role_type in {TECH, PLS} and active.
    if crew["role_type"] not in ("TECH", "PLS") or not crew["active"]:
        raise errors.err(errors.ERR_ROLE_MISMATCH, "crew member must be active TECH or PLS")
    # Priority 13: scheduled_end strictly after scheduled_start.
    start = calc._parse_dt(body["scheduled_start"])
    end = calc._parse_dt(body["scheduled_end"])
    if not (end > start):
        raise errors.err(errors.ERR_INVALID_WINDOW, "scheduled_end must be strictly after scheduled_start")
    # Priority 14: crew not double-booked (half-open intervals, adjacency allowed).
    for other in store.field_assignments.values():
        if other["crew_member_id"] != body["crew_member_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        o_start = calc._parse_dt(other["scheduled_start"])
        o_end = calc._parse_dt(other["scheduled_end"])
        # Overlap of [start,end) intervals: start < o_end AND o_start < end.
        if start < o_end and o_start < end:
            raise errors.err(errors.ERR_CREW_DOUBLE_BOOKED, "crew member is double-booked")

    fields = {
        "order_id": body["order_id"],
        "crew_member_id": body["crew_member_id"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
        "window_minutes": calc.window_minutes(body["scheduled_start"], body["scheduled_end"]),
    }
    rec = store.insert(store.field_assignments, fields)
    return success(plain_out(rec), status=201)


@bp.route("/field-assignments/<rid>", methods=["GET"])
def get_field_assignment(rid):
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    rec = lookup_or_404(store.field_assignments, rid)
    return success(plain_out(rec))


@bp.route("/field-assignments", methods=["GET"])
def list_field_assignments():
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    limit, offset = parse_pagination()
    records = _filter_list(store.field_assignments.values(),
                           ["order_id", "crew_member_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/field-assignments/<rid>/start", methods=["POST"])
def start_field_assignment(rid):
    authorize(authenticate()[1], {"FieldTech"})
    assignment = lookup_or_404(store.field_assignments, rid)
    if assignment["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "start requires SCHEDULED")
    order = store.survey_orders.get(assignment["order_id"])
    # Precondition: parent order in {FIELD_READY, IN_FIELD}; crew active.
    if order is None or order["status"] not in ("FIELD_READY", "IN_FIELD"):
        raise errors.err(errors.ERR_VALIDATION, "parent order must be FIELD_READY or IN_FIELD")
    crew = store.crew_members.get(assignment["crew_member_id"])
    if crew is None or not crew["active"]:
        raise errors.err(errors.ERR_VALIDATION, "crew member must be active")
    assignment["status"] = "IN_PROGRESS"
    store.touch(assignment)
    # Bubble-up: FIELD_READY -> IN_FIELD on first start.
    if order["status"] == "FIELD_READY":
        order["status"] = "IN_FIELD"
        _bump_order(order)
    return success(plain_out(assignment))


@bp.route("/field-assignments/<rid>/complete", methods=["POST"])
def complete_field_assignment(rid):
    authorize(authenticate()[1], {"FieldTech"})
    assignment = lookup_or_404(store.field_assignments, rid)
    if assignment["status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "complete requires IN_PROGRESS")
    assignment["status"] = "COMPLETED"
    _release_reservations_for_assignment(assignment["id"])
    store.touch(assignment)
    return success(plain_out(assignment))


@bp.route("/field-assignments/<rid>/cancel", methods=["POST"])
def cancel_field_assignment(rid):
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    assignment = lookup_or_404(store.field_assignments, rid)
    if assignment["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "cancel requires SCHEDULED")
    assignment["status"] = "CANCELLED"
    _release_reservations_for_assignment(assignment["id"])
    store.touch(assignment)
    return success(plain_out(assignment))


# =====================================================================
# InstrumentReservation
# =====================================================================
@bp.route("/instrument-reservations", methods=["POST"])
def create_instrument_reservation():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["assignment_id", "instrument_id"])
    assignment = lookup_or_404(store.field_assignments, body["assignment_id"])
    instrument = lookup_or_404(store.instruments, body["instrument_id"])

    res_start = calc._parse_dt(assignment["scheduled_start"])
    res_end = calc._parse_dt(assignment["scheduled_end"])
    buffer_seconds = calc.TURNAROUND_MINUTES * 60

    # Priority 15: instrument not held for an overlapping buffered window.
    for other in store.instrument_reservations.values():
        if other["instrument_id"] != body["instrument_id"]:
            continue
        if other["status"] != "HELD":
            continue
        o_start = calc._parse_dt(other["reserved_start"])
        o_end = calc._parse_dt(other["reserved_end"])
        # Expand each interval by buffer on both sides, then test overlap.
        from datetime import timedelta
        buf = timedelta(seconds=buffer_seconds)
        a_start, a_end = res_start - buf, res_end + buf
        b_start, b_end = o_start - buf, o_end + buf
        if a_start < b_end and b_start < a_end:
            raise errors.err(errors.ERR_INSTRUMENT_UNAVAILABLE, "instrument unavailable for this window")

    # Priority 16: calibration_due_on must be after assignment scheduled_end.
    cal_due = calc._parse_dt(instrument["calibration_due_on"])
    if not (cal_due > res_end):
        raise errors.err(errors.ERR_INSTRUMENT_OUT_OF_CALIBRATION, "instrument out of calibration for this window")

    fields = {
        "assignment_id": body["assignment_id"],
        "instrument_id": body["instrument_id"],
        "reserved_start": assignment["scheduled_start"],
        "reserved_end": assignment["scheduled_end"],
        "status": "HELD",
    }
    rec = store.insert(store.instrument_reservations, fields)
    # Instrument AVAILABLE -> RESERVED.
    instrument["status"] = "RESERVED"
    store.touch(instrument)
    return success(plain_out(rec), status=201)


@bp.route("/instrument-reservations/<rid>", methods=["GET"])
def get_instrument_reservation(rid):
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    rec = lookup_or_404(store.instrument_reservations, rid)
    return success(plain_out(rec))


@bp.route("/instrument-reservations", methods=["GET"])
def list_instrument_reservations():
    authorize(authenticate()[1], {"Coordinator", "FieldTech"})
    limit, offset = parse_pagination()
    records = _filter_list(store.instrument_reservations.values(),
                           ["assignment_id", "instrument_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


# =====================================================================
# DataSet
# =====================================================================
@bp.route("/data-sets", methods=["POST"])
def create_data_set():
    authorize(authenticate()[1], {"FieldTech", "Surveyor"})
    body = get_json_body()
    require_fields(body, ["order_id", "assignment_id", "recorded_by_id", "point_count", "closure_error_ppm"])
    require_int(body, "point_count", ge=0)
    require_int(body, "closure_error_ppm", ge=0)
    lookup_or_404(store.survey_orders, body["order_id"])
    lookup_or_404(store.field_assignments, body["assignment_id"])
    lookup_or_404(store.crew_members, body["recorded_by_id"])

    fields = {
        "order_id": body["order_id"],
        "assignment_id": body["assignment_id"],
        "recorded_by_id": body["recorded_by_id"],
        "point_count": body["point_count"],
        "closure_error_ppm": body["closure_error_ppm"],
        "status": "RAW",
    }
    rec = store.insert(store.data_sets, fields)
    return success(plain_out(rec), status=201)


@bp.route("/data-sets/<rid>", methods=["GET"])
def get_data_set(rid):
    authorize(authenticate()[1], {"Coordinator", "FieldTech", "Drafter", "Surveyor"})
    rec = lookup_or_404(store.data_sets, rid)
    return success(plain_out(rec))


@bp.route("/data-sets", methods=["GET"])
def list_data_sets():
    authorize(authenticate()[1], {"Coordinator", "FieldTech", "Drafter", "Surveyor"})
    limit, offset = parse_pagination()
    records = _filter_list(store.data_sets.values(),
                           ["order_id", "assignment_id", "recorded_by_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/data-sets/<rid>/reduce", methods=["POST"])
def reduce_data_set(rid):
    authorize(authenticate()[1], {"Drafter", "Surveyor"})
    ds = lookup_or_404(store.data_sets, rid)
    if ds["status"] != "RAW":
        raise errors.err(errors.ERR_INVALID_STATE, "reduce requires RAW")
    ds["status"] = "REDUCED"
    store.touch(ds)
    return success(plain_out(ds))


@bp.route("/data-sets/<rid>/accept", methods=["POST"])
def accept_data_set(rid):
    authorize(authenticate()[1], {"Surveyor"})
    ds = lookup_or_404(store.data_sets, rid)
    if ds["status"] != "REDUCED":
        raise errors.err(errors.ERR_INVALID_STATE, "accept requires REDUCED")
    ds["status"] = "ACCEPTED"
    store.touch(ds)
    # Advance parent order IN_FIELD -> DATA_READY.
    order = store.survey_orders.get(ds["order_id"])
    if order is not None and order["status"] == "IN_FIELD":
        order["status"] = "DATA_READY"
        _bump_order(order)
    return success(plain_out(ds))


# =====================================================================
# PlatDrawing
# =====================================================================
@bp.route("/plat-drawings", methods=["POST"])
def create_plat_drawing():
    authorize(authenticate()[1], {"Drafter"})
    body = get_json_body()
    require_fields(body, ["order_id", "dataset_id", "drafted_by_id"])
    order = lookup_or_404(store.survey_orders, body["order_id"])
    dataset = lookup_or_404(store.data_sets, body["dataset_id"])
    lookup_or_404(store.crew_members, body["drafted_by_id"])
    # Order must be in DATA_READY to create the first plat; precondition: a dataset is ACCEPTED.
    if order["status"] != "DATA_READY":
        raise errors.err(errors.ERR_INVALID_STATE, "plat creation requires order in DATA_READY")
    if dataset["status"] != "ACCEPTED":
        raise errors.err(errors.ERR_VALIDATION, "source dataset must be ACCEPTED")

    fields = {
        "order_id": body["order_id"],
        "dataset_id": body["dataset_id"],
        "drafted_by_id": body["drafted_by_id"],
        "sealed_by_id": None,
        "status": "DRAFTED",
        "sealed_at": None,
    }
    rec = store.insert(store.plat_drawings, fields)
    # Advance order DATA_READY -> DRAFTING.
    order["status"] = "DRAFTING"
    _bump_order(order)
    return success(plain_out(rec), status=201)


@bp.route("/plat-drawings/<rid>", methods=["GET"])
def get_plat_drawing(rid):
    authorize(authenticate()[1], {"Coordinator", "Drafter", "Surveyor"})
    rec = lookup_or_404(store.plat_drawings, rid)
    return success(plain_out(rec))


@bp.route("/plat-drawings", methods=["GET"])
def list_plat_drawings():
    authorize(authenticate()[1], {"Coordinator", "Drafter", "Surveyor"})
    limit, offset = parse_pagination()
    records = _filter_list(store.plat_drawings.values(),
                           ["order_id", "dataset_id", "drafted_by_id", "sealed_by_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/plat-drawings/<rid>/submit-review", methods=["POST"])
def submit_plat_review(rid):
    authorize(authenticate()[1], {"Drafter"})
    plat = lookup_or_404(store.plat_drawings, rid)
    if plat["status"] != "DRAFTED":
        raise errors.err(errors.ERR_INVALID_STATE, "submit-review requires DRAFTED")
    # Precondition: source dataset ACCEPTED.
    dataset = store.data_sets.get(plat["dataset_id"])
    if dataset is None or dataset["status"] != "ACCEPTED":
        raise errors.err(errors.ERR_VALIDATION, "source dataset must be ACCEPTED")
    plat["status"] = "UNDER_REVIEW"
    store.touch(plat)
    return success(plain_out(plat))


@bp.route("/plat-drawings/<rid>/seal", methods=["POST"])
def seal_plat_drawing(rid):
    authorize(authenticate()[1], {"Surveyor"})
    body = get_json_body()
    require_fields(body, ["sealed_by_id", "expected_order_version"])
    plat = lookup_or_404(store.plat_drawings, rid)
    sealer = lookup_or_404(store.crew_members, body["sealed_by_id"])
    # Priority 5: state legality first.
    if plat["status"] != "UNDER_REVIEW":
        raise errors.err(errors.ERR_INVALID_STATE, "seal requires UNDER_REVIEW")
    order = store.survey_orders.get(plat["order_id"])
    if order is None:
        raise errors.err(errors.ERR_NOT_FOUND, "parent order not found")
    # Priority 6: OCC after state legality, before business rules.
    if body["expected_order_version"] != order["version"]:
        raise errors.err(errors.ERR_STALE_ORDER_VERSION, "expected_order_version does not match order version")
    dataset = store.data_sets.get(plat["dataset_id"])
    # Priority 9: segregation of duties — sealer.id != source dataset recorded_by_id.
    if dataset is not None and body["sealed_by_id"] == dataset["recorded_by_id"]:
        raise errors.err(errors.ERR_SEGREGATION_VIOLATION, "sealer must differ from dataset recorder")
    # Priority 10: sealer is active PLS with non-expired license.
    if sealer["role_type"] != "PLS" or not sealer["active"]:
        raise errors.err(errors.ERR_SEAL_NOT_LICENSED, "sealer must be an active PLS")
    if not sealer.get("license_expires_on"):
        raise errors.err(errors.ERR_SEAL_NOT_LICENSED, "sealer license missing or expired")
    expires = calc._parse_dt(sealer["license_expires_on"])
    from datetime import datetime, timezone
    if not (expires > datetime.now(timezone.utc)):
        raise errors.err(errors.ERR_SEAL_NOT_LICENSED, "sealer license is expired")
    # Priority 11: closure tolerance.
    if dataset is not None and dataset["closure_error_ppm"] > calc.MAX_SEALABLE_CLOSURE_PPM:
        raise errors.err(errors.ERR_CLOSURE_OUT_OF_TOLERANCE, "closure error out of tolerance")

    from db import now_iso
    plat["status"] = "SEALED"
    plat["sealed_by_id"] = body["sealed_by_id"]
    plat["sealed_at"] = now_iso()
    store.touch(plat)
    # Advance order DRAFTING -> SEALED, increments order version.
    if order["status"] == "DRAFTING":
        order["status"] = "SEALED"
    _bump_order(order)
    return success(plain_out(plat))


@bp.route("/plat-drawings/<rid>/resume-draft", methods=["POST"])
def resume_draft_plat(rid):
    authorize(authenticate()[1], {"Drafter"})
    plat = lookup_or_404(store.plat_drawings, rid)
    if plat["status"] != "IN_REVISION":
        raise errors.err(errors.ERR_INVALID_STATE, "resume-draft requires IN_REVISION")
    plat["status"] = "DRAFTED"
    store.touch(plat)
    return success(plain_out(plat))


# =====================================================================
# RevisionRequest
# =====================================================================
@bp.route("/revision-requests", methods=["POST"])
def create_revision_request():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["plat_id", "reason"])
    require_enum(body, "reason", REVISION_REASONS)
    lookup_or_404(store.plat_drawings, body["plat_id"])

    fields = {
        "plat_id": body["plat_id"],
        "reason": body["reason"],
        "notes": body.get("notes"),
        "status": "REQUESTED",
        "reseal_fee_cents": calc.reseal_fee_for_reason(body["reason"]),
    }
    rec = store.insert(store.revision_requests, fields)
    return success(plain_out(rec), status=201)


@bp.route("/revision-requests/<rid>", methods=["GET"])
def get_revision_request(rid):
    authorize(authenticate()[1], {"Coordinator", "Drafter", "Surveyor"})
    rec = lookup_or_404(store.revision_requests, rid)
    return success(plain_out(rec))


@bp.route("/revision-requests", methods=["GET"])
def list_revision_requests():
    authorize(authenticate()[1], {"Coordinator", "Drafter", "Surveyor"})
    limit, offset = parse_pagination()
    records = _filter_list(store.revision_requests.values(), ["plat_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/revision-requests/<rid>/apply", methods=["POST"])
def apply_revision_request(rid):
    authorize(authenticate()[1], {"Coordinator"})
    rev = lookup_or_404(store.revision_requests, rid)
    if rev["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "apply requires REQUESTED")
    plat = store.plat_drawings.get(rev["plat_id"])
    if plat is None:
        raise errors.err(errors.ERR_NOT_FOUND, "plat not found")
    # Plat must be SEALED or UNDER_REVIEW to apply a revision.
    if plat["status"] not in ("SEALED", "UNDER_REVIEW"):
        raise errors.err(errors.ERR_INVALID_STATE, "revision can only be applied to SEALED or UNDER_REVIEW plat")

    order = store.survey_orders.get(plat["order_id"])
    was_sealed = plat["status"] == "SEALED"

    rev["status"] = "APPLIED"
    store.touch(rev)
    plat["status"] = "IN_REVISION"
    if was_sealed:
        # Clear seal.
        plat["sealed_by_id"] = None
        plat["sealed_at"] = None
    store.touch(plat)

    if order is not None:
        # revision_count incremented in both branches.
        order["revision_count"] = order["revision_count"] + 1
        if was_sealed:
            # Add reseal fee to estimated_fee_cents; revert SEALED -> DRAFTING.
            order["estimated_fee_cents"] = order["estimated_fee_cents"] + rev["reseal_fee_cents"]
            if order["status"] == "SEALED":
                order["status"] = "DRAFTING"
        _bump_order(order)
    return success(plain_out(rev))


@bp.route("/revision-requests/<rid>/reject", methods=["POST"])
def reject_revision_request(rid):
    authorize(authenticate()[1], {"Coordinator"})
    rev = lookup_or_404(store.revision_requests, rid)
    if rev["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "reject requires REQUESTED")
    rev["status"] = "REJECTED"
    store.touch(rev)
    return success(plain_out(rev))


# =====================================================================
# Deliverable
# =====================================================================
@bp.route("/deliverables", methods=["POST"])
def create_deliverable():
    authorize(authenticate()[1], {"Coordinator"})
    body = get_json_body()
    require_fields(body, ["order_id", "plat_id", "format"])
    require_enum(body, "format", DELIVERABLE_FORMATS)
    lookup_or_404(store.survey_orders, body["order_id"])
    plat = lookup_or_404(store.plat_drawings, body["plat_id"])
    # Assembling requires the referenced plat to be SEALED.
    if plat["status"] != "SEALED":
        raise errors.err(errors.ERR_VALIDATION, "referenced plat must be SEALED")

    fields = {
        "order_id": body["order_id"],
        "plat_id": body["plat_id"],
        "format": body["format"],
        "status": "ASSEMBLED",
    }
    rec = store.insert(store.deliverables, fields)
    return success(plain_out(rec), status=201)


@bp.route("/deliverables/<rid>", methods=["GET"])
def get_deliverable(rid):
    authorize(authenticate()[1], {"Coordinator", "BillingClerk"})
    rec = lookup_or_404(store.deliverables, rid)
    return success(plain_out(rec))


@bp.route("/deliverables", methods=["GET"])
def list_deliverables():
    authorize(authenticate()[1], {"Coordinator", "BillingClerk"})
    limit, offset = parse_pagination()
    records = _filter_list(store.deliverables.values(), ["order_id", "plat_id", "status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/deliverables/<rid>/release", methods=["POST"])
def release_deliverable(rid):
    authorize(authenticate()[1], {"Coordinator"})
    deliverable = lookup_or_404(store.deliverables, rid)
    if deliverable["status"] != "ASSEMBLED":
        raise errors.err(errors.ERR_INVALID_STATE, "release requires ASSEMBLED")
    plat = store.plat_drawings.get(deliverable["plat_id"])
    order = store.survey_orders.get(deliverable["order_id"])
    # Gated: released deliverable references a SEALED plat; order has an ISSUED invoice.
    if plat is None or plat["status"] != "SEALED":
        raise errors.err(errors.ERR_VALIDATION, "deliverable must reference a SEALED plat")
    if order is None or order["status"] != "SEALED":
        raise errors.err(errors.ERR_INVALID_STATE, "order must be SEALED to deliver")
    has_issued_invoice = any(
        inv["order_id"] == order["id"] and inv["lifecycle_status"] in ("ISSUED", "CLOSED")
        for inv in store.invoices.values()
    )
    if not has_issued_invoice:
        raise errors.err(errors.ERR_VALIDATION, "order must have an ISSUED invoice to deliver")

    deliverable["status"] = "RELEASED"
    store.touch(deliverable)
    order["status"] = "DELIVERED"
    _bump_order(order)
    return success(plain_out(deliverable))


# =====================================================================
# Invoice
# =====================================================================
@bp.route("/invoices", methods=["POST"])
def create_invoice():
    authorize(authenticate()[1], {"BillingClerk"})
    body = get_json_body()
    require_fields(body, ["order_id", "issued_by_id"])
    lookup_or_404(store.survey_orders, body["order_id"])
    lookup_or_404(store.crew_members, body["issued_by_id"])

    fields = {
        "order_id": body["order_id"],
        "issued_by_id": body["issued_by_id"],
        "subtotal_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "balance_due_cents": 0,
        "lifecycle_status": "DRAFT",
        "payment_status": "UNPAID",
    }
    rec = store.insert(store.invoices, fields)
    return success(plain_out(rec), status=201)


@bp.route("/invoices/<rid>", methods=["GET"])
def get_invoice(rid):
    authorize(authenticate()[1], {"Coordinator", "BillingClerk"})
    rec = lookup_or_404(store.invoices, rid)
    return success(plain_out(rec))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    authorize(authenticate()[1], {"Coordinator", "BillingClerk"})
    limit, offset = parse_pagination()
    records = _filter_list(store.invoices.values(),
                           ["order_id", "issued_by_id", "lifecycle_status", "payment_status"])
    window, total = paginate(records, limit, offset)
    return list_success([plain_out(r) for r in window], limit, offset, total)


@bp.route("/invoices/<rid>/issue", methods=["POST"])
def issue_invoice(rid):
    authorize(authenticate()[1], {"BillingClerk"})
    body = get_json_body()
    require_fields(body, ["expected_order_version"])
    invoice = lookup_or_404(store.invoices, rid)
    # Priority 5: state legality.
    if invoice["lifecycle_status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "issue requires DRAFT")
    order = store.survey_orders.get(invoice["order_id"])
    if order is None:
        raise errors.err(errors.ERR_NOT_FOUND, "order not found")
    if order["status"] not in ("SEALED", "DELIVERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "order must be SEALED or DELIVERED to issue")
    # Priority 6: OCC.
    if body["expected_order_version"] != order["version"]:
        raise errors.err(errors.ERR_STALE_ORDER_VERSION, "expected_order_version does not match order version")
    # Priority 19: at most one ISSUED/CLOSED invoice per order.
    for inv in store.invoices.values():
        if inv["id"] == rid:
            continue
        if inv["order_id"] == order["id"] and inv["lifecycle_status"] in ("ISSUED", "CLOSED"):
            raise errors.err(errors.ERR_DUPLICATE_CHILD, "order already has an issued invoice")

    # Compute final fee (actual variant): sum APPLIED reseal fees for this order's plats.
    order_plat_ids = {p["id"] for p in store.plat_drawings.values() if p["order_id"] == order["id"]}
    applied_reseal = sum(
        r["reseal_fee_cents"] for r in store.revision_requests.values()
        if r["status"] == "APPLIED" and r["plat_id"] in order_plat_ids
    )
    subtotal, tax, total = calc.invoice_final_components(order, applied_reseal)
    invoice["subtotal_cents"] = subtotal
    invoice["tax_cents"] = tax
    invoice["total_cents"] = total
    invoice["balance_due_cents"] = total - invoice["amount_paid_cents"]
    invoice["lifecycle_status"] = "ISSUED"
    store.touch(invoice)
    # Freeze final_fee_cents on order; increments order version.
    order["final_fee_cents"] = total
    _bump_order(order)
    return success(plain_out(invoice))


@bp.route("/invoices/<rid>/payments", methods=["POST"])
def pay_invoice(rid):
    authorize(authenticate()[1], {"BillingClerk"})
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    require_int(body, "amount_cents")
    invoice = lookup_or_404(store.invoices, rid)
    # Priority 5: payments require an ISSUED invoice.
    if invoice["lifecycle_status"] != "ISSUED":
        raise errors.err(errors.ERR_INVALID_STATE, "payments require an ISSUED invoice")
    amount = body["amount_cents"]
    # Priority 18: amount > 0 and does not exceed balance_due_cents.
    if amount <= 0 or amount > invoice["balance_due_cents"]:
        raise errors.err(errors.ERR_PAYMENT_EXCEEDS_BALANCE, "payment must be > 0 and <= balance due")

    invoice["amount_paid_cents"] = invoice["amount_paid_cents"] + amount
    invoice["balance_due_cents"] = invoice["total_cents"] - invoice["amount_paid_cents"]
    if invoice["balance_due_cents"] == 0:
        invoice["lifecycle_status"] = "CLOSED"
        invoice["payment_status"] = "PAID"
    else:
        if invoice["payment_status"] == "UNPAID":
            invoice["payment_status"] = "PARTIAL"
    store.touch(invoice)
    return success(plain_out(invoice))
