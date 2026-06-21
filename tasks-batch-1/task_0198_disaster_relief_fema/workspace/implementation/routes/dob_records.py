"""DobRecord endpoints — PRD §3.5."""
from flask import Blueprint

from db import STORE, to_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int, req_datetime, req_enum
from services import calc, case_ops

bp = Blueprint("dob_records", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]
SOURCE_TYPES = {"INSURANCE", "SBA_LOAN", "CHARITY", "OTHER_FEDERAL"}


def apply_dob_cascade(applicant):
    """Recompute total_dob, then cascade onto an AWARD_APPROVED/DISBURSING case
    (at-recoupment offset/net recompute + LATE_DOB recoupment). PRD §3.5."""
    calc.recompute_total_dob(applicant)
    touch(applicant)
    for case in STORE.ihp_cases.values():
        if case["applicant_id"] != applicant["id"]:
            continue
        if case["status"] not in ("AWARD_APPROVED", "DISBURSING"):
            continue
        assessment = case_ops.case_assessment(case)
        declaration = case_ops.case_declaration(case)
        case_ops.recompute_dob_for_case(case, applicant, assessment, declaration)
        touch(case)
        if case["disbursed_total_cents"] > case["net_eligible_cents"]:
            case_ops.maybe_establish_recoupment(case, "LATE_DOB")


@bp.route("/disaster-relief/dob-records", methods=["POST"])
def create_dob():
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin", "Caseworker"])
    body = require_body()
    applicant_id = req_str(body, "applicant_id")
    with STORE.lock:
        applicant = lookup("applicants", applicant_id)
        source_type = req_enum(body, "source_type", SOURCE_TYPES)
        amount_cents = req_int(body, "amount_cents", minimum=0)
        received_at = req_datetime(body, "received_at")

        d = base_entity()
        d.update({
            "applicant_id": applicant_id,
            "source_type": source_type,
            "amount_cents": amount_cents,
            "received_at": to_iso(received_at),
            "dob_status": "RECORDED",
        })
        STORE.dob_records[d["id"]] = d

        apply_dob_cascade(applicant)
        return success(serialize(d), status=201)


@bp.route("/disaster-relief/dob-records", methods=["GET"])
def list_dob():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.dob_records.values(),
            {"applicant_id": "applicant_id", "dob_status": "dob_status", "source_type": "source_type"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/dob-records/<did>", methods=["GET"])
def get_dob(did):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        d = lookup("dob_records", did)
        return success(serialize(d))


@bp.route("/disaster-relief/dob-records/<did>/reverse", methods=["POST"])
def reverse_dob(did):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    with STORE.lock:
        d = lookup("dob_records", did)
        if d["dob_status"] != "RECORDED":
            raise ApiError("ERR_DOB_NOT_RECORDED")
        d["dob_status"] = "REVERSED"
        touch(d)
        applicant = STORE.applicants.get(d["applicant_id"])
        if applicant is not None:
            # Recompute total_dob and recompute case dob_offset/net (compensating).
            calc.recompute_total_dob(applicant)
            touch(applicant)
            for case in STORE.ihp_cases.values():
                if case["applicant_id"] != applicant["id"]:
                    continue
                if case["status"] not in ("AWARD_APPROVED", "DISBURSING"):
                    continue
                assessment = case_ops.case_assessment(case)
                declaration = case_ops.case_declaration(case)
                case_ops.recompute_dob_for_case(case, applicant, assessment, declaration)
                touch(case)
        return success(serialize(d))
