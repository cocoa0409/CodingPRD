"""
Two requests that break two rules at once, where only one refusal may be given.

A closed account asked for money it does not have breaks a lifecycle rule and a
money rule together, and the lifecycle answer must win even though the two carry
different HTTP statuses. An employer under an open agency referral filing a
certification for a long-expired plan breaks an enforcement rule and a temporal
rule together, and both refusals share the same status, so only the ordering
tells them apart.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ADMIN_REVIEWER,
    EMPLOYER_RIDGE,
    ERR_ACCOUNT_CLOSED,
    ERR_ACCOUNT_RESTRICTED,
    ERR_ENFORCEMENT_HOLD,
    ERR_EXEMPTION_WINDOW_CLOSED,
    ERR_INSUFFICIENT_ACCOUNT_BALANCE,
    OFFICER_A,
    OFFICER_B,
    OFFICER_C,
    build_closed_account_environment,
    build_employer_environment,
    decide_exemption,
    dispose_penalty,
    file_exemption,
    make_employer_headers,
    make_participant_headers,
    read_account,
    read_employer,
    revoke_exemption,
    set_clock,
)


def _ask_the_closed_account_for_fifty_thousand_dollars(api, env):
    """Try to roll 5000000 cents out of an account that holds nothing."""
    return api.create_portability_transfer(
        {
            "participant_id": env["participant_id"],
            "source_account_id": env["account_id"],
            "destination_type": "EXTERNAL_IRA",
            "external_institution_name": "Northline Trust Company",
            "transfer_kind": "DIRECT_ROLLOVER",
            "amount_cents": 5000000,
        },
        make_participant_headers(env["participant_id"]))


def _build_employer_under_an_open_referral(api):
    """
    A large shop whose affirmed enrolment penalty was escalated to an agency by
    the revocation of its exemption, leaving the referral open at 1 July 2026.
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
    revoke_exemption(api, certification["id"],
                     "Qualified plan terminated retroactively to 2026-01-01",
                     OFFICER_C)
    env["certification_id"] = certification["id"]
    return env


def _claim_an_exemption_on_a_plan_from_2021(api, env):
    """File for a plan whose three-year coverage ran out on 1 January 2024."""
    return api.create_exemption_certification(
        env["employer_id"],
        {
            "qualified_plan_type": "403B",
            "plan_sponsor_ein": "77-8889990",
            "plan_effective_date": "2021-01-01",
            "attestation_accepted": True,
        },
        make_employer_headers(env["employer_id"]))


def _certifications_on_file(api, employer_id):
    """Every certification the employer's record carries."""
    return validate_paginated(
        api.list_employer_exemption_certifications(employer_id, ADMIN))


def test_a_closed_account_reports_its_closure_and_not_its_empty_balance(api):
    """Asking a closed, empty account for 5000000 cents is refused as closed.

    The request breaks two rules at once, since a closed account necessarily holds
    nothing. The lifecycle refusal is the one returned, with its own 409 status,
    and the payment-required answer about affordability is not given.

    "Ranking money last means every structural, temporal and coherence problem is
    reported before the question of whether the account can afford the request — so
    a closed account presented with an oversized request reports
    `ERR_ACCOUNT_CLOSED`, never the balance error."

    Design: Difficulty/priority_pair_validation_conflict/closed_account_state_gate_outranks_fiscal_sufficiency_check
    """
    env = build_closed_account_environment(api)

    response = _ask_the_closed_account_for_fifty_thousand_dollars(api, env)

    error = validate_error(response, ERR_ACCOUNT_CLOSED, 409)
    assert error["error_id"] != ERR_INSUFFICIENT_ACCOUNT_BALANCE
    assert response.status_code != 402


def test_the_locked_gate_of_a_closed_account_is_not_the_answer_given(api):
    """The closed account is also locked, but locking is the later gate.

    The account is closed with nothing in it and its derived gate reads locked, yet
    the refusal names the closure rather than the lock.

    "This sits strictly *after* the closed-account gate, so a `CLOSED` account —
    whose posture is also `LOCKED` — always reports `ERR_ACCOUNT_CLOSED` and never
    `ERR_ACCOUNT_RESTRICTED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_account_state_gate_outranks_fiscal_sufficiency_check
    """
    env = build_closed_account_environment(api)

    response = _ask_the_closed_account_for_fifty_thousand_dollars(api, env)

    error = validate_error(response, ERR_ACCOUNT_CLOSED, 409)
    assert error["error_id"] != ERR_ACCOUNT_RESTRICTED

    account = read_account(api, env["account_id"])
    assert account["account_status"] == "CLOSED"
    assert account["balance_cents"] == 0
    assert account["posture"] == "LOCKED"


def test_the_refused_rollover_leaves_no_movement_on_the_savers_file(api):
    """Nothing is recorded for a request that was turned away.

    The saver's portability history is still empty after the refusal, so no
    in-flight leg and no fee were created by the attempt.

    "The request is refused with `ERR_ACCOUNT_CLOSED` when the source account is
    `CLOSED`, with `ERR_ACCOUNT_RESTRICTED` when its posture is `RESTRICTED` or
    `LOCKED`, and with `ERR_INSUFFICIENT_ACCOUNT_BALANCE` when the gross
    `amount_cents` exceeds the source `balance_cents`."

    Design: Difficulty/priority_pair_validation_conflict/closed_account_state_gate_outranks_fiscal_sufficiency_check
    """
    env = build_closed_account_environment(api)

    response = _ask_the_closed_account_for_fifty_thousand_dollars(api, env)

    validate_error(response, ERR_ACCOUNT_CLOSED, 409)
    _, meta = validate_paginated(api.list_portability_transfers(
        make_participant_headers(env["participant_id"]),
        {"participant_id": env["participant_id"]}))
    assert meta["total_count"] == 0


def test_the_agency_hold_answers_before_the_expired_plan_window_does(api):
    """A stale plan date filed under an open referral is refused as a hold.

    The 2021 plan's three-year coverage ended on 1 January 2024, well behind the
    1 July 2026 clock, so the filing is doubly invalid. The enforcement interlock
    is the higher-ranked of the two and is the refusal returned; both answers carry
    the same 409 status, so only the ordering distinguishes them.

    "Filing an exemption certification or restating an employee count while the
    employer has at least one enforcement referral in status `OPEN` yields
    `ERR_ENFORCEMENT_HOLD`."

    "This deliberately outranks the temporal checks, so an employer under referral
    is told about the hold rather than about a stale plan date."

    Design: Difficulty/priority_pair_validation_conflict/enforcement_hold_outranks_exemption_coverage_window_temporal_check
    """
    env = _build_employer_under_an_open_referral(api)

    response = _claim_an_exemption_on_a_plan_from_2021(api, env)

    error = validate_error(response, ERR_ENFORCEMENT_HOLD, 409)
    assert error["error_id"] != ERR_EXEMPTION_WINDOW_CLOSED


def test_the_refused_filing_adds_nothing_to_the_certification_file(api):
    """The employer's file still holds only the certification it lost.

    A refused filing creates no submitted certification, so the single row on the
    file is the revoked one from before.

    "If the employer is under an `OPEN` referral, `ERR_ENFORCEMENT_HOLD` is
    reported instead of either of those, since the enforcement interlock outranks
    both the overlap and the window check."

    Design: Difficulty/priority_pair_validation_conflict/enforcement_hold_outranks_exemption_coverage_window_temporal_check
    """
    env = _build_employer_under_an_open_referral(api)

    response = _claim_an_exemption_on_a_plan_from_2021(api, env)

    validate_error(response, ERR_ENFORCEMENT_HOLD, 409)
    rows, meta = _certifications_on_file(api, env["employer_id"])
    assert meta["total_count"] == 1
    assert rows[0]["id"] == env["certification_id"]
    assert rows[0]["status"] == "REVOKED"


def test_the_held_employer_stays_unregistered_and_referred(api):
    """Being refused changes nothing about where the employer stands.

    The shop is still awaiting registration and still sits with an outside agency,
    which is precisely why it may not file a fresh certification.

    "Creating the referral pushes the employer's `compliance_status` to `REFERRED`,
    increments the employer's `version`, and places the employer under the
    enforcement hold of §2.9 — from that point it may neither file a new exemption
    certification nor restate its headcount until the referral is withdrawn."

    Design: Difficulty/priority_pair_validation_conflict/enforcement_hold_outranks_exemption_coverage_window_temporal_check
    """
    env = _build_employer_under_an_open_referral(api)

    response = _claim_an_exemption_on_a_plan_from_2021(api, env)

    validate_error(response, ERR_ENFORCEMENT_HOLD, 409)
    employer = read_employer(api, env["employer_id"])
    assert employer["registration_status"] == "PENDING_REGISTRATION"
    assert employer["compliance_status"] == "REFERRED"
