"""Edge behaviour of the program's computed figures.

This file exercises the arithmetic the contract pins: customer-responsibility
matrix coverage and its two-step rounding, the engagement pricing rollup at a
tier boundary and on a third-decimal five, severity-driven remediation
deadlines, the residual risk population and its disposition weighting,
preliminary impact aggregation as categories come and go, scan timeliness
grading, test-slot interval geometry, and the frozen package snapshot beside
the live authorization ledger.
"""

import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as tu
from test_helpers.api_errors import (
    ERR_NO_CONFIRMED_DATA_CATEGORY,
    ERR_TEST_SLOT_OVERLAP,
)

# The clock the reference-data builders stand the program up at, and the clock
# the assessment report and the authorization decision land on.
SETUP_CLOCK = fx.SETUP_CLOCK
AUTHORIZATION_CLOCK = fx.AUTHORIZATION_CLOCK

#: The two documented controls that leave family AC half documented.
HALF_DOCUMENTED_CONTROLS = (("AC-2", "AC"), ("SC-7", "SC"))


def _coverage(client, offering_id):
    """The live coverage computation for one offering."""
    return validate_success(
        client.get_crm_coverage(offering_id, tu.CSP_LEAD_HEADERS), 200
    )


def _risk_summary(client, authorization_id):
    """The live risk-summary read beside the stored score."""
    return validate_success(
        client.get_risk_summary(authorization_id, tu.CSP_LEAD_HEADERS), 200
    )


# ---------------------------------------------------------------------------
# Customer responsibility matrix coverage
# ---------------------------------------------------------------------------


def test_crm_coverage_walks_the_families_in_priority_rank_order_before_anything_is_documented(
    client,
):
    """An undocumented offering reads 0.00 coverage while still carrying the full requirement weight.

    PRD: "The computation walks the families of the offering's bound baseline in ascending `priority_rank`, breaking ties by `family_code` in ascending alphabetical order."

    Design: Corner/calculations/crm_coverage_read_returns_the_weighted_mean_for_a_half_documented_family
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))

    coverage = _coverage(client, env["offering_id"])

    # AC requires two controls and SC one, and nothing is documented yet.
    a.assert_money(
        coverage["overall_coverage_pct"],
        a.expected_overall_coverage([(0, 2), (0, 1)]),
        "overall_coverage_pct",
    )
    a.assert_money(coverage["overall_coverage_pct"], 0.00, "overall_coverage_pct")
    a.assert_integer(coverage["weight_total"], 3, "weight_total")
    breakdown = coverage["family_breakdown"]
    assert [row["family_code"] for row in breakdown] == ["AC", "SC"], (
        f"family_breakdown must follow priority_rank, got {breakdown}"
    )


def test_crm_coverage_returns_the_weighted_mean_for_a_half_documented_family(client):
    """One of two AC controls and the single SC control documented reads 66.67 overall.

    PRD: "If the weight total is zero, overall coverage is 0.00; otherwise overall coverage is the weighted sum divided by the weight total, rounded half up to two decimal places."

    Design: Corner/calculations/crm_coverage_read_returns_the_weighted_mean_for_a_half_documented_family
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))
    fx.seed_control_implementations(client, env, HALF_DOCUMENTED_CONTROLS)

    coverage = _coverage(client, env["offering_id"])

    # (50.00 * 2 + 100.00 * 1) / 3 = 66.67, not the 66.67-by-accident of a
    # straight documented/required ratio over the whole baseline (2/3 = 66.67
    # only because these weights happen to agree; the family percentages are
    # what the contract sums).
    a.assert_money(
        coverage["overall_coverage_pct"],
        a.expected_overall_coverage([(1, 2), (1, 1)]),
        "overall_coverage_pct",
    )
    a.assert_money(coverage["overall_coverage_pct"], 66.67, "overall_coverage_pct")
    a.assert_integer(coverage["weight_total"], 3, "weight_total")

    by_family = {row["family_code"]: row for row in coverage["family_breakdown"]}
    assert sorted(by_family) == ["AC", "SC"], (
        f"the breakdown must carry one row per non-zero family, got {sorted(by_family)}"
    )


def test_crm_coverage_is_stamped_from_the_logical_clock_and_writes_nothing(client):
    """The coverage read is evaluated at the logical clock and leaves the offering untouched.

    PRD: "The computed coverage read returns `overall_coverage_pct`, the `weight_total` it was divided by, a per-family `family_breakdown`, and the `evaluated_at` instant taken from the logical clock."

    Design: Corner/calculations/crm_coverage_read_returns_the_weighted_mean_for_a_half_documented_family
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))
    # create 1 + category 2 + confirm 3 + determination 4
    version_before = fx.offering_version(client, env["offering_id"])
    a.assert_integer(version_before, 4, "offering version before the read")

    coverage = _coverage(client, env["offering_id"])

    a.assert_instant(coverage["evaluated_at"], SETUP_CLOCK, "evaluated_at")
    a.assert_integer(
        fx.offering_version(client, env["offering_id"]),
        version_before,
        "offering version after the read",
    )


# ---------------------------------------------------------------------------
# Residual risk: the included population
# ---------------------------------------------------------------------------


def _authorized_with_three_findings(client):
    """A live authorization carrying HIGH, MODERATE and LOW findings.

    The HIGH item is walked to IN_REMEDIATION and the MODERATE one to
    AWAITING_VERIFICATION, so all three remediation states that contribute are
    represented.
    """
    env = fx.seed_authorized_offering(client)
    fx.seed_poam_item(
        client,
        env,
        severity="HIGH",
        control_id="AC-2",
        detected_at=AUTHORIZATION_CLOCK,
        key="high",
    )
    fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        control_id="AC-3",
        detected_at=AUTHORIZATION_CLOCK,
        key="moderate",
    )
    fx.seed_poam_item(
        client,
        env,
        severity="LOW",
        control_id="SC-7",
        detected_at=AUTHORIZATION_CLOCK,
        key="low",
    )
    fx.drive_remediation(client, env, env["high_id"], ["START"])
    fx.drive_remediation(client, env, env["moderate_id"], ["START", "SUBMIT_EVIDENCE"])
    return env


def test_open_and_in_flight_findings_all_contribute_to_the_residual_risk_score(client):
    """A finding in remediation and one awaiting verification weigh exactly as much as an open one.

    PRD: "The included population is the offering's findings whose `remediation_status` is `OPEN`, `IN_REMEDIATION` or `AWAITING_VERIFICATION`; a `CLOSED` finding never contributes regardless of its `closure_reason`."

    Design: Corner/calculations/closed_findings_leave_the_residual_risk_input_set_for_good
    """
    env = _authorized_with_three_findings(client)

    summary = _risk_summary(client, env["authorization_id"])

    population = [
        {
            "severity": "HIGH",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "HIGH"),
        },
        {
            "severity": "MODERATE",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "MODERATE"),
        },
        {
            "severity": "LOW",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "LOW"),
        },
    ]
    # 10.0 IN_REMEDIATION + 4.0 AWAITING_VERIFICATION + 1.0 OPEN, none overdue.
    a.assert_money(
        summary["residual_risk_score"],
        a.expected_residual_risk(population, AUTHORIZATION_CLOCK),
        "residual_risk_score",
    )
    a.assert_money(summary["residual_risk_score"], 15.00, "residual_risk_score")
    a.assert_money(
        summary["stored_residual_risk_score"], 15.00, "stored_residual_risk_score"
    )
    assert summary["poam_risk_tier"] == a.expected_risk_tier(15.00) == "MODERATE", (
        f"score 15.00 implies tier MODERATE, got {summary['poam_risk_tier']}"
    )
    a.assert_integer(summary["open_findings_count"], 3, "open_findings_count")
    a.assert_integer(summary["overdue_high_count"], 0, "overdue_high_count")


def test_verified_closure_removes_only_its_own_contribution(client):
    """Closing the LOW finding drops exactly its 1.00 and leaves the other two contributing in full.

    PRD: "`VERIFY_CLOSE` moves `AWAITING_VERIFICATION → CLOSED`, sets `closure_reason` to `REMEDIATED`, and recomputes the authorization's `open_findings_count`, `closed_findings_count` and `residual_risk_score`; it is refused with `ERR_DEVIATION_PENDING_ON_ITEM` while any deviation on the item is still in `SUBMITTED`, `BOARD_REVIEW` or `AGENCY_REVIEW`."

    Design: Corner/calculations/closed_findings_leave_the_residual_risk_input_set_for_good
    """
    env = _authorized_with_three_findings(client)

    closed = fx.drive_remediation(
        client, env, env["low_id"], ["START", "SUBMIT_EVIDENCE", "VERIFY_CLOSE"]
    )

    assert closed["remediation_status"] == "CLOSED", closed
    assert closed["closure_reason"] == "REMEDIATED", closed

    summary = _risk_summary(client, env["authorization_id"])
    remaining = [
        {
            "severity": "HIGH",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "HIGH"),
        },
        {
            "severity": "MODERATE",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "MODERATE"),
        },
    ]
    a.assert_money(
        summary["residual_risk_score"],
        a.expected_residual_risk(remaining, AUTHORIZATION_CLOCK),
        "residual_risk_score",
    )
    a.assert_money(summary["residual_risk_score"], 14.00, "residual_risk_score")
    # A population filtered on OPEN alone would have reported 10.00.
    assert abs(float(summary["residual_risk_score"]) - 10.00) > 0.01, (
        "the IN_REMEDIATION and AWAITING_VERIFICATION findings must keep contributing"
    )
    a.assert_integer(summary["open_findings_count"], 2, "open_findings_count")
    assert summary["poam_risk_tier"] == "MODERATE", summary

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(authorization["open_findings_count"], 2, "open_findings_count")
    a.assert_integer(authorization["closed_findings_count"], 1, "closed_findings_count")
    a.assert_integer(authorization["total_findings_count"], 3, "total_findings_count")
    a.assert_integer(
        authorization["risk_accepted_findings_count"], 0, "risk_accepted_findings_count"
    )
    a.assert_money(
        authorization["residual_risk_score"], 14.00, "stored residual_risk_score"
    )
    a.assert_all_invariants(authorization=authorization)


def test_the_remediation_walk_never_touches_the_risk_dimension(client):
    """Starting work and submitting evidence leave both findings at risk_disposition NONE.

    PRD: "Starting remediation work moves only the remediation dimension; filing a deviation moves only the risk dimension."

    Design: Corner/calculations/closed_findings_leave_the_residual_risk_input_set_for_good
    """
    env = _authorized_with_three_findings(client)

    high = fx.read_poam_item(client, env["high_id"])
    moderate = fx.read_poam_item(client, env["moderate_id"])

    assert high["remediation_status"] == "IN_REMEDIATION", high
    assert high["risk_disposition"] == "NONE", high
    assert moderate["remediation_status"] == "AWAITING_VERIFICATION", moderate
    assert moderate["risk_disposition"] == "NONE", moderate


# ---------------------------------------------------------------------------
# Remediation deadlines
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "severity, expected_deadline_at",
    [
        ("HIGH", "2026-03-03T00:00:00Z"),
        ("MODERATE", "2026-05-02T00:00:00Z"),
        ("LOW", "2026-07-31T00:00:00Z"),
    ],
)
def test_severity_base_allowances_land_on_three_distinct_deadlines(
    client, severity, expected_deadline_at
):
    """A finding detected 2026-02-01 is due 30, 90 or 180 real calendar days later.

    PRD: "Base allowances are 30 days for a `HIGH` finding, 90 days for a `MODERATE` finding and 180 days for a `LOW` finding."

    Design: Corner/calculations/the_three_base_day_constants_land_on_three_distinct_deadlines
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))

    item = validate_success(
        client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"],
                control_id="AC-2",
                severity=severity,
                detected_at=SETUP_CLOCK,
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(SETUP_CLOCK, severity),
        f"{severity} deadline_at",
    )
    a.assert_instant(item["deadline_at"], expected_deadline_at, f"{severity} deadline_at")
    a.assert_integer(
        item["granted_extension_days"], 0, "granted_extension_days"
    )
    assert a.days_between(item["anchor_at"], item["deadline_at"]) == c.BASE_DAYS[
        severity
    ], f"{severity} deadline must sit {c.BASE_DAYS[severity]} days past the anchor"


def test_a_new_finding_anchors_on_its_detection_instant(client):
    """anchor_at equals detected_at, and the deadline is measured from that anchor.

    PRD: "At creation an item's `anchor_at` equals its `detected_at`, and its `deadline_at` is `anchor_at` advanced by the severity base allowance and then by `granted_extension_days` further days."

    Design: Corner/calculations/the_three_base_day_constants_land_on_three_distinct_deadlines
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))

    item = validate_success(
        client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"],
                control_id="AC-3",
                severity="MODERATE",
                detected_at=SETUP_CLOCK,
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_instant(item["anchor_at"], SETUP_CLOCK, "anchor_at")
    a.assert_instant(item["detected_at"], SETUP_CLOCK, "detected_at")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(item["anchor_at"], "MODERATE", 0),
        "deadline_at",
    )
    a.assert_instant(item["deadline_at"], "2026-05-02T00:00:00Z", "deadline_at")


def test_a_directly_filed_finding_opens_with_the_declared_defaults(client):
    """A filed finding opens OPEN, undisposed, unclosed and never reopened.

    PRD: "Every new item opens with `remediation_status` `OPEN`, `risk_disposition` `NONE`, `closure_reason` null, `granted_extension_days` 0 and `reopen_count` 0."

    Design: Corner/calculations/the_three_base_day_constants_land_on_three_distinct_deadlines
    """
    env = fx.seed_categorized_offering(client, fx.seed_reference_data(client))

    item = validate_success(
        client.create_poam_item(
            f.build_poam_item_payload(
                env["offering_id"],
                control_id="SC-7",
                severity="LOW",
                detected_at=SETUP_CLOCK,
            ),
            env["lead_headers"],
        ),
        201,
    )

    assert item["remediation_status"] == "OPEN", item
    assert item["risk_disposition"] == "NONE", item
    assert item["closure_reason"] is None, item
    a.assert_integer(item["granted_extension_days"], 0, "granted_extension_days")
    a.assert_integer(item["reopen_count"], 0, "reopen_count")
    assert item["source"] == "SELF_IDENTIFIED", item


# ---------------------------------------------------------------------------
# Engagement pricing
# ---------------------------------------------------------------------------


def _priced_engagement(client, *, labor_cost_usd, contracted_hours=900.00, env=None):
    """Create one engagement on a PATH_SELECTED MODERATE offering and return it."""
    if env is None:
        env = fx.seed_path_selected_offering(client, fx.seed_reference_data(client))
    return env, validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["offering_id"],
                contracted_hours=contracted_hours,
                labor_cost_usd=labor_cost_usd,
            ),
            env["lead_headers"],
        ),
        201,
    )


def test_program_surcharge_rounds_a_third_decimal_five_half_up(client):
    """Labor of 100000.25 at 0.06 is exactly 6000.015 and must round up to 6000.02.

    PRD: "`program_surcharge_usd` is `labor_cost_usd` multiplied by `surcharge_rate`, rounded half up to two decimal places, and it is charged on labor alone."

    Design: Corner/calculations/engagement_cost_rounds_half_up_on_a_third_decimal_five
    """
    _, engagement = _priced_engagement(client, labor_cost_usd=100000.25)

    a.assert_money(engagement["surcharge_rate"], 0.06, "surcharge_rate")
    a.assert_money(
        engagement["program_surcharge_usd"],
        a.round_half_up(6000.015),
        "program_surcharge_usd",
    )
    a.assert_money(engagement["program_surcharge_usd"], 6000.02, "program_surcharge_usd")
    # Truncation of the third decimal would have produced 6000.01.
    assert a.round_half_up(engagement["program_surcharge_usd"]) != 6000.01, (
        "the third-decimal five must round up, not away"
    )


def test_contracted_hours_exactly_at_the_moderate_allowance_draw_no_overage(client):
    """900 contracted hours sit exactly on the MODERATE allowance, so the overage is 0.00.

    PRD: "Subtract that allowance from `contracted_hours`; if the difference is negative treat it as zero; multiply the result by 120.00 US dollars per hour and round half up to two decimal places to obtain `hour_overage_usd`."

    Design: Corner/calculations/engagement_cost_rounds_half_up_on_a_third_decimal_five
    """
    _, engagement = _priced_engagement(client, labor_cost_usd=100000.25)

    # The contracted pool equals the MODERATE allowance exactly, so the
    # difference the overage is charged on is zero rather than negative.
    a.assert_money(
        engagement["contracted_hours"],
        float(c.HOUR_ALLOWANCE["MODERATE"]),
        "contracted_hours",
    )
    a.assert_money(engagement["hour_overage_usd"], 0.00, "hour_overage_usd")
    a.assert_money(engagement["allocated_hours"], 0.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 900.00, "unallocated_hours")
    a.assert_hour_conservation(engagement)


def test_total_engagement_cost_sums_labor_surcharge_and_overage(client):
    """100000.25 labor plus a 6000.02 surcharge and no overage totals 106000.27.

    PRD: "Third, `total_cost_usd` is `labor_cost_usd` plus `program_surcharge_usd` plus `hour_overage_usd`, rounded half up to two decimal places."

    Design: Corner/calculations/engagement_cost_rounds_half_up_on_a_third_decimal_five
    """
    env, engagement = _priced_engagement(client, labor_cost_usd=100000.25)

    a.assert_money(
        engagement["total_cost_usd"],
        a.round_half_up(100000.25 + 6000.02 + 0.00),
        "total_cost_usd",
    )
    a.assert_money(engagement["total_cost_usd"], 106000.27, "total_cost_usd")
    assert engagement["status"] == "DRAFT", engagement
    # Pricing an engagement does not advance the offering.
    assert fx.read_offering(client, env["offering_id"])["status"] == "PATH_SELECTED"


@pytest.mark.parametrize(
    "labor_cost_usd, expected_rate, expected_surcharge, expected_total",
    [
        (250000.00, 0.045, 11250.00, 261250.00),
        (249999.99, 0.06, 15000.00, 264999.99),
    ],
)
def test_surcharge_tier_boundary_takes_the_cheaper_rate_at_the_ceiling(
    client, labor_cost_usd, expected_rate, expected_surcharge, expected_total
):
    """A labor cost of exactly 250000.00 draws 0.045 while one cent less still draws 0.06.

    PRD: "First the program surcharge: the `surcharge_rate` is selected from a tier keyed on `labor_cost_usd` and never on the total — a labor cost below 250000.00 draws a rate of 0.06, a labor cost of at least 250000.00 but below 600000.00 draws 0.045, and a labor cost of 600000.00 or more draws 0.03."

    Design: Corner/calculations/labor_cost_exactly_at_the_tier_ceiling_takes_the_cheaper_rate
    """
    _, engagement = _priced_engagement(client, labor_cost_usd=labor_cost_usd)

    a.assert_money(
        engagement["surcharge_rate"],
        c.expected_surcharge_rate(labor_cost_usd),
        "surcharge_rate",
    )
    a.assert_money(engagement["surcharge_rate"], expected_rate, "surcharge_rate")
    a.assert_engagement_costs(engagement, labor_cost_usd, 900.00, "MODERATE")
    a.assert_money(
        engagement["program_surcharge_usd"], expected_surcharge, "program_surcharge_usd"
    )
    a.assert_money(engagement["hour_overage_usd"], 0.00, "hour_overage_usd")
    a.assert_money(engagement["total_cost_usd"], expected_total, "total_cost_usd")


def test_the_larger_labor_cost_at_the_ceiling_carries_the_smaller_total(client):
    """The engagement at the tier ceiling costs less in total than the one a cent below it.

    PRD: "First the program surcharge: the `surcharge_rate` is selected from a tier keyed on `labor_cost_usd` and never on the total — a labor cost below 250000.00 draws a rate of 0.06, a labor cost of at least 250000.00 but below 600000.00 draws 0.045, and a labor cost of 600000.00 or more draws 0.03."

    Design: Corner/calculations/labor_cost_exactly_at_the_tier_ceiling_takes_the_cheaper_rate
    """
    env, at_ceiling = _priced_engagement(client, labor_cost_usd=250000.00)

    # A second offering, so the two engagements never share a parent.
    env = fx.seed_categorized_offering(
        client, env, offering_key="second", name="GovCloud Object Store"
    )
    below_ceiling = validate_success(
        client.create_engagement(
            f.build_engagement_payload(
                env["second_id"], contracted_hours=900.00, labor_cost_usd=249999.99
            ),
            env["lead_headers"],
        ),
        201,
    )

    a.assert_money(at_ceiling["total_cost_usd"], 261250.00, "total at the ceiling")
    a.assert_money(below_ceiling["total_cost_usd"], 264999.99, "total below the ceiling")
    assert float(at_ceiling["total_cost_usd"]) < float(below_ceiling["total_cost_usd"]), (
        "the cheaper rate on the larger labor cost must yield the smaller total"
    )
    # The allowance came from the same MODERATE tier table on both offerings.
    second = fx.read_offering(client, env["second_id"])
    assert second["final_impact_level"] == "MODERATE", second
    assert second["baseline_id"] == env["baseline_id"], second


# ---------------------------------------------------------------------------
# Preliminary impact aggregation
# ---------------------------------------------------------------------------


def _declare(client, env, category_code, confidentiality, integrity, availability):
    """Declare one data category on the DRAFT offering."""
    return validate_success(
        client.create_data_category(
            env["offering_id"],
            f.build_data_category_payload(
                category_code=category_code,
                confidentiality_impact=confidentiality,
                integrity_impact=integrity,
                availability_impact=availability,
            ),
            env["lead_headers"],
        ),
        201,
    )


def test_preliminary_impact_level_climbs_as_categories_are_declared(client):
    """The mark rises LOW then MODERATE then HIGH as each declaration raises an axis.

    PRD: "For each such category take the highest rank among its confidentiality, integrity and availability ratings, then take the greatest of those per-category highs across the set: `preliminary_impact_level` is the level with that rank."

    Design: Corner/calculations/the_preliminary_high_water_mark_rises_on_add_and_falls_on_withdrawal
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    _declare(client, env, "BILLING", "LOW", "LOW", "LOW")
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "LOW", offering
    a.assert_integer(offering["version"], 2, "version after BILLING")

    _declare(client, env, "PII", "LOW", "MODERATE", "LOW")
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "MODERATE", offering
    a.assert_integer(offering["version"], 3, "version after PII")

    # The availability axis alone lifts the mark to HIGH.
    _declare(client, env, "TELEMETRY", "LOW", "LOW", "HIGH")
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "HIGH", offering
    a.assert_integer(offering["version"], 4, "version after TELEMETRY")


def test_a_category_that_cannot_raise_the_mark_still_recomputes_and_bumps_the_version(
    client,
):
    """Declaring an all-LOW category under a HIGH mark leaves the mark and still bumps the version.

    PRD: "The **preliminary impact level** is a high-water mark maintained continuously while the offering is `DRAFT`, and it is recomputed on every data-category creation, confirmation and withdrawal."

    Design: Corner/calculations/the_preliminary_high_water_mark_rises_on_add_and_falls_on_withdrawal
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))
    _declare(client, env, "BILLING", "LOW", "LOW", "LOW")
    _declare(client, env, "PII", "LOW", "MODERATE", "LOW")
    _declare(client, env, "TELEMETRY", "LOW", "LOW", "HIGH")

    _declare(client, env, "LOGS", "LOW", "LOW", "LOW")

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "HIGH", offering
    a.assert_integer(offering["version"], 5, "version after LOGS")


def test_withdrawing_the_high_category_drops_the_preliminary_mark_back(client):
    """Withdrawing the only HIGH category returns the mark to MODERATE.

    PRD: "`WITHDRAWN` is terminal for a category, and a withdrawn category is invisible to every impact computation thereafter."

    Design: Corner/calculations/the_preliminary_high_water_mark_rises_on_add_and_falls_on_withdrawal
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))
    _declare(client, env, "BILLING", "LOW", "LOW", "LOW")
    _declare(client, env, "PII", "LOW", "MODERATE", "LOW")
    telemetry = _declare(client, env, "TELEMETRY", "LOW", "LOW", "HIGH")
    _declare(client, env, "LOGS", "LOW", "LOW", "LOW")

    withdrawn = validate_success(
        client.confirm_data_category(
            telemetry["id"],
            f.build_category_decision_payload("WITHDRAW"),
            tu.BOARD_HEADERS,
        ),
        200,
    )

    assert withdrawn["status"] == "WITHDRAWN", withdrawn
    assert withdrawn["confirmed_by_user_id"] == tu.BOARD_1, withdrawn

    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "MODERATE", offering
    a.assert_integer(offering["version"], 6, "version after the withdrawal")
    assert offering["final_impact_level"] is None, offering
    assert offering["baseline_id"] is None, offering


# ---------------------------------------------------------------------------
# Disposition weighting
# ---------------------------------------------------------------------------


def _authorized_with_two_high_findings(client):
    """A live authorization carrying two OPEN HIGH findings detected at authorization."""
    env = fx.seed_authorized_offering(client)
    fx.seed_poam_item(
        client,
        env,
        severity="HIGH",
        control_id="AC-2",
        detected_at=AUTHORIZATION_CLOCK,
        key="first_high",
    )
    fx.seed_poam_item(
        client,
        env,
        severity="HIGH",
        control_id="AC-3",
        detected_at=AUTHORIZATION_CLOCK,
        key="second_high",
    )
    return env


def test_filing_a_deviation_leaves_the_residual_risk_score_untouched(client):
    """A DEVIATION_REQUESTED finding still carries factor 1.0, so the score stays at 20.00.

    PRD: "Disposition factors are 1.0 for `NONE`, `DEVIATION_REQUESTED` and `EXTENSION_GRANTED`, 0.5 for `RISK_ACCEPTED` and 0.0 for `FALSE_POSITIVE_ACCEPTED`."

    Design: Corner/calculations/an_agency_risk_acceptance_halves_one_items_severity_weight
    """
    env = _authorized_with_two_high_findings(client)

    before = _risk_summary(client, env["authorization_id"])
    a.assert_money(before["residual_risk_score"], 20.00, "residual_risk_score")
    assert before["poam_risk_tier"] == "MODERATE", before

    fx.seed_deviation(client, env, env["second_high_id"], kind="RISK_ADJUSTMENT")

    filed = fx.read_poam_item(client, env["second_high_id"])
    assert filed["risk_disposition"] == "DEVIATION_REQUESTED", filed
    assert filed["remediation_status"] == "OPEN", filed

    after = _risk_summary(client, env["authorization_id"])
    a.assert_money(after["residual_risk_score"], 20.00, "residual_risk_score")
    assert after["poam_risk_tier"] == "MODERATE", after


def test_an_approved_agency_risk_adjustment_halves_the_accepted_findings_weight(client):
    """An agency-approved RISK_ADJUSTMENT drops one HIGH finding to half weight, 20.00 to 15.00.

    PRD: "Approving a `RISK_ADJUSTMENT` request in the agency queue leaves `granted_extension_days` at 0, moves the finding's `risk_disposition` `DEVIATION_REQUESTED → RISK_ACCEPTED`, and recomputes the authorization's `risk_accepted_findings_count` and `residual_risk_score`, where the accepted finding now contributes at half weight."

    Design: Corner/calculations/an_agency_risk_acceptance_halves_one_items_severity_weight
    """
    env = _authorized_with_two_high_findings(client)
    fx.seed_deviation(
        client,
        env,
        env["second_high_id"],
        kind="RISK_ADJUSTMENT",
        review_queue="AGENCY",
        router=tu.BOARD_1,
    )

    decided = fx.decide_deviation(
        client, env, env["deviation_id"], decision="APPROVE"
    )

    assert decided["status"] == "APPROVED", decided
    assert decided["decided_by_user_id"] == env["agency_id"], decided
    a.assert_integer(decided["granted_extension_days"], 0, "granted_extension_days")

    accepted = fx.read_poam_item(client, env["second_high_id"])
    assert accepted["risk_disposition"] == "RISK_ACCEPTED", accepted
    assert accepted["remediation_status"] == "OPEN", accepted
    a.assert_instant(
        accepted["deadline_at"],
        a.expected_deadline(AUTHORIZATION_CLOCK, "HIGH"),
        "deadline_at",
    )

    summary = _risk_summary(client, env["authorization_id"])
    population = [
        {
            "severity": "HIGH",
            "risk_disposition": "NONE",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "HIGH"),
        },
        {
            "severity": "HIGH",
            "risk_disposition": "RISK_ACCEPTED",
            "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "HIGH"),
        },
    ]
    a.assert_money(
        summary["residual_risk_score"],
        a.expected_residual_risk(population, AUTHORIZATION_CLOCK),
        "residual_risk_score",
    )
    a.assert_money(summary["residual_risk_score"], 15.00, "residual_risk_score")
    # Excluding an accepted finding altogether would have reported 10.00.
    assert abs(float(summary["residual_risk_score"]) - 10.00) > 0.01, (
        "an accepted finding is halved, not dropped"
    )
    a.assert_integer(summary["open_findings_count"], 2, "open_findings_count")
    assert summary["poam_risk_tier"] == "MODERATE", summary

    authorization = fx.read_authorization(client, env["authorization_id"])
    a.assert_integer(
        authorization["risk_accepted_findings_count"], 1, "risk_accepted_findings_count"
    )
    a.assert_money(
        authorization["residual_risk_score"], 15.00, "stored residual_risk_score"
    )


# ---------------------------------------------------------------------------
# Scan timeliness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "submitted_at, expected_days_late, expected_status",
    [
        ("2026-04-06T00:00:00Z", 0, "ACCEPTED"),
        ("2026-04-09T00:00:00Z", 3, "LATE_ACCEPTED"),
        ("2026-04-10T00:00:00Z", 4, "REJECTED"),
    ],
)
def test_scan_timeliness_grades_by_whole_days_late(
    client, submitted_at, expected_days_late, expected_status
):
    """Submitting at the due instant, on the last grace day and one day later grades three ways.

    PRD: "The submission's `status` follows directly from that figure — `ACCEPTED` when `days_late` is 0, `LATE_ACCEPTED` when `days_late` is 1, 2 or 3, and `REJECTED` when `days_late` is 4 or more."

    Design: Corner/calculations/scan_lateness_crosses_from_late_accepted_to_rejected_on_the_fourth_day
    """
    env = fx.seed_authorized_offering(client)
    period = fx.read_monitoring_period(client, env["period_id"])
    a.assert_monitoring_window(period, "2026-03")

    fx.set_clock(client, submitted_at)
    submission = validate_success(
        client.create_scan_submission(
            env["period_id"], f.build_scan_submission_payload(), env["lead_headers"]
        ),
        201,
    )

    days_late = a.whole_days_late(submitted_at, period["scan_due_at"])
    a.assert_integer(days_late, expected_days_late, "derived days_late")
    a.assert_integer(submission["days_late"], expected_days_late, "days_late")
    assert submission["status"] == a.expected_scan_status(expected_days_late)
    assert submission["status"] == expected_status, submission


def test_a_rejected_submission_contributes_no_covered_scan_types(client):
    """Three submissions land one per status, and only the graded-in two supply coverage.

    PRD: "The period's `covered_scan_types` is then the sorted union of the `scan_types` of all its submissions whose `status` is `ACCEPTED` or `LATE_ACCEPTED`, so a rejected submission contributes no coverage at all."

    Design: Corner/calculations/scan_lateness_crosses_from_late_accepted_to_rejected_on_the_fourth_day
    """
    env = fx.seed_authorized_offering(client)

    fx.set_clock(client, "2026-04-06T00:00:00Z")
    fx.submit_scans(client, env, env["period_id"])
    fx.set_clock(client, "2026-04-09T00:00:00Z")
    fx.submit_scans(client, env, env["period_id"])
    # The fourth day past the due instant: rejected, and its CONTAINER scan
    # therefore never reaches the period's coverage.
    fx.set_clock(client, "2026-04-10T00:00:00Z")
    fx.submit_scans(
        client,
        env,
        env["period_id"],
        scan_types=["INFRASTRUCTURE", "WEB_APP", "DATABASE", "CONTAINER"],
    )

    period = fx.read_monitoring_period(client, env["period_id"])
    a.assert_integer(period["accepted_submission_count"], 1, "accepted_submission_count")
    a.assert_integer(period["late_submission_count"], 1, "late_submission_count")
    a.assert_integer(period["rejected_submission_count"], 1, "rejected_submission_count")
    assert period["covered_scan_types"] == ["DATABASE", "INFRASTRUCTURE", "WEB_APP"], (
        period["covered_scan_types"]
    )
    assert period["status"] == "OPEN", period


# ---------------------------------------------------------------------------
# Test-slot interval geometry
# ---------------------------------------------------------------------------


def _engagement_with_first_slot(client):
    """An engagement in TESTING holding one 09:00-17:00 slot on 2026-03-02."""
    env = fx.seed_engagement(
        client, fx.seed_path_selected_offering(client, fx.seed_reference_data(client))
    )
    env = fx.seed_test_slot(client, env, key="outer")
    return env


def _slot(client, env, *, start_at, end_at, hours, family_code="AC"):
    return client.create_test_slot(
        f.build_test_slot_payload(
            env["engagement_id"],
            start_at=start_at,
            end_at=end_at,
            hours=hours,
            family_code=family_code,
        ),
        env["assessor_headers"],
    )


def test_a_slot_contained_by_an_existing_slot_is_refused(client):
    """An 11:00-12:00 slot strictly inside an existing 09:00-17:00 slot conflicts.

    PRD: "Two slots of the same engagement conflict when the new slot's start falls strictly before the existing slot's end *and* the existing slot's start falls strictly before the new slot's end, evaluated against the engagement's slots in `SCHEDULED` or `COMPLETED` status; a conflict is refused with `ERR_TEST_SLOT_OVERLAP`."

    Design: Corner/calculations/a_test_slot_that_contains_or_is_contained_by_another_overlaps_either_way
    """
    env = _engagement_with_first_slot(client)
    assert env["slots"]["outer"]["status"] == "SCHEDULED", env["slots"]["outer"]

    response = _slot(
        client,
        env,
        start_at="2026-03-02T11:00:00Z",
        end_at="2026-03-02T12:00:00Z",
        hours=1.0,
    )

    validate_error(response, ERR_TEST_SLOT_OVERLAP, 409)
    slots = fx.list_test_slots(client, env["engagement_id"])
    assert len(slots) == 1, slots


def test_a_slot_containing_an_existing_slot_is_refused(client):
    """An 08:00-18:00 slot that swallows an existing 09:00-17:00 slot conflicts too.

    PRD: "Two slots of the same engagement conflict when the new slot's start falls strictly before the existing slot's end *and* the existing slot's start falls strictly before the new slot's end, evaluated against the engagement's slots in `SCHEDULED` or `COMPLETED` status; a conflict is refused with `ERR_TEST_SLOT_OVERLAP`."

    Design: Corner/calculations/a_test_slot_that_contains_or_is_contained_by_another_overlaps_either_way
    """
    env = _engagement_with_first_slot(client)

    response = _slot(
        client,
        env,
        start_at="2026-03-02T08:00:00Z",
        end_at="2026-03-02T18:00:00Z",
        hours=10.0,
        family_code="SC",
    )

    validate_error(response, ERR_TEST_SLOT_OVERLAP, 409)
    slots = fx.list_test_slots(client, env["engagement_id"])
    assert len(slots) == 1, slots


def test_refused_overlaps_leave_the_hour_ledger_untouched(client):
    """Two refused slots cost no hours, so only the two disjoint days are allocated.

    PRD: "An engagement's `allocated_hours` is the sum of the `hours` of its slots in `SCHEDULED` or `COMPLETED` status, rounded half up to two decimal places, and its `unallocated_hours` is `contracted_hours` less `allocated_hours`, likewise rounded and never negative."

    Design: Corner/calculations/a_test_slot_that_contains_or_is_contained_by_another_overlaps_either_way
    """
    env = _engagement_with_first_slot(client)
    a.assert_money(env["engagement"]["allocated_hours"], 8.00, "allocated_hours")
    a.assert_money(env["engagement"]["unallocated_hours"], 192.00, "unallocated_hours")

    validate_error(
        _slot(
            client,
            env,
            start_at="2026-03-02T11:00:00Z",
            end_at="2026-03-02T12:00:00Z",
            hours=1.0,
        ),
        ERR_TEST_SLOT_OVERLAP,
        409,
    )
    validate_error(
        _slot(
            client,
            env,
            start_at="2026-03-02T08:00:00Z",
            end_at="2026-03-02T18:00:00Z",
            hours=10.0,
            family_code="SC",
        ),
        ERR_TEST_SLOT_OVERLAP,
        409,
    )
    next_day = validate_success(
        _slot(
            client,
            env,
            start_at="2026-03-03T09:00:00Z",
            end_at="2026-03-03T17:00:00Z",
            hours=8.0,
            family_code="SC",
        ),
        201,
    )
    assert next_day["status"] == "SCHEDULED", next_day

    engagement = fx.read_engagement(client, env["engagement_id"])
    a.assert_money(engagement["allocated_hours"], 16.00, "allocated_hours")
    a.assert_money(engagement["unallocated_hours"], 184.00, "unallocated_hours")
    a.assert_hour_conservation(engagement)

    _, meta = validate_paginated(
        client.list_test_slots(env["engagement_id"], env["assessor_headers"])
    )
    assert meta["total_count"] == 2, meta


# ---------------------------------------------------------------------------
# Which impact variant runs where
# ---------------------------------------------------------------------------


def test_declaring_a_category_writes_only_the_preliminary_level(client):
    """A merely declared category moves the preliminary mark and leaves the final level null.

    PRD: "Consider every data category of the offering whose `status` is `DECLARED` or `CONFIRMED`; withdrawn categories are excluded."

    Design: Corner/calculations/the_final_impact_variant_runs_only_on_the_determination_endpoint
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))

    category = _declare(client, env, "PII", "MODERATE", "MODERATE", "LOW")

    assert category["status"] == "DECLARED", category
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["preliminary_impact_level"] == "MODERATE", offering
    assert offering["final_impact_level"] is None, offering
    assert offering["baseline_id"] is None, offering
    assert offering["status"] == "DRAFT", offering
    a.assert_integer(offering["version"], 2, "version after the declaration")


def test_impact_determination_refuses_before_any_category_is_confirmed(client):
    """With only a DECLARED category the final variant has an empty input set and refuses.

    PRD: "If the offering has no confirmed category at all, the request fails with `ERR_NO_CONFIRMED_DATA_CATEGORY`."

    Design: Corner/calculations/the_final_impact_variant_runs_only_on_the_determination_endpoint
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))
    _declare(client, env, "PII", "MODERATE", "MODERATE", "LOW")

    response = client.determine_impact(env["offering_id"], {}, tu.BOARD_HEADERS)

    validate_error(response, ERR_NO_CONFIRMED_DATA_CATEGORY, 422)
    offering = fx.read_offering(client, env["offering_id"])
    assert offering["status"] == "DRAFT", offering
    a.assert_integer(offering["version"], 2, "version after the refusal")
    assert offering["final_impact_level"] is None, offering


def test_impact_determination_writes_the_final_level_and_binds_the_baseline(client):
    """Once the category is confirmed the determination endpoint computes the final level.

    PRD: "On success the offering moves `DRAFT → CATEGORIZED`, `final_impact_level` and `baseline_id` are written, and the offering's `version` increments by one."

    Design: Corner/calculations/the_final_impact_variant_runs_only_on_the_determination_endpoint
    """
    env = fx.seed_draft_offering(client, fx.seed_reference_data(client))
    category = _declare(client, env, "PII", "MODERATE", "MODERATE", "LOW")
    confirmed = validate_success(
        client.confirm_data_category(
            category["id"], f.build_category_decision_payload("CONFIRM"), tu.BOARD_HEADERS
        ),
        200,
    )
    assert confirmed["status"] == "CONFIRMED", confirmed
    a.assert_integer(
        fx.read_offering(client, env["offering_id"])["version"],
        3,
        "version after the confirmation",
    )

    determined = validate_success(
        client.determine_impact(env["offering_id"], {}, tu.BOARD_HEADERS), 200
    )

    assert determined["final_impact_level"] == "MODERATE", determined
    assert determined["baseline_id"] == env["baseline_id"], determined
    assert determined["status"] == "CATEGORIZED", determined
    a.assert_integer(determined["version"], 4, "version after the determination")
    # The final variant never overwrites the preliminary field.
    assert determined["preliminary_impact_level"] == "MODERATE", determined


# ---------------------------------------------------------------------------
# The frozen package snapshot beside the live ledger
# ---------------------------------------------------------------------------


def _authorized_with_a_pre_package_finding(client):
    """Authorize an offering that already carried one OPEN MODERATE finding."""
    env = fx.seed_reference_data(client)
    env = fx.seed_path_selected_offering(client, env)
    env = fx.seed_control_implementations(client, env)
    env = fx.seed_engagement(client, env)
    env = fx.seed_report_delivered(client, env, report_at=AUTHORIZATION_CLOCK)
    env = fx.seed_poam_item(
        client,
        env,
        severity="MODERATE",
        control_id="AC-2",
        detected_at=AUTHORIZATION_CLOCK,
        key="moderate",
    )
    env = fx.seed_submitted_package(client, env)
    env = fx.decide_package(client, env, decision="AUTHORIZE")
    return env


def test_submission_freezes_coverage_risk_and_open_finding_count(client):
    """The package snapshot records 100.00 coverage, a 4.00 risk score and one open finding.

    PRD: "Three figures are frozen onto the package at that instant and never move again: `crm_coverage_pct` from the coverage computation, `residual_risk_score_at_submission` from the submission variant of the risk score, and `open_findings_at_submission` as the count of the offering's findings whose `remediation_status` is not `CLOSED`."

    Design: Corner/calculations/the_package_snapshot_stays_frozen_while_the_authorization_ledger_moves_on
    """
    env = _authorized_with_a_pre_package_finding(client)

    package = fx.read_package(client, env["package_id"])

    a.assert_money(package["crm_coverage_pct"], 100.00, "crm_coverage_pct")
    a.assert_money(
        package["residual_risk_score_at_submission"],
        a.expected_residual_risk(
            [
                {
                    "severity": "MODERATE",
                    "risk_disposition": "NONE",
                    "deadline_at": a.expected_deadline(AUTHORIZATION_CLOCK, "MODERATE"),
                }
            ],
            AUTHORIZATION_CLOCK,
        ),
        "residual_risk_score_at_submission",
    )
    a.assert_money(
        package["residual_risk_score_at_submission"],
        4.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 1, "open_findings_at_submission"
    )
    a.assert_instant(package["submitted_at"], AUTHORIZATION_CLOCK, "submitted_at")
    assert package["status"] == "AUTHORIZED", package


def test_a_finding_opened_after_authorization_moves_only_the_live_score(client):
    """A new HIGH finding lifts the authorization to 14.00 while the package still reads 4.00.

    PRD: "The risk-summary read exists exactly for that reason: it recomputes the monitoring variant live and returns `residual_risk_score`, the derived `poam_risk_tier`, the lagging `stored_residual_risk_score`, the `open_findings_count`, an `overdue_high_count` of open high-severity findings past their deadline, and the `evaluated_at` instant it used."

    Design: Corner/calculations/the_package_snapshot_stays_frozen_while_the_authorization_ledger_moves_on
    """
    env = _authorized_with_a_pre_package_finding(client)

    at_authorization = _risk_summary(client, env["authorization_id"])
    a.assert_money(at_authorization["residual_risk_score"], 4.00, "residual_risk_score")
    a.assert_money(
        at_authorization["stored_residual_risk_score"],
        4.00,
        "stored_residual_risk_score",
    )
    assert at_authorization["poam_risk_tier"] == a.expected_risk_tier(4.00) == "LOW"

    fx.seed_poam_item(
        client,
        env,
        severity="HIGH",
        control_id="AC-3",
        detected_at=AUTHORIZATION_CLOCK,
        key="high",
    )

    after = _risk_summary(client, env["authorization_id"])
    a.assert_money(after["residual_risk_score"], 14.00, "residual_risk_score")
    assert after["poam_risk_tier"] == "MODERATE", after
    a.assert_integer(after["open_findings_count"], 2, "open_findings_count")
    a.assert_instant(after["evaluated_at"], AUTHORIZATION_CLOCK, "evaluated_at")

    # The frozen snapshot is read from its own field and does not follow.
    package = fx.read_package(client, env["package_id"])
    a.assert_money(
        package["residual_risk_score_at_submission"],
        4.00,
        "residual_risk_score_at_submission",
    )
    a.assert_integer(
        package["open_findings_at_submission"], 1, "open_findings_at_submission"
    )


def test_a_self_identified_finding_is_not_re_anchored_at_authorization(client):
    """The self-identified MODERATE finding keeps its detection anchor through the AUTHORIZE cascade.

    PRD: "Items sourced from a scan or self-identified are never re-anchored."

    Design: Corner/calculations/the_package_snapshot_stays_frozen_while_the_authorization_ledger_moves_on
    """
    env = _authorized_with_a_pre_package_finding(client)

    item = fx.read_poam_item(client, env["moderate_id"])

    assert item["source"] == "SELF_IDENTIFIED", item
    a.assert_instant(item["anchor_at"], AUTHORIZATION_CLOCK, "anchor_at")
    a.assert_instant(
        item["deadline_at"],
        a.expected_deadline(AUTHORIZATION_CLOCK, "MODERATE"),
        "deadline_at",
    )
    a.assert_instant(item["deadline_at"], "2026-06-28T00:00:00Z", "deadline_at")
