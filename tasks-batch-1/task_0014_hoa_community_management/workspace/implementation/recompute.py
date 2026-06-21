"""Derived-field recomputation and cascading side effects.

Implements:
  - late_fee_accrual (chronological per-cycle floor)
  - Property.account_balance_cents rollup
  - Property.compliance_posture rollup
  - Auto Lien filing cascade when threshold breached
  - DUE -> OVERDUE clock-driven recomputation
"""
from __future__ import annotations

import datetime
import math

import db


# ---------------------------------------------------------------------------
# Late-fee accrual — authoritative chronological per-cycle variant
# ---------------------------------------------------------------------------
def _elapsed_days(now: datetime.datetime, due: datetime.datetime) -> int:
    delta = now - due
    return math.floor(delta.total_seconds() / 86400)


def compute_late_fee_chronological(principal_cents: int,
                                   due_date: datetime.datetime,
                                   community: dict,
                                   as_of: datetime.datetime) -> int:
    """Per-cycle floor, then sum.

    cycles = 0 when elapsed_days < grace
    cycles = 1 + floor((elapsed_days - grace) / grace) otherwise
    per_cycle = late_fee_flat_cents + floor(principal * pct_bps / 10000)
    """
    grace = int(community["late_fee_grace_days"])
    elapsed = _elapsed_days(as_of, due_date)
    if elapsed < grace:
        return 0
    cycles = 1 + ((elapsed - grace) // grace)
    flat = int(community["late_fee_flat_cents"])
    pct_bps = int(community["late_fee_pct_bps"])
    per_cycle_pct = (principal_cents * pct_bps) // 10000  # floor per cycle
    per_cycle = flat + per_cycle_pct
    return per_cycle * cycles


def compute_late_fee_projection(principal_cents: int,
                                due_date: datetime.datetime,
                                community: dict,
                                as_of: datetime.datetime) -> int:
    """Forward-looking variant — ceil cycles, floor only at the very end.

    Per PRD §3.3: ceil(elapsed_days / grace) inclusive of the partial cycle.
    """
    grace = int(community["late_fee_grace_days"])
    elapsed = _elapsed_days(as_of, due_date)
    if elapsed < grace:
        return 0
    # ceil(elapsed / grace) -- inclusive of partial cycle
    cycles = math.ceil(elapsed / grace)
    flat = int(community["late_fee_flat_cents"])
    pct_bps = int(community["late_fee_pct_bps"])
    # Sum exact fractional cents, floor once at the end
    total_pct = (principal_cents * pct_bps * cycles) / 10000
    total_flat = flat * cycles
    total = math.floor(total_flat + total_pct)
    return int(total)


# ---------------------------------------------------------------------------
# Assessment derived fields
# ---------------------------------------------------------------------------
def recompute_assessment_paid_outstanding(assessment: dict):
    """Recompute paid_cents from APPLIED payments and refresh outstanding."""
    aid = assessment["id"]
    paid = 0
    for p in db.payment_applications.values():
        if p["assessment_id"] == aid and p["state"] == "APPLIED":
            paid += int(p["amount_cents"])
    assessment["paid_cents"] = paid
    principal = int(assessment["principal_cents"])
    late = int(assessment.get("late_fee_cents", 0))
    outstanding = max(0, principal + late - paid)
    assessment["outstanding_cents"] = outstanding


def maybe_transition_to_paid(assessment: dict):
    """If outstanding_cents == 0 and the assessment is in DUE or OVERDUE,
    transition to PAID."""
    if assessment["status"] in {"DUE", "OVERDUE"} and assessment["outstanding_cents"] == 0:
        assessment["status"] = "PAID"


def maybe_revert_from_paid(assessment: dict):
    """If a reversal makes outstanding_cents > 0 again on a PAID assessment,
    revert to DUE/OVERDUE based on the clock."""
    if assessment["status"] != "PAID":
        return
    if assessment["outstanding_cents"] <= 0:
        return
    community = _find_community_for_assessment(assessment)
    if community is None:
        assessment["status"] = "DUE"
        return
    due_date = db.parse_iso(assessment["due_date"])
    now = db.get_current_utc()
    grace = int(community["late_fee_grace_days"])
    elapsed = _elapsed_days(now, due_date)
    if elapsed > grace:
        assessment["status"] = "OVERDUE"
    else:
        assessment["status"] = "DUE"


def _find_community_for_assessment(assessment: dict) -> dict | None:
    prop = db.properties.get(assessment["property_id"])
    if prop is None:
        return None
    return db.communities.get(prop["community_id"])


# ---------------------------------------------------------------------------
# Property derived fields
# ---------------------------------------------------------------------------
def recompute_property_account_balance(prop: dict):
    """Sum outstanding_cents across this property's DUE/OVERDUE assessments."""
    pid = prop["id"]
    total = 0
    for a in db.assessments.values():
        if a["property_id"] == pid and a["status"] in {"DUE", "OVERDUE"}:
            total += int(a["outstanding_cents"])
    prop["account_balance_cents"] = total
    db.bump(prop)


def recompute_property_compliance_posture(prop: dict):
    """Compute COMPLIANT | UNDER_REVIEW | SUSPENDED.

    SUSPENDED when any FILED Lien exists on the property.
    UNDER_REVIEW when no FILED lien but at least one Violation.status == ACTIVE.
    COMPLIANT otherwise.
    """
    pid = prop["id"]
    has_filed_lien = any(
        l["property_id"] == pid and l["status"] == "FILED"
        for l in db.liens.values()
    )
    if has_filed_lien:
        new_posture = "SUSPENDED"
    else:
        has_active_violation = any(
            v["property_id"] == pid and v["status"] == "ACTIVE"
            for v in db.violations.values()
        )
        new_posture = "UNDER_REVIEW" if has_active_violation else "COMPLIANT"
    if prop.get("compliance_posture") != new_posture:
        prop["compliance_posture"] = new_posture
        db.bump(prop)


def maybe_file_lien_cascade(prop: dict):
    """If account_balance_cents >= lien_threshold AND no FILED lien exists,
    file a new Lien and force compliance_posture=SUSPENDED."""
    community = db.communities.get(prop["community_id"])
    if community is None:
        return None
    if int(prop["account_balance_cents"]) < int(community["lien_threshold_cents"]):
        return None
    existing_filed = any(
        l["property_id"] == prop["id"] and l["status"] == "FILED"
        for l in db.liens.values()
    )
    if existing_filed:
        return None
    lien = {
        **db.make_common_fields(),
        "property_id": prop["id"],
        "principal_at_filing_cents": int(prop["account_balance_cents"]),
        "status": "FILED",
        "filed_at": db.iso_now(),
    }
    db.liens[lien["id"]] = lien
    recompute_property_compliance_posture(prop)
    return lien


# ---------------------------------------------------------------------------
# Assessment status recomputation under the wall clock
# ---------------------------------------------------------------------------
def recompute_assessment_for_clock(assessment: dict):
    """If past grace and outstanding > 0, ensure OVERDUE + late fee accrual."""
    if assessment["status"] not in {"DUE", "OVERDUE"}:
        return
    if int(assessment["outstanding_cents"]) <= 0:
        return
    community = _find_community_for_assessment(assessment)
    if community is None:
        return
    due_date = db.parse_iso(assessment["due_date"])
    now = db.get_current_utc()
    grace = int(community["late_fee_grace_days"])
    elapsed = _elapsed_days(now, due_date)
    if elapsed <= grace:
        # still within grace -- no late fee, ensure DUE
        if assessment["status"] != "DUE":
            assessment["status"] = "DUE"
        # late_fee_cents stays at 0 unless previously accrued; per PRD it is
        # never reset by payment, but a brand new assessment will be 0 anyway.
        return
    # Past the grace boundary
    new_fee = compute_late_fee_chronological(
        int(assessment["principal_cents"]),
        due_date, community, now
    )
    # Late fees never reset, but recomputed value should reflect the
    # chronological calc as of `now`. Assign the new value.
    old_fee = int(assessment.get("late_fee_cents", 0))
    assessment["late_fee_cents"] = new_fee
    if assessment["status"] == "DUE":
        assessment["status"] = "OVERDUE"
    # refresh outstanding
    recompute_assessment_paid_outstanding(assessment)


def clock_advance_cascade():
    """Run after current_utc is set. For each DUE/OVERDUE assessment whose
    grace has expired: accrue late fees, transition to OVERDUE, refresh
    property balance, potentially file lien.

    Per PRD §2.4: recomputation of a derived field counts as a mutation, so
    we bump the assessment's updated_at + version when its status or
    late_fee_cents changes.
    """
    # Group assessments by property for batched property recomputation
    touched_props: set[str] = set()
    for a in db.assessments.values():
        if a["status"] in {"DUE", "OVERDUE"}:
            old_status = a["status"]
            old_fee = int(a.get("late_fee_cents", 0))
            recompute_assessment_for_clock(a)
            if a["status"] != old_status or int(a.get("late_fee_cents", 0)) != old_fee:
                db.bump(a)
                touched_props.add(a["property_id"])
    for pid in touched_props:
        prop = db.properties.get(pid)
        if prop is None:
            continue
        recompute_property_account_balance(prop)
        maybe_file_lien_cascade(prop)
