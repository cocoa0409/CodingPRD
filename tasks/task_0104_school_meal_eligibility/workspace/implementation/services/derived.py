"""Derived (computed) fields for Student, District, ParentAccount, etc.

These are evaluated on every GET / response — never persisted. See PRD §3.1
(district totals), §3.2 (allergy_block_active), §3.6 (meals_served_today_count
and parent balance).
"""

from core.clock import CLOCK
from core.store import STORE, iso_from_dt
from services.ledger import parent_balance
from services.relationships import (
    active_allergy_entries_for_student,
    active_menu_items_in_district,
    meal_servings_for_student,
    ledger_entries_for_parent,
)


def student_allergy_block_active(student: dict) -> bool:
    """True iff at least one ACTIVE AllergyProfileEntry intersects today's menu items.

    Per PRD §3.2: union of contains_allergens across ACTIVE menu items in this
    district on today's serving_date.
    """
    actives = active_allergy_entries_for_student(student["id"])
    if not actives:
        return False
    student_allergens = {e["allergen"] for e in actives}
    todays_allergens = set()
    for m in active_menu_items_in_district(student["district_id"]):
        for a in m.get("contains_allergens", []):
            todays_allergens.add(a)
    return bool(student_allergens & todays_allergens)


def student_allergy_blocks_menu_item(student: dict, menu_item: dict) -> bool:
    """Per-menu-item intersection check (used at meal-serving validation)."""
    actives = active_allergy_entries_for_student(student["id"])
    if not actives:
        return False
    student_allergens = {e["allergen"] for e in actives}
    item_allergens = set(menu_item.get("contains_allergens", []))
    return bool(student_allergens & item_allergens)


def student_meals_served_today_count(student: dict) -> int:
    """Number of SERVED MealServingRecord for student on today's UTC-midnight day."""
    today = iso_from_dt(CLOCK.today_midnight())
    n = 0
    for r in meal_servings_for_student(student["id"]):
        if r["status"] != "SERVED":
            continue
        if r["serving_date"] == today:
            n += 1
    return n


def parent_prepaid_balance(parent_account: dict) -> int:
    bal = parent_balance(parent_account["id"])
    return max(bal, 0)  # PRD §1.1: "never negative" on this derived field.


def district_usda_total(district_id: str) -> int:
    total = 0
    for c in STORE.usda_claims.values():
        if c["district_id"] != district_id:
            continue
        if c["status"] == "FINALIZED":
            total += c.get("final_reimbursement_cents", 0) or 0
    return total


def district_top_up_outstanding(district_id: str) -> int:
    """Sum across all ParentAccounts in this district of (TOP_UP - CHARGE - REFUND).

    Per SCAFFOLD entity description: "Sum of (TOP_UP) - (CHARGE) - (REFUND, sign-aware)"
    which is the parent balance computed by waterfall_consumption. The standard
    waterfall is TOP_UP minus CHARGE plus REFUND (refunds restore balance), but
    the scaffold's outstanding definition subtracts REFUND because the figure
    is the OUTSTANDING (i.e., yet-to-be-claimed) cash on hand attributable to
    parent contributions net of charges, with refund money having been returned.
    We use: TOP_UP - CHARGE - REFUND across ledger entries for parent accounts
    in this district.
    """
    total = 0
    for pa in STORE.parent_accounts.values():
        if pa["district_id"] != district_id:
            continue
        for e in ledger_entries_for_parent(pa["id"]):
            t = e["type"]
            amt = e["amount_cents"]
            if t == "TOP_UP":
                total += amt
            elif t == "CHARGE":
                total -= amt
            elif t == "REFUND":
                total -= amt
    return total


def student_current_eligibility(student: dict):
    """Return (eligibility_tier, eligibility_application_id) from currently
    APPROVED or RENEWED_FROM_PRIOR applications for this student in the
    current school year.

    Per PRD §3.4: the tier is derived from the latest APPROVED FrlApplication
    governing the current school year; PAID with no application otherwise.
    Auto-renewal applications carry RENEWED_FROM_PRIOR status with a valid
    decided_tier and they too mint eligibility.
    """
    district = STORE.districts[student["district_id"]]
    current_sys = district["school_year_start"]
    best = None
    best_seq = -1
    for app in STORE.frl_applications.values():
        if app["district_id"] != student["district_id"]:
            continue
        if app["student_id"] != student["id"]:
            continue
        if app["status"] not in ("APPROVED", "RENEWED_FROM_PRIOR"):
            continue
        if app.get("school_year_start") != current_sys:
            continue
        if app.get("decided_tier") not in ("FREE", "REDUCED"):
            continue
        # Latest by _seq.
        if app["_seq"] > best_seq:
            best = app
            best_seq = app["_seq"]
    if best is None:
        return "PAID", None
    return best["decided_tier"], best["id"]
