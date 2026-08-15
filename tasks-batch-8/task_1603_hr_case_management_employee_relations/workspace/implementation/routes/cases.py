"""Case intake, lifecycle transitions, and the litigation-hold freeze (PRD §3.2, §3.6)."""
from flask import Blueprint, request

from db import db, case_number_seq
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_INVESTIGATOR_CONFLICT,
    ERR_CERTIFICATION_INSUFFICIENT, ERR_CAPACITY_EXCEEDED, ERR_STALE_VERSION,
    ERR_CLOSURE_GATE, ERR_REOPEN_LIMIT, ERR_DOCUMENTATION_STANDARD,
    ERR_UNAUTHORIZED,
)
from middleware import authorize, require_investigator
from response import success_object
from services import calculations as calc
from services.core import (
    new_record, touch, require_path, require_ref, list_response, serialize_case,
    check_case_not_held, check_capacity_available, get_bool_filter,
    bump_investigator_count, mark_snapshots_stale_for_case,
    recompute_assessment_scores,
    interviews_of, notices_of, findings_of, assessments_of,
)
from util import CLOCK, fmt_dt, parse_dt
from validate import Payload
from routes.intake_channels import CATEGORIES, SEVERITIES
from routes.investigators import CERT_COVERS

bp = Blueprint("cases", __name__)

READ_ROLES = {"ERManager", "Investigator", "LegalCounsel", "HRAnalyst"}


def _mint_case_number(year: int) -> str:
    seq = case_number_seq.get(year, 0) + 1
    case_number_seq[year] = seq
    return f"ER-{year:04d}-{seq:04d}"


def _check_occ(case, expected_version):
    """OCC screen (priority 23) — runs only when a value was supplied; a missing
    expected_case_version is a syntactic failure handled at priority 24."""
    if expected_version is not None and expected_version != case["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_case_version {expected_version} does not match "
                    f"current case version {case['version']}")


@bp.post("/er/cases")
def create_case():
    authorize({"ERManager"})
    p = Payload(request.get_json(silent=True))
    intake_channel_id = p.get_str("intake_channel_id", required=True)
    subject_employee_id = p.get_str("subject_employee_id", required=True)
    reporter_employee_id = p.get_str("reporter_employee_id", required=False)
    category = p.get_enum("category", CATEGORIES, required=False)
    severity = p.get_enum("severity", SEVERITIES, required=False)
    litigation_hold = p.get_bool("litigation_hold", required=False)

    # priority 5 — body FK resolution
    channel = None
    if intake_channel_id is not None:
        channel = require_ref("intake_channels", intake_channel_id,
                              "intake_channel_id")
    if subject_employee_id is not None:
        require_ref("employees", subject_employee_id, "subject_employee_id")
    if reporter_employee_id is not None:
        require_ref("employees", reporter_employee_id, "reporter_employee_id")

    # priority 24 — includes the mandatory-reporter rule ("fails as an invalid
    # request", PRD §3.2)
    if channel is not None and channel["requires_reporter_identity"] \
            and reporter_employee_id is None:
        p.errors.append("reporter_employee_id is required for this intake channel")
    p.raise_if_errors()

    now = CLOCK.now()
    intake_dt = now
    due_dt = calc.sla_due_date_for(intake_dt, channel)
    rec = new_record()
    rec.update({
        "case_number": _mint_case_number(now.year),
        "intake_channel_id": intake_channel_id,
        "reporter_employee_id": reporter_employee_id,
        "subject_employee_id": subject_employee_id,
        "category": category if category is not None else channel["default_category"],
        "severity": severity if severity is not None else channel["default_severity"],
        "status": "TRIAGE",
        "assigned_investigator_id": None,
        "litigation_hold": litigation_hold if litigation_hold is not None else False,
        "reopen_count": 0,
        "sla_due_date": fmt_dt(due_dt),
        "_sla_due_dt": due_dt,
        "intake_received_at": fmt_dt(intake_dt),
        "closed_at": None,
        "days_to_close": None,
        "_closures": [],
    })
    db["cases"][rec["id"]] = rec
    return success_object(serialize_case(rec), status=201)


@bp.get("/er/cases/<cid>")
def get_case(cid):
    authorize(READ_ROLES)
    rec = require_path("cases", cid)
    return success_object(serialize_case(rec))


@bp.get("/er/cases")
def list_cases():
    authorize(READ_ROLES)
    items = list(db["cases"].values())
    for field in ("status", "category", "severity", "assigned_investigator_id",
                  "subject_employee_id", "reporter_employee_id",
                  "intake_channel_id"):
        v = request.args.get(field)
        if v is not None:
            items = [c for c in items if c.get(field) == v]
    hold_filter = get_bool_filter("litigation_hold")
    if hold_filter is not None:
        items = [c for c in items if c["litigation_hold"] == hold_filter]
    return list_response(items, serialize_case)


@bp.patch("/er/cases/<cid>")
def patch_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    intake_channel_id = p.get_str("intake_channel_id")
    category = p.get_enum("category", CATEGORIES)
    severity = p.get_enum("severity", SEVERITIES)
    litigation_hold = p.get_bool("litigation_hold")

    # priority 5 — body FK resolution
    new_channel = None
    if intake_channel_id is not None:
        new_channel = require_ref("intake_channels", intake_channel_id,
                                  "intake_channel_id")

    # priority 6 — mutability windows (litigation_hold toggling is exempt from
    # the freeze: PATCH is the operation through which legal places/lifts it)
    if (intake_channel_id is not None or category is not None
            or severity is not None) and case["status"] != "TRIAGE":
        raise_error(ERR_INVALID_STATE,
                    "intake_channel_id, category and severity are mutable only "
                    "while the case is TRIAGE")
    if litigation_hold is not None and case["status"] not in ("TRIAGE", "CLOSED"):
        raise_error(ERR_INVALID_STATE,
                    "litigation_hold is mutable only while the case is TRIAGE "
                    "or CLOSED")

    # priority 24
    p.raise_if_errors()

    changed = False
    if intake_channel_id is not None:
        case["intake_channel_id"] = intake_channel_id
        # channel change recomputes the SLA due date from the new channel's
        # allowance, anchored at the original intake timestamp
        due_dt = calc.sla_due_date_for(parse_dt(case["intake_received_at"]),
                                       new_channel)
        case["sla_due_date"] = fmt_dt(due_dt)
        case["_sla_due_dt"] = due_dt
        changed = True
    if category is not None:
        case["category"] = category
        changed = True
    if severity is not None:
        case["severity"] = severity
        changed = True
    if litigation_hold is not None:
        case["litigation_hold"] = litigation_hold
        changed = True
    if changed:
        touch(case)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/assign")
def assign_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    investigator_id = p.get_str("investigator_id", required=True)
    expected_version = p.get_int("expected_case_version", required=True)

    # priority 5
    inv = None
    if investigator_id is not None:
        inv = require_ref("investigators", investigator_id, "investigator_id")

    # priority 6 — state legality (REOPENED behaves as TRIAGE for assignment)
    if case["status"] not in ("TRIAGE", "REOPENED"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot assign a case in status {case['status']}")
    # priority 7 — litigation-hold freeze
    check_case_not_held(case)

    if inv is not None:
        # priority 9 — conflict screen fires first among business checks
        conflicts = inv["conflicted_employee_ids"]
        if case["subject_employee_id"] in conflicts or (
                case["reporter_employee_id"] is not None
                and case["reporter_employee_id"] in conflicts):
            raise_error(ERR_INVESTIGATOR_CONFLICT,
                        "investigator is conflicted against the case subject "
                        "or reporter")
        # priority 10 — certification ladder
        if case["severity"] not in CERT_COVERS[inv["certification_level"]]:
            raise_error(ERR_CERTIFICATION_INSUFFICIENT,
                        f"{inv['certification_level']} does not cover "
                        f"{case['severity']} cases")
        # priority 14 — capacity (live derived count)
        check_capacity_available(inv)

    # priority 23 — OCC
    _check_occ(case, expected_version)
    # priority 24
    p.raise_if_errors()

    case["assigned_investigator_id"] = investigator_id
    case["status"] = "ASSIGNED"
    touch(case)
    bump_investigator_count(investigator_id, +1)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/unassign")
def unassign_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    expected_version = p.get_int("expected_case_version", required=True)

    # priority 6
    if case["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot unassign a case in status {case['status']}")
    if any(iv["status"] == "COMPLETED" for iv in interviews_of(cid)):
        raise_error(ERR_INVALID_STATE,
                    "cannot unassign a case with a completed interview")
    # priority 7
    check_case_not_held(case)
    # priority 23
    _check_occ(case, expected_version)
    # priority 24
    p.raise_if_errors()

    departing = case["assigned_investigator_id"]
    case["assigned_investigator_id"] = None
    case["status"] = "TRIAGE"
    touch(case)
    if departing is not None:
        bump_investigator_count(departing, -1)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/begin-investigation")
def begin_investigation(cid):
    caller = authorize({"Investigator"})
    case = require_path("cases", cid)

    # priority 6
    if case["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot begin investigation on a case in status "
                    f"{case['status']}")
    # priority 7
    check_case_not_held(case)
    # ownership — only the assigned investigator may open the file
    inv = require_investigator(caller)
    if inv["id"] != case["assigned_investigator_id"]:
        raise_error(ERR_UNAUTHORIZED,
                    "only the case's assigned investigator may begin the "
                    "investigation")

    case["status"] = "INVESTIGATING"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/hold")
def hold_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    hold_reason = p.get_str("hold_reason", required=True)

    # priority 6
    if case["status"] != "INVESTIGATING":
        raise_error(ERR_INVALID_STATE,
                    f"cannot hold a case in status {case['status']}")
    # priority 7
    check_case_not_held(case)
    # priority 16 — documentation standard
    if hold_reason is not None and len(hold_reason) < 20:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "hold_reason must be at least 20 characters")
    # priority 24
    p.raise_if_errors()

    # cascade: every SCHEDULED interview on the case is cancelled (each child
    # gets its own timestamp/version bump)
    for iv in interviews_of(cid):
        if iv["status"] == "SCHEDULED":
            iv["status"] = "CANCELLED"
            touch(iv)
    case["status"] = "ON_HOLD"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/resume")
def resume_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    if case["status"] != "ON_HOLD":
        raise_error(ERR_INVALID_STATE,
                    f"cannot resume a case in status {case['status']}")
    check_case_not_held(case)
    case["status"] = "INVESTIGATING"
    touch(case)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/close")
def close_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    expected_version = p.get_int("expected_case_version", required=True)

    # priority 6
    if case["status"] != "PENDING_CLOSURE":
        raise_error(ERR_INVALID_STATE,
                    f"cannot close a case in status {case['status']}")
    # priority 7
    check_case_not_held(case)

    # priority 18 — closure gates, evaluated before the version screen
    case_findings = findings_of(cid)
    if not any(f["approval_status"] == "APPROVED" for f in case_findings):
        raise_error(ERR_CLOSURE_GATE, "no APPROVED finding on the case")
    case_notices = notices_of(cid)
    if not any(n["recipient_role"] == "SUBJECT" and n["delivery_status"] == "SENT"
               for n in case_notices):
        raise_error(ERR_CLOSURE_GATE, "no SENT closure notice for the SUBJECT")
    if case["reporter_employee_id"] is not None:
        if not any(n["recipient_role"] == "REPORTER"
                   and n["delivery_status"] == "SENT" for n in case_notices):
            raise_error(ERR_CLOSURE_GATE,
                        "no SENT closure notice for the REPORTER")

    # priority 23 — OCC
    _check_occ(case, expected_version)
    # priority 24
    p.raise_if_errors()

    now = CLOCK.now()
    case["status"] = "CLOSED"
    case["closed_at"] = fmt_dt(now)
    case["_closures"] = case.get("_closures", []) + [now]
    intake_dt = parse_dt(case["intake_received_at"])
    case["days_to_close"] = (now.date() - intake_dt.date()).days
    touch(case)
    if case["assigned_investigator_id"] is not None:
        bump_investigator_count(case["assigned_investigator_id"], -1)
    mark_snapshots_stale_for_case(case)
    return success_object(serialize_case(case))


@bp.post("/er/cases/<cid>/reopen")
def reopen_case(cid):
    authorize({"ERManager"})
    case = require_path("cases", cid)
    p = Payload(request.get_json(silent=True))
    reopen_reason = p.get_str("reopen_reason", required=True)

    # priority 6 — reopen is defined only from CLOSED ("A CLOSED case may be
    # reopened", PRD §3.6); from any other status the transition is undefined
    if case["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE,
                    f"cannot reopen a case in status {case['status']}")
    # priority 7 — never while a litigation hold is in force
    check_case_not_held(case)
    # priority 16 — documentation standard (before the reopen limit per §2.6)
    if reopen_reason is not None and len(reopen_reason) < 30:
        raise_error(ERR_DOCUMENTATION_STANDARD,
                    "reopen_reason must be at least 30 characters")
    # priority 19 — reopen cap: a case whose reopen_count has already reached
    # two refuses (per-case counter, PRD §3.6)
    if not case["reopen_count"] < 2:
        raise_error(ERR_REOPEN_LIMIT,
                    "case has already been reopened twice")
    # priority 24
    p.raise_if_errors()

    case["reopen_count"] += 1
    case["status"] = "REOPENED"
    # closed_at and days_to_close are retained for the prior closure
    touch(case)
    # every credibility assessment flips to RECENCY_WEIGHTED, scores recomputed
    for assessment in assessments_of(cid):
        assessment["active_variant"] = "RECENCY_WEIGHTED"
        recompute_assessment_scores(assessment)
        touch(assessment)
    mark_snapshots_stale_for_case(case)
    return success_object(serialize_case(case))
