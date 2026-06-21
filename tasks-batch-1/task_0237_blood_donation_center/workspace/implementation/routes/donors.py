"""Donor registration and reads."""
from flask import Blueprint, request

import db
import lookup
from common import (
    get_json_body,
    paginate,
    require_enum,
    require_number,
    require_string,
)
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_donor

bp = Blueprint("donors", __name__)


@bp.route("/blood-bank/donors", methods=["POST"])
@require_roles("IntakeNurse", "Donor")
def register_donor():
    body = get_json_body()
    with db.lock:
        center_id = require_string(body, "center_id")
        full_name = require_string(body, "full_name")
        date_of_birth = require_string(body, "date_of_birth")
        weight_kg = require_number(body, "weight_kg")
        blood_type = require_enum(body, "blood_type", domain.BLOOD_TYPES)
        # existence: center FK
        center = lookup.center(center_id)
        # validate date_of_birth shape
        from timeutil import parse_date
        if parse_date(date_of_birth) is None:
            from common import invalid
            invalid("date_of_birth must be an ISO date YYYY-MM-DD.")

        donor = {
            "center_id": center_id,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "weight_kg": weight_kg,
            "blood_type": blood_type,
            "eligibility_status": "ELIGIBLE",
            "last_qualifying_donation_id": None,
            "pending_donation_type": "NONE",
            "lifetime_collected_count": 0,
        }
        db.stamp_new(donor)
        db.donors[donor["id"]] = donor
        # compute eligibility at registration (UNDERAGE vs ELIGIBLE)
        domain.recompute_eligibility(donor, center)
        return success(serialize_donor(donor), status=201)


@bp.route("/blood-bank/donors", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager")
def list_donors():
    center_id = request.args.get("center_id")
    eligibility_status = request.args.get("eligibility_status")
    blood_type = request.args.get("blood_type")
    with db.lock:
        rows = list(db.donors.values())
        # recompute derived fields so filters see live values
        for d in rows:
            domain.donor_view(d)
        if center_id is not None:
            rows = [d for d in rows if d["center_id"] == center_id]
        if eligibility_status is not None:
            rows = [d for d in rows if d["eligibility_status"] == eligibility_status]
        if blood_type is not None:
            rows = [d for d in rows if d["blood_type"] == blood_type]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_donor(d) for d in page], limit, offset, total)


@bp.route("/blood-bank/donors/<donor_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")
def get_donor(donor_id):
    with db.lock:
        donor = lookup.donor(donor_id)
        return success(serialize_donor(donor))
