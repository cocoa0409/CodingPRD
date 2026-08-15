"""Business logic: calculations (scaffold 1.3), cascades (1.2), sweeps, serializers."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import touch

# Liability-cap constants (calculation "liability_cap")
LIABILITY_MULTIPLIER = 10
MIN_CAP_CENTS = 25000
MAX_CAP_CENTS = 100000
EXTENDED_COVERAGE_RATE = Decimal("0.10")

DEPT_TYPES = ("UTILITY", "CODE_ENFORCEMENT", "PERMIT", "TAX_COLLECTOR")
FINDING_KINDS = ("UNPAID_UTILITY", "CODE_VIOLATION", "OPEN_PERMIT", "TAX_LIEN")
SUBJECT_TYPES = ("SEARCH_ORDER", "RESEARCH_TASK", "ESTOPPEL_ORDER")
DISCREPANCY_TYPES = ("MISSED_ITEM", "BALANCE_MISMATCH", "PAYOFF_MISMATCH", "STALE_ESTOPPEL")
RESOLUTION_OUTCOMES = ("CONFIRMED_CORRECTION", "REJECTED_INVALID", "VOID_ORDER_CANCELLED")


# ---------------------------------------------------------------- calculations

def task_findings_amounts(findings):
    """task_unpaid_balance: round each CODE_VIOLATION accrual half-up FIRST, then sum."""
    total = 0
    violations = 0
    for f in findings:
        amt = f.get("amount_cents", 0)
        if f.get("finding_kind") == "CODE_VIOLATION":
            violations += 1
            dac = f.get("daily_accrual_cents")
            days = f.get("days_outstanding")
            if dac is not None and days is not None:
                accrual = (Decimal(str(dac)) * Decimal(int(days))).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
                amt = amt + int(accrual)
        total += amt
    return total, violations


def task_fee(order, task):
    """fee_charged_cents while COMPLETED; 0 otherwise."""
    if task["status"] != "COMPLETED":
        return 0
    fee = task["fee_base_cents"]
    if order is not None and order["order_class"] == "RUSH":
        fee += task["fee_rush_surcharge_cents"]
    return fee


def order_children(order_id):
    tasks = [t for t in db.research_tasks.values() if t["search_order_id"] == order_id]
    estoppels = [e for e in db.estoppel_orders.values() if e["search_order_id"] == order_id]
    discs = [d for d in db.discrepancies.values() if d["search_order_id"] == order_id]
    dels = [d for d in db.deliveries.values() if d["search_order_id"] == order_id]
    return tasks, estoppels, discs, dels


def order_totals(order):
    """order_total_payoff / order_total_fees / pending claims / confirmed liability."""
    oid = order["id"]
    payoff = 0
    fees = 0
    for t in db.research_tasks.values():
        if t["search_order_id"] != oid:
            continue
        if t["status"] == "COMPLETED":
            payoff += t["unpaid_balance_cents"]
            fees += task_fee(order, t)
    for e in db.estoppel_orders.values():
        if e["search_order_id"] != oid:
            continue
        if e["status"] == "RECEIVED":
            payoff += e["payoff_amount_cents"] or 0
        if e["status"] in ("RECEIVED", "EXPIRED"):
            fees += e["lifetime_fees_cents"]
    claims = sum(
        d["claimed_amount_cents"]
        for d in db.discrepancies.values()
        if d["search_order_id"] == oid and d["status"] in ("OPEN", "UNDER_REVIEW")
    )
    liability = sum(
        d["confirmed_liability_cents"] or 0
        for d in db.discrepancies.values()
        if d["search_order_id"] == oid and d["status"] == "RESOLVED"
    )
    return payoff, fees, claims, liability


def liability_cap_projection(base_fees_cents, extended_coverage):
    """Pinned 5-step evaluation order (calculation "liability_cap")."""
    base = base_fees_cents                                            # step 1
    provisional_cap = max(
        MIN_CAP_CENTS, min(LIABILITY_MULTIPLIER * base, MAX_CAP_CENTS)
    )                                                                # step 2
    if extended_coverage:                                            # step 3
        coverage_fee = int(
            (EXTENDED_COVERAGE_RATE * Decimal(provisional_cap)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    else:
        coverage_fee = 0
    total_with_coverage = base + coverage_fee                        # step 4
    final_cap = max(
        MIN_CAP_CENTS, min(LIABILITY_MULTIPLIER * total_with_coverage, MAX_CAP_CENTS)
    )                                                                # step 5
    return coverage_fee, final_cap


def statutory_due_at(ordered_at, response_days):
    """ordered date + response_days calendar days, at 23:59:59.000Z on the due date."""
    due_date = ordered_at.date() + timedelta(days=response_days)
    return datetime.combine(due_date, time(23, 59, 59, 0), tzinfo=timezone.utc)


def estoppel_valid_through(received_at, validity_days):
    """received date + association.estoppel_validity_days calendar days (ISO date)."""
    return received_at.date() + timedelta(days=validity_days)


def covering_statute(jurisdiction_id, on_date):
    """Half-open window coverage: effective_from <= date < effective_to (null = open)."""
    for s in db.statutes.values():
        if s["jurisdiction_id"] != jurisdiction_id:
            continue
        if s["effective_from"] <= on_date and (
            s["effective_to"] is None or on_date < s["effective_to"]
        ):
            return s
    return None


# ------------------------------------------------------------------ cascades

def spawn_research_task(order, dept):
    t = {
        "id": db.new_id(),
        "search_order_id": order["id"],
        "department_id": dept["id"],
        "dept_type": dept["dept_type"],
        "status": "PENDING",
        "findings": [],
        "findings_recorded": False,
        "unpaid_balance_cents": 0,
        "open_violation_count": 0,
        "fee_base_cents": dept["research_fee_cents"],
        "fee_rush_surcharge_cents": dept["rush_surcharge_cents"],
        "completed_by_user_id": None,
        "unreachable_reason": None,
    }
    db.stamp(t)
    db.research_tasks[t["id"]] = t
    return t


def spawn_estoppel_draft(order, association_id):
    e = {
        "id": db.new_id(),
        "search_order_id": order["id"],
        "association_id": association_id,
        "status": "DRAFT",
        "fee_quoted_cents": None,
        "ordered_at": None,
        "statutory_due_at": None,
        "received_at": None,
        "late_delivery": None,
        "current_fee_cents": 0,
        "lifetime_fees_cents": 0,
        "payoff_amount_cents": None,
        "valid_through": None,
        "renewal_count": 0,
    }
    db.stamp(e)
    db.estoppel_orders[e["id"]] = e
    return e


def revert_order_to_research(order, void_ready=True, supersede_delivered=False, bump=True):
    """Shared VERIFICATION/READY_FOR_DELIVERY/DELIVERED -> RESEARCH_IN_PROGRESS cascade."""
    order["status"] = "RESEARCH_IN_PROGRESS"
    order["payoff_verified_by_user_id"] = None
    order["payoff_verified_at"] = None
    for d in db.deliveries.values():
        if d["search_order_id"] != order["id"]:
            continue
        if void_ready and d["status"] == "READY":
            d["status"] = "VOIDED"
            touch(d)
        elif supersede_delivered and d["status"] in ("DELIVERED", "ACKNOWLEDGED"):
            d["status"] = "SUPERSEDED"
            touch(d)
    if bump:
        touch(order)


def cancel_order_cascade(order):
    """SearchOrder -> CANCELLED cascades (scaffold 1.2)."""
    oid = order["id"]
    for t in db.research_tasks.values():
        if t["search_order_id"] == oid and t["status"] in (
            "PENDING", "IN_PROGRESS", "UNABLE_TO_REACH",
        ):
            t["status"] = "CANCELLED"
            touch(t)
    for e in db.estoppel_orders.values():
        if e["search_order_id"] == oid and e["status"] in ("DRAFT", "ORDERED", "OVERDUE"):
            e["status"] = "CANCELLED"
            touch(e)
    for d in db.discrepancies.values():
        if d["search_order_id"] == oid and d["status"] in ("OPEN", "UNDER_REVIEW"):
            d["status"] = "RESOLVED"
            d["resolution_outcome"] = "VOID_ORDER_CANCELLED"
            d["confirmed_liability_cents"] = 0
            touch(d)
    for d in db.deliveries.values():
        if d["search_order_id"] == oid and d["status"] == "READY":
            d["status"] = "VOIDED"
            touch(d)
    order["status"] = "CANCELLED"
    touch(order)


def estoppel_sweep():
    """Clock-set sweep: ORDERED past due -> OVERDUE; RECEIVED past validity -> EXPIRED."""
    clock_date = db.today()
    for e in list(db.estoppel_orders.values()):
        if e["status"] == "ORDERED" and e["statutory_due_at"] is not None:
            if clock_date > e["statutory_due_at"].date():
                e["status"] = "OVERDUE"
                touch(e)
    for e in list(db.estoppel_orders.values()):
        if e["status"] == "RECEIVED" and e["valid_through"] is not None:
            order = db.search_orders.get(e["search_order_id"])
            if order is None or order["status"] in ("DELIVERED", "CANCELLED"):
                continue
            if clock_date > e["valid_through"]:
                e["status"] = "EXPIRED"
                touch(e)
                # Order payoff drops by payoff_amount_cents (recomputed live).
                if order["status"] in ("VERIFICATION", "READY_FOR_DELIVERY"):
                    revert_order_to_research(order, void_ready=True)
                else:
                    touch(order)


# --------------------------------------------------------------- serializers

def ser_jurisdiction(j):
    return {
        "id": j["id"], "code": j["code"], "name": j["name"],
        "state_code": j["state_code"],
        "rush_daily_capacity": j["rush_daily_capacity"], "status": j["status"],
        "created_at": j["created_at"], "updated_at": j["updated_at"],
        "version": j["version"],
    }


def ser_statute(s):
    return {
        "id": s["id"], "jurisdiction_id": s["jurisdiction_id"],
        "effective_from": s["effective_from"].isoformat(),
        "effective_to": s["effective_to"].isoformat() if s["effective_to"] else None,
        "estoppel_response_days": s["estoppel_response_days"],
        "estoppel_fee_cap_cents": s["estoppel_fee_cap_cents"],
        "estoppel_validity_days": s["estoppel_validity_days"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_department(d):
    return {
        "id": d["id"], "jurisdiction_id": d["jurisdiction_id"],
        "dept_type": d["dept_type"], "name": d["name"],
        "research_fee_cents": d["research_fee_cents"],
        "rush_surcharge_cents": d["rush_surcharge_cents"],
        "supports_rush": d["supports_rush"], "status": d["status"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_association(a):
    return {
        "id": a["id"], "jurisdiction_id": a["jurisdiction_id"], "name": a["name"],
        "management_company": a["management_company"],
        "estoppel_fee_cents": a["estoppel_fee_cents"],
        "estoppel_validity_days": a["estoppel_validity_days"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_order(o):
    payoff, fees, claims, liability = order_totals(o)
    return {
        "id": o["id"], "title_agent_id": o["title_agent_id"],
        "property_address": o["property_address"],
        "parcel_number": o["parcel_number"],
        "association_id": o["association_id"],
        "jurisdiction_id": o["jurisdiction_id"],
        "rush_candidate_jurisdiction_id": o["rush_candidate_jurisdiction_id"],
        "statute_id": o["statute_id"], "order_class": o["order_class"],
        "service_date": o["service_date"].isoformat() if o["service_date"] else None,
        "closing_date": o["closing_date"].isoformat() if o["closing_date"] else None,
        "extended_coverage": o["extended_coverage"], "status": o["status"],
        "research_completed_by_user_id": o["research_completed_by_user_id"],
        "payoff_verified_by_user_id": o["payoff_verified_by_user_id"],
        "payoff_verified_at": db.fmt_ts(o["payoff_verified_at"]) if o["payoff_verified_at"] else None,
        "total_payoff_cents": payoff, "total_fees_cents": fees,
        "pending_claims_cents": claims, "total_liability_cents": liability,
        "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_task(t):
    order = db.search_orders.get(t["search_order_id"])
    return {
        "id": t["id"], "search_order_id": t["search_order_id"],
        "department_id": t["department_id"], "dept_type": t["dept_type"],
        "status": t["status"], "findings": t["findings"],
        "findings_recorded": t["findings_recorded"],
        "unpaid_balance_cents": t["unpaid_balance_cents"],
        "open_violation_count": t["open_violation_count"],
        "fee_base_cents": t["fee_base_cents"],
        "fee_rush_surcharge_cents": t["fee_rush_surcharge_cents"],
        "fee_charged_cents": task_fee(order, t),
        "completed_by_user_id": t["completed_by_user_id"],
        "unreachable_reason": t["unreachable_reason"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_estoppel(e):
    return {
        "id": e["id"], "search_order_id": e["search_order_id"],
        "association_id": e["association_id"], "status": e["status"],
        "fee_quoted_cents": e["fee_quoted_cents"],
        "ordered_at": db.fmt_ts(e["ordered_at"]) if e["ordered_at"] else None,
        "statutory_due_at": db.fmt_ts(e["statutory_due_at"]) if e["statutory_due_at"] else None,
        "received_at": db.fmt_ts(e["received_at"]) if e["received_at"] else None,
        "late_delivery": e["late_delivery"],
        "current_fee_cents": e["current_fee_cents"],
        "lifetime_fees_cents": e["lifetime_fees_cents"],
        "payoff_amount_cents": e["payoff_amount_cents"],
        "valid_through": e["valid_through"].isoformat() if e["valid_through"] else None,
        "renewal_count": e["renewal_count"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_discrepancy(d):
    return {
        "id": d["id"], "search_order_id": d["search_order_id"],
        "subject_type": d["subject_type"], "subject_id": d["subject_id"],
        "discrepancy_type": d["discrepancy_type"],
        "claimed_amount_cents": d["claimed_amount_cents"],
        "description": d["description"],
        "filed_by_user_id": d["filed_by_user_id"],
        "post_delivery": d["post_delivery"], "status": d["status"],
        "resolution_outcome": d["resolution_outcome"],
        "confirmed_amount_cents": d["confirmed_amount_cents"],
        "confirmed_liability_cents": d["confirmed_liability_cents"],
        "resolved_by_user_id": d["resolved_by_user_id"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_delivery(d):
    return {
        "id": d["id"], "search_order_id": d["search_order_id"],
        "status": d["status"],
        "snapshot_payoff_cents": d["snapshot_payoff_cents"],
        "snapshot_fees_cents": d["snapshot_fees_cents"],
        "coverage_fee_cents": d["coverage_fee_cents"],
        "liability_cap_cents": d["liability_cap_cents"],
        "delivered_at": db.fmt_ts(d["delivered_at"]) if d["delivered_at"] else None,
        "delivered_to_agent_id": d["delivered_to_agent_id"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }
