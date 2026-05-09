"""Fee billing: principal, late-fee accrual, issuance, waiver.

§3.4 fee_principal:
  PER_SQM_MONTHLY  -> base = round(rate * area_sqm, 2)
  FIXED_AMOUNT     -> base = round(rate, 2)
  discount = 0.05 if last 12 consecutive months PAID, else 0.0
  principal = round(base * (1 - discount), 2)

§3.5 fee_late_charge:
  days_overdue = max(0, floor((min(now, payment_freeze_at) - due_date).days))
  raw_late     = round(principal * late_fee_daily_rate * days_overdue, 2)
  cap          = round(principal * late_fee_cap_pct, 2)
  late_fee     = min(raw_late, cap)
  total_due    = round(principal + late_fee, 2)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
from services.common import bump, snapshot, stamp_create
from services.audit import write_audit
from services.voting_status import recompute_for_owner
from utils import (
    days_in_month,
    iso_format,
    parse_iso,
    round2,
    round2_dec,
    to_decimal,
)


# ---------------------------------------------------------------------------
# Principal computation (regular property fee)
# ---------------------------------------------------------------------------
def _has_twelve_consecutive_paid(owner_id: str, period_year: int, period_month: int) -> bool:
    """True iff the owner's properties have 12 consecutive PAID monthly bills
    immediately preceding (period_year, period_month). For each of the 12 prior
    months we require at least one PAID bill to exist for any property of the
    owner; if any month is missing such a bill we return False."""
    owner_property_ids = {
        p["id"] for p in db.properties.values() if p.get("owner_id") == owner_id
    }
    if not owner_property_ids:
        return False

    # Walk back 12 months
    months: list[tuple[int, int]] = []
    y, m = period_year, period_month
    for _ in range(12):
        m -= 1
        if m == 0:
            y -= 1
            m = 12
        months.append((y, m))

    paid_lookup: set[tuple[int, int]] = set()
    for b in db.fee_bills.values():
        if b.get("property_id") in owner_property_ids and b.get("status") == "PAID":
            paid_lookup.add((b["period_year"], b["period_month"]))

    return all(month in paid_lookup for month in months)


def compute_principal(*, rule: dict, prop: dict, owner_id: str,
                      period_year: int, period_month: int) -> float:
    """Returns the principal_amount as a 2-dp float."""
    rate = to_decimal(rule["rate"])
    if rule["kind"] == "PER_SQM_MONTHLY":
        base = round2_dec(rate * to_decimal(prop["area_sqm"]))
    elif rule["kind"] == "FIXED_AMOUNT_MONTHLY":
        base = round2_dec(rate)
    else:
        # Defensive — should be unreachable.
        base = round2_dec(rate)

    discount_pct = Decimal("0.05") if _has_twelve_consecutive_paid(
        owner_id, period_year, period_month
    ) else Decimal("0")
    principal = round2_dec(base * (Decimal("1") - discount_pct))
    return float(principal)


def compute_parking_first_month_principal(*, monthly_fee, started_at: datetime) -> float:
    """Parking variant: principal = round(monthly_fee * (days_remaining/days_in_month), 2)
    where days_remaining = days_in_month - day_of_month(started_at) + 1."""
    fee = to_decimal(monthly_fee)
    dim = days_in_month(started_at.year, started_at.month)
    days_remaining = dim - started_at.day + 1
    ratio = to_decimal(days_remaining) / to_decimal(dim)
    return float(round2_dec(fee * ratio))


# ---------------------------------------------------------------------------
# Bill issuance
# ---------------------------------------------------------------------------
def _due_date_for_period(year: int, month: int) -> datetime:
    last_day = days_in_month(year, month)
    end_of_month = datetime(year, month, last_day, 23, 59, 59, 999_000, tzinfo=timezone.utc)
    return end_of_month + timedelta(days=14)


def issue_bills_for_period(period_year: int, period_month: int) -> list[dict]:
    """Issue one FeeBill per (property, ACTIVE rule) for the given period."""
    issued: list[dict] = []
    active_rules = [r for r in db.fee_billing_rules.values() if r.get("rule_status") == "ACTIVE"]

    # Pre-compute the discount lookup once for this batch: paid_lookup_by_owner
    # maps owner_id -> set of (year, month) for which they have at least one
    # PAID bill on any of their properties. _has_twelve_consecutive_paid would
    # otherwise rebuild this set per bill (O(N²) issuance).
    owner_to_property_ids: dict[str, set[str]] = {}
    for p in db.properties.values():
        owner_to_property_ids.setdefault(p.get("owner_id"), set()).add(p["id"])

    paid_months_by_owner: dict[str, set[tuple[int, int]]] = {}
    for b in db.fee_bills.values():
        if b.get("status") != "PAID":
            continue
        prop = db.properties.get(b.get("property_id"))
        if prop is None:
            continue
        owner_id = prop.get("owner_id")
        paid_months_by_owner.setdefault(owner_id, set()).add(
            (b["period_year"], b["period_month"])
        )

    # 12-month walkback (independent of property iteration).
    months: list[tuple[int, int]] = []
    y, m = period_year, period_month
    for _ in range(12):
        m -= 1
        if m == 0:
            y -= 1
            m = 12
        months.append((y, m))

    for prop in db.properties.values():
        owner_id = prop["owner_id"]
        owner_paid = paid_months_by_owner.get(owner_id, set())
        has_discount = bool(owner_to_property_ids.get(owner_id)) and all(
            month in owner_paid for month in months
        )
        for rule in active_rules:
            # Inline of compute_principal to reuse has_discount.
            rate_d = to_decimal(rule["rate"])
            if rule["kind"] == "PER_SQM_MONTHLY":
                base = round2_dec(rate_d * to_decimal(prop["area_sqm"]))
            else:
                base = round2_dec(rate_d)
            discount_pct = Decimal("0.05") if has_discount else Decimal("0")
            principal = float(round2_dec(base * (Decimal("1") - discount_pct)))
            bill = {
                "property_id": prop["id"],
                "rule_id": rule["id"],
                "period_year": period_year,
                "period_month": period_month,
                "principal_amount": principal,
                "late_fee_amount": 0.0,
                "total_due": principal,
                "due_date": iso_format(_due_date_for_period(period_year, period_month)),
                "status": "OPEN",
                "paid_amount": 0.0,
                "dunning_stage": "NONE",
            }
            stamp_create(bill)
            db.fee_bills[bill["id"]] = bill
            issued.append(bill)
    return issued


def issue_parking_first_bill(*, prop: dict, parking_space: dict, started_at: datetime) -> dict | None:
    """Schedule the first prorated FIXED-parking fee bill at approval time.
    Returns the new bill dict (or None if monthly_fee is zero)."""
    monthly_fee = parking_space.get("monthly_fee", 0)
    if to_decimal(monthly_fee) == 0:
        return None
    principal = compute_parking_first_month_principal(
        monthly_fee=monthly_fee, started_at=started_at
    )
    # The bill mirrors a FIXED_AMOUNT_MONTHLY bill but is not bound to a billing
    # rule (rule_id None); due_date is end-of-month + 14d for the started-at month.
    due_date = _due_date_for_period(started_at.year, started_at.month)
    bill = {
        "property_id": prop["id"],
        "rule_id": None,
        "period_year": started_at.year,
        "period_month": started_at.month,
        "principal_amount": principal,
        "late_fee_amount": 0.0,
        "total_due": principal,
        "due_date": iso_format(due_date),
        "status": "OPEN",
        "paid_amount": 0.0,
        "dunning_stage": "NONE",
    }
    stamp_create(bill)
    db.fee_bills[bill["id"]] = bill
    return bill


def issue_damage_spillover_bill(*, property_id: str, spillover_amount: float) -> dict:
    """Damage spillover: kind=FIXED_AMOUNT_MONTHLY-style bill for the difference,
    due_date = now() + 14d (PRD §3.7)."""
    now = db.now()
    due_date = now + timedelta(days=14)
    principal = round2(spillover_amount)
    bill = {
        "property_id": property_id,
        "rule_id": None,
        "period_year": now.year,
        "period_month": now.month,
        "principal_amount": principal,
        "late_fee_amount": 0.0,
        "total_due": principal,
        "due_date": iso_format(due_date),
        "status": "OPEN",
        "paid_amount": 0.0,
        "dunning_stage": "NONE",
    }
    stamp_create(bill)
    db.fee_bills[bill["id"]] = bill
    return bill


# ---------------------------------------------------------------------------
# Late-fee accrual & total_due refresh
# ---------------------------------------------------------------------------
def _rule_late_fee_params(bill: dict) -> tuple[float, float]:
    """Returns (late_fee_daily_rate, late_fee_cap_pct). Falls back to PRD defaults
    when bill has no associated rule (parking / damage spillover bills)."""
    rule_id = bill.get("rule_id")
    if rule_id and rule_id in db.fee_billing_rules:
        rule = db.fee_billing_rules[rule_id]
        return float(rule.get("late_fee_daily_rate", 0.0005)), float(rule.get("late_fee_cap_pct", 0.30))
    return 0.0005, 0.30


def _floor_days(td: timedelta) -> int:
    """Floor of timedelta to whole days (no negatives)."""
    total_seconds = td.total_seconds()
    if total_seconds < 0:
        return 0
    return int(total_seconds // 86400)


def refresh_late_fee(bill: dict, *, evaluation_instant: datetime | None = None) -> None:
    """Recompute late_fee_amount and total_due in place. No-op for PAID/WAIVED."""
    status = bill.get("status")
    if status in ("PAID", "WAIVED"):
        return  # frozen

    due_date = parse_iso(bill["due_date"], field="due_date")
    eval_instant = evaluation_instant if evaluation_instant is not None else db.now()
    days_overdue = _floor_days(eval_instant - due_date)
    if days_overdue < 0:
        days_overdue = 0

    daily_rate, cap_pct = _rule_late_fee_params(bill)
    principal = to_decimal(bill["principal_amount"])
    raw_late = round2_dec(principal * to_decimal(daily_rate) * to_decimal(days_overdue))
    cap = round2_dec(principal * to_decimal(cap_pct))
    late_fee = raw_late if raw_late < cap else cap
    total = round2_dec(principal + late_fee)

    bill["late_fee_amount"] = float(late_fee)
    bill["total_due"] = float(total)


# ---------------------------------------------------------------------------
# Auto-transitions: OPEN -> OVERDUE, dunning escalation
# ---------------------------------------------------------------------------
def _affected_owner_id(bill: dict) -> str | None:
    prop = db.properties.get(bill.get("property_id"))
    if prop is None:
        return None
    return prop.get("owner_id")


def auto_transition_overdue_and_dunning() -> None:
    """Walk every fee bill: if status==OPEN and now()>due_date and paid<total,
    flip OPEN->OVERDUE; bump dunning if needed; recompute owner voting_status."""
    now = db.now()
    affected_owners: set[str] = set()

    # Sort bills by due_date ascending so cascades are deterministic.
    bills_sorted = sorted(
        db.fee_bills.values(),
        key=lambda b: (b.get("due_date", ""), b.get("created_at", "")),
    )
    for bill in bills_sorted:
        status = bill.get("status")
        if status not in ("OPEN", "OVERDUE"):
            continue
        due_date = parse_iso(bill["due_date"], field="due_date")
        # 1. OPEN -> OVERDUE
        if status == "OPEN" and now > due_date and float(bill.get("paid_amount", 0)) < float(bill.get("total_due", 0)):
            bill["status"] = "OVERDUE"
            refresh_late_fee(bill, evaluation_instant=now)
            if bill.get("dunning_stage") == "NONE":
                bill["dunning_stage"] = "REMINDED"
            bump(bill)
            owner_id = _affected_owner_id(bill)
            if owner_id:
                affected_owners.add(owner_id)
            status = "OVERDUE"  # fall through to dunning

        # 2. Dunning escalation while OVERDUE
        if status == "OVERDUE":
            refresh_late_fee(bill, evaluation_instant=now)
            stage = bill.get("dunning_stage")
            changed = False
            if stage == "REMINDED" and now > due_date + timedelta(days=30):
                bill["dunning_stage"] = "ESCALATED"
                stage = "ESCALATED"
                changed = True
            if stage == "ESCALATED" and now > due_date + timedelta(days=60):
                bill["dunning_stage"] = "LEGAL_NOTICE"
                changed = True
            if changed:
                bump(bill)

    for owner_id in affected_owners:
        recompute_for_owner(owner_id)


# ---------------------------------------------------------------------------
# Waiver
# ---------------------------------------------------------------------------
def waive_bill(bill: dict, *, reason: str) -> dict:
    before = snapshot(bill)
    bill["status"] = "WAIVED"
    # Freeze late fee at its current value (do not reset).
    bump(bill)
    write_audit(
        subject_kind="FEE_BILL",
        subject_id=bill["id"],
        action="BILL_WAIVED",
        before=before,
        after=snapshot(bill),
    )
    owner_id = _affected_owner_id(bill)
    if owner_id:
        recompute_for_owner(owner_id)
    return bill


# ---------------------------------------------------------------------------
# Read-side refresh (PRD §3.5: refresh on every read while OPEN/OVERDUE/PARTIALLY_PAID)
# ---------------------------------------------------------------------------
def read_with_refresh(bill: dict) -> dict:
    if bill.get("status") in ("OPEN", "OVERDUE", "PARTIALLY_PAID"):
        refresh_late_fee(bill)
    return bill
