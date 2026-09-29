"""Corner cases of the arithmetic: staging bays, safety floors and settlement money.

Every scenario is rebuilt from scratch inside the test that needs it, because the
server is relaunched against an empty database before each test.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_profitability_margin,
    assert_settlement_waterfall,
    expected_payout_waterfall,
    expected_safety_cost_cents,
    get_success_data,
    make_finance_approver_headers,
    make_finance_preparer_headers,
    make_safety_author_headers,
    make_safety_certifier_headers,
    make_series_promoter_headers,
    make_ticketing_manager_headers,
    round_half_up_2dp,
    round_half_up_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as helpers

# ---------------------------------------------------------------------------
# Module-local scenario builders
# ---------------------------------------------------------------------------

#: The instant inside the Atlanta staging window used by the settlement scenarios.
_ATL_STAGING_CLOCK = "2026-11-14T17:00:00Z"

#: Selling window that closes five hours before the Atlanta show starts.
_ATL_ON_SALE_END = "2026-11-14T18:00:00Z"

#: Selling window that closes five hours before the Omaha show starts.
_OMA_ON_SALE_END = "2027-01-09T18:00:00Z"


def _bay_order_stop(api: ApiClient) -> Dict[str, Any]:
    """A four-bay Atlanta stop plus one team that will enter several vehicles."""
    state = helpers.stop_with_show_timing(api)
    state.update(
        helpers.create_competitor(
            api,
            team_name="Bay Order Racing",
            driver_name="T. Nolan",
            home_market_code="CLT",
            vehicle_class="LIGHT",
        )
    )
    return state


def _enter_vehicle(
    api: ApiClient, state: Dict[str, Any], vehicle_number: str, weight_lbs: int
):
    """Post one entry on the bay-order stop and return the raw response."""
    return api.create_vehicle_entry(
        {
            "competitor_id": state["competitor_id"],
            "tour_stop_id": state["stop_id"],
            "vehicle_number": vehicle_number,
            "vehicle_weight_lbs": weight_lbs,
            "haul_distance_miles": 100,
            "scheduled_arrival_utc": "2026-11-14T18:00:00Z",
        },
        headers=make_series_promoter_headers(),
    )


def _fill_four_bays(api: ApiClient, state: Dict[str, Any]) -> Dict[str, Any]:
    """Enter light 7200, heavy 9000, light 8999 and heavy 12000, in that order."""
    entries: Dict[str, Any] = {}
    entries["light_1"] = get_success_data(_enter_vehicle(api, state, "1", 7200))
    entries["heavy_1"] = get_success_data(_enter_vehicle(api, state, "2", 9000))
    entries["light_2"] = get_success_data(_enter_vehicle(api, state, "3", 8999))
    entries["heavy_2"] = get_success_data(_enter_vehicle(api, state, "4", 12000))
    return entries


def _omaha_stop_with_draft_plan(api: ApiClient) -> Dict[str, Any]:
    """A concrete-floored 6000-seat Omaha stop carrying a DRAFT plan and no entries."""
    state = helpers.stop_with_show_timing(
        api,
        venue_name="Omaha Pavilion",
        market_code="OMA",
        city="Omaha",
        state_code="NE",
        seat_capacity=6000,
        floor_type="CONCRETE",
        catch_fence_max_height_ft=9,
        medical_bay_count=1,
        load_in_hours_required=8,
        staging_bay_count=2,
        turnaround_hours=12,
        tour_date="2027-01-09",
        rental_base_cents=2200000,
        revenue_share_pct=0.10,
        per_ticket_facility_fee_cents=300,
        load_in_start_utc="2027-01-08T14:00:00Z",
        tear_down_end_utc="2027-01-10T06:00:00Z",
        doors_open_utc="2027-01-09T22:00:00Z",
        show_start_utc="2027-01-09T23:00:00Z",
        show_window_minutes=150,
    )
    state.update(
        helpers.draft_safety_plan(
            api,
            state["stop_id"],
            barrier_linear_feet=1200,
            catch_fence_height_ft=6,
            medical_als_staff_count=1,
            medical_bls_staff_count=4,
            ambulance_count=1,
            emergency_access_lanes=1,
        )
    )
    return state


def _add_omaha_ga_tier(api: ApiClient, state: Dict[str, Any]) -> Dict[str, Any]:
    """The 5999-seat general admission tier, taking attendance just below 6000."""
    return helpers.create_ticket_tier(
        api,
        state["stop_id"],
        tier_code="GA",
        price_cents=3000,
        allotment=5999,
        on_sale_end_utc=_OMA_ON_SALE_END,
    )


def _add_omaha_pit_tier(api: ApiClient, state: Dict[str, Any]) -> Dict[str, Any]:
    """The single extra seat that takes attendance to exactly 6000."""
    return helpers.create_ticket_tier(
        api,
        state["stop_id"],
        tier_code="PIT",
        price_cents=9000,
        allotment=1,
        on_sale_end_utc=_OMA_ON_SALE_END,
    )


def _omaha_stop_at_six_thousand(api: ApiClient) -> Dict[str, Any]:
    """The Omaha stop with both tiers added, so expected attendance is 6000."""
    state = _omaha_stop_with_draft_plan(api)
    state.update(_add_omaha_ga_tier(api, state))
    _add_omaha_pit_tier(api, state)
    return state


def _atl_stop_with_segment_and_tier(
    api: ApiClient,
    tier_code: str,
    price_cents: int,
    allotment: int,
    segment_title: str,
    duration_minutes: int,
    **booking_terms: Any,
) -> Dict[str, Any]:
    """An Atlanta stop carrying one competition segment and one selling tier."""
    state = helpers.stop_with_show_timing(api, **booking_terms)
    helpers.create_show_segment(
        api,
        state["stop_id"],
        segment_type="COMPETITION",
        segment_title=segment_title,
        run_order_position=1,
        duration_minutes=duration_minutes,
    )
    state.update(
        helpers.create_ticket_tier(
            api,
            state["stop_id"],
            tier_code=tier_code,
            price_cents=price_cents,
            allotment=allotment,
            on_sale_end_utc=_ATL_ON_SALE_END,
        )
    )
    return state


def _certify_lean_plan(api: ApiClient, stop_id: str) -> Dict[str, Any]:
    """Certify the minimal adequate plan: 1200 feet of barrier, 1 ALS, 2 BLS, 1 ambulance."""
    return helpers.certified_safety_plan(
        api,
        stop_id,
        barrier_linear_feet=1200,
        catch_fence_height_ft=6,
        medical_als_staff_count=1,
        medical_bls_staff_count=2,
        ambulance_count=1,
        emergency_access_lanes=1,
    )


def _filtered_settlement_stop(api: ApiClient) -> Dict[str, Any]:
    """A closed Atlanta stop with a released allocation and one entry that never staged.

    Radio money stays committed while digital money is released, and of the two
    vehicle entries only the first checks in, so exactly one entry is ``STAGED``.
    """
    state = _atl_stop_with_segment_and_tier(
        api,
        tier_code="GA",
        price_cents=3200,
        allotment=500,
        segment_title="Heat 1",
        duration_minutes=30,
    )
    state.update(
        helpers.create_competitor(
            api,
            team_name="Purse Test Racing",
            driver_name="L. Vega",
            home_market_code="DAL",
            vehicle_class="LIGHT",
        )
    )
    staged = helpers.create_vehicle_entry(
        api,
        state["stop_id"],
        competitor_id=state["competitor_id"],
        vehicle_number="21",
        vehicle_weight_lbs=7000,
        entry_haul_distance_miles=100,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )
    entered = helpers.create_vehicle_entry(
        api,
        state["stop_id"],
        competitor_id=state["competitor_id"],
        vehicle_number="22",
        vehicle_weight_lbs=6800,
        entry_haul_distance_miles=100,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )
    state["staged_entry_id"] = staged["entry_id"]
    state["entered_entry_id"] = entered["entry_id"]
    state.update(_certify_lean_plan(api, state["stop_id"]))
    radio = helpers.commit_marketing_allocation(
        api, state["stop_id"], state["season_id"], channel="RADIO", amount_cents=500000
    )
    digital = helpers.commit_marketing_allocation(
        api, state["stop_id"], state["season_id"], channel="DIGITAL", amount_cents=700000
    )
    state["radio_allocation_id"] = radio["allocation_id"]
    state["digital_allocation_id"] = digital["allocation_id"]
    helpers.set_clock(api, _ATL_STAGING_CLOCK)
    validate_success(
        api.check_in_vehicle_entry(
            state["staged_entry_id"],
            {"arrival_note": "on time"},
            headers=make_series_promoter_headers(),
        )
    )
    validate_success(
        api.open_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    state.update(
        helpers.place_paid_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=100,
            purchaser_name="Filter Patron",
            purchaser_email="filter@example.com",
        )
    )
    validate_success(
        api.release_marketing_allocation(
            state["digital_allocation_id"], headers=make_series_promoter_headers()
        )
    )
    validate_success(
        api.close_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    return state


def _fully_funded_prepared_settlement(api: ApiClient) -> Dict[str, Any]:
    """A closed Atlanta sell-out whose collected cash covers every obligation."""
    state = _atl_stop_with_segment_and_tier(
        api,
        tier_code="PREM",
        price_cents=10000,
        allotment=500,
        segment_title="Feature",
        duration_minutes=40,
    )
    state.update(
        helpers.create_competitor(
            api,
            team_name="Waterfall Motors",
            driver_name="S. Kaur",
            home_market_code="DAL",
            vehicle_class="LIGHT",
        )
    )
    entry = helpers.create_vehicle_entry(
        api,
        state["stop_id"],
        competitor_id=state["competitor_id"],
        vehicle_number="31",
        vehicle_weight_lbs=7000,
        entry_haul_distance_miles=100,
        scheduled_arrival_utc="2026-11-14T16:00:00Z",
    )
    state["entry_id"] = entry["entry_id"]
    state.update(_certify_lean_plan(api, state["stop_id"]))
    helpers.commit_marketing_allocation(
        api, state["stop_id"], state["season_id"], channel="RADIO", amount_cents=500000
    )
    helpers.set_clock(api, _ATL_STAGING_CLOCK)
    validate_success(
        api.check_in_vehicle_entry(
            state["entry_id"], headers=make_series_promoter_headers()
        )
    )
    validate_success(
        api.open_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    state.update(
        helpers.place_paid_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=500,
            purchaser_name="Full House",
            purchaser_email="full@example.com",
        )
    )
    validate_success(
        api.close_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    settlement = get_success_data(
        api.create_settlement(state["stop_id"], headers=make_finance_preparer_headers()),
        expected_status=201,
    )
    state["settlement"] = settlement
    state["settlement_id"] = settlement["id"]
    return state


def _half_cent_settlement(api: ApiClient) -> Dict[str, Any]:
    """A closed Atlanta stop on tiny terms, where two money lines land on a half cent.

    Three seats at 2350 cents give a revenue share of 775.5 cents and a co-op
    credit of 17.5 cents, so both rounding sites are observable in one row.
    """
    state = _atl_stop_with_segment_and_tier(
        api,
        tier_code="GA",
        price_cents=2350,
        allotment=500,
        segment_title="Heat 1",
        duration_minutes=30,
        rental_base_cents=700,
        revenue_share_pct=0.11,
        per_ticket_facility_fee_cents=33,
    )
    state.update(_certify_lean_plan(api, state["stop_id"]))
    helpers.commit_marketing_allocation(
        api, state["stop_id"], state["season_id"], channel="RADIO", amount_cents=500000
    )
    validate_success(
        api.open_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    state.update(
        helpers.place_paid_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=3,
            purchaser_name="Half Cent",
            purchaser_email="halfcent@example.com",
        )
    )
    validate_success(
        api.close_tour_stop_sales(
            state["stop_id"], headers=make_ticketing_manager_headers()
        )
    )
    settlement = get_success_data(
        api.create_settlement(state["stop_id"], headers=make_finance_preparer_headers()),
        expected_status=201,
    )
    state["settlement"] = settlement
    state["settlement_id"] = settlement["id"]
    return state


# ---------------------------------------------------------------------------
# The staging bay selector
# ---------------------------------------------------------------------------


class TestStagingBaySelectorCorners:
    """Weight-inverted bay ranking on a four-bay building, then exhaustion."""

    def test_heavy_rigs_take_the_highest_free_bay_and_light_rigs_the_lowest(
        self, api: ApiClient
    ) -> None:
        """PRD 3.3: "The choice within the candidate set depends on weight: an entry whose `vehicle_weight_lbs` is at least 9000 pounds is a heavy rig and takes the **highest** free bay index, staging nearest the ramp, while a lighter rig takes the **lowest** free index, staging from the far wall."

        Design: Corner/calculations/corner_calc_staging_bay_ranking_heavy_max_light_min_then_exhaustion
        """
        state = _bay_order_stop(api)
        entries = _fill_four_bays(api, state)

        assert entries["light_1"]["staging_bay_index"] == 1
        assert entries["heavy_1"]["staging_bay_index"] == 4
        assert entries["light_2"]["staging_bay_index"] == 2
        assert entries["heavy_2"]["staging_bay_index"] == 3

    def test_a_fifth_entry_finds_no_free_bay_and_nothing_is_created(
        self, api: ApiClient
    ) -> None:
        """PRD 3.3: "If the candidate set is empty — every bay of the building is already held by a live entry of the stop — the request is rejected with `ERR_NO_STAGING_BAY_AVAILABLE` and no entry is created at all."

        Design: Corner/calculations/corner_calc_staging_bay_ranking_heavy_max_light_min_then_exhaustion
        """
        state = _bay_order_stop(api)
        _fill_four_bays(api, state)

        validate_error(
            _enter_vehicle(api, state, "5", 7000),
            ApiErrorId.ERR_NO_STAGING_BAY_AVAILABLE,
        )

        _, meta = validate_paginated(
            api.list_vehicle_entries(
                {"tour_stop_id": state["stop_id"]},
                headers=make_series_promoter_headers(),
            )
        )
        assert meta["total_count"] == 4

    def test_each_created_entry_opens_pre_staging_at_a_full_score(
        self, api: ApiClient
    ) -> None:
        """PRD 3.3: "Under the **`PRE_STAGING`** variant, which runs at entry creation while the transporter has not yet arrived and the entry is still `ENTERED`, the schedule penalty is 15 points when the promised `scheduled_arrival_utc` falls later than the staging close instant — that is, later than two hours before `show_start_utc` — and 0 otherwise." "The haul penalty is common to both variants: 5 points are deducted for every complete block of 500 road miles in the entry's own `haul_distance_miles`, where the number of blocks is the mileage divided by 500 and rounded down to a whole number."

        Design: Corner/calculations/corner_calc_staging_bay_ranking_heavy_max_light_min_then_exhaustion
        """
        state = _bay_order_stop(api)
        entries = _fill_four_bays(api, state)

        for entry in entries.values():
            assert entry["logistics_state"] == "ENTERED"
            assert entry["readiness_variant"] == "PRE_STAGING"
            assert entry["readiness_score"] == 100


# ---------------------------------------------------------------------------
# The safety requirement floors at the attendance threshold
# ---------------------------------------------------------------------------


class TestProvisioningAtTheAttendanceThreshold:
    """One extra seat of allotment moves attendance to exactly 6000."""

    def test_an_attendance_of_5999_still_needs_only_one_als_medic_and_one_lane(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "`expected_attendance` is itself derived as the smaller of the booked venue's `seat_capacity` and the sum of `allotment` over the stop's ticket tiers." "`required_als_staff_count` is 1, plus one more when `expected_attendance` is 6000 or greater, plus one more when the live entry count is 12 or greater." "`required_bls_staff_count` is the larger of 2 and the attendance divided by 2500 rounded **up** to a whole number, plus one further medic when the booked venue's `floor_type` is `CONCRETE`." "`required_emergency_access_lanes` is 1, plus one more when `expected_attendance` is 6000 or greater."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_with_draft_plan(api)
        _add_omaha_ga_tier(api, state)

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["expected_attendance"] == 5999

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["required_als_staff_count"] == 1
        assert plan["required_bls_staff_count"] == 4
        assert plan["required_emergency_access_lanes"] == 1

    def test_the_5999_seat_house_needs_one_ambulance_a_six_foot_fence_and_1200_feet_of_barrier(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "`required_ambulance_count` is the larger of 1 and the live entry count divided by 10 rounded **up** to a whole number." "`required_catch_fence_height_ft` is 8 feet when a heavy rig is present among the live entries and 6 feet otherwise." "`required_barrier_linear_feet` is the larger of 1200 feet and 900 feet plus 75 feet for each live entry."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_with_draft_plan(api)
        _add_omaha_ga_tier(api, state)

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["required_ambulance_count"] == 1
        assert plan["required_catch_fence_height_ft"] == 6
        assert plan["required_barrier_linear_feet"] == 1200

    def test_an_attendance_of_exactly_6000_adds_the_second_als_medic_and_the_second_lane(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "`required_als_staff_count` is 1, plus one more when `expected_attendance` is 6000 or greater, plus one more when the live entry count is 12 or greater. An attendance of exactly 6000 already requires the second ALS medic." "`required_emergency_access_lanes` is 1, plus one more when `expected_attendance` is 6000 or greater."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["expected_attendance"] == 6000

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["required_als_staff_count"] == 2
        assert plan["required_emergency_access_lanes"] == 2
        assert plan["required_bls_staff_count"] == 4

    def test_a_draft_plan_is_never_auto_returned_when_a_tier_is_added(
        self, api: ApiClient
    ) -> None:
        """PRD 2.9: "When the recomputed requirements outrun what a `CERTIFIED` plan actually provisioned, the plan moves from `CERTIFIED` to `RETURNED`, its `certified_by_user_id` is cleared, its `return_count` increments by one, and its `return_reason` is set to the exact string `AUTO_REQUIREMENT_INCREASE`."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["state"] == "DRAFT"
        assert plan["return_count"] == 0
        assert plan["return_reason"] is None

    def test_the_medical_shortfall_is_reported_before_the_lane_shortfall(
        self, api: ApiClient
    ) -> None:
        """PRD 2.10: "Where several rules could reject the same request, they are evaluated in a fixed order and the first failure determines the response." "16. `ERR_MEDICAL_STAFFING_SHORTFALL` (422) — provisioned ALS or BLS medics fall short. Applies to both plan submission and plan certification." "19. `ERR_EMERGENCY_ACCESS_INSUFFICIENT` (422) — emergency lanes fall short. Both submission and certification."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)

        validate_error(
            api.submit_safety_plan(
                state["plan_id"], headers=make_safety_author_headers()
            ),
            ApiErrorId.ERR_MEDICAL_STAFFING_SHORTFALL,
        )

    def test_the_provisioning_bill_charges_medics_ambulances_and_barrier_footage(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "The plan's `safety_cost_cents` is the provisioning bill that later flows into settlement: each ALS medic costs 45,000 cents, each BLS medic 28,000 cents, each ambulance 120,000 cents, and each linear foot of barrier 350 cents, and the cost is the sum of `medical_als_staff_count`, `medical_bls_staff_count`, `ambulance_count` and `barrier_linear_feet` each multiplied by its own rate."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)

        plan = get_success_data(
            api.update_safety_plan(
                state["plan_id"],
                {"medical_als_staff_count": 2},
                headers=make_safety_author_headers(),
            )
        )

        assert plan["safety_cost_cents"] == 742000
        assert plan["safety_cost_cents"] == expected_safety_cost_cents(2, 4, 1, 1200)

    def test_the_lane_shortfall_surfaces_once_medical_staffing_is_satisfied(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "`emergency_access_lanes` must be at least `required_emergency_access_lanes`, or `ERR_EMERGENCY_ACCESS_INSUFFICIENT`; and `barrier_linear_feet` must be at least `required_barrier_linear_feet`, or `ERR_BARRIER_INSUFFICIENT`."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)
        validate_success(
            api.update_safety_plan(
                state["plan_id"],
                {"medical_als_staff_count": 2},
                headers=make_safety_author_headers(),
            )
        )

        validate_error(
            api.submit_safety_plan(
                state["plan_id"], headers=make_safety_author_headers()
            ),
            ApiErrorId.ERR_EMERGENCY_ACCESS_INSUFFICIENT,
        )

    def test_the_corrected_plan_submits_and_certifies_at_an_unchanged_cost(
        self, api: ApiClient
    ) -> None:
        """PRD 3.5: "On success the plan becomes `SUBMITTED` and the stop's `safety_state` moves from `SAFETY_DRAFT` to `SAFETY_REVIEW`, with the posture recomputed." "On success `certified_by_user_id` is set to the caller, and the stop's `safety_state` moves from `SAFETY_REVIEW` to `SAFETY_CERTIFIED`, with the posture recomputed — which is the moment a stop can first become `OPEN`." "Note that catch fencing and emergency lanes are requirements but carry no cost line."

        Design: Corner/calculations/corner_calc_required_provisioning_at_the_attendance_6000_threshold
        """
        state = _omaha_stop_at_six_thousand(api)
        for patch in ({"medical_als_staff_count": 2}, {"emergency_access_lanes": 2}):
            validate_success(
                api.update_safety_plan(
                    state["plan_id"], patch, headers=make_safety_author_headers()
                )
            )

        submitted = get_success_data(
            api.submit_safety_plan(
                state["plan_id"], headers=make_safety_author_headers()
            )
        )
        assert submitted["state"] == "SUBMITTED"
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_REVIEW"
        )

        certified = get_success_data(
            api.certify_safety_plan(
                state["plan_id"],
                {"note": "provisioned for a 6000-seat concrete floor"},
                headers=make_safety_certifier_headers(),
            )
        )
        assert certified["state"] == "CERTIFIED"
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"]
            == "SAFETY_CERTIFIED"
        )
        assert certified["safety_cost_cents"] == 742000


# ---------------------------------------------------------------------------
# The settlement's state-filtered input set
# ---------------------------------------------------------------------------


class TestSettlementInputSetFiltering:
    """Released marketing money and entries that never staged fall out of the money."""

    def test_a_released_allocation_drops_out_of_marketing_spend(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "Three cost figures come from elsewhere on the stop: `marketing_spend_cents` is the sum of `amount_cents` over the stop's allocations in `COMMITTED`; `safety_cost_cents` is copied from the stop's safety plan, and is 0 when the stop has no plan; and `purse_cents` is the competitor purse, 150,000 cents for every vehicle entry of the stop whose `logistics_state` is `STAGED`."

        Design: Corner/calculations/corner_calc_settlement_excludes_released_marketing_and_unstaged_entries
        """
        state = _filtered_settlement_stop(api)
        settlement = get_success_data(
            api.create_settlement(
                state["stop_id"], headers=make_finance_preparer_headers()
            ),
            expected_status=201,
        )

        released = get_success_data(
            api.get_marketing_allocation(
                state["digital_allocation_id"], headers=make_series_promoter_headers()
            )
        )
        committed = get_success_data(
            api.get_marketing_allocation(
                state["radio_allocation_id"], headers=make_series_promoter_headers()
            )
        )
        assert released["state"] == "RELEASED"
        assert committed["state"] == "COMMITTED"
        assert (
            helpers.fetch_stop(api, state["stop_id"])["marketing_spend_committed_cents"]
            == 500000
        )
        assert settlement["marketing_spend_cents"] == 500000

    def test_the_purse_pays_only_the_entry_that_staged(self, api: ApiClient) -> None:
        """PRD 3.9: "Three cost figures come from elsewhere on the stop: `marketing_spend_cents` is the sum of `amount_cents` over the stop's allocations in `COMMITTED`; `safety_cost_cents` is copied from the stop's safety plan, and is 0 when the stop has no plan; and `purse_cents` is the competitor purse, 150,000 cents for every vehicle entry of the stop whose `logistics_state` is `STAGED`."

        Design: Corner/calculations/corner_calc_settlement_excludes_released_marketing_and_unstaged_entries
        """
        state = _filtered_settlement_stop(api)
        settlement = get_success_data(
            api.create_settlement(
                state["stop_id"], headers=make_finance_preparer_headers()
            ),
            expected_status=201,
        )

        assert helpers.fetch_entry(api, state["staged_entry_id"])["logistics_state"] == (
            "STAGED"
        )
        assert helpers.fetch_entry(api, state["entered_entry_id"])[
            "logistics_state"
        ] == ("ENTERED")
        assert settlement["purse_cents"] == 150000
        assert settlement["safety_cost_cents"] == 641000

    def test_the_revenue_lines_and_the_collected_cash_of_the_filtered_stop(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "Over the included set, the settlement writes: `ticket_revenue_cents` as the sum of each included order's `line_subtotal_cents` minus its `group_discount_cents`; `addon_revenue_cents` as the sum of each included order's `addon_subtotal_cents` minus its `addon_discount_cents`; `facility_fee_cents` as the sum of the included orders' `facility_fee_cents`; and `sponsorship_revenue_cents` as the sum of the recognized fee over the stop's included activations." "`collected_cash_cents` is `ticket_revenue_cents` plus `addon_revenue_cents` plus `facility_fee_cents` plus `sponsorship_revenue_cents`."

        Design: Corner/calculations/corner_calc_settlement_excludes_released_marketing_and_unstaged_entries
        """
        state = _filtered_settlement_stop(api)
        settlement = get_success_data(
            api.create_settlement(
                state["stop_id"], headers=make_finance_preparer_headers()
            ),
            expected_status=201,
        )

        assert settlement["ticket_revenue_cents"] == 320000
        assert settlement["facility_fee_cents"] == 35000
        assert settlement["addon_revenue_cents"] == 0
        assert settlement["sponsorship_revenue_cents"] == 0
        assert settlement["collected_cash_cents"] == 355000

    def test_the_coop_rate_is_keyed_on_the_pre_credit_total_it_then_reduces(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "`rental_due_pre_credit_cents` is then the greater of the booking's `rental_base_cents` and that share component, plus the facility fee total." "The co-op credit rate `coop_credit_pct` is selected from that pre-credit figure with inclusive boundaries: 0.06 when `rental_due_pre_credit_cents` is 5,000,000 cents or more, otherwise 0.04 when it is 2,500,000 cents or more, otherwise 0.02." "`venue_due_cents` is `rental_due_pre_credit_cents` minus `coop_credit_cents`."

        Design: Corner/calculations/corner_calc_settlement_excludes_released_marketing_and_unstaged_entries
        """
        state = _filtered_settlement_stop(api)
        settlement = get_success_data(
            api.create_settlement(
                state["stop_id"], headers=make_finance_preparer_headers()
            ),
            expected_status=201,
        )

        assert settlement["rental_due_pre_credit_cents"] == 3035000
        assert settlement["coop_credit_pct"] == pytest.approx(0.04, abs=0.01)
        assert settlement["coop_credit_cents"] == 121400
        assert settlement["venue_due_cents"] == 2913600

    def test_the_venue_bucket_swallows_the_cash_and_starves_the_other_three(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "`payout_venue_cents` is the smaller of the remainder and `venue_due_cents`, and the remainder falls by that amount." "Whatever survives all four buckets is `promoter_remainder_cents`, which is never negative by construction." "`shortfall_cents` is the total unfunded obligation: the amount by which `venue_due_cents` exceeded its payout, plus the same difference for safety, plus marketing, plus purse." "These are integer subtractions with no rounding, and every settlement must satisfy the identity that `net_to_promoter_cents` equals `promoter_remainder_cents` minus `shortfall_cents` under both variants."

        Design: Corner/calculations/corner_calc_settlement_excludes_released_marketing_and_unstaged_entries
        """
        state = _filtered_settlement_stop(api)
        settlement = get_success_data(
            api.create_settlement(
                state["stop_id"], headers=make_finance_preparer_headers()
            ),
            expected_status=201,
        )

        assert settlement["payout_venue_cents"] == 355000
        assert settlement["payout_safety_cents"] == 0
        assert settlement["payout_marketing_cents"] == 0
        assert settlement["payout_purse_cents"] == 0
        assert settlement["promoter_remainder_cents"] == 0
        assert settlement["shortfall_cents"] == 3849600
        assert settlement["net_to_promoter_cents"] == -3849600
        assert settlement["profitability_margin_pct"] == pytest.approx(
            -1084.39, abs=0.01
        )
        assert_settlement_waterfall(settlement)
        assert_profitability_margin(settlement)


# ---------------------------------------------------------------------------
# A waterfall that funds everything and still leaves a remainder
# ---------------------------------------------------------------------------


class TestFullyFundedWaterfall:
    """Collected cash covers all four buckets, so the shortfall is zero."""

    def test_all_four_buckets_are_funded_in_full_and_a_remainder_survives(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "Immediately after those figures, and in both variants, the payout waterfall funds four buckets in this exact order out of `collected_cash_cents`." "Whatever survives all four buckets is `promoter_remainder_cents`, which is never negative by construction." "`shortfall_cents` is the total unfunded obligation: the amount by which `venue_due_cents` exceeded its payout, plus the same difference for safety, plus marketing, plus purse."

        Design: Corner/calculations/corner_calc_waterfall_funds_all_four_buckets_and_leaves_a_remainder
        """
        state = _fully_funded_prepared_settlement(api)
        settlement = state["settlement"]

        assert settlement["collected_cash_cents"] == 5175000
        assert settlement["rental_due_pre_credit_cents"] == 3175000
        assert settlement["coop_credit_pct"] == pytest.approx(0.04, abs=0.01)
        assert settlement["coop_credit_cents"] == 127000
        assert settlement["venue_due_cents"] == 3048000
        assert settlement["safety_cost_cents"] == 641000
        assert settlement["marketing_spend_cents"] == 500000
        assert settlement["purse_cents"] == 150000

        assert settlement["payout_venue_cents"] == 3048000
        assert settlement["payout_safety_cents"] == 641000
        assert settlement["payout_marketing_cents"] == 500000
        assert settlement["payout_purse_cents"] == 150000
        assert settlement["promoter_remainder_cents"] == 836000
        assert settlement["shortfall_cents"] == 0
        assert settlement["net_to_promoter_cents"] == 836000
        assert settlement["profitability_margin_pct"] == pytest.approx(16.15, abs=0.01)
        assert_settlement_waterfall(settlement)
        assert_profitability_margin(settlement)
        assert expected_payout_waterfall(5175000, 3048000, 641000, 500000, 150000) == {
            "payout_venue_cents": 3048000,
            "payout_safety_cents": 641000,
            "payout_marketing_cents": 500000,
            "payout_purse_cents": 150000,
            "promoter_remainder_cents": 836000,
            "shortfall_cents": 0,
        }

    def test_the_final_variant_reproduces_the_provisional_numbers_field_for_field(
        self, api: ApiClient
    ) -> None:
        """PRD 2.9: "Approving a settlement recomputes every money field under the final variant, sets `variant` to `FINAL`, `state` to `APPROVED` and `approved_by_user_id` from the caller."

        Design: Corner/calculations/corner_calc_waterfall_funds_all_four_buckets_and_leaves_a_remainder
        """
        state = _fully_funded_prepared_settlement(api)
        provisional = state["settlement"]
        assert provisional["variant"] == "PROVISIONAL"

        approved = get_success_data(
            api.approve_settlement(
                state["settlement_id"],
                {"note": "clean market, nothing refunded"},
                headers=make_finance_approver_headers(),
            )
        )

        assert approved["variant"] == "FINAL"
        assert approved["state"] == "APPROVED"
        assert approved["prepared_by_user_id"] == "fc-preparer-1"
        assert approved["approved_by_user_id"] == "fc-approver-2"
        for field in (
            "ticket_revenue_cents",
            "addon_revenue_cents",
            "facility_fee_cents",
            "sponsorship_revenue_cents",
            "marketing_spend_cents",
            "safety_cost_cents",
            "purse_cents",
            "collected_cash_cents",
            "rental_due_pre_credit_cents",
            "coop_credit_cents",
            "venue_due_cents",
            "payout_venue_cents",
            "payout_safety_cents",
            "payout_marketing_cents",
            "payout_purse_cents",
            "promoter_remainder_cents",
            "shortfall_cents",
            "net_to_promoter_cents",
        ):
            assert approved[field] == provisional[field], field
        assert approved["profitability_margin_pct"] == pytest.approx(
            provisional["profitability_margin_pct"], abs=0.01
        )
        assert_settlement_waterfall(approved)

    def test_approval_settles_the_stop_and_closes_the_only_season_stop(
        self, api: ApiClient
    ) -> None:
        """PRD 2.9: "Because the settlement became `APPROVED`, the stop moves `sales_state` from `SALES_CLOSED` to `SETTLED`. Because the stop became `SETTLED`, the season's `settled_stop_count` increments by one, the settlement's `net_to_promoter_cents` is added to the season's `season_net_cents`, and the season's `version` increments by one." "If, after that, the season has at least one tour stop, every tour stop of the season has `sales_state` in `SETTLED` or `CANCELLED`, and at least one of them is `SETTLED`, the season's `status` moves from `PLANNING` to `CLOSED` and the season's `version` increments again."

        Design: Corner/calculations/corner_calc_waterfall_funds_all_four_buckets_and_leaves_a_remainder
        """
        state = _fully_funded_prepared_settlement(api)
        validate_success(
            api.approve_settlement(
                state["settlement_id"],
                {"note": "clean market, nothing refunded"},
                headers=make_finance_approver_headers(),
            )
        )

        assert helpers.fetch_stop(api, state["stop_id"])["sales_state"] == "SETTLED"
        season = helpers.fetch_season(api, state["season_id"])
        assert season["settled_stop_count"] == 1
        assert season["season_net_cents"] == 836000
        assert season["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Round-half-up, applied per line
# ---------------------------------------------------------------------------


class TestRoundHalfUpPerMoneyLine:
    """Both the revenue share and the co-op credit land exactly on a half cent."""

    def test_the_order_freezes_its_six_lines_at_the_tiny_terms(
        self, api: ApiClient
    ) -> None:
        """PRD 3.7: "`line_subtotal_cents` is the tier's `price_cents` multiplied by `qty`." "`facility_fee_cents` is the `per_ticket_facility_fee_cents` from the stop's booking — the terms in force when the booking was confirmed — multiplied by `qty`. The facility fee is never discounted." "`total_cents` is `line_subtotal_cents` minus `group_discount_cents`, plus `addon_subtotal_cents` minus `addon_discount_cents`, plus `facility_fee_cents`."

        Design: Corner/calculations/corner_calc_round_half_up_is_applied_per_line_on_share_and_coop_credit
        """
        state = _half_cent_settlement(api)
        order = state["order"]

        assert order["line_subtotal_cents"] == 7050
        assert order["group_discount_cents"] == 0
        assert order["facility_fee_cents"] == 99
        assert order["total_cents"] == 7149

    def test_the_share_line_rounds_up_from_a_half_cent_and_beats_the_rental_floor(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "The share component is the adjusted gross multiplied by the booking's `revenue_share_pct`, rounded half up to whole cents." "`rental_due_pre_credit_cents` is then the greater of the booking's `rental_base_cents` and that share component, plus the facility fee total."

        Design: Corner/calculations/corner_calc_round_half_up_is_applied_per_line_on_share_and_coop_credit
        """
        state = _half_cent_settlement(api)

        assert round_half_up_cents(7050 * 0.11) == 776
        assert state["settlement"]["rental_due_pre_credit_cents"] == 875

    def test_the_coop_credit_rounds_up_from_its_own_half_cent(
        self, api: ApiClient
    ) -> None:
        """PRD 2.5: "Where a percentage is applied to a monetary amount, the product is rounded to whole cents using the round-half-up rule, and the rounding is applied to each named component separately, on its own line, in the order the calculation declares."

        Design: Corner/calculations/corner_calc_round_half_up_is_applied_per_line_on_share_and_coop_credit
        """
        state = _half_cent_settlement(api)
        settlement = state["settlement"]

        assert settlement["coop_credit_pct"] == pytest.approx(0.02, abs=0.01)
        assert settlement["coop_credit_cents"] == 18
        assert settlement["venue_due_cents"] == 857

    def test_the_margin_is_pinned_to_two_decimals_on_a_deeply_negative_ratio(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "`profitability_margin_pct` is `net_to_promoter_cents` divided by `collected_cash_cents`, multiplied by 100 and rounded half up to two decimal places when `collected_cash_cents` is greater than 0; when collected cash is 0 the margin is 0.00."

        Design: Corner/calculations/corner_calc_round_half_up_is_applied_per_line_on_share_and_coop_credit
        """
        state = _half_cent_settlement(api)
        settlement = state["settlement"]

        assert settlement["collected_cash_cents"] == 7149
        assert settlement["purse_cents"] == 0
        assert settlement["safety_cost_cents"] == 641000
        assert settlement["marketing_spend_cents"] == 500000
        assert settlement["net_to_promoter_cents"] == -1134708
        assert settlement["profitability_margin_pct"] == pytest.approx(
            round_half_up_2dp(-1134708 / 7149 * 100), abs=0.01
        )
        assert settlement["profitability_margin_pct"] == pytest.approx(
            -15872.26, abs=0.01
        )

    def test_the_safety_bucket_takes_only_what_the_venue_bucket_left(
        self, api: ApiClient
    ) -> None:
        """PRD 3.9: "`payout_safety_cents` is then the smaller of the remainder and `safety_cost_cents`, and the remainder falls again." "`payout_marketing_cents` is the smaller of the remainder and `marketing_spend_cents`." "`payout_purse_cents` is the smaller of the remainder and `purse_cents`."

        Design: Corner/calculations/corner_calc_round_half_up_is_applied_per_line_on_share_and_coop_credit
        """
        state = _half_cent_settlement(api)
        settlement = state["settlement"]

        assert settlement["payout_venue_cents"] == 857
        assert settlement["payout_safety_cents"] == 6292
        assert settlement["payout_marketing_cents"] == 0
        assert settlement["payout_purse_cents"] == 0
        assert settlement["promoter_remainder_cents"] == 0
        assert settlement["shortfall_cents"] == 1134708
        assert_settlement_waterfall(settlement)
