"""Nested clamps, tier selection and the rounding order of the reliance roll-up."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import ASSET_HEADERS, PLANNER_HEADERS
from test_helpers.assertions import assert_capacity_fields, assert_cost_breakdown
from test_helpers.factories import legacy_placement_payload
from test_helpers.fixtures import (
    build_campus,
    certify_study,
    create_request,
    create_site,
    create_study,
    create_unit,
    submit_study,
)

CYPRESS = {
    "school_overrides": {"name": "Cypress Middle", "site_acreage": 14.0,
                         "sewer_spare_connections": 1},
    "room_areas": (900, 900, 900, 480),
    "projections": ((6, 36), (7, 36), (8, 35)),
}


def _two_arm_district(api):
    """One campus, two pads and two units chosen to hit opposite clamp arms."""
    ctx = build_campus(api, **CYPRESS)
    ctx["floor_site_id"] = create_site(
        api, ctx["school_id"], pad_code="PAD-FLOOR", electrical_drop_available_kw=20,
        sewer_connection_available=True, ada_path_of_travel_compliant=True,
    )["id"]
    ctx["cap_site_id"] = create_site(
        api, ctx["school_id"], pad_code="PAD-CAP", pad_length_ft=80, pad_width_ft=50,
        distance_to_fire_lane_ft=60, electrical_drop_available_kw=10,
        sewer_connection_available=False, ada_path_of_travel_compliant=False,
    )["id"]
    ctx["unit_a_id"] = create_unit(
        api, asset_tag="PU-3001", condition_grade="A", ada_ramp_installed=True,
        acquisition_cost_cents=8_000_000, in_service_year=2024,
    )["id"]
    ctx["unit_c_id"] = create_unit(
        api, asset_tag="PU-3002", size_class="TRIPLE_36x64", condition_grade="C",
        ada_ramp_installed=False, acquisition_cost_cents=22_000_000,
        in_service_year=2013,
    )["id"]

    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    ctx["study_id"] = study["id"]

    ctx["floor_request_id"] = create_request(
        api, study["id"], ctx["floor_site_id"], ctx["budget_id"],
        haul_miles=0, portable_unit_id=ctx["unit_a_id"],
        requested_window_start="2027-06-15", requested_window_end="2027-06-25",
    )["id"]
    ctx["cap_request_id"] = create_request(
        api, study["id"], ctx["cap_site_id"], ctx["budget_id"],
        haul_miles=30, portable_unit_id=ctx["unit_c_id"],
        requested_window_start="2027-06-15", requested_window_end="2027-06-30",
    )["id"]
    return ctx


def test_contingency_is_pinned_at_the_cap_on_the_expensive_arm(api):
    """PRD §3.6: "**Contingency** is 12 percent of that direct cost, rounded half up,
    then capped at 1,500,000 cents from above and lifted to 700,000 cents from below
    — the floor applies after the cap, so an estimate whose 12 percent computes below
    the floor pays exactly the floor and one whose 12 percent computes above the cap
    pays exactly the cap." The direct cost it clamps is itself conditional:
    "1,850,000 cents when the pad's `electrical_drop_available_kw` is less than the
    chassis's service draw, 2,400,000 cents when the chassis needs a sewer connection
    and the pad's `sewer_connection_available` is false, and 3,150,000 cents when
    either the unit's `ada_ramp_installed` is false or the pad's
    `ada_path_of_travel_compliant` is false."

    Design: Difficulty/combinatorial_formula/contingency_nested_clamp_floor_and_cap_arms
    """
    ctx = _two_arm_district(api)

    data = validate_success(api.get_cost_model(ctx["cap_request_id"], PLANNER_HEADERS))

    assert_cost_breakdown(data, {
        "mobilisation_cents": 10_940_000,
        "site_work_cents": 7_400_000,
        "rehab_cents": 4_600_000,
        "permit_fee_cents": 1_050_000,
        "direct_cost_cents": 23_990_000,
        "contingency_cents": 1_500_000,
        "estimated_relocation_cost_cents": 25_490_000,
    })
    assert data["off_summer_applied"] is False


def test_contingency_is_lifted_to_the_floor_on_the_cheap_arm(api):
    """PRD §3.6: "**Contingency** is 12 percent of that direct cost, rounded half up,
    then capped at 1,500,000 cents from above and lifted to 700,000 cents from below",
    where the direct cost of a fully serviced pad carries no site work and a grade `A`
    unit carries "nothing for grade `A`" of rehab.

    Design: Difficulty/combinatorial_formula/contingency_nested_clamp_floor_and_cap_arms
    """
    ctx = _two_arm_district(api)

    data = validate_success(api.get_cost_model(ctx["floor_request_id"], PLANNER_HEADERS))

    assert_cost_breakdown(data, {
        "mobilisation_cents": 4_500_000,
        "site_work_cents": 0,
        "rehab_cents": 0,
        "permit_fee_cents": 630_000,
        "direct_cost_cents": 5_130_000,
        "contingency_cents": 700_000,
        "estimated_relocation_cost_cents": 5_830_000,
    })

    stored = validate_success(
        api.get_placement_request(ctx["floor_request_id"], PLANNER_HEADERS)
    )
    assert stored["estimated_relocation_cost_cents"] == 5_830_000

    study = validate_success(api.get_capacity_study(ctx["study_id"], PLANNER_HEADERS))
    assert_capacity_fields(study, seat_deficit=12, required_portable_count=1)


def _two_campus_district(api):
    """Two identical campuses, one of which is given a legacy portable."""
    alder = build_campus(api, school_overrides={"name": "Alder Middle",
                                                "site_acreage": 9.0,
                                                "electrical_spare_capacity_kw": 40,
                                                "sewer_spare_connections": 1})
    birch = build_campus(api, clock=None, policy_id=alder["policy_id"],
                         budget_cents=None,
                         school_overrides={"name": "Birch Middle",
                                           "site_acreage": 9.0,
                                           "electrical_spare_capacity_kw": 40,
                                           "sewer_spare_connections": 1})

    for ctx in (alder, birch):
        study = create_study(api, ctx["school_id"], alder["policy_id"])
        submit_study(api, study["id"])
        certify_study(api, study["id"])
        ctx["study_id"] = study["id"]

    alder["site_id"] = create_site(api, alder["school_id"], pad_code="PAD-A1")["id"]
    alder["unit_id"] = create_unit(
        api, asset_tag="PU-4001", condition_grade="B", ada_ramp_installed=True,
        acquisition_cost_cents=9_000_000, in_service_year=2018,
    )["id"]
    return alder, birch


def test_each_campus_reliance_share_is_rounded_on_its_own_report(api):
    """PRD §3.9: "`portable_seat_share_pct` is the hosted portable seats multiplied by
    100, divided by the sum of the permanent seats and the hosted portable seats,
    rounded half up to one decimal place. The campus's `reliance_flag` is
    `LONG_TERM_RELIANCE` when that share reaches 15.0 percent or more, or when
    `consecutive_reliance_years` reaches 5 or more; failing that, it is `MONITOR` when
    the share reaches 5.0 percent or more; otherwise it is `NONE`. A narrative to the
    board is required exactly when the flag is `LONG_TERM_RELIANCE`, reported as
    `narrative_required`."

    Design: Difficulty/combinatorial_formula/reliance_share_rounded_per_school_then_averaged
    """
    alder, birch = _two_campus_district(api)

    placed = validate_success(
        api.record_existing_placement(
            alder["unit_id"],
            legacy_placement_payload(alder["school_id"], alder["site_id"],
                                     installed_on="2027-03-01"),
            ASSET_HEADERS,
        )
    )
    assert placed["allocation_status"] == "INSTALLED"
    assert placed["lifetime_relocation_count"] == 1

    hosting = validate_success(
        api.get_reliance_report(alder["school_id"], PLANNER_HEADERS)
    )
    assert hosting["permanent_seats"] == 56
    assert hosting["hosted_portable_seats"] == 24
    assert hosting["portable_seat_share_pct"] == 30.0
    assert hosting["reliance_flag"] == "LONG_TERM_RELIANCE"
    assert hosting["narrative_required"] is True

    quiet = validate_success(
        api.get_reliance_report(birch["school_id"], PLANNER_HEADERS)
    )
    assert quiet["permanent_seats"] == 56
    assert quiet["hosted_portable_seats"] == 0
    assert quiet["portable_seat_share_pct"] == 0.0
    assert quiet["reliance_flag"] == "NONE"
    assert quiet["narrative_required"] is False


def test_district_average_averages_already_rounded_campus_shares(api):
    """PRD §3.9: "Each qualifying campus's share is rounded to one decimal place
    first, exactly as its own report would show it; only then are those already-rounded
    values averaged, and the average is rounded half up to one decimal place again to
    give `district_average_portable_share_pct`. Pooling district-wide seats and
    rounding once at the end is explicitly not the rule and yields a different number"
    and "`long_term_reliance_school_count` counts the qualifying campuses whose flag is
    `LONG_TERM_RELIANCE`".

    Design: Difficulty/combinatorial_formula/reliance_share_rounded_per_school_then_averaged
    """
    alder, _ = _two_campus_district(api)

    validate_success(
        api.record_existing_placement(
            alder["unit_id"],
            legacy_placement_payload(alder["school_id"], alder["site_id"],
                                     installed_on="2027-03-01"),
            ASSET_HEADERS,
        )
    )

    summary = validate_success(api.get_reliance_summary(PLANNER_HEADERS))

    assert summary["qualifying_school_count"] == 2
    assert summary["district_average_portable_share_pct"] == 15.0
    assert summary["district_average_portable_share_pct"] != 17.6
    assert summary["long_term_reliance_school_count"] == 1


def _single_request_on_cypress(api):
    ctx = build_campus(api, **CYPRESS)
    ctx["site_id"] = create_site(api, ctx["school_id"], pad_code="PAD-C")["id"]
    ctx["unit_id"] = create_unit(
        api, asset_tag="PU-5001", condition_grade="B", ada_ramp_installed=True,
        acquisition_cost_cents=9_600_000, in_service_year=2019,
    )["id"]
    study = create_study(api, ctx["school_id"], ctx["policy_id"])
    submit_study(api, study["id"])
    ctx["study_id"] = study["id"]
    ctx["request_id"] = create_request(
        api, study["id"], ctx["site_id"], ctx["budget_id"],
        haul_miles=10, portable_unit_id=ctx["unit_id"],
    )["id"]
    return ctx


def test_soft_cost_tier_is_selected_from_the_direct_cost_not_from_the_total(api):
    """PRD §3.6: "The tier is always selected from the **direct** cost, never from the
    total: a direct cost below 50,000,000 cents attracts 9 percent, a direct cost below
    150,000,000 cents attracts 13 percent, and any larger direct cost attracts 17
    percent. The soft cost is that percentage of the direct cost, rounded half up. The
    total program cost is the direct cost plus the soft cost — computed last, and never
    used to pick the tier."

    Design: Difficulty/combinatorial_formula/soft_cost_tier_keyed_to_direct_not_total
    """
    ctx = _single_request_on_cypress(api)

    data = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))

    assert data["basis"] == "LIFECYCLE_20YR"
    assert data["permanent_addition_direct_cents"] == 46_200_000
    assert data["permanent_addition_soft_cost_cents"] == 4_158_000
    assert data["permanent_addition_total_program_cost_cents"] == 50_358_000
    assert data["permanent_addition_total_program_cost_cents"] != 52_206_000


def test_cheapest_total_program_cost_wins_the_recommendation(api):
    """PRD §3.6: "**A boundary change** costs a fixed 4,200,000 cents of study work
    plus 96,000 cents of transport for each deficit seat for each of 5 years. **A
    permanent addition** costs 3,850,000 cents for each deficit seat." and "The
    recommendation is the surviving option with the smallest total program cost."

    Design: Difficulty/combinatorial_formula/soft_cost_tier_keyed_to_direct_not_total
    """
    ctx = _single_request_on_cypress(api)

    data = validate_success(api.get_cost_model(ctx["request_id"], PLANNER_HEADERS))

    assert_cost_breakdown(data, {
        "estimated_relocation_cost_cents": 7_571_200,
        "relocation_direct_cents": 32_171_200,
        "relocation_soft_cost_cents": 2_895_408,
        "relocation_total_program_cost_cents": 35_066_608,
        "boundary_change_direct_cents": 9_960_000,
        "boundary_change_total_program_cost_cents": 10_856_400,
        "cost_recommendation": "BOUNDARY_CHANGE",
    })
