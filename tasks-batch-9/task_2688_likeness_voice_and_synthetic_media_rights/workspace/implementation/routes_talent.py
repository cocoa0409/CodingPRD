"""Talent records, death recording and estate administration."""

from flask import Blueprint, g

import calc
import guards
import services
from core import (
    ALL_ROLES, authorize, body_json, collection, db, fail, invalid, new_id, now,
    public, respond, touch, want_code, want_dt, want_enum, want_str,
)

bp = Blueprint("talents", __name__)

UNION_CHOICES = ("NONE", "SAG_AFTRA", "AFM")


@bp.post("/talents")
def create_talent():
    authorize("RightsAdministrator")
    body = body_json()
    legal_name = want_str(body, "legal_name", 1, 200)
    domicile_state_code = want_code(body, "domicile_state_code")
    union_code = want_enum(body, "union_code", UNION_CHOICES,
                           required=False, default="NONE")
    guards.need_profile(domicile_state_code)
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "legal_name": legal_name,
        "domicile_state_code": domicile_state_code,
        "union_code": union_code,
        "life_status": "LIVING",
        "date_of_death": None,
        "postmortem_rights_until": None,
        "postmortem_registration_number": None,
        "rights_posture": "CLEAR",
        "open_removal_obligation_count": 0,
        "legal_hold_asset_count": 0,
        "lifetime_compensation_cents": 0,
        "_seq": db.next_seq(),
    }
    db.talents[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/talents/<row_id>")
def read_talent(row_id):
    authorize(*ALL_ROLES)
    return respond(public(guards.need_talent(row_id)))


@bp.get("/talents")
def list_talents():
    authorize("RightsAdministrator", "ComplianceOfficer")
    return collection(db.talents.values(), {
        "domicile_state_code": "domicile_state_code",
        "life_status": "life_status",
        "rights_posture": "rights_posture",
    })


@bp.post("/talents/<row_id>/death-record")
def record_death(row_id):
    authorize("RightsAdministrator")
    body = body_json()
    date_of_death = want_dt(body, "date_of_death")
    if date_of_death > now():
        invalid("date_of_death must be at or before the current logical instant")
    talent = guards.need_talent(row_id)
    profile = guards.need_profile(talent["domicile_state_code"])
    if talent["life_status"] != "LIVING":
        fail("ERR_INVALID_TALENT_STATE", "this talent is already DECEASED")
    talent["date_of_death"] = date_of_death
    talent["life_status"] = "DECEASED"
    talent["postmortem_rights_until"] = calc.postmortem_rights_expiry(date_of_death, profile)
    touch(talent)
    services.death_record_cascade(talent)
    return respond(public(talent))


@bp.post("/talents/<row_id>/estate-authorities")
def submit_estate_authority(row_id):
    authorize("RightsAdministrator")
    body = body_json()
    executor_name = want_str(body, "executor_name", 1, 200)
    court_document_ref = want_str(body, "court_document_ref", 1, 120)
    registration_number = want_str(body, "registration_number", 1, 120,
                                   required=False, default=None)
    talent = guards.need_talent(row_id)
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "talent_id": talent["id"],
        "executor_name": executor_name,
        "court_document_ref": court_document_ref,
        "registration_number": registration_number,
        "status": "SUBMITTED",
        "submitted_by_user_id": g.user_id,
        "verified_by_user_id": None,
        "verified_at": None,
        "_seq": db.next_seq(),
    }
    db.estate_authorities[row["id"]] = row
    return respond(public(row), 201)


@bp.get("/talents/<row_id>/estate-authorities")
def list_estate_authorities(row_id):
    authorize("RightsAdministrator", "ComplianceOfficer", "EstateRepresentative")
    talent = guards.need_talent(row_id)
    rows = [a for a in db.estate_authorities.values() if a["talent_id"] == talent["id"]]
    return collection(rows, {"status": "status"})


@bp.get("/estate-authorities/<row_id>")
def read_estate_authority(row_id):
    authorize("RightsAdministrator", "ComplianceOfficer", "EstateRepresentative")
    return respond(public(guards.need_estate_authority(row_id)))


@bp.post("/estate-authorities/<row_id>/verify")
def verify_estate_authority(row_id):
    authorize("RightsAdministrator")
    body_json()
    authority = guards.need_estate_authority(row_id)
    if g.user_id == authority["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the verifying user may not be the submitting user")
    if authority["status"] != "SUBMITTED":
        fail("ERR_INVALID_ESTATE_AUTHORITY_STATE",
             "only a SUBMITTED claim may be verified")
    authority["status"] = "VERIFIED"
    authority["verified_by_user_id"] = g.user_id
    authority["verified_at"] = now()
    touch(authority)
    talent = db.talents.get(authority["talent_id"])
    if talent is not None:
        talent["postmortem_registration_number"] = authority["registration_number"]
        touch(talent)
        services.release_estate_pending(talent)
    return respond(public(authority))
