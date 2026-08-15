"""Validation-priority pair conflicts: state beats temporal, safety beats referential,
constraint beats temporal (PRD §2.8 normative ordering)."""
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
    invite_and_complete_candidate,
    book_completed_session,
    create_approved_guide,
    create_cycle_payload,
    create_session_payload,
    create_scorecard_payload,
    freeze_cycle_payload,
    set_clock_payload,
    make_interviewer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
HM = TEST_USERS["hm_headers"]
CO = TEST_USERS["co_headers"]


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_on_scorecard_submit
# ---------------------------------------------------------------------------

def _build_frozen_cycle_with_stale_scorecard():
    """Cycle FROZEN; c1 COMPLETED; session s1 COMPLETED at 2026-08-12T11:00:00Z;
    DRAFT scorecard sc1 exists. Clock then moved to 2026-08-16T00:00:00Z so the
    72h submit window (closing 2026-08-15T11:00:00Z) has also elapsed."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    s1 = book_completed_session(cycle["id"], c1["id"], interviewer["id"], guide["id"],
                                "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z")
    resp = api_client.create_scorecard(
        s1["id"],
        create_scorecard_payload(ratings=[{"competency_code": "COMM", "rating": 4}]),
        make_interviewer_headers(interviewer["id"]),
    )
    sc1 = get_success_data(resp)
    get_success_data(api_client.freeze_cycle(cycle["id"], freeze_cycle_payload(), CO))
    get_success_data(api_client.set_clock(set_clock_payload("2026-08-16T00:00:00Z"), ADMIN))
    return ctx, interviewer, sc1


def test_scorecard_submit_frozen_cycle_reports_state_not_window(api):
    """PRD §2.8: "the failure reported is the violated rule with the lowest priority
    number" — tier 7 (dedicated state gates) lists `ERR_CYCLE_FROZEN` before tier 11
    (temporal gates) lists `ERR_SCORECARD_WINDOW_CLOSED`.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_on_scorecard_submit
    """
    ctx, interviewer, sc1 = _build_frozen_cycle_with_stale_scorecard()
    resp = api.submit_scorecard(sc1["id"], make_interviewer_headers(interviewer["id"]))
    validate_error(resp, ApiErrorId.ERR_CYCLE_FROZEN)


def test_scorecard_submit_frozen_cycle_leaves_scorecard_draft(api):
    """PRD §3.6: "Submitting is the author's own act and moves `DRAFT` → `SUBMITTED`" —
    a rejected submit performs no transition, so the scorecard remains DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_on_scorecard_submit
    """
    ctx, interviewer, sc1 = _build_frozen_cycle_with_stale_scorecard()
    api.submit_scorecard(sc1["id"], make_interviewer_headers(interviewer["id"]))
    data = validate_success(api.get_scorecard(sc1["id"], ADMIN))
    assert data["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/safety_priority_beats_referential_on_session_create
# ---------------------------------------------------------------------------

def _build_uncalibrated_and_mismatched_session_setup():
    """Cycle ACTIVE pinning g1; second APPROVED guide g2 (distinct id); c1 COMPLETED;
    iv3 holds only a TRAINED record for g1 (never certified)."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    g1 = ctx["guide"]
    g2 = create_approved_guide(
        rubric_items=[{"competency_code": "COMM", "weight": 0.5, "scale_max": 5},
                      {"competency_code": "ANAL", "weight": 0.5, "scale_max": 5}],
        title="Guide Two",
    )
    # iv3 with a TRAINED-only record for g1
    from test_helpers import create_interviewer, create_calibration_payload
    iv3 = create_interviewer(full_name="Ivy Three", email="ivy3@x.com")
    get_success_data(api_client.create_calibration(iv3["id"], create_calibration_payload(g1["id"]), ADMIN))
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    return ctx, g2, iv3, c1


def test_session_create_uncalibrated_beats_guide_mismatch(api):
    """PRD §2.8: tier 9 (business safety gates) names `ERR_INTERVIEWER_NOT_CALIBRATED`
    before tier 12 (guide version pinning) names `ERR_GUIDE_VERSION_MISMATCH`, and "the
    failure reported is the violated rule with the lowest priority number".

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_beats_referential_on_session_create
    """
    ctx, g2, iv3, c1 = _build_uncalibrated_and_mismatched_session_setup()
    cycle = ctx["cycle"]
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv3["id"], g2["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_INTERVIEWER_NOT_CALIBRATED)


def test_session_create_guide_mismatch_alone_reports_referential(api):
    """PRD §3.6: "finally the version pin — the supplied `guide_id` must equal the
    cycle's pinned `guide_id`, else `ERR_GUIDE_VERSION_MISMATCH` (HTTP 422)".

    With a CALIBRATED interviewer (safety satisfied) the referential gate surfaces.

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_beats_referential_on_session_create
    """
    ctx, g2, _iv3, c1 = _build_uncalibrated_and_mismatched_session_setup()
    cycle = ctx["cycle"]
    g1 = ctx["guide"]
    iv_ok, _cal = create_calibrated_interviewer(g1["id"])
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], iv_ok["id"], g2["id"],
                               scheduled_start="2026-08-12T10:00:00Z",
                               scheduled_end="2026-08-12T11:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_GUIDE_VERSION_MISMATCH)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/constraint_priority_beats_temporal_on_session_create
# ---------------------------------------------------------------------------

def _build_duration_and_window_conflict_setup():
    """Cycle ACTIVE (window ends 2026-08-20T00:00:00Z); c1 COMPLETED; iv1 CALIBRATED."""
    ctx = setup_active_cycle()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    interviewer, _cal = create_calibrated_interviewer(guide["id"])
    c1 = create_candidate(external_ref="C-1", full_name="Cand One", email="c1@x.com",
                          group_code="GROUP_A")
    invite_and_complete_candidate(cycle["id"], c1["id"], raw_score=72)
    return ctx, interviewer, c1


def test_session_create_short_duration_beats_outside_window(api):
    """PRD §2.8: tier 10 (business constraints) names `ERR_SESSION_DURATION_INVALID`
    before tier 11 (temporal gates) names `ERR_OUTSIDE_ADMINISTRATION_WINDOW`.

    A 10-minute session on 2026-08-25 (after window end 2026-08-20) violates both;
    the constraint wins.

    Design: Difficulty/priority_pair_validation_conflict/constraint_priority_beats_temporal_on_session_create
    """
    ctx, interviewer, c1 = _build_duration_and_window_conflict_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], interviewer["id"], guide["id"],
                               scheduled_start="2026-08-25T10:00:00Z",
                               scheduled_end="2026-08-25T10:10:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_DURATION_INVALID)


def test_session_create_outside_window_alone_reports_temporal(api):
    """PRD §3.6: "then the temporal gate — the session must fit inside the closed
    administration window, `scheduled_start` no earlier than `administration_window_start`
    and `scheduled_end` no later than `administration_window_end`, else
    `ERR_OUTSIDE_ADMINISTRATION_WINDOW`".

    A 60-minute session (valid duration) on 2026-08-25 hits only the temporal gate.

    Design: Difficulty/priority_pair_validation_conflict/constraint_priority_beats_temporal_on_session_create
    """
    ctx, interviewer, c1 = _build_duration_and_window_conflict_setup()
    cycle = ctx["cycle"]
    guide = ctx["guide"]
    resp = api.create_session(
        cycle["id"],
        create_session_payload(c1["id"], interviewer["id"], guide["id"],
                               scheduled_start="2026-08-25T10:00:00Z",
                               scheduled_end="2026-08-25T11:00:00Z"),
        HM,
    )
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_ADMINISTRATION_WINDOW)
