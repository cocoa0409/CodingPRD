"""Correction execution: distribution waterfall, QNEC allocation,
recharacterization, excise tax and gap-period income (PRD §3.7)."""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import clock, store
from services.common import bump, employees_of_year, fmt_date, new_entity

EXCISE_RATE = Decimal("0.10")
DEEMED_EARNINGS_RATE = Decimal("0.07")
DAY_COUNT = Decimal("365")


def compute_deadline_date(py):
    """12 calendar months after plan year end (2026-12-31 -> 2027-12-31)."""
    year_end = date.fromisoformat(py["year_end"])
    try:
        deadline = year_end.replace(year=year_end.year + 1)
    except ValueError:
        deadline = year_end.replace(year=year_end.year + 1, day=28)
    return deadline


def apply_execute_side_effects(correction):
    """Apply the correction method; compute excise and gap-period income."""
    py = store.plan_years[correction["plan_year_id"]]
    now = clock.now()
    correction["executed_at"] = clock.now_iso()
    executed_date = now.date()
    year_end = date.fromisoformat(py["year_end"])
    deadline = date.fromisoformat(correction["deadline_date"])

    ctype = correction["correction_type"]
    if ctype == "CORRECTIVE_DISTRIBUTION":
        _distribution_waterfall(correction)
        days = max(0, (executed_date - year_end).days)
        gap = (Decimal(correction["amount_cents"]) * DEEMED_EARNINGS_RATE
               * Decimal(days) / DAY_COUNT)
        correction["gap_period_income_cents"] = int(
            gap.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if executed_date <= deadline:
            correction["excise_tax_cents"] = 0
            correction["excise_status"] = "NOT_ASSESSED"
        else:
            excise = (Decimal(correction["amount_cents"]) * EXCISE_RATE)
            correction["excise_tax_cents"] = int(
                excise.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            correction["excise_status"] = "ASSESSED"
    elif ctype == "QNEC_CONTRIBUTION":
        _qnec_allocation(correction, py)
    elif ctype == "RECHARACTERIZATION":
        _recharacterize(correction)
    elif ctype == "QMAC_REALLOCATION":
        _qmac_reallocation(correction)
    # PLAN_AMENDMENT_RETRO: no contribution ledger movement.

    correction["status"] = "EXECUTED"
    bump(correction)


def _target_contributions(correction, types, statuses):
    contribs = [c for c in store.contributions.values()
                if c["census_employee_id"] == correction["target_census_employee_id"]
                and c["contribution_type"] in types
                and c["status"] in statuses]
    contribs.sort(key=lambda c: (c["contribution_date"], c["created_at"], c["id"]))
    return contribs


def _distribution_waterfall(correction):
    """Oldest contribution_date first (tie-break created_at ASC); the final
    selected contribution may split, leaving a RECHARACTERIZED remainder."""
    remaining = correction["amount_cents"]
    for c in _target_contributions(correction, ("ELECTIVE_DEFERRAL",), ("POSTED",)):
        if remaining <= 0:
            break
        if c["amount_cents"] <= remaining:
            remaining -= c["amount_cents"]
            c["status"] = "DISTRIBUTED"
            bump(c)
        else:
            split_off = c["amount_cents"] - remaining
            c["amount_cents"] = remaining
            c["status"] = "DISTRIBUTED"
            bump(c)
            remainder = new_entity({
                "census_employee_id": c["census_employee_id"],
                "contribution_type": c["contribution_type"],
                "amount_cents": split_off,
                "contribution_date": c["contribution_date"],
                "status": "RECHARACTERIZED",
            })
            store.contributions[remainder["id"]] = remainder
            remaining = 0


def _qnec_allocation(correction, py):
    """Plan-wide QNEC: equal dollars per NHCE, remainder cents to the
    earliest-created NHCE (created_at ASC). Creates one QNEC contribution row
    for the correction amount allocated across the cohort."""
    nhce = [e for e in employees_of_year(py["id"]) if e["hce_status"] == "NHCE"]
    nhce.sort(key=lambda e: (e["created_at"], e["id"]))
    if not nhce:
        return
    per_share = correction["amount_cents"] // len(nhce)
    remainder = correction["amount_cents"] - per_share * len(nhce)
    for index, e in enumerate(nhce):
        share = per_share + (remainder if index == 0 else 0)
        if share <= 0:
            continue
        row = new_entity({
            "census_employee_id": e["id"],
            "contribution_type": "QNEC",
            "amount_cents": share,
            "contribution_date": py["year_end"],
            "status": "POSTED",
        })
        store.contributions[row["id"]] = row


def _recharacterize(correction):
    """Move POSTED ELECTIVE_DEFERRAL to RECHARACTERIZED and create a sibling
    MATCH contribution for the recharacterized amount."""
    remaining = correction["amount_cents"]
    for c in _target_contributions(correction, ("ELECTIVE_DEFERRAL",), ("POSTED",)):
        if remaining <= 0:
            break
        moved = min(c["amount_cents"], remaining)
        c["status"] = "RECHARACTERIZED"
        bump(c)
        sibling = new_entity({
            "census_employee_id": c["census_employee_id"],
            "contribution_type": "MATCH",
            "amount_cents": moved,
            "contribution_date": c["contribution_date"],
            "status": "POSTED",
        })
        store.contributions[sibling["id"]] = sibling
        remaining -= moved


def _qmac_reallocation(correction):
    """QMAC reallocation: move POSTED MATCH amounts into QMAC for the target."""
    remaining = correction["amount_cents"]
    for c in _target_contributions(correction, ("MATCH",), ("POSTED",)):
        if remaining <= 0:
            break
        moved = min(c["amount_cents"], remaining)
        if moved == c["amount_cents"]:
            c["contribution_type"] = "QMAC"
            bump(c)
        else:
            c["amount_cents"] = c["amount_cents"] - moved
            bump(c)
            sibling = new_entity({
                "census_employee_id": c["census_employee_id"],
                "contribution_type": "QMAC",
                "amount_cents": moved,
                "contribution_date": c["contribution_date"],
                "status": "POSTED",
            })
            store.contributions[sibling["id"]] = sibling
        remaining -= moved


def assess_excise_at_filing(py):
    """Filing settles excise on late EXECUTED corrections not yet PAID."""
    for correction in store.corrections.values():
        if correction["plan_year_id"] != py["id"]:
            continue
        if correction["status"] != "EXECUTED":
            continue
        if correction["correction_type"] != "CORRECTIVE_DISTRIBUTION":
            continue
        if correction["excise_status"] == "PAID":
            continue
        deadline = date.fromisoformat(correction["deadline_date"])
        executed_date = date.fromisoformat(correction["executed_at"][:10])
        if executed_date > deadline:
            excise = Decimal(correction["amount_cents"]) * EXCISE_RATE
            correction["excise_tax_cents"] = int(
                excise.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            correction["excise_status"] = "ASSESSED"
            bump(correction)


def distributable_balance_cents(emp_id):
    """Sum of the target employee's POSTED ELECTIVE_DEFERRAL contributions."""
    total = 0
    for c in store.contributions.values():
        if (c["census_employee_id"] == emp_id
                and c["contribution_type"] == "ELECTIVE_DEFERRAL"
                and c["status"] == "POSTED"):
            total += c["amount_cents"]
    return total
