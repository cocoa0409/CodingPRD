"""State-machine corner cases: invalid transitions, terminal lockdown, sweep
side effects, expiry preconditions, and the void compensation.
PRD §3.6, §3.11, §3.12, §3.8, §3.13.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_completed_visit, setup_invoiced_visit, setup_referral, setup_active_member,
    create_slot, book_visit, make_provider_headers, make_member_headers,
    message_thread_payload, set_clock, ApiErrorId, ADMIN,
)


def test_cancel_completed_visit_returns_invalid_state(api):
    """PRD §3.6: "A `Member` may cancel a visit that is still `BOOKED`, moving it to
    `CANCELLED`; cancellation decrements the slot's `booked_count` for the visit's
    `slot_id` and recomputes that slot's `slot_state`."
    PRD §3.6: "Any clinical transition requested from a state in which it is not
    defined — for instance checking in a visit that is not `BOOKED` — is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_visit_from_completed_returns_invalid_state
    """
    ctx = setup_completed_visit([{"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000}])
    member_h = make_member_headers(ctx["member"]["id"])
    res = api_client.cancel_visit(ctx["visit"]["id"], member_h)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    visit = validate_success(api_client.get_visit(ctx["visit"]["id"], ADMIN), 200)
    assert visit["clinical_status"] == "COMPLETED"


def test_authorize_denied_referral_returns_invalid_state(api):
    """PRD §3.11: "A provider may instead deny a `REQUESTED` referral, moving it
    directly to the terminal `DENIED` state."
    PRD §3.11: "Any referral transition requested from a state in which it is not
    defined is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/referral_deny_then_authorize_returns_invalid_state
    """
    ctx = setup_referral(status="DENIED")
    prov_h = make_provider_headers(ctx["provider"]["id"])
    res = api_client.authorize_referral(ctx["referral"]["id"], prov_h)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
    ref = validate_success(api_client.get_referral(ctx["referral"]["id"], prov_h), 200)
    assert ref["referral_status"] == "DENIED"


def test_authorized_referral_expires_via_sweep(api):
    """PRD §3.11: "An `AUTHORIZED` referral that is never sent is moved to the
    terminal `EXPIRED` state by the periodic sweep once the clock reaches or passes
    its `expires_at`."

    Design: Corner/state_machines/referral_authorized_expires_via_sweep
    """
    # Authorized at 2026-06-01 -> expires 2026-07-01; sweep run at 2026-07-02.
    ctx = setup_referral(status="AUTHORIZED")
    set_clock("2026-07-02T00:00:00Z")
    get_success_data(api_client.run_suspension_sweep(ADMIN))
    ref = validate_success(api_client.get_referral(
        ctx["referral"]["id"], make_provider_headers(ctx["provider"]["id"])), 200)
    assert ref["referral_status"] == "EXPIRED"


def test_send_referral_at_expiry_returns_referral_expired(api):
    """PRD §3.11: "A provider sends an `AUTHORIZED` referral, moving it to the
    terminal `SENT` state, provided the referral is currently `AUTHORIZED` and the
    clock is still before its `expires_at`. Sending a referral at or after
    `expires_at` is rejected with `ERR_REFERRAL_EXPIRED`."

    Design: Corner/state_machines/referral_send_after_expiry_returns_referral_expired
    """
    # Authorized at 2026-06-01 -> expires 2026-07-01; attempt send at exactly expiry.
    ctx = setup_referral(status="AUTHORIZED")
    set_clock("2026-07-01T00:00:00Z")
    res = api_client.send_referral(
        ctx["referral"]["id"], make_provider_headers(ctx["provider"]["id"]))
    validate_error(res, ApiErrorId.ERR_REFERRAL_EXPIRED.value)


def test_open_thread_escalates_via_sla_breach(api):
    """PRD §3.12: "When an `OPEN` thread's `response_deadline` has been reached or
    passed without a reply, the periodic sweep moves it from `OPEN` to
    `ESCALATED`."

    Design: Corner/state_machines/message_thread_open_to_escalated_via_sla_breach
    """
    # Thread opened at 09:00Z (ROUTINE, deadline +24h = next day 09:00Z); sweep at 10:00Z next day.
    ctx = setup_active_member(clock="2026-06-01T09:00:00Z")
    member_h = make_member_headers(ctx["member"]["id"])
    thread = get_success_data(api_client.create_message_thread(
        ctx["member"]["id"], message_thread_payload("knee pain"), member_h))
    assert thread["priority"] == "ROUTINE"
    set_clock("2026-06-02T10:00:00Z")
    get_success_data(api_client.run_suspension_sweep(ADMIN))
    refreshed = validate_success(api_client.get_message_thread(thread["id"], member_h), 200)
    assert refreshed["thread_status"] == "ESCALATED"


def test_void_invoice_writes_off_linked_visit(api):
    """PRD §3.8: "A `Provider` may void an `ISSUED` invoice, advancing its
    `invoice_status` to `VOID`; as a compensating cross-entity effect, the linked
    visit's `billing_status` is set to `WRITTEN_OFF`, so the visit is no longer
    treated as `INVOICED`."

    Design: Corner/state_machines/invoice_void_compensates_visit_to_written_off
    """
    ctx = setup_invoiced_visit(
        [{"service_code": "XRAY", "units": 1, "unit_charge_cents": 9000}],
        member_overrides={"has_insurance": False})
    prov_h = make_provider_headers(ctx["provider"]["id"])
    invoice = validate_success(api_client.void_invoice(ctx["invoice"]["id"], prov_h), 200)
    assert invoice["invoice_status"] == "VOID"
    visit = validate_success(api_client.get_visit(ctx["visit"]["id"], ADMIN), 200)
    assert visit["billing_status"] == "WRITTEN_OFF"
