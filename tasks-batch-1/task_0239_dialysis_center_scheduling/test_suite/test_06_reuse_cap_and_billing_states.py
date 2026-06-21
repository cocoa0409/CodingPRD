"""Dialyzer reuse cap boundary at completion, plus billing/transport/station
state-error checks from the errors section.

Difficulty queue (A): boundary_precision_check (dialyzer reuse cap).
Corner queue (B): errors section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_bookable_scenario, setup_clinic_inventory, setup_reuse_count_at,
    book_session, book_and_complete,
    create_patient_payload, create_order_payload, create_session_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
NEPH = TEST_USERS["nephrologist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]
BILL = TEST_USERS["billing_clerk_headers"]


# ─── boundary_precision_check / dialyzer_reuse_cap ────────────────────────
def test_complete_at_reuse_count_below_limit_succeeds(api):
    """PRD §3.6: "For a `HEMODIALYSIS` or `HEMODIAFILTRATION` session, completion
    is permitted only when the machine's `dialyzer_reuse_count` is strictly less
    than the clinic's `dialyzer_reuse_limit`, because completion increments that
    counter and would otherwise push it to or past the cap"
    PRD §3.6: "if the order's `modality` is `HEMODIALYSIS` or `HEMODIAFILTRATION`,
    the machine's `dialyzer_reuse_count` is increased by 1."

    Design: Difficulty/boundary_precision_check/dialyzer_reuse_cap_at_limit_minus_one_passes_at_limit_fails
    """
    # limit 2; first completion leaves count at 1 (1 < 2 succeeded)
    bundle = setup_reuse_count_at(target_count=1, dialyzer_reuse_limit=2)
    machine = validate_success(api.get_machine(bundle["machine"]["id"], ADMIN), 200)
    assert machine["dialyzer_reuse_count"] == 1


def test_complete_at_reuse_count_equal_limit_rejected(api):
    """PRD §3.6: "a completion that would breach the cap is rejected with
    `ERR_DIALYZER_REUSE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/dialyzer_reuse_cap_at_limit_minus_one_passes_at_limit_fails
    """
    # limit 2; drive count to 2, leave a CHECKED_IN session; completing it breaches (2 >= 2)
    bundle = setup_reuse_count_at(target_count=2, dialyzer_reuse_limit=2)
    machine = validate_success(api.get_machine(bundle["machine"]["id"], ADMIN), 200)
    assert machine["dialyzer_reuse_count"] == 2
    res = api.complete_session(bundle["pending_session"]["id"], SCHED)
    validate_error(res, "ERR_DIALYZER_REUSE_EXCEEDED")


# ─── Corner: errors / void_billing_on_completed_session_not_voidable ──────
def test_void_billing_on_completed_session_rejected(api):
    """PRD §3.10: "a session that was never properly delivered can have its
    billing voided, moving `UNBILLED → VOID` (terminal); voiding is permitted only
    when the session's `clinical_status` is `CANCELLED` or `MISSED`, else
    `ERR_SESSION_NOT_VOIDABLE`."

    Design: Corner/errors/void_billing_on_completed_session_not_voidable
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=12, coinsurance_pct=0.0)
    completed = book_and_complete(scenario)
    res = api.void_billing_session(completed["id"], BILL)
    validate_error(res, "ERR_SESSION_NOT_VOIDABLE")


# ─── Corner: errors / bill_session_not_completed ──────────────────────────
def test_bill_booked_session_rejected(api):
    """PRD §3.10: "Billing a session moves it `UNBILLED → BILLED`, permitted only
    when the session's `clinical_status` is `COMPLETED`, else
    `ERR_SESSION_NOT_COMPLETED`."

    Design: Corner/errors/bill_session_not_completed
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    session = book_session(scenario)
    res = api.bill_session(session["id"], BILL)
    validate_error(res, "ERR_SESSION_NOT_COMPLETED")


# ─── Corner: errors / take_offline_blocked_by_booked_session ──────────────
def test_take_station_offline_blocked_by_booked_session(api):
    """PRD §3.2: "Taking a station offline moves it `ACTIVE → OUT_OF_SERVICE`, but
    only when no treatment session in `BOOKED` or `CHECKED_IN` occupies that
    station; an occupied station is rejected with `ERR_STATION_OCCUPIED`."

    Design: Corner/errors/take_offline_blocked_by_booked_session
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    book_session(scenario)
    res = api.take_station_offline(scenario["station"]["id"], ADMIN)
    validate_error(res, "ERR_STATION_OCCUPIED")


# ─── Corner: errors / close_clinic_with_active_sessions_rejected ──────────
def test_close_clinic_with_booked_session_rejected(api):
    """PRD §3.1: "Closing a clinic, however, is blocked while any treatment
    session in the clinic is still in `BOOKED` or `CHECKED_IN`, which earns
    `ERR_CLINIC_HAS_ACTIVE_SESSIONS`."

    Design: Corner/errors/close_clinic_with_active_sessions_rejected
    """
    scenario = setup_bookable_scenario(dialyzer_reuse_limit=99, coinsurance_pct=0.0)
    book_session(scenario)
    res = api.close_clinic(scenario["clinic"]["id"], ADMIN)
    validate_error(res, "ERR_CLINIC_HAS_ACTIVE_SESSIONS")
