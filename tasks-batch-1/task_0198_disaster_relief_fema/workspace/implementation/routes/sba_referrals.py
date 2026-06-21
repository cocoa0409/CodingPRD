"""SbaReferral endpoints — PRD §3.7."""
from flask import Blueprint

from db import STORE, to_iso, now_dt
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int, opt_int
from services import calc, case_ops
from routes.dob_records import apply_dob_cascade

bp = Blueprint("sba_referrals", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/sba-referrals", methods=["POST"])
def create_referral():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    body = require_body()
    ihp_case_id = req_str(body, "ihp_case_id")
    with STORE.lock:
        case = lookup("ihp_cases", ihp_case_id)
        applicant = STORE.applicants[case["applicant_id"]]
        assessment = case_ops.case_assessment(case)

        verified_total_loss = (
            (assessment["verified_repair_cost_cents"] or 0)
            + (assessment["verified_personal_property_cents"] or 0)
        )
        eligible = (
            applicant["annual_income_cents"] <= calc.SBA_INCOME_CEILING_CENTS
            or verified_total_loss > calc.SBA_LOSS_THRESHOLD_CENTS
        )
        if not eligible:
            raise ApiError("ERR_SBA_NOT_ELIGIBLE")

        r = base_entity()
        r.update({
            "ihp_case_id": ihp_case_id,
            "referred_loss_cents": verified_total_loss,
            "sba_loan_amount_cents": None,
            "status": "REFERRED",
        })
        STORE.sba_referrals[r["id"]] = r
        return success(serialize(r), status=201)


@bp.route("/disaster-relief/sba-referrals", methods=["GET"])
def list_referrals():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.sba_referrals.values(),
            {"ihp_case_id": "ihp_case_id", "status": "status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/sba-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        r = lookup("sba_referrals", rid)
        return success(serialize(r))


@bp.route("/disaster-relief/sba-referrals/<rid>/record-outcome", methods=["POST"])
def record_outcome(rid):
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    body = require_body()
    with STORE.lock:
        r = lookup("sba_referrals", rid)
        if r["status"] != "REFERRED":
            raise ApiError("ERR_REFERRAL_NOT_OPEN")

        outcome = body.get("outcome")
        if outcome not in ("APPROVED", "DECLINED"):
            raise ApiError("ERR_INVALID_SBA_OUTCOME", "outcome must be APPROVED or DECLINED.")

        if outcome == "DECLINED":
            r["status"] = "SBA_DECLINED"
            touch(r)
            return success(serialize(r))

        # APPROVED requires sba_loan_amount_cents
        if "sba_loan_amount_cents" not in body or body["sba_loan_amount_cents"] is None:
            raise ApiError("ERR_INVALID_SBA_OUTCOME", "APPROVED requires sba_loan_amount_cents.")
        sba_loan_amount_cents = req_int(body, "sba_loan_amount_cents", minimum=0)

        r["sba_loan_amount_cents"] = sba_loan_amount_cents
        r["status"] = "SBA_APPROVED"
        touch(r)

        case = STORE.ihp_cases[r["ihp_case_id"]]
        applicant = STORE.applicants[case["applicant_id"]]

        # Hop 1: create SBA_LOAN DobRecord
        dob = base_entity()
        dob.update({
            "applicant_id": applicant["id"],
            "source_type": "SBA_LOAN",
            "amount_cents": sba_loan_amount_cents,
            "received_at": to_iso(now_dt()),
            "dob_status": "RECORDED",
        })
        STORE.dob_records[dob["id"]] = dob

        # Hops 2 & 3: total_dob recompute -> dob_offset/net recompute -> LATE_DOB recoupment
        apply_dob_cascade(applicant)
        return success(serialize(r))
