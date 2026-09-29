"""Settlement: the append-only ledger, direct payments, installment plans and
the community-service alternative."""

from flask import Blueprint

import calc
import cascade
import serial
from core import (ApiError, authorize, base_record, body, db, days, fk, lookup,
                  opt_bool, ordered, page, pagination, query_filter, req_int,
                  req_str, respond_object, touch)

bp = Blueprint("settlement", __name__)

PLAN_READ_ROLES = ("EnforcementPlanner", "Rider", "HearingOfficer", "AppealsBoardMember")
SERVICE_READ_ROLES = PLAN_READ_ROLES


def _active_plans(citation_id):
    return [p for p in db.plans.values()
            if p["citation_id"] == citation_id and p["status"] == "ACTIVE"]


def _active_services(citation_id):
    return [s for s in db.services.values()
            if s["citation_id"] == citation_id and s["status"] == "ACTIVE"]


# ---------------------------------------------------------------------------
# Direct payment (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.post("/citations/<citation_id>/payments")
def pay_citation(citation_id):
    actor = authorize("Rider", "EnforcementPlanner")
    payload = body()
    amount_cents = req_int(payload, "amount_cents")
    citation = lookup(db.citations, citation_id, "ERR_CITATION_NOT_FOUND")

    if actor.is_rider and actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may pay this citation.")
    if citation["adjudication_status"] not in ("ISSUED", "UPHELD", "REDUCED"):
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s; settlement requires a live citation."
                       % citation["adjudication_status"])
    if citation["settlement_status"] != "OUTSTANDING":
        raise ApiError("ERR_SETTLEMENT_STATUS_INVALID",
                       "Settlement status is %s, not OUTSTANDING."
                       % citation["settlement_status"])

    calc.refresh_citation_money(citation)
    outstanding = citation["outstanding_balance_cents"]
    if amount_cents <= 0 or amount_cents > outstanding:
        raise ApiError("ERR_PAYMENT_AMOUNT_INVALID",
                       "amount_cents must be > 0 and <= the outstanding balance.")
    if outstanding <= 0:
        raise ApiError("ERR_NOTHING_OUTSTANDING", "Nothing is left to pay.")

    payment = cascade.append_payment(citation["id"], "DIRECT", amount_cents)
    calc.refresh_citation_money(citation)
    if citation["outstanding_balance_cents"] == 0:
        citation["settlement_status"] = "SATISFIED"
        citation["outstanding_balance_cents"] = 0
    touch(citation)
    return respond_object(serial.payment_out(payment), 201)


# ---------------------------------------------------------------------------
# Installment plans (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.post("/payment-plans")
def open_plan():
    actor = authorize("Rider", "EnforcementPlanner")
    payload = body()
    req_str(payload, "citation_id", min_len=1)
    installment_count = req_int(payload, "installment_count")
    down_payment_cents = req_int(payload, "down_payment_cents")
    expected_citation_version = req_int(payload, "expected_citation_version")
    supersede_alternative = opt_bool(payload, "supersede_alternative", False)

    citation = fk(payload, "citation_id", db.citations, "ERR_CITATION_NOT_FOUND")
    if expected_citation_version != citation["version"]:
        raise ApiError("ERR_STALE_CITATION_VERSION",
                       "expected_citation_version %d does not match the citation's version %d."
                       % (expected_citation_version, citation["version"]))
    if actor.is_rider and actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may open a plan on this citation.")
    if citation["adjudication_status"] not in ("ISSUED", "UPHELD", "REDUCED"):
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s; settlement requires a live citation."
                       % citation["adjudication_status"])
    if citation["settlement_status"] not in ("OUTSTANDING", "SERVICE_ACTIVE"):
        raise ApiError("ERR_SETTLEMENT_STATUS_INVALID",
                       "Settlement status is %s, not OUTSTANDING."
                       % citation["settlement_status"])

    live_plans = _active_plans(citation["id"])
    live_services = _active_services(citation["id"])
    if (live_plans or live_services) and not supersede_alternative:
        raise ApiError("ERR_ALTERNATIVE_ALREADY_ACTIVE",
                       "A live settlement alternative exists; pass supersede_alternative.")
    if not (calc.PLAN_MIN_INSTALLMENTS <= installment_count <= calc.PLAN_MAX_INSTALLMENTS):
        raise ApiError("ERR_INSTALLMENT_COUNT_OUT_OF_RANGE",
                       "installment_count must be between 2 and 6.")

    calc.refresh_citation_money(citation)
    balance = citation["outstanding_balance_cents"]
    if down_payment_cents < calc.minimum_down_payment_cents(balance):
        raise ApiError("ERR_DOWN_PAYMENT_BELOW_MINIMUM",
                       "The down payment must be at least 10 percent of the balance.")
    if down_payment_cents >= balance:
        raise ApiError("ERR_DOWN_PAYMENT_EXCEEDS_BALANCE",
                       "The down payment must be strictly below the outstanding balance.")

    financed = balance - down_payment_cents
    base, final = calc.plan_schedule(financed, installment_count)
    plan = base_record()
    plan.update({
        "citation_id": citation["id"],
        "installment_count": installment_count,
        "down_payment_cents": down_payment_cents,
        "financed_cents": financed,
        "base_installment_cents": base,
        "final_installment_cents": final,
        "first_due_at": plan["created_at"] + days(calc.INSTALLMENT_INTERVAL_DAYS),
        "installments_paid_count": 0,
        "missed_installment_count": 0,
        "remaining_balance_cents": financed,
        "status": "ACTIVE",
    })
    db.plans[plan["id"]] = plan

    for superseded in live_services:
        superseded["status"] = "FORFEITED"
        touch(superseded)
    for superseded in live_plans:
        superseded["status"] = "CANCELLED"
        touch(superseded)

    if down_payment_cents > 0:
        cascade.append_payment(citation["id"], "DOWN_PAYMENT", down_payment_cents,
                               plan_id=plan["id"])
    citation["settlement_status"] = "PLAN_ACTIVE"
    calc.refresh_citation_money(citation)
    touch(citation)
    return respond_object(serial.plan_out(plan), 201)


@bp.post("/payment-plans/<plan_id>/installments")
def pay_installment(plan_id):
    actor = authorize("Rider", "EnforcementPlanner")
    payload = body()
    amount_cents = req_int(payload, "amount_cents")
    plan = lookup(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    citation = db.citations[plan["citation_id"]]

    if actor.is_rider and actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may pay this plan.")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Plan is %s, not ACTIVE." % plan["status"])

    calc.refresh_plan_counters(plan)
    expected = calc.next_installment_amount(plan)
    if amount_cents != expected:
        raise ApiError("ERR_PAYMENT_AMOUNT_INVALID",
                       "The next scheduled installment is %d cents." % expected)

    payment = cascade.append_payment(citation["id"], "PLAN_INSTALLMENT", amount_cents,
                                     plan_id=plan["id"])
    calc.refresh_plan_counters(plan)
    calc.refresh_citation_money(citation)
    if (plan["installments_paid_count"] >= plan["installment_count"]
            and plan["remaining_balance_cents"] == 0):
        plan["status"] = "COMPLETED"
        plan["remaining_balance_cents"] = 0
        citation["settlement_status"] = "SATISFIED"
        citation["outstanding_balance_cents"] = 0
    touch(plan)
    touch(citation)
    return respond_object(serial.payment_out(payment), 201)


@bp.post("/payment-plans/<plan_id>/assess-delinquency")
def assess_delinquency(plan_id):
    authorize("EnforcementPlanner")
    plan = lookup(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "Plan is %s, not ACTIVE." % plan["status"])
    calc.refresh_plan_counters(plan)
    missed = calc.missed_installments(plan, db.now())
    changed = missed != plan["missed_installment_count"]
    plan["missed_installment_count"] = missed
    if missed >= calc.PLAN_DEFAULT_MISSED_THRESHOLD:
        plan["status"] = "DEFAULTED"
        touch(plan)
        citation = db.citations[plan["citation_id"]]
        if citation["settlement_status"] == "PLAN_ACTIVE":
            citation["settlement_status"] = "OUTSTANDING"
            calc.refresh_citation_money(citation)
            touch(citation)
    elif changed:
        touch(plan)
    return respond_object(serial.plan_out(plan))


@bp.get("/payment-plans/<plan_id>")
def get_plan(plan_id):
    authorize(*PLAN_READ_ROLES)
    plan = lookup(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    return respond_object(serial.plan_out(plan))


@bp.get("/payment-plans")
def list_plans():
    authorize(*PLAN_READ_ROLES)
    limit, offset = pagination()
    citation_id = query_filter("citation_id")
    status = query_filter("status")
    rows = [p for p in db.plans.values()
            if (citation_id is None or p["citation_id"] == citation_id)
            and (status is None or p["status"] == status)]
    return page(ordered(rows), limit, offset, serial.plan_out)


@bp.get("/payment-plans/<plan_id>/payments")
def list_plan_payments(plan_id):
    authorize(*PLAN_READ_ROLES)
    limit, offset = pagination()
    plan = lookup(db.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    rows = ordered([p for p in db.payments.values() if p["plan_id"] == plan["id"]])
    return page(rows, limit, offset, serial.payment_out)


# ---------------------------------------------------------------------------
# Community service (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.post("/community-service-assignments")
def open_service():
    actor = authorize("Rider", "EnforcementPlanner")
    payload = body()
    req_str(payload, "citation_id", min_len=1)
    partner_org_name = req_str(payload, "partner_org_name", min_len=1)
    expected_citation_version = req_int(payload, "expected_citation_version")

    citation = fk(payload, "citation_id", db.citations, "ERR_CITATION_NOT_FOUND")
    if expected_citation_version != citation["version"]:
        raise ApiError("ERR_STALE_CITATION_VERSION",
                       "expected_citation_version %d does not match the citation's version %d."
                       % (expected_citation_version, citation["version"]))
    if actor.is_rider and actor.user_id != citation["rider_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "Only the cited rider may open service on this citation.")
    if citation["adjudication_status"] not in ("ISSUED", "UPHELD", "REDUCED"):
        raise ApiError("ERR_CITATION_STATUS_INVALID",
                       "Citation is %s; settlement requires a live citation."
                       % citation["adjudication_status"])
    if citation["settlement_status"] != "OUTSTANDING":
        raise ApiError("ERR_SETTLEMENT_STATUS_INVALID",
                       "Settlement status is %s, not OUTSTANDING."
                       % citation["settlement_status"])
    if _active_plans(citation["id"]) or _active_services(citation["id"]):
        raise ApiError("ERR_ALTERNATIVE_ALREADY_ACTIVE",
                       "A live settlement alternative already exists on this citation.")

    calc.refresh_citation_money(citation)
    balance = citation["outstanding_balance_cents"]
    if balance <= 0:
        raise ApiError("ERR_NOTHING_OUTSTANDING", "Nothing is left to work off.")

    assignment = base_record()
    assignment.update({
        "citation_id": citation["id"],
        "partner_org_name": partner_org_name,
        "required_hours": calc.required_service_hours(balance),
        "hours_completed": 0,
        "credited_cents": 0,
        "status": "ACTIVE",
    })
    db.services[assignment["id"]] = assignment
    citation["settlement_status"] = "SERVICE_ACTIVE"
    touch(citation)
    return respond_object(serial.service_out(assignment), 201)


@bp.post("/community-service-assignments/<assignment_id>/log-hours")
def log_hours(assignment_id):
    authorize("EnforcementPlanner")
    payload = body()
    if "hours" not in payload or payload["hours"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'hours' is required.")
    hours = payload["hours"]
    assignment = lookup(db.services, assignment_id, "ERR_SERVICE_ASSIGNMENT_NOT_FOUND")
    if assignment["status"] != "ACTIVE":
        raise ApiError("ERR_SERVICE_NOT_ACTIVE",
                       "Assignment is %s, not ACTIVE." % assignment["status"])
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        raise ApiError("ERR_INVALID_SERVICE_HOURS",
                       "hours must be a whole number of at least 1.")

    citation = db.citations[assignment["citation_id"]]
    calc.refresh_citation_money(citation)
    credit = calc.service_credit_for_hours(hours, citation["outstanding_balance_cents"])
    if credit > 0:
        cascade.append_payment(citation["id"], "SERVICE_CREDIT", credit,
                               hours_credited=hours)
    assignment["hours_completed"] = assignment["hours_completed"] + hours
    assignment["credited_cents"] = calc.service_credit_cents_for_citation(citation["id"])
    calc.refresh_citation_money(citation)
    if (assignment["hours_completed"] >= assignment["required_hours"]
            or citation["outstanding_balance_cents"] == 0):
        assignment["status"] = "COMPLETED"
        citation["settlement_status"] = "SATISFIED"
        citation["outstanding_balance_cents"] = 0
    touch(assignment)
    touch(citation)
    return respond_object(serial.service_out(assignment))


@bp.get("/community-service-assignments/<assignment_id>")
def get_service(assignment_id):
    authorize(*SERVICE_READ_ROLES)
    assignment = lookup(db.services, assignment_id, "ERR_SERVICE_ASSIGNMENT_NOT_FOUND")
    return respond_object(serial.service_out(assignment))


@bp.get("/community-service-assignments")
def list_services():
    authorize(*SERVICE_READ_ROLES)
    limit, offset = pagination()
    citation_id = query_filter("citation_id")
    status = query_filter("status")
    rows = [s for s in db.services.values()
            if (citation_id is None or s["citation_id"] == citation_id)
            and (status is None or s["status"] == status)]
    return page(ordered(rows), limit, offset, serial.service_out)
