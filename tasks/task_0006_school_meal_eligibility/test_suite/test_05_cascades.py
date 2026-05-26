"""Tests covering transitive cascades:
- depth-3: approve MealApplication → create new EligibilityDetermination →
  supersede prior actives → re-bind PENDING ServiceTransactions.
- depth-2: PATCH AllergyProfile severity → REJECT PENDING ServiceTransactions
  with matching allergens.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock,
    setup_clean_world,
    setup_approved_application,
    create_household,
    create_student,
    create_allergy_profile,
    update_allergy_profile,
    create_application,
    submit_application,
    start_review,
    approve_application,
    create_direct_cert_eligibility,
    create_menu_item,
    create_service_transaction,
    topup_account,
    get_service_transaction,
    api_client,
    TEST_USERS,
    make_parent_headers,
)


# ---------------------------------------------------------------------
# Difficulty rule 4 / instance 1 — depth-3 cascade on application approve.
# ---------------------------------------------------------------------

def test_application_approve_rebinds_pending_transactions_and_recomputes_charges(api):
    """PRD §3.3: "Every prior `EligibilityDetermination` for the same household
    that is currently `ACTIVE` has its `lifecycle_status` flipped to
    `SUPERSEDED` and its `valid_to_utc` reset to the current server clock
    instant; each supersession bumps the determination's `version` and
    refreshes `updated_at`. Then, every `ServiceTransaction` in `PENDING`
    whose `eligibility_determination_id` references any newly-superseded
    determination is re-bound to the new determination: its
    `eligibility_determination_id` is updated, its `applied_tier` is replaced
    with the new tier, and its `paid_charge_cents` is recomputed by the
    meal-pricing procedure of §3.4."

    Design: Difficulty/transitive_cascade/application_approved_supersedes_eligibility_recompute_pending_charges_depth_3
    """
    set_clock("2026-03-01T10:00:00.000Z")
    # Household at $80,000/yr family of 4 in CA → PAID tier via first approved app.
    hh = create_household(
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    # First application A → PAID
    app_a = create_application(hh["id"])
    submit_application(app_a["id"], hh["id"])
    start_review(app_a["id"])
    approve_application(app_a["id"], decision_reason="initial verified")
    # Income drops; PATCH household to $30,000
    res = api.update_household(
        hh["id"], {"annual_income_cents": 3_000_000},
        TEST_USERS["school_staff_headers"],
    )
    validate_success(res, 200)
    # Topup for PAID tier 300c charge feasibility (not used pre-supersession but harmless)
    topup_account(hh["id"], 1000)
    # PENDING transaction at PAID tier
    menu = create_menu_item(
        school_code="ELEM-101", name="Sandwich",
        list_price_cents=300, allergens_present=[],
    )
    tx = create_service_transaction(stu["id"], menu["id"])
    assert tx["applied_tier"] == "PAID", (
        f"with $80k/yr household first approval, tx must price PAID; "
        f"got {tx['applied_tier']!r}"
    )
    assert tx["paid_charge_cents"] == 300, (
        f"PAID-tier full list price 300c; got {tx['paid_charge_cents']}"
    )
    initial_elig_id = tx["eligibility_determination_id"]

    # Second application B with low income → FREE; APPROVE triggers cascade.
    app_b = create_application(hh["id"])
    # snapshot will pin $30,000 (current household income)
    submit_application(app_b["id"], hh["id"])
    start_review(app_b["id"])
    approve_application(app_b["id"], decision_reason="income reduced; FREE granted")

    # Cascade depth 3 — read the PENDING tx back; must be re-bound and re-priced.
    tx_after = get_service_transaction(tx["id"])
    assert tx_after["applied_tier"] == "FREE", (
        f"tx must be re-bound to FREE tier after second approval; "
        f"got {tx_after['applied_tier']!r}"
    )
    assert tx_after["paid_charge_cents"] == 0, (
        f"after re-binding to FREE tier, paid_charge_cents must be 0; "
        f"got {tx_after['paid_charge_cents']}"
    )
    assert tx_after["eligibility_determination_id"] != initial_elig_id, (
        "tx must be re-bound to a NEW determination id (the FREE one); "
        f"both were {initial_elig_id!r}"
    )


def test_application_approve_supersedes_prior_active_determination(api):
    """PRD §3.3: "Every prior `EligibilityDetermination` for the same household
    that is currently `ACTIVE` has its `lifecycle_status` flipped to
    `SUPERSEDED` and its `valid_to_utc` reset to the current server clock
    instant; each supersession bumps the determination's `version` and
    refreshes `updated_at`."

    Design: Difficulty/transitive_cascade/application_approved_supersedes_eligibility_recompute_pending_charges_depth_3
    """
    set_clock("2026-03-01T10:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=8_000_000,
        address_state="CA", direct_certification_flag=False,
    )
    create_student(hh["id"], school_code="ELEM-101")
    # First application → ACTIVE PAID determination A
    app_a = create_application(hh["id"])
    submit_application(app_a["id"], hh["id"])
    start_review(app_a["id"])
    approve_application(app_a["id"], decision_reason="initial verified")
    # Read back the household's determinations — exactly one ACTIVE.
    res1 = api.list_household_eligibility_determinations(
        hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data1 = validate_success(res1, 200)
    rows1 = data1 if isinstance(data1, list) else data1.get("data", data1)
    active1 = [r for r in rows1 if r["lifecycle_status"] == "ACTIVE"]
    assert len(active1) == 1
    elig_a_id = active1[0]["id"]

    # Patch income to drop tier
    api.update_household(
        hh["id"], {"annual_income_cents": 3_000_000},
        TEST_USERS["school_staff_headers"],
    )
    # Second application → cascades supersession
    app_b = create_application(hh["id"])
    submit_application(app_b["id"], hh["id"])
    start_review(app_b["id"])
    approve_application(app_b["id"], decision_reason="income reduced")

    res2 = api.list_household_eligibility_determinations(
        hh["id"], TEST_USERS["district_reviewer_headers"]
    )
    data2 = validate_success(res2, 200)
    rows2 = data2 if isinstance(data2, list) else data2.get("data", data2)
    a_row = next(r for r in rows2 if r["id"] == elig_a_id)
    assert a_row["lifecycle_status"] == "SUPERSEDED", (
        "prior ACTIVE determination must be flipped to SUPERSEDED; "
        f"got {a_row['lifecycle_status']!r}"
    )
    # Exactly one ACTIVE remains (the new one).
    active2 = [r for r in rows2 if r["lifecycle_status"] == "ACTIVE"]
    assert len(active2) == 1, (
        f"after second approval exactly one ACTIVE determination expected; "
        f"got {len(active2)}"
    )


# ---------------------------------------------------------------------
# Difficulty rule 4 / instance 2 — depth-2 cascade on allergy-profile PATCH.
# ---------------------------------------------------------------------

def test_allergy_profile_severe_update_rejects_matching_pending_transactions(api):
    """PRD §3.1: "Updating an `allergens` list or `severity` is significant
    beyond the profile itself: any `PENDING` `ServiceTransaction` tied to a
    student whose new profile would now contain an allergen also present in
    the served `MenuItem` — together with `severity` of
    `SEVERE_ANAPHYLACTIC` — is immediately transitioned to `REJECTED` with
    `rejection_reason` set to `ALLERGEN_CONFLICT`."

    Design: Difficulty/transitive_cascade/allergy_update_rejects_pending_transactions_depth_2
    """
    set_clock("2026-03-15T11:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    profile = create_allergy_profile(stu["id"], allergens=[], severity="MILD")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    peanut_menu = create_menu_item(
        school_code="ELEM-101", name="PB Cookie",
        list_price_cents=100, allergens_present=["PEANUT"],
    )
    apple_menu = create_menu_item(
        school_code="ELEM-101", name="Apple",
        list_price_cents=50, allergens_present=[],
    )
    tx_peanut = create_service_transaction(stu["id"], peanut_menu["id"])
    tx_apple = create_service_transaction(stu["id"], apple_menu["id"])
    assert tx_peanut["status"] == "PENDING"
    assert tx_apple["status"] == "PENDING"

    update_allergy_profile(profile["id"], allergens=["PEANUT"], severity="SEVERE_ANAPHYLACTIC")

    tx_peanut_after = get_service_transaction(tx_peanut["id"])
    tx_apple_after = get_service_transaction(tx_apple["id"])
    assert tx_peanut_after["status"] == "REJECTED", (
        "PENDING tx on peanut MenuItem must be auto-REJECTED after severe-allergen "
        f"profile update; got status={tx_peanut_after['status']!r}"
    )
    assert tx_peanut_after["rejection_reason"] == "ALLERGEN_CONFLICT", (
        "auto-rejection must set rejection_reason=ALLERGEN_CONFLICT; "
        f"got {tx_peanut_after['rejection_reason']!r}"
    )
    assert tx_apple_after["status"] == "PENDING", (
        "tx on non-peanut MenuItem must be unaffected; "
        f"got status={tx_apple_after['status']!r}"
    )


def test_create_allergy_profile_with_severe_rejects_pre_existing_pending_transactions(api):
    """PRD §3.1: "The same cascade fires when a brand-new profile is created
    for a student who already has pending transactions."

    Design: Difficulty/transitive_cascade/allergy_update_rejects_pending_transactions_depth_2
    """
    set_clock("2026-03-15T11:00:00.000Z")
    hh = create_household(
        family_size=4, annual_income_cents=4_500_000,
        address_state="CA", direct_certification_flag=True,
    )
    stu = create_student(hh["id"], school_code="ELEM-101")
    create_direct_cert_eligibility(
        hh["id"], tier="FREE",
        valid_from_utc="2026-01-01T00:00:00.000Z",
        valid_to_utc="2026-08-31T23:59:59.000Z",
    )
    peanut_menu = create_menu_item(
        school_code="ELEM-101", name="PB Cookie",
        list_price_cents=100, allergens_present=["PEANUT"],
    )
    tx = create_service_transaction(stu["id"], peanut_menu["id"])
    assert tx["status"] == "PENDING"

    create_allergy_profile(stu["id"], allergens=["PEANUT"], severity="SEVERE_ANAPHYLACTIC")

    tx_after = get_service_transaction(tx["id"])
    assert tx_after["status"] == "REJECTED", (
        "creating a SEVERE allergy profile must reject pre-existing PENDING tx "
        f"on matching MenuItem; got {tx_after['status']!r}"
    )
    assert tx_after["rejection_reason"] == "ALLERGEN_CONFLICT"
