"""Two calculations that answer the same question two ways.

An unmet-need determination and a volunteer skill-fit score each have an
authoritative variant and an advisory one; running both over one fixture is what
proves the two code paths are genuinely different.
"""

from typing import Any, Dict

import pytest

from test_helpers import (
    TEST_USERS,
    assert_skill_fit_report,
    assert_unmet_need_assessment,
    create_case,
    create_group,
    create_project,
    create_survivor,
    document_and_verify_damage,
    permit_project,
    record_assistance,
    run_assessment,
    set_clock,
    validate_success,
)

COORDINATOR = TEST_USERS["volunteer_coordinator_headers"]


def _setup_case_with_stranded_housing_over_award() -> Dict[str, Any]:
    """A case whose temporary-housing award exceeds its temporary-housing need.

    Verified damage lands at 14100000 after two per-item ceilings bite (a 4000000
    roof is capped to 3500000 and 1800000 of contents to 1500000). Documented
    assistance totals 8300000 across three purposes, of which the 900000 of
    temporary-housing money over-covers a 300000 need by 600000. A fourth award of
    1000000 is DISPUTED and therefore offsets nothing.
    """
    set_clock()
    survivor = create_survivor(
        household_name="Alvarez Household",
        primary_contact_phone="555-0101",
        household_size=4,
        income_band="VLI",
        head_of_household_age=58,
        has_member_with_disability=True,
    )
    case = create_case(survivor["id"], temporary_housing_need_cents=300_000)
    document_and_verify_damage(case["id"], "STRUCTURE", 8_500_000, "Foundation and framing")
    document_and_verify_damage(case["id"], "ROOF", 4_000_000, "Full roof replacement")
    document_and_verify_damage(case["id"], "CONTENTS", 1_800_000, "Household contents")
    document_and_verify_damage(case["id"], "ACCESSIBILITY", 600_000, "Ramp and grab bars")
    record_assistance(
        case["id"],
        source_type="INSURANCE_SETTLEMENT",
        purpose_code="STRUCTURE_REPAIR",
        awarded_cents=7_000_000,
        received_on="2026-07-15",
        documentation_status="DOCUMENTED",
    )
    record_assistance(
        case["id"],
        source_type="FEMA_IA",
        purpose_code="TEMPORARY_HOUSING",
        awarded_cents=900_000,
        received_on="2026-07-20",
        documentation_status="DOCUMENTED",
    )
    record_assistance(
        case["id"],
        source_type="NONPROFIT_GRANT",
        purpose_code="CONTENTS_REPLACEMENT",
        awarded_cents=400_000,
        received_on="2026-07-22",
        documentation_status="DOCUMENTED",
    )
    record_assistance(
        case["id"],
        source_type="SBA_LOAN",
        purpose_code="STRUCTURE_REPAIR",
        awarded_cents=1_000_000,
        received_on="2026-07-25",
        documentation_status="DISPUTED",
    )
    return {"survivor": survivor, "case": case}


def test_purpose_matched_determination_floors_each_bucket_before_summing(api):
    """PRD §3.3: "Under `PURPOSE_MATCHED`, the buckets are reduced independently
    and each result is floored at zero before they are added: for each bucket in the
    fixed order `STRUCTURE_REPAIR`, `CONTENTS_REPLACEMENT`, `ACCESSIBILITY_MOD`,
    `TEMPORARY_HOUSING`, take that bucket's need less that bucket's offset, treat
    any negative result as zero, and sum the four floored figures into
    `unmet_need_total_cents`."

    Design: Difficulty/dual_variant_calc/unmet_need_purpose_matched_vs_pooled_diverge_by_600000
    """
    scenario = _setup_case_with_stranded_housing_over_award()

    snapshot = validate_success(
        api.create_assessment(
            scenario["case"]["id"], {"variant": "PURPOSE_MATCHED"}, TEST_USERS["case_manager_headers"]
        ),
        201,
    )

    assert_unmet_need_assessment(snapshot)
    assert snapshot["variant"] == "PURPOSE_MATCHED"
    assert snapshot["bucket_need_cents"] == {
        "STRUCTURE_REPAIR": 12_000_000,
        "CONTENTS_REPLACEMENT": 1_500_000,
        "ACCESSIBILITY_MOD": 600_000,
        "TEMPORARY_HOUSING": 300_000,
    }
    assert snapshot["bucket_offset_cents"] == {
        "STRUCTURE_REPAIR": 7_000_000,
        "CONTENTS_REPLACEMENT": 400_000,
        "ACCESSIBILITY_MOD": 0,
        "TEMPORARY_HOUSING": 900_000,
    }
    # 5000000 + 1100000 + 600000 + 0 — the 600000 housing surplus is stranded.
    assert snapshot["unmet_need_total_cents"] == 6_700_000


def test_pooled_determination_nets_every_bucket_before_flooring_once(api):
    """PRD §3.3: "Under `POOLED`, all four needs are added into one total, all four
    offsets are added into one total, the offset total is subtracted from the need
    total, and the single result is floored at zero into `unmet_need_total_cents`."

    Design: Difficulty/dual_variant_calc/unmet_need_purpose_matched_vs_pooled_diverge_by_600000
    """
    scenario = _setup_case_with_stranded_housing_over_award()
    purpose_matched = run_assessment(scenario["case"]["id"], "PURPOSE_MATCHED")

    pooled = validate_success(
        api.create_assessment(
            scenario["case"]["id"], {"variant": "POOLED"}, TEST_USERS["case_manager_headers"]
        ),
        201,
    )

    assert_unmet_need_assessment(pooled)
    assert pooled["variant"] == "POOLED"
    # 14400000 of need less 8300000 of offsets, floored once.
    assert pooled["unmet_need_total_cents"] == 6_100_000
    assert pooled["bucket_need_cents"] == purpose_matched["bucket_need_cents"]
    assert pooled["bucket_offset_cents"] == purpose_matched["bucket_offset_cents"]
    assert (
        purpose_matched["unmet_need_total_cents"] - pooled["unmet_need_total_cents"] == 600_000
    )


def test_disputed_assistance_offsets_nothing_under_either_variant(api):
    """PRD §3.3: "`UNDOCUMENTED` and `DISPUTED` rows are excluded, and
    `is_excluded_from_dob` is irrelevant here — it affects only the
    duplication-of-benefits check described in §3.6."

    Design: Difficulty/dual_variant_calc/unmet_need_purpose_matched_vs_pooled_diverge_by_600000
    """
    scenario = _setup_case_with_stranded_housing_over_award()

    purpose_matched = validate_success(
        api.create_assessment(
            scenario["case"]["id"], {"variant": "PURPOSE_MATCHED"}, TEST_USERS["case_manager_headers"]
        ),
        201,
    )
    pooled = validate_success(
        api.create_assessment(
            scenario["case"]["id"], {"variant": "POOLED"}, TEST_USERS["case_manager_headers"]
        ),
        201,
    )

    # 7000000 + 900000 + 400000; the 1000000 DISPUTED award is in neither total.
    for snapshot in (purpose_matched, pooled):
        assert snapshot["total_documented_assistance_cents"] == 8_300_000
        assert snapshot["bucket_offset_cents"]["STRUCTURE_REPAIR"] == 7_000_000
        assert snapshot["verified_damage_total_cents"] == 14_100_000


def _setup_undersized_crew_against_a_weighted_project() -> Dict[str, Any]:
    """A permitted phase needing 1350 weighted trade hours and a 12-member crew.

    Every declared trade is represented in the crew's profile, but the crew cannot
    deliver the framing and roofing hours the phase asks for.
    """
    set_clock()
    survivor = create_survivor(
        household_name="Nakamura Household",
        primary_contact_phone="555-0103",
        household_size=3,
        income_band="LOW",
        head_of_household_age=44,
    )
    case = create_case(survivor["id"])
    project = create_project(
        case["id"],
        required_trade_hours={"FRAMING": 300, "ROOFING": 150, "GENERAL_LABOR": 300},
        estimated_material_cents=900_000,
        critical_trades=["FRAMING"],
    )
    permit_project(project["id"], "PB-3301")
    group = create_group(
        group_name="Redwood Baptist Crew",
        home_organization="Redwood Baptist",
        member_count=12,
        skill_profile={"FRAMING": 5, "ROOFING": 2, "GENERAL_LABOR": 12},
        requires_housing=False,
    )
    return {"case": case, "project": project, "group": group}


def test_coverage_weighted_skill_fit_counts_deliverable_hours(api):
    """PRD §3.8: "Under `COVERAGE_WEIGHTED`, the crew's capacity for a trade is the
    count of members qualified in that trade — taken from the group's
    `skill_profile`, treated as 0 when the trade is absent from the profile —
    multiplied by six volunteer hours per day, multiplied by `day_count`."

    Design: Difficulty/dual_variant_calc/skill_fit_coverage_weighted_6000_vs_headcount_weighted_10000
    """
    scenario = _setup_undersized_crew_against_a_weighted_project()

    report = validate_success(
        api.get_skill_fit(
            scenario["project"]["id"],
            COORDINATOR,
            params={
                "group_id": scenario["group"]["id"],
                "variant": "COVERAGE_WEIGHTED",
                "arrival_date": "2026-09-07",
                "departure_date": "2026-09-11",
            },
        )
    )

    assert_skill_fit_report(report)
    assert report["variant"] == "COVERAGE_WEIGHTED"
    assert report["day_count"] == 5
    # capacities 150/60/360 covered against 300/150/300 -> 3*150 + 60 + 300.
    assert report["weighted_covered"] == 810
    assert report["weighted_required"] == 1350
    assert report["score_bps"] == 6000
    assert report["meets_minimum"] is True


def test_headcount_weighted_skill_fit_counts_only_representation(api):
    """PRD §3.8: "Under `HEADCOUNT_WEIGHTED`, the numerator is the sum over all
    trades of the trade's weight multiplied by one when the group has at least one
    qualified member in that trade and zero when it has none; the denominator is the
    sum over all trades of the trade's weight."

    Design: Difficulty/dual_variant_calc/skill_fit_coverage_weighted_6000_vs_headcount_weighted_10000
    """
    scenario = _setup_undersized_crew_against_a_weighted_project()
    window = {"arrival_date": "2026-09-07", "departure_date": "2026-09-11"}

    coverage = validate_success(
        api.get_skill_fit(
            scenario["project"]["id"],
            COORDINATOR,
            params={"group_id": scenario["group"]["id"], "variant": "COVERAGE_WEIGHTED", **window},
        )
    )
    headcount = validate_success(
        api.get_skill_fit(
            scenario["project"]["id"],
            COORDINATOR,
            params={"group_id": scenario["group"]["id"], "variant": "HEADCOUNT_WEIGHTED", **window},
        )
    )

    assert_skill_fit_report(headcount)
    assert headcount["variant"] == "HEADCOUNT_WEIGHTED"
    # 3 for critical FRAMING + 1 ROOFING + 1 GENERAL_LABOR, all represented.
    assert headcount["weighted_required"] == 5
    assert headcount["weighted_covered"] == 5
    assert headcount["score_bps"] == 10000
    assert headcount["meets_minimum"] is True
    assert headcount["day_count"] == coverage["day_count"] == 5
    assert headcount["project_id"] == coverage["project_id"] == scenario["project"]["id"]
    assert headcount["group_id"] == coverage["group_id"] == scenario["group"]["id"]
    assert headcount["score_bps"] > coverage["score_bps"]
