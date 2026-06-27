"""Calculation rules (SCAFFOLD §1.3, PRD §3.4, §3.6, §3.11, §3.13, §3.14).

All monetary amounts are integer cents. Fractional multiplications use
round-half-up to the nearest whole cent (PRD §2.7).
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import db

# --- Constants (SCAFFOLD §1.3) ---
JURISDICTION_PAGE_RATE_CENTS = {
    "FEDERAL": 380,
    "STATE_CA": 325,
    "STATE_NY": 400,
    "STATE_TX": 300,
}
TURNAROUND_MULTIPLIER = {
    "STANDARD": "1.00",
    "EXPEDITE_14": "1.25",
    "EXPEDITE_7": "1.50",
    "EXPEDITE_3": "2.00",
    "DAILY": "3.00",
}
CERTIFICATION_FLAT_CENTS = 2500
TIER2_MARGINAL_PCT = "0.90"
TIER3_MARGINAL_PCT = "0.80"
TIER1_MAX_PAGE = 50
TIER2_MAX_PAGE = 150
EXHIBIT_PAGE_RATE_CENTS = 75
MIN_BILLABLE_HOURS = 2
REALTIME_SURCHARGE = "1.20"


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up (PRD §2.7)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# compute_staffing_posture (PRD §3.4)
# =============================================================================
def required_roles(job):
    roles = {"REPORTER"}
    if job["requires_videographer"]:
        roles.add("VIDEOGRAPHER")
    if job["requires_interpreter"]:
        roles.add("INTERPRETER")
    return roles


def _role_covered(job, assignment):
    """A role counts as covered only if its assignment satisfies the same
    per-role eligibility used at assignment time (PRD §3.4)."""
    if assignment["role"] == "REPORTER" and job["requires_realtime"]:
        resource = db.resources.get(assignment["resource_id"])
        if not resource or not resource["realtime_capable"]:
            return False
    if assignment["role"] == "INTERPRETER":
        resource = db.resources.get(assignment["resource_id"])
        lang = job["interpreter_language"]
        if not resource or lang is None or lang not in resource.get("certifications", []):
            return False
    return True


def compute_staffing_posture(job):
    req = required_roles(job)
    active = [
        a for a in db.assignments.values()
        if a["job_id"] == job["id"] and a["status"] == "ACTIVE"
    ]
    covered = {a["role"] for a in active if _role_covered(job, a)}
    covered &= req  # only required roles count toward coverage
    if req.issubset(covered):
        return "READY"
    if not covered:
        return "UNSTAFFED"
    return "PARTIAL"


# =============================================================================
# compute_appearance_fee (PRD §3.6)
# =============================================================================
def _appearance_fee(role, hourly_cents, start, end, requires_realtime):
    raw_minutes = int((end - start).total_seconds() // 60)
    billable_hours = max(MIN_BILLABLE_HOURS, math.ceil(raw_minutes / 60))
    base = billable_hours * hourly_cents
    if role == "REPORTER" and requires_realtime:
        return round_half_up(Decimal(base) * Decimal(REALTIME_SURCHARGE))
    return base


def appearance_fee_actual(job, resource, role):
    """Authoritative fee frozen at adjournment, from actual_start/actual_end."""
    return _appearance_fee(
        role,
        resource["hourly_appearance_cents"],
        job["actual_start"],
        job["actual_end"],
        job["requires_realtime"],
    )


def appearance_fee_estimate(job, resource, role):
    """Provisional estimate from the scheduled window (PRD §3.6)."""
    return _appearance_fee(
        role,
        resource["hourly_appearance_cents"],
        job["scheduled_start"],
        job["scheduled_end"],
        job["requires_realtime"],
    )


# =============================================================================
# compute_page_charge (PRD §3.11)
# =============================================================================
def compute_page_charge(pages, jurisdiction, turnaround_tier, certified_copy):
    base_rate = JURISDICTION_PAGE_RATE_CENTS[jurisdiction]
    tier1 = min(pages, TIER1_MAX_PAGE)
    tier2 = max(0, min(pages, TIER2_MAX_PAGE) - TIER1_MAX_PAGE)
    tier3 = max(0, pages - TIER2_MAX_PAGE)
    # Per-tier marginal rate rounded to whole cent BEFORE multiplying by tier pages.
    rate2 = round_half_up(Decimal(base_rate) * Decimal(TIER2_MARGINAL_PCT))
    rate3 = round_half_up(Decimal(base_rate) * Decimal(TIER3_MARGINAL_PCT))
    page_base = tier1 * base_rate + tier2 * rate2 + tier3 * rate3
    # Expedite multiplier applied AFTER the tier sum.
    multiplier = TURNAROUND_MULTIPLIER[turnaround_tier]
    page_charge = round_half_up(Decimal(page_base) * Decimal(multiplier))
    # Certified flat fee added AFTER the multiplier (not multiplied).
    if certified_copy:
        page_charge += CERTIFICATION_FLAT_CENTS
    return page_charge


# =============================================================================
# compute_exhibit_charge (PRD §3.13)
# =============================================================================
def compute_exhibit_charge(transcript_order_id):
    total_pages = sum(
        e["page_count"]
        for e in db.exhibits.values()
        if e["transcript_order_id"] == transcript_order_id
    )
    return total_pages * EXHIBIT_PAGE_RATE_CENTS


# =============================================================================
# compute_invoice subtotals (PRD §3.14)
# =============================================================================
def appearance_subtotal(job_id):
    return sum(
        a["appearance_fee_cents"]
        for a in db.assignments.values()
        if a["job_id"] == job_id and a["status"] == "COMPLETED"
    )
