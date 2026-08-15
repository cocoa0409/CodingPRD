"""ExaminationCase and ExaminationFinding endpoints."""
from flask import Blueprint, request

from db import stamp_new, store, touch
from errors import (
    ERR_CASE_NOT_FOUND,
    ERR_CASE_SCOPE_OVERLAP,
    ERR_DUPLICATE_CASE_NUMBER,
    ERR_EXAMINATION_HAS_OPEN_FINDINGS,
    ERR_FINDING_NOT_FOUND,
    ERR_FINDING_TARGET_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ApiError,
    bad_request,
)
from middleware import authenticate, body, f_date, f_enum, f_str, sorted_page
from response import ok, ok_list
from serializers import serialize_case, serialize_finding
from services.audit import main_event

bp = Blueprint("examinations", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]
REGULATORS = ("FINCEN", "OCC", "FDIC", "STATE")
SEVERITIES = ("OBSERVATION", "DEFICIENCY", "VIOLATION")
TARGET_TYPES = (
    "CTR",
    "EXEMPTION_DESIGNATION",
    "STRUCTURING_ALERT",
    "MONETARY_INSTRUMENT_SALE",
    "CASH_TRANSACTION",
)
LIVE_CASE_STATUSES = ("OPEN", "FIELDWORK", "FINDINGS_ISSUED")


def get_case_or_404(case_id):
    c = store.cases.get(case_id)
    if c is None:
        raise ApiError(ERR_CASE_NOT_FOUND, "Examination case not found", 404)
    return c


def get_finding_or_404(finding_id):
    f = store.findings.get(finding_id)
    if f is None:
        raise ApiError(ERR_FINDING_NOT_FOUND, "Examination finding not found", 404)
    return f


def resolve_target(target_type, target_id):
    pools = {
        "CTR": store.ctrs,
        "EXEMPTION_DESIGNATION": store.exemptions,
        "STRUCTURING_ALERT": store.alerts,
        "MONETARY_INSTRUMENT_SALE": store.instrument_sales,
        "CASH_TRANSACTION": store.cash_transactions,
    }
    pool = pools.get(target_type)
    if pool is None:
        return None
    return pool.get(target_id)


@bp.post("/examination-cases")
def create_case():
    authenticate(["Examiner"])
    b = body()
    regulator = f_enum(b, "regulator", REGULATORS)
    case_number = f_str(b, "case_number")
    start_raw, start = f_date(b, "scope_start_date")
    end_raw, end = f_date(b, "scope_end_date")
    # Half-open scope: start strictly earlier than end (shape-level check).
    if start >= end:
        raise bad_request("scope_start_date must be strictly earlier than scope_end_date")
    for existing in store.cases.values():
        if existing["case_number"] == case_number:
            raise ApiError(
                ERR_DUPLICATE_CASE_NUMBER,
                "case_number already exists",
                422,
            )
    for existing in store.cases.values():
        if existing["regulator"] != regulator or existing["status"] not in LIVE_CASE_STATUSES:
            continue
        ex_start = store_date(existing["scope_start_date"])
        ex_end = store_date(existing["scope_end_date"])
        # Half-open overlap; touching boundaries are allowed.
        if start < ex_end and ex_start < end:
            raise ApiError(
                ERR_CASE_SCOPE_OVERLAP,
                "Scope overlaps another live case for this regulator",
                422,
            )
    case = {
        "regulator": regulator,
        "case_number": case_number,
        "scope_start_date": start_raw,
        "scope_end_date": end_raw,
        "status": "OPEN",
    }
    stamp_new(case)
    store.cases[case["id"]] = case
    main_event(
        "POST /examination-cases", "ExaminationCase", case["id"], None,
        serialize_case(case),
    )
    return ok(serialize_case(case), status=201)


def store_date(raw):
    from db import parse_date_strict

    return parse_date_strict(raw)


@bp.get("/examination-cases")
def list_cases():
    authenticate(ALL_ROLES)
    items = list(store.cases.values())
    for param in ("regulator", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_case(c) for c in page], limit, offset, total)


@bp.get("/examination-cases/<case_id>")
def get_case(case_id):
    authenticate(ALL_ROLES)
    return ok(serialize_case(get_case_or_404(case_id)))


def _case_transition(case_id, from_status, to_status, action):
    authenticate(["Examiner"])
    case = get_case_or_404(case_id)
    if case["status"] != from_status:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Case is not in %s status" % from_status,
            409,
        )
    before = serialize_case(case)
    case["status"] = to_status
    touch(case)
    main_event(action, "ExaminationCase", case["id"], before, serialize_case(case))
    return ok(serialize_case(case))


@bp.post("/examination-cases/<case_id>/begin-fieldwork")
def begin_fieldwork(case_id):
    return _case_transition(
        case_id, "OPEN", "FIELDWORK", "POST /examination-cases/{id}/begin-fieldwork"
    )


@bp.post("/examination-cases/<case_id>/issue-findings")
def issue_findings(case_id):
    return _case_transition(
        case_id, "FIELDWORK", "FINDINGS_ISSUED",
        "POST /examination-cases/{id}/issue-findings",
    )


@bp.post("/examination-cases/<case_id>/reopen-fieldwork")
def reopen_fieldwork(case_id):
    return _case_transition(
        case_id, "FINDINGS_ISSUED", "FIELDWORK",
        "POST /examination-cases/{id}/reopen-fieldwork",
    )


@bp.post("/examination-cases/<case_id>/close")
def close_case(case_id):
    authenticate(["Examiner"])
    case = get_case_or_404(case_id)
    if case["status"] != "FINDINGS_ISSUED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Case is not in FINDINGS_ISSUED status", 409
        )
    for f in store.findings.values():
        if f["case_id"] == case_id and f["status"] != "VERIFIED":
            raise ApiError(
                ERR_EXAMINATION_HAS_OPEN_FINDINGS,
                "All findings must be VERIFIED before the case can be closed",
                409,
            )
    before = serialize_case(case)
    case["status"] = "CLOSED"
    touch(case)
    main_event(
        "POST /examination-cases/{id}/close", "ExaminationCase", case["id"],
        before, serialize_case(case),
    )
    return ok(serialize_case(case))


@bp.post("/examination-cases/<case_id>/findings")
def create_finding(case_id):
    authenticate(["Examiner"])
    b = body()
    severity = f_enum(b, "severity", SEVERITIES)
    target_type = f_enum(b, "target_type", TARGET_TYPES)
    target_id = f_str(b, "target_id")
    description = f_str(b, "description")
    case = get_case_or_404(case_id)
    if resolve_target(target_type, target_id) is None:
        raise ApiError(
            ERR_FINDING_TARGET_NOT_FOUND,
            "target_id does not resolve for the given target_type",
            404,
        )
    if case["status"] not in ("FIELDWORK", "FINDINGS_ISSUED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Findings may be recorded only while the case is in FIELDWORK or FINDINGS_ISSUED",
            409,
        )
    finding = {
        "case_id": case_id,
        "severity": severity,
        "target_type": target_type,
        "target_id": target_id,
        "description": description,
        "status": "OPEN",
        "remediation_note": None,
    }
    stamp_new(finding)
    store.findings[finding["id"]] = finding
    main_event(
        "POST /examination-cases/{case_id}/findings", "ExaminationFinding",
        finding["id"], None, serialize_finding(finding),
    )
    return ok(serialize_finding(finding), status=201)


@bp.get("/examination-findings")
def list_findings():
    authenticate(ALL_ROLES)
    items = list(store.findings.values())
    for param in ("case_id", "status", "severity"):
        value = request.args.get(param)
        if value is not None:
            items = [f for f in items if f[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_finding(f) for f in page], limit, offset, total)


@bp.get("/examination-findings/<finding_id>")
def get_finding(finding_id):
    authenticate(ALL_ROLES)
    return ok(serialize_finding(get_finding_or_404(finding_id)))


@bp.post("/examination-findings/<finding_id>/remediate")
def remediate_finding(finding_id):
    authenticate(["BSAOfficer"])
    b = body()
    remediation_note = f_str(b, "remediation_note")
    finding = get_finding_or_404(finding_id)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Finding is not OPEN", 409)
    case = store.cases.get(finding["case_id"])
    if case is None or case["status"] not in ("FIELDWORK", "FINDINGS_ISSUED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Parent case is not in FIELDWORK or FINDINGS_ISSUED",
            409,
        )
    before = serialize_finding(finding)
    finding["status"] = "REMEDIATED"
    finding["remediation_note"] = remediation_note
    touch(finding)
    main_event(
        "POST /examination-findings/{id}/remediate", "ExaminationFinding",
        finding["id"], before, serialize_finding(finding),
    )
    return ok(serialize_finding(finding))


@bp.post("/examination-findings/<finding_id>/verify")
def verify_finding(finding_id):
    authenticate(["Examiner"])
    finding = get_finding_or_404(finding_id)
    if finding["status"] != "REMEDIATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Finding is not REMEDIATED", 409)
    before = serialize_finding(finding)
    finding["status"] = "VERIFIED"
    touch(finding)
    main_event(
        "POST /examination-findings/{id}/verify", "ExaminationFinding",
        finding["id"], before, serialize_finding(finding),
    )
    return ok(serialize_finding(finding))


@bp.post("/examination-findings/<finding_id>/reject-remediation")
def reject_remediation(finding_id):
    authenticate(["Examiner"])
    b = body()
    note = f_str(b, "note")
    finding = get_finding_or_404(finding_id)
    if finding["status"] != "REMEDIATED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Finding is not REMEDIATED", 409)
    before = serialize_finding(finding)
    finding["status"] = "OPEN"
    finding["remediation_note"] = note
    touch(finding)
    main_event(
        "POST /examination-findings/{id}/reject-remediation", "ExaminationFinding",
        finding["id"], before, serialize_finding(finding),
    )
    return ok(serialize_finding(finding))
