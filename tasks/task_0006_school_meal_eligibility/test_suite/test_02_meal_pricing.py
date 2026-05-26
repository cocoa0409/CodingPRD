"""Tests covering meal pricing: reduced-tier cap interaction, allergen
substitution surcharge, and the FREE-tier surcharge bypass.
"""
import pytest

from test_helpers import (
    validate_success,
    setup_approved_application,
    setup_direct_cert_household,
    create_allergy_profile,
    create_menu_item,
    create_service_transaction,
    TEST_USERS,
)


# ---------------------------------------------------------------------
# Difficulty rule 2 / instance 1 — paid_charge tiered with allergen surcharge
# (mode a): REDUCED tier × $8.00 item × peanut allergen overlap × substitution
# requested → tier_cents = min(40, round_half_up(800*0.10)) + 25 = 40 + 25 = 65.
# ---------------------------------------------------------------------

def test_reduced_tier_allergen_substitution_applies_cap_then_surcharge(api):
    """PRD §3.5: "If `applied_tier` is `REDUCED`, the per-tier amount is the
    smaller of (a) the constant `REDUCED_PRICE_CAP_CENTS` of 40 cents and
    (b) the list price multiplied by `REDUCED_DISCOUNT_FACTOR` of 0.10 — that
    is, 10 percent of list price — with the multiplication rounded half-up to
    the nearest whole cent."
    PRD §3.5: "if all of the following hold — the request set
    `substitute_for_allergen` to true, the menu item's `allergens_present`
    array shares at least one allergen with the student's
    `AllergyProfile.allergens` array, and `applied_tier` is not `FREE` — the
    per-tier amount is increased by the constant `ALLERGEN_SUB_SURCHARGE_CENTS`
    of 25 cents."

    Design: Difficulty/combinatorial_formula/paid_charge_tiered_with_allergen_surcharge_mode_a
    """
    # Household at $55,000/yr family of 4 in CA → REDUCED tier via approved app.
    # annual=5500000 → monthly=round_half_up(5500000/12)=458333.
    # 458333 between thr_free=338000 and thr_red=481000 → REDUCED.
    hh, stu, approved_app = setup_approved_application(
        clock_iso="2026-01-15T12:00:00.000Z",
        family_size=4, annual_income_cents=5_500_000,
        address_state="CA",
        decision_reason="income verified",
        direct_certification_flag=False,
    )
    assert approved_app["status"] == "APPROVED"
    create_allergy_profile(stu["id"], allergens=["PEANUT"], severity="MILD")
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=800, name="PB Cookie",
        allergens_present=["PEANUT"],
    )
    res = api.create_service_transaction(
        {
            "student_id": stu["id"],
            "menu_item_id": menu["id"],
            "substitute_for_allergen": True,
        },
        TEST_USERS["school_staff_headers"],
    )
    tx = validate_success(res, 201)
    assert tx["applied_tier"] == "REDUCED", (
        f"$55k/yr fam-of-4 CA must price at REDUCED; got {tx['applied_tier']!r}"
    )
    # round_half_up(800 * 0.10) = 80; min(40, 80) = 40; +25 surcharge = 65.
    assert tx["paid_charge_cents"] == 65, (
        f"REDUCED $8.00 item with allergen substitution must charge 65c "
        f"(min(40, 80) + 25); got {tx['paid_charge_cents']}"
    )


def test_free_tier_never_charges_allergen_substitution_surcharge(api):
    """PRD §3.5: "if all of the following hold — the request set
    `substitute_for_allergen` to true, the menu item's `allergens_present`
    array shares at least one allergen with the student's
    `AllergyProfile.allergens` array, and `applied_tier` is not `FREE` — the
    per-tier amount is increased by the constant `ALLERGEN_SUB_SURCHARGE_CENTS`
    of 25 cents. The surcharge never applies to a `FREE`-tier student."

    Design: Difficulty/combinatorial_formula/paid_charge_tiered_with_allergen_surcharge_mode_a
    """
    # FREE tier (direct cert) — surcharge MUST NOT apply, even with substitution.
    hh, stu, _elig = setup_direct_cert_household()
    create_allergy_profile(stu["id"], allergens=["PEANUT"], severity="MILD")
    menu = create_menu_item(
        school_code="ELEM-101", list_price_cents=800, name="PB Cookie",
        allergens_present=["PEANUT"],
    )
    res = api.create_service_transaction(
        {
            "student_id": stu["id"],
            "menu_item_id": menu["id"],
            "substitute_for_allergen": True,
        },
        TEST_USERS["school_staff_headers"],
    )
    tx = validate_success(res, 201)
    assert tx["applied_tier"] == "FREE"
    assert tx["paid_charge_cents"] == 0, (
        "FREE-tier student must not be charged allergen surcharge; "
        f"got {tx['paid_charge_cents']}"
    )
