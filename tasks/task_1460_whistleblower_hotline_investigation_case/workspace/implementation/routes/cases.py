"""Case intake and lifecycle endpoints (PRD 3.2, 3.3)."""
from flask import Blueprint, request

from db import DB, new_id, next_seq, now_dt
from errors import ApiError
from middleware import STAFF_READ_ROLES, auth
from response import ok, ok_list
from services import (
    CASE_TERMINAL_STATES,
    CATEGORIES,
    CHANNELS,
    EXPOSURE_BANDS,
    REGIONS,
    SENIORITIES,
    SLA_DAYS,
    TRIAGE_DECISIONS,
    VULNERABILITIES,
    add_event,
    bump,
    compute_severity,
    get_case,
    paginate,
    case_view,
)
from util import as_bool, as_str_list, body, opt_str, pagination_args, req, req_enum, req_str

bp = Blueprint("cases", __name__)


@bp.post("/hotline/cases")
def create_case():
    user_id, _ = auth(["HotlineReporter"])
    data = body()
    channel = req_enum(data, "channel", CHANNELS)
    category = req_enum(data, "category", CATEGORIES)
    description = req_str(data, "description", min_len=20)
    region = req_enum(data, "region", REGIONS)
    is_anonymous = True
    if "is_anonymous" in data and data["is_anonymous"] is not None:
        is_anonymous = as_bool(data["is_anonymous"], "is_anonymous")
    reporter_contact = opt_str(data, "reporter_contact")
    if is_anonymous:
        if reporter_contact is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "reporter_contact is not allowed for an anonymous report",
            )
    else:
        if not reporter_contact:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "reporter_contact is required when is_anonymous is false",
            )
    subject_employee_ids = []
    if "subject_employee_ids" in data and data["subject_employee_ids"] is not None:
        subject_employee_ids = as_str_list(data["subject_employee_ids"], "subject_employee_ids")

    rec = {
        "id": new_id(),
        "channel": channel,
        "category": category,
        "confirmed_category": None,
        "description": description,
        "region": region,
        "is_anonymous": is_anonymous,
        "reporter_contact": reporter_contact,
        "reporter_access_key": "rak_" + new_id().replace("-", ""),
        "subject_employee_ids": subject_employee_ids,
        "status": "RECEIVED",
        "severity": None,
        "sla_days": None,
        "triaged_by_id": None,
        "assigned_investigator_id": None,
        "duplicate_of_case_id": None,
        "received_at": now_dt(),
        "closure_ready_at": None,
        "closed_at": None,
        "reopen_count": 0,
        "determination_finding": None,
        "_pending_notice_summary": None,
        "created_at": now_dt(),
        "updated_at": now_dt(),
        "version": 1,
        "_seq": next_seq(),
    }
    DB["cases"][rec["id"]] = rec
    add_event(rec["id"], "CASE_CREATED", None, "RECEIVED", "HotlineReporter", user_id)
    # The reporter_access_key is returned exactly once: in this intake response.
    return ok(case_view(rec, include_reporter_key=True), status=201)


@bp.get("/hotline/cases")
def list_cases():
    auth(STAFF_READ_ROLES)
    limit, offset = pagination_args()
    records = list(DB["cases"].values())
    status = request.args.get("status")
    if status is not None:
        records = [c for c in records if c["status"] == status]
    severity = request.args.get("severity")
    if severity is not None:
        records = [c for c in records if c["severity"] == severity]
    region = request.args.get("region")
    if region is not None:
        records = [c for c in records if c["region"] == region]
    investigator = request.args.get("assigned_investigator_id")
    if investigator is not None:
        records = [c for c in records if c["assigned_investigator_id"] == investigator]
    duplicate_of = request.args.get("duplicate_of_case_id")
    if duplicate_of is not None:
        records = [c for c in records if c["duplicate_of_case_id"] == duplicate_of]
    page, total = paginate(records, limit, offset)
    return ok_list([case_view(c) for c in page], total, limit, offset)


@bp.get("/hotline/cases/<cid>")
def get_one_case(cid):
    auth(STAFF_READ_ROLES)
    return ok(case_view(get_case(cid)))


@bp.get("/hotline/cases/<cid>/reporter-status")
def reporter_status(cid):
    user_id, _ = auth(["HotlineReporter"])
    case = get_case(cid)
    if user_id != case["reporter_access_key"]:
        raise ApiError(
            "ERR_REPORTER_ACCESS_DENIED", 403, "X-User-ID does not match the case access key"
        )
    notices = [
        n for n in DB["closure_notices"].values() if n["case_id"] == case["id"]
    ]
    notices.sort(key=lambda n: n["_seq"])
    closure_summary = notices[-1]["closure_summary"] if notices else None
    return ok(
        {
            "case_status": case["status"],
            "severity": case["severity"],
            "closure_summary": closure_summary,
            "monitoring_active": case["status"] == "MONITORING",
        }
    )


@bp.post("/hotline/cases/<cid>/withdraw")
def withdraw_case(cid):
    user_id, _ = auth(["HotlineReporter"])
    case = get_case(cid)
    if user_id != case["reporter_access_key"]:
        raise ApiError(
            "ERR_REPORTER_ACCESS_DENIED", 403, "X-User-ID does not match the case access key"
        )
    if case["status"] not in ("RECEIVED", "TRIAGED"):
        raise ApiError(
            "ERR_CASE_NOT_WITHDRAWABLE",
            409,
            "Only a case in RECEIVED or TRIAGED may be withdrawn",
        )
    from_status = case["status"]
    case["status"] = "WITHDRAWN"
    bump(case)
    add_event(case["id"], "CASE_WITHDRAWN", from_status, "WITHDRAWN", "HotlineReporter", user_id)
    return ok(case_view(case))


@bp.post("/hotline/cases/<cid>/triage")
def triage_case(cid):
    user_id, _ = auth(["IntakeSpecialist"])
    case = get_case(cid)
    data = body()
    confirmed_category = req_enum(data, "confirmed_category", CATEGORIES)
    subject_seniority = req_enum(data, "subject_seniority", SENIORITIES)
    financial_exposure_band = req_enum(data, "financial_exposure_band", EXPOSURE_BANDS)
    reporter_vulnerability = req_enum(data, "reporter_vulnerability", VULNERABILITIES)
    triage_decision = req_enum(data, "triage_decision", TRIAGE_DECISIONS)
    reject_reason = opt_str(data, "reject_reason")
    duplicate_of_case_id = opt_str(data, "duplicate_of_case_id")

    if case["status"] != "RECEIVED":
        raise ApiError("ERR_CASE_NOT_RECEIVED", 409, "Triage requires case status RECEIVED")

    if triage_decision == "REJECT":
        if duplicate_of_case_id is not None:
            target = DB["cases"].get(duplicate_of_case_id)
            if target is None or target["status"] in CASE_TERMINAL_STATES:
                raise ApiError(
                    "ERR_DUPLICATE_TARGET_INVALID",
                    409,
                    "duplicate_of_case_id must reference a non-terminal case",
                )
        case["status"] = "REJECTED"
        case["duplicate_of_case_id"] = duplicate_of_case_id
        case["reject_reason"] = reject_reason
        bump(case)
        add_event(case["id"], "CASE_REJECTED", "RECEIVED", "REJECTED", "IntakeSpecialist", user_id)
        return ok(case_view(case))

    # PROCEED: compute severity from the four questionnaire inputs on this case.
    case["confirmed_category"] = confirmed_category
    case["severity"] = compute_severity(
        confirmed_category, subject_seniority, financial_exposure_band, reporter_vulnerability
    )
    case["sla_days"] = SLA_DAYS[case["severity"]]
    case["triaged_by_id"] = user_id
    case["status"] = "TRIAGED"
    bump(case)
    add_event(case["id"], "TRIAGED", "RECEIVED", "TRIAGED", "IntakeSpecialist", user_id)
    return ok(case_view(case))
