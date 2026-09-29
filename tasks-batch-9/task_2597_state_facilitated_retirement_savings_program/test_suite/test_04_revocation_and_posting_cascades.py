"""
Two single writes whose consequences travel several hops away from the trigger.

Losing a qualified-plan exemption walks a chain: the certification dies, the
mandate falls back, an overdue deadline mints an automatic penalty, and an
existing affirmed penalty is escalated to an outside agency. Posting a payroll
batch fans out instead of walking: the batch and its lines settle, a saver's
account fills past the annual ceiling, a case that did not exist before is
opened against that account, the account is held, and the employer's arrears
clear.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import (
    ADMIN,
    ADMIN_REVIEWER,
    EMPLOYER_RIDGE,
    OFFICER_A,
    OFFICER_B,
    OFFICER_C,
    RECORDKEEPER,
    SYSTEM_ACTOR,
    add_remittance_line,
    build_active_saver_environment,
    build_employer_environment,
    create_remittance,
    decide_exemption,
    dispose_penalty,
    file_exemption,
    find_row,
    fund_account_by_remittance,
    post_earnings,
    read_account,
    read_employer,
    read_exemption,
    read_remittance,
    read_remittance_line,
    revoke_exemption,
    set_clock,
    submit_remittance,
)


def _build_exempt_shop_with_an_affirmed_penalty(api):
    """
    A large unregistered shop whose enrolment failure was assessed and affirmed,
    which then obtained a qualified-plan exemption, with the clock one day past
    its wave deadline of 30 June 2026.
    """
    env = build_employer_environment(api, employer=EMPLOYER_RIDGE, register=False)
    set_clock(api, "2026-02-01T00:00:00Z")
    penalty = validate_success(api.create_penalty_assessment(
        env["employer_id"],
        {"violation_type": "FAILURE_TO_ENROLL", "notice_date": "2025-10-01",
         "cure_days": 30},
        OFFICER_A), 201)
    dispose_penalty(api, penalty["id"], "AFFIRM",
                    "Employer did not respond to notice", OFFICER_B)
    certification = file_exemption(api, env["employer_id"],
                                   plan_sponsor_ein="77-8889990")
    decide_exemption(api, certification["id"], "APPROVE",
                     "Plan documents verified", ADMIN_REVIEWER)
    set_clock(api, "2026-07-01T00:00:00Z")
    env["penalty_id"] = penalty["id"]
    env["certification_id"] = certification["id"]
    return env


def _withdraw_the_exemption(api, env):
    """Pull the exemption once the qualified plan turns out to be gone."""
    return revoke_exemption(
        api, env["certification_id"],
        "Qualified plan terminated retroactively to 2026-01-01", OFFICER_C)


def _employer_penalties(api, employer_id):
    """Every assessment on the employer's file."""
    return validate_paginated(
        api.list_employer_penalty_assessments(employer_id, ADMIN))


def _build_saver_one_batch_from_the_ceiling(api):
    """
    A saver credited 400000 cents and 50000 cents of earnings, with a second
    400000-cent batch handed over but not yet posted, which will break the
    700000-cent annual ceiling by 100000 cents when it lands.
    """
    env = build_active_saver_environment(api)
    fund_account_by_remittance(
        api, env, "2026-02-01", "2026-02-28", "2026-03-05",
        8000000, 400000, "2026-03-06T00:00:00Z",
        posting_reference="PR-2026-0001")
    post_earnings(api, env["account_id"], 50000, "2026-03-06")
    set_clock(api, "2026-04-05T00:00:00Z")
    batch = create_remittance(api, env["employer_id"], "2026-03-01", "2026-03-31",
                              "2026-04-03", 400000)
    line = add_remittance_line(api, batch["id"], env["employer_id"],
                               env["enrollment_id"], 8000000, 400000)
    submit_remittance(api, batch["id"], env["employer_id"])
    env["remittance_id"] = batch["id"]
    env["line_id"] = line["id"]
    return env


def _post_the_second_batch(api, env):
    """The recordkeeper lands the second batch on the saver's account."""
    return validate_success(api.post_remittance(
        env["remittance_id"], {"posting_reference": "PR-2026-0002"},
        RECORDKEEPER))


def _account_excess_cases(api, account_id):
    """Every excess-contribution case standing against the account."""
    return validate_paginated(api.list_account_excess_cases(account_id, ADMIN))


def test_losing_the_exemption_reopens_the_mandate_and_mints_a_penalty(api):
    """One revocation kills the certification, reopens the mandate and prices it.

    The certification is revoked, the shop is back to awaiting registration, and
    because its 30 June 2026 deadline has already passed the programme raises a
    second assessment by itself, for failing to register, noticed on that very
    deadline and signed by the system rather than by an officer.

    "A penalty assessment is then minted automatically with `violation_type`
    `FAILURE_TO_REGISTER`, `origin` `SYSTEM_CASCADE`, `notice_date` set to the
    employer's `registration_deadline` and `assessed_by_user_id` set to the literal
    `SYSTEM`, which drives `compliance_status` on to `PENALIZED`."

    Design: Difficulty/transitive_cascade/exemption_revocation_cascades_four_levels_to_enforcement_referral
    """
    env = _build_exempt_shop_with_an_affirmed_penalty(api)

    _withdraw_the_exemption(api, env)

    assert read_exemption(api, env["certification_id"])["status"] == "REVOKED"
    assert read_employer(api, env["employer_id"])["registration_status"] == (
        "PENDING_REGISTRATION")

    rows, meta = _employer_penalties(api, env["employer_id"])
    assert meta["total_count"] == 2
    minted = [row for row in rows if row["origin"] == "SYSTEM_CASCADE"]
    assert len(minted) == 1
    assert minted[0]["violation_type"] == "FAILURE_TO_REGISTER"
    assert minted[0]["notice_date"] == "2026-06-30"
    assert minted[0]["assessed_by_user_id"] == SYSTEM_ACTOR
    assert minted[0]["status"] == "ASSESSED"


def test_the_chain_ends_at_an_agency_referral_on_the_older_penalty(api):
    """The escalation attaches to the affirmed penalty, not the one just minted.

    The revocation opens a single referral, and it hangs off the assessment that
    was already affirmed. The newly minted assessment is still inside its own cure
    period and carries no referral of its own. The shop's enforcement dimension
    ends the request at referred, one step beyond penalised.

    "Finally, if — and only if — the employer already has a separate assessment in
    status `AFFIRMED`, an enforcement referral is minted **on that pre-existing
    affirmed assessment**, not on the assessment just created, which is still
    inside its own cure period and cannot yet be affirmed; that referral carries
    `agency` `STATE_LABOR_COMMISSIONER` and `referred_by_user_id` `SYSTEM`, and
    pushes `compliance_status` to `REFERRED`."

    Design: Difficulty/transitive_cascade/exemption_revocation_cascades_four_levels_to_enforcement_referral
    """
    env = _build_exempt_shop_with_an_affirmed_penalty(api)

    _withdraw_the_exemption(api, env)

    assert read_employer(api, env["employer_id"])["compliance_status"] == "REFERRED"

    rows, meta = validate_paginated(
        api.list_enforcement_referrals(env["penalty_id"], ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "OPEN"
    assert rows[0]["agency"] == "STATE_LABOR_COMMISSIONER"
    assert rows[0]["referred_by_user_id"] == SYSTEM_ACTOR
    assert rows[0]["employer_ein_snapshot"] == "77-8889990"

    penalties, _ = _employer_penalties(api, env["employer_id"])
    minted = find_row(penalties, origin="SYSTEM_CASCADE")
    _, fresh_meta = validate_paginated(
        api.list_enforcement_referrals(minted["id"], ADMIN))
    assert fresh_meta["total_count"] == 0


def test_the_automatic_penalty_is_priced_at_nothing_while_the_old_one_stands(api):
    """The new assessment is one day old, so its statutory figure is still zero.

    Only one day separates the 30 June 2026 notice from the assessment, well short
    of the ninety days the first tier needs, so nothing accrues on the automatic
    assessment. The affirmed assessment beside it is untouched, still owing the
    3000000 cents that 120 employees and 123 days of notice produced.

    "Starting from zero, if that day count is at least the program year's
    `notice_period_days`, the figure gains `employee_count_at_assessment`
    multiplied by `register_penalty_initial_cents_per_employee`; then, if the day
    count is also at least `sustained_notice_days`, the figure gains a further
    `employee_count_at_assessment` multiplied by
    `register_penalty_sustained_cents_per_employee`."

    Design: Difficulty/transitive_cascade/exemption_revocation_cascades_four_levels_to_enforcement_referral
    """
    env = _build_exempt_shop_with_an_affirmed_penalty(api)

    _withdraw_the_exemption(api, env)

    rows, _ = _employer_penalties(api, env["employer_id"])
    minted = find_row(rows, origin="SYSTEM_CASCADE")
    assert minted["statutory_amount_cents"] == 0
    assert minted["assessed_cents"] == 0

    older = find_row(rows, id=env["penalty_id"])
    assert older["origin"] == "MANUAL"
    assert older["status"] == "AFFIRMED"
    assert older["statutory_amount_cents"] == 3000000
    assert older["assessed_cents"] == 3000000
    assert older["cure_deadline"] == "2025-10-31"


def test_posting_credits_the_line_in_full_and_records_the_overage(api):
    """The whole withheld amount is credited, with the overage noted beside it.

    Only 300000 cents of room were left before this batch, so 100000 of the
    400000 cents is over the ceiling. The line still allocates all 400000, the
    overage is recorded rather than refused, and the batch's totals mirror the
    single line.

    "For each line, the room available before that line is the ceiling minus the
    year-to-date total accumulated so far, floored at zero; the line's
    `excess_cents` is its `allocated_cents` minus that room, likewise floored at
    zero."

    Design: Difficulty/transitive_cascade/remittance_posting_cascades_to_excess_case_and_restricted_posture
    """
    env = _build_saver_one_batch_from_the_ceiling(api)

    _post_the_second_batch(api, env)

    batch = read_remittance(api, env["remittance_id"])
    assert batch["status"] == "POSTED"
    assert batch["total_allocated_cents"] == 400000
    assert batch["total_excess_cents"] == 100000
    assert batch["line_count"] == 1

    line = read_remittance_line(api, env["remittance_id"], env["line_id"])
    assert line["status"] == "POSTED"
    assert line["allocated_cents"] == 400000
    assert line["excess_cents"] == 100000
    assert line["expected_deduction_cents"] == 400000


def test_the_same_posting_opens_a_case_on_the_savers_account(api):
    """A case that did not exist before the posting is opened by it.

    Exactly one case stands against the account. It captures the 100000-cent
    overage, the 450000 cents the account held immediately before the posting, the
    400000 cents that carried the overage in, the clock date of 5 April 2026 as
    its computation start, and the following spring's filing date as its deadline.

    "For every account that crossed its ceiling during the posting, a single
    excess-contribution case is opened in status `DETECTED`, capturing the
    account's `account_id`, the program year's `calendar_year`, the
    `detected_excess_cents`, the `detected_at_pay_date` taken from the pay date of
    the batch whose posting produced the excess, the `opening_fmv_cents` recorded
    as the account's `balance_cents` immediately *before* this posting, the
    `period_contributions_cents` begun with the deposit that carried the excess,
    the `computation_period_start` set to the clock's date at detection, and the
    `deadline_date` described in §3.6."

    Design: Difficulty/transitive_cascade/remittance_posting_cascades_to_excess_case_and_restricted_posture
    """
    env = _build_saver_one_batch_from_the_ceiling(api)
    before, before_meta = _account_excess_cases(api, env["account_id"])
    assert before_meta["total_count"] == 0

    _post_the_second_batch(api, env)

    rows, meta = _account_excess_cases(api, env["account_id"])
    assert meta["total_count"] == 1
    case = rows[0]
    assert case["status"] == "DETECTED"
    assert case["detected_excess_cents"] == 100000
    assert case["opening_fmv_cents"] == 450000
    assert case["period_contributions_cents"] == 400000
    assert case["computation_period_start"] == "2026-04-05"
    assert case["deadline_date"] == "2027-04-15"


def test_the_credited_account_is_full_and_held_against_new_movement(api):
    """The money lands, the annual room is gone, and the account is held.

    Balance and basis both take the 400000 cents, the year-to-date total reaches
    800000 against a 700000-cent ceiling so the remaining room floors at zero, and
    the unresolved case leaves the account restricted rather than free.

    "Each affected account has its `balance_cents`, `contribution_basis_cents` and
    `ytd_contribution_cents` increased by the amounts credited to it, its
    `remaining_headroom_cents` recomputed, its fund split re-derived, and its
    `version` incremented."

    Design: Difficulty/transitive_cascade/remittance_posting_cascades_to_excess_case_and_restricted_posture
    """
    env = _build_saver_one_batch_from_the_ceiling(api)

    _post_the_second_batch(api, env)

    account = read_account(api, env["account_id"])
    assert account["balance_cents"] == 850000
    assert account["contribution_basis_cents"] == 800000
    assert account["ytd_contribution_cents"] == 800000
    assert account["remaining_headroom_cents"] == 0
    assert account["posture"] == "RESTRICTED"


def test_the_arrived_money_leaves_the_employer_owing_nothing(api):
    """Once posted, the batch stops counting against the employer.

    Posted money has reached the programme, so the employer's arrears figure reads
    zero and its enforcement dimension reads compliant.

    "The employer's `unremitted_deduction_cents` and `compliance_status` are
    recomputed, since the money has now arrived."

    Design: Difficulty/transitive_cascade/remittance_posting_cascades_to_excess_case_and_restricted_posture
    """
    env = _build_saver_one_batch_from_the_ceiling(api)

    _post_the_second_batch(api, env)

    employer = read_employer(api, env["employer_id"])
    assert employer["unremitted_deduction_cents"] == 0
    assert employer["compliance_status"] == "COMPLIANT"
