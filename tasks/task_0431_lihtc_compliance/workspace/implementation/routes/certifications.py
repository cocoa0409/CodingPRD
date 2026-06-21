"""Certification endpoints and lifecycle (PRD §3.3)."""

from flask import Blueprint, request

import errors
import middleware
import response
import serializers
import validate
from db import db, new_id, stamp_create, touch
from services import calc, domain

bp = Blueprint("certifications", __name__)

CERT_TYPES = {"INITIAL", "RECERT"}
DECISIONS = {"APPROVE", "REJECT"}


@bp.route("/certifications", methods=["POST"])
def create_certification():
    middleware.require_role("OwnerAgent")
    body = validate.get_json_body()
    household_id = validate.as_str(body, "household_id")
    unit_id = validate.as_str(body, "unit_id")
    cert_type = validate.as_enum(body, "cert_type", CERT_TYPES)
    annual_income = validate.as_int(body, "annual_income_cents", minimum=0)
    effective_date = validate.as_datetime(body, "effective_date")

    # Resolution order (§2.4): unit before household.
    if db.units.get(unit_id) is None:
        raise errors.not_found("Unit not found")
    if db.households.get(household_id) is None:
        raise errors.not_found("Household not found")

    cert = {
        "id": new_id(),
        "household_id": household_id,
        "unit_id": unit_id,
        "cert_type": cert_type,
        "annual_income_cents": annual_income,
        "effective_date": effective_date,
        "status": "DRAFT",
        "over_income_threshold_cents": None,
        "is_over_income": False,
    }
    stamp_create(cert)
    db.certifications[cert["id"]] = cert
    return response.success(serializers.public(cert), status=201)


@bp.route("/certifications", methods=["GET"])
def list_certifications():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    unit_id = request.args.get("unit_id")
    household_id = request.args.get("household_id")
    items = list(db.certifications.values())
    if unit_id is not None:
        items = [c for c in items if c["unit_id"] == unit_id]
    if household_id is not None:
        items = [c for c in items if c["household_id"] == household_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    middleware.require_role("OwnerAgent", "StateHFA")
    cert = db.certifications.get(cid)
    if cert is None:
        raise errors.not_found("Certification not found")
    return response.success(serializers.public(cert), status=200)


@bp.route("/certifications/<cid>/submit", methods=["POST"])
def submit_certification(cid):
    middleware.require_role("OwnerAgent")
    cert = db.certifications.get(cid)
    if cert is None:
        raise errors.not_found("Certification not found")
    if cert["status"] != "DRAFT":
        raise errors.invalid_state("Certification must be DRAFT to submit")

    unit = db.units.get(cert["unit_id"])
    household = db.households.get(cert["household_id"])

    # Priority 7: student rule (beats income limit at priority 8).
    if household is not None and not household.get("student_eligible", True):
        raise errors.ApiError(
            errors.ERR_STUDENT_INELIGIBLE, 422, "Household is student-ineligible"
        )

    income_limit = unit.get("income_limit_cents") if unit else None
    # Priority 8: INITIAL income must not exceed the unit income limit.
    if cert["cert_type"] == "INITIAL" and income_limit is not None and cert["annual_income_cents"] > income_limit:
        raise errors.ApiError(
            errors.ERR_INCOME_OVER_LIMIT, 422, "INITIAL income exceeds the unit income limit"
        )

    # Side effects: recompute over_income_threshold and is_over_income.
    if income_limit is not None:
        threshold = calc.over_income_threshold(income_limit)
    else:
        threshold = None
    cert["over_income_threshold_cents"] = threshold
    cert["is_over_income"] = bool(
        cert["cert_type"] == "RECERT"
        and threshold is not None
        and cert["annual_income_cents"] > threshold
    )
    cert["status"] = "SUBMITTED"
    touch(cert)
    return response.success(serializers.public(cert), status=200)


@bp.route("/certifications/<cid>/revise", methods=["POST"])
def revise_certification(cid):
    middleware.require_role("OwnerAgent")
    cert = db.certifications.get(cid)
    if cert is None:
        raise errors.not_found("Certification not found")
    if cert["status"] != "SUBMITTED":
        raise errors.invalid_state("Certification must be SUBMITTED to revise")
    cert["status"] = "DRAFT"
    touch(cert)
    return response.success(serializers.public(cert), status=200)


@bp.route("/certifications/<cid>/approve", methods=["POST"])
def approve_certification(cid):
    middleware.require_role("StateHFA")
    cert = db.certifications.get(cid)
    if cert is None:
        raise errors.not_found("Certification not found")
    body = validate.get_json_body()
    decision = validate.as_enum(body, "decision", DECISIONS)
    if cert["status"] != "SUBMITTED":
        raise errors.invalid_state("Certification must be SUBMITTED to decide")

    if decision == "REJECT":
        cert["status"] = "REJECTED"
        touch(cert)
        return response.success(serializers.public(cert), status=200)

    # APPROVE
    cert["status"] = "APPROVED"
    touch(cert)
    unit = db.units.get(cert["unit_id"])
    if unit is not None:
        _apply_unit_side_effects(cert, unit)
    return response.success(serializers.public(cert), status=200)


def _apply_unit_side_effects(cert, unit):
    changed = False
    if cert["cert_type"] == "INITIAL":
        if unit["ami_designation"] != "MARKET" and unit["li_status"] == "VACANT_NEVER_OCCUPIED":
            unit["li_status"] = "QUALIFIED"
            unit["is_low_income_counted"] = True
            changed = True
    else:  # RECERT
        if cert["is_over_income"] and unit["li_status"] == "QUALIFIED":
            unit["li_status"] = "OVER_INCOME"
            unit["is_low_income_counted"] = True
            changed = True
        elif (not cert["is_over_income"]) and unit["li_status"] == "OVER_INCOME":
            unit["li_status"] = "QUALIFIED"
            unit["is_low_income_counted"] = True
            changed = True
    if changed:
        touch(unit)
        building = db.buildings.get(unit["building_id"])
        if building is not None:
            domain.reconcile_building(building)
