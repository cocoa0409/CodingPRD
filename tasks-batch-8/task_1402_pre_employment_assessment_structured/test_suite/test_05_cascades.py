"""Transitive cascades: vendor suspension depth-3 chain and cycle-close fan-out."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_active_cycle,
    create_calibrated_interviewer,
    create_candidate,
    invite_candidate,
    schedule_assessment,
    invite_and_complete_candidate,
    create_session_payload,
    set_clock_payload,
    complete_assessment_at,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/vendor_suspension_depth_three_cascade
# ---------------------------------------------------------------------------

def _build_vendor_cascade_setup():
    """ACTIVE cycle on the vendor's VALIDATED instrument; one COMPLETED candidate;
    one SCHEDULED session 2026-08-14T10:00-11:00 (60 min) with iv1."""
    ctx = setup_active_cycle()
    guide = ctx["guide"]
    cycle = ctx["cycle"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    resp = api_client.create_session(
        cycle["id"],
        create_session_payload(c1["id"], interviewer["id"], guide["id"],
                               scheduled_start="2026-08-14T10:00:00Z",
                               scheduled_end="2026-08-14T11:00:00Z"),
        HM,
    )
    session = get_success_data(resp)
    mins_pre = validate_success(
        api_client.get_interviewer(interviewer["id"], ADMIN)
    )["committed_minutes_total"]
    assert mins_pre == 60
    return ctx, interviewer, session


def test_vendor_suspend_freezes_cycles_and_cancels_sessions(api):
    """PRD §3.1: "Suspending a vendor is the deepest cascade in the system, propagating
    three links outward." and "second, every assessment cycle whose pinned
    `instrument_id` belongs to that flagged set and whose `posture` is `SETUP`,
    `ACTIVE`, or `SCORING` is forced into `FROZEN`, capturing the prior posture in
    `frozen_from_posture`, recording `frozen_reason` as `VENDOR_HOLD`, and incrementing
    the cycle's `version`" and "third, every interview session in those cycles still in
    `SCHEDULED` status is cancelled with `cancellation_reason` set to `VENDOR_HOLD` and
    its `version` incremented, and each such cancellation debits the affected
    interviewer's `committed_minutes_total` by the session's duration in minutes."

    Design: Difficulty/transitive_cascade/vendor_suspension_depth_three_cascade
    """
    ctx, interviewer, session = _build_vendor_cascade_setup()
    vendor = ctx["vendor"]
    instrument = ctx["instrument"]
    cycle = ctx["cycle"]

    resp = api.suspend_vendor(vendor["id"], ADMIN)
    assert validate_success(resp)["status"] == "SUSPENDED"
    inst = validate_success(api.get_instrument(instrument["id"], ADMIN))
    assert inst["vendor_suspended"] is True
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["posture"] == "FROZEN"
    assert cyc["frozen_from_posture"] == "ACTIVE"
    assert cyc["frozen_reason"] == "VENDOR_HOLD"
    sess = validate_success(api.get_session(session["id"], ADMIN))
    assert sess["status"] == "CANCELLED"
    assert sess["cancellation_reason"] == "VENDOR_HOLD"
    mins_post = validate_success(api.get_interviewer(interviewer["id"], ADMIN))[
        "committed_minutes_total"
    ]
    assert mins_post == 0, "60-minute session cancelled -> minutes debited to 0"


def test_vendor_reinstate_is_asymmetric_compensation(api):
    """PRD §3.1: "Reinstating a vendor unwinds only part of that cascade." and
    "The compensation is deliberately asymmetric: sessions cancelled by the suspension
    are not restored, and the debited committed minutes are not re-credited."

    Design: Difficulty/transitive_cascade/vendor_suspension_depth_three_cascade
    """
    ctx, interviewer, session = _build_vendor_cascade_setup()
    vendor = ctx["vendor"]
    cycle = ctx["cycle"]
    api.suspend_vendor(vendor["id"], ADMIN)

    resp = api.reinstate_vendor(vendor["id"], ADMIN)
    assert validate_success(resp)["status"] == "ACTIVE"
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["posture"] == "ACTIVE", "frozen_from_posture restored on reinstate"
    assert cyc["frozen_from_posture"] is None
    assert cyc["frozen_reason"] is None
    sess = validate_success(api.get_session(session["id"], ADMIN))
    assert sess["status"] == "CANCELLED", "cancelled sessions are NOT restored"
    mins = validate_success(api.get_interviewer(interviewer["id"], ADMIN))[
        "committed_minutes_total"
    ]
    assert mins == 0, "debited minutes are NOT re-credited"


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/cycle_close_cancel_fanout_is_chained
# ---------------------------------------------------------------------------

def _build_cycle_close_setup():
    """Cycle ACTIVE: a1 COMPLETED (raw 72) with SCHEDULED session s1 08-14 10:00-11:00;
    a2 still SCHEDULED (not started). Clock parked at 2026-08-15T09:00:00Z."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    c2 = create_candidate(external_ref="C-2", full_name="Cand Two", email="c2@x.com",
                          group_code="GROUP_B")
    a1 = invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    a2 = invite_candidate(cycle["id"], c2["id"])
    schedule_assessment(a2["id"], scheduled_for="2026-08-16T09:00:00Z")
    resp = api_client.create_session(
        cycle["id"],
        create_session_payload(c1["id"], interviewer["id"], guide["id"],
                               scheduled_start="2026-08-14T10:00:00Z",
                               scheduled_end="2026-08-14T11:00:00Z"),
        HM,
    )
    session = get_success_data(resp)
    api_client.set_clock(set_clock_payload("2026-08-15T09:00:00Z"), ADMIN)
    return ctx, a1, a2, session, interviewer


def test_cycle_close_cascades_to_non_terminal_assessments_and_sessions(api):
    """PRD §3.4: "First, every candidate assessment in the cycle whose `admin_status` is
    `INVITED`, `SCHEDULED`, `ACCOMMODATION_HOLD`, or `IN_PROGRESS` moves to `CANCELLED`,
    with its `feedback_status` moving `NOT_SENT` → `NOT_APPLICABLE` where still unsent,
    and its `version` incremented." and "Second, each such cancellation decrements the
    cycle's `active_candidate_count` by one and cancels that candidate's
    still-`SCHEDULED` interview sessions in the cycle with `cancellation_reason` of
    `CYCLE_CLOSED`, debiting each affected interviewer's committed minutes."

    Design: Difficulty/transitive_cascade/cycle_close_cancel_fanout_is_chained
    """
    ctx, a1, a2, session, interviewer = _build_cycle_close_setup()
    cycle = ctx["cycle"]
    resp = api.close_cycle(cycle["id"], HM)
    closed = validate_success(resp)
    assert closed["posture"] == "CLOSED"
    from test_helpers import assert_iso_instant_equal
    assert_iso_instant_equal(closed["closed_at"], "2026-08-15T09:00:00Z")
    # Link 1 is conditional: terminal COMPLETED a1 untouched; SCHEDULED a2 cancelled
    a1_after = validate_success(api.get_assessment(a1["id"], HM))
    assert a1_after["admin_status"] == "COMPLETED"
    a2_after = validate_success(api.get_assessment(a2["id"], HM))
    assert a2_after["admin_status"] == "CANCELLED"
    assert a2_after["feedback_status"] == "NOT_APPLICABLE"
    # Cycle counters
    cyc = validate_success(api.get_cycle(cycle["id"], CO))
    assert cyc["active_candidate_count"] == 1, "only a2's cancellation decremented"


def test_cycle_close_reanchors_retention_for_undecided_completed(api):
    """PRD §3.4: "Third, the retention anchor is recomputed for every completed
    assessment in the cycle that has no finalized decision: its `retention_expires_at`
    becomes the cycle's `closed_at` plus the requisition's `retention_days`."

    Design: Difficulty/transitive_cascade/cycle_close_cancel_fanout_is_chained
    """
    ctx, a1, a2, session, interviewer = _build_cycle_close_setup()
    cycle = ctx["cycle"]
    resp = api.close_cycle(cycle["id"], HM)
    closed = validate_success(resp)
    a1_after = validate_success(api.get_assessment(a1["id"], HM))
    # closed_at 2026-08-15T09:00:00Z + 730 days = 2028-08-14T09:00:00Z
    from test_helpers import assert_iso_instant_equal
    assert_iso_instant_equal(a1_after["retention_expires_at"], "2028-08-14T09:00:00Z")
