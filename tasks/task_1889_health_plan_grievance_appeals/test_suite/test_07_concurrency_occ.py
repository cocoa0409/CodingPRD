"""Corner queue: cross-cutting OCC, version increments, and the
decision-notification cascade (PRD §2.5, §2.7, §3.3, §3.5, §3.9).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    CLOCK_DEFAULT_ISO,
    TEST_USERS,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, get_case_effectuation,
    start_effectuation, get_effectuation_fresh, create_notification_payload,
    ALL_DECISION_ELEMENTS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def _setup_triaged_appeal_with_extension_policy():
    member = create_member("MBR-CC1", full_name="Occ Test", program="MEDICARE")
    provider = create_provider("7766554433", legal_name="Occ Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=24, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    return triage_case(case["id"])


def test_extension_with_stale_case_version_rejected(api):
    """PRD §2.7: "Applying the single member-requested extension to a case requires the
    request to carry `expected_case_version` equal to the case's current
    `version`."
    If another writer has advanced the case's version since the client last
    read it, the extension is rejected with ERR_STALE_VERSION (HTTP 412)
    per PRD §2.7.

    Design: Corner/cross_cutting/occ_stale_version_rejected
    """
    triaged = _setup_triaged_appeal_with_extension_policy()
    stale_version = triaged["version"]
    # An event append advances the case version past the client's view.
    get_success_data(api.append_case_event(
        triaged["id"], {"event_type": "NOTE", "body": "bumps version"},
        ANALYST), expected_status=201)
    validate_error(
        api.extend_case(triaged["id"],
                        {"expected_case_version": stale_version}, MSR),
        ApiErrorId.ERR_STALE_VERSION)


def test_extension_with_fresh_version_succeeds(api):
    """PRD §2.7: "Applying the single member-requested extension to a case requires the
    request to carry `expected_case_version` equal to the case's current
    `version`."
PRD §3.3: "Granting sets `extension_applied` to `true`, recomputes
    `resolution_due_at` as the previously computed deadline plus the
    policy's extension hours, appends an `EXTENSION_GRANTED` event, and
    increments the case's `version`."

    Design: Corner/cross_cutting/occ_stale_version_rejected
    """
    triaged = _setup_triaged_appeal_with_extension_policy()
    get_success_data(api.append_case_event(
        triaged["id"], {"event_type": "NOTE", "body": "bumps version"},
        ANALYST), expected_status=201)
    fresh = get_success_data(api.get_case(triaged["id"], MSR))
    data = validate_success(api.extend_case(
        triaged["id"], {"expected_case_version": fresh["version"]}, MSR))
    assert data["extension_applied"] is True


def _setup_in_progress_effectuation():
    """GRIEVANCE decided FULLY_FAVORABLE (payment 100); effectuation started.
    Returns (case, effectuation_id, stale_version_captured_before_start)."""
    member = create_member("MBR-CC2", full_name="Occ Eff", program="MEDICARE")
    provider = create_provider("6655443322", legal_name="OccEff Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE",
                              provider_id=provider["id"])["id"],
        decision_outcome="FULLY_FAVORABLE", payment_amount_cents=100)
    eff = get_case_effectuation(case["id"])
    stale_version = eff["version"]
    start_effectuation(eff["id"])
    return case, eff["id"], stale_version


def test_effectuation_complete_with_stale_version_rejected(api):
    """PRD §2.7: "Completing an effectuation requires the request to carry
    `expected_effectuation_version` equal to the effectuation's current
    `version`."
    A stale completion is rejected with ERR_STALE_VERSION (HTTP 412) per PRD
    §2.7.

    Design: Corner/cross_cutting/occ_effectuation_complete_stale_version
    """
    _case, eff_id, stale_version = _setup_in_progress_effectuation()
    # start bumped the version after the client captured it.
    validate_error(
        api.complete_effectuation(
            eff_id, {"expected_effectuation_version": stale_version}, CLAIMS),
        ApiErrorId.ERR_STALE_VERSION)
    after = get_success_data(api.get_effectuation(eff_id, CLAIMS))
    assert after["status"] == "IN_PROGRESS"


def test_effectuation_complete_with_fresh_version_succeeds(api):
    """PRD §3.7: "Completing stamps `completed_at`, computes `timeliness_percent`, appends
    an `EFFECTUATION_COMPLETED` event on the parent case, and — when the
    effectuation's `referral_id` is set — fires the linked referral's
    auto-transition to `EFFECTUATED`."

    Design: Corner/cross_cutting/occ_effectuation_complete_stale_version
    """
    _case, eff_id, _stale = _setup_in_progress_effectuation()
    fresh = get_effectuation_fresh(eff_id)
    data = validate_success(api.complete_effectuation(
        eff_id, {"expected_effectuation_version": fresh["version"]}, CLAIMS))
    assert data["status"] == "EFFECTUATED"
    assert data["completed_at"] is not None


def test_case_version_increments_on_every_mutation(api):
    """PRD §2.5: "**`version` (integer):** A system-managed integer that increments with
    every modification to the resource — including appends to its event
    log and automatic state reconciliations — and serves as the basis for
    optimistic concurrency control where §2.7 applies."
PRD §3.3: "The server stamps `acknowledged_at`, computes `resolution_due_at`, appends
    a `NOTE` event whose `body` reads `TRIAGED`, and increments the case's
    `version`."
PRD §3.3: "A `PRIORITY_UPGRADE` event is appended and the case's `version`
    increments."
PRD §3.9: "Staff in the `IntakeSpecialist`, `CaseAnalyst`, `MemberServicesRep`, and
    `ComplianceOfficer` roles may append events with an `event_type` of
    `NOTE`, `DOCUMENT`, `EXTENSION_REQUEST`, `CTM_LINKED`, or
    `CTM_UNLINKED` and an optional free-text `body`; the server stamps
    `occurred_at` and captures `actor_role` and `actor_id` from the
    request headers at append time, and every append increments the parent
    case's `version` by one."

    Design: Corner/cross_cutting/version_increments_on_every_mutation
    """
    member = create_member("MBR-CC3", full_name="Ver Count", program="MEDICARE")
    provider = create_provider("5544332211", legal_name="Ver Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    create_policy("MEDICARE", "APPEAL", "EXPEDITED", resolution_hours=72,
                  extension_hours=0, effectuation_hours=24)
    set_clock(CLOCK_DEFAULT_ISO)
    case = intake_case(member["id"], case_kind="APPEAL",
                       provider_id=provider["id"])
    assert case["version"] == 1
    v0 = case["version"]
    triage_case(case["id"])                                             # +1
    get_success_data(api.append_case_event(
        case["id"], {"event_type": "NOTE", "body": "n1"}, ANALYST),
        expected_status=201)                                            # +1
    validate_success(api.expedite_case(case["id"], MD))                 # +1
    final = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert final["version"] == v0 + 3, (
        f"triage + event append + expedite = three increments from {v0}; "
        f"got {final['version']}")


def test_decision_notification_cascade_is_member_scoped(api):
    """PRD §3.5: "The transition with regulatory teeth is the member's decision letter: when
    the `DECISION` notification addressed to the `MEMBER` reaches `SENT`,
    the parent case auto-transitions `DECIDED` → `NOTIFIED`, the case's
    `notified_at` takes the notification's `sent_at`, a
    `NOTIFICATION_SENT` event is appended, and the case's `version`
    increments."

    Design: Corner/cross_cutting/decision_notification_cascade_fires_once
    """
    member = create_member("MBR-CC4", full_name="Cascade Once",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = decide_grievance_from_in_review(
        create_in_review_case(member["id"], case_kind="GRIEVANCE")["id"],
        decision_outcome="UNFAVORABLE")
    provider_notice = get_success_data(api.create_notification(
        case["id"],
        create_notification_payload(recipient_kind="PROVIDER",
                                    notification_kind="DECISION"),
        MSR), expected_status=201)
    member_notice = get_success_data(api.create_notification(
        case["id"],
        create_notification_payload(recipient_kind="MEMBER",
                                    notification_kind="DECISION"),
        MSR), expected_status=201)
    # Sending the PROVIDER decision notice must not move the case.
    validate_success(api.mark_notification_sent(provider_notice["id"], MSR))
    after_provider = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after_provider["status"] == "DECIDED"
    # The MEMBER decision notice drives DECIDED -> NOTIFIED.
    sent_member = validate_success(
        api.mark_notification_sent(member_notice["id"], MSR))
    after_member = get_success_data(api.get_case(case["id"], COMPLIANCE))
    assert after_member["status"] == "NOTIFIED"
    assert after_member["notified_at"] == sent_member["sent_at"]
