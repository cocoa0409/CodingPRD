"""Legacy wellbore endpoints (PRD 3.3)."""

from decimal import Decimal as D

from flask import Blueprint

import clock
import db
import enums
import middleware as mw
import response
from errors import ApiError
from services import calc, derive, lookup, serialize

bp = Blueprint("wellbores", __name__)

ADMIN = "ProgramAdmin"
DEV = "ProjectDeveloper"
REVIEWER = "RegulatoryReviewer"


@bp.post("/ccs/legacy-wellbores")
@mw.require(DEV)
def create_wellbore():
    payload = mw.body()
    project_id = mw.req_str(payload, "project_id")
    api_number = mw.req_str(payload, "api_number")
    distance = mw.req_num(payload, "distance_from_injector_km", ge=0)
    total_depth = mw.req_num(payload, "total_depth_m", gt=0)
    penetrates_seal = mw.req_bool(payload, "penetrates_seal")
    plug_condition = mw.req_enum(payload, "plug_condition", enums.PLUG_CONDITION)
    plug_record_available = mw.req_bool(payload, "plug_record_available")

    project = lookup.project(project_id)
    derive.require_not_frozen(project)

    for existing in db.wellbores_of(project["id"]):
        if existing["api_number"] == api_number:
            raise ApiError(
                "ERR_DUPLICATE_API_NUMBER", "api_number already registered for this project"
            )

    row = db.base_fields()
    row.update(
        {
            "project_id": project["id"],
            "api_number": api_number,
            "distance_from_injector_km": distance,
            "total_depth_m": total_depth,
            "penetrates_seal": penetrates_seal,
            "plug_condition": plug_condition,
            "plug_record_available": plug_record_available,
            "risk_score": D("0.00"),
            "ca_cost_estimate_usd": D("0.00"),
            "corrective_action_status": "OUT_OF_AOR",
            "ca_window_start": None,
            "ca_window_end": None,
            "waiver_reviewer_user_id": None,
        }
    )

    risk, cost = calc.wellbore_risk(row, project["aor_radius_km"])
    row["risk_score"] = risk
    row["ca_cost_estimate_usd"] = cost

    aor = D(project["aor_radius_km"])
    if aor <= 0 or distance > aor:
        row["corrective_action_status"] = "OUT_OF_AOR"
    else:
        row["corrective_action_status"] = "IDENTIFIED"
        derive.screen_wellbore_for_ca(row)

    db.legacy_wellbores[row["id"]] = row

    derive.recompute_ca_completion(project)
    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.wellbore(row), 201)


@bp.get("/ccs/legacy-wellbores/<wellbore_id>")
@mw.require(ADMIN, DEV, REVIEWER)
def get_wellbore(wellbore_id):
    return response.object_response(serialize.wellbore(lookup.wellbore(wellbore_id)))


@bp.post("/ccs/legacy-wellbores/<wellbore_id>/schedule-corrective-action")
@mw.require(DEV)
def schedule_corrective_action(wellbore_id):
    payload = mw.body()
    window_start = mw.req_ts(payload, "window_start")
    window_end = mw.req_ts(payload, "window_end")
    start_dt = clock.must_parse(window_start, "window_start")
    end_dt = clock.must_parse(window_end, "window_end")
    if not end_dt > start_dt:
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")

    wellbore = lookup.wellbore(wellbore_id)
    project = db.projects.get(wellbore["project_id"])
    derive.require_not_frozen(project)

    if wellbore["corrective_action_status"] != "CA_REQUIRED":
        raise ApiError(
            "ERR_INVALID_WELLBORE_CA_STATE", "corrective action may only be scheduled from CA_REQUIRED"
        )

    concurrent = 0
    for sibling in db.wellbores_of(project["id"]):
        if sibling["id"] == wellbore["id"]:
            continue
        if sibling["corrective_action_status"] != "CA_SCHEDULED":
            continue
        sib_start = clock.parse_iso(sibling["ca_window_start"])
        sib_end = clock.parse_iso(sibling["ca_window_end"])
        if sib_start is None or sib_end is None:
            continue
        if sib_start <= end_dt and start_dt <= sib_end:
            concurrent += 1
    if concurrent >= project["ca_rig_slots"]:
        raise ApiError(
            "ERR_CA_RIG_CAPACITY_EXCEEDED", "the project's corrective-action rig slots are exhausted"
        )

    wellbore["ca_window_start"] = window_start
    wellbore["ca_window_end"] = window_end
    wellbore["corrective_action_status"] = "CA_SCHEDULED"
    db.touch(wellbore)
    return response.object_response(serialize.wellbore(wellbore))


@bp.post("/ccs/legacy-wellbores/<wellbore_id>/complete-corrective-action")
@mw.require(DEV)
def complete_corrective_action(wellbore_id):
    payload = mw.body()
    mw.opt_str(payload, "completion_note")

    wellbore = lookup.wellbore(wellbore_id)
    project = db.projects.get(wellbore["project_id"])
    derive.require_not_frozen(project)

    if wellbore["corrective_action_status"] != "CA_SCHEDULED":
        raise ApiError(
            "ERR_INVALID_WELLBORE_CA_STATE", "corrective action may only be completed from CA_SCHEDULED"
        )

    window_start = clock.parse_iso(wellbore["ca_window_start"])
    if window_start is not None and clock.now() < window_start:
        raise ApiError(
            "ERR_INVALID_WELLBORE_CA_STATE",
            "corrective action cannot be completed before its window opens",
        )

    wellbore["corrective_action_status"] = "CA_COMPLETE"
    db.touch(wellbore)

    derive.recompute_ca_completion(project)
    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.wellbore(wellbore))


@bp.post("/ccs/legacy-wellbores/<wellbore_id>/waive-corrective-action")
@mw.require(REVIEWER)
def waive_corrective_action(wellbore_id):
    payload = mw.body()
    mw.req_str(payload, "waiver_rationale")

    wellbore = lookup.wellbore(wellbore_id)
    project = db.projects.get(wellbore["project_id"])
    derive.require_not_frozen(project)

    if wellbore["corrective_action_status"] != "CA_REQUIRED":
        raise ApiError(
            "ERR_INVALID_WELLBORE_CA_STATE", "a waiver is only admissible from CA_REQUIRED"
        )

    if wellbore["penetrates_seal"] or wellbore["risk_score"] > calc.CA_WAIVER_RISK_CEILING:
        raise ApiError(
            "ERR_CA_WAIVER_NOT_ELIGIBLE",
            "the wellbore penetrates the confining zone or its risk score exceeds 60.00",
        )

    wellbore["corrective_action_status"] = "CA_WAIVED"
    wellbore["waiver_reviewer_user_id"] = mw.caller_id()
    db.touch(wellbore)

    derive.recompute_ca_completion(project)
    derive.recompute_required_assurance(project)
    db.touch(project)

    return response.object_response(serialize.wellbore(wellbore))
