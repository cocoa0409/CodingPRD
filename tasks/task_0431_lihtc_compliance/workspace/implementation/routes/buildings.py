"""Building endpoints incl. Form 8609 issuance, revoke, recapture (PRD §3.1, §3.5, §3.6)."""

from flask import Blueprint, g

import errors
import middleware
import response
import serializers
import validate
from db import db, new_id, stamp_create, touch
from services import calc, domain

bp = Blueprint("buildings", __name__)

CREDIT_TYPES = {"NINE_PERCENT", "FOUR_PERCENT"}
ISSUANCE_TYPES = {"PROVISIONAL", "FINAL"}


@bp.route("/buildings", methods=["POST"])
def create_building():
    middleware.require_role("OwnerAgent")
    body = validate.get_json_body()
    project_id = validate.as_str(body, "project_id")
    bin_ = validate.as_str(body, "bin")
    eligible_basis = validate.as_int(body, "eligible_basis_cents", minimum=0)
    credit_type = validate.as_enum(body, "credit_type", CREDIT_TYPES)
    total_units = validate.as_int(body, "total_residential_units", minimum=1)
    total_sqft = validate.as_int(body, "total_residential_sqft", minimum=1)

    if db.projects.get(project_id) is None:
        raise errors.not_found("Project not found")

    building = {
        "id": new_id(),
        "project_id": project_id,
        "bin": bin_,
        "eligible_basis_cents": eligible_basis,
        "credit_type": credit_type,
        "total_residential_units": total_units,
        "total_residential_sqft": total_sqft,
        "applicable_fraction": 0.0,
        "qualified_basis_cents": 0,
        "first_year_fraction": 0.0,
        "annual_credit_cents": 0,
        "credit_status": "PRE_ALLOCATION",
    }
    stamp_create(building)
    db.buildings[building["id"]] = building
    return response.success(serializers.public(building), status=201)


@bp.route("/buildings", methods=["GET"])
def list_buildings():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    from flask import request
    project_id = request.args.get("project_id")
    items = list(db.buildings.values())
    if project_id is not None:
        items = [b for b in items if b["project_id"] == project_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/buildings/<bid>", methods=["GET"])
def get_building(bid):
    middleware.require_role("OwnerAgent", "StateHFA")
    building = db.buildings.get(bid)
    if building is None:
        raise errors.not_found("Building not found")
    return response.success(serializers.public(building), status=200)


@bp.route("/buildings/<bid>/form8609", methods=["POST"])
def issue_form8609(bid):
    middleware.require_role("StateHFA")
    building = db.buildings.get(bid)
    if building is None:
        raise errors.not_found("Building not found")
    body = validate.get_json_body()
    issuance_type = validate.as_enum(body, "issuance_type", ISSUANCE_TYPES)

    if issuance_type == "PROVISIONAL":
        return _issue_provisional(building, body)
    return _issue_final(building, body)


def _issue_provisional(building, body):
    # State precondition (priority 4) before the set-aside business check (priority 11).
    if building["credit_status"] != "PRE_ALLOCATION":
        raise errors.invalid_state("Building must be PRE_ALLOCATION for a PROVISIONAL 8609")
    project = db.projects.get(building["project_id"])
    if project is None or project["status"] not in ("SET_ASIDE_MET", "CREDIT_PERIOD"):
        raise errors.ApiError(
            errors.ERR_SET_ASIDE_NOT_MET, 409,
            "Owning project must be SET_ASIDE_MET or CREDIT_PERIOD",
        )

    units = domain.units_for_building(building["id"])
    frac = calc.provisional_fraction(building, units)
    building["first_year_fraction"] = float(frac)
    building["annual_credit_cents"] = calc.credit_from_fraction(building, frac)
    building["credit_status"] = "PROVISIONAL_8609"
    touch(building)

    form = _snapshot_form(building, "PROVISIONAL")
    return response.success(serializers.public(form), status=201)


def _issue_final(building, body):
    if building["credit_status"] != "PROVISIONAL_8609":
        raise errors.invalid_state("Building must be PROVISIONAL_8609 for a FINAL 8609")
    monthly = validate.as_int_array(body, "monthly_qualified_units", required=True, length=12)
    expected_version = validate.as_int(body, "expected_building_version", required=True)
    if expected_version != building["version"]:
        raise errors.stale_version()

    frac = calc.final_chronological_fraction(building, monthly)
    building["first_year_fraction"] = float(frac)
    building["annual_credit_cents"] = calc.credit_from_fraction(building, frac)
    building["credit_status"] = "FINAL_8609"
    touch(building)  # FINAL increments Building.version by 1

    form = _snapshot_form(building, "FINAL")
    return response.success(serializers.public(form), status=201)


def _snapshot_form(building, issuance_type):
    form = {
        "id": new_id(),
        "building_id": building["id"],
        "issuance_type": issuance_type,
        "allocated_fraction": building["first_year_fraction"],
        "allocated_annual_credit_cents": building["annual_credit_cents"],
        "status": "ISSUED",
    }
    stamp_create(form)
    db.form8609s[form["id"]] = form
    return form


@bp.route("/buildings/<bid>/revoke-final", methods=["POST"])
def revoke_final(bid):
    middleware.require_role("StateHFA")
    building = db.buildings.get(bid)
    if building is None:
        raise errors.not_found("Building not found")
    if building["credit_status"] != "FINAL_8609":
        raise errors.invalid_state("Building must be FINAL_8609 to revoke")

    # Revoke the most recent ISSUED FINAL Form8609 for this building.
    final_form = _latest_form(building["id"], "FINAL", "ISSUED")
    if final_form is not None:
        final_form["status"] = "REVOKED"
        touch(final_form)

    units = domain.units_for_building(building["id"])
    frac = calc.provisional_fraction(building, units)
    building["first_year_fraction"] = float(frac)
    building["annual_credit_cents"] = calc.credit_from_fraction(building, frac)
    building["credit_status"] = "PROVISIONAL_8609"
    touch(building)
    return response.success(serializers.public(building), status=200)


@bp.route("/buildings/<bid>/recapture", methods=["POST"])
def recapture(bid):
    middleware.require_role("StateHFA")
    building = db.buildings.get(bid)
    if building is None:
        raise errors.not_found("Building not found")
    body = validate.get_json_body()
    if building["credit_status"] != "FINAL_8609":
        raise errors.invalid_state("Building must be FINAL_8609 to recapture")
    project = db.projects.get(building["project_id"])
    if project is None or project["posture"] != "NONCOMPLIANT":
        raise errors.ApiError(
            errors.ERR_RECAPTURE_REQUIRES_NONCOMPLIANT, 409,
            "Owning project must be NONCOMPLIANT to recapture",
        )
    expected_version = validate.as_int(body, "expected_building_version", required=True)
    if expected_version != building["version"]:
        raise errors.stale_version()

    final_form = _latest_form(building["id"], "FINAL", "ISSUED")
    if final_form is not None:
        final_form["status"] = "REVOKED"
        touch(final_form)

    building["annual_credit_cents"] = 0
    building["applicable_fraction"] = 0.0
    building["qualified_basis_cents"] = 0
    building["credit_status"] = "RECAPTURED"
    touch(building)  # increments Building.version by 1
    return response.success(serializers.public(building), status=200)


def _latest_form(building_id, issuance_type, status):
    candidates = [
        f for f in db.form8609s.values()
        if f["building_id"] == building_id
        and f["issuance_type"] == issuance_type
        and f["status"] == status
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.get("_seq", 0))
