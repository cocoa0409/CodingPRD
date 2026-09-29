"""Coach certification and background checks (Cascade A lives here)."""
from flask import Blueprint

from core import (
    DB, SPORTS, auth, own, body, ok, fail, req_str, req_enum, req_date,
    opt_str, opt_date, new_record, touch, now_date, get_school, get_credential,
    ser_credential,
)
import domain

bp = Blueprint("credentials", __name__)

ROLE_TITLES = ["HEAD_COACH", "ASSISTANT_COACH"]


@bp.post("/athletics/staff-credentials")
def create_credential():
    p = auth(["SchoolAthleticDirector"])
    b = body()
    raw_school = b.get("school_id")
    if isinstance(raw_school, str):
        own(p, raw_school)
        get_school(raw_school)
    school_id = req_str(b, "school_id")
    coach_name = req_str(b, "coach_name")
    sport = req_enum(b, "sport", SPORTS)
    role_title = req_enum(b, "role_title", ROLE_TITLES)
    expires_on = req_date(b, "certification_expires_on")

    school = DB.schools[school_id]
    rec = new_record({
        "school_id": school_id,
        "coach_name": coach_name,
        "sport": sport,
        "role_title": role_title,
        "certification_expires_on": expires_on,
        "status": "BACKGROUND_PENDING",
        "background_check_completed_on": None,
        "background_check_reference": None,
    })
    DB.credentials[rec["id"]] = rec
    if role_title == "HEAD_COACH" and not domain.has_cleared_head_coach(school_id, sport):
        domain.gap_add(school, sport)
    return ok(ser_credential(rec), 201)


@bp.post("/athletics/staff-credentials/<cid>/background-check")
def background_check(cid):
    auth(["AssociationAdmin"])
    cred = get_credential(cid)
    b = body()
    result = req_enum(b, "result", ["CLEARED", "DENIED"])
    reference = opt_str(b, "background_check_reference", None)
    renewed = opt_date(b, "renewed_certification_expires_on", None)
    school = DB.schools.get(cred["school_id"])
    today = now_date()

    if cred["status"] == "BACKGROUND_PENDING":
        if result == "DENIED":
            cred["status"] = "DENIED"
            cred["background_check_completed_on"] = today
            if reference is not None:
                cred["background_check_reference"] = reference
            touch(cred)
            return ok(ser_credential(cred))
        effective = renewed if renewed is not None else cred["certification_expires_on"]
        if not (today < effective):
            fail("ERR_CREDENTIAL_ALREADY_LAPSED",
                 "the certification has already lapsed on the logical clock")
        if renewed is not None:
            cred["certification_expires_on"] = renewed
        cred["status"] = "CLEARED"
        cred["background_check_completed_on"] = today
        if reference is not None:
            cred["background_check_reference"] = reference
        touch(cred)
        if school is not None:
            domain.apply_credential_cleared(cred, school)
        return ok(ser_credential(cred))

    if cred["status"] == "EXPIRED" and result == "CLEARED":
        if renewed is None or not (renewed > today):
            fail("ERR_CREDENTIAL_ALREADY_LAPSED",
                 "renewed_certification_expires_on must be strictly after the logical clock date")
        cred["certification_expires_on"] = renewed
        cred["status"] = "CLEARED"
        cred["background_check_completed_on"] = today
        if reference is not None:
            cred["background_check_reference"] = reference
        touch(cred)
        if school is not None:
            domain.apply_credential_cleared(cred, school)
        return ok(ser_credential(cred))

    fail("ERR_INVALID_STATE",
         "a credential in %s admits no background-check adjudication of %s"
         % (cred["status"], result))


@bp.post("/athletics/staff-credentials/<cid>/revoke")
def revoke_credential(cid):
    auth(["AssociationAdmin"])
    cred = get_credential(cid)
    b = body()
    opt_str(b, "revocation_note", None)
    if cred["status"] != "CLEARED":
        fail("ERR_INVALID_STATE", "only a CLEARED credential may be revoked")
    school = DB.schools.get(cred["school_id"])
    # CASCADE-A LINK 1
    cred["status"] = "REVOKED"
    touch(cred)
    gap_opened = False
    if school is not None:
        gap_opened = domain.apply_credential_lost(cred, school)
    # LINKS 2-4 fire only because link 1 opened a gap
    if gap_opened and school is not None:
        domain.cascade_a(cred, school)
    return ok(ser_credential(cred))
