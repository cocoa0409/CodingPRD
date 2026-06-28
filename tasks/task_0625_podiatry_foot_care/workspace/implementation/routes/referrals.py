"""Referrals (PRD §3.10)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
import response as resp
import validate as v

bp = Blueprint("referrals", __name__)

ALL_ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}

SPECIALTIES = {"VASCULAR", "ENDOCRINOLOGY", "ORTHOPEDIC_SURGERY", "WOUND_CARE"}


@bp.route("/podiatry/referrals", methods=["POST"])
def create_referral():
    _, role = mw.authenticate()
    mw.require_role(role, {"Podiatrist"})
    body = mw.get_body()
    with db.lock():
        encounter_id = v.as_str(body, "encounter_id", required=True)
        encounter = db.encounters.get(encounter_id)
        if encounter is None:
            raise errors.fk_not_found("encounter_id references a non-existent encounter.")
        specialty = v.as_enum(body, "specialty", SPECIALTIES, required=True)
        reason = v.as_str(body, "reason", required=True)
        entity = {
            "encounter_id": encounter_id,
            "patient_id": encounter["patient_id"],
            "specialty": specialty,
            "reason": reason,
            "status": "SENT",
        }
        db.stamp_common(entity)
        db.referrals[entity["id"]] = entity
        return resp.success(entity, 201)


@bp.route("/podiatry/referrals", methods=["GET"])
def list_referrals():
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    encounter_id = request.args.get("encounter_id")
    items = [r for r in db.referrals.values()
             if encounter_id is None or r["encounter_id"] == encounter_id]
    page, meta = mw.paginate(items)
    return resp.success(page, 200, pagination=meta)


@bp.route("/podiatry/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    _, role = mw.authenticate()
    mw.require_role(role, ALL_ROLES)
    entity = db.referrals.get(referral_id)
    if entity is None:
        raise errors.not_found("Referral not found.")
    return resp.success(entity, 200)
