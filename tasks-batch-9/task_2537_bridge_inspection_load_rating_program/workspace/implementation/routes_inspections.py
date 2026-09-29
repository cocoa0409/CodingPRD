"""Inspection and ElementCondition endpoints."""

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from calc import dec
from db import db as store
from errors import ApiError
from middleware import BRIDGE_INSPECTOR, QA_REVIEWER, authenticate, authenticate_read

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("ROUTINE", "UNDERWATER", "FRACTURE_CRITICAL", "SPECIAL", "DAMAGE")
INSPECTION_STATUSES = ("DRAFT", "SUBMITTED", "IN_QA", "ACCEPTED", "VOIDED")
UNITS = ("SQM", "M", "EA")
ACTIVE_STATUSES = ("DRAFT", "SUBMITTED", "IN_QA", "ACCEPTED")


# --------------------------------------------------------------------------- #
# inspections
# --------------------------------------------------------------------------- #
@bp.post("/bridges/<bridge_id>/inspections")
def create_inspection(bridge_id):
    actor = authenticate(BRIDGE_INSPECTOR)
    body = params.json_body()
    inspection_type = params.get_enum(body, "inspection_type", INSPECTION_TYPES, required=True)
    team_leader_id = params.get_string(body, "team_leader_id", required=True)
    raw_start, start = params.get_instant(body, "field_window_start", required=True)
    raw_end, end = params.get_instant(body, "field_window_end", required=True)
    if end <= start:
        params.bad("field_window_end must be strictly later than field_window_start.")
    qa_reviewer_id = params.get_string(body, "qa_reviewer_id")
    notes = params.get_string(body, "notes")

    bridge = services.get_bridge(bridge_id)
    leader = services.get_personnel(team_leader_id)
    if qa_reviewer_id is not None:
        services.get_personnel(qa_reviewer_id)
    if team_leader_id != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if not leader["team_leader_certified"] or not services.person_is_current(leader):
        raise ApiError("ERR_TEAM_LEADER_NOT_QUALIFIED")
    if inspection_type == "UNDERWATER" and not bridge["underwater_elements"]:
        raise ApiError("ERR_INSPECTION_TYPE_NOT_APPLICABLE")
    if inspection_type == "FRACTURE_CRITICAL" and not bridge["fracture_critical"]:
        raise ApiError("ERR_INSPECTION_TYPE_NOT_APPLICABLE")

    for other in services.rows("inspections"):
        if other["status"] not in ACTIVE_STATUSES:
            continue
        if other["bridge_id"] == bridge_id and calc.buffered_overlap(
            start, end, other["_field_window_start"], other["_field_window_end"]
        ):
            raise ApiError("ERR_BRIDGE_ACCESS_BUFFER_CONFLICT")
    for other in services.rows("inspections"):
        if other["status"] not in ACTIVE_STATUSES:
            continue
        if other["team_leader_id"] == team_leader_id and calc.half_open_overlap(
            start, end, other["_field_window_start"], other["_field_window_end"]
        ):
            raise ApiError("ERR_TEAM_LEADER_WINDOW_CONFLICT")

    record = db.new_record(
        {
            "bridge_id": bridge_id,
            "inspection_type": inspection_type,
            "team_leader_id": team_leader_id,
            "qa_reviewer_id": None,
            "status": "DRAFT",
            "field_window_start": raw_start,
            "field_window_end": raw_end,
            "_field_window_start": start,
            "_field_window_end": end,
            "inspection_date": None,
            "_inspection_date": None,
            "submitted_at": None,
            "qa_claimed_at": None,
            "accepted_at": None,
            "returned_count": 0,
            "qa_escalation_required": False,
            "element_count": 0,
            "reported_quantity_total": dec(0),
            "deficient_quantity_total": dec(0),
            "photo_count_total": 0,
            "quantity_balanced": True,
            "deck_group_ehi": None,
            "superstructure_group_ehi": None,
            "substructure_group_ehi": None,
            "computed_deck_rating": None,
            "computed_superstructure_rating": None,
            "computed_substructure_rating": None,
            "bridge_health_index": None,
            "notes": notes,
        }
    )
    store.inspections[record["id"]] = record
    return response.object_response(serializers.inspection(record), 201)


@bp.get("/inspections/<inspection_id>")
def read_inspection(inspection_id):
    authenticate_read()
    record = services.get_inspection(inspection_id)
    return response.object_response(serializers.inspection(record))


@bp.get("/inspections")
def list_inspections():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    team_leader_id = params.query_string("team_leader_id")
    qa_reviewer_id = params.query_string("qa_reviewer_id")
    status = params.query_enum("status", INSPECTION_STATUSES)
    inspection_type = params.query_enum("inspection_type", INSPECTION_TYPES)
    items = []
    for record in services.rows("inspections"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if team_leader_id is not None and record["team_leader_id"] != team_leader_id:
            continue
        if qa_reviewer_id is not None and record["qa_reviewer_id"] != qa_reviewer_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if inspection_type is not None and record["inspection_type"] != inspection_type:
            continue
        items.append(serializers.inspection(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/inspections/<inspection_id>/submit")
def submit_inspection(inspection_id):
    actor = authenticate(BRIDGE_INSPECTOR)
    body = params.json_body()
    raw_date, observed = params.get_instant(body, "inspection_date", required=True)
    record = services.get_inspection(inspection_id)
    if record["team_leader_id"] != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if record["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")

    leader = services.get_personnel(record["team_leader_id"])
    if not services.person_is_current(leader):
        raise ApiError("ERR_TEAM_LEADER_NOT_QUALIFIED")
    if record["inspection_type"] == "UNDERWATER" and not leader["underwater_diver_certified"]:
        raise ApiError("ERR_TEAM_LEADER_NOT_QUALIFIED")
    if record["inspection_type"] == "FRACTURE_CRITICAL" and not leader["fracture_critical_certified"]:
        raise ApiError("ERR_TEAM_LEADER_NOT_QUALIFIED")

    children = services.element_conditions_of(inspection_id)
    if len(children) < 1:
        raise ApiError("ERR_NO_ELEMENT_CONDITIONS")
    groups = set(child["element_group"] for child in children)
    if record["inspection_type"] == "UNDERWATER":
        required_groups = {"SUBSTRUCTURE"}
    else:
        required_groups = {"DECK_GROUP", "SUPERSTRUCTURE", "SUBSTRUCTURE"}
    if not required_groups.issubset(groups):
        raise ApiError("ERR_ELEMENT_GROUP_MISSING")
    for child in children:
        if not child["balanced"]:
            raise ApiError("ERR_ELEMENT_QUANTITY_MISMATCH")
    for child in children:
        if dec(child["deficient_quantity"]) > 0:
            notes = child.get("defect_notes")
            if int(child["photo_count"] or 0) < 1 or notes is None or str(notes).strip() == "":
                raise ApiError("ERR_PHOTO_DOCUMENTATION_MISSING")
    if (
        observed < record["_field_window_start"]
        or observed > record["_field_window_end"]
        or observed > db.now()
    ):
        raise ApiError("ERR_INSPECTION_DATE_OUT_OF_WINDOW")

    record["inspection_date"] = raw_date
    record["_inspection_date"] = observed
    record["status"] = "SUBMITTED"
    record["submitted_at"] = db.now()
    services.compute_inspection_condition(record)
    db.touch(record)
    return response.object_response(serializers.inspection(record))


@bp.post("/inspections/<inspection_id>/qa-claim")
def qa_claim(inspection_id):
    actor = authenticate(QA_REVIEWER)
    record = services.get_inspection(inspection_id)
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if actor.user_id == record["team_leader_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    reviewer = store.personnel.get(actor.user_id)
    if (
        reviewer is None
        or not reviewer["team_leader_certified"]
        or not services.person_is_current(reviewer)
    ):
        raise ApiError("ERR_QA_REVIEWER_NOT_QUALIFIED")
    record["status"] = "IN_QA"
    record["qa_reviewer_id"] = actor.user_id
    record["qa_claimed_at"] = db.now()
    db.touch(record)
    return response.object_response(serializers.inspection(record))


@bp.post("/inspections/<inspection_id>/qa-decision")
def qa_decision(inspection_id):
    actor = authenticate(QA_REVIEWER)
    body = params.json_body()
    decision = params.get_enum(body, "decision", ("RETURN", "ACCEPT"), required=True)
    return_note = params.get_string(body, "return_note")
    record = services.get_inspection(inspection_id)
    if record["status"] != "IN_QA":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    if actor.user_id == record["team_leader_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    reviewer = store.personnel.get(actor.user_id)
    if (
        reviewer is None
        or not reviewer["team_leader_certified"]
        or not services.person_is_current(reviewer)
    ):
        raise ApiError("ERR_QA_REVIEWER_NOT_QUALIFIED")
    if record["qa_reviewer_id"] != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")

    if decision == "RETURN":
        record["status"] = "DRAFT"
        record["returned_count"] = int(record["returned_count"]) + 1
        record["qa_reviewer_id"] = None
        record["qa_escalation_required"] = record["returned_count"] >= 2
        db.touch(record)
    else:
        services.accept_inspection(record)
    return response.object_response(serializers.inspection(record))


@bp.post("/inspections/<inspection_id>/void")
def void_inspection(inspection_id):
    authenticate(BRIDGE_INSPECTOR)
    params.json_body()
    record = services.get_inspection(inspection_id)
    if record["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    record["status"] = "VOIDED"
    db.touch(record)
    return response.object_response(serializers.inspection(record))


# --------------------------------------------------------------------------- #
# element conditions
# --------------------------------------------------------------------------- #
def _element_payload(body, existing=None):
    total = params.get_number(body, "total_quantity", required=True, exclusive_minimum=0)
    values = {}
    for field in ("cs1_qty", "cs2_qty", "cs3_qty", "cs4_qty"):
        values[field] = params.get_number(body, field, default=dec(0), minimum=0)
        if values[field] > total:
            params.bad("Field '%s' may not exceed total_quantity." % field)
    photo_count = params.get_int(body, "photo_count", minimum=0)
    defect_notes = params.get_string(body, "defect_notes")
    if photo_count is None:
        photo_count = existing["photo_count"] if existing is not None else 0
    if defect_notes is None and existing is not None:
        defect_notes = existing["defect_notes"]
    values["total_quantity"] = total
    values["photo_count"] = photo_count
    values["defect_notes"] = defect_notes
    return values


@bp.post("/inspections/<inspection_id>/element-conditions")
def create_element_condition(inspection_id):
    authenticate(BRIDGE_INSPECTOR)
    body = params.json_body()
    element_key = params.get_enum(body, "element_key", calc.ELEMENT_KEYS, required=True)
    element_group = params.get_enum(body, "element_group", calc.ELEMENT_GROUPS)
    mandated = calc.GROUP_OF_ELEMENT[element_key]
    if element_group is not None and element_group != mandated:
        params.bad("element_group must be %s for element_key %s." % (mandated, element_key))
    unit = params.get_enum(body, "unit", UNITS, required=True)
    values = _element_payload(body)

    inspection = services.get_inspection(inspection_id)
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    for existing in services.element_conditions_of(inspection_id):
        if existing["element_key"] == element_key:
            raise ApiError("ERR_DUPLICATE_ELEMENT_KEY")

    record = db.new_record(
        {
            "inspection_id": inspection_id,
            "element_key": element_key,
            "element_group": mandated,
            "unit": unit,
            "total_quantity": values["total_quantity"],
            "cs1_qty": values["cs1_qty"],
            "cs2_qty": values["cs2_qty"],
            "cs3_qty": values["cs3_qty"],
            "cs4_qty": values["cs4_qty"],
            "photo_count": values["photo_count"],
            "defect_notes": values["defect_notes"],
        }
    )
    services.recompute_element_condition(record)
    store.element_conditions[record["id"]] = record
    services.recompute_inspection_rollup(inspection)
    db.touch(inspection)
    return response.object_response(serializers.element_condition(record), 201)


@bp.get("/element-conditions/<element_id>")
def read_element_condition(element_id):
    authenticate_read()
    record = services.get_element_condition(element_id)
    return response.object_response(serializers.element_condition(record))


@bp.get("/element-conditions")
def list_element_conditions():
    authenticate_read()
    limit, offset = params.query_pagination()
    inspection_id = params.query_string("inspection_id")
    element_key = params.query_enum("element_key", calc.ELEMENT_KEYS)
    element_group = params.query_enum("element_group", calc.ELEMENT_GROUPS)
    balanced = params.query_bool("balanced")
    items = []
    for record in services.rows("element_conditions"):
        if inspection_id is not None and record["inspection_id"] != inspection_id:
            continue
        if element_key is not None and record["element_key"] != element_key:
            continue
        if element_group is not None and record["element_group"] != element_group:
            continue
        if balanced is not None and bool(record["balanced"]) != balanced:
            continue
        items.append(serializers.element_condition(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.put("/element-conditions/<element_id>")
def update_element_condition(element_id):
    authenticate(BRIDGE_INSPECTOR)
    body = params.json_body()
    record = services.get_element_condition(element_id)
    values = _element_payload(body, existing=record)
    inspection = services.get_inspection(record["inspection_id"])
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    record.update(values)
    services.recompute_element_condition(record)
    db.touch(record)
    services.recompute_inspection_rollup(inspection)
    db.touch(inspection)
    return response.object_response(serializers.element_condition(record))


@bp.delete("/element-conditions/<element_id>")
def delete_element_condition(element_id):
    authenticate(BRIDGE_INSPECTOR)
    record = services.get_element_condition(element_id)
    inspection = services.get_inspection(record["inspection_id"])
    if inspection["status"] != "DRAFT":
        raise ApiError("ERR_INSPECTION_STATE_INVALID")
    del store.element_conditions[record["id"]]
    services.recompute_inspection_rollup(inspection)
    db.touch(inspection)
    return response.empty_response(204)
