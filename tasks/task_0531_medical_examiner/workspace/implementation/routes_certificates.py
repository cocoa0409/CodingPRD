"""Death certificate drafting, signing, amending, voiding."""
from flask import Blueprint, request

import errors
import lookup
import validate
from db import db
from middleware import require, json_body, paginate
from records import make_record, touch, public
from response import object_response, array_response
import services

bp = Blueprint("certificates", __name__)

MANNERS = {"NATURAL", "ACCIDENT", "HOMICIDE", "UNDETERMINED"}


def _manner_consistent(case_type, manner):
    """UNDETERMINED always allowed. NATURAL case may not certify HOMICIDE, and
    HOMICIDE case may not certify NATURAL. Otherwise consistent."""
    if manner == "UNDETERMINED":
        return True
    if case_type == "HOMICIDE" and manner == "NATURAL":
        return False
    if case_type == "NATURAL" and manner == "HOMICIDE":
        return False
    return True


@bp.post("/cases/<case_id>/death-certificate")
def draft_certificate(case_id):
    require({"MedicalExaminer"})
    case = lookup.case(case_id)
    body = json_body()
    cause_of_death = validate.req_str(body, "cause_of_death")
    manner_of_death = validate.req_enum(body, "manner_of_death", MANNERS)

    if case["status"] == "DECLINED":
        raise errors.err(errors.ERR_CASE_DECLINED, "Case is declined")

    rec = make_record({
        "case_id": case_id,
        "certifying_me_user_id": None,
        "cause_of_death": cause_of_death,
        "manner_of_death": manner_of_death,
        "cert_status": "DRAFT",
        "amendment_count": 0,
        "signed_at": None,
    })
    db.death_certificates[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/cases/<case_id>/death-certificate")
def list_case_certificate(case_id):
    require({"Admin", "Investigator", "MedicalExaminer"})
    lookup.case(case_id)
    rows = [c for c in db.death_certificates.values() if c["case_id"] == case_id]
    page, limit, offset, total = paginate(rows)
    return array_response([public(c) for c in page], limit, offset, total)


@bp.get("/death-certificates/<id_>")
def get_certificate(id_):
    require({"Admin", "Investigator", "MedicalExaminer"})
    rec = lookup.death_certificate(id_)
    return object_response(public(rec), 200)


@bp.get("/death-certificates")
def list_certificates():
    require({"Admin", "Investigator", "MedicalExaminer"})
    rows = list(db.death_certificates.values())
    me = request.args.get("certifying_me_user_id")
    if me is not None:
        rows = [c for c in rows if c.get("certifying_me_user_id") == me]
    page, limit, offset, total = paginate(rows)
    return array_response([public(c) for c in page], limit, offset, total)


@bp.post("/death-certificates/<id_>/sign")
def sign_certificate(id_):
    actor = require({"MedicalExaminer"})
    rec = lookup.death_certificate(id_)
    body = json_body()
    if "expected_case_version" not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing expected_case_version")
    expected_case_version = validate.req_int(body, "expected_case_version")

    case = db.cases.get(rec["case_id"])
    # (case always exists since certificate is created under a case)

    # state legality (priority 21)
    if rec["cert_status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Sign only allowed from DRAFT")

    # segregation of duties (priority 12): acting ME != case autopsy pathologist
    exam = services.case_autopsy_exam(rec["case_id"])
    if exam is not None and actor.user_id == exam["pathologist_user_id"]:
        raise errors.err(errors.ERR_SEGREGATION_VIOLATION,
                         "Signing ME must not be the case's autopsy pathologist")

    # manner consistency (priority 23)
    if not _manner_consistent(case["case_type"], rec["manner_of_death"]):
        raise errors.err(errors.ERR_MANNER_INCONSISTENT, "Manner inconsistent with case type")

    # required autopsy complete (priority 24)
    if case["autopsy_required"]:
        if exam is None or exam["exam_status"] != "COMPLETED":
            raise errors.err(errors.ERR_AUTOPSY_INCOMPLETE, "Required autopsy not completed")

    # OCC on case (priority 50)
    if expected_case_version != case["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale case version")

    rec["cert_status"] = "SIGNED"
    rec["certifying_me_user_id"] = actor.user_id
    rec["signed_at"] = db.clock.now_iso()
    touch(rec)

    # cascade Case INVESTIGATING -> CERTIFIED
    case["status"] = "CERTIFIED"
    touch(case)

    # cascade clear release_blocked on the case's body
    for b in services.case_bodies(rec["case_id"]):
        if b["release_blocked"]:
            b["release_blocked"] = False
            touch(b)

    return object_response(public(rec), 200)


@bp.post("/death-certificates/<id_>/amend")
def amend_certificate(id_):
    require({"MedicalExaminer"})
    rec = lookup.death_certificate(id_)
    body = json_body()
    cause_of_death = validate.req_str(body, "cause_of_death")
    manner_of_death = validate.req_enum(body, "manner_of_death", MANNERS)

    if rec["cert_status"] not in ("SIGNED", "AMENDED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Amend only allowed from SIGNED or AMENDED")

    rec["cause_of_death"] = cause_of_death
    rec["manner_of_death"] = manner_of_death
    rec["amendment_count"] += 1
    rec["cert_status"] = "AMENDED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.post("/death-certificates/<id_>/void")
def void_certificate(id_):
    require({"MedicalExaminer"})
    rec = lookup.death_certificate(id_)
    if rec["cert_status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Void only allowed from DRAFT")
    rec["cert_status"] = "VOID"
    touch(rec)
    return object_response(public(rec), 200)
