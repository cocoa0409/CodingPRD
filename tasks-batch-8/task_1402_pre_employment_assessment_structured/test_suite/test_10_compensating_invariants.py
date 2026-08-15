"""Compensating invariants: interviewer committed minutes and the vendor content
ledger both return to their prior value after a forward+compensating pair."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_vendor,
    create_content_ledger_event_payload,
    create_session_payload,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_and_complete_candidate,
    make_vendorrep_headers,
    assert_interviewer,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/interviewer_minutes_book_cancel_compensation
# ---------------------------------------------------------------------------

def test_committed_minutes_track_each_booking(api):
    """PRD §3.6: "That counter is a conserved workload ledger: it equals the sum, over
    all of the interviewer's sessions currently in `SCHEDULED`, of each session's
    duration in whole minutes. Booking a session credits the duration".

    0 -> +60 -> +90 = 150 at each intermediate step.

    Design: Difficulty/compensating_invariant/interviewer_minutes_book_cancel_compensation
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)

    mins0 = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins0 == 0
    s1 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM),
        expected_status=201)
    mins1 = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins1 == 60
    s2 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:30:00Z"), HM),
        expected_status=201)
    mins2 = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins2 == 150
    iv = validate_success(api.get_interviewer(interviewer["id"], ADMIN))
    assert_interviewer(iv)
    return s1, s2, interviewer


def test_committed_minutes_return_to_zero_after_cancels(api):
    """PRD §3.6: "any cancellation of a scheduled session — manual, vendor cascade,
    candidate withdrawal, cycle close, or assessment cancellation — debits the same
    duration, so booking a session and then cancelling it returns
    `committed_minutes_total` to exactly its prior value."

    150 -> cancel 60 -> 90 -> cancel 90 -> 0.

    Design: Difficulty/compensating_invariant/interviewer_minutes_book_cancel_compensation
    """
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-12T10:00:00Z", scheduled_end="2026-08-12T11:00:00Z"), HM),
        expected_status=201)
    s2 = validate_success(api.create_session(cycle["id"], create_session_payload(
        c1["id"], interviewer["id"], guide["id"],
        scheduled_start="2026-08-13T10:00:00Z", scheduled_end="2026-08-13T11:30:00Z"), HM),
        expected_status=201)

    validate_success(api.cancel_session(s1["id"], HM))
    mins3 = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins3 == 90
    validate_success(api.cancel_session(s2["id"], HM))
    mins4 = validate_success(api.get_interviewer(interviewer["id"], ADMIN))["committed_minutes_total"]
    assert mins4 == 0, "forward+compensating pair returns the conserved quantity exactly"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/vendor_content_ledger_distribute_destroy_compensation
# ---------------------------------------------------------------------------

def test_content_ledger_distribute_destroy_arithmetic(api):
    """PRD §3.1: "The vendor's `content_copies_outstanding` is the sum of `copies` over
    distribution events minus the sum over destruction events".

    0 -> DISTRIBUTE 10 -> 10 -> DESTROY 4 -> 6 -> DESTROY 6 -> 0.

    Design: Difficulty/compensating_invariant/vendor_content_ledger_distribute_destroy_compensation
    """
    vendor = create_vendor()
    rep = make_vendorrep_headers(vendor["id"])
    l0 = validate_success(api.get_vendor(vendor["id"], ADMIN))["content_copies_outstanding"]
    assert l0 == 0
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(direction="DISTRIBUTE", copies=10),
        ADMIN), expected_status=201)
    l1 = validate_success(api.get_vendor(vendor["id"], ADMIN))["content_copies_outstanding"]
    assert l1 == 10
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(
            direction="DESTROY", copies=4, note="Certified destruction batch one."), rep),
        expected_status=201)
    l2 = validate_success(api.get_vendor(vendor["id"], ADMIN))["content_copies_outstanding"]
    assert l2 == 6
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(
            direction="DESTROY", copies=6, note="Certified destruction batch two."), rep),
        expected_status=201)
    l3 = validate_success(api.get_vendor(vendor["id"], ADMIN))["content_copies_outstanding"]
    assert l3 == 0, "distribute 10 + destroy 10 restores the conserved quantity exactly"


def test_content_ledger_negative_and_outstanding_gates(api):
    """PRD §3.1: "it may never go negative: a destruction event whose `copies` exceeds
    the current outstanding balance is rejected with `ERR_CONTENT_LEDGER_NEGATIVE`
    (HTTP 422)" and "a `content_copies_outstanding` balance above zero blocks
    termination with `ERR_CONTENT_COPIES_OUTSTANDING` (HTTP 422)".

    Design: Difficulty/compensating_invariant/vendor_content_ledger_distribute_destroy_compensation
    """
    vendor = create_vendor()
    rep = make_vendorrep_headers(vendor["id"])
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(direction="DISTRIBUTE", copies=10),
        ADMIN), expected_status=201)
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(
            direction="DESTROY", copies=4, note="Certified destruction batch one."), rep),
        expected_status=201)
    # outstanding 6 blocks terminate
    resp = api.terminate_vendor(vendor["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_CONTENT_COPIES_OUTSTANDING)
    # settle to zero
    validate_success(api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(
            direction="DESTROY", copies=6, note="Certified destruction batch two."), rep),
        expected_status=201)
    # DESTROY 1 at outstanding 0 would drive the ledger negative
    resp = api.create_content_ledger_event(
        vendor["id"], create_content_ledger_event_payload(
            direction="DESTROY", copies=1, note="One copy too many."), rep)
    validate_error(resp, ApiErrorId.ERR_CONTENT_LEDGER_NEGATIVE)
    # settled ledger now terminates
    resp = api.terminate_vendor(vendor["id"], ADMIN)
    assert validate_success(resp)["status"] == "TERMINATED"
