"""All pure calculations: capped value, exemption stack, tax bill, deferral interest."""

from datetime import date, datetime, timezone
from decimal import Decimal

from config import (
    DISABILITY_FULL,
    GROWTH_CAP,
    HOMESTEAD_CAP_DOLLARS,
    HOMESTEAD_PCT,
    SENIOR_FLAT,
    VETERAN_FLAT,
)
from db import store
from utils import round_half_up


# ---------------------------------------------------------------------------
# Capped Assessed Value
# ---------------------------------------------------------------------------
def compute_capped_value(assessment_rec, property_rec):
    """Returns (capped_value: Decimal, cap_reset_applied: bool, prior_capped_value: Decimal).

    Step 1 — reset detection: first roll OR ownership_change_date inside the roll year.
    Step 2 — growth cap: min(market_value_at_roll, prior_capped_value * (1 + GROWTH_CAP)) rounded.
    """
    prior_id = assessment_rec.get("prior_assessment_id")
    prior_capped = Decimal("0")
    if prior_id is not None:
        prior = store.assessments.get(prior_id)
        if prior is not None and prior.get("capped_value") is not None:
            prior_capped = Decimal(str(prior["capped_value"]))

    market = Decimal(str(assessment_rec["market_value_at_roll"]))
    roll_year = assessment_rec["roll_year"]
    own_change = property_rec.get("ownership_change_date")
    roll_start = datetime(roll_year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    roll_end = datetime(roll_year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    reset = False
    if prior_capped == Decimal("0"):
        reset = True
    elif own_change is not None and roll_start <= own_change <= roll_end:
        reset = True

    if reset:
        capped_value = round_half_up(market, 2)
        cap_reset_applied = True
    else:
        ceiling = round_half_up(prior_capped * (Decimal("1") + GROWTH_CAP), 2)
        capped_value = round_half_up(min(market, ceiling), 2)
        cap_reset_applied = False

    return capped_value, cap_reset_applied, prior_capped


# ---------------------------------------------------------------------------
# Exemption Stack
# ---------------------------------------------------------------------------
EXEMPTION_PRIORITY = ["HOMESTEAD", "SENIOR", "VETERAN", "DISABILITY"]


def compute_exemption_stack(property_id, roll_year, assessment_capped_value, mutate=True):
    """Recompute the exemption stack for (property_id, roll_year).

    Returns (total_exemption_amount: Decimal, layers: dict[type -> dict]).

    When mutate=True, the participating APPROVED ExemptionApplications have their
    approved_amount updated in place (but updated_at / version are NOT touched —
    the stack recompute is a derived projection, not a separate mutation event).
    The PRD says approved_amount is computed at APPROVED time and recomputed on
    revocation; for downstream cascades we use mutate=True from the controllers
    that own the transition. For pure read-only computation pass mutate=False.
    """
    base = Decimal(str(assessment_capped_value)) if assessment_capped_value is not None else Decimal("0")
    total = Decimal("0")
    layers = {}
    # Collect APPROVED applications by type
    approved_by_type = {}
    for rec in store.exemption_applications.values():
        if rec["property_id"] != property_id:
            continue
        if rec["effective_roll_year"] != roll_year:
            continue
        if rec["status"] != "APPROVED":
            continue
        # Only one APPROVED per (type) should exist (uniqueness rule)
        approved_by_type[rec["exemption_type"]] = rec

    for et in EXEMPTION_PRIORITY:
        app = approved_by_type.get(et)
        if app is None:
            continue
        if et == "HOMESTEAD":
            amt = round_half_up(min(HOMESTEAD_PCT * base, HOMESTEAD_CAP_DOLLARS), 2)
        elif et == "SENIOR":
            amt = SENIOR_FLAT
        elif et == "VETERAN":
            amt = VETERAN_FLAT
        else:  # DISABILITY
            owner = store.owners.get(app["owner_id"])
            rating = owner.get("disability_rating", 0) if owner else 0
            if rating >= 70:
                amt = DISABILITY_FULL
            else:
                amt = round_half_up(Decimal("0.5") * DISABILITY_FULL, 2)
        # Floor at base
        amt = min(amt, base)
        if mutate:
            app["approved_amount"] = amt
        layers[et] = {"amount": amt, "application_id": app["id"]}
        base -= amt
        total += amt

    return total, layers


# ---------------------------------------------------------------------------
# Tax Bill Computation
# ---------------------------------------------------------------------------
def compute_tax_bill_fields(bill_rec, *, recompute_stack=True):
    """Recomputes taxable_value, total_exemption_amount, base_tax_amount,
    total_payments_applied, amount_due on the given TaxBill record.

    Does NOT mutate timestamps/version on the bill itself — the caller is
    responsible for bumping those when the recompute is part of a cascade.
    """
    assessment_id = bill_rec.get("assessment_id")
    assessment = store.assessments.get(assessment_id) if assessment_id else None
    capped_value = Decimal(str(assessment["capped_value"])) if assessment and assessment.get("capped_value") is not None else Decimal("0")

    if recompute_stack:
        total_exemption, _ = compute_exemption_stack(
            bill_rec["property_id"], bill_rec["roll_year"], capped_value, mutate=True
        )
    else:
        # Use the already-set approved_amount values without mutating
        total_exemption = Decimal("0")
        # Re-derive in priority order, but read approved_amount as already stored
        approved_by_type = {}
        for rec in store.exemption_applications.values():
            if rec["property_id"] != bill_rec["property_id"]:
                continue
            if rec["effective_roll_year"] != bill_rec["roll_year"]:
                continue
            if rec["status"] != "APPROVED":
                continue
            approved_by_type[rec["exemption_type"]] = rec
        for et in EXEMPTION_PRIORITY:
            app = approved_by_type.get(et)
            if app is None:
                continue
            amt = Decimal(str(app.get("approved_amount", 0)))
            total_exemption += amt

    bill_rec["total_exemption_amount"] = round_half_up(total_exemption, 2)

    taxable_value = round_half_up(capped_value - total_exemption, 2)
    if taxable_value < Decimal("0"):
        taxable_value = Decimal("0.00")
    bill_rec["taxable_value"] = taxable_value

    mill_rate = Decimal(str(bill_rec["mill_rate"]))
    base_tax = round_half_up(taxable_value * mill_rate / Decimal("1000"), 2)
    bill_rec["base_tax_amount"] = base_tax

    total_payments = Decimal("0")
    for p in store.payments.values():
        if p["tax_bill_id"] != bill_rec["id"]:
            continue
        if p["status"] == "APPLIED":
            total_payments += Decimal(str(p["amount"]))
    bill_rec["total_payments_applied"] = round_half_up(total_payments, 2)

    # Deferral accrued interest contribution
    accrued = Decimal("0")
    for d in store.deferral_plans.values():
        if d["tax_bill_id"] != bill_rec["id"]:
            continue
        if d["status"] == "ACTIVE":
            accrued = compute_accrued_interest(d, store.clock.now())
            d["accrued_interest"] = accrued
            break

    amount_due = round_half_up(base_tax - total_payments + accrued, 2)
    if amount_due < Decimal("0"):
        amount_due = Decimal("0.00")
    bill_rec["amount_due"] = amount_due


# ---------------------------------------------------------------------------
# Deferral Interest Accrual
# ---------------------------------------------------------------------------
def compute_accrued_interest(plan_rec, now: datetime) -> Decimal:
    """Compounded daily, rounded once at the end.

    days_elapsed = floor((now - started_at) / 1 day)
    accrued = principal * ((1 + annual/365) ** days_elapsed - 1)
    """
    started = plan_rec.get("started_at")
    if started is None:
        return Decimal("0.00")
    closed = plan_rec.get("closed_at")
    if closed is not None:
        end_time = closed
    else:
        end_time = now
    if end_time < started:
        return Decimal("0.00")
    elapsed_seconds = (end_time - started).total_seconds()
    days = int(elapsed_seconds // 86400)
    if days <= 0:
        return Decimal("0.00")
    principal = Decimal(str(plan_rec["principal_deferred"]))
    annual = Decimal(str(plan_rec["annual_interest_rate"]))
    daily = annual / Decimal("365")
    growth = (Decimal("1") + daily) ** days
    return round_half_up(principal * (growth - Decimal("1")), 2)


# ---------------------------------------------------------------------------
# Age helper
# ---------------------------------------------------------------------------
def owner_age_on_jan1(owner_rec, roll_year: int) -> int:
    from utils import parse_iso_date, age_on
    dob = parse_iso_date(owner_rec["date_of_birth"])
    return age_on(dob, date(roll_year, 1, 1))


def owner_age_today(owner_rec, today: date) -> int:
    from utils import parse_iso_date, age_on
    dob = parse_iso_date(owner_rec["date_of_birth"])
    return age_on(dob, today)
