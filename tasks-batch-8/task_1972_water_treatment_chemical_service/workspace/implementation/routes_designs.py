"""ProgramDesign endpoints: the survey -> draft -> propose -> accept cycle."""

from flask import Blueprint, g

import errors
from calc import feed_rate_setpoint, recompute_station
from db import db, create_entity, touch
from helpers import list_response, account_of_design, query_filter
from response import success_object
from serializers import program_design as ser
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership)

bp = Blueprint("program_designs", __name__)

DRAFT_FIELDS = ("proposed_coc", "inhibitor_target_ppm", "ph_min", "ph_max",
                "conductivity_max_umhos", "service_rate_cents_per_month")


def _owning_account_id(design):
    asset = db["assets"].get(design["asset_id"])
    return asset["account_id"] if asset else None


@bp.route("/wt/program-designs", methods=["POST"])
def create_design():
    body = get_body()
    asset = resolve_body_fk(body, "asset_id", "assets")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("survey_notes", "str", False),
    ])
    ent = create_entity("program_designs", {
        "asset_id": asset["id"],
        "survey_notes": vals["survey_notes"],
        "proposed_coc": None,
        "inhibitor_target_ppm": None,
        "ph_min": None,
        "ph_max": None,
        "conductivity_max_umhos": None,
        "service_rate_cents_per_month": None,
        "revision_number": 1,
        "status": "SURVEY_SCHEDULED",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/program-designs", methods=["GET"])
def list_designs():
    user = (g.role, g.user_id)
    items = list(db["program_designs"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [d for d in items if d["asset_id"] == asset_id]
    status = query_filter("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response(items, ser, account_of_design, user)


@bp.route("/wt/program-designs/<designId>", methods=["GET"])
def get_design(designId):
    ent = db["program_designs"].get(designId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, _owning_account_id(ent))
    ent = resolve("program_designs", designId)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/record-survey", methods=["POST"])
def record_survey(designId):
    ent = resolve("program_designs", designId)
    body = get_body()
    vals = validate_shape(body, [("survey_notes", "str", True)])
    if ent["status"] != "SURVEY_SCHEDULED":
        raise errors.invalid_state("Design must be SURVEY_SCHEDULED to record the survey")
    ent["survey_notes"] = vals["survey_notes"]
    ent["status"] = "SURVEYED"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/draft", methods=["POST"])
def draft_design(designId):
    ent = resolve("program_designs", designId)
    body = get_body()
    # Missing design parameters carry their own code (ERR_INCOMPLETE_DESIGN).
    vals = validate_shape(body, [
        ("proposed_coc", "num", True),
        ("inhibitor_target_ppm", "num", True),
        ("ph_min", "num", True),
        ("ph_max", "num", True),
        ("conductivity_max_umhos", "int", True),
        ("service_rate_cents_per_month", "int", True),
    ], missing_error=lambda: errors.ApiError(
        errors.ERR_INCOMPLETE_DESIGN, 422,
        "Draft requires proposed_coc, inhibitor_target_ppm, ph_min, ph_max, "
        "conductivity_max_umhos and service_rate_cents_per_month"))
    if ent["status"] != "SURVEYED":
        raise errors.invalid_state("Design must be SURVEYED to draft")
    # Tier 10 field constraints.
    if not (1.5 <= vals["proposed_coc"] <= 12.0):
        raise errors.field_constraint("proposed_coc must lie between 1.5 and 12.0 inclusive")
    if vals["inhibitor_target_ppm"] <= 0:
        raise errors.field_constraint("inhibitor_target_ppm must be > 0")
    if vals["ph_min"] < 6.0:
        raise errors.field_constraint("ph_min must be at least 6.0")
    if vals["ph_max"] > 10.0:
        raise errors.field_constraint("ph_max must be at most 10.0")
    if not vals["ph_min"] < vals["ph_max"]:
        raise errors.field_constraint("ph_min must be strictly below ph_max")
    if vals["conductivity_max_umhos"] <= 0:
        raise errors.field_constraint("conductivity_max_umhos must be a positive whole number")
    if vals["service_rate_cents_per_month"] < 0:
        raise errors.field_constraint("service_rate_cents_per_month must be >= 0")
    for f in DRAFT_FIELDS:
        ent[f] = vals[f]
    ent["status"] = "DRAFTED"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/propose", methods=["POST"])
def propose_design(designId):
    ent = resolve("program_designs", designId)
    if ent["status"] != "DRAFTED":
        raise errors.invalid_state("Design must be DRAFTED to propose")
    ent["status"] = "PROPOSED"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/accept", methods=["POST"])
def accept_design(designId):
    ent = db["program_designs"].get(designId)
    if ent is not None:
        # Tier 3 ownership: CustomerContact must own the design's account.
        check_cc_ownership(g.user_id, g.role, _owning_account_id(ent))
    ent = resolve("program_designs", designId)
    body = get_body()
    vals = validate_shape(body, [("expected_program_design_version", "int", True)])
    if ent["status"] != "PROPOSED":
        raise errors.invalid_state("Design must be PROPOSED to accept")
    # Tier 15 OCC.
    if vals["expected_program_design_version"] != ent["version"]:
        raise errors.stale_version()
    asset = db["assets"][ent["asset_id"]]
    # Supersede any other ACCEPTED design of the same asset.
    for other in db["program_designs"].values():
        if other["asset_id"] == ent["asset_id"] and other["id"] != ent["id"] \
                and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
    ent["status"] = "ACCEPTED"
    touch(ent)
    # Freeze the asset's target_coc to the accepted proposal.
    if asset["target_coc"] != ent["proposed_coc"]:
        asset["target_coc"] = ent["proposed_coc"]
        touch(asset)
    # Recompute every feed station of the asset against the new target.
    for station in db["feed_stations"].values():
        if station["asset_id"] != asset["id"]:
            continue
        product = db["products"].get(station["product_id"])
        if product is None:
            continue
        new_setpoint = feed_rate_setpoint(asset, ent, product, station)
        if station["setpoint_ml_per_min"] != new_setpoint:
            station["setpoint_ml_per_min"] = new_setpoint
            touch(station)
        recompute_station(station)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/request-revision", methods=["POST"])
def request_revision(designId):
    ent = db["program_designs"].get(designId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, _owning_account_id(ent))
    ent = resolve("program_designs", designId)
    get_body()
    if ent["status"] != "PROPOSED":
        raise errors.invalid_state("Design must be PROPOSED to request revision")
    ent["status"] = "REVISE_REQUESTED"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/reopen-survey", methods=["POST"])
def reopen_survey(designId):
    ent = resolve("program_designs", designId)
    get_body()
    if ent["status"] != "REVISE_REQUESTED":
        raise errors.invalid_state("Design must be REVISE_REQUESTED to reopen the survey")
    ent["status"] = "SURVEYED"
    ent["revision_number"] += 1
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/program-designs/<designId>/withdraw", methods=["POST"])
def withdraw_design(designId):
    ent = resolve("program_designs", designId)
    get_body()
    if ent["status"] != "PROPOSED":
        raise errors.invalid_state("Design must be PROPOSED to withdraw")
    ent["status"] = "WITHDRAWN"
    touch(ent)
    return success_object(ser(ent), 200)
