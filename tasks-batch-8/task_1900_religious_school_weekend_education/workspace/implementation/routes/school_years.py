"""SchoolYear, SecurityPlan, CalendarClosure, clock endpoints."""

from flask import Blueprint, request
from decimal import Decimal

from db import store, parse_iso
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, not_found, invalid_state,
    ERR_SCHOOL_YEAR_NOT_OPEN, ERR_SECURITY_PLAN_NOT_ACTIVE, ERR_CLOSURE_OVERLAP,
)
from services.core import (
    base_record, touch, public, get_year, get_security_plan, parse_date,
    round_half_up_cents, reevaluate_milestones_for_section,
    recompute_family_outstanding, recompute_commitment,
)

bp = Blueprint("school_years", __name__)


NUM = (int, float)


def _req_field(body, name):
    if not isinstance(body, dict) or name not in body or body[name] is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def _req_int(body, name):
    v = _req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{name} must be an integer")
    return v


def _req_num(body, name):
    v = _req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, NUM):
        raise invalid_request(f"{name} must be a number")
    return v


def _req_str(body, name):
    v = _req_field(body, name)
    if not isinstance(v, str):
        raise invalid_request(f"{name} must be a string")
    return v


# ---------------------------------------------------------------------------
# SchoolYear
# ---------------------------------------------------------------------------

@bp.route("/school/school-years", methods=["POST"])
def create_school_year():
    require_roles(["SchoolAdmin"])
    body = request.get_json(silent=True) or {}

    name = _req_str(body, "name")
    start_date = _req_str(body, "start_date")
    end_date = _req_str(body, "end_date")
    sd = parse_date(start_date, "start_date")
    ed = parse_date(end_date, "end_date")
    if not sd < ed:
        raise invalid_request("start_date must be strictly earlier than end_date")

    member_tuition_cents = _req_int(body, "member_tuition_cents")
    non_member_tuition_cents = _req_int(body, "non_member_tuition_cents")
    if member_tuition_cents <= 0:
        raise invalid_request("member_tuition_cents must be > 0")
    if non_member_tuition_cents <= 0:
        raise invalid_request("non_member_tuition_cents must be > 0")

    early_bird_pct = _req_num(body, "early_bird_pct")
    if not (0 <= early_bird_pct < 1):
        raise invalid_request("early_bird_pct must be in [0, 1)")

    early_bird_deadline = _req_str(body, "early_bird_deadline")
    try:
        parse_iso(early_bird_deadline)
    except Exception:
        raise invalid_request("early_bird_deadline must be ISO 8601 datetime")

    sibling_discount_pcts = _req_field(body, "sibling_discount_pcts")
    if not isinstance(sibling_discount_pcts, list) or len(sibling_discount_pcts) == 0:
        raise invalid_request("sibling_discount_pcts must be a non-empty array")
    for p in sibling_discount_pcts:
        if isinstance(p, bool) or not isinstance(p, NUM):
            raise invalid_request("sibling_discount_pcts elements must be numbers")

    activity_fee_cents = _req_int(body, "activity_fee_cents")
    if activity_fee_cents < 0:
        raise invalid_request("activity_fee_cents must be >= 0")

    volunteer_hours_required = _req_int(body, "volunteer_hours_required")
    if volunteer_hours_required <= 0:
        raise invalid_request("volunteer_hours_required must be > 0")

    volunteer_buyout_fee_cents = _req_int(body, "volunteer_buyout_fee_cents")
    if volunteer_buyout_fee_cents < 0:
        raise invalid_request("volunteer_buyout_fee_cents must be >= 0")

    late_fee_pct = _req_num(body, "late_fee_pct")
    if not (0 <= late_fee_pct <= 1):
        raise invalid_request("late_fee_pct must be in [0, 1]")

    late_fee_min_balance_cents = _req_int(body, "late_fee_min_balance_cents")
    if late_fee_min_balance_cents < 0:
        raise invalid_request("late_fee_min_balance_cents must be >= 0")

    tuition_due_date = _req_str(body, "tuition_due_date")
    parse_date(tuition_due_date, "tuition_due_date")
    withdrawal_deadline = _req_str(body, "withdrawal_deadline")
    parse_date(withdrawal_deadline, "withdrawal_deadline")

    refund_pct_after_deadline = _req_num(body, "refund_pct_after_deadline")
    if not (0 <= refund_pct_after_deadline <= 1):
        raise invalid_request("refund_pct_after_deadline must be in [0, 1]")

    attendance_threshold_pct = _req_num(body, "attendance_threshold_pct")
    if not (0 < attendance_threshold_pct <= 100):
        raise invalid_request("attendance_threshold_pct must be in (0, 100]")

    rec = base_record()
    rec.update({
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "member_tuition_cents": member_tuition_cents,
        "non_member_tuition_cents": non_member_tuition_cents,
        "early_bird_pct": early_bird_pct,
        "early_bird_deadline": early_bird_deadline,
        "sibling_discount_pcts": list(sibling_discount_pcts),
        "activity_fee_cents": activity_fee_cents,
        "volunteer_hours_required": volunteer_hours_required,
        "volunteer_buyout_fee_cents": volunteer_buyout_fee_cents,
        "late_fee_pct": late_fee_pct,
        "late_fee_min_balance_cents": late_fee_min_balance_cents,
        "tuition_due_date": tuition_due_date,
        "withdrawal_deadline": withdrawal_deadline,
        "refund_pct_after_deadline": refund_pct_after_deadline,
        "attendance_threshold_pct": attendance_threshold_pct,
        "status": "SETUP",
    })
    store.school_years[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/school-years/<year_id>", methods=["GET"])
def get_school_year(year_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    rec = get_year(year_id)
    return success_object(public(rec))


@bp.route("/school/school-years/<year_id>/open", methods=["POST"])
def open_school_year(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    if year["status"] != "SETUP":
        raise invalid_state("SchoolYear is not in SETUP")
    has_active_plan = any(
        p["school_year_id"] == year_id and p["status"] == "ACTIVE"
        for p in store.security_plans.values()
    )
    if not has_active_plan:
        raise ApiError(ERR_SECURITY_PLAN_NOT_ACTIVE, 409, "No ACTIVE SecurityPlan for the year")
    year["status"] = "OPEN"
    touch(year)
    return success_object(public(year))


@bp.route("/school/school-years/<year_id>/close", methods=["POST"])
def close_school_year(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    if year["status"] != "OPEN":
        raise invalid_state("SchoolYear is not OPEN")

    now_str = store.now_str()

    # 1. Cancel every SCHEDULED session of every section in this year (YEAR_CLOSE)
    for s in store.sessions.values():
        section = store.sections.get(s["section_id"])
        if section and section["school_year_id"] == year_id and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            s["cancel_reason"] = "YEAR_CLOSE"
            touch(s)

    # 2. Volunteer sweep
    for c in list(store.commitments.values()):
        if c["school_year_id"] != year_id:
            continue
        if c["status"] == "OPEN":
            if c["logged_hours"] < c["required_hours"]:
                c["status"] = "DEFAULTED"
                touch(c)
                # create fee-only VOLUNTEER_FEE invoice
                family = store.families.get(c["family_id"])
                inv = base_record()
                inv.update({
                    "family_id": c["family_id"],
                    "school_year_id": year_id,
                    "status": "ISSUED",
                    "kind": "VOLUNTEER_FEE",
                    "line_items": [],
                    "gross_cents": 0,
                    "activity_fee_cents": 0,
                    "award_cents": 0,
                    "assistance_application_id": None,
                    "credit_applied_cents": 0,
                    "total_due_cents": year["volunteer_buyout_fee_cents"],
                    "paid_cents": 0,
                    "late_fees_cents": 0,
                    "balance_cents": year["volunteer_buyout_fee_cents"],
                    "issued_at": now_str,
                    "due_date": year["tuition_due_date"],
                })
                store.invoices[inv["id"]] = inv
                if family:
                    recompute_family_outstanding(family)
                    touch(family)
            else:
                c["status"] = "FULFILLED"
                touch(c)

    # 3. Sections OPEN/FULL -> CLOSED
    for sec in store.sections.values():
        if sec["school_year_id"] == year_id and sec["status"] in ("OPEN", "FULL"):
            sec["status"] = "CLOSED"
            touch(sec)

    # 4. Enrollments REGISTERED/ACTIVE -> COMPLETED
    for e in store.enrollments.values():
        if e["school_year_id"] == year_id and e["status"] in ("REGISTERED", "ACTIVE"):
            e["status"] = "COMPLETED"
            touch(e)

    year["status"] = "CLOSED"
    touch(year)
    return success_object(public(year))


@bp.route("/school/school-years/<year_id>/accrue-late-fees", methods=["POST"])
def accrue_late_fees(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    now = store.now()
    current_date = now.date()
    accrued_ids = []
    total_fees = 0
    touched_families = set()

    for inv in store.invoices.values():
        if inv["school_year_id"] != year_id:
            continue
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            continue
        due = parse_date(inv["due_date"], "due_date")
        eligible = (current_date > due) and (inv["balance_cents"] >= year["late_fee_min_balance_cents"])
        if not eligible:
            continue
        snapshot = inv["balance_cents"]
        fee = round_half_up_cents(Decimal(snapshot) * Decimal(str(year["late_fee_pct"])))
        inv["late_fees_cents"] += fee
        inv["balance_cents"] += fee
        touch(inv)
        accrued_ids.append(inv["id"])
        total_fees += fee
        touched_families.add(inv["family_id"])

    for fid in touched_families:
        family = store.families.get(fid)
        if family:
            recompute_family_outstanding(family)
            touch(family)

    return success_object({
        "accrued_invoice_ids": accrued_ids,
        "total_fees_cents": total_fees,
    })


# ---------------------------------------------------------------------------
# SecurityPlan
# ---------------------------------------------------------------------------

@bp.route("/school/school-years/<year_id>/security-plan", methods=["POST"])
def create_security_plan(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    body = request.get_json(silent=True) or {}
    plan_document = _req_str(body, "plan_document")
    rec = base_record()
    rec.update({
        "school_year_id": year["id"],
        "plan_document": plan_document,
        "status": "DRAFT",
        "approved_at": None,
    })
    store.security_plans[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/school-years/<year_id>/security-plan", methods=["GET"])
def list_security_plans(year_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    year = get_year(year_id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.security_plans.values() if p["school_year_id"] == year["id"]]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(p) for p in page], limit, offset, total)


@bp.route("/school/security-plans/<plan_id>/submit", methods=["POST"])
def submit_security_plan(plan_id):
    require_roles(["SchoolAdmin"])
    plan = get_security_plan(plan_id)
    if plan["status"] != "DRAFT":
        raise invalid_state("SecurityPlan is not in DRAFT")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(public(plan))


@bp.route("/school/security-plans/<plan_id>/approve", methods=["POST"])
def approve_security_plan(plan_id):
    require_roles(["SchoolAdmin"])
    plan = get_security_plan(plan_id)
    if plan["status"] != "SUBMITTED":
        raise invalid_state("SecurityPlan is not in SUBMITTED")
    # supersede other ACTIVE plans for the same year
    for p in store.security_plans.values():
        if (
            p["id"] != plan["id"]
            and p["school_year_id"] == plan["school_year_id"]
            and p["status"] == "ACTIVE"
        ):
            p["status"] = "SUPERSEDED"
            p["approved_at"] = None
            touch(p)
    plan["status"] = "ACTIVE"
    plan["approved_at"] = store.now_str()
    touch(plan)
    return success_object(public(plan))


@bp.route("/school/security-plans/<plan_id>/reject", methods=["POST"])
def reject_security_plan(plan_id):
    require_roles(["SchoolAdmin"])
    plan = get_security_plan(plan_id)
    if plan["status"] != "SUBMITTED":
        raise invalid_state("SecurityPlan is not in SUBMITTED")
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(public(plan))


@bp.route("/school/security-plans/<plan_id>/retire", methods=["POST"])
def retire_security_plan(plan_id):
    require_roles(["SchoolAdmin"])
    plan = get_security_plan(plan_id)
    if plan["status"] != "ACTIVE":
        raise invalid_state("SecurityPlan is not ACTIVE")
    plan["status"] = "SUPERSEDED"
    plan["approved_at"] = None
    touch(plan)
    return success_object(public(plan))


# ---------------------------------------------------------------------------
# CalendarClosure
# ---------------------------------------------------------------------------

@bp.route("/school/school-years/<year_id>/closures", methods=["POST"])
def create_closure(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    body = request.get_json(silent=True) or {}
    start_date = _req_str(body, "start_date")
    end_date = _req_str(body, "end_date")
    reason = _req_str(body, "reason")
    sd = parse_date(start_date, "start_date")
    ed = parse_date(end_date, "end_date")
    if ed < sd:
        raise invalid_request("end_date must be on or after start_date")

    # closed-interval overlap check against existing closures of this year
    for c in store.closures.values():
        if c["school_year_id"] != year_id:
            continue
        csd = parse_date(c["start_date"])
        ced = parse_date(c["end_date"])
        # closed-interval intersection
        if sd <= ced and csd <= ed:
            raise ApiError(ERR_CLOSURE_OVERLAP, 409, "Closure overlaps an existing closure")

    rec = base_record()
    rec.update({
        "school_year_id": year_id,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
    })
    store.closures[rec["id"]] = rec

    # cancel covered SCHEDULED sessions of the year's sections
    affected_sections = set()
    for s in store.sessions.values():
        section = store.sections.get(s["section_id"])
        if not section or section["school_year_id"] != year_id:
            continue
        if s["status"] != "SCHEDULED":
            continue
        sess_d = parse_date(s["session_date"])
        if sd <= sess_d <= ed:
            s["status"] = "CANCELLED"
            s["cancel_reason"] = "CLOSURE"
            touch(s)
            affected_sections.add(s["section_id"])

    for sec_id in affected_sections:
        reevaluate_milestones_for_section(sec_id)

    return success_object(public(rec), status=201)


@bp.route("/school/school-years/<year_id>/closures", methods=["GET"])
def list_closures(year_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    year = get_year(year_id)
    limit, offset = parse_pagination(request.args)
    items = [c for c in store.closures.values() if c["school_year_id"] == year["id"]]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Test-driving clock
# ---------------------------------------------------------------------------

@bp.route("/school/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["SchoolAdmin"])
    body = request.get_json(silent=True) or {}
    to_iso8601 = _req_str(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso8601)
    except Exception:
        raise invalid_request("to_iso8601 must be ISO 8601 datetime")
    from db import fmt_ts
    store.clock.set(dt)
    return success_object({"current_utc": fmt_ts(store.clock.now())})
