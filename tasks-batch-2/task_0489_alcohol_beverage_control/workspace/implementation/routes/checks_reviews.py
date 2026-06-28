"""Background checks and zoning reviews: fetch + decide/resolve transitions."""
from flask import Blueprint

import errors
from auth import require_auth, ALL_READERS
from clock import clock
from db import db, touch
from helpers import body, out, get_or_404
import validate
from response import ok

bp = Blueprint("checks_reviews", __name__)

BG_DECISIONS = {"PASS", "FAIL"}
ZONING_DECISIONS = {"CLEAR", "VARIANCE", "BLOCK"}


# --- Background checks --------------------------------------------------------
@bp.route("/background-checks/<id>", methods=["GET"])
def get_background_check(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.background_checks, id)
    return ok(out(ent))


@bp.route("/background-checks/<id>/resolve", methods=["POST"])
def resolve_background_check(id):
    require_auth(["LicensingExaminer"])
    bc = get_or_404(db.background_checks, id)
    if bc["result"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Background check already resolved")
    data = body()
    decision = validate.require_enum(data, "decision", BG_DECISIONS)

    applicant = db.applicants.get(bc["applicant_id"])
    if decision == "PASS":
        # priority 6: a PASS against a felony_flag applicant is rejected
        if applicant is not None and applicant["felony_flag"]:
            raise errors.err(errors.ERR_APPLICANT_DISQUALIFIED, "Felony applicant cannot pass")
        bc["result"] = "PASSED"
        bc["status"] = "PASSED"
        bc["resolved_at"] = clock.now()
        touch(bc)
    else:  # FAIL
        bc["result"] = "FAILED"
        bc["status"] = "FAILED"
        bc["resolved_at"] = clock.now()
        touch(bc)
        # cross-entity cascade: disqualify the applicant
        if applicant is not None:
            applicant["disqualified"] = True
            touch(applicant)
    return ok(out(bc))


# --- Zoning reviews ----------------------------------------------------------
@bp.route("/zoning-reviews/<id>", methods=["GET"])
def get_zoning_review(id):
    require_auth(ALL_READERS)
    ent = get_or_404(db.zoning_reviews, id)
    return ok(out(ent))


@bp.route("/zoning-reviews/<id>/decide", methods=["POST"])
def decide_zoning_review(id):
    require_auth(["ZoningOfficer"])
    zr = get_or_404(db.zoning_reviews, id)
    if zr["result"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Zoning review already decided")
    data = body()
    decision = validate.require_enum(data, "decision", ZONING_DECISIONS)

    if decision == "CLEAR":
        if not zr["buffer_satisfied"]:
            raise errors.err(errors.ERR_INVALID_STATE, "Buffer not satisfied; cannot clear")
        zr["result"] = "CLEARED"
        zr["status"] = "CLEARED"
    elif decision == "VARIANCE":
        premise = db.premises.get(zr["premise_id"])
        if premise is not None and premise["zoning_district"] == "RESIDENTIAL":
            raise errors.err(errors.ERR_INVALID_STATE, "No variance into residential")
        zr["result"] = "VARIANCE_GRANTED"
        zr["status"] = "VARIANCE_GRANTED"
    else:  # BLOCK
        zr["result"] = "BLOCKED"
        zr["status"] = "BLOCKED"
    zr["resolved_at"] = clock.now()
    touch(zr)
    return ok(out(zr))
