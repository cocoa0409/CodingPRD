"""Transitive cascades and compensating invariants: verification-driven completion
(certificate issuance + placement completion), report-back suspension cascade, and
void-preserves-partition.

Covers Difficulty queue: transitive_cascade (x2) and compensating_invariant (void).
"""
from test_helpers import (
    validate_success,
    assert_referral_partition, assert_certificate,
    TEST_USERS,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# ============================ Difficulty: verify -> complete -> cert -> placement
def test_verification_completes_referral_and_cascades(api):
    """PRD §3.8: "When a verification credit brings `hours_completed` to at least `hours_ordered` and
    `hours_outstanding` to 0, the referral moves from `ACTIVE` to `COMPLETED`."
    PRD §3.8: "In both cases the system auto-issues a completion certificate and cascades every `ACTIVE`
    placement for the referral to `COMPLETED`."
    PRD §3.8: "writes the new certificate's `id` back onto the referral as `certificate_id`."

    Design: Difficulty/transitive_cascade/tc_verify_completes_referral_issues_cert_completes_placement
    """
    s = fx.active_placement_scenario(hours_ordered=3.50, court_case_number="CR-7")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T10:52:00Z")
    fx.completed_session(s, "2026-06-02T09:00:00Z", "2026-06-02T10:52:00Z")
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 3.50
    assert ref["status"] == "COMPLETED"
    assert ref["certificate_id"] is not None
    plc = validate_success(api.get_placement(s["placement_id"], COORD), 200)
    assert plc["status"] == "COMPLETED"


def test_completion_certificate_pins_total_hours_credited(api):
    """PRD §3.8: "At issuance the system mints a human-readable `certificate_number`, pins
    `total_hours_credited` to the referral's `hours_completed` plus `hours_converted` at
    that instant, stamps `issued_at` with the current clock, records the `referral_id`".

    Design: Difficulty/transitive_cascade/tc_verify_completes_referral_issues_cert_completes_placement
    """
    s = fx.active_placement_scenario(hours_ordered=3.50, court_case_number="CR-7B")
    fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T10:52:00Z")
    fx.completed_session(s, "2026-06-02T09:00:00Z", "2026-06-02T10:52:00Z")
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    cert = validate_success(api.get_certificate(ref["certificate_id"], COORD), 200)
    assert_certificate(cert)
    assert cert["referral_id"] == s["referral_id"]
    assert cert["total_hours_credited"] == 3.50


# ============================ Difficulty: report-back suspension cascade
def test_reportback_suspends_placement_and_cancels_session(api):
    """PRD §3.7: "A `REPORT_BACK` reports the participant back to court and drives the referral from `ACTIVE`
    to `NON_COMPLIANT`, so `resulting_referral_status` is `NON_COMPLIANT`; this cascades
    every `ACTIVE` placement for the referral to `SUSPENDED`, and each such suspension in
    turn cancels that placement's still-`SCHEDULED` sessions (moving them to `CANCELLED`)."

    Design: Difficulty/transitive_cascade/tc_reportback_suspends_placement_cancels_scheduled_sessions
    """
    s = fx.active_placement_scenario(court_case_number="CR-8")
    ws = fx.new_session(s["placement_id"], "2026-06-10T09:00:00Z", "2026-06-10T12:00:00Z")
    fx.report_back(s["referral_id"], reason="Absconded")
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["status"] == "NON_COMPLIANT"
    plc = validate_success(api.get_placement(s["placement_id"], COORD), 200)
    assert plc["status"] == "SUSPENDED"
    session = validate_success(api.get_work_session(ws["id"], COORD), 200)
    assert session["attendance_status"] == "CANCELLED"


def test_reportback_cancels_all_scheduled_sessions(api):
    """PRD §3.7: "each such suspension in turn cancels that placement's still-`SCHEDULED` sessions (moving
    them to `CANCELLED`)."

    Design: Difficulty/transitive_cascade/tc_reportback_suspends_placement_cancels_scheduled_sessions
    """
    s = fx.active_placement_scenario(court_case_number="CR-8B")
    ws1 = fx.new_session(s["placement_id"], "2026-06-10T09:00:00Z", "2026-06-10T11:00:00Z")
    ws2 = fx.new_session(s["placement_id"], "2026-06-10T13:00:00Z", "2026-06-10T15:00:00Z")
    fx.report_back(s["referral_id"], reason="Absconded")
    for ws in (ws1, ws2):
        session = validate_success(api.get_work_session(ws["id"], COORD), 200)
        assert session["attendance_status"] == "CANCELLED"


# ============================ Difficulty: void preserves hours partition
def test_void_verified_session_restores_partition(api):
    """PRD §3.5: "If the session had been `VERIFIED`, voiding reverses its credit by subtracting its
    `verified_hours` from the referral's `hours_completed` and recomputing
    `hours_outstanding`".

    Design: Difficulty/compensating_invariant/ci_void_session_preserves_hours_partition
    """
    s = fx.active_placement_scenario(hours_ordered=10, court_case_number="CR-17")
    ws = fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T13:00:00Z")  # 4.00
    voided = validate_success(api.void_work_session(ws["id"], COORD,
                                                    {"reason": "logged in error"}), 200)
    assert voided["attendance_status"] == "VOIDED"
    ref = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert ref["hours_completed"] == 0
    assert ref["hours_converted"] == 0
    assert ref["hours_outstanding"] == 10


def test_void_keeps_partition_invariant_balanced(api):
    """PRD §2.7: "The governing invariant, which must hold at all times, is that `hours_ordered` equals
    `hours_completed` plus `hours_converted` plus `hours_outstanding`."

    Design: Difficulty/compensating_invariant/ci_void_session_preserves_hours_partition
    """
    s = fx.active_placement_scenario(hours_ordered=10, court_case_number="CR-17B")
    ws = fx.completed_session(s, "2026-06-01T09:00:00Z", "2026-06-01T13:00:00Z")  # 4.00
    after_verify = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert after_verify["hours_completed"] == 4
    assert after_verify["hours_outstanding"] == 6
    assert_referral_partition(after_verify)
    validate_success(api.void_work_session(ws["id"], COORD), 200)
    after_void = validate_success(api.get_referral(s["referral_id"], COORD), 200)
    assert_referral_partition(after_void)
    assert after_void["hours_completed"] == 0
    assert after_void["hours_outstanding"] == 10
