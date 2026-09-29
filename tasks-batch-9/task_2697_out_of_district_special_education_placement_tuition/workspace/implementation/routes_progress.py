"""Quarterly progress reporting and the return-readiness gate (PRD 3.8)."""
from flask import Blueprint

from calc import (
    MIN_ACCEPTED_REPORTS,
    READINESS_VARIANTS,
    RETURN_READINESS_MIN,
    TRANSITION_SERVICES_RESERVE_CENTS,
    recompute_placement_encumbrance,
    report_score,
    return_readiness,
)
from cascades import account_of, book_encumbrance
from common import (
    REPORT_DECISIONS,
    collection,
    placement_or_404,
    plan_or_404,
    report_or_404,
    single,
)
from errors import fail
from middleware import (
    ALL_ROLES,
    PLACEMENT_COORDINATOR,
    SCHOOL_BILLING_AGENT,
    TEAM_CHAIR,
    check_scope,
    endpoint,
)
from response import created, ok
from store import clock_date, db, new_row, parse_date, public, touch
from validation import (
    get_date,
    get_enum,
    get_id,
    get_int,
    get_number,
    get_str_array,
    get_text,
    q_enum,
    q_int,
    q_str,
    read_body,
)

bp = Blueprint("progress", __name__)


# =========================================================================
# progress reports
# =========================================================================

@endpoint(bp, "GET", "/progress-reports", ALL_ROLES)
def list_progress_reports():
    return collection(db.progress.values(), [
        ("placement_id", q_str("placement_id")),
        ("status", q_str("status")),
        ("fiscal_year", q_int("fiscal_year")),
    ])


@endpoint(bp, "GET", "/progress-reports/<report_id>", ALL_ROLES)
def get_progress_report(report_id):
    return single(report_or_404(report_id))


@endpoint(bp, "POST", "/progress-reports", (SCHOOL_BILLING_AGENT, PLACEMENT_COORDINATOR))
def create_progress_report():
    body = read_body((
        "placement_id", "fiscal_year", "quarter", "goals_total", "goals_met",
        "goals_regressed", "benchmark_scaled_score", "attendance_rate_pct",
    ))
    placement_id = get_id(body, "placement_id")
    fiscal_year = get_int(body, "fiscal_year", minimum=2020, maximum=2100)
    quarter = get_int(body, "quarter")
    goals_total = get_int(body, "goals_total", minimum=1)
    goals_met = get_int(body, "goals_met", minimum=0)
    goals_regressed = get_int(body, "goals_regressed", required=False, default=0, minimum=0)
    benchmark = get_number(body, "benchmark_scaled_score", minimum=0, maximum=100)
    attendance = get_number(body, "attendance_rate_pct", minimum=0, maximum=100)
    if goals_met > goals_total:
        fail("ERR_INVALID_REQUEST", "goals_met may not exceed goals_total.")
    if goals_met + goals_regressed > goals_total:
        fail("ERR_INVALID_REQUEST",
             "goals_met plus goals_regressed may not exceed goals_total.")

    placement = placement_or_404(placement_id)
    check_scope(placement)

    if quarter < 1 or quarter > 4:
        fail("ERR_DUPLICATE_PROGRESS_PERIOD", "quarter must be an integer from 1 to 4.")
    for other in db.progress.values():
        if (other["placement_id"] == placement_id
                and other["fiscal_year"] == fiscal_year
                and other["quarter"] == quarter
                and other["status"] in ("SUBMITTED", "ACCEPTED")):
            fail("ERR_DUPLICATE_PROGRESS_PERIOD",
                 "A live report already covers this placement, fiscal year and quarter.")

    row = new_row("progress", {
        "placement_id": placement_id,
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "goals_total": goals_total,
        "goals_met": goals_met,
        "goals_regressed": goals_regressed,
        "benchmark_scaled_score": benchmark,
        "attendance_rate_pct": attendance,
        "report_score": 0,
        "status": "SUBMITTED",
    })
    row["report_score"] = report_score(row)
    db.progress[row["id"]] = row
    return created(public(row))


@endpoint(bp, "POST", "/progress-reports/<report_id>/accept",
          (PLACEMENT_COORDINATOR, TEAM_CHAIR))
def accept_progress_report(report_id):
    report = report_or_404(report_id)
    body = read_body(("decision",))
    decision = get_enum(body, "decision", REPORT_DECISIONS)

    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a SUBMITTED progress report may be disposed of.")

    if decision == "ACCEPT":
        placement = db.placements.get(report["placement_id"])
        if placement is None or placement["status"] not in (
                "ACTIVE", "TERMINATED", "RETURNED_TO_DISTRICT"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A report may only be accepted on an active or closed placement.")
        report["status"] = "ACCEPTED"
        report["report_score"] = report_score(report)
    else:
        report["status"] = "REJECTED"
        report["report_score"] = 0
    touch(report)
    return ok(public(report))


# =========================================================================
# return transition plans
# =========================================================================

@endpoint(bp, "GET", "/return-transition-plans", ALL_ROLES)
def list_transition_plans():
    return collection(db.plans.values(), [
        ("placement_id", q_str("placement_id")),
        ("status", q_str("status")),
    ])


@endpoint(bp, "GET", "/return-transition-plans/<plan_id>", ALL_ROLES)
def get_transition_plan(plan_id):
    return single(plan_or_404(plan_id))


@endpoint(bp, "POST", "/return-transition-plans", (PLACEMENT_COORDINATOR, TEAM_CHAIR))
def create_transition_plan():
    body = read_body(("placement_id", "target_return_date", "receiving_program"))
    placement_id = get_id(body, "placement_id")
    target_date = get_date(body, "target_return_date")
    program = get_text(body, "receiving_program")

    placement = placement_or_404(placement_id)
    check_scope(placement)

    for other in db.plans.values():
        if other["placement_id"] == placement_id and other["status"] in ("DRAFT", "ACTIVE"):
            fail("ERR_DUPLICATE_RESOURCE",
                 "A non-terminal transition plan already exists for this placement.")

    row = new_row("plan", {
        "placement_id": placement_id,
        "target_return_date": target_date.isoformat(),
        "receiving_program": program,
        "transition_services": [],
        "readiness_score_at_activation": None,
        "reserve_cents": 0,
        "status": "DRAFT",
    })
    db.plans[row["id"]] = row
    return created(public(row))


@endpoint(bp, "GET", "/return-transition-plans/<plan_id>/readiness", ALL_ROLES)
def get_plan_readiness(plan_id):
    plan = plan_or_404(plan_id)
    variant = q_enum("variant", READINESS_VARIANTS) or "trailing_two_quarter"
    check_scope(plan)
    score, count, scores = return_readiness(plan["placement_id"], variant)
    contributing = scores[:2] if variant == "trailing_two_quarter" else scores
    met = count >= MIN_ACCEPTED_REPORTS and score >= RETURN_READINESS_MIN
    return ok({
        "plan_id": plan["id"],
        "variant": variant,
        "readiness_score": score,
        "accepted_report_count": count,
        "readiness_met": met,
        "report_scores": contributing,
    })


@endpoint(bp, "POST", "/return-transition-plans/<plan_id>/activate", (TEAM_CHAIR,))
def activate_transition_plan(plan_id):
    plan = plan_or_404(plan_id)
    body = read_body(("transition_services", "readiness_variant"))
    services = get_str_array(body, "transition_services")
    variant = get_enum(body, "readiness_variant", READINESS_VARIANTS,
                       required=False, default="trailing_two_quarter")

    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT plan may be activated.")
    placement = db.placements.get(plan["placement_id"])
    if placement is None or placement["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "The parent placement must be ACTIVE.")
    for other in db.plans.values():
        if (other["id"] != plan["id"]
                and other["placement_id"] == plan["placement_id"]
                and other["status"] == "ACTIVE"):
            fail("ERR_INVALID_STATE_TRANSITION",
                 "Another plan on this placement is already ACTIVE.")

    target_date = parse_date(plan["target_return_date"])
    if not services or any(not str(entry).strip() for entry in services):
        fail("ERR_TRANSITION_SERVICES_INCOMPLETE",
             "transition_services must carry at least one non-blank entry.")
    if target_date is None or target_date < clock_date():
        fail("ERR_TRANSITION_SERVICES_INCOMPLETE",
             "target_return_date may not fall before the current logical clock date.")

    score, count, _ = return_readiness(plan["placement_id"], variant)
    if count < MIN_ACCEPTED_REPORTS or score < RETURN_READINESS_MIN:
        fail("ERR_RETURN_READINESS_NOT_MET",
             "The placement has not cleared the return-readiness gate.")

    account = account_of(placement)
    if account is None or account["available_cents"] < TRANSITION_SERVICES_RESERVE_CENTS:
        fail("ERR_INSUFFICIENT_FISCAL_AUTHORITY",
             "The appropriation cannot cover the transition-services reserve.")

    plan["status"] = "ACTIVE"
    plan["transition_services"] = services
    plan["readiness_score_at_activation"] = score
    plan["reserve_cents"] = TRANSITION_SERVICES_RESERVE_CENTS
    touch(plan)

    placement["transition_reserve_cents"] = TRANSITION_SERVICES_RESERVE_CENTS
    recompute_placement_encumbrance(placement)
    touch(placement)
    book_encumbrance(account, TRANSITION_SERVICES_RESERVE_CENTS)
    return ok(public(plan))
