"""Round trips that must conserve a quantity. Beds are booked then released; landlord
units and incentive money are committed then withdrawn. Both partitions must come back
to their pre-create values with no residue.
"""

from test_helpers import (
    MODERATE_FACTORS,
    api_client,
    assert_bed_ledger_invariant,
    assert_landlord_ledger_invariant,
    assert_unit_status_derived,
    cancel_reservation,
    get_success_data,
    match_referral,
    read_partner,
    read_shelter,
    read_staff,
    read_unit,
    seed_active_plan,
    seed_hotline_advocate,
    seed_housing_specialist,
    seed_landlord_partner,
    seed_reserved_admission,
    seed_shelter_scene,
    submit_referral,
    validate_success,
    withdraw_match,
)

CEDAR_HOUSE = {
    "name": "Cedar House",
    "confidential_location": True,
    "nightly_rate_cents": 8500,
    "weekend_surcharge_cents": 2500,
    "child_supplement_cents": 1200,
}
FAMILY_SUITE_A1 = {"unit_label": "A1", "unit_type": "FAMILY_SUITE", "bed_capacity": 4}
FAMILY_OF_THREE = {
    "client_code": "C-9701",
    "legal_name": "Alina Ford",
    "household_size": 3,
    "minor_children_count": 2,
    "accessibility_required": False,
    "location_confidential": True,
    "hmis_disclosure_consent": "DENIED",
}
CANCEL_REASON = "Household found a relative to stay with before the entry date."


def _reservation_holding_three_of_four_beds():
    """Three of A1's four beds are reserved; the empty-unit readings are captured first."""
    scene = seed_shelter_scene(
        shelter_overrides=dict(CEDAR_HOUSE), unit_overrides=dict(FAMILY_SUITE_A1)
    )
    assert scene.unit["bed_capacity"] == 4
    assert scene.unit["available_beds"] == 4
    assert scene.unit["reserved_beds"] == 0
    assert scene.unit["occupied_beds"] == 0
    assert scene.unit["status"] == "AVAILABLE"
    empty_shelter = read_shelter(scene.manager, scene.shelter["id"])
    assert empty_shelter["available_beds"] == 4
    assert empty_shelter["capacity_posture"] == "OPEN"
    scene, client, request, admission = seed_reserved_admission(
        scene=scene,
        client_overrides=dict(FAMILY_OF_THREE),
        assessment_overrides=dict(MODERATE_FACTORS),
        admission_overrides={"entry_date": "2026-08-07", "planned_exit_date": "2026-08-12"},
    )
    held_unit = read_unit(scene.manager, scene.unit["id"])
    assert held_unit["reserved_beds"] == 3
    assert held_unit["available_beds"] == 1
    assert held_unit["status"] == "HOLD"
    held_shelter = read_shelter(scene.manager, scene.shelter["id"])
    assert held_shelter["available_beds"] == 1
    assert held_shelter["capacity_posture"] == "NEAR_CAPACITY"
    assert admission["projected_stay_cost_cents"] == 57000
    return scene, client, request, admission


def test_cancelling_the_only_reservation_restores_every_term_of_the_bed_partition():
    """The pool comes back whole: four available beds, not one plus three fragments.

    PRD: "Cancelling the last reservation on a held unit moves it `HOLD` → `AVAILABLE` with
    `available_beds` back at full `bed_capacity`."

    Design: Difficulty/compensating_invariant/bed_ledger_fully_restored_after_reservation_cancel
    """
    scene, _client, _request, admission = _reservation_holding_three_of_four_beds()

    response = cancel_reservation(scene, admission["id"], cancel_reason=CANCEL_REASON)

    cancelled = validate_success(response, 200)
    assert cancelled["occupancy_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == CANCEL_REASON
    unit = read_unit(scene.manager, scene.unit["id"])
    assert unit["reserved_beds"] == 0
    assert unit["occupied_beds"] == 0
    assert unit["available_beds"] == 4
    assert unit["status"] == "AVAILABLE"
    assert unit["bed_capacity"] == unit["available_beds"] + unit["reserved_beds"] + unit["occupied_beds"]
    assert_bed_ledger_invariant(unit)
    assert_unit_status_derived(unit)
    shelter = read_shelter(scene.manager, scene.shelter["id"])
    assert shelter["available_beds"] == 4
    assert shelter["total_bed_capacity"] == 4
    assert shelter["capacity_posture"] == "OPEN"


def test_the_cancelled_reservation_keeps_its_estimate_and_bills_nothing():
    """The estimate survives as history while the money and the caseload stay untouched.

    PRD: "Cancellation records `cancel_reason`, leaves `settled_stay_cost_cents` null and
    retains `projected_stay_cost_cents` as the historical estimate, releases `household_size`
    beds from the unit's `reserved_beds`, recomputes the ledger and the unit's derived status,
    recomputes the facility's `available_beds` and `capacity_posture`, and returns the linked
    screening request from `ADMITTED` back to `APPROVED` so that the household can be placed
    in a different unit."

    PRD: "That return is the only re-entry into `APPROVED` from `ADMITTED`, and because the
    counted caseload set spans both `APPROVED` and `ADMITTED`, the round trip leaves the
    advocate's `active_caseload_count` exactly where it was and preserves both
    `assigned_advocate_id` and `decided_at`."

    Design: Difficulty/compensating_invariant/bed_ledger_fully_restored_after_reservation_cancel
    """
    scene, _client, request, admission = _reservation_holding_three_of_four_beds()

    cancelled = validate_success(
        cancel_reservation(scene, admission["id"], cancel_reason=CANCEL_REASON), 200
    )

    assert cancelled["settled_stay_cost_cents"] is None
    assert cancelled["projected_stay_cost_cents"] == 57000
    assert read_shelter(scene.manager, scene.shelter["id"])["settled_revenue_cents"] == 0
    assert (
        get_success_data(api_client.get_screening_request(request["id"], scene.manager.headers))[
            "status"
        ]
        == "APPROVED"
    )
    assert read_staff(scene.advocate.id)["active_caseload_count"] == 1


NADIA_ROE = {
    "client_code": "C-9801",
    "legal_name": "Nadia Roe",
    "household_size": 2,
    "minor_children_count": 0,
    "accessibility_required": False,
    "location_confidential": True,
    "hmis_disclosure_consent": "DENIED",
}
RELOCATION_DETAIL = {
    "detail": "Lease a flat on the far side of the city with no shared contacts.",
    "target_completion_date": "2026-08-25",
}
WITHDRAW_REASON = "Landlord relet the unit before the paperwork closed."


def _two_matched_referrals():
    """Vista Rentals holds two matched referrals, one priced at BASE and one at SILVER."""
    advocate = seed_hotline_advocate("Rosa Marin")
    specialist = seed_housing_specialist("Omar Diaz", max_caseload=15)
    client, _plan, _components = seed_active_plan(
        advocate,
        client_overrides=dict(NADIA_ROE),
        assessment_overrides=dict(MODERATE_FACTORS),
        component_types=("RELOCATION",),
        component_overrides={"RELOCATION": dict(RELOCATION_DETAIL)},
    )
    partner = seed_landlord_partner(
        specialist,
        name="Vista Rentals",
        units_pledged=4,
        accepts_subsidy_type="RAPID_REHOUSING_SUBSIDY",
        base_incentive_cents=40000,
    )
    first = submit_referral(
        specialist,
        client["id"],
        partner["id"],
        program_type="TRANSITIONAL_HOUSING",
        subsidy_type="RAPID_REHOUSING_SUBSIDY",
    )
    first = get_success_data(
        match_referral(specialist, first["id"], partner["id"], monthly_rent_cents=145000)
    )
    second = submit_referral(
        specialist,
        client["id"],
        partner["id"],
        program_type="RAPID_REHOUSING",
        subsidy_type="RAPID_REHOUSING_SUBSIDY",
    )
    second = get_success_data(
        match_referral(specialist, second["id"], partner["id"], monthly_rent_cents=152000)
    )
    assert first["incentive_fee_cents"] == 40000
    assert first["incentive_tier_applied"] == "BASE"
    assert second["incentive_fee_cents"] == 59000
    assert second["incentive_tier_applied"] == "SILVER"
    mid = read_partner(specialist, partner["id"])
    assert mid["units_committed"] == 2
    assert mid["units_available"] == 2
    assert mid["incentive_accrued_cents"] == 99000
    assert mid["engagement_score"] == 50.0
    assert mid["incentive_tier"] == "GOLD"
    return specialist, partner, first, second


def test_withdrawing_a_match_returns_the_referral_to_submitted_and_clears_its_fee():
    """The withdrawn referral keeps no stranded money and counts the withdrawal once.

    PRD: "`withdraw_count` increases by 1, and `incentive_fee_cents` and
    `incentive_tier_applied` are cleared to null."

    Design: Difficulty/compensating_invariant/landlord_commitment_and_incentive_restored_after_withdraw_match
    """
    specialist, _partner, first, second = _two_matched_referrals()

    response = withdraw_match(specialist, second["id"], withdraw_reason=WITHDRAW_REASON)

    withdrawn = validate_success(response, 200)
    assert withdrawn["status"] == "SUBMITTED"
    assert withdrawn["withdraw_count"] == 1
    assert withdrawn["incentive_fee_cents"] is None
    assert withdrawn["incentive_tier_applied"] is None
    untouched = get_success_data(
        api_client.get_housing_referral(first["id"], specialist.headers)
    )
    assert untouched["status"] == "MATCHED"
    assert untouched["incentive_fee_cents"] == 40000
    assert untouched["incentive_tier_applied"] == "BASE"
    assert untouched["withdraw_count"] == 0


def test_the_partner_ledger_comes_back_to_one_committed_unit_and_forty_thousand_accrued():
    """Units and money both return to their pre-second-match values with no residue.

    PRD: "On the partner, `units_committed` drops by 1, `units_available` rises by 1, the
    cleared fee is subtracted from `incentive_accrued_cents`, and `engagement_score` and
    `incentive_tier` are re-derived — restoring both compensating invariants, namely that
    `units_pledged` always equals `units_available` plus `units_committed`, and that
    `incentive_accrued_cents` always equals the total of the fees of the partner's `MATCHED`
    and `LEASED` referrals."

    Design: Difficulty/compensating_invariant/landlord_commitment_and_incentive_restored_after_withdraw_match
    """
    specialist, partner, _first, second = _two_matched_referrals()

    validate_success(
        withdraw_match(specialist, second["id"], withdraw_reason=WITHDRAW_REASON), 200
    )

    restored = read_partner(specialist, partner["id"])
    assert restored["units_committed"] == 1
    assert restored["units_available"] == 3
    assert restored["units_pledged"] == 4
    assert_landlord_ledger_invariant(restored)
    assert restored["incentive_accrued_cents"] == 40000
    assert restored["engagement_score"] == 25.0
    assert restored["incentive_tier"] == "SILVER"
