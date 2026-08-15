"""RecyclingIntake endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_number, as_string, body, optional, require
from services import calc, cascade

bp = Blueprint("recycling", __name__)


def intake_view(i):
    return {
        "id": i["id"],
        "retailer_id": i["retailer_id"],
        "unit_id": i["unit_id"],
        "declared_weight_kg": i["declared_weight_kg"],
        "provisional_credit_cents": i["provisional_credit_cents"],
        "final_credit_cents": i["final_credit_cents"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def get_intake(intake_id):
    i = db.intakes.get(intake_id)
    if i is None:
        errors.raise_err(errors.ERR_INTAKE_NOT_FOUND, "intake not found")
    return i


@bp.route("/recycling-intakes", methods=["POST"])
def create_intake():
    middleware.require_roles(["LogisticsCoordinator"])
    data = body()
    retailer_id = as_string(require(data, "retailer_id"), "retailer_id")
    declared = as_number(require(data, "declared_weight_kg"), "declared_weight_kg")
    if calc.dec(declared) <= 0:
        errors.raise_err(errors.ERR_VALIDATION_FAILED, "declared_weight_kg must be > 0")
    unit_id = optional(data, "unit_id", None)
    if unit_id is not None:
        as_string(unit_id, "unit_id")
    # body-FK existence: unit reference (when given) before retailer
    unit = None
    if unit_id is not None:
        unit = db.units.get(unit_id)
        if unit is None:
            errors.raise_err(errors.ERR_UNIT_NOT_FOUND, "unit not found")
    retailer = db.retailers.get(retailer_id)
    if retailer is None:
        errors.raise_err(errors.ERR_RETAILER_NOT_FOUND, "retailer not found")
    # tier 8: program gate
    if not retailer["recycling_enrolled"]:
        errors.raise_err(errors.ERR_RECYCLING_NOT_ENROLLED, "retailer not recycling-enrolled")
    # tier 10: unit link must be a SCRAPPED unit owned by the same retailer
    if unit_id is not None:
        if (
            unit["status"] != "SCRAPPED"
            or unit["retailer_id"] != retailer_id
        ):
            errors.raise_err(
                errors.ERR_UNIT_NOT_SCRAPPED,
                "unit_id must reference a SCRAPPED unit owned by the retailer",
            )
    provisional = calc.recycling_provisional(declared)
    # tier 11: fiscal cap on the provisional posting
    if retailer["credit_balance_cents"] + provisional > retailer["credit_limit_cents"]:
        errors.raise_err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "credit limit exceeded")
    intake = cascade.create_recycling_intake(
        retailer, declared, unit_id, "RECYCLING_PROVISIONAL"
    )
    return response.success_object(intake_view(intake), 201)


@bp.route("/recycling-intakes", methods=["GET"])
def list_intakes():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.intakes.values())
    for param in ("retailer_id", "unit_id", "status"):
        q = request.args.get(param)
        if q is not None:
            items = [i for i in items if i[param] == q]
    items.sort(key=lambda i: i["_seq"])
    return response.success_list([intake_view(i) for i in items])


@bp.route("/recycling-intakes/<intakeId>", methods=["GET"])
def get_one_intake(intakeId):
    middleware.require_roles(middleware.ALL_ROLES)
    i = get_intake(intakeId)
    return response.success_object(intake_view(i))


@bp.route("/recycling-intakes/<intakeId>/finalize", methods=["POST"])
def finalize_intake(intakeId):
    middleware.require_roles(["PlantManager"])
    intake = get_intake(intakeId)
    data = body()
    steel = as_number(require(data, "actual_steel_kg"), "actual_steel_kg")
    foam = as_number(require(data, "actual_foam_kg"), "actual_foam_kg")
    fiber = as_number(require(data, "actual_fiber_kg"), "actual_fiber_kg")
    wood = as_number(require(data, "actual_wood_kg"), "actual_wood_kg")
    if intake["status"] != "RECEIVED":
        errors.raise_err(errors.ERR_INTAKE_NOT_RECEIVED, "intake must be RECEIVED")
    final = calc.recycling_final(steel, foam, fiber, wood)
    retailer = db.retailers[intake["retailer_id"]]
    delta = final - intake["provisional_credit_cents"]
    cascade.post_credit_adjustment(
        retailer,
        delta,
        "Recycling take-back final reconciliation",
        "RECYCLING_FINAL_DELTA",
        intake["id"],
    )
    intake["final_credit_cents"] = final
    intake["status"] = "FINALIZED"
    cascade.bump(intake)
    return response.success_object(intake_view(intake))
