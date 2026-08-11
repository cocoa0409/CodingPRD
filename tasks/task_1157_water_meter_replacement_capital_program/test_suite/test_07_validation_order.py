"""Validation order (PRD 2.7): earlier stage is the one reported when several
checks would fail."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, api_client, assign_contractor, book_appointment,
    create_installed_account, create_invoice, create_work_order, fc,
    get_success_data, send_and_deliver_notification,
    setup_program_wave_contractor, setup_work_order_closed, validate_error,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def _tiny_program_closed_invoice():
    """Program budget 17000; one work order CLOSED; invoice submitted with
    net 17945 frozen (> budget_available 17000)."""
    from test_helpers import create_contractor, create_program, create_wave
    prog = create_program(name="AMI-TINY", budget_total_cents=17000,
                          target_meter_count=100)
    contr = create_contractor(prog["id"])
    wave = create_wave(prog["id"])
    ctx = setup_work_order_closed(contr["id"], program=prog, wave=wave)
    inv = create_invoice(contr["id"])
    get_success_data(api_client.submit_invoice(inv["id"], fc(contr["id"])))
    return prog, contr, inv


def test_state_stage_beats_fiscal_on_invoice_approve(api):
    """PRD §2.7: "Every request passes through the same gauntlet of checks,
    and the stages are evaluated strictly in the order given here: a failure
    at an earlier stage is the one reported, even when a later stage would
    also have failed." — stage 7 is "State validity — the target resource is
    in a valid from-state for the requested transition, terminal states reject
    every transition, and complaint filing additionally requires the work
    order to be `SWAPPED` or later; otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_invoice_approve
    """
    prog, contr, inv = _tiny_program_closed_invoice()
    get_success_data(api.dispute_invoice(inv["id"], {"reason": "backup missing"}, PM))
    # DISPUTED is not a from-state for approve AND net 17945 > available 17000:
    # state validity (stage 7) precedes fiscal gates (stage 14).
    resp = api.approve_invoice(inv["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = get_success_data(api.get_invoice(inv["id"], PM))
    assert after["status"] == "DISPUTED"


def test_fiscal_arm_isolated_approving_submitted_invoice(api):
    """PRD §3.9: "Approval requires the invoice's `net_amount_cents` to be no
    greater than the program's `budget_available_cents`, with equality allowed
    — a shortfall is refused with `ERR_BUDGET_AVAILABLE_EXCEEDED`"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_invoice_approve
    """
    prog, contr, inv = _tiny_program_closed_invoice()
    # SUBMITTED (valid from-state) but net 17945 > available 17000.
    resp = api.approve_invoice(inv["id"], PM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_AVAILABLE_EXCEEDED.value)
    after = get_success_data(api.get_invoice(inv["id"], PM))
    assert after["status"] == "SUBMITTED"


def _capacity_one_program():
    return setup_program_wave_contractor(
        contractor_overrides={"crew_capacity_per_window": 1})


def test_temporal_stage_beats_capacity_on_booking(api):
    """PRD §2.7: "Temporal rules — the notice window
    (`ERR_NOTICE_WINDOW_NOT_MET`), the slot-not-in-past rule
    (`ERR_APPOINTMENT_SLOT_PAST`), and the wave window non-overlap rule
    (`ERR_WAVE_WINDOW_OVERLAP`)." come before "Capacity constraints — the crew
    window bucket (`ERR_CREW_WINDOW_FULL`), wave capacity
    (`ERR_WAVE_CAPACITY_EXCEEDED`), and the one-open-work-order-per-account
    rule (`ERR_ACCOUNT_ALREADY_IN_PROGRAM`)." under the rule that "the stages
    are evaluated strictly in the order given here: a failure at an earlier
    stage is the one reported, even when a later stage would also have
    failed."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_capacity_on_booking
    """
    prog, wave, contr = _capacity_one_program()
    # Filler: delivered 2026-04-28 -> eligible 2026-05-01; books 2026-05-04 AM.
    acctF, oldmF = create_installed_account()
    woF = create_work_order(wave["id"], acctF["id"])
    assign_contractor(woF["id"], contr["id"])
    send_and_deliver_notification(woF["id"], delivered_at="2026-04-28T10:00:00Z")
    book_appointment(woF["id"], slot_date="2026-05-04", window="AM")
    # Target: delivered 2026-05-02 -> eligible 2026-05-05; 2026-05-04 AM both
    # violates the notice window AND lands in the full bucket.
    acctT, oldmT = create_installed_account()
    woT = create_work_order(wave["id"], acctT["id"])
    assign_contractor(woT["id"], contr["id"])
    send_and_deliver_notification(woT["id"], delivered_at="2026-05-02T10:00:00Z")
    woT = get_success_data(api_client.get_work_order(woT["id"], SCHED))
    resp = api.create_appointment({
        "work_order_id": woT["id"], "slot_date": "2026-05-04", "window": "AM",
        "expected_work_order_version": woT["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_NOTICE_WINDOW_NOT_MET.value)
    after = get_success_data(api_client.get_work_order(woT["id"], SCHED))
    assert after["lifecycle_status"] == "NOTIFIED"


def test_crew_bucket_arm_isolated_when_notice_satisfied(api):
    """PRD §3.4: "its crew bucket — the count of that contractor's
    appointments in `BOOKED` or `CONFIRMED` status on the same (`slot_date`,
    `window`) — must be strictly below `crew_capacity_per_window`
    (`ERR_CREW_WINDOW_FULL`)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_capacity_on_booking
    """
    prog, wave, contr = _capacity_one_program()
    acctF, oldmF = create_installed_account()
    woF = create_work_order(wave["id"], acctF["id"])
    assign_contractor(woF["id"], contr["id"])
    send_and_deliver_notification(woF["id"], delivered_at="2026-04-28T10:00:00Z")
    book_appointment(woF["id"], slot_date="2026-05-06", window="AM")
    # Target also delivered 2026-04-28: notice satisfied for 2026-05-06, so
    # only the crew bucket can fail.
    acctT, oldmT = create_installed_account()
    woT = create_work_order(wave["id"], acctT["id"])
    assign_contractor(woT["id"], contr["id"])
    send_and_deliver_notification(woT["id"], delivered_at="2026-04-28T10:00:00Z")
    woT = get_success_data(api_client.get_work_order(woT["id"], SCHED))
    resp = api.create_appointment({
        "work_order_id": woT["id"], "slot_date": "2026-05-06", "window": "AM",
        "expected_work_order_version": woT["version"]}, SCHED)
    validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_FULL.value)
    after = get_success_data(api_client.get_work_order(woT["id"], SCHED))
    assert after["lifecycle_status"] == "NOTIFIED"
