"""Guest screening: risk scoring, pass/fail precedence, the revision cycle,
and approval gated on a passed screen.

Covers difficulty rules non_linear_state_machine (screening half) and
cross_entity_state_dependency (approve half), plus corner calculations /
state_machines screening instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, make_guest_headers,
    create_host, create_guest, create_listed_listing, create_booking,
    setup_screening_booking, get_latest_screening_result,
)


# ==========================================================================
# Difficulty: non_linear_state_machine (booking screening revision cycle)
# ==========================================================================
def test_screening_revision_cycle_returns_to_requested(api):
    """PRD §3.5: "The host may bounce the request back for more guest
    information, returning the booking from `SCREENING` to `REQUESTED`; this
    discards the latest screening result rather than marking it failed — a
    subsequent screen run creates a fresh one."

    Design: Difficulty/non_linear_state_machine/booking_screening_revision_cycle
    """
    ctx = setup_screening_booking(guest_overrides={"govt_id_verified": True})
    host, booking = ctx["host"], ctx["booking"]
    resp = api.request_info_booking(booking["id"], headers=make_host_headers(host["id"]))
    after = validate_success(resp)
    assert after["status"] == "REQUESTED", \
        f"After request-info expected REQUESTED, got {after['status']}"


def test_screening_cycle_can_be_re_screened(api):
    """PRD §3.5: "Screening begins when the owning host moves a booking from
    `REQUESTED` to `SCREENING`."
    PRD §3.5: "The host may bounce the request back for more guest information,
    returning the booking from `SCREENING` to `REQUESTED`; this discards the
    latest screening result rather than marking it failed — a subsequent screen
    run creates a fresh one."

    Design: Difficulty/non_linear_state_machine/booking_screening_revision_cycle
    """
    ctx = setup_screening_booking(guest_overrides={"govt_id_verified": True})
    host, booking = ctx["host"], ctx["booking"]
    api.request_info_booking(booking["id"], headers=make_host_headers(host["id"]))
    resp = api.screen_booking(booking["id"], headers=make_host_headers(host["id"]))
    after = validate_success(resp)
    assert after["status"] == "SCREENING", \
        f"After re-screen expected SCREENING (cycle traversed twice), got {after['status']}"


# ==========================================================================
# Difficulty: cross_entity_state_dependency (approve depends on screening PASSED)
# ==========================================================================
def test_approve_succeeds_when_screening_passed(api):
    """PRD §3.5: "The host may approve, advancing `SCREENING` to `APPROVED`, but
    approval is gated on the booking's latest screening result being `PASSED`;
    an approve attempt while the latest result is not `PASSED` is rejected with
    `ERR_SCREENING_NOT_PASSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/booking_approve_depends_on_screening_passed
    """
    ctx = setup_screening_booking(
        guest_overrides={"govt_id_verified": True, "prior_cancellations": 2,
                         "chargeback_flag": False})
    host, booking = ctx["host"], ctx["booking"]
    sr = get_latest_screening_result(host, booking)
    assert sr["status"] == "PASSED", f"Screening should PASS, got {sr['status']}"
    resp = api.approve_booking(booking["id"], headers=make_host_headers(host["id"]))
    after = validate_success(resp)
    assert after["status"] == "APPROVED", \
        f"Approve with PASSED screen should reach APPROVED, got {after['status']}"


def test_approve_rejected_when_screening_failed(api):
    """PRD §3.5: "an approve attempt while the latest result is not `PASSED` is
    rejected with `ERR_SCREENING_NOT_PASSED` (HTTP 409)."

    Second test of the cross-entity dependency: the FAILED-screen branch.

    Design: Difficulty/cross_entity_state_dependency/booking_approve_depends_on_screening_passed
    """
    ctx = setup_screening_booking(guest_overrides={"govt_id_verified": False})
    host, booking = ctx["host"], ctx["booking"]
    resp = api.approve_booking(booking["id"], headers=make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_PASSED.value)


# ==========================================================================
# Corner: calculations / guest_risk_score
# ==========================================================================
def test_guest_risk_score_below_threshold_passes(api):
    """PRD §3.5: "It starts at zero and adds 15 points for each of the guest's
    `prior_cancellations`, adds 60 points if the guest's `chargeback_flag` is
    set, and adds 40 points if the guest's `govt_id_verified` is false (a
    verified guest adds nothing on that count)."
    PRD §3.5: "The screening result resolves to `PASSED` only when all three
    conditions hold: the guest's `govt_id_verified` is true, the guest's
    `chargeback_flag` is false, and the computed risk score is strictly less
    than 50."

    Design: Corner/calculations/guest_risk_score_pass_below_threshold
    """
    ctx = setup_screening_booking(
        guest_overrides={"govt_id_verified": True, "prior_cancellations": 3,
                         "chargeback_flag": False})
    host, guest, booking = ctx["host"], ctx["guest"], ctx["booking"]
    resp = api.get_guest(guest["id"], headers=make_host_headers(host["id"]))
    gdata = validate_success(resp)
    assert gdata["risk_score"] == 45.00, \
        f"3*15 = 45.00 risk_score expected, got {gdata['risk_score']}"
    sr = get_latest_screening_result(host, booking)
    assert sr["status"] == "PASSED", f"risk 45 < 50 should PASS, got {sr['status']}"


# ==========================================================================
# Corner: state_machines / screening fail reason precedence
# ==========================================================================
def test_screening_failure_reason_precedence(api):
    """PRD §3.5: "If any of the three conditions is violated the result is
    `FAILED`, and its `failure_reason` is set to the single dominant
    disqualifier chosen by a fixed precedence: an unverified government ID
    (`ID_UNVERIFIED`) takes precedence over a chargeback (`CHARGEBACK`), which
    in turn takes precedence over crossing the risk threshold
    (`RISK_THRESHOLD`)."

    Design: Corner/state_machines/screening_fail_reason_precedence
    """
    ctx = setup_screening_booking(
        guest_overrides={"govt_id_verified": False, "prior_cancellations": 0,
                         "chargeback_flag": True})
    host, booking = ctx["host"], ctx["booking"]
    sr = get_latest_screening_result(host, booking)
    assert sr["status"] == "FAILED", f"Expected FAILED, got {sr['status']}"
    assert sr["failure_reason"] == "ID_UNVERIFIED", \
        f"ID_UNVERIFIED outranks CHARGEBACK, got {sr['failure_reason']}"
