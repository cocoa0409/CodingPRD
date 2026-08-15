"""Determination endpoints (PRD 3.6): draft (OCC-guarded, superseding), submit
with completeness gates, and officer review with the three-way outcome."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    FINDINGS,
    REVIEW_DECISIONS,
    add_event,
    bump,
    case_posture,
    create_closure_notice,
    determination_view,
    get_case,
    get_determination,
    paginate,
)
from util import as_occ_version, as_str, body, opt_str, pagination_args, req, req_enum, req_str

bp = Blueprint("determinations", __name__)


@bp.post("/hotline/cases/<cid>/determinations")
def create_determination(cid):
    user_id, role = auth(["Investigator"])
    case = get_case(cid)
    # Binding (priority 4): the caller must be the case's assigned investigator.
    if case["assigned_investigator_id"] != user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INVESTIGATOR",
            403,
            "Caller is not the case's assigned investigator",
        )
    data = body()
    finding = req_enum(data, "finding", FINDINGS)
    rationale = req_str(data, "rationale", min_len=50)
    if "expected_case_version" not in data or data["expected_case_version"] is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: expected_case_version"
        )
    expected = as_occ_version(data["expected_case_version"], "expected_case_version")

    # OCC (priority 7)
    if expected != case["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_case_version does not match the case's current version",
        )
    # State (priority 8)
    if case["status"] != "UNDER_INVESTIGATION":
        raise ApiError(
            "ERR_CASE_NOT_UNDER_INVESTIGATION",
            409,
            "Determination drafting requires case UNDER_INVESTIGATION",
        )

    # A new draft supersedes any existing DRAFT determination of the case.
    for prior in DB["determinations"].values():
        if prior["case_id"] == case["id"] and prior["status"] == "DRAFT":
            prior["status"] = "SUPERSEDED"
            bump(prior)

    rec = {
        "id": new_id(),
        "case_id": case["id"],
        "finding": finding,
        "rationale": rationale,
        "decided_by_id": user_id,
        "reviewed_by_id": None,
        "status": "DRAFT",
        "review_notes": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["determinations"][rec["id"]] = rec
    bump(case)
    add_event(case["id"], "DETERMINATION_DRAFTED", None, "DRAFT", role, user_id)
    return ok(determination_view(rec), status=201)


@bp.get("/hotline/cases/<cid>/determinations")
def list_determinations(cid):
    auth(STAFF_READ_ROLES)
    get_case(cid)
    limit, offset = pagination_args()
    records = [d for d in DB["determinations"].values() if d["case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [d for d in records if d["status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([determination_view(d) for d in page], total, limit, offset)


@bp.get("/hotline/determinations/<did>")
def get_one_determination(did):
    auth(STAFF_READ_ROLES)
    return ok(determination_view(get_determination(did)))


@bp.post("/hotline/determinations/<did>/submit")
def submit_determination(did):
    user_id, role = auth(["Investigator"])
    determination = get_determination(did)
    # Binding (priority 4): only the deciding investigator may submit.
    if determination["decided_by_id"] != user_id:
        raise ApiError(
            "ERR_NOT_ASSIGNED_INVESTIGATOR",
            403,
            "Caller is not the determination's deciding investigator",
        )
    if determination["status"] != "DRAFT":
        raise ApiError(
            "ERR_DETERMINATION_NOT_DRAFT", 409, "Submit requires determination DRAFT"
        )
    case = DB["cases"].get(determination["case_id"])
    # Completeness gates (priority 14): >= 1 CONDUCTED interview, then zero
    # PRESERVED evidence.
    conducted = any(
        i["case_id"] == determination["case_id"] and i["status"] == "CONDUCTED"
        for i in DB["interviews"].values()
    )
    if not conducted:
        raise ApiError(
            "ERR_NO_CONDUCTED_INTERVIEW",
            409,
            "Submit requires at least one CONDUCTED interview",
        )
    unsealed = any(
        e["case_id"] == determination["case_id"] and e["status"] == "PRESERVED"
        for e in DB["evidence_items"].values()
    )
    if unsealed:
        raise ApiError(
            "ERR_UNSEALED_EVIDENCE",
            409,
            "Submit requires zero PRESERVED evidence items",
        )

    determination["status"] = "SUBMITTED"
    bump(determination)
    if case is not None:
        from_status = case["status"]
        case["status"] = "DETERMINATION_REVIEW"
        bump(case)
        add_event(
            case["id"],
            "DETERMINATION_SUBMITTED",
            from_status,
            "DETERMINATION_REVIEW",
            role,
            user_id,
        )
    return ok(determination_view(determination))


@bp.post("/hotline/determinations/<did>/review")
def review_determination(did):
    user_id, role = auth(["ComplianceOfficer"])
    determination = get_determination(did)
    data = body()
    decision = req_enum(data, "decision", REVIEW_DECISIONS)
    review_notes = req_str(data, "review_notes", min_len=10)
    notice_summary = opt_str(data, "notice_summary")
    # Entering CLOSURE_READY (APPROVE on a non-SUBSTANTIATED finding) requires
    # the notice_summary the system composes the closure notice from.
    if (
        decision == "APPROVE"
        and determination["finding"] != "SUBSTANTIATED"
        and not notice_summary
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "notice_summary is required when approval moves the case to CLOSURE_READY",
        )

    if determination["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_DETERMINATION_NOT_SUBMITTED", 409, "Review requires determination SUBMITTED"
        )
    case = DB["cases"].get(determination["case_id"])

    # Freeze gate (priority 9): CLOSURE_READY entry is hold-gated.
    if (
        decision == "APPROVE"
        and determination["finding"] != "SUBSTANTIATED"
        and case is not None
        and case_posture(case) != "NORMAL"
    ):
        raise ApiError(
            "ERR_LEGAL_HOLD_FREEZE", 409, "Case is FROZEN by an ACTIVE legal hold"
        )

    # SoD (priority 10): reviewer must differ from the decider.
    if user_id == determination["decided_by_id"]:
        raise ApiError(
            "ERR_SOD_SELF_REVIEW",
            409,
            "The reviewing officer must differ from the deciding investigator",
        )

    determination["reviewed_by_id"] = user_id
    determination["review_notes"] = review_notes

    if decision == "RETURN":
        determination["status"] = "RETURNED"
        bump(determination)
        if case is not None:
            from_status = case["status"]
            case["status"] = "UNDER_INVESTIGATION"
            bump(case)
            add_event(
                case["id"],
                "DETERMINATION_RETURNED",
                from_status,
                "UNDER_INVESTIGATION",
                role,
                user_id,
            )
        return ok(determination_view(determination))

    # APPROVE
    determination["status"] = "APPROVED"
    bump(determination)
    if case is not None:
        case["determination_finding"] = determination["finding"]
        if notice_summary:
            case["_pending_notice_summary"] = notice_summary
        from_status = case["status"]
        if determination["finding"] == "SUBSTANTIATED":
            case["status"] = "REMEDIATION"
            bump(case)
            add_event(
                case["id"], "DETERMINATION_APPROVED", from_status, "REMEDIATION", role, user_id
            )
        else:
            case["status"] = "CLOSURE_READY"
            case["closure_ready_at"] = now_dt()
            bump(case)
            create_closure_notice(case, notice_summary)
            add_event(
                case["id"],
                "DETERMINATION_APPROVED",
                from_status,
                "CLOSURE_READY",
                role,
                user_id,
            )
            add_event(
                case["id"], "CLOSURE_READY", from_status, "CLOSURE_READY", role, user_id
            )
    return ok(determination_view(determination))
