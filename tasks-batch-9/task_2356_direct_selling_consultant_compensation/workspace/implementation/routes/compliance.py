"""Compliance cases, the disciplinary ladder and appeals."""

from flask import Blueprint

from common import (
    clock_dt,
    clock_str,
    fmt_dt,
    new_row,
    opt_dt_str,
    opt_enum,
    opt_str,
    pagination,
    paginate,
    parse_dt,
    plus_days,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import actor_id, auth, own_consultant
from response import created, ok, ok_list
from services import consultant_ops
from services.genealogy import by_created
from services.lookup import fetch, peek

bp = Blueprint("compliance", __name__)

CASE_STATUSES = ("OPEN", "UNDER_REVIEW", "SANCTIONED", "DISMISSED", "APPEALED")
CLAIM_TYPES = ("INCOME_CLAIM", "PRODUCT_CLAIM", "PRICING_VIOLATION", "CROSS_RECRUITING")
SANCTION_LEVELS = ("WARNING", "PROBATION", "SUSPENSION", "TERMINATION")
SANCTION_ORDER = {"WARNING": 1, "PROBATION": 2, "SUSPENSION": 3, "TERMINATION": 4}

READ_ROLES = ["Consultant", "ComplianceOfficer", "PlatformAdmin"]


@bp.post("/compliance-cases")
def create_case():
    auth(["ComplianceOfficer"])
    body = raw_body()
    consultant_id = req_str(body, "consultant_id", min_len=1)
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    evidence_reference = req_str(body, "evidence_reference", min_len=1)

    consultant = fetch("consultant", consultant_id)
    if consultant["status"] == "TERMINATED":
        raise ApiError("ERR_CONSULTANT_ALREADY_TERMINATED")

    row = new_row()
    row.update(
        {
            "consultant_id": consultant["id"],
            "claim_type": claim_type,
            "evidence_reference": evidence_reference,
            "status": "OPEN",
            "sanction_level": None,
            "sanction_order": 0,
            "effective_from": None,
            "effective_until": None,
            "appeal_deadline_at": None,
            "appeal_count": 0,
            "reviewed_by_user_id": None,
            "decision_reason": None,
            "resolved_at": None,
        }
    )
    db.cases[row["id"]] = row

    consultant["open_case_count"] = int(consultant["open_case_count"]) + 1
    touch(consultant)
    return created(row)


@bp.get("/compliance-cases")
def list_cases():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "consultant_id": q_str("consultant_id"),
        "status": q_enum("status", CASE_STATUSES),
        "claim_type": q_enum("claim_type", CLAIM_TYPES),
        "sanction_level": q_enum("sanction_level", SANCTION_LEVELS),
    }
    rows = by_created(list(db.cases.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/compliance-cases/<case_id>")
def read_case(case_id):
    auth(READ_ROLES)
    existing = peek("case", case_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])
    return ok(fetch("case", case_id))


@bp.post("/compliance-cases/<case_id>/review")
def review_case(case_id):
    auth(["ComplianceOfficer"])
    case = fetch("case", case_id)
    if case["status"] not in ("OPEN", "APPEALED"):
        raise ApiError("ERR_CASE_NOT_REVIEWABLE")

    case["status"] = "UNDER_REVIEW"
    case["reviewed_by_user_id"] = actor_id()
    touch(case)
    return ok(case)


def _window_conflict(case, consultant_id, new_from, new_until, cooloff_days):
    for other in db.cases.values():
        if other["id"] == case["id"] or other["consultant_id"] != consultant_id:
            continue
        if other["status"] != "SANCTIONED":
            continue
        other_from = parse_dt(other.get("effective_from") or "")
        other_until = parse_dt(other.get("effective_until") or "")
        if other_from is None or other_until is None:
            continue
        if new_from <= other_until and other_from <= new_until:
            return True
        if other_until < new_from <= plus_days(other_until, cooloff_days):
            return True
    return False


@bp.post("/compliance-cases/<case_id>/decision")
def decide_case(case_id):
    auth(["ComplianceOfficer"])
    body = raw_body()
    decision = req_enum(body, "decision", ("SANCTION", "DISMISS"))
    sanction_level = opt_enum(body, "sanction_level", SANCTION_LEVELS)
    effective_from = opt_dt_str(body, "effective_from")
    effective_until = opt_dt_str(body, "effective_until")
    decision_reason = opt_str(body, "decision_reason")

    case = fetch("case", case_id)
    if case["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CASE_NOT_UNDER_REVIEW")

    consultant = db.consultants.get(case["consultant_id"])
    plan = (
        db.plans.get(consultant["compensation_plan_id"]) if consultant is not None else None
    )

    if decision == "SANCTION":
        if sanction_level is None or effective_from is None or effective_until is None:
            raise ApiError("ERR_SANCTION_FIELDS_REQUIRED")
        order = SANCTION_ORDER[sanction_level]
        held = int(consultant["highest_sanction_order"]) if consultant else 0
        if not order > held:
            raise ApiError("ERR_DISCIPLINARY_ESCALATION_REQUIRED")
        from_dt = parse_dt(effective_from)
        until_dt = parse_dt(effective_until)
        if not (until_dt > from_dt):
            raise ApiError("ERR_SANCTION_WINDOW_INVALID")
        cooloff = int(plan["sanction_cooloff_days"]) if plan else 0
        if _window_conflict(case, case["consultant_id"], from_dt, until_dt, cooloff):
            raise ApiError("ERR_SANCTION_WINDOW_CONFLICT")
        if sanction_level == "TERMINATION" and consultant is not None:
            if consultant_ops.approved_run_blocks_termination(consultant):
                raise ApiError("ERR_APPROVED_RUN_BLOCKS_TERMINATION")

        case["status"] = "SANCTIONED"
        case["sanction_level"] = sanction_level
        case["sanction_order"] = order
        case["effective_from"] = effective_from
        case["effective_until"] = effective_until
        case["decision_reason"] = decision_reason
        window_days = int(plan["appeal_window_days"]) if plan else 0
        case["appeal_deadline_at"] = fmt_dt(plus_days(from_dt, window_days))
        case["resolved_at"] = clock_str()
        touch(case)

        if consultant is not None:
            consultant["open_case_count"] = max(0, int(consultant["open_case_count"]) - 1)
            if sanction_level == "TERMINATION":
                consultant["active_sanction_level"] = "TERMINATION"
                consultant["active_sanction_until"] = None
                consultant["highest_sanction_order"] = max(held, 4)
                consultant_ops.terminate(consultant, "DISCIPLINARY", from_sanction=True)
            else:
                if sanction_level == "PROBATION":
                    if consultant["status"] == "ACTIVE":
                        consultant["status"] = "PROBATION"
                    consultant["active_sanction_level"] = "PROBATION"
                    consultant["active_sanction_until"] = effective_until
                    consultant["highest_sanction_order"] = max(held, 2)
                elif sanction_level == "SUSPENSION":
                    if consultant["status"] in ("ACTIVE", "PROBATION"):
                        consultant["status"] = "SUSPENDED"
                    consultant["active_sanction_level"] = "SUSPENSION"
                    consultant["active_sanction_until"] = effective_until
                    consultant["highest_sanction_order"] = max(held, 3)
                else:  # WARNING
                    consultant["highest_sanction_order"] = max(held, 1)
                touch(consultant)
    else:
        previous_level = case["sanction_level"]
        case["status"] = "DISMISSED"
        case["decision_reason"] = decision_reason
        case["resolved_at"] = clock_str()
        touch(case)

        if consultant is not None:
            consultant["open_case_count"] = max(0, int(consultant["open_case_count"]) - 1)
            if previous_level in ("PROBATION", "SUSPENSION"):
                consultant["status"] = "ACTIVE"
                consultant["active_sanction_level"] = None
                consultant["active_sanction_until"] = None
            touch(consultant)

    return ok(case)


@bp.post("/compliance-cases/<case_id>/appeal")
def appeal_case(case_id):
    auth(["Consultant"])
    existing = peek("case", case_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])

    body = raw_body()
    req_str(body, "appeal_statement", min_len=1)

    case = fetch("case", case_id)
    if case["status"] != "SANCTIONED":
        raise ApiError("ERR_CASE_NOT_SANCTIONED")
    deadline = parse_dt(case.get("appeal_deadline_at") or "")
    now = clock_dt()
    if deadline is not None and now is not None and now > deadline:
        raise ApiError("ERR_APPEAL_WINDOW_EXPIRED")
    if int(case["appeal_count"]) != 0:
        raise ApiError("ERR_APPEAL_ALREADY_FILED")

    case["status"] = "APPEALED"
    case["appeal_count"] = int(case["appeal_count"]) + 1
    touch(case)

    consultant = db.consultants.get(case["consultant_id"])
    if consultant is not None:
        consultant["open_case_count"] = int(consultant["open_case_count"]) + 1
        touch(consultant)
    return ok(case)
