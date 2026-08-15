"""The withholding waterfall (calc withholding_waterfall, PRD §3.6).

Executed per statement when a payroll run is paid. Six steps:
  1. disposable earnings   DE = gross - mandatory_deductions
  2. protected floor       state-dependent (weekly-normalized or TX hourly)
  3. priority ordering     class rank, then received_at / effective_date /
                           created_at (never the record id)
  4. retroactive proration effective_date strictly inside the period
  5. award pass            min(raw demand, state cap, remaining pool, balance)
                           + CREDITOR non-compete behind CHILD_SUPPORT
  6. employer admin fee    computed last; never reduces awards
"""

from decimal import Decimal

from db import logical_now, next_seq, store
from services import audit
from util import (
    FEDERAL_MINIMUM_WAGE_CENTS,
    PERIOD_WEEKS,
    new_uuid,
    parse_date,
    render_instant,
    rhu,
)

# Withholdable pipeline states (parallel dimension remit_posture must be
# REMITTING as well).
WITHHOLDABLE = {"RECEIVED", "VALIDATED", "EMPLOYEE_NOTIFIED", "ACTIVE", "ANSWER_FILED"}

CLASS_RANK = {
    "CHILD_SUPPORT": 1,
    "FEDERAL_TAX_LEVY": 2,
    "STUDENT_LOAN": 3,
    "CREDITOR": 4,
}


def _touch(rec):
    rec["updated_at"] = render_instant(logical_now())
    rec["version"] += 1


def _period_floor(employee, statement, state_rule):
    """Step 2 — protected floor, rounded half-up to cents before subtraction."""
    if state_rule is None:
        return 0
    if employee["work_state_code"] == "TX":
        # Hourly-test variant: ignores pay frequency and the federal multiplier.
        hours = Decimal(str(statement.get("hours_worked")))
        return rhu(hours * Decimal(state_rule["hourly_floor_cents"]))
    weekly = (
        Decimal(str(state_rule["min_wage_multiplier"]))
        * FEDERAL_MINIMUM_WAGE_CENTS
        * 40
    )
    return rhu(weekly * PERIOD_WEEKS[employee["pay_frequency"]])


def _proration_factor(order, run):
    """Step 4 — factor < 1 only when effective_date falls strictly inside
    the period; the ratio is applied at full precision before any rounding."""
    effective = parse_date(order["effective_date"])
    period_start = parse_date(run["period_start"])
    period_end = parse_date(run["period_end"])
    if period_start < effective <= period_end:
        days_effective = (period_end - max(effective, period_start)).days + 1
        days_period = (period_end - period_start).days + 1
        return Decimal(days_effective) / Decimal(days_period), True
    return Decimal(1), False


def _raw_demand(order, de_cents, factor, prorated):
    model = order["amount_model"]
    if model == "PERCENT_OF_DISPOSABLE":
        # amount_value is basis points: 2500 = 25%.
        return rhu(
            Decimal(de_cents) * Decimal(order["amount_value"]) * factor / Decimal(10000)
        )
    if model == "FIXED_AMOUNT_PER_PERIOD":
        return rhu(Decimal(order["amount_value"]) * factor)
    # LUMP_SUM_BALANCE: full remaining balance, unprorated.
    return order["remaining_balance_cents"]


def _post_event(order, statement, run, amount, proof):
    now = render_instant(logical_now())
    event = {
        "id": new_uuid(),
        "created_at": now,
        "garnishment_order_id": order["id"],
        "employer_id": order["employer_id"],
        "payroll_run_id": run["id"],
        "pay_statement_id": statement["id"],
        "event_type": "WITHHOLD",
        "amount_cents": amount,
        "computation_proof": proof,
        "created_logical_at": now,
        "_seq": next_seq(),
        "_remittance_id": None,
    }
    store.events[event["id"]] = event
    return event


def run_statement_waterfall(statement, run, employee, employer, actor_role, actor_id):
    """Execute the waterfall for one statement; finalize the statement."""
    state_rule = store.state_rules.get(employee["work_state_code"])

    # Step 1 — disposable earnings (always >= 1 given statement bounds).
    de = statement["gross_earnings_cents"] - statement["mandatory_deductions_cents"]

    # Step 2 — protected floor and pool.
    floor = _period_floor(employee, statement, state_rule)
    pool = max(0, de - floor)

    # Step 3 — participants, in priority order.
    period_end = parse_date(run["period_end"])
    participants = [
        o for o in store.orders.values()
        if o["employee_id"] == employee["id"]
        and o["processing_status"] in WITHHOLDABLE
        and o["remit_posture"] == "REMITTING"
        and parse_date(o["effective_date"]) <= period_end
    ]
    participants.sort(
        key=lambda o: (
            CLASS_RANK[o["order_type"]],
            o["received_at"],
            o["effective_date"],
            o["created_at"],
            o["_seq"],
        )
    )

    # Step 5 — award pass.
    remaining_pool = pool
    total_withheld = 0
    awarded_count = 0
    support_awarded = False
    breakdown = []

    for rank, order in enumerate(participants, start=1):
        factor, prorated = _proration_factor(order, run)
        raw = _raw_demand(order, de, factor, prorated)
        cap_fraction = Decimal(str(state_rule["caps"][order["order_type"]])) if state_rule else Decimal(0)
        cap = rhu(Decimal(de) * cap_fraction)
        balance_before = order["remaining_balance_cents"]

        if order["order_type"] == "CREDITOR" and support_awarded:
            # CREDITOR non-compete: a CHILD_SUPPORT award this pass blocks
            # every creditor order outright.
            breakdown.append({
                "order_id": order["id"],
                "awarded_cents": 0,
                "basis": "BLOCKED_BY_SUPPORT",
                "note": "creditor non-compete: a child support order was awarded this pass",
                "disposable_earnings_cents": de,
                "floor_cents": floor,
                "pool_cents": pool,
            })
            continue

        award = min(raw, cap, remaining_pool, balance_before)

        if award <= 0:
            if remaining_pool <= 0:
                basis, note = "CAPPED_BY_POOL", "withholding pool exhausted"
            elif cap <= 0:
                basis, note = "CAPPED_BY_STATE", "state cap allows no withholding"
            elif raw <= 0:
                basis = "PRORATED" if prorated else "FULL"
                note = "demand rounds to zero"
            else:
                basis, note = "CAPPED_BY_BALANCE", "no remaining balance"
            breakdown.append({
                "order_id": order["id"],
                "awarded_cents": 0,
                "basis": basis,
                "note": note,
                "disposable_earnings_cents": de,
                "floor_cents": floor,
                "pool_cents": pool,
            })
            continue

        if award == balance_before:
            basis, note = "FINAL_PARTIAL", "final dollar withheld; order satisfied"
        elif award == raw:
            basis = "PRORATED" if prorated else "FULL"
            note = "full demand awarded" if not prorated else "prorated demand awarded"
        elif award == cap:
            basis, note = "CAPPED_BY_STATE", "limited by state cap"
        elif award == remaining_pool:
            basis, note = "CAPPED_BY_POOL", "limited by remaining pool"
        else:
            basis, note = "CAPPED_BY_BALANCE", "limited by remaining balance"

        proof = {
            "disposable_earnings_cents": de,
            "pool_cents": pool,
            "cap_fraction": float(cap_fraction),
            "cap_cents": cap,
            "floor_cents": floor,
            "rank": rank,
            "basis": basis,
        }
        event = _post_event(order, statement, run, award, proof)

        order["withheld_cents"] += award
        order["remaining_balance_cents"] = (
            order["total_balance_cents"] - order["withheld_cents"] + order["refunded_cents"]
        )
        _touch(order)

        remaining_pool -= award
        total_withheld += award
        awarded_count += 1
        if order["order_type"] == "CHILD_SUPPORT":
            support_awarded = True

        if award == balance_before:
            # Bubble-up auto transition: ACTIVE -> SATISFIED, posture CLOSED.
            order["processing_status"] = "SATISFIED"
            order["remit_posture"] = "CLOSED"
            order["hold_reason"] = None
            _touch(order)
            audit.append_audit(
                order["employer_id"], "GarnishmentOrder", order["id"],
                "order.satisfy",
                details={
                    "payroll_run_id": run["id"],
                    "pay_statement_id": statement["id"],
                    "withholding_event_id": event["id"],
                    "awarded_cents": award,
                },
                actor_role="SYSTEM", actor_id="system",
            )

        breakdown.append({
            "order_id": order["id"],
            "awarded_cents": award,
            "basis": basis,
            "note": note,
            "disposable_earnings_cents": de,
            "floor_cents": floor,
            "pool_cents": pool,
        })

    # Step 6 — employer administrative fee, computed last; never reduces awards.
    if employer["administrative_fee_policy"] == "PER_ORDER":
        fee = employer["admin_fee_cents"] * awarded_count
        if state_rule is not None and state_rule["fee_deductible_from_wages"]:
            if fee > de - total_withheld:
                fee = de - total_withheld  # clip: net pay lands at exactly 0
            net_pay = de - total_withheld - fee
        else:
            net_pay = de - total_withheld  # fee recorded, borne by employer
    else:
        fee = 0
        net_pay = de - total_withheld

    statement["total_withheld_cents"] = total_withheld
    statement["total_admin_fee_cents"] = fee
    statement["net_pay_cents"] = net_pay
    # PRD §3.6: computation_breakdown preserves the per-order allocation trace
    # as entries of order_id, awarded_cents, basis, and note (each entry also
    # carries the statement-level allocation context captured at award time).
    statement["computation_breakdown"] = breakdown
    _touch(statement)
