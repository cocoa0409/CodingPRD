"""Breadth tests for state-machine initial states, cascades, terminal lockdown,
invalid transitions, preconditions, and revert edges.

Queue B (Corner) translations for the `state_machines` section.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    create_active_carrier,
    create_product,
    create_producer,
    create_account,
    create_quoted_policy,
    setup_compliant_writer,
    setup_active_policy_no_split,
    setup_renewal_task_offered,
    open_renewal_task,
    open_trust_account_with_balance,
    open_statement,
    finalize_statement,
    set_clock,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


def test_carrier_initial_state_is_prospective(api):
    """PRD §3.1: "A newly created carrier begins in the `PROSPECTIVE` state."

    Design: Corner/state_machines/carrier_initial_state_is_prospective
    """
    resp = api.create_carrier(factories.create_carrier_payload(name="Init C"), ADMIN())
    data = validate_success(resp, 201)
    assert data["status"] == "PROSPECTIVE", data


def test_carrier_terminate_cascades_appointments(api):
    """PRD §3.1: "When a carrier is terminated, the effect cascades downward: every
    appointment naming that carrier whose status is `REQUESTED`, `APPROVED`, or `ACTIVE` is
    itself transitioned to `TERMINATED`, and each such appointment's `version` increments."

    Design: Corner/state_machines/carrier_terminate_cascades_appointments
    """
    carrier = create_active_carrier()
    producer = create_producer()
    appt = get_success_data(
        api.create_appointment(
            factories.create_appointment_payload(carrier["id"], producer["id"], state_code="CA"),
            ADMIN(),
        )
    )
    get_success_data(
        api.approve_appointment(appt["id"], {"expected_appointment_version": appt["version"]}, ADMIN())
    )
    term = validate_success(
        api.terminate_carrier(carrier["id"], {"expected_carrier_version": carrier["version"]}, ADMIN()),
        200,
    )
    assert term["status"] == "TERMINATED", term
    appt_after = get_success_data(api.get_appointment(appt["id"], ADMIN()))
    assert appt_after["status"] == "TERMINATED", appt_after


def test_appointment_terminal_lockdown(api):
    """PRD §2.10: "then — for state-transition endpoints — whether the target is in a state
    from which the transition is legal (`ERR_INVALID_STATE`, HTTP 409)".
    A TERMINATED appointment is terminal, so approving it again is not a legal transition.

    Design: Corner/state_machines/appointment_terminal_lockdown
    """
    carrier = create_active_carrier()
    producer = create_producer()
    appt = get_success_data(
        api.create_appointment(
            factories.create_appointment_payload(carrier["id"], producer["id"], state_code="CA"),
            ADMIN(),
        )
    )
    terminated = get_success_data(
        api.terminate_appointment(appt["id"], {"expected_appointment_version": appt["version"]}, ADMIN())
    )
    resp = api.approve_appointment(
        appt["id"], {"expected_appointment_version": terminated["version"]}, ADMIN()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_policy_activate_from_quoted_invalid(api):
    """PRD §3.4: "Once bound, a policy is brought **active** by an `AccountManager`,
    transitioning `BOUND → ACTIVE`."
    PRD §2.10: "whether the target is in a state from which the transition is legal
    (`ERR_INVALID_STATE`, HTTP 409)". A QUOTED policy is not BOUND, so activation is illegal.

    Design: Corner/state_machines/policy_activate_from_quoted_invalid
    """
    ctx = setup_compliant_writer()
    policy = create_quoted_policy(
        ctx,
        annual_premium_cents=100000,
        effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
    )
    resp = api.activate_policy(policy["id"], {"expected_policy_version": policy["version"]}, MANAGER())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api.get_policy(policy["id"], MANAGER()))
    assert refreshed["status"] == "QUOTED", refreshed


def test_reinstate_underwriting_cancellation_rejected(api):
    """PRD §3.7: "reinstatement is allowed only while the current moment is strictly before
    the policy's `expiration_date` and only when the `cancellation_reason` was not
    `UNDERWRITING` (underwriting cancellations are never reinstatable). A request violating
    either condition is rejected with `ERR_REINSTATE_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/state_machines/reinstate_underwriting_cancellation_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    open_trust_account_with_balance(5_000_000, state_code="CA")
    s = setup_active_policy_no_split(
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        }
    )
    policy = s["policy"]
    cancelled = get_success_data(
        api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2026-06-01T00:00:00Z",
                "cancellation_reason": "UNDERWRITING",
            },
            MANAGER(),
        )
    )
    resp = api.reinstate_policy(
        cancelled["id"], {"expected_policy_version": cancelled["version"]}, MANAGER()
    )
    validate_error(resp, ApiErrorId.ERR_REINSTATE_NOT_ALLOWED.value)
    refreshed = get_success_data(api.get_policy(policy["id"], MANAGER()))
    assert refreshed["status"] == "CANCELLED", refreshed


def test_nonpayment_cancel_forces_pro_rata(api):
    """PRD §3.6: "The applicable basis is `PRO_RATA` whenever the cancellation reason is
    `NON_PAYMENT` — a non-payment cancellation always refunds pro-rata regardless of the
    product's configured basis".

    Design: Corner/state_machines/nonpayment_cancel_forces_pro_rata
    """
    set_clock("2026-07-01T00:00:00Z")
    open_trust_account_with_balance(5_000_000, state_code="CA")
    s = setup_active_policy_no_split(
        ctx=setup_compliant_writer(product_overrides={"cancellation_basis": "SHORT_RATE"}),
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        },
    )
    policy = s["policy"]
    data = validate_success(
        api.cancel_policy(
            policy["id"],
            {
                "expected_policy_version": policy["version"],
                "cancellation_date": "2026-07-01T00:00:00Z",
                "cancellation_reason": "NON_PAYMENT",
            },
            MANAGER(),
        ),
        200,
    )
    # NON_PAYMENT forces PRO_RATA: full unearned 604932 (not the short-rate 544438).
    assert data["return_premium_cents"] == 604932, data
    assert data["earned_premium_cents"] == 595068, data


def test_nonterminal_renewal_task_duplicate_rejected(api):
    """PRD §3.8: "at most one non-terminal renewal task — one whose stage is neither
    `COMPLETED` nor `LOST` — may exist for a given policy at a time; a second is rejected with
    `ERR_DUPLICATE_RENEWAL_TASK` (HTTP 409)."

    Design: Corner/state_machines/nonterminal_renewal_task_duplicate_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    s = setup_active_policy_no_split(
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        }
    )
    set_clock("2026-11-15T00:00:00Z")
    open_renewal_task(s["policy"]["id"], "2027-01-01T00:00:00Z")
    resp = api.create_renewal_task(
        {"policy_id": s["policy"]["id"], "target_effective_date": "2027-01-01T00:00:00Z"},
        MANAGER(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RENEWAL_TASK.value)


def test_renewal_task_advance_from_terminal_lost_rejected(api):
    """PRD §3.8: "A task may also be marked **lost** — moving to the terminal `LOST` stage —
    from either `REVIEW` or `OFFERED`."
    PRD §2.10: "whether the target is in a state from which the transition is legal
    (`ERR_INVALID_STATE`, HTTP 409)". A LOST task is terminal, so advancing it is illegal.

    Design: Corner/state_machines/renewal_task_idempotent_advance_from_terminal
    """
    set_clock("2026-01-01T00:00:00Z")
    s = setup_active_policy_no_split(
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        }
    )
    set_clock("2026-11-15T00:00:00Z")
    task = open_renewal_task(s["policy"]["id"], "2027-01-01T00:00:00Z")
    advanced = get_success_data(
        api.advance_renewal_task(task["id"], {"expected_renewaltask_version": task["version"]}, MANAGER())
    )  # IDENTIFIED -> REVIEW
    lost = get_success_data(
        api.lose_renewal_task(task["id"], {"expected_renewaltask_version": advanced["version"]}, MANAGER())
    )
    resp = api.advance_renewal_task(
        task["id"], {"expected_renewaltask_version": lost["version"]}, MANAGER()
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = get_success_data(api.get_renewal_task(task["id"], MANAGER()))
    assert refreshed["stage"] == "LOST", refreshed


def test_statement_reopen_from_finalized(api):
    """PRD §3.10: "A finalized but unpaid statement may be **reopened** by a
    `TrustAccountant`, transitioning `FINALIZED → OPEN` so an accountant can correct a
    premature finalize".

    Design: Corner/state_machines/statement_reopen_from_finalized
    """
    set_clock("2026-03-01T00:00:00Z")
    producer = create_producer()
    stmt = open_statement(producer["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    finalized = finalize_statement(stmt["id"], stmt["version"])
    resp = api.reopen_statement(
        stmt["id"], {"expected_commissionstatement_version": finalized["version"]}, TRUST()
    )
    data = validate_success(resp, 200)
    assert data["status"] == "OPEN", data
