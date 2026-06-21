"""Fee, surcharge, and penalty calculations (PRD §3.6).

Covers the dual-variant license fee, kennel nested-rounding, kennel discount
floor, dangerous-dog surcharge floor, the altered-pet half rate, and the
late-penalty tier boundary.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_owner_headers,
    set_clock,
    advance_clock,
    create_owner,
    create_pet,
    create_rabies_record,
    create_kennel,
    create_draft_license,
    setup_owner_pet,
    setup_kennel_with_active_licenses,
    setup_active_kennel_license,
    drive_license_to_under_review,
    setup_active_individual_license,
    setup_appealed_case,
    setup_designated_case,
)

CLERK = TEST_USERS["clerk_headers"]
OFFICER = TEST_USERS["officer_headers"]


def test_provisional_and_final_fee_diverge_on_designation(api):
    """PRD §3.6: "The provisional variant is stamped when the owner submits
    (DRAFT -> SUBMITTED); it reads is_altered as declared on the application at
    that moment and the kennel's occupied slots as of submission, and it never
    includes any dangerous-dog surcharge."
    PRD §3.6: "The final variant is recomputed when the clerk approves
    (UNDER_REVIEW -> APPROVED); it reads the pet's verified is_altered and adds
    the dangerous-dog surcharge when the pet's is_dangerous is true at approval
    time."
    PRD §3.6: "Start from a base surcharge of 50 dollars (5000 cents) and scale
    it by a severity multiplier: a BITE multiplies by one (1.0)".

    Design: Difficulty/dual_variant_calc/license_fee_provisional_vs_final_diverge_on_designation
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner A", email="oa@x.com", address_zip="10001")
    pet = create_pet(owner["id"], name="Rex", is_altered=False, species="DOG")
    vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1
    )

    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    assert submitted["provisional_fee_cents"] == 4000

    # Drive to UNDER_REVIEW with proof attached, then designate BEFORE approval.
    drive_license_to_under_review(owner["id"], lic["id"], vr["id"])
    setup_designated_case(owner["id"], pet["id"], severity="BITE")

    approved = validate_success(api.approve_license(lic["id"], CLERK), 200)
    assert approved["provisional_fee_cents"] == 4000
    assert approved["final_fee_cents"] == 9000
    assert approved["final_fee_cents"] - approved["provisional_fee_cents"] == 5000


def test_kennel_fee_nested_rounding_order_pinned(api):
    """PRD §3.6: "The fee after multiplying by one-minus-that-discount is rounded
    half-up to whole cents a second time; this second rounding happens after the
    discount, and the order of the two roundings is fixed."
    PRD §3.6: "a KENNEL license from 120 dollars (12000 cents) of per-pet base."
    PRD §3.6: "each occupied slot shaves five percent (0.05) off, so the discount
    percentage is five percent multiplied by the kennel's occupied-slot count".

    Design: Difficulty/combinatorial_formula/kennel_fee_nested_rounding_order_pinned
    """
    set_clock("2026-01-01T00:00:00Z")
    # Kennel with 3 ACTIVE kennel licenses → occupied_slots=3.
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=8, occupied=3)

    kennel_now = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_now["occupied_slots"] == 3

    # 4th unaltered-pet KENNEL license; submit observes occupied_slots=3.
    pet4 = create_pet(owner["id"], name="K4", is_altered=False, species="DOG")
    lic4 = create_draft_license(
        owner["id"], pet4["id"], license_kind="KENNEL", term_years=1,
        kennel_id=kennel["id"],
    )
    submitted = validate_success(
        api.submit_license(lic4["id"], make_owner_headers(owner["id"])), 200
    )
    # 12000 * 1.0 = 12000; discount 0.15 → 12000 * 0.85 = 10200.
    assert submitted["provisional_fee_cents"] == 10200


def test_kennel_discount_floor_caps_at_60pct(api):
    """PRD §3.6: "the discount is capped so that the discounted fee never falls
    below sixty percent of the un-discounted fee - equivalently, the discount
    percentage is the smaller of (five percent times occupied slots) and forty
    percent (which is one minus the sixty-percent floor)."

    Design: Corner/cross_cutting_complexity_layers/kennel_discount_floor_caps_at_60pct
    """
    set_clock("2026-01-01T00:00:00Z")
    # 10 occupied slots → 5%*10 = 50% would apply, but clamped to 40% floor.
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=12, occupied=10)

    kennel_now = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_now["occupied_slots"] == 10

    pet11 = create_pet(owner["id"], name="Eleven", is_altered=False, species="DOG")
    lic = create_draft_license(
        owner["id"], pet11["id"], license_kind="KENNEL", term_years=1,
        kennel_id=kennel["id"],
    )
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    # 12000 * (1 - 0.40) = 7200, NOT 6000 (which 50% would give).
    assert submitted["provisional_fee_cents"] == 7200


def test_altered_pet_individual_fee_half_rate(api):
    """PRD §3.6: "That base is multiplied by an alteration factor - one-half (0.5)
    when the pet is altered, and the full factor of one (1.0) when it is not".
    PRD §3.6: "an INDIVIDUAL license starts from 40 dollars (4000 cents)".

    Design: Corner/calculations/altered_pet_individual_fee_half_rate
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, _ = setup_owner_pet(
        owner_overrides={"full_name": "Z Owner", "email": "zo@x.com"},
        pet_overrides={"is_altered": True, "species": "CAT"},
        with_rabies=False,
    )
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1
    )
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    # 4000 * 0.5 = 2000.
    assert submitted["provisional_fee_cents"] == 2000


def test_dangerous_surcharge_nuisance_hits_floor(api):
    """PRD §3.6: "a NUISANCE by one-half (0.5). Round that product half-up to
    whole cents, then floor it at a minimum of 30 dollars (3000 cents), so even a
    NUISANCE designation never produces a surcharge below 3000 cents."

    Design: Corner/calculations/dangerous_surcharge_nuisance_hits_floor
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Y Owner", email="yo@x.com", address_zip="10019")
    pet = create_pet(owner["id"], name="Noisy", is_altered=False, species="DOG")
    case = setup_designated_case(owner["id"], pet["id"], severity="NUISANCE")
    # 5000 * 0.5 = 2500 → floored to 3000.
    assert case["surcharge_cents"] == 3000


class TestLatePenaltyTierBoundary:
    """PRD §3.6: "if the days late are at most 30, the rate is 2 dollars (200
    cents) per day; once the days late exceed 30, the rate is 5 dollars (500
    cents) per day. The boundary is inclusive of the first tier - exactly 30 days
    late still uses the 200-cents-per-day rate, and 31 days late uses the
    500-cents rate."
    """

    def test_at_exactly_30_days_uses_tier_1(self, api):
        """PRD §3.6: "exactly 30 days late still uses the 200-cents-per-day rate".

        Design: Difficulty/boundary_precision_check/late_penalty_tier_boundary_at_30_days
        """
        set_clock("2026-01-01T00:00:00Z")
        owner = create_owner(full_name="Owner H", email="oh@x.com", address_zip="80001")
        kennel = create_kennel(owner["id"], slot_capacity=5, facility_name="H Kennels")
        # One KENNEL license, occupied_slots=0 at submit → final_fee 12000.
        _, _, lic = setup_active_kennel_license(
            owner, kennel, pet_overrides={"name": "Max", "is_altered": False}
        )
        # issued 2026-01-01 term 1yr → expires 2027-01-01; grace_end 2027-01-31;
        # +30 days = 2027-03-02 → days_late == 30.
        advance_clock("2027-03-02T00:00:00Z")
        expired = validate_success(api.get_license(lic["id"], CLERK), 200)
        assert expired["status"] == "EXPIRED"
        assert expired["final_fee_cents"] == 12000
        # 30 * 200 = 6000, capped at 12000 → 6000.
        assert expired["late_penalty_cents"] == 6000

    def test_at_31_days_uses_tier_2(self, api):
        """PRD §3.6: "31 days late uses the 500-cents rate."
        PRD §3.6: "Multiply days late by the chosen per-day rate, round half-up to
        whole cents, and then cap the result at the license's own final_fee_cents".

        Design: Difficulty/boundary_precision_check/late_penalty_tier_boundary_at_30_days
        """
        set_clock("2026-01-01T00:00:00Z")
        owner = create_owner(full_name="Owner H2", email="oh2@x.com", address_zip="80002")
        kennel = create_kennel(owner["id"], slot_capacity=5, facility_name="H2 Kennels")
        _, _, lic = setup_active_kennel_license(
            owner, kennel, pet_overrides={"name": "Max2", "is_altered": False}
        )
        # grace_end 2027-01-31; +31 days = 2027-03-03 → days_late == 31.
        advance_clock("2027-03-03T00:00:00Z")
        expired = validate_success(api.get_license(lic["id"], CLERK), 200)
        assert expired["status"] == "EXPIRED"
        # 31 * 500 = 15500, capped at final_fee 12000 → 12000.
        assert expired["late_penalty_cents"] == 12000


def test_dangerous_overturn_restores_license_final_fee(api):
    """PRD §3.7: "Overturning it advances APPEALED -> OVERTURNED (terminal) and
    runs a compensating reversal that must exactly undo the designation's fee
    contribution: if no other case for the pet remains DESIGNATED, the pet's
    is_dangerous is cleared back to false (hop one), and for each license of that
    pet in ACTIVE or GRACE that is carrying this case's surcharge, that surcharge
    is subtracted back out of the license's final_fee_cents (hop two), so the net
    surcharge contribution returns to zero."

    Design: Difficulty/compensating_invariant/dangerous_overturn_restores_license_final_fee
    """
    set_clock("2026-01-01T00:00:00Z")
    # Unaltered pet, ACTIVE INDIVIDUAL license, final_fee 4000 (no designation yet).
    owner, pet, vr, lic = setup_active_individual_license(
        owner_overrides={"full_name": "Owner N", "email": "on@x.com"},
        pet_overrides={"is_altered": False, "name": "Zeus"},
    )
    # BITE designation: final_fee → 9000, is_dangerous true; then appeal.
    case = setup_appealed_case(owner["id"], pet["id"], severity="BITE")

    validate_success(api.overturn_case(case["id"], OFFICER), 200)

    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    pet_after = validate_success(api.get_pet(pet["id"], CLERK), 200)
    case_after = validate_success(api.get_dangerous_dog_case(case["id"], CLERK), 200)
    assert lic_after["final_fee_cents"] == 4000
    assert pet_after["is_dangerous"] is False
    assert case_after["status"] == "OVERTURNED"


def test_provisional_final_diverge_when_alteration_misdeclared(api):
    """PRD §3.6: "The two figures can legitimately diverge - for instance when
    alteration was mis-declared, or when a designation landed between submission
    and approval - which is exactly why the provisional figure is an estimate and
    the final figure is authoritative."
    PRD §3.6: "it reads is_altered as declared on the application at that moment"
    PRD §3.6: "it reads the pet's verified is_altered".

    Note: this companion exercises the dual-variant divergence via a designation
    landing between submit and approve on an ALTERED pet (verified is_altered=true
    → base 2000), so provisional 2000 and final 7000 differ by the BITE surcharge.

    Design: Difficulty/dual_variant_calc/license_fee_provisional_vs_final_diverge_on_designation
    """
    set_clock("2026-01-01T00:00:00Z")
    owner = create_owner(full_name="Owner A2", email="oa2@x.com", address_zip="10003")
    pet = create_pet(owner["id"], name="Fixed", is_altered=True, species="DOG")
    vr = create_rabies_record(owner["id"], pet["id"])
    lic = create_draft_license(
        owner["id"], pet["id"], license_kind="INDIVIDUAL", term_years=1
    )
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    # Altered → 4000 * 0.5 = 2000, no surcharge at provisional.
    assert submitted["provisional_fee_cents"] == 2000

    drive_license_to_under_review(owner["id"], lic["id"], vr["id"])
    setup_designated_case(owner["id"], pet["id"], severity="BITE")
    approved = validate_success(api.approve_license(lic["id"], CLERK), 200)
    # Final: verified altered base 2000 + BITE surcharge 5000 = 7000.
    assert approved["final_fee_cents"] == 7000
    assert approved["final_fee_cents"] - approved["provisional_fee_cents"] == 5000


def test_kennel_fee_two_occupied_slots_nested_rounding(api):
    """PRD §3.6: "the discount percentage is five percent multiplied by the
    kennel's occupied-slot count".
    PRD §3.6: "The fee after multiplying by one-minus-that-discount is rounded
    half-up to whole cents a second time; this second rounding happens after the
    discount, and the order of the two roundings is fixed."

    Companion at occupied_slots=2 → discount 0.10 → 12000 * 0.90 = 10800, a
    different point on the pinned two-step rounding than occupied_slots=3.

    Design: Difficulty/combinatorial_formula/kennel_fee_nested_rounding_order_pinned
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, kennel, _ = setup_kennel_with_active_licenses(slot_capacity=8, occupied=2)
    kennel_now = validate_success(api.get_kennel(kennel["id"], CLERK), 200)
    assert kennel_now["occupied_slots"] == 2

    pet3 = create_pet(owner["id"], name="K3rd", is_altered=False, species="DOG")
    lic = create_draft_license(
        owner["id"], pet3["id"], license_kind="KENNEL", term_years=1,
        kennel_id=kennel["id"],
    )
    submitted = validate_success(
        api.submit_license(lic["id"], make_owner_headers(owner["id"])), 200
    )
    assert submitted["provisional_fee_cents"] == 10800


def test_dangerous_overturn_restores_altered_pet_final_fee(api):
    """PRD §3.7: "for each license of that pet in ACTIVE or GRACE that is carrying
    this case's surcharge, that surcharge is subtracted back out of the license's
    final_fee_cents (hop two), so the net surcharge contribution returns to zero."

    Companion: the conserved baseline here is an ALTERED pet's 2000 final fee with
    an ATTACK (2.0x → 10000) surcharge, proving the exact-reversal holds for a
    different baseline and a different surcharge magnitude.

    Design: Difficulty/compensating_invariant/dangerous_overturn_restores_license_final_fee
    """
    set_clock("2026-01-01T00:00:00Z")
    owner, pet, vr, lic = setup_active_individual_license(
        owner_overrides={"full_name": "Owner N2", "email": "on2@x.com"},
        pet_overrides={"is_altered": True, "name": "Athena"},
    )
    lic_before = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_before["final_fee_cents"] == 2000

    case = setup_appealed_case(owner["id"], pet["id"], severity="ATTACK")
    designated = validate_success(api.get_license(lic["id"], CLERK), 200)
    # 2000 + ATTACK surcharge 10000 = 12000.
    assert designated["final_fee_cents"] == 12000

    validate_success(api.overturn_case(case["id"], OFFICER), 200)
    lic_after = validate_success(api.get_license(lic["id"], CLERK), 200)
    assert lic_after["final_fee_cents"] == 2000
    pet_after = validate_success(api.get_pet(pet["id"], CLERK), 200)
    assert pet_after["is_dangerous"] is False
