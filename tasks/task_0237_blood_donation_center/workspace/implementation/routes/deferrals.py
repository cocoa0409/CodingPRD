"""Deferrals: manual raise, lift, reads."""
from flask import Blueprint, request

import db
import errors
import lookup
from common import (
    get_json_body,
    invalid,
    optional_integer,
    paginate,
    require_enum,
    require_string,
)
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_deferral

bp = Blueprint("deferrals", __name__)

CATEGORIES = {"TRAVEL", "MEDICATION", "HEMOGLOBIN", "ADVERSE_REACTION", "INFECTIOUS_RISK"}
KINDS = {"TEMPORARY", "PERMANENT"}


@bp.route("/blood-bank/deferrals", methods=["POST"])
@require_roles("IntakeNurse")
def create_deferral():
    body = get_json_body()
    with db.lock:
        donor_id = require_string(body, "donor_id")
        category = require_enum(body, "category", CATEGORIES)
        kind = require_enum(body, "kind", KINDS)
        reason = require_string(body, "reason", min_len=5)
        source_reaction_id = body.get("source_reaction_id")
        if source_reaction_id is not None and not isinstance(source_reaction_id, str):
            invalid("source_reaction_id must be a string.")

        # existence: donor FK
        donor = lookup.donor(donor_id)
        if source_reaction_id is not None:
            lookup.reaction(source_reaction_id)

        # duration validation (ERR_INVALID_DEFERRAL_DURATION, 422)
        duration_days = body.get("duration_days")
        if kind == "TEMPORARY":
            if not isinstance(duration_days, int) or isinstance(duration_days, bool) or duration_days < 1:
                raise ApiError(
                    errors.ERR_INVALID_DEFERRAL_DURATION,
                    422,
                    "TEMPORARY deferral requires duration_days >= 1.",
                )
        else:  # PERMANENT
            if duration_days is not None:
                raise ApiError(
                    errors.ERR_INVALID_DEFERRAL_DURATION,
                    422,
                    "PERMANENT deferral must not carry duration_days.",
                )

        center = db.centers.get(donor["center_id"])
        deferral = domain.create_deferral(
            donor, center, category, kind, reason,
            duration_days=duration_days if kind == "TEMPORARY" else None,
            source_reaction_id=source_reaction_id,
        )
        return success(serialize_deferral(deferral), status=201)


@bp.route("/blood-bank/deferrals", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")
def list_deferrals():
    donor_id = request.args.get("donor_id")
    center_id = request.args.get("center_id")
    source_reaction_id = request.args.get("source_reaction_id")
    status = request.args.get("status")
    category = request.args.get("category")
    with db.lock:
        rows = list(db.deferrals.values())
        if donor_id is not None:
            rows = [d for d in rows if d["donor_id"] == donor_id]
        if center_id is not None:
            rows = [d for d in rows if d["center_id"] == center_id]
        if source_reaction_id is not None:
            rows = [d for d in rows if d.get("source_reaction_id") == source_reaction_id]
        if status is not None:
            rows = [d for d in rows if d["status"] == status]
        if category is not None:
            rows = [d for d in rows if d["category"] == category]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_deferral(d) for d in page], limit, offset, total)


@bp.route("/blood-bank/deferrals/<deferral_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")
def get_deferral(deferral_id):
    with db.lock:
        deferral = lookup.deferral(deferral_id)
        return success(serialize_deferral(deferral))


@bp.route("/blood-bank/deferrals/<deferral_id>/lift", methods=["POST"])
@require_roles("IntakeNurse")
def lift_deferral(deferral_id):
    with db.lock:
        deferral = lookup.deferral(deferral_id)
        # state precondition first
        if deferral["status"] != "ACTIVE":
            raise ApiError(errors.ERR_DEFERRAL_NOT_ACTIVE, 409,
                           "Deferral must be ACTIVE to lift.")
        if deferral["category"] == "INFECTIOUS_RISK":
            raise ApiError(errors.ERR_INFECTIOUS_DEFERRAL_NOT_LIFTABLE, 409,
                           "INFECTIOUS_RISK deferrals cannot be lifted.")
        deferral["status"] = "LIFTED"
        db.touch(deferral)
        donor = db.donors.get(deferral["donor_id"])
        if donor is not None:
            center = db.centers.get(donor["center_id"])
            domain.recompute_donor(donor, center)
        return success(serialize_deferral(deferral))
