"""Monthly statement derivation stack (PRD §3.8, SCAFFOLD §1.3).

Implements: statement_accrual_cash_totals, management_fee_assessment,
budget_variance, charter_offset, tax_use_allocation.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from util import parse_date, period_bounds
from services.core import current_agreement_for_aircraft


def _round_half_up_cents(value):
    """Round a Decimal to integer cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_statement_fields(st):
    """Compute (in place) every derived figure of a MonthlyStatement."""
    aircraft_id = st["aircraft_id"]
    period = st["period"]
    start, end = period_bounds(period)

    agreement = current_agreement_for_aircraft(aircraft_id)

    # --- expense sets -----------------------------------------------------
    non_void = [
        e for e in db.expenses.values()
        if e["aircraft_id"] == aircraft_id and e["status"] in ("POSTED", "BILLED")
    ]

    def _in_period(date_str):
        if not date_str:
            return False
        d = parse_date(date_str, "date")
        return start <= d < end

    accrual_lines = [e for e in non_void if _in_period(e["service_date"])]
    cash_lines = [e for e in non_void if e["paid_date"] and _in_period(e["paid_date"])]

    accrual_total = sum(e["amount_cents"] for e in accrual_lines)
    cash_total = sum(e["amount_cents"] for e in cash_lines)

    # --- completed trips in period (by completion instant) -----------------
    completed_trips = []
    for t in db.trips.values():
        if t["aircraft_id"] != aircraft_id or t["status"] != "COMPLETED":
            continue
        completed_at = t.get("_completed_at")
        if completed_at is None:
            continue
        comp_date = completed_at.date()
        if start <= comp_date < end:
            completed_trips.append(t)

    # --- charter offset ----------------------------------------------------
    charter_offset = sum(
        (t["owner_credit_cents"] or 0) for t in completed_trips if t["trip_use"] == "CHARTER"
    )

    # --- management fee (evaluation order pinned; fee on pre-fee subtotal) --
    if agreement is not None:
        variable_component = _round_half_up_cents(
            Decimal(str(agreement["variable_fee_pct"])) * Decimal(accrual_total)
        )
        management_fee = agreement["monthly_management_fee_cents"] + variable_component
        tax_method_used = agreement["tax_allocation_method"]
    else:
        management_fee = 0
        tax_method_used = None

    # --- budget variance ----------------------------------------------------
    budget_variance = None
    year = start.year
    for b in db.budgets.values():
        if (b["aircraft_id"] == aircraft_id and b["fiscal_year"] == year
                and b["status"] == "APPROVED"):
            annual_total = (b["fuel_cents"] + b["maintenance_cents"] + b["crew_cents"]
                            + b["hangar_cents"] + b["insurance_cents"] + b["other_cents"])
            monthly_share = _round_half_up_cents(Decimal(annual_total) / Decimal(12))
            budget_variance = accrual_total - monthly_share
            break

    # --- tax split (per-line round half up, then sum) -----------------------
    charter_trips = [t for t in completed_trips if t["trip_use"] == "CHARTER"]
    method = tax_method_used
    if method == "TRIP_LEGS":
        denom = len(completed_trips)
        numer = len(charter_trips)
    else:  # FLIGHT_HOURS (default when method unset)
        denom_hours = sum(Decimal(str(t["block_hours_actual"] or 0)) for t in completed_trips)
        numer_hours = sum(Decimal(str(t["block_hours_actual"] or 0)) for t in charter_trips)
        denom = denom_hours
        numer = numer_hours

    if not denom:
        charter_ratio = Decimal("0")
    else:
        charter_ratio = Decimal(numer) / Decimal(denom)
    owner_ratio = Decimal("1") - charter_ratio

    mixed_lines = [e for e in accrual_lines if e["tax_use"] == "MIXED"]
    mixed_owner_total = 0
    mixed_charter_total = 0
    for e in mixed_lines:
        line_owner = _round_half_up_cents(Decimal(e["amount_cents"]) * owner_ratio)
        line_charter = e["amount_cents"] - line_owner
        mixed_owner_total += line_owner
        mixed_charter_total += line_charter

    st["accrual_total_cents"] = accrual_total
    st["cash_total_cents"] = cash_total
    st["management_fee_cents"] = management_fee
    st["charter_offset_cents"] = charter_offset
    st["budget_variance_cents"] = budget_variance
    st["mixed_owner_share_cents"] = mixed_owner_total
    st["mixed_charter_share_cents"] = mixed_charter_total
    st["tax_method_used"] = tax_method_used
