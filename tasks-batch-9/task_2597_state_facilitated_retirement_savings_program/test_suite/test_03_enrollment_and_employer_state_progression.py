"""
Two state machines that do not simply run forwards along a single line.

An enrolment can leave the active state and come back, but coming back is not a
restoration: the saver's own deferral rate is thrown away and the programme
default is seeded afresh, while a counter records that the loop happened. An
employer carries two separate status dimensions on one row, and the enforcement
dimension can walk several steps without the mandate dimension moving at all.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import (
    EMPLOYER_HARBOR,
    OFFICER_ASSESSOR,
    activate_savers,
    add_remittance_line,
    build_active_saver_environment,
    build_employer_environment,
    build_notified_saver,
    create_remittance,
    elect_rate,
    read_employer,
    read_enrollment,
    read_remittance,
    reenroll,
    opt_out,
    run_compliance_sweep,
    set_clock,
    submit_remittance,
)


def _build_opted_out_saver_on_an_elected_rate(api):
    """
    An activated saver who elected 700 basis points of their own and then opted
    out for affordability, so the enrolment sits outside the programme.
    """
    env = build_active_saver_environment(api)
    elect_rate(api, env["enrollment_id"], env["participant_id"], 700)
    opt_out(api, env["enrollment_id"], env["participant_id"], "AFFORDABILITY")
    return env


def _build_registered_five_employee_shop(api):
    """A five-employee shop that has completed registration and owes nothing yet."""
    env = build_employer_environment(api, employer=EMPLOYER_HARBOR)
    build_notified_saver(api, env, hire_date="2025-12-01",
                         annual_compensation_cents=19200000)
    return env


def _leave_deductions_unremitted(api, env):
    """
    Withhold 800000 cents for a December payroll, hand the batch over but never
    post it, then run the year-end sweep so the money reads as overdue.
    """
    activate_savers(api, env)
    batch = create_remittance(api, env["employer_id"], "2025-12-01", "2025-12-31",
                              "2026-01-02", 800000)
    add_remittance_line(api, batch["id"], env["employer_id"],
                        env["enrollment_id"], 16000000, 800000)
    submit_remittance(api, batch["id"], env["employer_id"])
    env["remittance_id"] = batch["id"]
    set_clock(api, "2026-12-31T00:00:00Z")
    run_compliance_sweep(api)
    return env


def _assess_the_unremitted_money(api, env):
    """Raise a shortfall assessment on the shop with thirty days to cure."""
    return validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_REMIT", "notice_date": "2026-10-02",
         "cure_days": 30},
        OFFICER_ASSESSOR), 201)


def test_coming_back_reseeds_the_programme_default_rate(api):
    """Re-entry discards the saver's seven-percent choice and restores five percent.

    The enrolment returns to active, but the 700 basis points the saver had chosen
    are gone and the rate reads the program year's default of 500 basis points
    with the rate attributed to the programme rather than to the saver.

    "On success the enrolment moves `OPTED_OUT → ACTIVE`, and the rate is
    deliberately **not** resumed: `contribution_rate_bp` is reset to the program
    year's `default_contribution_rate_bp` with `rate_source` back to `DEFAULT`,
    `escalation_opt_out` is cleared to false, `reenrollment_count` increments by
    one, and `opted_out_at` and `opt_out_reason_code` are cleared."

    Design: Difficulty/non_linear_state_machine/enrollment_opt_out_then_reenroll_cycle_resets_rate_to_default
    """
    env = _build_opted_out_saver_on_an_elected_rate(api)

    enrollment = reenroll(api, env["enrollment_id"], env["participant_id"])

    assert enrollment["enrollment_status"] == "ACTIVE"
    assert enrollment["contribution_rate_bp"] == 500
    assert enrollment["contribution_rate_bp"] != 700
    assert enrollment["rate_source"] == "DEFAULT"


def test_the_loop_is_counted_and_the_opt_out_trail_is_cleared(api):
    """The round trip leaves a count of one behind and no live opt-out.

    Exactly one completed cycle is recorded, the escalation waiver the opt-out
    period could have carried is back to false, and nothing remains to say the
    saver is currently out of the programme.

    "On success the enrolment moves `OPTED_OUT → ACTIVE`, and the rate is
    deliberately **not** resumed: `contribution_rate_bp` is reset to the program
    year's `default_contribution_rate_bp` with `rate_source` back to `DEFAULT`,
    `escalation_opt_out` is cleared to false, `reenrollment_count` increments by
    one, and `opted_out_at` and `opt_out_reason_code` are cleared."

    Design: Difficulty/non_linear_state_machine/enrollment_opt_out_then_reenroll_cycle_resets_rate_to_default
    """
    env = _build_opted_out_saver_on_an_elected_rate(api)

    reenroll(api, env["enrollment_id"], env["participant_id"])

    enrollment = read_enrollment(api, env["enrollment_id"])
    assert enrollment["reenrollment_count"] == 1
    assert enrollment["escalation_opt_out"] is False
    assert enrollment["opted_out_at"] is None
    assert enrollment["opt_out_reason_code"] is None


def test_the_elected_rate_survives_the_opt_out_and_dies_on_re_entry(api):
    """While the saver is out, the chosen rate is still on the record; re-entry ends it.

    An opted-out enrolment keeps the saver's own 700 basis points and the reason
    they gave, so the history of the decision is readable. Only the re-enrolment
    overwrites it.

    "Either way `opted_out_at` is stamped from the clock and
    `opt_out_reason_code` is stored, and the enrolment's `contribution_rate_bp` is
    retained as audit history until a re-enrolment resets it."

    Design: Difficulty/non_linear_state_machine/enrollment_opt_out_then_reenroll_cycle_resets_rate_to_default
    """
    env = _build_opted_out_saver_on_an_elected_rate(api)

    while_out = read_enrollment(api, env["enrollment_id"])
    assert while_out["enrollment_status"] == "OPTED_OUT"
    assert while_out["contribution_rate_bp"] == 700
    assert while_out["rate_source"] == "PARTICIPANT_ELECTED"
    assert while_out["opt_out_reason_code"] == "AFFORDABILITY"
    assert while_out["opted_out_at"] is not None

    reenroll(api, env["enrollment_id"], env["participant_id"])

    back_in = read_enrollment(api, env["enrollment_id"])
    assert back_in["contribution_rate_bp"] == 500
    assert back_in["rate_source"] != "PARTICIPANT_ELECTED"


def test_the_enforcement_dimension_walks_compliant_then_delinquent_then_penalized(api):
    """One shop passes through three enforcement states as the facts accumulate.

    A freshly registered shop owes nothing and reads compliant. Once withheld
    money goes past its due date the derivation drops it to delinquent, and once
    an assessment exists the higher condition takes over and it reads penalised.

    "`compliance_status` is then re-derived from the highest applicable condition
    downwards. If any enforcement referral raised on any of this employer's
    assessments is in status `OPEN`, the employer is `REFERRED`. Otherwise, if any
    of its penalty assessments is in status `ASSESSED` or `AFFIRMED`, it is
    `PENALIZED`. Otherwise, if `unremitted_deduction_cents` is greater than zero,
    it is `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/employer_registration_and_compliance_dimensions_advance_independently
    """
    env = _build_registered_five_employee_shop(api)
    assert read_employer(api, env["employer_id"])["compliance_status"] == "COMPLIANT"

    _leave_deductions_unremitted(api, env)
    assert read_employer(api, env["employer_id"])["compliance_status"] == "DELINQUENT"

    _assess_the_unremitted_money(api, env)

    assert read_employer(api, env["employer_id"])["compliance_status"] == "PENALIZED"


def test_the_mandate_dimension_never_moves_while_enforcement_escalates(api):
    """Being penalised says nothing about whether the shop is validly registered.

    The shop reaches the penalised end of the enforcement dimension while its
    mandate dimension still reads registered, and in particular has not fallen
    back to awaiting registration.

    "An employer carries **two independent state dimensions on the same row**, and
    confusing them is the most common misreading of this domain."

    Design: Difficulty/non_linear_state_machine/employer_registration_and_compliance_dimensions_advance_independently
    """
    env = _build_registered_five_employee_shop(api)
    _leave_deductions_unremitted(api, env)

    _assess_the_unremitted_money(api, env)

    employer = read_employer(api, env["employer_id"])
    assert employer["registration_status"] == "REGISTERED"
    assert employer["registration_status"] != "PENDING_REGISTRATION"
    assert employer["compliance_status"] == "PENALIZED"


def test_the_handed_over_but_unposted_batch_is_the_money_still_owed(api):
    """The batch stays handed over, and its whole declared total reads as owed.

    Assessing the shop neither posts nor rejects the batch, so it remains in the
    submitted state and its 800000 cents continue to count as money withheld from
    savers and not passed on.

    "First the programme computes `unremitted_deduction_cents`, the sum of
    `total_deducted_cents` over that employer's remittance batches whose status is
    `DRAFT` or `SUBMITTED` and whose `pay_date` plus the program year's
    `remittance_due_days` is strictly earlier than the current clock date."

    Design: Difficulty/non_linear_state_machine/employer_registration_and_compliance_dimensions_advance_independently
    """
    env = _build_registered_five_employee_shop(api)
    _leave_deductions_unremitted(api, env)

    penalty = _assess_the_unremitted_money(api, env)

    assert read_employer(api, env["employer_id"])["unremitted_deduction_cents"] == 800000
    assert read_remittance(api, env["remittance_id"])["status"] == "SUBMITTED"
    assert penalty["status"] == "ASSESSED"
    assert penalty["violation_type"] == "FAILURE_TO_REMIT"
