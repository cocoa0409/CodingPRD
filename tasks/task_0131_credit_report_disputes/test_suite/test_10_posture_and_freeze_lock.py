"""PRD §3.7 (posture), §3.11 (freeze, lock), §3.12 (hard inquiries),
§3.14 (archive).

Covers:
- Posture: FROZEN if active freeze else RESTRICTED if active disputes
  >=1 else OPEN. Boundary: exactly 0 active disputes -> OPEN.
- CreditFreeze placement mints freeze_pin on first; uniqueness per
  (consumer, bureau); lift requires correct PIN.
- CreditLock placement; uniqueness per (consumer, bureau);
  unlock/relock.
- HardInquiry: BLOCKED_FREEZE on ACTIVE freeze; BLOCKED_LOCK on
  LOCKED lock; ACCEPTED otherwise.
- CreditReport.archive blocked when non-terminal disputes exist.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    assert_credit_freeze,
    assert_credit_lock,
    assert_hard_inquiry,
    close_dispute_verified,
    create_consumer,
    create_credit_report,
    create_furnisher,
    get_consumer,
    get_credit_report,
    lift_credit_freeze,
    lift_credit_freeze_payload,
    make_consumer_headers,
    make_furnisher_headers,
    place_credit_freeze,
    place_credit_lock,
    relock_credit_lock,
    request_hard_inquiry,
    setup_consumer_furnisher_report_tradeline,
    setup_consumer_with_freeze,
    submit_dispute,
    unlock_credit_lock,
    validate_error,
    validate_success,
)


# ===========================================================================
# Posture — PRD §3.7
# ===========================================================================
class TestPosture:

    def test_open_posture_when_no_freeze_no_dispute(self, api):
        """PRD §3.7: 'Otherwise — that is, only when the active-disputes
        count is exactly zero — the posture is OPEN.'

        Initially a freshly created report has zero active disputes
        and no freezes -> posture must be OPEN."""
        c = create_consumer()
        r = create_credit_report(c["id"])
        assert r["posture"] == "OPEN"

    def test_restricted_posture_when_active_dispute(self, api):
        """PRD §3.7: 'if the active-disputes count is at least one,
        the posture is RESTRICTED.'

        PRD §3.2 start_investigation side effect: 'with an active
        dispute now on the report, the posture becomes RESTRICTED.'"""
        from test_helpers import (
            setup_dispute_in_state,
        )
        c, f, r, t, d = setup_dispute_in_state(state="UNDER_INVESTIGATION")
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["posture"] == "RESTRICTED"

    def test_open_posture_after_dispute_closes(self, api):
        """PRD §3.7 boundary: 'the posture returns to OPEN only when
        no non-terminal disputes remain.'

        Close the dispute VERIFIED -> active count = 0 -> OPEN."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_verified(consumer=c, report=r, tradeline=t)
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["posture"] == "OPEN"

    def test_frozen_posture_dominates_disputes(self, api):
        """PRD §3.7: 'If the active-freezes count is greater than
        zero, the posture is FROZEN.'

        Freeze on matching bureau dominates even if a dispute is
        also active."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        # Submit dispute then freeze on matching bureau.
        submit_dispute(consumer=c, report=r, tradeline=t)
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        r_after = get_credit_report(c["id"], r["id"])
        assert r_after["posture"] == "FROZEN"


# ===========================================================================
# CreditFreeze — PRD §3.11
# ===========================================================================
class TestCreditFreeze:

    def test_first_freeze_mints_freeze_pin(self, api):
        """PRD §3.11: 'If this is the consumer's first freeze across
        any bureau, the system mints a freeze_pin on the Consumer
        and that PIN persists for all future freeze lifts.'"""
        c = create_consumer()
        assert c["freeze_pin"] is None
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        c_after = get_consumer(
            c["id"], headers=make_consumer_headers(c["id"]),
        )
        assert c_after["freeze_pin"] is not None
        assert isinstance(c_after["freeze_pin"], str)
        assert len(c_after["freeze_pin"]) > 0

    def test_second_freeze_same_bureau_rejected(self, api):
        """PRD §3.11: 'At most one ACTIVE CreditFreeze may exist per
        (consumer_id, bureau) pair; a second placement is rejected
        with ERR_FREEZE_ALREADY_ACTIVE'."""
        c = create_consumer()
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        res = api.create_credit_freeze(
            c["id"], {"bureau": "EQUIFAX"},
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FREEZE_ALREADY_ACTIVE)

    def test_freeze_on_other_bureau_succeeds(self, api):
        """PRD §3.11: '(consumer_id, bureau) pair' — the partition
        key includes bureau, so freezes on different bureaus are
        independent."""
        c = create_consumer()
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        res = api.create_credit_freeze(
            c["id"], {"bureau": "EXPERIAN"},
            make_consumer_headers(c["id"]),
        )
        validate_success(res, 201)

    def test_lift_with_correct_pin_succeeds(self, api):
        """PRD §3.11: 'On success, the freeze's status flips to
        LIFTED and its lifted_day is stamped from the current clock
        day'."""
        from test_helpers import read_clock_day
        c, freeze = setup_consumer_with_freeze(bureau="EQUIFAX")
        c_after_place = get_consumer(
            c["id"], headers=make_consumer_headers(c["id"]),
        )
        pin = c_after_place["freeze_pin"]
        now = read_clock_day()
        lifted = lift_credit_freeze(
            consumer=c, freeze_id=freeze["id"], pin=pin,
        )
        assert lifted["status"] == "LIFTED"
        assert lifted["lifted_day"] == now

    def test_lift_with_wrong_pin_rejected(self, api):
        """PRD §3.11: 'If the supplied pin does not equal the
        consumer's freeze_pin, the lift is rejected with
        ERR_INVALID_FREEZE_PIN.'"""
        c, freeze = setup_consumer_with_freeze(bureau="EQUIFAX")
        res = api.lift_credit_freeze(
            c["id"], freeze["id"],
            lift_credit_freeze_payload(pin="0000000-WRONG-PIN-0000"),
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_FREEZE_PIN)


# ===========================================================================
# CreditLock — PRD §3.11
# ===========================================================================
class TestCreditLock:

    def test_lock_initial_status_locked(self, api):
        """PRD §3.11: 'on engagement, status is set to LOCKED'."""
        c = create_consumer()
        lock = place_credit_lock(consumer=c, bureau="EQUIFAX")
        assert_credit_lock(lock)
        assert lock["status"] == "LOCKED"

    def test_second_lock_same_bureau_rejected(self, api):
        """PRD §3.11: 'At most one LOCKED CreditLock may exist per
        (consumer_id, bureau) pair; a second engagement is rejected
        with ERR_LOCK_ALREADY_ACTIVE.'"""
        c = create_consumer()
        place_credit_lock(consumer=c, bureau="EQUIFAX")
        res = api.create_credit_lock(
            c["id"], {"bureau": "EQUIFAX"},
            make_consumer_headers(c["id"]),
        )
        validate_error(res, ApiErrorId.ERR_LOCK_ALREADY_ACTIVE)

    def test_unlock_relock_round_trip(self, api):
        """PRD §3.11: 'Unlike a freeze, a lock has no PIN: the
        consumer simply unlocks (transitioning the lock from LOCKED
        to UNLOCKED) or relocks (transitioning from UNLOCKED back to
        LOCKED) at will.'"""
        c = create_consumer()
        lock = place_credit_lock(consumer=c, bureau="EQUIFAX")
        unlocked = unlock_credit_lock(consumer=c, lock_id=lock["id"])
        assert unlocked["status"] == "UNLOCKED"
        relocked = relock_credit_lock(consumer=c, lock_id=lock["id"])
        assert relocked["status"] == "LOCKED"


# ===========================================================================
# HardInquiry — PRD §3.12
# ===========================================================================
class TestHardInquiry:

    def test_accepted_when_no_freeze_no_lock(self, api):
        """PRD §3.12: 'Only when neither a freeze nor a lock is in
        effect does the outcome record as ACCEPTED'."""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        resp = request_hard_inquiry(
            credit_report_id=r["id"], furnisher=f,
        )
        hi = validate_success(resp, 201)
        assert_hard_inquiry(hi)
        assert hi["outcome"] == "ACCEPTED"

    def test_blocked_freeze_when_freeze_active(self, api):
        """PRD §3.12: 'If the matching (consumer_id, bureau) pair
        carries an ACTIVE CreditFreeze, the outcome is BLOCKED_FREEZE
        and the request is rejected with
        ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        place_credit_freeze(consumer=c, bureau="EQUIFAX")
        resp = request_hard_inquiry(
            credit_report_id=r["id"], furnisher=f,
        )
        validate_error(resp, ApiErrorId.ERR_HARD_INQUIRY_BLOCKED_BY_FREEZE)

    def test_blocked_lock_when_lock_locked(self, api):
        """PRD §3.12: 'Otherwise, if the matching pair carries a
        LOCKED CreditLock, the outcome is BLOCKED_LOCK and the
        request is rejected with ERR_HARD_INQUIRY_BLOCKED_BY_LOCK.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline(
            bureau="EQUIFAX",
        )
        place_credit_lock(consumer=c, bureau="EQUIFAX")
        resp = request_hard_inquiry(
            credit_report_id=r["id"], furnisher=f,
        )
        validate_error(resp, ApiErrorId.ERR_HARD_INQUIRY_BLOCKED_BY_LOCK)


# ===========================================================================
# Archive — PRD §3.14
# ===========================================================================
class TestArchive:

    def test_archive_blocked_when_non_terminal_dispute(self, api):
        """PRD §3.14: 'A PlatformAdmin archives a CreditReport by
        invoking the archive action on the report. The transition is
        from ACTIVE to ARCHIVED and is rejected if any Dispute on the
        report is in a non-terminal state ..., in which case
        ERR_REPORT_HAS_OPEN_DISPUTES is returned.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        submit_dispute(consumer=c, report=r, tradeline=t)
        res = api.archive_credit_report(
            c["id"], r["id"], TEST_USERS["platform_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_REPORT_HAS_OPEN_DISPUTES)

    def test_archive_succeeds_when_all_disputes_terminal(self, api):
        """PRD §3.14: 'There are no side effects beyond the status
        flip itself; archived reports remain readable but are no
        longer subject to further dispute submission.'"""
        c, f, r, t = setup_consumer_furnisher_report_tradeline()
        close_dispute_verified(consumer=c, report=r, tradeline=t)
        res = api.archive_credit_report(
            c["id"], r["id"], TEST_USERS["platform_admin_headers"],
        )
        archived = validate_success(res, 200)
        assert archived["status"] == "ARCHIVED"
