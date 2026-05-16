"""Serialisers that convert internal dicts to API-shaped response objects.

All derived fields are recomputed on read.
"""

from services.derived import (
    student_allergy_block_active,
    student_meals_served_today_count,
    parent_prepaid_balance,
    district_usda_total,
    district_top_up_outstanding,
)


_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
_APPEND_ONLY_FIELDS = ("id", "created_at")


def _pick(obj, fields):
    return {k: obj.get(k) for k in fields}


def district_view(d: dict) -> dict:
    out = _pick(d, _COMMON_FIELDS)
    out["name"] = d["name"]
    out["school_year_start"] = d["school_year_start"]
    out["usda_reimbursement_total_cents"] = district_usda_total(d["id"])
    out["top_up_outstanding_cents"] = district_top_up_outstanding(d["id"])
    return out


def parent_account_view(pa: dict) -> dict:
    out = _pick(pa, _COMMON_FIELDS)
    out["district_id"] = pa["district_id"]
    out["parent_email"] = pa["parent_email"]
    out["prepaid_balance_cents"] = parent_prepaid_balance(pa)
    return out


def student_view(s: dict) -> dict:
    out = _pick(s, _COMMON_FIELDS)
    out["district_id"] = s["district_id"]
    out["parent_account_id"] = s["parent_account_id"]
    out["full_name"] = s["full_name"]
    out["grade_level"] = s["grade_level"]
    # eligibility_tier and eligibility_application_id are persisted from the
    # state-machine transitions on FrlApplication (approval / denial /
    # auto-renew). The persisted values are authoritative; we surface them
    # verbatim. PRD §3.1: students start at PAID until APPROVED app mints
    # a new tier; PRD §3.4 specifies updates on approve/deny/auto-renew.
    out["eligibility_tier"] = s.get("eligibility_tier", "PAID")
    out["eligibility_application_id"] = s.get("eligibility_application_id")
    out["allergy_block_active"] = student_allergy_block_active(s)
    out["meals_served_today_count"] = student_meals_served_today_count(s)
    return out


def frl_application_view(a: dict) -> dict:
    out = _pick(a, _COMMON_FIELDS)
    out["district_id"] = a["district_id"]
    out["student_id"] = a["student_id"]
    out["school_year_start"] = a.get("school_year_start")
    out["household_size"] = a["household_size"]
    out["declared_annual_income_cents"] = a["declared_annual_income_cents"]
    out["documents_attached_count"] = a.get("documents_attached_count", 0)
    out["status"] = a["status"]
    out["decided_tier"] = a.get("decided_tier")
    out["federal_poverty_guideline_cents"] = a.get("federal_poverty_guideline_cents")
    out["prior_year_application_id"] = a.get("prior_year_application_id")
    out["review_note"] = a.get("review_note")
    out["reviewer_user_id"] = a.get("reviewer_user_id")
    return out


def allergy_entry_view(e: dict) -> dict:
    out = _pick(e, _APPEND_ONLY_FIELDS)
    out["student_id"] = e["student_id"]
    out["allergen"] = e["allergen"]
    out["severity"] = e["severity"]
    out["status"] = e["status"]
    out["doctor_note_attached"] = e["doctor_note_attached"]
    return out


def menu_item_view(m: dict) -> dict:
    out = _pick(m, _COMMON_FIELDS)
    out["district_id"] = m["district_id"]
    out["name"] = m["name"]
    out["contains_allergens"] = list(m.get("contains_allergens", []))
    out["calories"] = m["calories"]
    out["sodium_mg"] = m["sodium_mg"]
    out["full_price_cents"] = m["full_price_cents"]
    out["reimbursable"] = m["reimbursable"]
    out["status"] = m["status"]
    return out


def meal_serving_view(r: dict) -> dict:
    out = _pick(r, _COMMON_FIELDS)
    out["district_id"] = r["district_id"]
    out["student_id"] = r["student_id"]
    out["menu_item_id"] = r["menu_item_id"]
    out["serving_date"] = r["serving_date"]
    out["status"] = r["status"]
    out["tier_at_serving"] = r["tier_at_serving"]
    out["charged_cents"] = r["charged_cents"]
    out["provisional_reimbursement_cents"] = r["provisional_reimbursement_cents"]
    return out


def usda_claim_view(c: dict) -> dict:
    out = _pick(c, _COMMON_FIELDS)
    out["district_id"] = c["district_id"]
    out["period_start"] = c["period_start"]
    out["period_end"] = c["period_end"]
    out["status"] = c["status"]
    out["serving_record_ids"] = list(c.get("serving_record_ids", []))
    out["final_reimbursement_cents"] = c.get("final_reimbursement_cents", 0)
    out["provisional_total_cents"] = c.get("provisional_total_cents", 0)
    return out


def ledger_entry_view(e: dict) -> dict:
    out = _pick(e, _APPEND_ONLY_FIELDS)
    out["parent_account_id"] = e["parent_account_id"]
    out["type"] = e["type"]
    out["amount_cents"] = e["amount_cents"]
    out["serving_record_id"] = e.get("serving_record_id")
    out["occurred_at"] = e["occurred_at"]
    return out
