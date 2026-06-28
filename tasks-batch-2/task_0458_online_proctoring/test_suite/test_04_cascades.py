"""Multi-hop cascades and conserved-quantity invariants.

Covers the uphold cascade (session void -> appointment consumed -> proctor load
recompute, PRD §3.6 / §2.7), the auto-void-on-flag cascade (PRD §3.5), and
integrity-score restoration when an escalation is dismissed (PRD §3.6 / §2.6).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_paginated,
    api_client,
    make_proctor_headers,
    make_review_officer_headers,
    setup_under_review_escalation,
    create_active_session,
    create_decide_payload,
    raise_flag,
    get_session,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _flag_status(api, session_id, flag_id, proctor_id):
    flags, _ = validate_paginated(
        api.list_flags(session_id, make_proctor_headers(proctor_id)))
    match = [f for f in flags if f["id"] == flag_id]
    assert match, f"flag {flag_id} not found in session flag list"
    return match[0]["status"]


def test_uphold_cascade_voids_consumes_and_zeroes_proctor_load(api):
    """PRD §3.6: "drives the held session from `REVIEW_HELD` to `VOIDED` with a
    `void_reason` of `ESCALATION_UPHELD`; the underlying appointment is driven to
    `CONSUMED`, the triggering incident flag is resolved to `RESOLVED`, and the
    proctor's `active_session_count` and `load_factor` are recomputed." PRD §2.7:
    "After a session terminates, the denormalized `load_factor` and
    `active_session_count` reflect only the sessions still counted, excluding the one
    that just ended."

    Design: Difficulty/transitive_cascade/uphold_voids_session_consumes_appointment_recomputes_proctor_load
    """
    ctx = setup_under_review_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    res = api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("UPHELD", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"]))
    validate_success(res, 200)

    session = get_session(ctx["session"]["id"], ctx["opener"]["id"])
    assert session["status"] == "VOIDED", "hop 1->2: session voided"
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], COORD), 200)
    assert appt["status"] == "CONSUMED", "hop 2->3: appointment consumed"
    proc = validate_success(api.get_proctor(ctx["opener"]["id"], COORD), 200)
    assert proc["load_factor"] == 0.0000, (
        f"hop 3 recompute: voided session no longer counted -> 0.0000, "
        f"got {proc['load_factor']}")


def test_uphold_cascade_resolves_triggering_flag(api):
    """PRD §3.6: "the underlying appointment is driven to `CONSUMED`, the triggering
    incident flag is resolved to `RESOLVED`, and the proctor's `active_session_count` and
    `load_factor` are recomputed."

    Design: Difficulty/transitive_cascade/uphold_voids_session_consumes_appointment_recomputes_proctor_load
    """
    ctx = setup_under_review_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    validate_success(api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("UPHELD", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"])), 200)
    assert _flag_status(api, ctx["session"]["id"], ctx["flag"]["id"], ctx["opener"]["id"]) == "RESOLVED"


def test_auto_void_on_flag_consumes_appointment(api):
    """PRD §3.5: "If, after a flag is raised, the recomputed `integrity_score` falls
    strictly below 50, the session is automatically voided: its `void_reason` is set to
    `AUTO_THRESHOLD`, the session moves from `ACTIVE` or `PAUSED` to `VOIDED`, the
    underlying appointment is driven to `CONSUMED`, every still-`OPEN` incident flag on
    the session is resolved to `RESOLVED`, and the proctor's `active_session_count` and
    `load_factor` are recomputed to drop the session."

    Design: Difficulty/transitive_cascade/auto_void_on_flag_consumes_appointment
    """
    ctx = create_active_session(monitoring_mode="LIVE",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    sid, pid = ctx["session"]["id"], ctx["proctor"]["id"]
    raise_flag(sid, pid, "PROHIBITED_MATERIAL", "CRITICAL")  # 40 -> 60
    raise_flag(sid, pid, "SECOND_FACE", "MAJOR")             # +15 -> 45 < 50

    session = get_session(sid, pid)
    assert session["status"] == "VOIDED", "hop 1: penalty 55 -> score 45 < 50 auto-voids"
    assert session["void_reason"] == "AUTO_THRESHOLD"
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], COORD), 200)
    assert appt["status"] == "CONSUMED", "hop 2: appointment consumed"


def test_auto_void_resolves_open_flags(api):
    """PRD §3.5: "the session moves from `ACTIVE` or `PAUSED` to `VOIDED`, the underlying
    appointment is driven to `CONSUMED`, every still-`OPEN` incident flag on the session
    is resolved to `RESOLVED`, and the proctor's `active_session_count` and `load_factor`
    are recomputed to drop the session."

    Design: Difficulty/transitive_cascade/auto_void_on_flag_consumes_appointment
    """
    ctx = create_active_session(monitoring_mode="LIVE",
                                scheduled_start_utc="2026-07-01T09:00:00Z")
    sid, pid = ctx["session"]["id"], ctx["proctor"]["id"]
    f1 = raise_flag(sid, pid, "PROHIBITED_MATERIAL", "CRITICAL")  # 40 -> 60
    f2 = raise_flag(sid, pid, "SECOND_FACE", "MAJOR")             # +15 -> 45 < 50, void

    assert get_session(sid, pid)["status"] == "VOIDED"
    assert _flag_status(api, sid, f1["id"], pid) == "RESOLVED"
    assert _flag_status(api, sid, f2["id"], pid) == "RESOLVED"


def test_dismiss_restores_integrity_score_to_100(api):
    """PRD §3.6: "the triggering incident flag is resolved to `RESOLVED` and the
    session's `integrity_score` is recomputed now that the cleared flag no longer
    counts." PRD §2.6: "a flag that has been `RESOLVED` — including a flag cleared when
    an escalation is dismissed — is excluded from the penalty set."

    Design: Difficulty/compensating_invariant/dismiss_conserves_session_integrity_penalty_set
    """
    ctx = setup_under_review_escalation(flag_kind="GAZE_OFF_SCREEN", flag_severity="MINOR")
    res = api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("DISMISSED", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"]))
    validate_success(res, 200)

    session = get_session(ctx["session"]["id"], ctx["opener"]["id"])
    assert session["integrity_score"] == 100.00, (
        f"single MINOR penalty fully reversed on dismiss -> 100.00, "
        f"got {session['integrity_score']}")
    assert session["status"] == "ACTIVE"


def test_dismiss_resolves_triggering_flag(api):
    """PRD §3.6: "the triggering incident flag is resolved to `RESOLVED` and the
    session's `integrity_score` is recomputed now that the cleared flag no longer
    counts."

    Design: Difficulty/compensating_invariant/dismiss_conserves_session_integrity_penalty_set
    """
    ctx = setup_under_review_escalation(flag_kind="GAZE_OFF_SCREEN", flag_severity="MINOR")
    validate_success(api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("DISMISSED", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"])), 200)
    assert _flag_status(api, ctx["session"]["id"], ctx["flag"]["id"], ctx["opener"]["id"]) == "RESOLVED"
