"""The two compensatory-minute bases on one breach, and the award that commits to one."""
from test_helpers import (
    BreachSeverity,
    BreachStatus,
    ComplianceStatus,
    RemedyBasis,
    assert_timeline_breach,
    fixtures,
)


def _eight_day_breach():
    """A single-domain case swept eight days past its statutory due date."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Eastview Middle",
        building_code="EV02",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=1,
        enrollment_count=610,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Cara Blum",
        employee_number="E-1003",
        credential_type="SSP",
        languages_certified=["en"],
        weekly_capacity_points=20,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-D",
        requested_domains=["COGNITIVE"],
        intervention_team_summary="tier 3 behaviour",
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    fixtures.set_clock("2026-10-08T00:00:00Z")
    fixtures.run_sweep()
    return (
        psychologist,
        fixtures.get_evaluation(evaluation["id"]),
        fixtures.first_breach(evaluation["id"]),
    )


def test_the_two_bases_disagree_on_identical_frozen_inputs():
    """Eight breached days price at 300 minutes one way and 375 the other.

    "The two bases are never reconciled and routinely disagree; the proposal picks one and the resulting award is final."

    Design: Difficulty/dual_variant_calc/compensatory_minutes_basis_divergence_on_breach
    """
    _, evaluation, breach = _eight_day_breach()

    assert evaluation["elapsed_statutory_days"] == 68
    assert evaluation["days_remaining"] == -8
    assert evaluation["compliance_status"] == ComplianceStatus.BREACHED.value

    assert_timeline_breach(breach)
    assert breach["breach_days"] == 8
    assert breach["severity"] == BreachSeverity.MODERATE.value
    assert breach["minutes_breach_day_basis"] == 300
    assert breach["minutes_missed_service_basis"] == 375
    assert (
        breach["minutes_missed_service_basis"] - breach["minutes_breach_day_basis"]
    ) == 75


def test_a_fresh_breach_carries_both_figures_and_awards_neither():
    """Both bases are frozen at detection while the award stays at zero.

    "A breach opens in `DETECTED` status with `remedy_basis`, `corrective_action_note`, `proposed_by_user_id` and `approved_by_user_id` all null, `additional_minutes` at zero, and `remedy_minutes_awarded` at zero."

    Design: Difficulty/dual_variant_calc/compensatory_minutes_basis_divergence_on_breach
    """
    _, _, breach = _eight_day_breach()

    assert breach["status"] == BreachStatus.DETECTED.value
    assert breach["remedy_basis"] is None
    assert breach["corrective_action_note"] is None
    assert breach["proposed_by_user_id"] is None
    assert breach["approved_by_user_id"] is None
    assert breach["additional_minutes"] == 0
    assert breach["remedy_minutes_awarded"] == 0
    # The unchosen figures are nevertheless both on the record.
    assert breach["minutes_breach_day_basis"] == 300
    assert breach["minutes_missed_service_basis"] == 375


def test_the_proposal_commits_to_the_chosen_basis_plus_the_discretionary_minutes():
    """Choosing the weeks basis awards 375 plus 25, not the 300 of the other basis.

    "The breach moves `DETECTED → REMEDY_PROPOSED`, records those three inputs plus `proposed_by_user_id` from the officer's `X-User-ID`, and sets `remedy_minutes_awarded` to the frozen minutes for the chosen basis plus `additional_minutes`."

    Design: Difficulty/dual_variant_calc/compensatory_minutes_basis_divergence_on_breach
    """
    _, evaluation, breach = _eight_day_breach()

    proposed = fixtures.propose_remedy(
        breach["id"],
        RemedyBasis.MISSED_SERVICE_BASIS.value,
        additional_minutes=25,
        corrective_action_note="Weekly compensatory counselling blocks plus intake audit",
    )

    assert_timeline_breach(proposed)
    assert proposed["status"] == BreachStatus.REMEDY_PROPOSED.value
    assert proposed["remedy_basis"] == RemedyBasis.MISSED_SERVICE_BASIS.value
    assert proposed["additional_minutes"] == 25
    assert proposed["remedy_minutes_awarded"] == 400
    assert proposed["breach_days"] == 8

    # The proposal is a breach-side action and leaves the timeline alone.
    after = fixtures.get_evaluation(evaluation["id"])
    assert after["compliance_status"] == ComplianceStatus.BREACHED.value
    assert after["days_remaining"] == -8
