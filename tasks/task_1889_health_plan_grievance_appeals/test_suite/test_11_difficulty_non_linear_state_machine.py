"""Difficulty queue: non-linear state machines (PRD §3.5, §3.8).

Cyclic and self-loop shapes: the case CLOSED -> REOPENED -> CLOSED cycle, the
notification SENT -> FAILED -> RETRIED -> SENT loop, and guarded expedite
self-transitions.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    assert_same_instant, api_client,
    TEST_USERS, make_intake_specialist_headers, make_medical_director_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, create_and_send_decision_notification,
    setup_closed_case, setup_closed_case_with_reopening_under_review,
    create_and_review_reopening, setup_notified_case,
    create_notification_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_reopening_under_review():
    member = create_member("MBR-NL1", full_name="Quinn Hale", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    closed, reopening = setup_closed_case_with_reopening_under_review(
        member["id"], request_reason="NEW_EVIDENCE")
    return member, closed, reopening


def test_reopen_grant_flips_source_and_spawns_replacement(api):
    """PRD §3.8: "On grant, the reopening's `decided_at` is stamped and its
    `spawned_case_id` is set to a newly created case — status `RECEIVED`,
    `reopened_from_case_id` pointing at the source case, `case_kind` and
    `priority_track` copied from it — while the source case
    auto-transitions `CLOSED` → `REOPENED` as a marker, the member's
    `open_case_count` increments by one for the spawned case, any
    `DETERMINED` clinical review on the source case transitions to
    `SUPERSEDED`, and a `REOPEN_GRANTED` event is appended on the source
    case."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_closed_to_reopened_to_closed
    """
    member, closed, reopening = _setup_reopening_under_review()
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    data = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    assert data["status"] == "GRANTED"
    spawned_id = data["spawned_case_id"]
    assert spawned_id, "grant must set spawned_case_id"
    source = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    assert source["status"] == "REOPENED"
    spawned = get_success_data(api.get_case(spawned_id, COMPLIANCE))
    assert spawned["status"] == "RECEIVED"
    assert spawned["reopened_from_case_id"] == closed["id"]


def test_reopen_cycle_closes_source_when_spawned_case_closes(api):
    """PRD §3.8: "The marker unwinds itself: when the spawned replacement case eventually
    reaches `CLOSED`, the source case auto-transitions `REOPENED` →
    `CLOSED` and its `closed_at` is overwritten with that moment."

    Design: Difficulty/non_linear_state_machine/case_cyclic_reopen_closed_to_reopened_to_closed
    """
    member, closed, reopening = _setup_reopening_under_review()
    fresh = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    granted = validate_success(api.grant_reopening(
        reopening["id"], {"expected_case_version": fresh["version"]},
        COMPLIANCE))
    spawned_id = granted["spawned_case_id"]
    # Walk the spawned GRIEVANCE through its full lifecycle to CLOSED.
    triage_case(spawned_id)
    begin_review(spawned_id)
    decide_grievance_from_in_review(spawned_id, decision_outcome="UNFAVORABLE")
    create_and_send_decision_notification(spawned_id)
    validate_success(api.close_case(spawned_id, COMPLIANCE))
    source = get_success_data(api.get_case(closed["id"], COMPLIANCE))
    assert source["status"] == "CLOSED", (
        f"Source case must return to CLOSED once the spawned case closes; "
        f"got {source['status']}")


def _setup_decided_grievance_with_notification():
    member = create_member("MBR-NL2", full_name="Rosa Iles", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock("2026-08-01T00:00:00Z")
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    case = decide_grievance_from_in_review(case["id"],
                                           decision_outcome="UNFAVORABLE")
    notif = get_success_data(api_client.create_notification(
        case["id"],
        create_notification_payload(recipient_kind="MEMBER",
                                    notification_kind="DECISION"),
        MSR), expected_status=201)
    return case, notif


def test_notification_failed_retried_sent_loop(api):
    """PRD §3.5: "From `SENT`, the notice may be marked `DELIVERED` or may be marked
    `FAILED`; a `FAILED` notice may be retried into `RETRIED`, and a
    retried notice is marked sent into `SENT` again under the same
    completeness gate."

    Design: Difficulty/non_linear_state_machine/notification_failed_retried_sent_delivery_loop
    """
    _case, notif = _setup_decided_grievance_with_notification()
    sent = validate_success(api.mark_notification_sent(notif["id"], MSR))
    assert sent["status"] == "SENT"
    failed = validate_success(api.mark_notification_failed(notif["id"], MSR))
    assert failed["status"] == "FAILED"
    retried = validate_success(api.retry_notification(notif["id"], MSR))
    assert retried["status"] == "RETRIED"
    sent_again = validate_success(api.mark_notification_sent(notif["id"], MSR))
    assert sent_again["status"] == "SENT"


def test_notification_loop_member_cascade_fires_only_from_decided(api):
    """PRD §3.5: "The transition with regulatory teeth is the member's decision letter: when
    the `DECISION` notification addressed to the `MEMBER` reaches `SENT`,
    the parent case auto-transitions `DECIDED` → `NOTIFIED`, the case's
    `notified_at` takes the notification's `sent_at`, a
    `NOTIFICATION_SENT` event is appended, and the case's `version`
    increments."

    Design: Difficulty/non_linear_state_machine/notification_failed_retried_sent_delivery_loop
    """
    case, notif = _setup_decided_grievance_with_notification()
    validate_success(api.mark_notification_sent(notif["id"], MSR))
    after_first = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after_first["status"] == "NOTIFIED"
    notified_at = after_first["notified_at"]
    # Loop the notice through FAILED -> RETRIED -> SENT; the case is already
    # NOTIFIED, so no second DECIDED -> NOTIFIED cascade can fire.
    validate_success(api.mark_notification_failed(notif["id"], MSR))
    validate_success(api.retry_notification(notif["id"], MSR))
    validate_success(api.mark_notification_sent(notif["id"], MSR))
    after_second = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after_second["status"] == "NOTIFIED"
    assert after_second["notified_at"] == notified_at


def test_expedite_self_transition_from_triaged(api):
    """PRD §3.3: "The expedited upgrade, performed by a `MedicalDirector` from `TRIAGED` or
    `IN_REVIEW`, tightens the clock rather than loosening it."
PRD §3.3: "The upgrade sets `priority_track` to `EXPEDITED` and recomputes
    `resolution_due_at` under the expedited policy's smaller
    `resolution_hours` — crucially, the anchor remains the original
    `received_at`, not the moment of the upgrade, so a mid-flight upgrade
    shortens the remaining window rather than restarting it."

    Design: Difficulty/non_linear_state_machine/case_priority_track_self_transition_expedite
    """
    member = create_member("MBR-NL3", full_name="Sam Tyre", program="MEDICARE")
    provider = create_provider("6758493021", legal_name="Tyre Labs",
                               w9_on_file=True)
    create_policy("MEDICARE", "ORG_DETERMINATION", "STANDARD",
                  resolution_hours=336, extension_hours=0,
                  effectuation_hours=72)
    create_policy("MEDICARE", "ORG_DETERMINATION", "EXPEDITED",
                  resolution_hours=72, extension_hours=0,
                  effectuation_hours=24)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="ORG_DETERMINATION",
                       provider_id=provider["id"])
    triage_case(case["id"])
    data = validate_success(api.expedite_case(case["id"], MD))
    assert data["status"] == "TRIAGED", "expedite is a self-transition"
    assert data["priority_track"] == "EXPEDITED"
    assert_same_instant(data["resolution_due_at"], "2026-08-04T00:00:00Z")


def test_expedite_self_transition_from_in_review(api):
    """PRD §3.3: "The expedited upgrade, performed by a `MedicalDirector` from `TRIAGED` or
    `IN_REVIEW`, tightens the clock rather than loosening it."
PRD §3.3: "A `PRIORITY_UPGRADE` event is appended and the case's `version`
    increments."

    Design: Difficulty/non_linear_state_machine/case_priority_track_self_transition_expedite
    """
    member = create_member("MBR-NL3B", full_name="Sam Tyre", program="MEDICARE")
    provider = create_provider("6758493022", legal_name="Tyre Labs B",
                               w9_on_file=True)
    create_policy("MEDICARE", "ORG_DETERMINATION", "STANDARD",
                  resolution_hours=336, extension_hours=0,
                  effectuation_hours=72)
    create_policy("MEDICARE", "ORG_DETERMINATION", "EXPEDITED",
                  resolution_hours=72, extension_hours=0,
                  effectuation_hours=24)
    set_clock("2026-08-01T00:00:00Z")
    case = intake_case(member["id"], case_kind="ORG_DETERMINATION",
                       provider_id=provider["id"])
    triage_case(case["id"])
    begin_review(case["id"])
    data = validate_success(api.expedite_case(case["id"], MD))
    assert data["status"] == "IN_REVIEW", "expedite is a self-transition"
    assert data["priority_track"] == "EXPEDITED"
    # Anchor stays at received_at (2026-08-01T00:00:00Z + 72h).
    assert_same_instant(data["resolution_due_at"], "2026-08-04T00:00:00Z")
