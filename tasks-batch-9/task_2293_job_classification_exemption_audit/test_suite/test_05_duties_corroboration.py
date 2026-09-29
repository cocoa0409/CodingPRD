"""Duty documentation and the attested-interview corroboration calculation."""

from typing import Any, Dict

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    DutiesValidationStatus,
    ErrorId,
    RespondentType,
    assert_family_risk,
    assert_one_decimal,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


@pytest.fixture
def spread_boundary_pair(api, pinned_clock) -> Dict[str, Any]:
    """Two jobs whose manager/incumbent spreads straddle the 15.0 point limit."""
    fixtures.register_state_rule(
        api,
        factories.california_rule_payload(
            liquidated_damages_multiplier=1.0, back_wage_lookback_weeks_override=156
        ),
    )
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])
    fixtures.advance_project(api, project["id"], "FIELDWORK")
    family_id = family["id"]
    position_s = fixtures.create_position(
        api, family_id, title="Shift Supervisor S", job_code="SS-101"
    )
    position_t = fixtures.create_position(
        api, family_id, title="Shift Supervisor T", job_code="SS-102"
    )

    bookings = [
        (position_s["id"], RespondentType.MANAGER, "MGR-S", ("2026-09-15T09:00:00Z", "2026-09-15T10:00:00Z"), (60.0, 45, 3, True)),
        (position_s["id"], RespondentType.INCUMBENT, "INC-S", ("2026-09-15T10:00:00Z", "2026-09-15T11:00:00Z"), (45.0, 49, 2, True)),
        (position_t["id"], RespondentType.MANAGER, "MGR-T", ("2026-09-15T11:00:00Z", "2026-09-15T12:00:00Z"), (60.1, 45, 3, True)),
        (position_t["id"], RespondentType.INCUMBENT, "INC-T", ("2026-09-15T12:00:00Z", "2026-09-15T13:00:00Z"), (45.0, 49, 2, True)),
    ]
    interviews = []
    for position_id, respondent_type, respondent_ref, window, account in bookings:
        interview = fixtures.book_interview(
            api, position_id, "int-4", window, respondent_type, respondent_ref
        )
        fixtures.complete_interview(api, interview["id"], account)
        interviews.append(interview)
    for interview in interviews:
        fixtures.attest_interview(api, interview["id"])

    return {
        "project_id": project["id"],
        "family_id": family_id,
        "position_s_id": position_s["id"],
        "position_t_id": position_t["id"],
    }


def test_spread_of_exactly_fifteen_points_still_corroborates(api, spread_boundary_pair):
    """A 15.0 point spread is inside the inclusive limit and yields the weighted blend.

    PRD: "If the spread is 15.0 points or less, `duties_validation_status` becomes `CORROBORATED`
    and `primary_duty_pct` becomes a weighted blend of the two accounts, giving the manager a 40
    percent weight and the incumbent a 60 percent weight"

    Design: Difficulty/boundary_precision_check/corroboration_spread_boundary_flips_at_one_tenth_of_a_point
    """
    position = fixtures.read_position(api, spread_boundary_pair["position_s_id"])

    assert position["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        "a spread of exactly 15.0 points must still corroborate, got "
        f"{position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 51.0, "primary_duty_pct")
    assert position["validated_weekly_hours"] == 49, (
        f"validated hours take the greater account, got {position['validated_weekly_hours']}"
    )
    assert position["corroborated_supervises_headcount"] == 2, (
        "the supervised headcount takes the lesser account, got "
        f"{position['corroborated_supervises_headcount']}"
    )
    assert position["corroborated_hire_fire_influence"] is True, (
        "both respondents reported hire-fire influence, got "
        f"{position['corroborated_hire_fire_influence']}"
    )


def test_spread_of_fifteen_point_one_conflicts_and_takes_the_lower_account(
    api, spread_boundary_pair
):
    """One tenth of a point past the limit flips the outcome to the conservative view.

    PRD: "If the spread is greater than 15.0 percentage points, the two accounts do not agree:
    `duties_validation_status` becomes `CONFLICTED` and the audit takes the conservative view,
    setting `primary_duty_pct` to the **lower** of the two reported percentages, rounded half up
    to one decimal place."

    Design: Difficulty/boundary_precision_check/corroboration_spread_boundary_flips_at_one_tenth_of_a_point
    """
    position = fixtures.read_position(api, spread_boundary_pair["position_t_id"])

    assert position["duties_validation_status"] == DutiesValidationStatus.CONFLICTED, (
        f"a spread of 15.1 points must conflict, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 45.0, "primary_duty_pct")
    assert position["validated_weekly_hours"] == 49, (
        f"validated hours take the greater account, got {position['validated_weekly_hours']}"
    )
    assert position["corroborated_supervises_headcount"] == 2, (
        "the supervised headcount takes the lesser account, got "
        f"{position['corroborated_supervises_headcount']}"
    )
    assert position["corroborated_hire_fire_influence"] is True, (
        "both respondents reported hire-fire influence, got "
        f"{position['corroborated_hire_fire_influence']}"
    )
    family = fixtures.read_family(api, spread_boundary_pair["family_id"])
    assert family["risk_variant"] == "EVIDENCE_WEIGHTED", (
        f"with no job left PENDING the premium variant does not apply, got {family['risk_variant']}"
    )


def test_corroboration_ignores_a_completed_but_unattested_interview(api, pinned_clock):
    """Only attested accounts feed the calculation; a completed one is filtered out.

    PRD: "Only interviews whose `status` is `ATTESTED` feed the calculation; `SCHEDULED`,
    `COMPLETED` and `VOIDED` accounts are all excluded."

    Design: Corner/calculations/duties_corroboration_ignores_a_completed_but_unattested_interview
    """
    fixtures.register_state_rule(
        api, factories.california_rule_payload(back_wage_lookback_weeks_override=156)
    )
    project = fixtures.create_project(api, lookback_policy="WILLFUL_3Y")
    family = fixtures.create_family(api, project["id"])
    fixtures.advance_project(api, project["id"], "FIELDWORK")
    position = fixtures.create_position(api, family["id"])
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="D-EX",
        description="Directs the shift and schedules the crew",
        claimed_time_pct=45.0,
        is_exempt_duty=True,
    )
    fixtures.add_duty(
        api,
        position["id"],
        duty_code="D-NX",
        description="Works the line alongside the crew",
        claimed_time_pct=55.0,
        is_exempt_duty=False,
        discretion_level="NONE",
    )

    manager = fixtures.book_interview(
        api, position["id"], "int-21", ("2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z")
    )
    fixtures.complete_interview(api, manager["id"], (46.0, 45, 3, True))
    fixtures.attest_interview(api, manager["id"])
    incumbent = fixtures.book_interview(
        api,
        position["id"],
        "int-21",
        ("2026-09-11T14:00:00Z", "2026-09-11T15:00:00Z"),
        RespondentType.INCUMBENT,
        "INC-1",
    )
    fixtures.complete_interview(api, incumbent["id"], (52.0, 49, 2, True))

    before = fixtures.read_position(api, position["id"])
    assert before["duties_validation_status"] == DutiesValidationStatus.PENDING, (
        f"one attested account is not a pair, got {before['duties_validation_status']}"
    )
    assert_one_decimal(before["self_reported_exempt_pct"], 45.0, "self_reported_exempt_pct")
    assert_one_decimal(before["primary_duty_pct"], 45.0, "primary_duty_pct before attestation")
    assert before["validated_weekly_hours"] == 47, (
        "the employer-reported average is the fallback, got "
        f"{before['validated_weekly_hours']}"
    )
    assert before["corroborated_supervises_headcount"] == 0, (
        f"the corroborated headcount is 0 while PENDING, got {before['corroborated_supervises_headcount']}"
    )
    assert before["corroborated_hire_fire_influence"] is False, (
        "hire-fire influence is false while PENDING, got "
        f"{before['corroborated_hire_fire_influence']}"
    )
    assert_family_risk(
        fixtures.read_family(api, family["id"]), 96, "CRITICAL", variant="SCREENING"
    )

    fixtures.attest_interview(api, incumbent["id"])

    after = fixtures.read_position(api, position["id"])
    assert after["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        f"the attested pair must corroborate, got {after['duties_validation_status']}"
    )
    assert_one_decimal(after["primary_duty_pct"], 49.6, "primary_duty_pct after attestation")
    assert after["validated_weekly_hours"] == 49, (
        f"validated hours take the greater account, got {after['validated_weekly_hours']}"
    )
    assert after["corroborated_supervises_headcount"] == 2, (
        "the supervised headcount takes the lesser account, got "
        f"{after['corroborated_supervises_headcount']}"
    )
    assert after["corroborated_hire_fire_influence"] is True, (
        "both accounts reported hire-fire influence, got "
        f"{after['corroborated_hire_fire_influence']}"
    )
    assert_family_risk(
        fixtures.read_family(api, family["id"]), 88, "CRITICAL", variant="EVIDENCE_WEIGHTED"
    )


def test_corroboration_weighted_mean_is_rounded_to_one_decimal_place(api, ca_engagement):
    """The 40/60 blend of 46.7 and 52.4 is 50.12 unrounded and must serialize as 50.1.

    PRD: "multiply the manager's reported percentage by 40 and the incumbent's by 60, add the two
    products, divide the sum by 100, and round the result half up to one decimal place."

    Design: Corner/calculations/corroboration_weighted_mean_is_rounded_to_one_decimal_place
    """
    position_id = ca_engagement["position_id"]
    manager = fixtures.book_interview(
        api, position_id, "int-23", ("2026-09-14T14:00:00Z", "2026-09-14T15:00:00Z")
    )
    fixtures.complete_interview(api, manager["id"], (46.7, 45, 3, True))
    fixtures.attest_interview(api, manager["id"])
    incumbent = fixtures.book_interview(
        api,
        position_id,
        "int-23",
        ("2026-09-15T14:00:00Z", "2026-09-15T15:00:00Z"),
        RespondentType.INCUMBENT,
        "INC-1",
    )
    fixtures.complete_interview(api, incumbent["id"], (52.4, 49, 2, True))
    fixtures.attest_interview(api, incumbent["id"])

    position = fixtures.read_position(api, position_id)
    assert position["duties_validation_status"] == DutiesValidationStatus.CORROBORATED, (
        f"a 5.7 point spread must corroborate, got {position['duties_validation_status']}"
    )
    assert_one_decimal(position["primary_duty_pct"], 50.1, "primary_duty_pct")
    assert position["validated_weekly_hours"] == 49, (
        f"validated hours take the greater account, got {position['validated_weekly_hours']}"
    )


def test_duty_shares_are_rejected_only_once_the_running_sum_passes_one_hundred(
    api, ca_planning_engagement
):
    """Landing on exactly 100.0 is allowed; exceeding it is not, and nothing is written.

    PRD: "The claimed shares are an allocation of one person's time, so their sum across a
    position may never exceed 100 -- a duty line that would push the total above 100 is rejected
    with `ERR_DUTY_TIME_OVERALLOCATED`."

    Design: Corner/validations/duty_percentages_are_rejected_only_once_the_running_sum_passes_one_hundred
    """
    position_id = ca_planning_engagement["position_id"]
    first = fixtures.add_duty(
        api,
        position_id,
        duty_code="D-1",
        description="Directs the shift",
        claimed_time_pct=60.0,
        is_exempt_duty=True,
    )

    validate_error(
        api.create_duty_statement(
            factories.duty_statement_payload(
                position_id,
                duty_code="D-2",
                description="Runs the line",
                claimed_time_pct=45.0,
                is_exempt_duty=False,
                discretion_level="NONE",
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        ErrorId.DUTY_TIME_OVERALLOCATED,
        409,
    )

    third = validate_success(
        api.create_duty_statement(
            factories.duty_statement_payload(
                position_id,
                duty_code="D-3",
                description="Runs the line",
                claimed_time_pct=40.0,
                is_exempt_duty=False,
                discretion_level="NONE",
            ),
            COMPLIANCE_ANALYST_HEADERS,
        ),
        201,
    )

    rows, meta = validate_paginated(api.list_position_duty_statements(position_id, AUDITOR_HEADERS))
    assert meta["total_count"] == 2, f"only two duty lines may exist, got {meta['total_count']}"
    assert sorted(row["id"] for row in rows) == sorted([first["id"], third["id"]]), (
        "the rejected duty line must not have been written"
    )

    position = fixtures.read_position(api, position_id)
    assert_one_decimal(position["self_reported_exempt_pct"], 60.0, "self_reported_exempt_pct")
