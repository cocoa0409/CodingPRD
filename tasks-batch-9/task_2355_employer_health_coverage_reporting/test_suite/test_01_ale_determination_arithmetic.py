"""Applicable-large-employer determination arithmetic.

The frozen per-member full-time-equivalent quotient, the pinned rounding order
of each month's group figure, the annual average and the inclusive threshold
comparison that decides applicable-large-employer status, plus the two counting
bases the determination can be run on.
"""

import pytest

from test_helpers import (
    assert_controlled_group,
    assert_monthly_headcount,
    factories,
    fixtures,
    get_success_data,
    make_compliance_officer_headers,
    validate_success,
)

CO = make_compliance_officer_headers()

# Twelve prior-year months of 20 full-time employees and no part-time hours:
# a frozen member_fte of 20.00 every month.
SMALL_MEMBER = {
    "ein": "111111111",
    "legal_name": "Cascade Small Co",
    "ownership_pct": 60,
    "full_time_employee_count": 20,
    "part_time_hours_total": 0,
    "total_employee_count": 25,
}
# Twelve prior-year months of 40 full-time employees and 1200 part-time hours:
# a frozen member_fte of 50.00 every month.
LARGE_MEMBER = {
    "ein": "222222222",
    "legal_name": "Cascade Large Co",
    "ownership_pct": 40,
    "full_time_employee_count": 40,
    "part_time_hours_total": 1200,
    "total_employee_count": 70,
}
# Two identical members whose part-time quotient 1190 / 120 does not land on a
# whole cent: 9.9166... rounds half up to 9.92, giving member_fte 29.92.
MILL_NORTH = {
    "ein": "444444441",
    "legal_name": "Twin Mills North",
    "ownership_pct": 50,
    "full_time_employee_count": 20,
    "part_time_hours_total": 1190,
    "total_employee_count": 45,
}
MILL_SOUTH = dict(MILL_NORTH, ein="444444442", legal_name="Twin Mills South")
# 1200 / 120 is exactly 10.00, so member_fte lands exactly on the threshold.
AT_THRESHOLD_MEMBER = {
    "ein": "151515151",
    "legal_name": "At Threshold Co",
    "ownership_pct": 100,
    "full_time_employee_count": 40,
    "part_time_hours_total": 1200,
    "total_employee_count": 60,
}
# 1199 / 120 is 9.9916..., which rounds half up to 9.99 and lands one cent short.
BELOW_THRESHOLD_MEMBER = {
    "ein": "161616161",
    "legal_name": "Below Threshold Co",
    "ownership_pct": 100,
    "full_time_employee_count": 40,
    "part_time_hours_total": 1199,
    "total_employee_count": 60,
}


# ---------------------------------------------------------------------------
# Local composition over test_helpers.fixtures
# ---------------------------------------------------------------------------
def _season_group_with_headcounts(api, member_specs, group_name="Cascade Holdings"):
    """A season, a fresh controlled group and one active member per spec, each
    member carrying twelve prior-year headcount months of the spec's counts."""
    season = fixtures.create_filing_season(api)
    group = fixtures.create_controlled_group(api, season["id"], name=group_name)
    members = []
    for spec in member_specs:
        member = fixtures.create_group_member(
            api,
            group["id"],
            ein=spec["ein"],
            legal_name=spec["legal_name"],
            ownership_pct=spec["ownership_pct"],
            measurement_method="MONTHLY",
        )
        fixtures.record_headcounts(
            api,
            member["id"],
            count_year="PRIOR_YEAR",
            full_time_employee_count=spec["full_time_employee_count"],
            part_time_hours_total=spec["part_time_hours_total"],
            total_employee_count=spec["total_employee_count"],
        )
        members.append(member)
    return season, group, members


def _prior_year_headcounts(api, member_id):
    """Headcount rows are reachable only through the filtered list read."""
    return get_success_data(
        api.list_monthly_headcounts(
            CO,
            params={"group_member_id": member_id, "count_year": "PRIOR_YEAR", "limit": 100},
        )
    )


def _determine(api, group_id, expected_version, **overrides):
    payload = factories.ale_determination_payload(expected_version, **overrides)
    return validate_success(api.run_ale_determination(group_id, payload, CO), 200)


# ---------------------------------------------------------------------------
# The two counting bases
# ---------------------------------------------------------------------------
def test_aggregated_basis_sums_every_active_member_to_ale(api):
    """PRD §3.2: "Under the aggregated basis the counted set is every `ACTIVE`
    member of the group; under the single-member basis it is exactly the named
    member."
    PRD §3.2: "The twelve stored monthly figures are then summed, divided by 12,
    and rounded half up to two decimal places to give `annual_average_fte_raw`;
    truncating that value gives the whole-number `annual_average_fte` that is
    compared against the threshold of 50 full-time-equivalent employees."
    PRD §3.2: "When `annual_average_fte` is at least 50 but that exception does
    not apply, the group becomes `DETERMINED_ALE` with `ale_reason` of
    `THRESHOLD_MET` and `seasonal_exception_applied` false."

    Design: Difficulty/dual_variant_calc/aggregated_basis_vs_single_member_basis_ale_status
    """
    _, group, _members = _season_group_with_headcounts(api, [SMALL_MEMBER, LARGE_MEMBER])

    determined = _determine(api, group["id"], group["version"], basis="AGGREGATED")

    assert_controlled_group(
        determined,
        determination_state="DETERMINED_ALE",
        determination_basis="AGGREGATED",
        ale_reason="THRESHOLD_MET",
        seasonal_exception_applied=False,
        annual_average_fte=70,
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(70.00, abs=0.01), (
        f"20.00 + 50.00 per month must average 70.00, got "
        f"{determined['annual_average_fte_raw']}"
    )
    assert determined["monthly_group_fte"] == [70] * 12, (
        f"expected twelve monthly group figures of 70, got {determined['monthly_group_fte']}"
    )


def test_single_member_basis_counts_only_the_named_member_below_threshold(api):
    """PRD §3.2: "Under the aggregated basis the counted set is every `ACTIVE`
    member of the group; under the single-member basis it is exactly the named
    member."
    PRD §3.2: "When `annual_average_fte` is below 50, the group becomes
    `DETERMINED_NON_ALE` with `ale_reason` of `BELOW_THRESHOLD` and
    `seasonal_exception_applied` false."

    Design: Difficulty/dual_variant_calc/aggregated_basis_vs_single_member_basis_ale_status
    """
    _, group, members = _season_group_with_headcounts(api, [SMALL_MEMBER, LARGE_MEMBER])
    member_a = members[0]

    determined = _determine(
        api,
        group["id"],
        group["version"],
        basis="SINGLE_MEMBER",
        single_member_id=member_a["id"],
    )

    assert_controlled_group(
        determined,
        determination_state="DETERMINED_NON_ALE",
        determination_basis="SINGLE_MEMBER",
        ale_reason="BELOW_THRESHOLD",
        seasonal_exception_applied=False,
        annual_average_fte=20,
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(20.00, abs=0.01), (
        f"the named member alone averages 20.00, got {determined['annual_average_fte_raw']}"
    )
    assert determined["monthly_group_fte"] == [20] * 12, (
        f"the larger member must not be counted, got {determined['monthly_group_fte']}"
    )


def test_rerunning_determination_replaces_the_verdict_and_advances_version(api):
    """PRD §3.2: "Whichever branch fires, the determination writes
    `monthly_group_fte`, `annual_average_fte_raw`, `annual_average_fte`,
    `determination_basis` (`AGGREGATED` or `SINGLE_MEMBER`), `ale_reason` and
    `seasonal_exception_applied`, stamps `determined_at` from the logical clock
    and `last_determination_user_id` from the acting officer, and increments the
    group's `version` by one."
    PRD §3.2: "Re-running a determination on a group already in `DETERMINED_ALE`
    is a legitimate self-loop that overwrites the previous outputs with the new
    basis and again advances `version`; this is precisely why the write is
    version-guarded."

    Design: Difficulty/dual_variant_calc/aggregated_basis_vs_single_member_basis_ale_status
    """
    _, group, members = _season_group_with_headcounts(api, [SMALL_MEMBER, LARGE_MEMBER])
    member_a = members[0]

    first = _determine(api, group["id"], group["version"], basis="AGGREGATED")
    assert first["determination_state"] == "DETERMINED_ALE", (
        f"aggregated basis must reach ALE first, got {first['determination_state']}"
    )

    _determine(
        api,
        group["id"],
        fixtures.current_group_version(api, group["id"]),
        basis="SINGLE_MEMBER",
        single_member_id=member_a["id"],
    )

    reread = fixtures.read_group(api, group["id"])
    assert_controlled_group(
        reread,
        expected_version=3,
        determination_state="DETERMINED_NON_ALE",
        determination_basis="SINGLE_MEMBER",
        ale_reason="BELOW_THRESHOLD",
        annual_average_fte=20,
    )
    assert reread["annual_average_fte_raw"] == pytest.approx(20.00, abs=0.01), (
        f"the re-run must overwrite the aggregated average, got "
        f"{reread['annual_average_fte_raw']}"
    )
    assert reread["determined_at"] is not None, "the re-run must stamp determined_at"


# ---------------------------------------------------------------------------
# The pinned rounding order
# ---------------------------------------------------------------------------
def test_member_fte_rounds_the_part_time_quotient_half_up_to_two_decimals(api):
    """PRD §3.1: "Each created row freezes its own `member_fte` at creation: the
    month's `full_time_employee_count` plus the month's `part_time_hours_total`
    divided by 120 hours and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/fte_rounding_order_two_members_at_1190_part_time_hours
    """
    _, _group, members = _season_group_with_headcounts(
        api, [MILL_NORTH, MILL_SOUTH], group_name="Twin Mills Group"
    )

    for member in members:
        rows = _prior_year_headcounts(api, member["id"])
        assert len(rows) == 12, f"expected twelve prior-year rows, got {len(rows)}"
        for row in rows:
            assert_monthly_headcount(
                row,
                count_year="PRIOR_YEAR",
                full_time_employee_count=20,
                part_time_hours_total=1190,
            )
            assert row["member_fte"] == pytest.approx(29.92, abs=0.01), (
                f"20 + round_half_up(1190 / 120) is 29.92, got {row['member_fte']} "
                f"for month {row['month']}"
            )


def test_monthly_group_fte_sums_members_before_truncating(api):
    """PRD §3.2: "Those per-member values are added together at full two-decimal
    precision, the sum itself is rounded half up to two decimal places, and only
    then is the month's group figure truncated to a whole number and stored in
    `monthly_group_fte`, whose first element is January of the prior year."
    PRD §3.2: "Truncating each member before summing is the wrong order and
    yields a smaller count."
    PRD §3.2: "When `annual_average_fte` is at least 50 but that exception does
    not apply, the group becomes `DETERMINED_ALE` with `ale_reason` of
    `THRESHOLD_MET` and `seasonal_exception_applied` false."

    Design: Difficulty/combinatorial_formula/fte_rounding_order_two_members_at_1190_part_time_hours
    """
    _, group, _members = _season_group_with_headcounts(
        api, [MILL_NORTH, MILL_SOUTH], group_name="Twin Mills Group"
    )

    determined = _determine(api, group["id"], group["version"], basis="AGGREGATED")

    assert determined["monthly_group_fte"] == [59] * 12, (
        f"29.92 + 29.92 is 59.84, truncating to 59 in every month, got "
        f"{determined['monthly_group_fte']}"
    )
    assert determined["monthly_group_fte"][0] != 58, (
        "58 is the January figure a truncate-per-member-then-sum order would produce"
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(59.00, abs=0.01), (
        f"twelve figures of 59 average 59.00, got {determined['annual_average_fte_raw']}"
    )
    assert_controlled_group(
        determined,
        determination_state="DETERMINED_ALE",
        ale_reason="THRESHOLD_MET",
        seasonal_exception_applied=False,
        annual_average_fte=59,
    )


# ---------------------------------------------------------------------------
# The threshold boundary
# ---------------------------------------------------------------------------
def test_annual_average_of_exactly_fifty_meets_the_threshold(api):
    """PRD §2.9: "Threshold comparisons are inclusive unless stated otherwise: a
    count that exactly equals the applicable-large-employer threshold meets it,
    hours exactly equal to the monthly hours threshold make a month full time, a
    required contribution exactly equal to an affordability threshold is
    affordable, and an aggregate return count exactly equal to the
    electronic-filing threshold requires electronic transmission."
    PRD §3.2: "When `annual_average_fte` is at least 50 but that exception does
    not apply, the group becomes `DETERMINED_ALE` with `ale_reason` of
    `THRESHOLD_MET` and `seasonal_exception_applied` false."

    Design: Difficulty/boundary_precision_check/ale_annual_average_at_exactly_fifty_is_ale
    """
    _, group, members = _season_group_with_headcounts(
        api, [AT_THRESHOLD_MEMBER], group_name="At Threshold Group"
    )

    for row in _prior_year_headcounts(api, members[0]["id"]):
        assert row["member_fte"] == pytest.approx(50.00, abs=0.01), (
            f"40 + 1200 / 120 is exactly 50.00, got {row['member_fte']} for month "
            f"{row['month']}"
        )

    determined = _determine(api, group["id"], group["version"], basis="AGGREGATED")

    assert determined["monthly_group_fte"] == [50] * 12, (
        f"expected twelve monthly group figures of 50, got {determined['monthly_group_fte']}"
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(50.00, abs=0.01), (
        f"expected an annual average of 50.00, got {determined['annual_average_fte_raw']}"
    )
    assert_controlled_group(
        determined,
        determination_state="DETERMINED_ALE",
        ale_reason="THRESHOLD_MET",
        seasonal_exception_applied=False,
        annual_average_fte=50,
    )


def test_annual_average_one_cent_short_of_fifty_falls_below_the_threshold(api):
    """PRD §3.1: "Each created row freezes its own `member_fte` at creation: the
    month's `full_time_employee_count` plus the month's `part_time_hours_total`
    divided by 120 hours and rounded half up to two decimal places."
    PRD §3.2: "When `annual_average_fte` is below 50, the group becomes
    `DETERMINED_NON_ALE` with `ale_reason` of `BELOW_THRESHOLD` and
    `seasonal_exception_applied` false."

    Design: Difficulty/boundary_precision_check/ale_annual_average_at_exactly_fifty_is_ale
    """
    _, group, members = _season_group_with_headcounts(
        api, [BELOW_THRESHOLD_MEMBER], group_name="Below Threshold Group"
    )

    for row in _prior_year_headcounts(api, members[0]["id"]):
        assert row["member_fte"] == pytest.approx(49.99, abs=0.01), (
            f"40 + round_half_up(1199 / 120) is 49.99, got {row['member_fte']} for "
            f"month {row['month']}"
        )

    determined = _determine(api, group["id"], group["version"], basis="AGGREGATED")

    assert determined["monthly_group_fte"] == [49] * 12, (
        f"49.99 truncates to 49 in every month, got {determined['monthly_group_fte']}"
    )
    assert determined["annual_average_fte_raw"] == pytest.approx(49.00, abs=0.01), (
        f"twelve figures of 49 average 49.00, got {determined['annual_average_fte_raw']}"
    )
    assert_controlled_group(
        determined,
        determination_state="DETERMINED_NON_ALE",
        ale_reason="BELOW_THRESHOLD",
        seasonal_exception_applied=False,
        annual_average_fte=49,
    )
