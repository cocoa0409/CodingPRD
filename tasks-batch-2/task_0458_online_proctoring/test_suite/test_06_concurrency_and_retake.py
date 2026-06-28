"""OCC stale-version guards, the retake/rebook workflow, and report-content boundaries.

Covers the two optimistic-concurrency rejections (decide and rebook), immediate
visibility of a rebook supersede, the empty / non-terminal report boundary, and the
retake / cancel error paths.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    make_review_officer_headers,
    setup_session_with_open_escalation,
    setup_authorized_retake,
    create_completed_session,
    create_decide_payload,
    create_rebook_payload,
    create_retake_authorization_payload,
    setup_catalog,
    create_active_session,
    create_appointment,
    set_clock,
    make_candidate_headers,
    make_proctor_headers,
    create_proctor,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


# ─── boundary_precision_check / empty report ──────────

def test_empty_report_session_ids_rejected_at_create(api):
    """PRD §3.7: "a report whose `session_ids` is empty, or that names a session which
    is not terminal, is rejected with `ERR_EMPTY_REPORT`."

    Design: Difficulty/boundary_precision_check/empty_report_session_ids_rejected
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    res = api.create_integrity_report(
        {"institution_id": cat["institution"]["id"], "candidate_id": cat["candidate"]["id"],
         "exam_id": cat["exam"]["id"], "session_ids": []}, COORD)
    validate_error(res, "ERR_EMPTY_REPORT")


def test_report_with_non_terminal_session_rejected_empty_report(api):
    """PRD §3.7: "Each included session must be terminal — `COMPLETED` or `VOIDED`".
    PRD §3.7: "a report whose `session_ids` is empty, or that names a session which is
    not terminal, is rejected with `ERR_EMPTY_REPORT`."

    Design: Difficulty/boundary_precision_check/empty_report_session_ids_rejected
    """
    ctx = create_active_session(monitoring_mode="LIVE")  # session still ACTIVE
    res = api.create_integrity_report(
        {"institution_id": ctx["institution"]["id"], "candidate_id": ctx["candidate"]["id"],
         "exam_id": ctx["exam"]["id"], "session_ids": [ctx["session"]["id"]]}, COORD)
    validate_error(res, "ERR_EMPTY_REPORT")


# ─── corner: optimistic concurrency ───────────────────

def test_decide_with_stale_escalation_version_rejected(api):
    """PRD §2.9: "A request to decide an escalation must carry `expected_escalation_version`,
    holding the `version` of the `Escalation` the review officer last observed. If the
    escalation's current `version` has advanced beyond that value — for instance because
    the claim step or a sibling write already bumped it since the officer read it — the
    decision is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_decide_stale_escalation_version_rejected
    """
    ctx = setup_session_with_open_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    pre_claim_version = ctx["escalation"]["version"]
    # claim bumps the version past the pre-claim value
    validate_success(api.claim_escalation(
        ctx["escalation"]["id"], make_review_officer_headers(ctx["officer"]["id"])), 200)
    res = api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("UPHELD", pre_claim_version),
        make_review_officer_headers(ctx["officer"]["id"]))
    validate_error(res, "ERR_STALE_VERSION")


def test_rebook_with_stale_appointment_version_rejected(api):
    """PRD §2.9: "A rebook request must carry `expected_appointment_version`, holding the
    `version` of the original (consumed) appointment the coordinator last observed. If
    that original appointment's current `version` has advanced ... the rebook is rejected
    with `ERR_STALE_VERSION` (HTTP 412)". PRD §3.8: "the supplied
    `expected_appointment_version` must match the original appointment's current
    `version`; if an earlier rebook already advanced that version, the request is
    rejected with `ERR_STALE_VERSION` so no duplicate replacement is created."

    Design: Corner/cross_cutting_complexity_layers/occ_rebook_supersede_stale_appointment_rejected
    """
    ctx = setup_authorized_retake(scheduled_start_utc="2026-07-01T09:00:00Z")
    stale_version = ctx["original_version"] - 1
    res = api.rebook_retake(
        ctx["retake"]["id"],
        create_rebook_payload(ctx["opener"]["id"], "2026-07-01T14:00:00Z", stale_version),
        COORD)
    validate_error(res, "ERR_STALE_VERSION")


# ─── corner: consistency model (immediate visibility) ─

def test_rebook_supersedes_original_immediately(api):
    """PRD §3.8: "A successful rebook creates a brand-new replacement `Appointment` in
    `SCHEDULED` status for the same exam and candidate ... It then sets the original
    appointment's `superseded_by_id` to the replacement's id and increments the original
    appointment's `version` by 1 while leaving its status `CONSUMED` (the original
    already ran and was voided). Finally the retake moves from `AUTHORIZED` to `REBOOKED`
    and its `replacement_appointment_id` is set to the new appointment."

    Design: Corner/consistency_model/rebook_supersede_immediate_visibility
    """
    ctx = setup_authorized_retake(scheduled_start_utc="2026-07-01T09:00:00Z")
    replacement = validate_success(api.rebook_retake(
        ctx["retake"]["id"],
        create_rebook_payload(ctx["opener"]["id"], "2026-07-01T14:00:00Z",
                              ctx["original_version"]),
        COORD), 201)

    original = validate_success(api.get_appointment(ctx["appointment"]["id"], COORD), 200)
    assert original["superseded_by_id"] == replacement["id"], "superseded_by_id visible immediately"
    assert original["status"] == "CONSUMED", "original status preserved as CONSUMED"
    retake = validate_success(api.get_retake_authorization(ctx["retake"]["id"], COORD), 200)
    assert retake["status"] == "REBOOKED"


# ─── corner: errors ───────────────────────────────────

def test_retake_for_non_voided_session_rejected(api):
    """PRD §3.8: "the session must actually be `VOIDED`, and an authorization sought for
    a session that is not voided is rejected with `ERR_NOT_VOIDED`."

    Design: Corner/errors/retake_for_non_voided_session_rejected
    """
    ctx = create_completed_session(monitoring_mode="LIVE")  # session COMPLETED, not VOIDED
    officer = create_proctor(ctx["institution"]["id"], full_name="Review Officer")
    res = api.create_retake_authorization(
        create_retake_authorization_payload(ctx["session"]["id"]),
        make_review_officer_headers(officer["id"]))
    validate_error(res, "ERR_NOT_VOIDED")


def test_cancel_with_active_session_rejected(api):
    """PRD §3.3: "Cancellation is refused if a non-terminal session — one that is
    `ACTIVE` or `PAUSED` — still exists for the appointment; such a session must be
    voided first, and the attempt is rejected with `ERR_SESSION_IN_PROGRESS`."

    Design: Corner/errors/cancel_with_active_session_rejected
    """
    ctx = create_active_session(monitoring_mode="LIVE")
    res = api.cancel_appointment(ctx["appointment"]["id"], COORD)
    validate_error(res, "ERR_SESSION_IN_PROGRESS")
