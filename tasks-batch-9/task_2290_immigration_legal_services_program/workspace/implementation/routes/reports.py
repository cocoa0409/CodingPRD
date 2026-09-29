"""Grant reports: confidentiality partition and reimbursement rollup (PRD 3.10)."""

from flask import Blueprint, request

import auth
import calc
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("reports", __name__)

DISCLOSURE_LEVELS = ("AGGREGATE_ONLY", "DEIDENTIFIED_CASE_LEVEL",
                     "IDENTIFIED_WITH_CONSENT")


def _report_or_404(report_id):
    row = store.get("reports", report_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The grant report does not exist.")
    return row


def _line_set(report):
    """Every matter of the cycle decided inside the inclusive period window."""
    start = store.parse_date(report.get("period_start_date"))
    end = store.parse_date(report.get("period_end_date"))
    lines = []
    for matter in store.rows("matters"):
        if matter.get("cycle_id") != report.get("cycle_id"):
            continue
        if matter.get("representation_status") == "WITHDRAWN_FROM":
            continue
        screening = store.get("screenings", matter.get("intake_id"))
        decided = store.parse_dt(screening.get("decided_at_utc")) if screening else None
        if decided is None:
            continue
        if start is not None and decided.date() < start:
            continue
        if end is not None and decided.date() > end:
            continue
        lines.append(matter)
    lines.sort(key=store.order_key)
    return lines


@bp.post("/grant-reports")
@auth.requires("GrantAnalyst", "ProgramDirector")
def create_report():
    payload = v.body()
    cycle_id = v.as_id(payload, "cycle_id")
    cycle = store.get("cycles", cycle_id)
    if cycle is None:
        raise ApiError("ERR_CYCLE_NOT_FOUND")
    grant_code = v.upper_code(payload, "grant_code", 2, 24)
    start = v.as_date(payload, "period_start_date")
    end = v.as_date(payload, "period_end_date")
    level = v.as_enum(payload, "disclosure_level", DISCLOSURE_LEVELS)

    cycle_start = store.parse_date(cycle.get("period_start_date"))
    cycle_end = store.parse_date(cycle.get("period_end_date"))
    if start > end:
        raise ApiError("ERR_REPORT_PERIOD_INVALID",
                       "period_start_date must not be after period_end_date.")
    if ((cycle_start is not None and start < cycle_start)
            or (cycle_end is not None and end > cycle_end)):
        raise ApiError("ERR_REPORT_PERIOD_INVALID",
                       "The reporting period falls outside the cycle window.")

    row = store.insert("reports", store.new_row({
        "cycle_id": cycle_id,
        "grant_code": grant_code,
        "period_start_date": start.isoformat(),
        "period_end_date": end.isoformat(),
        "disclosure_level": level,
        "status": "DRAFT",
        "cases_served_count": 0,
        "outcomes_summary": {},
        "consent_verified_count": 0,
        "suppressed_case_count": 0,
        "base_reimbursable_cents": 0,
        "supervision_surcharge_cents": 0,
        "total_reimbursable_cents": 0,
        "allocated_line_total_cents": 0,
        "rounding_remainder_cents": 0,
        "amendment_round": 0,
        "generated_at_utc": None,
        "submitted_at_utc": None,
    }))
    return response.created(serialize.report(row))


@bp.get("/grant-reports")
@auth.requires("GrantAnalyst", "ProgramDirector")
def list_reports():
    rows = store.rows("reports")
    args = request.args
    for key in ("cycle_id", "grant_code", "disclosure_level", "status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.report(r) for r in page], meta)


@bp.get("/grant-reports/<report_id>")
@auth.requires("GrantAnalyst", "ProgramDirector")
def read_report(report_id):
    return response.ok(serialize.report(_report_or_404(report_id)))


def _generate(row):
    lines = _line_set(row)
    level = row["disclosure_level"]
    sufficient = calc.DISCLOSURE_CONSENT_REQUIREMENTS[level]
    scopes = []
    for matter in lines:
        client = store.get("clients", matter.get("client_id"))
        scopes.append(client.get("confidentiality_consent_scope") if client else None)
    verified = sum(1 for scope in scopes if scope in sufficient)
    if level == "IDENTIFIED_WITH_CONSENT" and verified != len(lines):
        raise ApiError("ERR_CONSENT_SCOPE_INSUFFICIENT",
                       "Every reported client must hold FUNDER_IDENTIFIED consent.")

    money = calc.grant_financials(lines)
    row["cases_served_count"] = len(lines)
    row["outcomes_summary"] = calc.outcomes_summary(lines)
    row["consent_verified_count"] = verified
    row["suppressed_case_count"] = len(lines) - verified
    for key in ("base_reimbursable_cents", "supervision_surcharge_cents",
                "total_reimbursable_cents", "allocated_line_total_cents",
                "rounding_remainder_cents"):
        row[key] = money[key]
    if row["allocated_line_total_cents"] != row["total_reimbursable_cents"]:
        raise ApiError("ERR_INVARIANT_VIOLATION",
                       "The allocated line total does not conserve the report total.")
    row["generated_at_utc"] = store.clock_iso()
    row["status"] = "GENERATED"
    store.touch(row)


@bp.post("/grant-reports/<report_id>/transition")
@auth.requires("GrantAnalyst", "ProgramDirector")
def transition_report(report_id):
    row = _report_or_404(report_id)
    payload = v.body()
    action = v.as_enum(payload, "action", ("GENERATE", "SUBMIT", "AMEND"))
    v.as_str(payload, "amendment_reason_code", required=False, min_len=1, max_len=40,
             default=None)
    status = row["status"]

    if action == "GENERATE":
        if status not in ("DRAFT", "AMENDED"):
            raise ApiError("ERR_REPORT_STATE_INVALID",
                           "GENERATE is only legal from DRAFT or AMENDED.")
        _generate(row)
    elif action == "SUBMIT":
        if status != "GENERATED":
            raise ApiError("ERR_REPORT_STATE_INVALID",
                           "SUBMIT is only legal from GENERATED.")
        if row["allocated_line_total_cents"] != row["total_reimbursable_cents"]:
            raise ApiError("ERR_INVARIANT_VIOLATION",
                           "The allocated line total does not conserve the total.")
        if (row["disclosure_level"] == "IDENTIFIED_WITH_CONSENT"
                and int(row.get("suppressed_case_count") or 0) != 0):
            raise ApiError("ERR_CONSENT_SCOPE_INSUFFICIENT",
                           "An identified report may not suppress any case.")
        row["submitted_at_utc"] = store.clock_iso()
        row["status"] = "SUBMITTED"
        store.touch(row)
    else:
        if status != "SUBMITTED":
            raise ApiError("ERR_REPORT_STATE_INVALID",
                           "AMEND is only legal from SUBMITTED.")
        row["amendment_round"] = int(row.get("amendment_round") or 0) + 1
        row["submitted_at_utc"] = None
        row["status"] = "AMENDED"
        store.touch(row)
    return response.ok(serialize.report(row))
