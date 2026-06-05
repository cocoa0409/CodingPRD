"""State-machine corner cases: invalid transitions, initial state, terminal
lockdown, receipt verification preconditions and dispute path, OOP step ordering.

Queue B (Corner) — section state_machines.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_base_env,
    create_pending_trip,
    create_approved_trip,
    create_report,
    add_cdw_line,
    add_approval_step,
    upload_receipt,
)


def test_cancel_approved_trip_invalid_state(api):
    """PRD §3.2: "A Traveler may also cancel a trip while it is still PENDING, moving
    it to the terminal CANCELLED state."
    PRD §2.6: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_trip_from_approved_invalid_state
    """
    env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
    # in-policy 4-night trip auto-approves to APPROVED.
    trip = create_approved_trip(env, budget_total_cents=200000,
                                start_date="2026-06-01", end_date="2026-06-05")
    assert trip["status"] == "APPROVED"
    resp = api.cancel_trip_request(trip["id"], env["traveler_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_trip_starts_pending(api):
    """PRD §3.2: "At creation the trip is placed in PENDING, its policy_id is pinned to
    whichever policy is currently ACTIVE"
    PRD §2.4: "The version starts at its initial value on creation"

    Design: Corner/state_machines/trip_request_initial_state_pending
    """
    env = setup_base_env()
    trip = create_pending_trip(env, budget_total_cents=50000)
    assert trip["status"] == "PENDING"
    assert trip["version"] == 1


def test_denied_trip_second_decision_locked(api):
    """PRD §3.2: "An approve decision moves the trip from PENDING_OOP_APPROVAL to
    APPROVED, and a deny decision moves it to the terminal DENIED state."
    PRD §2.6: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/terminal_denied_trip_decision_locked
    """
    env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
    trip = create_pending_trip(env, budget_total_cents=300000,
                               start_date="2026-06-01", end_date="2026-06-05")
    get_success_data(api.submit_trip_request(trip["id"], env["traveler_headers"]))
    denied = get_success_data(
        api.decide_trip_request(trip["id"], {"decision": "DENY"}, env["approver_headers"])
    )
    assert denied["status"] == "DENIED"
    resp = api.decide_trip_request(trip["id"], {"decision": "APPROVE"}, env["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_receipt_verify_amount_mismatch_rejected(api):
    """PRD §3.7: "verifying moves it to VERIFIED, but only when its ocr_amount_cents
    equals the claimed_amount_cents of the linked expense line — a mismatch is rejected
    with ERR_RECEIPT_AMOUNT_MISMATCH."

    Design: Corner/state_machines/receipt_verify_amount_mismatch
    """
    env = setup_base_env(cdw_daily_cap_cents=3000)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Receipt Match Rpt")
    line = add_cdw_line(env, report, claimed_amount_cents=10000, rental_days=5)
    receipt = upload_receipt(env, line)
    get_success_data(
        api.ocr_receipt(receipt["id"], {"ocr_amount_cents": 9999, "ocr_merchant": "Hertz"},
                        env["admin_headers"])
    )
    resp = api.verify_receipt(receipt["id"], env["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_RECEIPT_AMOUNT_MISMATCH.value)


def test_receipt_dispute_then_verify_when_amount_matches(api):
    """PRD §3.7: "Marking a receipt disputed moves it from OCR_PROCESSED to DISPUTED,
    and a disputed receipt can later be re-verified, again moving to VERIFIED only when
    ocr_amount_cents equals the linked line's claimed_amount_cents, with the same
    ERR_RECEIPT_AMOUNT_MISMATCH guarding the re-verification."

    Design: Corner/state_machines/receipt_dispute_then_verify_path
    """
    env = setup_base_env(cdw_daily_cap_cents=3000)
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Dispute Rpt")
    line = add_cdw_line(env, report, claimed_amount_cents=10000, rental_days=5)
    receipt = upload_receipt(env, line)
    get_success_data(
        api.ocr_receipt(receipt["id"], {"ocr_amount_cents": 10000, "ocr_merchant": "Hertz"},
                        env["admin_headers"])
    )
    get_success_data(api.dispute_receipt(receipt["id"], env["admin_headers"]))
    verified = validate_success(
        api.verify_receipt(receipt["id"], env["admin_headers"]), expected_status=200
    )
    assert verified["status"] == "VERIFIED"


def test_oop_step_out_of_order_rejected(api):
    """PRD §3.9: "Before a step may be decided at all, every step for the same report
    with a smaller step_order must already have a decision of APPROVED; deciding a step
    while an earlier one is still outstanding is rejected with ERR_OOP_STEP_OUT_OF_ORDER."

    Design: Corner/state_machines/oop_step_out_of_order_rejected
    """
    env = setup_base_env()
    trip = create_approved_trip(env, budget_total_cents=100000)
    report = create_report(env, trip, title="Chain Rpt")
    add_approval_step(env, report, env["approver"]["id"], step_order=1)
    step2 = add_approval_step(env, report, env["approver"]["id"], step_order=2)
    resp = api.decide_approval_step(step2["id"], {"decision": "APPROVE"}, env["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_OOP_STEP_OUT_OF_ORDER.value)
