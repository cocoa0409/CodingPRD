"""Evidence endpoints (PRD 3.5): registration, dual-control seal, exclusion."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    EVIDENCE_TYPES,
    bump,
    case_posture,
    evidence_view,
    get_case,
    get_evidence,
    paginate,
)
from util import as_checksum, as_str, body, pagination_args, req, req_dt, req_enum, req_str

bp = Blueprint("evidence", __name__)


@bp.post("/hotline/evidence-items")
def create_evidence():
    user_id, _ = auth(["Investigator"])
    data = body()
    case_id = req(data, "case_id")
    if not isinstance(case_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field case_id must be a string")
    case = get_case(case_id)
    if case["assigned_investigator_id"] != user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INVESTIGATOR",
            403,
            "Caller is not the case's assigned investigator",
        )
    evidence_type = req_enum(data, "evidence_type", EVIDENCE_TYPES)
    description = req_str(data, "description", min_len=10)
    checksum = as_checksum(req(data, "checksum"))
    captured_at = req_dt(data, "captured_at")
    if case["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_CASE_NOT_UNDER_INVESTIGATION",
            409,
            "Evidence registration requires case UNDER_INVESTIGATION",
        )

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "uploaded_by_id": user_id,
        "evidence_type": evidence_type,
        "description": description,
        "checksum": checksum,
        "captured_at": captured_at,
        "status": "PRESERVED",
        "sealed_by_id": None,
        "excluded_by_id": None,
        "exclusion_reason": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["evidence_items"][rec["id"]] = rec
    return ok(evidence_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/evidence-items")
def list_evidence(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [e for e in DB["evidence_items"].values() if e["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [e for e in records if e["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([evidence_view(e) for e in page], total, limit, offset)


@bp.post("/hotline/evidence-items/<eid>/seal")
def seal_evidence(eid):
    user_id, _ = auth(["IntakeSpecialist", "Investigator", "ComplianceOfficer"])
    evidence = get_evidence(eid)
    if evidence["status"] != "PRESERVED":
        raise ApiError(
            "ERR_EVIDENCE_NOT_PRESERVED", 409, "Seal requires evidence PRESERVED"
        )
    if user_id == evidence["uploaded_by_id"]:
        raise ApiError(
            "ERR_SOD_SELF_SEAL", 409, "The sealer must differ from the uploader"
        )
    evidence["status"] = "SEALED"
    evidence["sealed_by_id"] = user_id
    bump(evidence)
    return ok(evidence_view(evidence))


@bp.post("/hotline/evidence-items/<eid>/exclude")
def exclude_evidence(eid):
    user_id, _ = auth(["ComplianceOfficer"])
    evidence = get_evidence(eid)
    data = body()
    exclusion_reason = data.get("exclusion_reason")
    if exclusion_reason is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: exclusion_reason"
        )
    exclusion_reason = as_str(exclusion_reason, "exclusion_reason", min_len=20)
    if evidence["status"] not in ("PRESERVED", "SEALED"):
        raise ApiError(
            "ERR_EVIDENCE_NOT_EXCLUDABLE",
            409,
            "Exclude requires evidence PRESERVED or SEALED",
        )
    case = DB["cases"].get(evidence["case_id"])
    if case is not None and case_posture(case) != "NORMAL":
        raise ApiError(
            "ERR_LEGAL_HOLD_FREEZE", 409, "Case is FROZEN by an ACTIVE legal hold"
        )
    evidence["status"] = "EXCLUDED"
    evidence["excluded_by_id"] = user_id
    evidence["exclusion_reason"] = exclusion_reason
    bump(evidence)
    return ok(evidence_view(evidence))
