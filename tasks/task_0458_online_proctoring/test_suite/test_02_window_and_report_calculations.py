"""Appointment effective-window arithmetic and integrity-report aggregation.

Covers the ceil-before-setup window computation (PRD §3.2 / §2.8), the
per-session-rounded report aggregate and its disposition (PRD §3.7).
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    make_proctor_headers,
    make_candidate_headers,
    setup_catalog,
    create_accommodation,
    create_appointment,
    set_clock,
    build_terminal_session_with_score,
    deliver_report,
    create_active_session,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_effective_window_ceils_core_before_adding_setup(api):
    """PRD §3.2: "The accommodated core is the base duration multiplied by one plus the
    extra percentage expressed as a fraction (so a 50 percent accommodation multiplies
    the base by 1.5), and that product is rounded up to the next whole minute. A fixed
    setup allowance of 10 minutes is then added to the rounded core to give the
    `effective_duration_minutes`." PRD §2.8: "the ceiling step is applied to the
    accommodated core duration before the fixed setup minutes are added".

    Design: Difficulty/combinatorial_formula/effective_window_ceil_before_setup_add_mode_a
    """
    cat = setup_catalog(base_duration_minutes=90, lockdown_required=False,
                        window_start_utc="2026-07-01T09:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    acc = create_accommodation(cat["candidate"]["id"], cat["exam"]["id"], extra_time_pct=25)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"], cat["proctor"]["id"],
                              "2026-07-01T10:00:00Z", accommodation_id=acc["id"])
    assert appt["effective_duration_minutes"] == 123, (
        f"ceil(90*1.25)=ceil(112.5)=113, +10 setup = 123, "
        f"got {appt['effective_duration_minutes']}")
    assert appt["effective_end_utc"] == "2026-07-01T12:03:00Z", (
        f"10:00 + 123min = 12:03, got {appt['effective_end_utc']}")


def test_effective_window_without_accommodation_adds_only_setup(api):
    """PRD §3.2: "the same base with no accommodation yields 120 plus setup, for 130
    minutes." PRD §3.2: "If an accommodation is supplied and that accommodation's status
    is `APPROVED`, the accommodation's `extra_time_pct` is applied; otherwise — when no
    accommodation is named, or the named one has been revoked — the extra percentage is
    treated as 0."

    Design: Difficulty/combinatorial_formula/effective_window_ceil_before_setup_add_mode_a
    """
    cat = setup_catalog(base_duration_minutes=120, lockdown_required=False,
                        window_start_utc="2026-07-01T09:00:00Z",
                        window_end_utc="2026-07-01T23:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"], cat["proctor"]["id"],
                              "2026-07-01T10:00:00Z")
    assert appt["effective_duration_minutes"] == 130, (
        f"120 base + 10 setup = 130, got {appt['effective_duration_minutes']}")


def test_report_aggregate_rounds_each_session_before_mean(api):
    """PRD §3.7: "each session's `integrity_score` is first rounded to the nearest whole
    number using round-half-up, then the arithmetic mean of those per-session rounded
    values is taken, and that mean is finally rounded to two decimal places using
    round-half-up. This per-session-rounding order is the production rule — for example,
    session scores of 80.0, 82.5, and 60.0 round to 80, 83, and 60, whose mean is
    74.33." PRD §3.7: "the disposition is `CLEARED` when the aggregate is greater than
    or equal to the institution's `report_threshold_score`, and
    `ESCALATED_TO_INSTITUTION` otherwise".

    Design: Difficulty/combinatorial_formula/report_aggregate_per_session_round_before_mean_mode_b
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False,
                        report_threshold_score=80)
    inst, proctor, cand = cat["institution"], cat["proctor"], cat["candidate"]
    from test_helpers import create_exam
    exam_live = cat["exam"]
    exam_rev = create_exam(inst["id"], monitoring_mode="RECORD_REVIEW",
                           window_start_utc="2026-07-01T09:00:00Z",
                           window_end_utc="2026-07-01T23:00:00Z")

    # Session A: LIVE, 1 MINOR + 1 MAJOR -> 80.00
    _, sess_a = build_terminal_session_with_score(
        inst["id"], exam_live["id"], cand["id"], proctor["id"],
        [("GAZE_OFF_SCREEN", "MINOR"), ("SECOND_FACE", "MAJOR")],
        "2026-07-01T09:00:00Z")
    # Session B: RECORD_REVIEW, 1 MINOR(2.5) + 1 MAJOR -> 82.50
    _, sess_b = build_terminal_session_with_score(
        inst["id"], exam_rev["id"], cand["id"], proctor["id"],
        [("GAZE_OFF_SCREEN", "MINOR"), ("SECOND_FACE", "MAJOR")],
        "2026-07-01T11:00:00Z")
    # Session C: LIVE, 1 CRITICAL -> 60.00
    _, sess_c = build_terminal_session_with_score(
        inst["id"], exam_live["id"], cand["id"], proctor["id"],
        [("PROHIBITED_MATERIAL", "CRITICAL")],
        "2026-07-01T13:00:00Z")

    report = deliver_report(inst["id"], cand["id"], exam_live["id"],
                            [sess_a["id"], sess_b["id"], sess_c["id"]])
    assert report["aggregate_score"] == 74.33, (
        f"[80,83,60] mean = 74.33 under PER_SESSION_ROUND, "
        f"got {report['aggregate_score']}")
    assert report["disposition"] == "ESCALATED_TO_INSTITUTION", (
        "74.33 < threshold 80 -> ESCALATED_TO_INSTITUTION")
    assert report["status"] == "DELIVERED"


def test_report_per_session_round_half_up_at_point_five(api):
    """PRD §3.7: "each session's `integrity_score` is first rounded to the nearest whole
    number using round-half-up, then the arithmetic mean of those per-session rounded
    values is taken, and that mean is finally rounded to two decimal places using
    round-half-up."

    Design: Difficulty/combinatorial_formula/report_aggregate_per_session_round_before_mean_mode_b
    """
    cat = setup_catalog(monitoring_mode="RECORD_REVIEW", lockdown_required=False)
    inst, proctor, cand, exam = (cat["institution"], cat["proctor"],
                                 cat["candidate"], cat["exam"])
    # RECORD_REVIEW: 1 MINOR (2.5) + 1 MAJOR (15) -> score 82.50.
    # Per-session round-half-up of 82.50 -> 83; single-session mean -> 83.00.
    _, sess = build_terminal_session_with_score(
        inst["id"], exam["id"], cand["id"], proctor["id"],
        [("GAZE_OFF_SCREEN", "MINOR"), ("SECOND_FACE", "MAJOR")],
        "2026-07-01T09:00:00Z")
    assert sess["integrity_score"] == 82.50
    report = deliver_report(inst["id"], cand["id"], exam["id"], [sess["id"]])
    assert report["aggregate_score"] == 83.00, (
        f"82.50 rounds half-up to 83 per session, mean 83.00, "
        f"got {report['aggregate_score']}")


def test_report_clean_session_clears_at_default_threshold(api):
    """PRD §3.7: "the disposition is `CLEARED` when the aggregate is greater than or
    equal to the institution's `report_threshold_score`". PRD §3.1: "that threshold
    defaults to 70". PRD §2.6: "A session's `integrity_score` begins conceptually at
    100".

    Design: Corner/state_machines/cleared_report_disposition_when_above_threshold
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    inst, proctor, cand, exam = (cat["institution"], cat["proctor"],
                                 cat["candidate"], cat["exam"])
    _, sess = build_terminal_session_with_score(
        inst["id"], exam["id"], cand["id"], proctor["id"], [],
        "2026-07-01T09:00:00Z")
    report = deliver_report(inst["id"], cand["id"], exam["id"], [sess["id"]])
    assert report["aggregate_score"] == 100.00, (
        f"single clean session score 100 -> aggregate 100.00, "
        f"got {report['aggregate_score']}")
    assert report["disposition"] == "CLEARED", "100 >= default threshold 70 -> CLEARED"
