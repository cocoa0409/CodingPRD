"""Workload weights, selector ranking, order pricing, index precision and severity bands."""
from prd_bench_local_runner.testing import validate_paginated

from test_helpers import (
    AssessmentStatus,
    BreachSeverity,
    BreachStatus,
    CaseloadStatus,
    ComplianceStatus,
    ConsentEventType,
    OrderStatus,
    ReferralStatus,
    ReferralType,
    api_client,
    assert_compliance_run_summary,
    assert_evaluation,
    assert_protocol_order,
    assert_psychologist,
    assert_timeline_breach,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]


def test_a_waived_reevaluation_weighs_one_point_less_than_the_same_initial_case():
    """Identical domains and no interpreter, so only the referral type differs.

    "Then the referral type contributes: two points for an `INITIAL` evaluation, one point for a `REEVALUATION`."

    Design: Corner/calculations/reevaluation_waived_consent_caseload_points
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Tamarack Elementary",
        building_code="TM39",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=400,
    )
    _, initial_evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-20",
        requested_domains=["COGNITIVE", "ADAPTIVE"],
    )
    waiver_reason = "Parents waived the three-year reevaluation consent in writing."
    reeval_referral, reeval_evaluation = fixtures.waived_referral(
        school["id"],
        initial_evaluation["id"],
        waiver_reason=waiver_reason,
        student_local_id="STU-20",
        requested_domains=["COGNITIVE", "ADAPTIVE"],
    )

    # 3 base + 1 extra domain + 0 interpreter, then 2 for INITIAL against 1 for REEVALUATION.
    assert initial_evaluation["caseload_points"] == 6
    assert reeval_evaluation["caseload_points"] == 5

    assert reeval_referral["status"] == ReferralStatus.CONSENT_WAIVED.value
    assert reeval_referral["last_consent_event_type"] == ConsentEventType.CONSENT_WAIVED.value
    assert reeval_referral["waiver_reason"] == waiver_reason
    assert reeval_referral["parent_signature_reference"] is None

    assert_evaluation(reeval_evaluation)
    assert reeval_evaluation["clock_start_date"] == "2026-08-01"
    assert reeval_evaluation["base_due_date"] == "2026-09-30"
    assert reeval_evaluation["referral_type"] == ReferralType.REEVALUATION.value
    assert reeval_evaluation["prior_evaluation_id"] == initial_evaluation["id"]

    descendants, _ = validate_paginated(
        api_client.list_evaluations(
            SUPERVISOR, {"prior_evaluation_id": initial_evaluation["id"]}
        )
    )
    assert [row["id"] for row in descendants] == [reeval_evaluation["id"]]


def test_the_selector_breaks_a_perfect_tie_on_created_at_then_ranks_on_continuity():
    """The first pick is decided by age, the second by the incumbent's own load.

    "Ties are broken in this exact order: lowest score first; then lowest `open_case_points`; then earliest `created_at`."

    "From that is subtracted a continuity bonus of one tenth of a point for each of their open evaluations whose referral was raised at the same building as this referral, counting at most two such evaluations — so the bonus is capped at two tenths of a point however many same-building cases the candidate already carries."

    Design: Corner/calculations/selector_tie_break_created_at_then_continuity_bonus
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Umberton Middle",
        building_code="UM40",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=480,
    )
    older = fixtures.create_psychologist(
        [school["id"]],
        full_name="Aloe First",
        employee_number="E-2014",
        credential_type="SSP",
    )
    # A later clock instant makes the created_at ordering of the two candidates strict.
    fixtures.set_clock("2026-08-02T00:00:00Z")
    younger = fixtures.create_psychologist(
        [school["id"]],
        full_name="Basil Second",
        employee_number="E-2015",
        credential_type="SSP",
    )
    assert older["created_at"] < younger["created_at"]
    _, first_evaluation = fixtures.consented_referral(
        school["id"],
        effective_at="2026-08-02T00:00:00Z",
        student_local_id="STU-21",
        requested_domains=["COGNITIVE"],
    )
    _, second_evaluation = fixtures.consented_referral(
        school["id"],
        effective_at="2026-08-02T00:00:00Z",
        student_local_id="STU-22",
        requested_domains=["ACADEMIC"],
    )

    first_assigned = fixtures.assign_evaluator(first_evaluation["id"])
    assert first_assigned["psychologist_id"] == older["id"]

    incumbent = fixtures.get_psychologist(older["id"])
    assert_psychologist(incumbent)
    assert incumbent["open_case_points"] == 5
    assert incumbent["pressure_index_assigned_basis"] == 0.25
    assert incumbent["pressure_index_clock_weighted"] == 0.25

    second_assigned = fixtures.assign_evaluator(second_evaluation["id"])

    # 0.25 clock-weighted, no breach penalty, less one same-building case at 0.10 => 0.15 > 0.00.
    assert second_assigned["psychologist_id"] == younger["id"]
    assert fixtures.get_psychologist(younger["id"])["open_case_points"] == 5
    assert fixtures.get_psychologist(older["id"])["open_case_points"] == 5


def test_a_small_order_picks_up_the_contract_discount_and_the_flat_handling_fee():
    """Below the first tier the multiplier is one and the flat fee applies.

    "Sixth, `handling_fee_cents` is a flat 1,250 cents when `quantity_requested` is fewer than 25 booklets — the same 25-booklet threshold that governs the first tier — and zero at 25 booklets or more."

    Design: Corner/calculations/protocol_order_small_order_constants_applied
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="BASC-3",
        instrument_code="BASC3",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )

    order = fixtures.order_protocols(instrument["id"], 10, rush_flag=False)

    assert_protocol_order(order)
    assert order["unit_price_cents"] == 1799
    assert order["base_cents"] == 17990
    # 17990 * 0.07 is 1259.3, which rounds half up to 1259.
    assert order["contract_discount_cents"] == 1259
    assert order["rush_surcharge_cents"] == 0
    assert order["handling_fee_cents"] == 1250
    assert order["total_cost_cents"] == 17981
    assert order["auto_approved"] is True
    assert order["status"] == OrderStatus.APPROVED.value


def test_one_more_booklet_across_the_tier_boundary_lowers_the_total():
    """Twenty-five booklets drop both the multiplier and the handling fee.

    "First, a volume tier multiplier is chosen from the ordered quantity alone: orders of fewer than 25 booklets get a multiplier of one, orders of 25 through 99 booklets get a multiplier of ninety-five hundredths, and orders of 100 booklets or more get a multiplier of nine tenths."

    Design: Corner/calculations/protocol_order_tier_boundary_lowers_total_across_threshold
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="DAS-II",
        instrument_code="DAS2",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )

    below = fixtures.order_protocols(instrument["id"], 24, rush_flag=False)
    at_boundary = fixtures.order_protocols(instrument["id"], 25, rush_flag=False)

    assert_protocol_order(below)
    assert below["unit_price_cents"] == 1799
    assert below["base_cents"] == 43176
    assert below["contract_discount_cents"] == 3022
    assert below["handling_fee_cents"] == 1250
    assert below["total_cost_cents"] == 41404
    assert below["auto_approved"] is False
    assert below["status"] == OrderStatus.SUBMITTED.value

    assert_protocol_order(at_boundary)
    # 1799 * 0.95 is 1709.05, which rounds half up to 1709.
    assert at_boundary["unit_price_cents"] == 1709
    assert at_boundary["base_cents"] == 42725
    # 42725 * 0.07 is 2990.75, which rounds half up to 2991.
    assert at_boundary["contract_discount_cents"] == 2991
    assert at_boundary["handling_fee_cents"] == 0
    assert at_boundary["total_cost_cents"] == 39734

    assert at_boundary["total_cost_cents"] < below["total_cost_cents"]
    assert at_boundary["auto_approved"] is True
    assert at_boundary["status"] == OrderStatus.APPROVED.value


def test_a_pressure_index_of_five_eighths_rounds_half_up_to_two_decimals():
    """Five points against a capacity of eight is 0.625 and must read 0.63.

    "`pressure_index_assigned_basis` is `open_case_points` divided by `weekly_capacity_points`, rounded half up to two decimals — the headcount-planning view, in which timeline posture is ignored entirely and every open evaluation weighs its raw points."

    Design: Corner/calculations/pressure_index_round_half_up_at_two_decimals
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Verdant Elementary",
        building_code="VD41",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=350,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Cass Ono",
        employee_number="E-2016",
        credential_type="SSP",
        weekly_capacity_points=8,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-23", requested_domains=["COGNITIVE"]
    )

    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    loaded = fixtures.get_psychologist(psychologist["id"])
    assert_psychologist(loaded)
    assert loaded["open_case_points"] == 5
    assert loaded["caseload_status"] == CaseloadStatus.BALANCED.value
    # 5 / 8 is exactly 0.625; rounding half up gives 0.63, never 0.62.
    assert loaded["pressure_index_assigned_basis"] == 0.63
    assert loaded["pressure_index_clock_weighted"] == 0.63


def test_a_cancelled_evaluation_drops_out_of_the_caseload_sum_it_still_names():
    """The row keeps its psychologist for audit but leaves the open input set.

    "`open_case_points` is the sum of `caseload_points` over every evaluation whose `psychologist_id` is this psychologist and whose `assessment_status` is one of `ASSIGNED`, `IN_TESTING`, `SCORED` or `REPORT_DRAFTED`."

    Design: Corner/calculations/cancelled_evaluation_excluded_from_open_case_points
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Westbrook Middle",
        building_code="WB42",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=610,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Dara Vey",
        employee_number="E-2017",
        credential_type="SSP",
    )
    withdrawn_referral, withdrawn_evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-24", requested_domains=["COGNITIVE"]
    )
    fixtures.assign_evaluator(withdrawn_evaluation["id"], psychologist["id"])
    _, surviving_evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-25",
        requested_domains=["COGNITIVE", "ACADEMIC"],
    )
    fixtures.assign_evaluator(surviving_evaluation["id"], psychologist["id"])

    before = fixtures.get_psychologist(psychologist["id"])
    assert before["open_case_points"] == 11
    assert before["pressure_index_assigned_basis"] == 0.55

    fixtures.withdraw_consent(withdrawn_referral["id"])

    cancelled = fixtures.get_evaluation(withdrawn_evaluation["id"])
    assert cancelled["assessment_status"] == AssessmentStatus.CANCELLED.value
    assert cancelled["compliance_status"] == ComplianceStatus.WAIVED.value
    assert cancelled["psychologist_id"] == psychologist["id"]

    after = fixtures.get_psychologist(psychologist["id"])
    assert after["open_case_points"] == 6
    assert after["pressure_index_assigned_basis"] == 0.30
    assert after["pressure_index_clock_weighted"] == 0.30

    # The filter belongs to the calculation, not to the listing channel.
    _, meta = validate_paginated(
        api_client.list_evaluations(SUPERVISOR, {"psychologist_id": psychologist["id"]})
    )
    assert meta["total_count"] == 2


def test_five_and_six_breached_days_land_in_different_severity_bands():
    """One sweep straddles the MINOR ceiling, and only the six-day case diverges.

    "Its `severity` is classified from that same frozen count: `MINOR` when `breach_days` is five or fewer, `MODERATE` when it is between six and fifteen inclusive, and `SEVERE` when it is greater than fifteen."

    Design: Corner/calculations/breach_severity_bands_at_five_and_six_days
    """
    fixtures.set_clock("2026-05-31T00:00:00Z")
    school = fixtures.create_school(
        name="Yarrow High",
        building_code="YW43",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=720,
    )
    _, six_day_case = fixtures.consented_referral(
        school["id"],
        effective_at="2026-05-31T00:00:00Z",
        student_local_id="STU-26",
        requested_domains=["COGNITIVE"],
    )
    fixtures.set_clock("2026-06-01T00:00:00Z")
    _, five_day_case = fixtures.consented_referral(
        school["id"],
        effective_at="2026-06-01T00:00:00Z",
        student_local_id="STU-27",
        requested_domains=["COGNITIVE"],
    )
    fixtures.set_clock("2026-08-05T00:00:00Z")

    summary = fixtures.run_sweep()

    assert_compliance_run_summary(summary)
    assert summary["evaluated_count"] == 2
    assert summary["at_risk_evaluation_ids"] == []
    assert set(summary["breached_evaluation_ids"]) == {
        five_day_case["id"],
        six_day_case["id"],
    }

    five_day_evaluation = fixtures.get_evaluation(five_day_case["id"])
    assert five_day_evaluation["elapsed_statutory_days"] == 65
    assert five_day_evaluation["days_remaining"] == -5
    assert five_day_evaluation["compliance_status"] == ComplianceStatus.BREACHED.value

    six_day_evaluation = fixtures.get_evaluation(six_day_case["id"])
    assert six_day_evaluation["elapsed_statutory_days"] == 66
    assert six_day_evaluation["days_remaining"] == -6
    assert six_day_evaluation["compliance_status"] == ComplianceStatus.BREACHED.value

    minor = fixtures.first_breach(five_day_case["id"])
    assert_timeline_breach(minor)
    assert minor["breach_days"] == 5
    assert minor["severity"] == BreachSeverity.MINOR.value
    # 5 * 30 * 1.0 is 150, and one whole missed week * 150 * 1.0 is also 150.
    assert minor["minutes_breach_day_basis"] == 150
    assert minor["minutes_missed_service_basis"] == 150

    moderate = fixtures.first_breach(six_day_case["id"])
    assert_timeline_breach(moderate)
    assert moderate["breach_days"] == 6
    assert moderate["severity"] == BreachSeverity.MODERATE.value
    # 6 * 30 * 1.25 is 225; one whole missed week * 150 * 1.25 is 187.5, rounding up to 190.
    assert moderate["minutes_breach_day_basis"] == 225
    assert moderate["minutes_missed_service_basis"] == 190

    for breach in (minor, moderate):
        assert breach["status"] == BreachStatus.DETECTED.value
        assert breach["detected_at"].startswith("2026-08-05")
        assert breach["remedy_basis"] is None
        assert breach["corrective_action_note"] is None
        assert breach["additional_minutes"] == 0
        assert breach["remedy_minutes_awarded"] == 0
