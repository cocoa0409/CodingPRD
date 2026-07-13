"""Reimbursement tiered-schedule calculations: estimate vs final divergence,
the combinatorial mode-(a) formula, and the tier-1/tier-2 mileage boundary at 50."""
from test_helpers import (
    validate_success, TEST_USERS, make_member_headers,
    create_incident, create_active_incident, create_team_and_member,
    create_task, create_claim, create_submitted_claim, log_ground_track,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# --- Difficulty: dual_variant_calc / reimbursement_estimate_vs_final_diverge ---

def test_reimbursement_estimate_uses_declared_mileage(api):
    """PRD §3.8: "submission computes the **estimate variant** and stores it in
    `estimated_amount_cents`, using the member-declared, unverified
    `declared_mileage_miles` as the mileage input."
    PRD §3.8: "the tier-1 portion is the smaller of the mileage and 50 multiplied by
    65 cents, the tier-2 portion is the mileage minus 50 (when positive, otherwise
    zero) multiplied by 40 cents, and exactly 50 miles is billed entirely at tier-1."

    Design: Difficulty/dual_variant_calc/reimbursement_estimate_vs_final_diverge
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Ridge Search", ics_incident_number="OR-2026-0001")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Jo Searcher"})
    task = create_task(api, inc["id"], segment_area_sqkm=10.0, planned_searcher_hours=8)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T10:00:00Z",
                     distance_km=30.0, duration_min=90, coverage_area_sqkm=3.0)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T12:00:00Z",
                     distance_km=42.0, duration_min=90, coverage_area_sqkm=4.0)
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=60,
                         meal_count=8, lodging_nights=2)
    submitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    # 50*65 + 10*40 (mileage) + min(8,6)*1500 (meals) + 2*9000 (lodging)
    assert submitted["estimated_amount_cents"] == 30650


def test_reimbursement_final_uses_reconciled_track_mileage_and_diverges(api):
    """PRD §3.8: "Approval computes the **final variant** and stores it in
    `final_amount_cents`, differing from the estimate only in its mileage input:
    instead of the declared figure, it uses the reconciled mileage, obtained by
    summing `distance_km` across every `GroundTrack` whose `member_id` equals the
    claim's member and whose task belongs to the claim's incident, multiplying that
    sum by `0.621371` miles per kilometer, and rounding half up to a whole number of
    miles."
    PRD §3.8: "Where declared and tracked mileage disagree, the estimate and final
    figures diverge."

    Design: Difficulty/dual_variant_calc/reimbursement_estimate_vs_final_diverge
    """
    api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, COORD)
    inc = create_active_incident(api, name="Ridge Search", ics_incident_number="OR-2026-0001b")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Jo Searcher"})
    task = create_task(api, inc["id"], segment_area_sqkm=10.0, planned_searcher_hours=8)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T10:00:00Z",
                     distance_km=30.0, duration_min=90, coverage_area_sqkm=3.0)
    log_ground_track(api, task["id"], member["id"], recorded_at="2026-05-02T12:00:00Z",
                     distance_km=42.0, duration_min=90, coverage_area_sqkm=4.0)
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=60,
                         meal_count=8, lodging_nights=2)
    validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    validate_success(api.demobilize_incident(inc["id"], IC))
    approved = validate_success(api.approve_claim(claim["id"], FIN))
    # reconciled miles = round_half_up(72.0 * 0.621371) = 45; 45*65 + 9000 + 18000
    assert approved["final_amount_cents"] == 29925
    assert approved["estimated_amount_cents"] != approved["final_amount_cents"]


# --- Difficulty: combinatorial_formula / reimbursement_tiered_mileage_and_caps_mode_a ---

def test_reimbursement_combines_tiered_mileage_meal_cap_and_lodging(api):
    """PRD §3.8: "The meal component is the smaller of `meal_count` and the cap
    `MEAL_MAX_COUNT` of 6, multiplied by `MEAL_PER_DIEM_CENTS` of 1500 cents per
    meal. The lodging component is `lodging_nights` multiplied by `LODGING_RATE_CENTS`
    of 9000 cents per night. The total is the sum of the mileage, meal, and lodging
    components, expressed in whole cents; because every input is an integer, no
    rounding is applied."

    Design: Difficulty/combinatorial_formula/reimbursement_tiered_mileage_and_caps_mode_a
    """
    inc = create_incident(api, name="Meadow Search", incident_type="URBAN",
                          ics_incident_number="OR-2026-0003")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Bo Hiker"})
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=60,
                         meal_count=8, lodging_nights=2)
    submitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    assert submitted["estimated_amount_cents"] == 30650


def test_reimbursement_meal_component_is_capped_at_six(api):
    """PRD §3.8: "The meal component is the smaller of `meal_count` and the cap
    `MEAL_MAX_COUNT` of 6, multiplied by `MEAL_PER_DIEM_CENTS` of 1500 cents per
    meal."

    Design: Difficulty/combinatorial_formula/reimbursement_tiered_mileage_and_caps_mode_a
    """
    inc = create_incident(api, name="Meadow Search 2", incident_type="URBAN",
                          ics_incident_number="OR-2026-0003b")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Bo Hiker"})
    # meals only; 8 requested but capped at 6 => 6*1500 = 9000 (no mileage, no lodging)
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=0,
                         meal_count=8, lodging_nights=0)
    submitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    assert submitted["estimated_amount_cents"] == 9000


# --- Difficulty: boundary_precision_check / mileage_tier_boundary_at_50_on_submit ---

def test_mileage_exactly_fifty_is_all_tier_one(api):
    """PRD §3.8: "the tier-1 portion is the smaller of the mileage and 50 multiplied
    by 65 cents, the tier-2 portion is the mileage minus 50 (when positive, otherwise
    zero) multiplied by 40 cents, and exactly 50 miles is billed entirely at tier-1."

    Design: Difficulty/boundary_precision_check/mileage_tier_boundary_at_50_on_submit
    """
    inc = create_incident(api, name="Boundary Mileage", incident_type="URBAN",
                          ics_incident_number="OR-2026-0012")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Ken A"})
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=50,
                         meal_count=0, lodging_nights=0)
    submitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    assert submitted["estimated_amount_cents"] == 3250  # 50 * 65


def test_mileage_fifty_one_crosses_into_tier_two(api):
    """PRD §3.8: "The mileage component reimburses the first `MILEAGE_TIER1_LIMIT_MI`
    of 50 miles at `MILEAGE_RATE_TIER1_CPM` of 65 cents per mile and every mile
    strictly beyond 50 at `MILEAGE_RATE_TIER2_CPM` of 40 cents per mile".

    Design: Difficulty/boundary_precision_check/mileage_tier_boundary_at_50_on_submit
    """
    inc = create_incident(api, name="Boundary Mileage 2", incident_type="URBAN",
                          ics_incident_number="OR-2026-0012b")
    team, member = create_team_and_member(api, member_overrides={"full_name": "Kim B"})
    claim = create_claim(api, member["id"], inc["id"], declared_mileage_miles=51,
                         meal_count=0, lodging_nights=0)
    submitted = validate_success(api.submit_claim(claim["id"], make_member_headers(member["id"])))
    assert submitted["estimated_amount_cents"] == 3290  # 50*65 + 1*40
