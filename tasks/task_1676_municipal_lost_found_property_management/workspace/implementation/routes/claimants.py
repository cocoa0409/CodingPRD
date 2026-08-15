"""Claimant registration and ID verification (PRD 3.4)."""
from flask import Blueprint

from errors import raise_error, ERR_FORBIDDEN
from middleware import authorized
from response import success_object
from services import core
from validate import get_body, req_str, opt_str, require_path

bp = Blueprint("claimants", __name__)

CLAIMANT_READERS = {"ClaimsExaminer", "ReleaseOfficer", "ProgramAdmin", "Claimant"}


@bp.post("/claimants")
def register_claimant():
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = opt_str(body, "phone", None)
    authorized({"PublicUser"})
    rec = core.new_record("claimants", {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "id_verified": False,
    })
    return success_object(rec, 201)


@bp.get("/claimants/<claimant_id>")
def get_claimant(claimant_id):
    caller = authorized(CLAIMANT_READERS)
    rec = require_path("claimants", claimant_id)
    if caller.role == "Claimant" and caller.user_id != claimant_id:
        raise_error(ERR_FORBIDDEN, "Claimant may only read its own record")
    return success_object(rec)


@bp.post("/claimants/<claimant_id>/verify-id")
def verify_id(claimant_id):
    authorized({"ClaimsExaminer"})
    rec = require_path("claimants", claimant_id)
    rec["id_verified"] = True
    core.touch(rec)
    # Recompute proof_score of that claimant's open claims (3.4)
    core.recompute_claim_scores_for_claimant(rec)
    return success_object(rec)
