"""Integrity scoring under the two monitoring regimes, and proctor load arithmetic.

Covers LIVE vs RECORD_REVIEW integrity scoring (PRD §2.6), proctor load on
admission vs after termination (PRD §2.7), the exact-50 auto-void boundary (PRD
§3.5), and weighted-load conservation across admission and void.
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    make_proctor_headers,
    make_candidate_headers,
    create_active_session,
    setup_catalog,
    create_appointment,
    set_clock,
    raise_flag,
    get_session,
    create_proctor,
    create_candidate,
    create_exam,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_integrity_score_live_minor_plus_major_is_80(api):
    """PRD §2.6: "Severity drives the base weight: a `MINOR` flag is worth 5 penalty
    points, a `MAJOR` flag 15, and a `CRITICAL` flag 40." PRD §2.6: "under `LIVE`
    monitoring every severity keeps its full weight." PRD §2.6: "The total penalty is
    summed first across all counting flags, then subtracted from 100".

    Design: Difficulty/dual_variant_calc/integrity_score_live_vs_record_review_diverge
    """
    ctx = create_active_session(monitoring_mode="LIVE",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "GAZE_OFF_SCREEN", "MINOR")
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "SECOND_FACE", "MAJOR")
    session = get_session(ctx["session"]["id"], ctx["proctor"]["id"])
    assert session["integrity_score"] == 80.00, (
        f"LIVE 1 MINOR + 1 MAJOR -> 100-(5+15)=80.00, got {session['integrity_score']}")


def test_integrity_score_record_review_halves_minor_to_82_50(api):
    """PRD §2.6: "Under `RECORD_REVIEW` monitoring, and only under that mode, the weight
    of a `MINOR` flag is halved to 2.5; `MAJOR` and `CRITICAL` weights are never
    adjusted". PRD §2.6: "The total penalty is summed first across all counting flags,
    then subtracted from 100".

    Design: Difficulty/dual_variant_calc/integrity_score_live_vs_record_review_diverge
    """
    ctx = create_active_session(monitoring_mode="RECORD_REVIEW",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "GAZE_OFF_SCREEN", "MINOR")
    raise_flag(ctx["session"]["id"], ctx["proctor"]["id"], "SECOND_FACE", "MAJOR")
    session = get_session(ctx["session"]["id"], ctx["proctor"]["id"])
    assert session["integrity_score"] == 82.50, (
        f"RECORD_REVIEW 1 MINOR(2.5) + 1 MAJOR(15) -> 100-17.5=82.50, "
        f"got {session['integrity_score']}")


def test_load_factor_admission_counts_prospective_session(api):
    """PRD §2.7: "each of the proctor's `ACTIVE` or `PAUSED` sessions contributes
    according to its monitoring mode — a `LIVE` session weighs 1.0 and a
    `RECORD_REVIEW` session weighs 0.4 — and the sum of those weights is divided by the
    proctor's `concurrent_capacity`." PRD §2.7: "The resulting `load_factor` is rounded
    to four decimal places using round-half-up."

    Design: Difficulty/dual_variant_calc/proctor_load_factor_admission_vs_snapshot_diverge
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=4,
                        lockdown_required=False)
    inst, proctor, exam = cat["institution"], cat["proctor"], cat["exam"]
    c1 = cat["candidate"]
    c2 = create_candidate(inst["id"])

    set_clock("2026-07-01T09:00:00Z")
    appt1 = create_appointment(exam["id"], c1["id"], proctor["id"], "2026-07-01T09:00:00Z")
    validate_success(api.check_in(appt1["id"], make_candidate_headers(c1["id"])), 201)
    appt2 = create_appointment(exam["id"], c2["id"], proctor["id"], "2026-07-01T11:00:00Z")
    set_clock("2026-07-01T11:00:00Z")
    validate_success(api.check_in(appt2["id"], make_candidate_headers(c2["id"])), 201)

    proc_view = validate_success(api.get_proctor(proctor["id"], COORD), 200)
    assert proc_view["load_factor"] == 0.5000, (
        f"two LIVE sessions weighted 2.0 / cap 4 = 0.5000, got {proc_view['load_factor']}")
    assert proc_view["active_session_count"] == 2


def test_load_factor_snapshot_excludes_completed_session(api):
    """PRD §2.7: "After a session terminates, the denormalized `load_factor` and
    `active_session_count` reflect only the sessions still counted, excluding the one
    that just ended." PRD §3.4: "Completion freezes the final `integrity_score`, drives
    the underlying appointment to `CONSUMED`, and recomputes the proctor's
    `active_session_count` and `load_factor` to drop the now-terminal session."

    Design: Difficulty/dual_variant_calc/proctor_load_factor_admission_vs_snapshot_diverge
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=4,
                        lockdown_required=False)
    inst, proctor, exam = cat["institution"], cat["proctor"], cat["exam"]
    c1 = cat["candidate"]
    c2 = create_candidate(inst["id"])

    set_clock("2026-07-01T09:00:00Z")
    appt1 = create_appointment(exam["id"], c1["id"], proctor["id"], "2026-07-01T09:00:00Z")
    sess1 = validate_success(api.check_in(appt1["id"], make_candidate_headers(c1["id"])), 201)
    appt2 = create_appointment(exam["id"], c2["id"], proctor["id"], "2026-07-01T11:00:00Z")
    set_clock("2026-07-01T11:00:00Z")
    validate_success(api.check_in(appt2["id"], make_candidate_headers(c2["id"])), 201)

    validate_success(api.complete_session(sess1["id"], make_proctor_headers(proctor["id"])), 200)

    proc_view = validate_success(api.get_proctor(proctor["id"], COORD), 200)
    assert proc_view["load_factor"] == 0.2500, (
        f"one remaining LIVE session 1.0 / cap 4 = 0.2500, got {proc_view['load_factor']}")
    assert proc_view["active_session_count"] == 1


def test_integrity_score_exactly_50_does_not_auto_void(api):
    """PRD §3.5: "A score of exactly 50 does not trigger this auto-void; only a score
    strictly less than 50 does." PRD §2.6: "Severity drives the base weight: a `MINOR`
    flag is worth 5 penalty points, a `MAJOR` flag 15, and a `CRITICAL` flag 40."

    Design: Difficulty/boundary_precision_check/integrity_score_exactly_50_does_not_void
    """
    ctx = create_active_session(monitoring_mode="LIVE",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    sid, pid = ctx["session"]["id"], ctx["proctor"]["id"]
    raise_flag(sid, pid, "PROHIBITED_MATERIAL", "CRITICAL")   # penalty 40 -> 60
    raise_flag(sid, pid, "GAZE_OFF_SCREEN", "MINOR")          # +5 -> 55
    raise_flag(sid, pid, "GAZE_OFF_SCREEN", "MINOR")          # +5 -> exactly 50
    session = get_session(sid, pid)
    assert session["integrity_score"] == 50.00, (
        f"CRITICAL+2 MINOR -> 100-50=50.00, got {session['integrity_score']}")
    assert session["status"] == "ACTIVE", (
        f"score exactly 50 is not < 50, so no auto-void; got {session['status']}")


def test_integrity_score_just_below_50_does_auto_void(api):
    """PRD §3.5: "If, after a flag is raised, the recomputed `integrity_score` falls
    strictly below 50, the session is automatically voided". PRD §3.5: "A score of
    exactly 50 does not trigger this auto-void; only a score strictly less than 50 does."

    Design: Difficulty/boundary_precision_check/integrity_score_exactly_50_does_not_void
    """
    ctx = create_active_session(monitoring_mode="LIVE",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    sid, pid = ctx["session"]["id"], ctx["proctor"]["id"]
    raise_flag(sid, pid, "PROHIBITED_MATERIAL", "CRITICAL")   # 40 -> 60
    raise_flag(sid, pid, "GAZE_OFF_SCREEN", "MINOR")          # +5 -> 55
    raise_flag(sid, pid, "GAZE_OFF_SCREEN", "MINOR")          # +5 -> 50
    raise_flag(sid, pid, "GAZE_OFF_SCREEN", "MINOR")          # +5 -> 45 (< 50)
    session = get_session(sid, pid)
    assert session["integrity_score"] == 45.00, (
        f"CRITICAL+3 MINOR -> 100-55=45.00, got {session['integrity_score']}")
    assert session["status"] == "VOIDED", "45 < 50 triggers auto-void"


def test_void_recompute_restores_proctor_load_to_pre_admission(api):
    """PRD §2.7: "After a session terminates, the denormalized `load_factor` and
    `active_session_count` reflect only the sessions still counted, excluding the one
    that just ended." PRD §3.5: "the session moves from `ACTIVE` or `PAUSED` to
    `VOIDED`, the underlying appointment is driven to `CONSUMED`, every still-`OPEN`
    incident flag on the session is resolved to `RESOLVED`, and the proctor's
    `active_session_count` and `load_factor` are recomputed to drop the session."

    Design: Difficulty/compensating_invariant/void_recompute_conserves_proctor_weighted_load
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=4,
                        lockdown_required=False)
    inst, proctor, exam = cat["institution"], cat["proctor"], cat["exam"]
    c1 = cat["candidate"]
    c2 = create_candidate(inst["id"])

    set_clock("2026-07-01T09:00:00Z")
    appt1 = create_appointment(exam["id"], c1["id"], proctor["id"], "2026-07-01T09:00:00Z")
    validate_success(api.check_in(appt1["id"], make_candidate_headers(c1["id"])), 201)
    appt2 = create_appointment(exam["id"], c2["id"], proctor["id"], "2026-07-01T11:00:00Z")
    set_clock("2026-07-01T11:00:00Z")
    sess2 = validate_success(api.check_in(appt2["id"], make_candidate_headers(c2["id"])), 201)

    raise_flag(sess2["id"], proctor["id"], "PROHIBITED_MATERIAL", "CRITICAL")  # 60
    raise_flag(sess2["id"], proctor["id"], "SECOND_FACE", "MAJOR")             # 45 -> void

    sess2_after = get_session(sess2["id"], proctor["id"])
    assert sess2_after["status"] == "VOIDED", "penalty 55 -> score 45 < 50 auto-voids"

    proc_view = validate_success(api.get_proctor(proctor["id"], COORD), 200)
    assert proc_view["load_factor"] == 0.2500, (
        f"load restored to pre-admission 0.2500 (only sess1 counted), "
        f"got {proc_view['load_factor']}")
    assert proc_view["active_session_count"] == 1


def test_forward_admission_raises_proctor_load_to_0_5000(api):
    """PRD §2.7: "each of the proctor's `ACTIVE` or `PAUSED` sessions contributes
    according to its monitoring mode — a `LIVE` session weighs 1.0 ... and the sum of
    those weights is divided by the proctor's `concurrent_capacity`." PRD §3.3: "On a
    successful admission the proctor's `active_session_count` and `load_factor` are
    recomputed to include the new session."

    Design: Difficulty/compensating_invariant/void_recompute_conserves_proctor_weighted_load
    """
    cat = setup_catalog(monitoring_mode="LIVE", concurrent_capacity=4,
                        lockdown_required=False)
    inst, proctor, exam = cat["institution"], cat["proctor"], cat["exam"]
    c1 = cat["candidate"]
    c2 = create_candidate(inst["id"])

    set_clock("2026-07-01T09:00:00Z")
    appt1 = create_appointment(exam["id"], c1["id"], proctor["id"], "2026-07-01T09:00:00Z")
    validate_success(api.check_in(appt1["id"], make_candidate_headers(c1["id"])), 201)
    proc_one = validate_success(api.get_proctor(proctor["id"], COORD), 200)
    assert proc_one["load_factor"] == 0.2500, "one LIVE session 1.0 / cap 4 = 0.2500"

    appt2 = create_appointment(exam["id"], c2["id"], proctor["id"], "2026-07-01T11:00:00Z")
    set_clock("2026-07-01T11:00:00Z")
    validate_success(api.check_in(appt2["id"], make_candidate_headers(c2["id"])), 201)
    proc_two = validate_success(api.get_proctor(proctor["id"], COORD), 200)
    assert proc_two["load_factor"] == 0.5000, (
        f"forward action admits a 1.0 LIVE session -> 2.0 / 4 = 0.5000, "
        f"got {proc_two['load_factor']}")
    assert proc_two["active_session_count"] == 2
