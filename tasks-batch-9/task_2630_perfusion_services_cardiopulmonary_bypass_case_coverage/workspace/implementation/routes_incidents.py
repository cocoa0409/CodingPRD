"""Quality review of an incident -- PRD 3.9."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("incidents", __name__)

READ_ROLES = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST)
FILE_ROLES = (ROLE_PERFUSIONIST, ROLE_CHIEF)


@bp.post("/incident-reports")
@endpoint(FILE_ROLES)
def file_report(actor):
    body = V.payload()
    V.require(body, "case_id", "involved_perfusionist_id", "severity", "category", "narrative")
    case_id = V.vstr(body, "case_id", required=True)
    involved_id = V.vstr(body, "involved_perfusionist_id", required=True)
    severity = V.venum(body, "severity", C.INCIDENT_SEVERITIES, required=True)
    category = V.venum(body, "category", C.INCIDENT_CATEGORIES, required=True)
    narrative = V.vstr(body, "narrative", max_len=2000, required=True)

    # Rung 12 -- the involved perfusionist resolves before the case (rung 16).
    svc.get_perfusionist(involved_id)
    case = svc.get_case(case_id)

    row = {
        "case_id": case["id"],
        "involved_perfusionist_id": involved_id,
        "filed_by_perfusionist_id": actor.user_id,
        "closed_by_perfusionist_id": None,
        "severity": severity,
        "category": category,
        "narrative": narrative,
        "status": "DRAFT",
        "return_count": 0,
        "reviewed_readiness_score": None,
        "finding": "NONE",
        "corrective_action_required": False,
    }
    stamp_new(row)
    insert("incident_reports", row)
    return ok(serialize.incident(row), 201)


@bp.get("/incident-reports/<iid>")
@endpoint(READ_ROLES)
def read_report(actor, iid):
    return ok(serialize.incident(svc.get_incident(iid)))


@bp.get("/incident-reports")
@endpoint(READ_ROLES)
def list_reports(actor):
    limit, offset = V.pagination()
    rows = ordered("incident_reports")
    for key in ("case_id", "involved_perfusionist_id", "filed_by_perfusionist_id",
                "closed_by_perfusionist_id", "status", "severity", "finding"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.incident(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/incident-reports/<iid>/submit")
@endpoint(FILE_ROLES)
def submit_report(actor, iid):
    report = svc.get_incident(iid)
    if actor.user_id != report["filed_by_perfusionist_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if report["status"] not in ("DRAFT", "RETURNED_FOR_INFO"):
        raise ApiError("ERR_INCIDENT_STATE_INVALID")
    case = db.bypass_cases.get(report["case_id"])
    if case is None or case["bypass_status"] not in ("OFF_BYPASS", "CLOSED"):
        raise ApiError("ERR_INCIDENT_CASE_NOT_COMPLETE")

    report["status"] = "SUBMITTED"
    touch(report)
    return ok(serialize.incident(report))


@bp.post("/incident-reports/<iid>/review")
@endpoint([ROLE_CHIEF])
def review_report(actor, iid):
    body = V.payload()
    V.require(body, "decision")
    decision = V.venum(body, "decision", ("ACCEPT_FOR_REVIEW", "RETURN_FOR_INFO"), required=True)
    V.vstr(body, "review_note", max_len=1000, allow_empty=True)

    report = svc.get_incident(iid)
    if actor.user_id in (report["involved_perfusionist_id"], report["filed_by_perfusionist_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INCIDENT_STATE_INVALID")
    if decision == "RETURN_FOR_INFO" and report["return_count"] >= C.MAX_INCIDENT_RETURNS:
        raise ApiError("ERR_INCIDENT_RETURN_LIMIT")

    if decision == "ACCEPT_FOR_REVIEW":
        report["status"] = "UNDER_REVIEW"
        involved = db.perfusionists.get(report["involved_perfusionist_id"])
        if involved is not None:
            report["reviewed_readiness_score"] = svc.set_readiness(
                involved, "AUDIT", record_variant=True)
        else:
            report["reviewed_readiness_score"] = D("0.000")
    else:
        report["status"] = "RETURNED_FOR_INFO"
        report["return_count"] += 1
    touch(report)
    return ok(serialize.incident(report))


@bp.post("/incident-reports/<iid>/close")
@endpoint([ROLE_CHIEF])
def close_report(actor, iid):
    body = V.payload()
    V.require(body, "finding")
    finding = V.venum(body, "finding", ("ISOLATED", "SYSTEMIC"), required=True)
    credit = V.vbool(body, "credit_case_fee", default=False)
    V.vstr(body, "closing_note", max_len=1000, allow_empty=True)

    report = svc.get_incident(iid)
    if actor.user_id in (report["involved_perfusionist_id"], report["filed_by_perfusionist_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if report["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INCIDENT_STATE_INVALID")

    if finding == "ISOLATED":
        report["status"] = "CLOSED_NO_ACTION"
        report["finding"] = "ISOLATED"
        report["closed_by_perfusionist_id"] = actor.user_id
        touch(report)
        return ok(serialize.incident(report))

    # Systemic gate -- the two grounds are independent (PRD 3.9).
    frozen = report["reviewed_readiness_score"]
    supported = report["severity"] in ("MAJOR", "SENTINEL")
    if not supported and frozen is not None and D(frozen) < C.READINESS_AUDIT_FLOOR:
        supported = True
    if not supported:
        raise ApiError("ERR_SYSTEMIC_FINDING_UNSUPPORTED")

    # Link 1 -- the report itself.
    report["status"] = "CLOSED_WITH_ACTION"
    report["finding"] = "SYSTEMIC"
    report["corrective_action_required"] = True
    report["closed_by_perfusionist_id"] = actor.user_id
    touch(report)

    # Links 2 through 4.
    svc.systemic_cascade(report)

    # Independently: the fee credit, only for an already-invoiced case.
    case = db.bypass_cases.get(report["case_id"])
    if credit and case is not None and case["billing_status"] == "INVOICED":
        contract = db.hospital_contracts.get(case["contract_id"])
        amount = int(case.get("accrued_fee_cents") or 0)
        case["billing_status"] = "CREDITED"
        case["accrued_fee_cents"] = 0
        touch(case)
        if contract is not None:
            svc.post_contract_accrual(contract, fee_delta=-amount, count_delta=-1)

    return ok(serialize.incident(report))
