"""SafetyForm endpoints (PRD 3.4)."""
from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize
from errors import raise_err
from util import (
    body_json,
    bump,
    get_or_404,
    list_response,
    new_record,
    opt_str,
    req_str,
    serialize,
    success_object,
)

bp = Blueprint("safety_forms", __name__)

FIELDS = [
    "id",
    "participant_id",
    "season_id",
    "emergency_contact_name",
    "emergency_contact_phone",
    "medical_notes",
    "signer_name",
    "status",
    "created_at",
    "updated_at",
    "version",
]

ROLES = ["HouseholdManager", "FrontDeskStaff", "ProgramCoordinator"]


def form_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/safety-forms", methods=["POST"])
def create_form():
    uid, role = authenticate()
    authorize(role, ["HouseholdManager"])
    body = body_json()
    participant_id = req_str(body, "participant_id")
    season_id = req_str(body, "season_id")
    emergency_contact_name = req_str(body, "emergency_contact_name")
    emergency_contact_phone = req_str(body, "emergency_contact_phone")
    medical_notes = opt_str(body, "medical_notes", "")
    signer_name = req_str(body, "signer_name")
    participant = get_or_404(store.participants, participant_id, "Participant")
    season = get_or_404(store.seasons, season_id, "Season")
    # Signature rules first (PRD 3.4): minors need a guardian signature,
    # adults must self-sign; age is measured at the season's start_date.
    age = services.age_years(participant["birth_date"], season["start_date"])
    if age < 18:
        if signer_name == participant["full_name"]:
            raise_err("ERR_GUARDIAN_SIGNATURE_REQUIRED", "A minor's form must be signed by someone other than the participant")
    else:
        if signer_name != participant["full_name"]:
            raise_err("ERR_SELF_SIGNATURE_REQUIRED", "An adult's form must be self-signed")
    # Then the duplicate-form guard.
    for f in store.safety_forms.values():
        if (
            f["participant_id"] == participant_id
            and f["season_id"] == season_id
            and f["status"] in ("SUBMITTED", "VERIFIED")
        ):
            raise_err("ERR_DUPLICATE_SAFETY_FORM", "A live safety form already exists for this participant and season")
    # The household-membership check comes after both.
    if participant["household_id"] != uid:
        raise_err("ERR_NOT_HOUSEHOLD_MEMBER", "The participant must belong to the caller's household")
    rec = new_record()
    rec.update(
        participant_id=participant_id,
        season_id=season_id,
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
        medical_notes=medical_notes,
        signer_name=signer_name,
        status="SUBMITTED",
    )
    store.safety_forms[rec["id"]] = rec
    return success_object(form_out(rec), 201)


@bp.route("/safety-forms", methods=["GET"])
def list_forms():
    _, role = authenticate()
    authorize(role, ROLES)
    participant_id = request.args.get("participant_id")
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    records = list(store.safety_forms.values())
    if participant_id is not None:
        records = [r for r in records if r["participant_id"] == participant_id]
    if season_id is not None:
        records = [r for r in records if r["season_id"] == season_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, form_out)


@bp.route("/safety-forms/<form_id>", methods=["GET"])
def get_form(form_id):
    _, role = authenticate()
    authorize(role, ROLES)
    rec = get_or_404(store.safety_forms, form_id, "SafetyForm")
    return success_object(form_out(rec), 200)


@bp.route("/safety-forms/<form_id>/verify", methods=["POST"])
def verify_form(form_id):
    _, role = authenticate()
    authorize(role, ["FrontDeskStaff"])
    rec = get_or_404(store.safety_forms, form_id, "SafetyForm")
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED form can be verified")
    rec["status"] = "VERIFIED"
    bump(rec)
    return success_object(form_out(rec), 200)


@bp.route("/safety-forms/<form_id>/reject", methods=["POST"])
def reject_form(form_id):
    _, role = authenticate()
    authorize(role, ["FrontDeskStaff"])
    body_json()  # optional reason is accepted and not persisted
    rec = get_or_404(store.safety_forms, form_id, "SafetyForm")
    if rec["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED form can be rejected")
    rec["status"] = "REJECTED"
    bump(rec)
    return success_object(form_out(rec), 200)
