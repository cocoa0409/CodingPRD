"""Difficulty queue A: compensating invariants — confirmed minutes conserved
across confirm/cancel, and order fee conserved across revision-accept +
equal waiver (PRD 3.2, 3.7, 3.9)."""
from test_helpers import (
    accept_revision,
    confirm_appointment,
    create_appointment,
    create_fee_adjustment_payload,
    get_order,
    get_scorecard,
    open_revision_on_delivered,
    setup_assigned_order,
    setup_delivered_order,
    validate_success,
)
from test_helpers import ADMIN


def _setup_confirmed_90_minute_appointment():
    """Inspection order ASSIGNED to A plus one CONFIRMED 90-minute window."""
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 14})
    baseline = get_scorecard(ctx["appraiser"]["id"])
    assert baseline["confirmed_minutes"] == 0
    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:30:00Z",
    )
    return ctx, appointment


def test_confirm_moves_confirmed_minutes_to_window_length(api):
    """PRD 3.2: "The scorecard view also carries `confirmed_minutes` — the
    summed length in minutes, from `window_start` to `window_end`, across the
    appraiser's `CONFIRMED` appointments".

    Design: Difficulty/compensating_invariant/appointment_confirm_then_cancel_preserves_committed_minutes
    """
    ctx, appointment = _setup_confirmed_90_minute_appointment()
    confirm_appointment(appointment["id"], ctx["appraiser"]["id"])

    scorecard = get_scorecard(ctx["appraiser"]["id"])
    assert scorecard["confirmed_minutes"] == 90, "one 90-minute CONFIRMED window"


def test_cancel_restores_confirmed_minutes_to_zero(api):
    """PRD 3.2: "`confirmed_minutes` — the summed length in minutes, from
    `window_start` to `window_end`, across the appraiser's `CONFIRMED`
    appointments".
    PRD 3.4: "An appointment in `PROPOSED` or `CONFIRMED` may also be
    cancelled outright, landing in the terminal `CANCELLED` state".

    Design: Difficulty/compensating_invariant/appointment_confirm_then_cancel_preserves_committed_minutes
    """
    ctx, appointment = _setup_confirmed_90_minute_appointment()
    confirm_appointment(appointment["id"], ctx["appraiser"]["id"])
    assert get_scorecard(ctx["appraiser"]["id"])["confirmed_minutes"] == 90

    validate_success(api.cancel_appointment(appointment["id"], ADMIN), 200)
    # the CANCELLED appointment no longer counts -> forward + compensating
    # actions conserve the committed-minutes invariant
    assert get_scorecard(ctx["appraiser"]["id"])["confirmed_minutes"] == 0


def _setup_revision_accepted():
    """Desktop STANDARD order delivered 2026-08-02 (fee_current 45000);
    revision accepted (schedule revision fee 15000)."""
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")
    baseline = get_order(ctx["order"]["id"])["fee_current_cents"]
    assert baseline == 45000
    rr = open_revision_on_delivered(ctx, detail="Correct basement note")
    accept_revision(rr["id"])
    return ctx


def test_revision_accept_adds_fee_to_fee_current(api):
    """PRD 3.7: "The revision fee is read from the client's fee schedule for
    the order's tier effective as-of the order's `first_delivered_at`; when no
    window covers that instant, the retail fallback of 15000 cents applies.
    The charged amount is stored in `revision_fee_charged_cents` and added
    both to the order's `fee_current_cents` and to its running
    `revision_fees_collected_cents`."

    Design: Difficulty/compensating_invariant/revision_fee_accept_then_equal_waiver_preserves_fee_current
    """
    ctx = _setup_revision_accepted()
    order = get_order(ctx["order"]["id"])
    assert order["fee_current_cents"] == 60000
    assert order["revision_fees_collected_cents"] == 15000


def test_equal_waiver_restores_fee_current_and_preserves_ledger(api):
    """PRD 3.9: "A `WAIVER` subtracts the amount from `fee_current_cents` and
    accumulates it into `waived_total_cents`".

    Design: Difficulty/compensating_invariant/revision_fee_accept_then_equal_waiver_preserves_fee_current
    """
    ctx = _setup_revision_accepted()
    adjusted = validate_success(
        api.create_fee_adjustment(
            ctx["order"]["id"],
            create_fee_adjustment_payload(
                "WAIVER", 15000, reason="Goodwill: revision fee waived"
            ),
            ADMIN,
        ),
        200,
    )
    assert adjusted["fee_current_cents"] == 45000, "back to the pre-accept baseline"
    assert adjusted["waived_total_cents"] == 15000
    assert adjusted["revision_fees_collected_cents"] == 15000, "audit trail preserved"
