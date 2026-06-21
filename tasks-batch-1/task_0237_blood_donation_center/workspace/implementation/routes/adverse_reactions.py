"""Adverse reactions: log (SEVERE auto-defers), reads."""
from flask import Blueprint, request

import db
import lookup
from common import get_json_body, paginate, require_enum, require_string
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_reaction

bp = Blueprint("adverse_reactions", __name__)

SEVERITIES = {"MILD", "MODERATE", "SEVERE"}


@bp.route("/blood-bank/adverse-reactions", methods=["POST"])
@require_roles("IntakeNurse", "LabTechnician")
def log_reaction():
    body = get_json_body()
    with db.lock:
        donation_id = require_string(body, "donation_id")
        severity = require_enum(body, "severity", SEVERITIES)
        symptom = require_string(body, "symptom", min_len=3)

        donation = lookup.donation(donation_id)
        center = db.centers.get(donation["center_id"])

        reaction = {
            "donation_id": donation_id,
            "donor_id": donation["donor_id"],
            "severity": severity,
            "symptom": symptom,
            "occurred_at": center["current_utc"],
            "triggered_deferral_id": None,
        }
        db.stamp_new(reaction)
        db.adverse_reactions[reaction["id"]] = reaction

        if severity == "SEVERE":
            donor = db.donors.get(donation["donor_id"])
            deferral = domain.create_deferral(
                donor, center, "ADVERSE_REACTION", "PERMANENT",
                "Auto-deferral from SEVERE adverse reaction",
                source_reaction_id=reaction["id"],
            )
            reaction["triggered_deferral_id"] = deferral["id"]
            db.touch(reaction)

        return success(serialize_reaction(reaction), status=201)


@bp.route("/blood-bank/adverse-reactions", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager")
def list_reactions():
    donation_id = request.args.get("donation_id")
    donor_id = request.args.get("donor_id")
    severity = request.args.get("severity")
    with db.lock:
        rows = list(db.adverse_reactions.values())
        if donation_id is not None:
            rows = [r for r in rows if r["donation_id"] == donation_id]
        if donor_id is not None:
            rows = [r for r in rows if r["donor_id"] == donor_id]
        if severity is not None:
            rows = [r for r in rows if r["severity"] == severity]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_reaction(r) for r in page], limit, offset, total)


@bp.route("/blood-bank/adverse-reactions/<reaction_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager")
def get_reaction(reaction_id):
    with db.lock:
        reaction = lookup.reaction(reaction_id)
        return success(serialize_reaction(reaction))
