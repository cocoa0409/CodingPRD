"""Corner section: state_machines (PRD §3.3, §3.4, §3.8).

Initial state, invalid transitions, terminal lockdown, idempotency rejection,
sequence gate, and partial-disposition non-cascade.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_purchase_period_payload,
    create_disposition_payload,
    create_plan_payload,
    create_offering_payload,
    setup_enrolled_participant,
    setup_settled_purchase,
    make_participant_headers,
)


def test_enrollment_initial_state_is_enrolled(api):
    """PRD §3.3: "A new enrollment opens in ENROLLED status with an
    accumulated_contribution_cents of 0 and a refunded_contribution_cents of 0."
    PRD §2.4: "an integer version that begins at 1".

    Design: Corner/state_machines/enrollment_initial_state_is_enrolled
    """
    _, _, _, enrollment = setup_enrolled_participant(rate_pct=10)
    assert enrollment["status"] == "ENROLLED", enrollment
    assert enrollment["version"] == 1, enrollment


def test_resume_from_enrolled_returns_invalid_state(api):
    """PRD §3.3: "Resuming moves it back from SUSPENDED to ENROLLED, permitted only
    when the enrollment is SUSPENDED ... Any transition from a state in which it is not
    defined is rejected with ERR_INVALID_STATE (HTTP 409)."

    Resuming an ENROLLED (not SUSPENDED) enrollment => ERR_INVALID_STATE.

    Design: Corner/state_machines/resume_from_enrolled_returns_invalid_state
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    resp = api.resume_enrollment(
        enrollment["id"], make_participant_headers(participant["id"])
    )
    validate_error(resp, "ERR_INVALID_STATE")


def test_terminal_withdrawn_enrollment_locks_down(api):
    """PRD §3.3: "An employee may also withdraw entirely from either ENROLLED or
    SUSPENDED, advancing the enrollment to WITHDRAWN ... Any transition from a state in
    which it is not defined is rejected with ERR_INVALID_STATE (HTTP 409)."

    A second withdraw on a WITHDRAWN (terminal) enrollment => ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_withdrawn_enrollment_locks_down
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.withdraw_enrollment(enrollment["id"], ph))
    resp = api.withdraw_enrollment(enrollment["id"], ph)
    validate_error(resp, "ERR_INVALID_STATE")


def test_suspend_then_suspend_idempotency_rejected(api):
    """PRD §3.3: "Suspending an enrollment moves it from ENROLLED to SUSPENDED, which
    is permitted only when the enrollment is ENROLLED and its parent offering is not
    CLOSED ... Any transition from a state in which it is not defined is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    A second suspend on an already-SUSPENDED enrollment => ERR_INVALID_STATE.

    Design: Corner/state_machines/suspend_then_suspend_idempotency_rejected
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.suspend_enrollment(enrollment["id"], ph))
    resp = api.suspend_enrollment(enrollment["id"], ph)
    validate_error(resp, "ERR_INVALID_STATE")


def test_sequence_gate_open_second_batch_before_first_terminal(api, admin_headers):
    """PRD §3.4: "every sibling batch with a smaller sequence_index has already reached
    a terminal state of PURCHASED or CANCELLED. This last condition is the sequential
    gate: lower-indexed batches must finish before a higher-indexed one opens, and an
    attempt to jump the queue is rejected with ERR_SEQUENCE_NOT_READY (HTTP 409)."

    Design: Corner/state_machines/sequence_gate_open_second_batch_before_first_terminal
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    offering = get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    get_success_data(api.close_enrollment(offering["id"], admin_headers))
    get_success_data(
        api.create_purchase_period(
            offering["id"],
            create_purchase_period_payload(
                sequence_index=1, purchase_date="2024-04-30T00:00:00.000Z",
                purchase_date_fmv_cents=1200,
            ),
            admin_headers,
        )
    )
    pp2 = get_success_data(
        api.create_purchase_period(
            offering["id"],
            create_purchase_period_payload(
                sequence_index=2, purchase_date="2024-08-31T00:00:00.000Z",
                purchase_date_fmv_cents=1300,
            ),
            admin_headers,
        )
    )
    resp = api.open_purchase_period(pp2["id"], admin_headers)
    validate_error(resp, "ERR_SEQUENCE_NOT_READY")


def test_partial_disposition_keeps_sharelot_open(api):
    """PRD §3.8: "recording it decrements the lot's shares_remaining by the shares
    sold; if that brings shares_remaining to exactly 0, the lot transitions from OPEN
    to FULLY_DISPOSED."

    Selling fewer shares than remain leaves the lot OPEN with shares_remaining reduced
    by exactly the shares sold (computed from the real lot size).

    Design: Corner/state_machines/partial_disposition_keeps_sharelot_open
    """
    ctx = setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=10,
    )
    lot = ctx["share_lot"]
    assert lot["shares_remaining"] > 50, lot  # precondition: a partial sale is possible
    ph = make_participant_headers(ctx["participant"]["id"])
    get_success_data(
        api.create_disposition(
            create_disposition_payload(
                lot["id"], ctx["participant"]["id"],
                sale_date="2024-06-30T00:00:00.000Z", shares_sold=50,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    refreshed = validate_success(api.get_share_lot(lot["id"], ph))
    assert refreshed["shares_remaining"] == lot["shares_remaining"] - 50, refreshed
    assert refreshed["status"] == "OPEN", refreshed
