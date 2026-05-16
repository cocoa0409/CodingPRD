"""Composite setup helpers — multi-step preambles tests can reuse.

The school-meal pipeline has many interlocking lifecycles: district →
parent-account → student → FRL application (DRAFT → SUBMITTED →
APPROVED/DENIED) → menu-item → meal-serving (with tier snapshot + ledger
side effects) → USDA reimbursement claim (DRAFT → SUBMITTED →
FINALIZED). Many test claims need the system in a late-pipeline state.

IDENTITY THREADING — PRD §2.1:

- Parent is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Parent,
  X-User-ID is the id of the acting ParentAccount; any ownership check
  on a Student, FrlApplication, AllergyProfileEntry, or top-up/refund
  operation compares the resource's parent_account_id (directly, or via
  the student's parent_account_id) to the header value." Every
  ownership-gated Parent call (create student, create FRL application,
  submit/resubmit, top-up, create/revoke allergy entries) MUST mint
  headers via make_parent_headers(parent_account["id"]) — never via the
  shared PARENT_FALLBACK_ID constant.

- DistrictReviewer, CafeteriaManager, AuditOfficer are OPAQUE — the
  shared TEST_USERS constants are the canonical form for those calls.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUTO_RENEWAL_INCOME_TOLERANCE,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_allergy_entry_payload,
    create_district_payload,
    create_frl_application_payload,
    create_meal_serving_payload,
    create_menu_item_payload,
    create_parent_account_payload,
    create_student_payload,
    create_usda_claim_payload,
    date_midnight_iso,
    deny_payload,
    iso_offset,
    iso_utc,
    random_email,
    random_suffix,
    refund_payload,
    request_info_payload,
    resubmit_payload,
    top_up_payload,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_parent_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.8 (AuditOfficer only)
# ===========================================================================
def advance_clock_to(target_instant: str,
                     headers: Optional[Dict[str, str]] = None
                     ) -> Dict[str, Any]:
    """POST /_clock/advance with the supplied ISO 8601 instant.

    PRD §2.8: AuditOfficer only.
    """
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.clock_advance(
        clock_advance_payload(target_instant=target_instant), headers,
    )
    return get_success_data(resp)


def advance_clock_by_days(days: int,
                          base_iso: Optional[str] = None,
                          headers: Optional[Dict[str, str]] = None
                          ) -> Dict[str, Any]:
    """Advance the server clock by `days` from `base_iso` (or
    server-now if omitted).
    """
    if base_iso is None:
        base_iso = iso_utc(utcnow())
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    return advance_clock_to(
        iso_utc(base + timedelta(days=days)), headers=headers,
    )


# ===========================================================================
# Tier 1: District + ParentAccount + Student
# ===========================================================================
def create_district(
    *,
    name: Optional[str] = None,
    school_year_start: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts — AuditOfficer only per PRD §3.1."""
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.create_district(
        create_district_payload(
            name=name, school_year_start=school_year_start,
        ),
        headers,
    )
    return get_success_data(resp)


def create_parent_account(
    *,
    district: Dict[str, Any],
    parent_email: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts — AuditOfficer only per
    PRD §3.1.
    """
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.create_parent_account(
        district["id"],
        create_parent_account_payload(parent_email=parent_email),
        headers,
    )
    return get_success_data(resp)


def create_student(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    full_name: Optional[str] = None,
    grade_level: int = TEST_DEFAULTS["DEFAULT_GRADE_LEVEL"],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/students — Parent or AuditOfficer per
    PRD §3.1.

    Identity threading: PRD §2.1 — Parent is entity-backed; mint headers
    from the parent account's id. Callers can override with
    AuditOfficer headers when the test needs a "create on behalf"
    pathway.
    """
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.create_student(
        district["id"],
        create_student_payload(
            parent_account_id=parent_account["id"],
            full_name=full_name,
            grade_level=grade_level,
        ),
        headers,
    )
    return get_success_data(resp)


def setup_district_with_family(
    *,
    school_year_start: Optional[str] = None,
    grade_level: int = TEST_DEFAULTS["DEFAULT_GRADE_LEVEL"],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Common bundle: District + ParentAccount + Student (PAID tier).

    Returns (district, parent_account, student).
    """
    district = create_district(school_year_start=school_year_start)
    parent = create_parent_account(district=district)
    student = create_student(
        district=district, parent_account=parent, grade_level=grade_level,
    )
    return district, parent, student


# ===========================================================================
# Tier 2: ParentAccount balance manipulation
# ===========================================================================
def top_up_parent_account(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts/{id}/top-up — Parent only
    per PRD §3.1.

    Identity threading: Parent is entity-backed, so X-User-ID is the
    ParentAccount.id.
    """
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.top_up_parent_account(
        district["id"], parent_account["id"],
        top_up_payload(amount_cents=amount_cents),
        headers,
    )
    return get_success_data(resp)


def refund_charge(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    serving_record_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/parent-accounts/{id}/refund — AuditOfficer
    only per PRD §3.6.
    """
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.refund_parent_account(
        district["id"], parent_account["id"],
        refund_payload(serving_record_id=serving_record_id),
        headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3: MenuItem lifecycle
# ===========================================================================
def create_menu_item(
    *,
    district: Dict[str, Any],
    name: Optional[str] = None,
    contains_allergens: Optional[List[str]] = None,
    calories: int = TEST_DEFAULTS["DEFAULT_CALORIES"],
    sodium_mg: int = TEST_DEFAULTS["DEFAULT_SODIUM_MG"],
    full_price_cents: int = TEST_DEFAULTS["DEFAULT_FULL_PRICE_CENTS"],
    reimbursable: bool = True,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/menu-items — CafeteriaManager only per
    PRD §3.3.
    """
    headers = headers or TEST_USERS["cafeteria_headers"]
    resp = api_client.create_menu_item(
        district["id"],
        create_menu_item_payload(
            name=name,
            contains_allergens=contains_allergens,
            calories=calories,
            sodium_mg=sodium_mg,
            full_price_cents=full_price_cents,
            reimbursable=reimbursable,
        ),
        headers,
    )
    return get_success_data(resp)


def retire_menu_item(
    *,
    district: Dict[str, Any],
    menu_item: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /menu-items/{id}/retire — CafeteriaManager only per
    PRD §3.3.
    """
    headers = headers or TEST_USERS["cafeteria_headers"]
    resp = api_client.retire_menu_item(
        district["id"], menu_item["id"], headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 4: AllergyProfileEntry lifecycle
# ===========================================================================
def create_allergy_entry(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    student: Dict[str, Any],
    allergen: str = "PEANUT",
    severity: str = "MODERATE",
    doctor_note_attached: bool = False,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /students/{id}/allergy-entries — Parent only per PRD §3.2.

    Identity threading: ownership-gated, so headers are minted from the
    owning ParentAccount.id.
    """
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.create_allergy_entry(
        district["id"], student["id"],
        create_allergy_entry_payload(
            allergen=allergen,
            severity=severity,
            doctor_note_attached=doctor_note_attached,
        ),
        headers,
    )
    return get_success_data(resp)


def revoke_allergy_entry(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    student: Dict[str, Any],
    entry_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """DELETE /students/{id}/allergy-entries/{id} — Parent only per
    PRD §3.2.
    """
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.delete_allergy_entry(
        district["id"], student["id"], entry_id, headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 5: FrlApplication lifecycle (DRAFT → SUBMITTED → APPROVED/DENIED)
# ===========================================================================
def create_frl_application(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    student: Dict[str, Any],
    household_size: int = TEST_DEFAULTS["DEFAULT_HOUSEHOLD_SIZE"],
    declared_annual_income_cents: int = TEST_DEFAULTS[
        "DEFAULT_INCOME_FREE_CENTS"
    ],
    documents_attached_count: Optional[int] = None,
    prior_year_application_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/frl-applications — Parent only per PRD §3.4."""
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.create_frl_application(
        district["id"],
        create_frl_application_payload(
            student_id=student["id"],
            household_size=household_size,
            declared_annual_income_cents=declared_annual_income_cents,
            documents_attached_count=documents_attached_count,
            prior_year_application_id=prior_year_application_id,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_frl_application(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    application: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /frl-applications/{id}/submit — Parent only per PRD §3.4."""
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.submit_frl_application(
        district["id"], application["id"], headers,
    )
    return get_success_data(resp)


def approve_frl_application(
    *,
    district: Dict[str, Any],
    application: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /frl-applications/{id}/approve — DistrictReviewer only per
    PRD §3.4.

    DistrictReviewer is opaque — shared header is canonical.
    """
    headers = headers or TEST_USERS["reviewer_headers"]
    resp = api_client.approve_frl_application(
        district["id"], application["id"], headers,
    )
    return get_success_data(resp)


def deny_frl_application(
    *,
    district: Dict[str, Any],
    application: Dict[str, Any],
    review_note: str = "Income exceeds reduced threshold",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /frl-applications/{id}/deny — DistrictReviewer only per
    PRD §3.4.
    """
    headers = headers or TEST_USERS["reviewer_headers"]
    resp = api_client.deny_frl_application(
        district["id"], application["id"],
        deny_payload(review_note=review_note),
        headers,
    )
    return get_success_data(resp)


def request_info_on_application(
    *,
    district: Dict[str, Any],
    application: Dict[str, Any],
    review_note: str = "Need W-2 documentation",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /frl-applications/{id}/request-info — DistrictReviewer only
    per PRD §3.4.
    """
    headers = headers or TEST_USERS["reviewer_headers"]
    resp = api_client.request_info_frl_application(
        district["id"], application["id"],
        request_info_payload(review_note=review_note),
        headers,
    )
    return get_success_data(resp)


def resubmit_application(
    *,
    district: Dict[str, Any],
    parent_account: Dict[str, Any],
    application: Dict[str, Any],
    documents_attached_count: int = 2,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /frl-applications/{id}/resubmit — Parent only per
    PRD §3.4.
    """
    headers = headers or make_parent_headers(parent_account["id"])
    resp = api_client.resubmit_frl_application(
        district["id"], application["id"],
        resubmit_payload(documents_attached_count=documents_attached_count),
        headers,
    )
    return get_success_data(resp)


def setup_student_with_tier(
    *,
    target_tier: str,
    household_size: int = TEST_DEFAULTS["DEFAULT_HOUSEHOLD_SIZE"],
    grade_level: int = TEST_DEFAULTS["DEFAULT_GRADE_LEVEL"],
    school_year_start: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Optional[Dict[str, Any]]]:
    """Mint district + parent + student + (optional) APPROVED FRL
    application to land the student in `target_tier`.

    target_tier ∈ {"FREE", "REDUCED", "PAID"}.

    Returns (district, parent_account, student, application_or_none).
    For PAID, returns (district, parent, student, None) since the
    default eligibility_tier on student creation is PAID per PRD §3.1.

    Income values chosen to land cleanly inside the band for the default
    household_size=4 (FEDERAL_POVERTY_GUIDELINE_BY_SIZE[4]=3,090,000):
    - FREE: 2,000,000 cents (ratio ~0.647 — well below 1.30).
    - REDUCED: 5,000,000 cents (ratio ~1.618 — between 1.30 and 1.85).
    - PAID (rejected): caller should not request this here; use the
      no-application path instead.
    """
    district, parent, student = setup_district_with_family(
        school_year_start=school_year_start, grade_level=grade_level,
    )
    if target_tier == "PAID":
        return district, parent, student, None

    income = (
        TEST_DEFAULTS["DEFAULT_INCOME_FREE_CENTS"]
        if target_tier == "FREE"
        else TEST_DEFAULTS["DEFAULT_INCOME_REDUCED_CENTS"]
    )
    app = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=household_size,
        declared_annual_income_cents=income,
    )
    app = submit_frl_application(
        district=district, parent_account=parent, application=app,
    )
    app = approve_frl_application(
        district=district, application=app,
    )
    return district, parent, student, app


# ===========================================================================
# Tier 6: MealServingRecord lifecycle
# ===========================================================================
def create_meal_serving(
    *,
    district: Dict[str, Any],
    student: Dict[str, Any],
    menu_item: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/meal-servings — CafeteriaManager only per
    PRD §3.6.
    """
    headers = headers or TEST_USERS["cafeteria_headers"]
    resp = api_client.create_meal_serving(
        district["id"],
        create_meal_serving_payload(
            student_id=student["id"], menu_item_id=menu_item["id"],
        ),
        headers,
    )
    return get_success_data(resp)


def void_meal_serving(
    *,
    district: Dict[str, Any],
    serving: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /meal-servings/{id}/void — CafeteriaManager or AuditOfficer
    per PRD §3.6.
    """
    headers = headers or TEST_USERS["cafeteria_headers"]
    resp = api_client.void_meal_serving(
        district["id"], serving["id"], headers,
    )
    return get_success_data(resp)


def serve_meals_across_days(
    *,
    district: Dict[str, Any],
    student: Dict[str, Any],
    menu_item: Dict[str, Any],
    day_anchors: List[str],
) -> List[Dict[str, Any]]:
    """Serve `student` `menu_item` once per day, advancing the logical
    clock between days. `day_anchors` is a list of ISO 8601 UTC
    timestamps; each one becomes "today" for one serving.

    Returns the list of MealServingRecords in serving order.
    """
    servings: List[Dict[str, Any]] = []
    for anchor in day_anchors:
        advance_clock_to(anchor)
        srv = create_meal_serving(
            district=district, student=student, menu_item=menu_item,
        )
        servings.append(srv)
    return servings


# ===========================================================================
# Tier 7: USDA Reimbursement Claim lifecycle
# ===========================================================================
def create_usda_claim(
    *,
    district: Dict[str, Any],
    period_start: str,
    period_end: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /districts/{id}/usda-claims — AuditOfficer only per
    PRD §3.7.
    """
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.create_usda_claim(
        district["id"],
        create_usda_claim_payload(
            period_start=period_start, period_end=period_end,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_usda_claim(
    *,
    district: Dict[str, Any],
    claim: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /usda-claims/{id}/submit — AuditOfficer only per PRD §3.7."""
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.submit_usda_claim(
        district["id"], claim["id"], headers,
    )
    return get_success_data(resp)


def finalize_usda_claim(
    *,
    district: Dict[str, Any],
    claim: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /usda-claims/{id}/finalize — AuditOfficer only per
    PRD §3.7.
    """
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.finalize_usda_claim(
        district["id"], claim["id"], headers,
    )
    return get_success_data(resp)


def reject_usda_claim(
    *,
    district: Dict[str, Any],
    claim: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /usda-claims/{id}/reject — AuditOfficer only per PRD §3.7."""
    headers = headers or TEST_USERS["audit_headers"]
    resp = api_client.reject_usda_claim(
        district["id"], claim["id"], headers,
    )
    return get_success_data(resp)


def submit_and_finalize_claim(
    *,
    district: Dict[str, Any],
    period_start: str,
    period_end: str,
) -> Dict[str, Any]:
    """Create + submit + finalize a USDA claim covering the supplied
    period. Returns the FINALIZED claim.
    """
    claim = create_usda_claim(
        district=district,
        period_start=period_start, period_end=period_end,
    )
    submit_usda_claim(district=district, claim=claim)
    return finalize_usda_claim(district=district, claim=claim)


# ===========================================================================
# Tier 8: Composite scenarios from SCAFFOLD_DIFFICULTY_DESIGN
# ===========================================================================
def setup_paid_serving_with_balance(
    *,
    full_price_cents: int = 350,
    top_up_amount_cents: int = 2000,
    school_year_start: Optional[str] = None,
    reimbursable: bool = True,
    contains_allergens: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Setup a complete environment for PAID-tier meal serving:
    district + parent + student (PAID tier, default) + menu_item +
    parent's prepaid balance topped up to `top_up_amount_cents`.

    Returns (district, parent_account, student, menu_item).
    """
    district, parent, student = setup_district_with_family(
        school_year_start=school_year_start,
    )
    top_up_parent_account(
        district=district, parent_account=parent,
        amount_cents=top_up_amount_cents,
    )
    menu_item = create_menu_item(
        district=district,
        full_price_cents=full_price_cents,
        reimbursable=reimbursable,
        contains_allergens=contains_allergens,
    )
    # Re-read parent account to obtain the updated balance.
    parent = get_success_data(api_client.get_parent_account(
        district["id"], parent["id"],
        make_parent_headers(parent["id"]),
    ))
    return district, parent, student, menu_item


def setup_three_paid_servings_then_approve_free(
    *,
    full_price_cents: int = 350,
    top_up_amount_cents: int = 2000,
    school_year_start: Optional[str] = None,
    income_cents_free: int = 2_000_000,
    household_size: int = 4,
) -> Dict[str, Any]:
    """Setup recipe from difficulty
    dual_variant_calc/usda_reimbursement_provisional_vs_final_on_claim:

    - District D, ParentAccount P (PAID by default).
    - Student S linked to P (eligibility_tier=PAID).
    - MenuItem M with reimbursable=true, full_price_cents=350.
    - Top up P by `top_up_amount_cents` so S can be served PAID.
    - POST /meal-servings (S,M) on 3 consecutive days using
      POST /_clock/advance between each (each row tier_at_serving=PAID,
      provisional=50).
    - Parent submits & DistrictReviewer approves an FrlApplication for
      S with household_size=4 and income=2_000_000 → decided_tier=FREE;
      S.eligibility_tier flips to FREE.

    Returns a dict bundling all generated entities:
      {
        "district": District, "parent_account": ParentAccount,
        "student": Student, "menu_item": MenuItem,
        "servings": [MealServingRecord, MealServingRecord,
                     MealServingRecord],
        "application": FrlApplication (status=APPROVED),
        "day1": str (ISO), "day2": str (ISO), "day3": str (ISO),
      }
    """
    district, parent, student, menu_item = setup_paid_serving_with_balance(
        full_price_cents=full_price_cents,
        top_up_amount_cents=top_up_amount_cents,
        school_year_start=school_year_start,
    )
    # Three consecutive days. Use a fixed base so tests are
    # deterministic.
    day1 = "2026-09-01T12:00:00.000Z"
    day2 = "2026-09-02T12:00:00.000Z"
    day3 = "2026-09-03T12:00:00.000Z"
    servings = serve_meals_across_days(
        district=district, student=student, menu_item=menu_item,
        day_anchors=[day1, day2, day3],
    )
    # Approve an FRL application that flips the student to FREE.
    app = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=household_size,
        declared_annual_income_cents=income_cents_free,
    )
    app = submit_frl_application(
        district=district, parent_account=parent, application=app,
    )
    app = approve_frl_application(
        district=district, application=app,
    )
    return {
        "district": district,
        "parent_account": parent,
        "student": student,
        "menu_item": menu_item,
        "servings": servings,
        "application": app,
        "day1": day1,
        "day2": day2,
        "day3": day3,
    }


def setup_mergeable_claim_period_pair(
    *,
    boundary_overlap: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Setup recipe from difficulty
    resource_temporal_overlap/usda_claim_period_overlap_closed_closed:

    - District D.
    - Claim C1 [2026-01-01, 2026-01-15] submitted.
    - Claim C2 [2026-01-15, 2026-01-31] in DRAFT (boundary overlap)
      OR [2026-02-01, 2026-02-15] (no overlap) per `boundary_overlap`.

    Returns (district, claim_c1, claim_c2).
    """
    district = create_district()
    c1 = create_usda_claim(
        district=district,
        period_start="2026-01-01T00:00:00.000Z",
        period_end="2026-01-15T00:00:00.000Z",
    )
    submit_usda_claim(district=district, claim=c1)
    if boundary_overlap:
        c2 = create_usda_claim(
            district=district,
            period_start="2026-01-15T00:00:00.000Z",
            period_end="2026-01-31T00:00:00.000Z",
        )
    else:
        c2 = create_usda_claim(
            district=district,
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-02-15T00:00:00.000Z",
        )
    return district, c1, c2


def setup_serve_then_void(
    *,
    full_price_cents: int = 350,
    top_up_amount_cents: int = 1000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Setup recipe from difficulty
    compensating_invariant/void_meal_preserves_parent_prepaid_balance:

    - District + ParentAccount (top up 1000 cents) + Student (PAID) +
      MenuItem (full_price=350).
    - Create one SERVED MealServingRecord (charges 350; balance becomes
      650).

    Returns (district, parent_account, student, menu_item, serving).
    The caller is expected to perform the void and assert the
    compensating-balance invariant.
    """
    district, parent, student, menu_item = setup_paid_serving_with_balance(
        full_price_cents=full_price_cents,
        top_up_amount_cents=top_up_amount_cents,
    )
    serving = create_meal_serving(
        district=district, student=student, menu_item=menu_item,
    )
    # Re-read parent account so the test sees the post-charge balance.
    parent = get_success_data(api_client.get_parent_account(
        district["id"], parent["id"],
        make_parent_headers(parent["id"]),
    ))
    return district, parent, student, menu_item, serving


def setup_prior_year_approved_application(
    *,
    prior_school_year_start: str = "2025-08-01T00:00:00.000Z",
    current_school_year_start: str = "2026-08-01T00:00:00.000Z",
    household_size: int = 4,
    income_cents: int = 2_000_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any],
           Dict[str, Any]]:
    """Setup recipe for auto-renewal tests.

    1. Create district with prior_school_year_start.
    2. Create parent + student.
    3. Create + submit + approve an FRL application for the prior year
       (decided_tier becomes FREE for income=2_000_000, household=4).
    4. Advance the server clock to a date one calendar year later, then
       advance the District's school_year_start by creating a fresh
       district that anchors the current year. (PRD §2.8: school_year_
       start is a snapshot field, so we create a new district to anchor
       the new year.)

    PRD §3.5 actually pins the renewal logic to:
    - The new application's school_year_start (captured on submit) lies
      ~365 days after the prior application's school_year_start.

    The simplest faithful setup is to keep the same district but
    advance the District's school_year_start before the new application
    is submitted. But PRD does NOT expose a PATCH for District. Instead,
    we work around this by creating BOTH applications within the same
    district by manipulating the logical clock and the District's
    initial school_year_start.

    To keep the recipe deterministic and PRD-faithful, this helper
    actually creates only the PRIOR application and leaves the
    constructed district at `prior_school_year_start`. The caller is
    expected to create the new (current-year) application separately —
    note that auto-renewal in this PRD is gated by the snapshot delta,
    so the test must arrange the snapshots to differ by ~365 days.

    Returns (district, parent_account, student, prior_application).
    """
    district = create_district(school_year_start=prior_school_year_start)
    parent = create_parent_account(district=district)
    student = create_student(
        district=district, parent_account=parent,
    )
    prior_app = create_frl_application(
        district=district, parent_account=parent, student=student,
        household_size=household_size,
        declared_annual_income_cents=income_cents,
    )
    prior_app = submit_frl_application(
        district=district, parent_account=parent, application=prior_app,
    )
    prior_app = approve_frl_application(
        district=district, application=prior_app,
    )
    return district, parent, student, prior_app


__all__ = [
    "advance_clock_to",
    "advance_clock_by_days",
    "create_district",
    "create_parent_account",
    "create_student",
    "setup_district_with_family",
    "top_up_parent_account",
    "refund_charge",
    "create_menu_item",
    "retire_menu_item",
    "create_allergy_entry",
    "revoke_allergy_entry",
    "create_frl_application",
    "submit_frl_application",
    "approve_frl_application",
    "deny_frl_application",
    "request_info_on_application",
    "resubmit_application",
    "setup_student_with_tier",
    "create_meal_serving",
    "void_meal_serving",
    "serve_meals_across_days",
    "create_usda_claim",
    "submit_usda_claim",
    "finalize_usda_claim",
    "reject_usda_claim",
    "submit_and_finalize_claim",
    "setup_paid_serving_with_balance",
    "setup_three_paid_servings_then_approve_free",
    "setup_mergeable_claim_period_pair",
    "setup_serve_then_void",
    "setup_prior_year_approved_application",
]
