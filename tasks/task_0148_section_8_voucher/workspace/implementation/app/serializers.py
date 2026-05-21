"""Serializers: convert internal entity records to API response dicts.

Computed/live fields (remaining_search_days, occupancy_status,
next_annual_inspection_due) are derived at read time and never persisted.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app import clock, store
from app.util import iso_format


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _common_full(entity: dict) -> dict:
    """Common fields for entities that carry id/created_at/updated_at/version."""
    return {
        "id": entity["id"],
        "created_at": iso_format(entity["created_at"]),
        "updated_at": iso_format(entity["updated_at"]),
        "version": entity["version"],
    }


def _common_append_only(entity: dict) -> dict:
    """Common fields for append-only entities (only id + created_at)."""
    return {
        "id": entity["id"],
        "created_at": iso_format(entity["created_at"]),
    }


# ---------------------------------------------------------------------------
# Per-entity serializers
# ---------------------------------------------------------------------------

def serialize_applicant(a: dict) -> dict:
    return {
        **_common_full(a),
        "household_name": a["household_name"],
        "household_size": a["household_size"],
        "dependents_count": a["dependents_count"],
        "elderly_or_disabled_head": a["elderly_or_disabled_head"],
        "gross_annual_income_cents": a["gross_annual_income_cents"],
        "childcare_expense_annual_cents": a["childcare_expense_annual_cents"],
        "medical_expense_annual_cents": a["medical_expense_annual_cents"],
        "adjusted_annual_income_cents": a["adjusted_annual_income_cents"],
        "income_band": a["income_band"],
        "eligibility_status": a["eligibility_status"],
    }


def serialize_voucher(v: dict) -> dict:
    deadline = v["search_deadline"]
    now = clock.now()
    remaining = (deadline - now).days if deadline else 0
    return {
        **_common_full(v),
        "applicant_id": v["applicant_id"],
        "bedroom_size": v["bedroom_size"],
        "issued_at": iso_format(v["issued_at"]),
        "search_deadline": iso_format(deadline),
        "zone": v["zone"],
        "special_mobility_flag": v["special_mobility_flag"],
        "administering_pha_id": v["administering_pha_id"],
        "status": v["status"],
        "remaining_search_days": remaining,
    }


def serialize_unit(u: dict) -> dict:
    last_pass = _last_inspection_passed_at(u["id"])
    next_due = last_pass + timedelta(days=365) if last_pass else None
    return {
        **_common_full(u),
        "landlord_id": u["landlord_id"],
        "street_address": u["street_address"],
        "zone": u["zone"],
        "bedroom_count": u["bedroom_count"],
        "asking_rent_cents": u["asking_rent_cents"],
        "tenant_paid_utilities_cents": u["tenant_paid_utilities_cents"],
        "last_inspection_passed_at": iso_format(last_pass),
        "next_annual_inspection_due": iso_format(next_due),
        "occupancy_status": _occupancy_status(u["id"]),
    }


def serialize_payment_standard(p: dict) -> dict:
    return {
        **_common_append_only(p),
        "zone": p["zone"],
        "bedroom_size": p["bedroom_size"],
        "standard_amount_cents": p["standard_amount_cents"],
        "mobility_amount_cents": p["mobility_amount_cents"],
        "effective_from": iso_format(p["effective_from"]),
    }


def serialize_tenancy(t: dict) -> dict:
    return {
        **_common_full(t),
        "voucher_id": t["voucher_id"],
        "unit_id": t["unit_id"],
        "requested_at": iso_format(t["requested_at"]),
        "lease_start": iso_format(t["lease_start"]),
        "gross_rent_cents": t["gross_rent_cents"],
        "applicable_payment_standard_cents": t["applicable_payment_standard_cents"],
        "rent_reasonable": t.get("rent_reasonable"),
        "initial_total_tenant_payment_cents": t.get("initial_total_tenant_payment_cents"),
        "initial_hap_cents": t.get("initial_hap_cents"),
        "current_total_tenant_payment_cents": t.get("current_total_tenant_payment_cents"),
        "current_hap_cents": t.get("current_hap_cents"),
        "rent_burden_at_lease_up_pct": t.get("rent_burden_at_lease_up_pct"),
        "status": t["status"],
        "abatement_started_at": iso_format(t.get("abatement_started_at")),
        "termination_reason": t.get("termination_reason"),
        "current_annual_review_id": t.get("current_annual_review_id"),
    }


def serialize_inspection(i: dict) -> dict:
    return {
        **_common_full(i),
        "tenancy_id": i["tenancy_id"],
        "unit_id": i["unit_id"],
        "inspection_type": i["inspection_type"],
        "scheduled_for": iso_format(i["scheduled_for"]),
        "completed_at": iso_format(i.get("completed_at")),
        "outcome": i.get("outcome"),
        "defects": i.get("defects", []),
        "cure_deadline": iso_format(i.get("cure_deadline")),
        "status": i["status"],
    }


def serialize_rent_reasonableness(r: dict) -> dict:
    return {
        **_common_append_only(r),
        "tenancy_id": r["tenancy_id"],
        "comparable_rents_cents": r["comparable_rents_cents"],
        "median_comparable_cents": r["median_comparable_cents"],
        "reasonable_threshold_cents": r["reasonable_threshold_cents"],
        "is_reasonable": r["is_reasonable"],
        "recorded_at": iso_format(r["recorded_at"]),
    }


def serialize_annual_review(r: dict) -> dict:
    return {
        **_common_full(r),
        "tenancy_id": r["tenancy_id"],
        "review_due_date": iso_format(r["review_due_date"]),
        "submitted_at": iso_format(r.get("submitted_at")),
        "declared_gross_annual_income_cents": r.get("declared_gross_annual_income_cents"),
        "declared_household_size": r.get("declared_household_size"),
        "new_adjusted_income_cents": r.get("new_adjusted_income_cents"),
        "new_total_tenant_payment_cents": r.get("new_total_tenant_payment_cents"),
        "new_hap_cents": r.get("new_hap_cents"),
        "deficiency_codes": r.get("deficiency_codes", []),
        "status": r["status"],
    }


def serialize_portability(p: dict) -> dict:
    return {
        **_common_full(p),
        "voucher_id": p["voucher_id"],
        "receiving_pha_id": p["receiving_pha_id"],
        "requested_at": iso_format(p["requested_at"]),
        "outcome": p["outcome"],
        "decided_at": iso_format(p.get("decided_at")),
        "denial_reason": p.get("denial_reason"),
    }


def serialize_hap_payment(h: dict) -> dict:
    return {
        **_common_append_only(h),
        "tenancy_id": h["tenancy_id"],
        "pay_period_month": h["pay_period_month"],
        "amount_cents": h["amount_cents"],
        "status": h["status"],
        "event_ref_type": h["event_ref_type"],
        "event_ref_id": h["event_ref_id"],
    }


# ---------------------------------------------------------------------------
# Helpers used by serializers (read-only derivations)
# ---------------------------------------------------------------------------

def _last_inspection_passed_at(unit_id: str):
    best = None
    for insp in store.inspections.values():
        if insp.get("unit_id") != unit_id:
            continue
        if insp.get("outcome") in ("PASS", "CURED") and insp.get("completed_at"):
            if best is None or insp["completed_at"] > best:
                best = insp["completed_at"]
    return best


def _occupancy_status(unit_id: str) -> str:
    """Derive Unit.occupancy_status from active Tenancy presence."""
    status_priority = {
        "OCCUPIED_ABATED": 3,
        "OCCUPIED_ACTIVE": 2,
        "OCCUPIED_PENDING": 1,
    }
    best = "VACANT"
    best_rank = 0
    for tn in store.tenancies.values():
        if tn.get("unit_id") != unit_id:
            continue
        s = tn.get("status")
        derived: Optional[str] = None
        if s == "ABATED":
            derived = "OCCUPIED_ABATED"
        elif s == "ACTIVE":
            derived = "OCCUPIED_ACTIVE"
        elif s in ("PENDING_INSPECTION", "PENDING_RENT_REASONABLE"):
            derived = "OCCUPIED_PENDING"
        if derived and status_priority[derived] > best_rank:
            best = derived
            best_rank = status_priority[derived]
    return best
