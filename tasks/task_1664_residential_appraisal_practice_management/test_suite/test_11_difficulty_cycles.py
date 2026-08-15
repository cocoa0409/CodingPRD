"""Difficulty queue A: cyclic state machines — the report revision loop and
the appointment reschedule loop (PRD 3.4, 3.6, 3.7)."""
from test_helpers import (
    accept_revision,
    confirm_appointment,
    create_appointment,
    get_order,
    open_revision_on_delivered,
    qc_pass,
    redeliver_revised_report,
    relock_comps,
    set_clock,
    setup_assigned_order,
    setup_delivered_order,
    submit_for_qc,
    validate_success,
)
from test_helpers import ADMIN


def _setup_revision_cycle():
    """Desktop STANDARD order delivered 2026-08-04 (fee 45000, schedule
    revision fee 15000); a CORRECTION revision opened and accepted."""
    ctx = setup_delivered_order(delivery_clock="2026-08-04T00:00:00Z")
    rr = open_revision_on_delivered(ctx, detail="Fix square footage note")
    rr = accept_revision(rr["id"])
    ctx["revision"] = rr
    return ctx


def test_revision_accept_reopens_report_and_order(api):
    """PRD 3.7: "The order moves from `DELIVERED` to `IN_REVISION`, the report
    moves from `DELIVERED` to `UNDER_REVISION` with `revision_round`
    incremented by one, every `LOCKED` comparable on the order returns to
    `VERIFIED`, and a `REVISION_CORRESPONDENCE` workfile record is filed."
    PRD 3.7: "The charged amount is stored in `revision_fee_charged_cents`
    and added both to the order's `fee_current_cents` and to its running
    `revision_fees_collected_cents`."

    Design: Difficulty/non_linear_state_machine/report_delivered_under_revision_redelivered_cycle
    """
    ctx = _setup_revision_cycle()

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "IN_REVISION"
    assert order["fee_current_cents"] == 60000, "45000 + 15000 revision fee"
    assert order["revision_fees_collected_cents"] == 15000

    report = validate_success(api.get_report(ctx["report"]["id"], ADMIN), 200)
    assert report["status"] == "UNDER_REVISION"
    assert report["revision_round"] == 1

    rr = validate_success(
        api.get_revision_request(ctx["revision"]["id"], ADMIN), 200
    )
    assert rr["status"] == "ACCEPTED"
    assert rr["revision_fee_charged_cents"] == 15000

    comps = validate_success(
        api.list_comparables(ADMIN, params={"order_id": ctx["order"]["id"]}), 200
    )
    assert {c["status"] for c in comps} == {"VERIFIED"}, "locks released by the accept"


def test_revision_cycle_resolves_on_second_delivery(api):
    """PRD 3.7: "An accepted request is resolved automatically when the
    revised report is delivered (§3.6), moving from `ACCEPTED` to
    `RESOLVED`."
    PRD 3.6: "Delivery moves the order to `DELIVERED` — from `QC_REVIEW` on
    the first pass, or from `IN_REVISION` on a revised report — stamps
    `first_delivered_at` when it was previously null and never again".

    Design: Difficulty/non_linear_state_machine/report_delivered_under_revision_redelivered_cycle
    """
    ctx = _setup_revision_cycle()
    redeliver_revised_report(ctx, delivery_clock="2026-08-06T00:00:00Z")

    report = validate_success(api.get_report(ctx["report"]["id"], ADMIN), 200)
    assert report["status"] == "DELIVERED"
    assert report["revision_round"] == 1

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "DELIVERED"
    assert order["first_delivered_at"] == "2026-08-04T00:00:00Z", "set once, never again"

    rr = validate_success(
        api.get_revision_request(ctx["revision"]["id"], ADMIN), 200
    )
    assert rr["status"] == "RESOLVED"


def _setup_appointment_loop():
    """Inspection-required STANDARD order ASSIGNED to a certified appraiser;
    one PROPOSED appointment 2026-08-02 09:00-10:00."""
    ctx = setup_assigned_order(desktop=False, order_overrides={"requested_turn_days": 7})
    appointment = create_appointment(
        ctx["order"]["id"],
        ctx["appraiser"]["id"],
        "2026-08-02T09:00:00Z",
        "2026-08-02T10:00:00Z",
    )
    ctx["appointment"] = appointment
    return ctx


def test_appointment_confirm_then_reschedule_returns_to_proposed(api):
    """PRD 3.4: "A confirmed appointment can be rescheduled, returning it to
    `PROPOSED` with a replacement `window_start` and `window_end`; the new
    start must again be strictly after the logical clock (`ERR_WINDOW_IN_PAST`)
    and the end strictly after the start (`ERR_VALIDATION`), and the order
    remains `INSPECTION_SCHEDULED` throughout."
    PRD 3.4: "The first confirmation for an order automatically advances the
    order from `ASSIGNED` to `INSPECTION_SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/appointment_confirm_reschedule_confirm_cycle
    """
    ctx = _setup_appointment_loop()
    confirmed = confirm_appointment(ctx["appointment"]["id"], ctx["appraiser"]["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert get_order(ctx["order"]["id"])["status"] == "INSPECTION_SCHEDULED"

    rescheduled = validate_success(
        api.reschedule_appointment(
            ctx["appointment"]["id"],
            {
                "window_start": "2026-08-03T14:00:00Z",
                "window_end": "2026-08-03T15:00:00Z",
            },
            ctx["appraiser_headers"],
        ),
        200,
    )
    assert rescheduled["status"] == "PROPOSED"
    assert rescheduled["window_start"] == "2026-08-03T14:00:00Z"
    assert get_order(ctx["order"]["id"])["status"] == "INSPECTION_SCHEDULED"


def test_appointment_second_confirm_after_reschedule(api):
    """PRD 3.4: "Confirmation moves a `PROPOSED` appointment to `CONFIRMED`
    and can be performed by the appraiser or a `FirmAdmin`."
    PRD 3.4: "the order remains `INSPECTION_SCHEDULED` throughout."

    Design: Difficulty/non_linear_state_machine/appointment_confirm_reschedule_confirm_cycle
    """
    ctx = _setup_appointment_loop()
    confirm_appointment(ctx["appointment"]["id"], ctx["appraiser"]["id"])
    validate_success(
        api.reschedule_appointment(
            ctx["appointment"]["id"],
            {
                "window_start": "2026-08-03T14:00:00Z",
                "window_end": "2026-08-03T15:00:00Z",
            },
            ctx["appraiser_headers"],
        ),
        200,
    )

    reconfirmed = validate_success(
        api.confirm_appointment(ctx["appointment"]["id"], ctx["appraiser_headers"]), 200
    )
    assert reconfirmed["status"] == "CONFIRMED"
    assert reconfirmed["window_start"] == "2026-08-03T14:00:00Z"

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "INSPECTION_SCHEDULED", "advanced exactly once"
