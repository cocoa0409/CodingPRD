"""IncidentReport endpoints + state machine (PRD §3.8)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from response import object_response
from services import calc, settlement

bp = Blueprint("incident_reports", __name__)

SEVERITIES = {"MINOR", "MAJOR", "TOTAL"}


@bp.route("/incident-reports", methods=["POST"])
def file_incident():
    _, role = get_principal()
    require_roles(role, {"RentalAgent", "FleetManager"})
    body = request.get_json(silent=True) or {}

    agreement_id = util.require_str(body, "agreement_id")
    severity = util.require_enum(body, "severity", SEVERITIES)
    assessed = util.require_int(body, "assessed_damage_cents", minimum=0)

    agreement = lookup.get_agreement(agreement_id)

    # State: incident filed against an OPEN agreement.
    if agreement["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "incidents may only be filed against an OPEN agreement")

    reservation = db.reservations[agreement["reservation_id"]]
    ldw_in_effect = reservation["ldw_selected"]
    liability = calc.incident_liability(severity, assessed, ldw_in_effect)

    rec = util.stamp_new(
        {
            "agreement_id": agreement_id,
            "severity": severity,
            "assessed_damage_cents": assessed,
            "member_liability_cents": liability,
            "status": "FILED",
        }
    )
    db.incidents[rec["id"]] = rec
    return object_response(serialize.incident(rec), 201)


@bp.route("/incident-reports/<incident_id>", methods=["GET"])
def get_incident(incident_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_incident(incident_id)
    return object_response(serialize.incident(rec), 200)


@bp.route("/incident-reports/<incident_id>/resolve", methods=["POST"])
def resolve_incident(incident_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    rec = lookup.get_incident(incident_id)

    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "incident is not FILED")

    # Priority 15: parent agreement must be CLOSED or WRITE_OFF.
    agreement = db.agreements[rec["agreement_id"]]
    if agreement["status"] not in ("CLOSED", "WRITE_OFF"):
        raise err("ERR_AGREEMENT_STILL_OPEN", "parent agreement is still OPEN")

    # Re-freeze member_liability_cents.
    reservation = db.reservations[agreement["reservation_id"]]
    rec["member_liability_cents"] = calc.incident_liability(
        rec["severity"], rec["assessed_damage_cents"], reservation["ldw_selected"]
    )
    rec["status"] = "RESOLVED"
    util.touch(rec)
    return object_response(serialize.incident(rec), 200)


@bp.route("/incident-reports/<incident_id>/void", methods=["POST"])
def void_incident(incident_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    rec = lookup.get_incident(incident_id)

    if rec["status"] != "FILED":
        raise err("ERR_INVALID_STATE", "incident is not FILED")

    agreement = db.agreements[rec["agreement_id"]]

    rec["status"] = "VOID"
    util.touch(rec)

    # If a DAMAGE ledger line was already emitted on a CLOSED agreement, emit a
    # compensating INCIDENT_REVERSAL of equal negative amount so the ledger sum
    # drops by exactly the prior DAMAGE charge.
    if agreement["status"] in ("CLOSED", "WRITE_OFF"):
        damage_emitted = any(
            e["agreement_id"] == agreement["id"] and e["kind"] == "DAMAGE"
            for e in db.ledger_entries.values()
        )
        if damage_emitted:
            reversal_amount = -rec["member_liability_cents"]
            entry = util.stamp_audit(
                {
                    "agreement_id": agreement["id"],
                    "kind": "INCIDENT_REVERSAL",
                    "amount_cents": reversal_amount,
                    "memo": "Reversal of voided incident %s" % rec["id"],
                }
            )
            db.ledger_entries[entry["id"]] = entry
            settlement.recompute_final_total(agreement)
            util.touch(agreement)

    return object_response(serialize.incident(rec), 200)
