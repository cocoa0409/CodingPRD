"""The replant obligation cycle: escalation arithmetic, loop re-entry, and
CASCADE B's crew release plus payment hold."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_ready_world, drive_to_planted, setup_replant_required_world,
    setup_contract_with_fulfilled_replant,
    record_site_prep, verify_site_prep, mark_ready, set_clock,
)

CO = TEST_USERS["contract_officer_headers"]
FA = TEST_USERS["field_auditor_headers"]
PA = TEST_USERS["program_administrator_headers"]


def test_replant_owed_first_failure_unescalated(api):
    """PRD §3.5: "At creation the server computes `required_seedlings`" and
    PRD §3.6: "The required-survivors figure is the contract's
    `required_seedlings` multiplied by the survey's `threshold_pct` and divided
    by 100, rounded up to a whole seedling. The base shortfall is that figure
    minus the survey's `alive_count`, and never below zero. When the contract
    has already failed at least one earlier survey — an `obligation_count` of
    one or more — the base shortfall is escalated by a factor of 1.25 and the
    product rounded up to a whole seedling; a first failure stands unescalated."

    Design: Difficulty/combinatorial_formula/replant_owed_first_vs_repeat_escalation
    """
    ctx = setup_ready_world(acres=40, trees_per_acre=430, contingency_pct=0.05,
                            order_quantity=19000, window_end="2028-12-31")
    assert ctx["required_seedlings"] == 18060, (
        f"ceil(40 * 430 * 1.05) = 18060, got {ctx['required_seedlings']}"
    )
    ctx = drive_to_planted(ctx, plant_date="2027-04-01", assignment_days=4)

    set_clock("2028-02-15T00:00:00Z")
    survey = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2028-02-15", "alive_count": 11000}, FA
        )
    )
    assert survey["obligation_status"] == "OPEN"
    assert survey["owed_quantity"] == 1642, (
        "first failure stands unescalated: ceil(18060 * 0.70) - 11000 = "
        f"12642 - 11000 = 1642, got {survey['owed_quantity']}"
    )


def test_replant_owed_repeat_failure_escalated(api):
    """PRD §3.6: "When the contract has already failed at least one earlier
    survey — an `obligation_count` of one or more — the base shortfall is
    escalated by a factor of 1.25 and the product rounded up to a whole
    seedling; a first failure stands unescalated. The survey's `owed_quantity`
    is then the smaller of two values: twice the `planted_count_snapshot`, and
    the smaller of the `planted_count_snapshot` and the possibly escalated
    shortfall."

    Design: Difficulty/combinatorial_formula/replant_owed_first_vs_repeat_escalation
    """
    ctx = setup_contract_with_fulfilled_replant()
    assert ctx["owed_1"] == 1642, (
        f"first failure must owe 1642, got {ctx['owed_1']}"
    )
    assert ctx["survey_1"]["obligation_status"] == "FULFILLED"

    set_clock("2029-05-01T00:00:00Z")
    survey_2 = get_success_data(
        api.create_survival_survey(
            {"planting_contract_id": ctx["contract"]["id"],
             "surveyed_on": "2029-05-01", "alive_count": 12000}, FA
        )
    )
    assert survey_2["obligation_status"] == "OPEN"
    assert survey_2["owed_quantity"] == 803, (
        "repeat failure escalates: ceil((12642 - 12000) * 1.25) = ceil(802.5) "
        f"= 803, got {survey_2['owed_quantity']}"
    )


def test_replant_loop_reenters_site_prep(api):
    """PRD §3.5: "The same recording action from `REPLANT_REQUIRED` closes the
    replant loop, again landing at `SITE_PREP` with `RECORDED`, which supersedes
    any earlier `VERIFIED` from the prior cycle." and PRD §3.6: "From
    `REPLANT_REQUIRED`, the contract re-enters the site-prep loop of §3.5,
    plants again, and is surveyed again in a new window."

    Design: Difficulty/non_linear_state_machine/contract_replant_loop_returns_to_ready
    """
    ctx = setup_replant_required_world(alive_count=2700)  # 67.50 < 70.00
    assert ctx["contract"]["status"] == "REPLANT_REQUIRED"
    assert ctx["survey"]["obligation_status"] == "OPEN"

    set_clock("2028-06-01T00:00:00Z")
    contract = record_site_prep(ctx["contract"]["id"], "2028-05-20")
    assert contract["status"] == "SITE_PREP", (
        f"record-site-prep closes the replant loop, got {contract['status']}"
    )
    assert contract["site_prep_status"] == "RECORDED", (
        "the fresh recording supersedes the prior cycle's VERIFIED"
    )


def test_replant_loop_reaches_ready_to_plant_again(api):
    """PRD §3.5: "The same recording action from `REPLANT_REQUIRED` closes the
    replant loop, again landing at `SITE_PREP` with `RECORDED`, which supersedes
    any earlier `VERIFIED` from the prior cycle. Independent verification by a
    `FieldAuditor` then advances `site_prep_status` from `RECORDED` to
    `VERIFIED`" and "Marking a contract ready moves it from `SITE_PREP` or
    `BLOCKED` to `READY_TO_PLANT`"

    Design: Difficulty/non_linear_state_machine/contract_replant_loop_returns_to_ready
    """
    ctx = setup_replant_required_world(alive_count=2700)
    contract_id = ctx["contract"]["id"]

    set_clock("2028-06-01T00:00:00Z")
    record_site_prep(contract_id, "2028-05-20")
    verified = verify_site_prep(contract_id)
    assert verified["site_prep_status"] == "VERIFIED"
    ready = mark_ready(contract_id)
    assert ready["status"] == "READY_TO_PLANT", (
        "the loop closes: READY_TO_PLANT is reached a second time"
    )


def _cascade_b_world(api):
    """Landowner with an APPROVED enrollment (threshold 80.00); contract planted
    with one CONFIRMED crew (auto-completed) plus one still-SCHEDULED follow-up
    assignment; surveyed at 67.50 < 80.00."""
    ctx = setup_replant_required_world(
        alive_count=2700,
        enrollment={},
        extra_assignments=(
            {"start_date": "2027-04-10", "end_date": "2027-04-12",
             "planned_seedlings": 2000, "confirm": False},
        ),
    )
    return ctx


def test_below_threshold_survey_releases_pending_crew(api):
    """PRD §3.6: "CASCADE B opens the survey's embedded replant obligation — its
    `obligation_status` moves from `NONE` to `OPEN` with the `owed_quantity`
    computed — releases every `SCHEDULED` or `CONFIRMED` crew assignment of the
    contract" and PRD §3.5: "every `CONFIRMED` crew assignment of the contract
    is automatically marked `COMPLETED`"

    Design: Difficulty/transitive_cascade/below_threshold_survey_releases_crew_and_holds_payment
    """
    ctx = _cascade_b_world(api)
    assert ctx["contract"]["status"] == "REPLANT_REQUIRED"

    follow_up = ctx["extra_assignments"][0]
    asg_after = get_success_data(api.get_crew_assignment(follow_up["id"], CO))
    assert asg_after["status"] == "RELEASED", (
        "the still-SCHEDULED follow-up assignment must be released by CASCADE B"
    )

    completed = get_success_data(api.get_crew_assignment(ctx["assignment"]["id"], CO))
    assert completed["status"] == "COMPLETED", (
        "the already-completed assignment is terminal and untouched"
    )


def test_below_threshold_survey_holds_enrollment_payment(api):
    """PRD §3.6: "CASCADE B opens the survey's embedded replant obligation — its
    `obligation_status` moves from `NONE` to `OPEN` with the `owed_quantity`
    computed — releases every `SCHEDULED` or `CONFIRMED` crew assignment of the
    contract, and, if the contract's landowner holds a cost-share enrollment in
    `APPROVED`, moves that enrollment to `PAYMENT_HELD`."

    Design: Difficulty/transitive_cascade/below_threshold_survey_releases_crew_and_holds_payment
    """
    ctx = _cascade_b_world(api)
    assert ctx["contract"]["status"] == "REPLANT_REQUIRED", (
        "the failing survey must flip the contract (cascade link 1)"
    )

    enrollment = get_success_data(
        api.get_cost_share_enrollment(ctx["enrollment"]["id"], PA)
    )
    assert enrollment["status"] == "PAYMENT_HELD", (
        f"the landowner's APPROVED enrollment must be held, got {enrollment['status']}"
    )
