"""
Wave release: the six-step quota arithmetic, the tier floor that can empty a
mailing, and the safety gate that outranks the quota gate entirely.
"""

from test_helpers import (
    AllocationStatus,
    ApiErrorId,
    CampaignStatus,
    RemedyStatus,
    RegionCode,
    WaveStatus,
    WaveType,
    fixtures as fx,
    get_success_data,
    read_list,
    validate_error,
    validate_success,
)
from test_helpers.test_users import OPERATIONS_MANAGER

FIVE_NE_BUILDS = [
    {
        "vin": "1HGCM82633A004352",
        "production_date": "2024-03-15",
        "suspect_part_number": 1500,
        "owner_name": "Ann Vega",
    },
    {
        "vin": "1HGCM82633A004353",
        "production_date": "2024-03-16",
        "suspect_part_number": 1501,
        "owner_name": "Ben Ito",
    },
    {
        "vin": "1HGCM82633A004354",
        "production_date": "2024-03-17",
        "suspect_part_number": 1502,
        "owner_name": "Cara Lu",
    },
    {
        "vin": "1HGCM82633A004355",
        "production_date": "2024-03-18",
        "suspect_part_number": 1503,
        "owner_name": "Dan Roe",
    },
    {
        "vin": "1HGCM82633A004356",
        "production_date": "2024-03-19",
        "suspect_part_number": 1504,
        "owner_name": "Eve Sun",
    },
]

TWO_NE_BUILDS = FIVE_NE_BUILDS[:2]


def _wave_over_five_owners_with_four_kits(api):
    """Five eligible NE owners against a four-kit regional holding."""
    state = fx.campaign_with_allocation(api, vehicles=FIVE_NE_BUILDS, requested_qty=4)
    state["wave"] = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-10",
    )
    state["wave_id"] = state["wave"]["id"]
    return state


def test_wave_release_gates_on_the_eligible_count_and_tiers_the_mailing_down(api):
    """
    Four kits across five eligible owners give a provisional ratio of 0.8000,
    which clears the MODERATE minimum, selects the 0.75 tier, and floors the
    mailing at three owners.

    PRD §3.6: "`provisional_coverage_ratio` is the `parts_capacity_qty` divided
    by the `eligible_vehicle_count`, rounded half up to four decimal places."

    PRD §3.6: "`coverage_tier_factor` is selected from that same provisional
    ratio, taking 1.00 when the ratio is at least 1.0000, otherwise 0.75 when it
    is at least 0.6000, otherwise 0.40 when it is at least 0.3000, and otherwise
    0.00."

    PRD §3.6: "`planned_vehicle_count` is the `eligible_vehicle_count` multiplied
    by the `coverage_tier_factor`, rounded **down** to a whole vehicle."

    Design: Difficulty/combinatorial_formula/wave_release_circular_coverage_ratio_mode_c
    """
    state = _wave_over_five_owners_with_four_kits(api)

    wave = validate_success(api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER), 200)

    assert wave["eligible_vehicle_count"] == 5
    assert wave["parts_capacity_qty"] == 4
    assert wave["provisional_coverage_ratio"] == 0.8
    assert wave["coverage_tier_factor"] == 0.75
    assert wave["planned_vehicle_count"] == 3


def test_reported_parts_coverage_ratio_divides_by_the_planned_count(api):
    """
    The reported ratio uses the planned count as its denominator, so four kits
    over three planned letters reports 1.3333 rather than the 0.8000 the gate
    compared, and the release consumes no kits.

    PRD §3.6: "`parts_coverage_ratio` is the `parts_capacity_qty` divided by the
    `planned_vehicle_count`, rounded half up to four decimal places."

    PRD §3.6: "the gate's denominator is the eligible count, the reported ratio's
    denominator is the planned count."

    Design: Difficulty/combinatorial_formula/wave_release_circular_coverage_ratio_mode_c
    """
    state = _wave_over_five_owners_with_four_kits(api)

    wave = validate_success(api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER), 200)

    assert wave["parts_coverage_ratio"] == 1.3333
    assert wave["provisional_coverage_ratio"] == 0.8
    assert wave["status"] == WaveStatus.RELEASE_APPROVED

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["allocated_qty"] == 4
    assert allocation["consumed_qty"] == 0


def _low_severity_wave_over_two_owners_with_one_kit(api):
    """A LOW-severity campaign with two eligible owners and a single kit."""
    state = fx.campaign_with_allocation(
        api,
        vehicles=TWO_NE_BUILDS,
        requested_qty=1,
        campaign={
            "defect_type": "NONCOMPLIANCE",
            "defect_description": "Label omits tire pressure information",
            "risk_severity": "LOW",
        },
        labor_operation={
            "labor_op_code": "R102-01",
            "description": "Apply corrected tire placard",
            "flat_hours": 0.30,
        },
        remedy_part={"part_number": "P-77001", "unit_cost": 4.25, "total_procured_qty": 50},
        narrative="Part 573 noncompliance information report",
    )
    state["wave"] = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-10",
    )
    state["wave_id"] = state["wave"]["id"]
    return state


def test_tier_factor_flooring_to_zero_owners_empties_the_wave(api):
    """
    One kit across two LOW-severity owners gives 0.5000, which clears the 0.3000
    minimum but selects the 0.40 tier, and two owners times 0.40 floors to zero,
    so the release is refused for an empty population rather than for coverage.

    PRD §3.6: "a `LOW` campaign at least 0.3000. A ratio exactly equal to the
    requirement passes; a ratio below it is rejected with
    `ERR_INSUFFICIENT_PARTS_COVERAGE`."

    PRD §3.6: "A `planned_vehicle_count` of zero is rejected with
    `ERR_EMPTY_WAVE_POPULATION`."

    Design: Difficulty/boundary_precision_check/wave_release_planned_count_floors_to_zero_at_tier_boundary
    """
    state = _low_severity_wave_over_two_owners_with_one_kit(api)

    response = api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER)
    validate_error(response, ApiErrorId.EMPTY_WAVE_POPULATION, 409)


def test_refused_wave_release_pins_no_quota_fields(api):
    """
    A release refused at step 5 leaves the wave in PLANNED with its quota fields
    still at their zero defaults, and leaves the dealer's single kit in hand.

    PRD §3.6: "A planned wave starts in status `PLANNED` with `auto_created`
    false, all its quota fields at their zero defaults, `mailed_vehicle_count` 0,
    and `actual_mail_date` and `cancel_reason` unset."

    PRD §3.6: "All six pinned values — `eligible_vehicle_count`,
    `parts_capacity_qty`, `provisional_coverage_ratio`, `coverage_tier_factor`,
    `planned_vehicle_count` and `parts_coverage_ratio` — are written onto the
    wave, its status advances from `PLANNED` to `RELEASE_APPROVED`, and its
    `version` increments by 1."

    Design: Difficulty/boundary_precision_check/wave_release_planned_count_floors_to_zero_at_tier_boundary
    """
    state = _low_severity_wave_over_two_owners_with_one_kit(api)
    validate_error(
        api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER),
        ApiErrorId.EMPTY_WAVE_POPULATION,
        409,
    )

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER), expected_total=1
    )
    wave = waves[0]
    assert wave["status"] == WaveStatus.PLANNED
    assert wave["planned_vehicle_count"] == 0
    assert wave["eligible_vehicle_count"] == 0
    assert wave["mailed_vehicle_count"] == 0

    allocation = get_success_data(
        api.get_parts_allocation(state["allocation_id"], OPERATIONS_MANAGER)
    )
    assert allocation["allocated_qty"] == 1
    assert allocation["status"] == AllocationStatus.ALLOCATED


def _interim_only_campaign_with_a_remedy_wave(api):
    """An INTERIM_NOTIFIED campaign whose operator planned a REMEDY wave too early."""
    state = fx.filed_campaign(api)
    state["campaign"] = fx.issue_interim_advisory(
        api, state["campaign_id"], stop_sale=False, do_not_drive=True
    )
    state["wave"] = fx.plan_wave(
        api,
        state["campaign_id"],
        wave_type=WaveType.REMEDY,
        target_region_code=RegionCode.NE,
        scheduled_mail_date="2026-08-10",
    )
    state["wave_id"] = state["wave"]["id"]
    return state


def test_remedy_wave_release_is_refused_while_the_remedy_is_interim_only(api):
    """
    A REMEDY wave cannot be approved while the campaign carries only an interim
    notice, and the safety gate answers before the coverage gate that the empty
    regional holding would otherwise trip.

    PRD §3.6: "a `REMEDY` or `FOLLOW_UP` wave requires `remedy_status`
    `REMEDY_RELEASED`, while an `INTERIM` wave requires `remedy_status`
    `INTERIM_ONLY` together with `campaign_status` `INTERIM_NOTIFIED`."

    PRD §3.4: "Each requires `remedy_status` to be either `REMEDY_RELEASED` or
    `REMEDY_REVISED`; attempting any of the three while `remedy_status` is
    `REMEDY_UNDER_DEVELOPMENT` or `INTERIM_ONLY` is rejected with
    `ERR_REMEDY_NOT_AVAILABLE`."

    Design: Difficulty/cross_entity_state_dependency/remedy_wave_release_blocked_by_campaign_interim_only_remedy_status
    """
    state = _interim_only_campaign_with_a_remedy_wave(api)

    response = api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER)
    validate_error(response, ApiErrorId.REMEDY_NOT_AVAILABLE, 409)


def test_wave_refused_for_remedy_availability_leaves_both_dimensions_alone(api):
    """
    The refused release writes nothing: the wave stays PLANNED with a zero
    coverage ratio, and the campaign keeps INTERIM_NOTIFIED / INTERIM_ONLY.

    PRD §2.7: "**Safety gates**, in this precedence: remedy availability
    (`ERR_REMEDY_NOT_AVAILABLE`), remedy-already-exists on an interim advisory
    (`ERR_REMEDY_ALREADY_AVAILABLE`), stop-sale hold (`ERR_STOP_SALE_ACTIVE`)."

    PRD §3.4: "Acceptance advances both dimensions at once — `campaign_status`
    from `FILED` to `INTERIM_NOTIFIED` and `remedy_status` from
    `REMEDY_UNDER_DEVELOPMENT` to `INTERIM_ONLY`".

    Design: Difficulty/cross_entity_state_dependency/remedy_wave_release_blocked_by_campaign_interim_only_remedy_status
    """
    state = _interim_only_campaign_with_a_remedy_wave(api)
    validate_error(
        api.release_wave(state["wave_id"], {}, OPERATIONS_MANAGER),
        ApiErrorId.REMEDY_NOT_AVAILABLE,
        409,
    )

    waves, _ = read_list(
        api.list_notification_waves(state["campaign_id"], OPERATIONS_MANAGER), expected_total=1
    )
    wave = waves[0]
    assert wave["status"] == WaveStatus.PLANNED
    assert wave["eligible_vehicle_count"] == 0
    assert wave["provisional_coverage_ratio"] == 0.0

    campaign = fx.read_campaign(api, state["campaign_id"])
    assert campaign["remedy_status"] == RemedyStatus.INTERIM_ONLY
    assert campaign["campaign_status"] == CampaignStatus.INTERIM_NOTIFIED
