"""Cross-entity lookups and ownership / district-scoping checks.

All path-segment lookups are left-to-right (PRD §2.7). When a path names
/districts/{district_id}/students/{student_id}/..., we first verify the district
exists, then the student exists AND belongs to that district. If either fails,
return ERR_NOT_FOUND for the FIRST id that doesn't resolve in scope.
"""

from core.errors import raise_error
from core.store import STORE


# ---- Single-entity lookups (scoped to district where applicable) ----------

def get_district_or_404(district_id: str) -> dict:
    d = STORE.districts.get(district_id)
    if d is None:
        raise_error("ERR_NOT_FOUND", f"District {district_id} not found")
    return d


def get_parent_account_in_district(district_id: str, parent_account_id: str) -> dict:
    pa = STORE.parent_accounts.get(parent_account_id)
    if pa is None or pa["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"ParentAccount {parent_account_id} not found in district")
    return pa


def get_student_in_district(district_id: str, student_id: str) -> dict:
    s = STORE.students.get(student_id)
    if s is None or s["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"Student {student_id} not found in district")
    return s


def get_frl_application_in_district(district_id: str, app_id: str) -> dict:
    a = STORE.frl_applications.get(app_id)
    if a is None or a["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"FrlApplication {app_id} not found in district")
    return a


def get_menu_item_in_district(district_id: str, menu_item_id: str) -> dict:
    m = STORE.menu_items.get(menu_item_id)
    if m is None or m["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"MenuItem {menu_item_id} not found in district")
    return m


def get_meal_serving_in_district(district_id: str, msr_id: str) -> dict:
    r = STORE.meal_serving_records.get(msr_id)
    if r is None or r["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"MealServingRecord {msr_id} not found in district")
    return r


def get_usda_claim_in_district(district_id: str, claim_id: str) -> dict:
    c = STORE.usda_claims.get(claim_id)
    if c is None or c["district_id"] != district_id:
        raise_error("ERR_NOT_FOUND",
                    f"UsdaReimbursementClaim {claim_id} not found in district")
    return c


def get_allergy_entry_for_student(student_id: str, entry_id: str) -> dict:
    e = STORE.allergy_entries.get(entry_id)
    if e is None or e["student_id"] != student_id:
        raise_error("ERR_NOT_FOUND",
                    f"AllergyProfileEntry {entry_id} not found on student")
    return e


# ---- Ownership checks -----------------------------------------------------

def parent_owns_student(parent_account_id: str, student: dict) -> bool:
    return student.get("parent_account_id") == parent_account_id


# ---- Aggregated child lookups (used for derived-field recomputation) -----

def active_allergy_entries_for_student(student_id: str):
    return [
        e for e in STORE.allergy_entries.values()
        if e["student_id"] == student_id and e["status"] == "ACTIVE"
    ]


def active_menu_items_in_district(district_id: str):
    return [
        m for m in STORE.menu_items.values()
        if m["district_id"] == district_id and m["status"] == "ACTIVE"
    ]


def ledger_entries_for_parent(parent_account_id: str):
    return [
        e for e in STORE.ledger_entries.values()
        if e["parent_account_id"] == parent_account_id
    ]


def meal_servings_for_student(student_id: str):
    return [
        r for r in STORE.meal_serving_records.values()
        if r["student_id"] == student_id
    ]
