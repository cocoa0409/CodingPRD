"""Validation precedence and cross-entity preconditions.

Three precedence pairs off the hospital-wide ladder of PRD §2.11 — posture state
against tracer occupancy, condition-level safety against submitter ownership,
and evidence state against segregation of duties — plus three preconditions a
write inherits from a *different* entity: a ticket's rounding session, an
evidence item's standard, and a finding's survey window.
"""

from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    assign_owner,
    close_rounding_session,
    create_chapter,
    create_standard,
    create_unit,
    escalate_finding,
    evidence_action,
    file_evidence,
    make_evidence_validator_headers,
    make_standard_owner_headers,
    open_rounding_session,
    raise_deficiency,
    read_chapter,
    read_finding,
    read_standard,
    read_unit,
    schedule_tracer,
    set_clock,
    setup_closed_survey_condition_level_finding,
    setup_eligible_window,
    ticket_action,
    tracer_action,
    validate_error,
    validate_paginated,
    validate_success,
)

NON_OWNER_USER_ID = "owner-9"


# ---------------------------------------------------------------------------
# Private setup chains — every test rebuilds its own world from scratch.
# ---------------------------------------------------------------------------

def _setup_unit_with_in_progress_tracer(restrict: bool):
    """Chapter EC with one mapped standard, unit ICU-4, and tracer T1 running
    IN_PROGRESS over 2026-08-05T08:00:00Z-12:00:00Z at clock 08:00Z.

    When `restrict` is true, three OPEN HIGH tickets worth twenty-one points are
    raised on the unit afterwards, which restricts its posture without leaving
    any ticket in ESCALATED.
    """
    chapter = create_chapter("EC", "Environment of Care", 100, 1)
    standard = create_standard(chapter["id"], "EC.02.06.01", "Safe environment", "DIRECT_IMPACT")
    assign_owner(standard["id"], "owner-1", "PRIMARY")
    unit = create_unit("ICU-4", "ICU", 14)
    tracer = schedule_tracer(
        unit["id"],
        chapter["id"],
        "2026-08-05T08:00:00Z",
        "2026-08-05T12:00:00Z",
        tracer_type="SYSTEM",
        expected_unit_version=unit["version"],
    )
    set_clock("2026-08-05T08:00:00Z")
    tracer = tracer_action(tracer["id"], "START")

    session = None
    if restrict:
        session = open_rounding_session(
            unit["id"], "ENVIRONMENT_OF_CARE", "2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z"
        )
        raise_deficiency(session["id"], standard["id"], "HIGH", "Blocked electrical panel")
        raise_deficiency(session["id"], standard["id"], "HIGH", "Missing eyewash inspection")
        raise_deficiency(
            session["id"], standard["id"], "HIGH", "Damaged ceiling tile above sterile field"
        )

    return {
        "chapter": chapter,
        "standard": standard,
        "unit": read_unit(unit["id"]),
        "tracer": tracer,
        "session": session,
    }


def _setup_owner_validating_own_evidence(submitted: bool):
    """Chapter MM with one standard owned by owner-1 as ACTIVE PRIMARY, carrying
    one evidence item either still in DRAFT or already SUBMITTED."""
    chapter = create_chapter("MM", "Medication Management", 30, 1)
    standard = create_standard(
        chapter["id"], "MM.05.01.01", "Medication order review", "INDIRECT_IMPACT"
    )
    assignment = assign_owner(standard["id"], "owner-1", "PRIMARY")
    evidence = file_evidence(
        standard["id"],
        title="Pharmacy review policy",
        doc_type="POLICY",
        effective_date="2026-07-01T00:00:00Z",
        owner_user_id="owner-1",
    )
    if submitted:
        evidence = evidence_action(
            evidence["id"], "SUBMIT", make_standard_owner_headers("owner-1")
        )
    return {
        "chapter": chapter,
        "standard": standard,
        "assignment": assignment,
        "evidence": evidence,
    }


def _setup_remediated_ticket_in_open_session():
    """Unit ED-4 with one OPEN LIFE_SAFETY session holding one MODERATE ticket
    already moved to REMEDIATED, at clock 2026-08-10T00:00:00Z."""
    chapter = create_chapter("LS", "Life Safety", 25, 1)
    standard = create_standard(
        chapter["id"], "LS.02.01.01", "Sprinkler coverage", "INDIRECT_IMPACT"
    )
    unit = create_unit("ED-4", "ED", 30)
    set_clock("2026-08-10T00:00:00Z")
    session = open_rounding_session(
        unit["id"], "LIFE_SAFETY", "2026-08-10T08:00:00Z", "2026-08-10T12:00:00Z"
    )
    ticket = raise_deficiency(
        session["id"], standard["id"], "MODERATE", "Extinguisher inspection overdue"
    )
    ticket_action(ticket["id"], "START_WORK")
    ticket = ticket_action(ticket["id"], "MARK_REMEDIATED")
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": read_unit(unit["id"]),
        "session": session,
        "ticket": ticket,
    }


def _setup_unmapped_standard_with_draft_evidence():
    """Chapter MM with one standard that has no OwnerAssignment, so its
    compliance_state is UNMAPPED, plus one DRAFT evidence item filed by owner-1."""
    chapter = create_chapter("MM", "Medication Management", 30, 1)
    standard = create_standard(
        chapter["id"], "MM.03.01.01", "Medication storage", "INDIRECT_IMPACT"
    )
    evidence = file_evidence(
        standard["id"],
        title="Storage inspection report",
        doc_type="INSPECTION_REPORT",
        effective_date="2026-07-15T00:00:00Z",
        owner_user_id="owner-1",
    )
    return {"chapter": chapter, "standard": standard, "evidence": evidence}


def _setup_eligible_window_with_activated_command_center():
    """Chapter EM with one standard, unit BH-1, and survey window CYCLE-2026
    swept to ELIGIBLE at clock 2026-09-20T00:00:00Z with its command center
    already ACTIVATED."""
    chapter = create_chapter("EM", "Emergency Management", 20, 1)
    standard = create_standard(
        chapter["id"], "EM.02.01.01", "Emergency operations plan", "SITUATIONAL_DECISION_RULE"
    )
    unit = create_unit("BH-1", "BEHAVIORAL_HEALTH", 10)
    built = setup_eligible_window(
        "CYCLE-2026", "2025-03-15T00:00:00Z", "2026-09-20T00:00:00Z", True
    )
    return {
        "chapter": chapter,
        "standard": standard,
        "unit": unit,
        "window": built["window"],
    }


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
#   unit_posture_state_error_precedes_tracer_window_temporal_conflict
# ---------------------------------------------------------------------------

def test_schedule_tracer_on_restricted_unit_inside_buffer_reports_posture_error(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §2.11: "The lower the number below, the earlier the check runs; the first check that fails produces the response, and no later check is evaluated."
    PRD §2.11: "Both scheduling a tracer and the `START` action require the unit's `posture` to be `OPEN` — `ERR_UNIT_POSTURE_RESTRICTED`, 409, on `POST /accreditation/mock-tracers` and `POST /accreditation/mock-tracers/{id}/transition`."
    PRD §2.11: "Tracer occupancy: no conflicting tracer in `SCHEDULED` or `IN_PROGRESS` on the same unit under the half-open interval rule plus the sixty-minute trailing buffer — `ERR_TRACER_WINDOW_CONFLICT`, 409, on `POST /accreditation/mock-tracers`."
    PRD §3.3: "`OPEN → RESTRICTED` fires automatically whenever the unit's `open_deficiency_penalty_points` changes — on ticket creation, on escalation, on a failed verification — and the resulting total is at least fifteen points."

    Design: Difficulty/priority_pair_validation_conflict/unit_posture_state_error_precedes_tracer_window_temporal_conflict
    """
    built = _setup_unit_with_in_progress_tracer(restrict=True)

    # An IN_PROGRESS tracer is not aborted by the posture change, so it still occupies the unit.
    assert built["tracer"]["state"] == "IN_PROGRESS"
    assert built["unit"]["posture"] == "RESTRICTED"
    assert built["unit"]["open_deficiency_penalty_points"] == 21

    # 12:30Z is inside 12:00Z plus the sixty-minute buffer, so rung 28 is violated too.
    response = api.create_mock_tracer(
        {
            "unit_id": built["unit"]["id"],
            "chapter_id": built["chapter"]["id"],
            "tracer_type": "SYSTEM",
            "window_start": "2026-08-05T12:30:00Z",
            "window_end": "2026-08-05T14:00:00Z",
            "expected_unit_version": built["unit"]["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_UNIT_POSTURE_RESTRICTED)

    tracers, meta = validate_paginated(
        api.list_mock_tracers(director_headers, {"unit_id": built["unit"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(tracers) == 1


def test_schedule_tracer_on_open_unit_inside_buffer_reports_window_conflict(
    api, tracer_surveyor_headers, director_headers
):
    """PRD §2.11: "Tracer occupancy: no conflicting tracer in `SCHEDULED` or `IN_PROGRESS` on the same unit under the half-open interval rule plus the sixty-minute trailing buffer — `ERR_TRACER_WINDOW_CONFLICT`, 409, on `POST /accreditation/mock-tracers`."
    PRD §3.4: "Concretely, a proposed tracer conflicts with an existing one when the proposed `window_start` falls strictly before the existing `window_end` extended by sixty minutes, **and** the proposed `window_end` falls strictly after the existing `window_start`."
    PRD §3.4: "The unit's `posture` must be `OPEN`; a `RESTRICTED` or `LOCKED_FOR_SURVEY` unit refuses new tracers with `ERR_UNIT_POSTURE_RESTRICTED`."

    Design: Difficulty/priority_pair_validation_conflict/unit_posture_state_error_precedes_tracer_window_temporal_conflict
    """
    built = _setup_unit_with_in_progress_tracer(restrict=False)

    # Only the lower-priority occupancy condition holds: the unit is still OPEN.
    assert built["tracer"]["state"] == "IN_PROGRESS"
    assert built["unit"]["posture"] == "OPEN"
    assert built["unit"]["open_deficiency_penalty_points"] == 0

    response = api.create_mock_tracer(
        {
            "unit_id": built["unit"]["id"],
            "chapter_id": built["chapter"]["id"],
            "tracer_type": "SYSTEM",
            "window_start": "2026-08-05T12:30:00Z",
            "window_end": "2026-08-05T14:00:00Z",
            "expected_unit_version": built["unit"]["version"],
        },
        tracer_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_TRACER_WINDOW_CONFLICT)

    tracers, meta = validate_paginated(
        api.list_mock_tracers(director_headers, {"unit_id": built["unit"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(tracers) == 1


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
#   condition_level_safety_error_precedes_submitter_referential_error
# ---------------------------------------------------------------------------

def test_esc_submission_by_non_owner_on_unescalated_condition_level_finding_reports_escalation_required(
    api, director_headers
):
    """PRD §2.11: "The lower the number below, the earlier the check runs; the first check that fails produces the response, and no later check is evaluated."
    PRD §2.11: "A finding whose `condition_level` is true must have reached `CONDITION_LEVEL_ESCALATED` before any submission is accepted — `ERR_CONDITION_LEVEL_ESCALATION_REQUIRED`, 409, on `POST /accreditation/survey-findings/{id}/esc-submissions`."
    PRD §2.11: "The submitting `X-User-ID` holds an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY` — `ERR_SUBMITTER_NOT_STANDARD_OWNER`, 422, on `POST /accreditation/survey-findings/{id}/esc-submissions`."
    PRD §3.7: "`condition_level` is true when either the `risk_level` came out as `IMMEDIATE_THREAT`, or the `classification` came out as `WIDESPREAD` while the referenced standard's `risk_tier` is `DIRECT_IMPACT` — the second branch is what catches a hospital-wide failure of a high-impact standard even when no harm was observed."
    PRD §3.6: "Every finding of this window still in `DRAFT` moves to `RESPONSE_PENDING`, and each gets both `initial_response_due_at` and `response_due_at` set to `survey_closed_at` plus that finding's own `response_deadline_days` days, counted as exact twenty-four-hour multiples."

    Design: Difficulty/priority_pair_validation_conflict/condition_level_safety_error_precedes_submitter_referential_error
    """
    built = setup_closed_survey_condition_level_finding()
    finding = built["finding"]

    assert finding["classification"] == "WIDESPREAD"
    assert finding["risk_level"] == "HIGH"
    assert finding["condition_level"] is True
    assert finding["state"] == "RESPONSE_PENDING"
    assert finding["response_deadline_days"] == 45
    assert_instant_equals(finding["response_due_at"], "2026-11-09T00:00:00.000Z")

    # owner-9 owns nothing, so rung 41 is violated as well as rung 26.
    response = api.create_esc_submission(
        finding["id"],
        {
            "corrective_action_summary": "Door hardware replacement",
            "measure_of_success": "Weekly egress audit",
            "leadership_signoff": True,
            "expected_finding_version": finding["version"],
        },
        make_standard_owner_headers(NON_OWNER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_CONDITION_LEVEL_ESCALATION_REQUIRED)

    unchanged = read_finding(finding["id"])
    assert unchanged["submission_count"] == 0
    assert unchanged["version"] == finding["version"]

    submissions, meta = validate_paginated(
        api.list_esc_submissions(finding["id"], director_headers)
    )
    assert meta["total_count"] == 0
    assert submissions == []


def test_esc_submission_by_non_owner_on_escalated_condition_level_finding_reports_submitter_error(
    api, director_headers
):
    """PRD §2.11: "The submitting `X-User-ID` holds an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY` — `ERR_SUBMITTER_NOT_STANDARD_OWNER`, 422, on `POST /accreditation/survey-findings/{id}/esc-submissions`."
    PRD §3.8: "And the submitting principal must hold an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY`, else `ERR_SUBMITTER_NOT_STANDARD_OWNER`."
    PRD §3.8: "A finding whose `condition_level` is true must already have reached `CONDITION_LEVEL_ESCALATED`; a submission against such a finding while it still sits in `RESPONSE_PENDING` is refused with `ERR_CONDITION_LEVEL_ESCALATION_REQUIRED`, which is what forces the surveyor's escalation to happen first."
    PRD §3.7: "It is permitted only from `RESPONSE_PENDING` — from any other finding state it is refused with `ERR_FINDING_NOT_AWAITING_RESPONSE` — and it requires the finding's `condition_level` to be true, refusing otherwise with `ERR_NOT_CONDITION_LEVEL`."

    Design: Difficulty/priority_pair_validation_conflict/condition_level_safety_error_precedes_submitter_referential_error
    """
    built = setup_closed_survey_condition_level_finding()
    escalated = escalate_finding(built["finding"]["id"])

    # The higher-priority condition is now satisfied, leaving only the ownership defect.
    assert escalated["condition_level"] is True
    assert escalated["state"] == "CONDITION_LEVEL_ESCALATED"

    response = api.create_esc_submission(
        escalated["id"],
        {
            "corrective_action_summary": "Door hardware replacement",
            "measure_of_success": "Weekly egress audit",
            "leadership_signoff": True,
            "expected_finding_version": escalated["version"],
        },
        make_standard_owner_headers(NON_OWNER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SUBMITTER_NOT_STANDARD_OWNER)

    unchanged = read_finding(escalated["id"])
    assert unchanged["submission_count"] == 0
    assert unchanged["state"] == "CONDITION_LEVEL_ESCALATED"

    submissions, meta = validate_paginated(
        api.list_esc_submissions(escalated["id"], director_headers)
    )
    assert meta["total_count"] == 0
    assert submissions == []


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict
#   evidence_state_error_precedes_segregation_referential_error
# ---------------------------------------------------------------------------

def test_validate_draft_evidence_by_active_owner_reports_evidence_not_submitted(
    api, director_headers
):
    """PRD §2.11: "The lower the number below, the earlier the check runs; the first check that fails produces the response, and no later check is evaluated."
    PRD §2.11: "`VALIDATE` requires `validation_state` to be `SUBMITTED` — `ERR_EVIDENCE_NOT_SUBMITTED`, 409, on `POST /accreditation/evidence-items/{id}/transition`."
    PRD §2.11: "Segregation of duties: the reviewing `X-User-ID` is not the `owner_user_id` of any owner assignment with `status` `ACTIVE` on the standard — `ERR_SEGREGATION_OF_DUTIES`, 403, on the `VALIDATE` and `REJECT` actions of `POST /accreditation/evidence-items/{id}/transition`."
    PRD §3.2: "A newly filed item begins at `validation_state` `DRAFT`, with `submitted_by_user_id`, `reviewed_by_user_id` and `review_note` all null and `rejection_count` at zero."

    Design: Difficulty/priority_pair_validation_conflict/evidence_state_error_precedes_segregation_referential_error
    """
    built = _setup_owner_validating_own_evidence(submitted=False)
    assert built["evidence"]["validation_state"] == "DRAFT"

    # The reviewer's identity is the standard's own ACTIVE owner, so rung 40 is violated too.
    response = api.transition_evidence_item(
        built["evidence"]["id"],
        {"action": "VALIDATE", "review_note": "Self-approval attempt on a draft"},
        make_evidence_validator_headers("owner-1"),
    )
    validate_error(response, ApiErrorId.ERR_EVIDENCE_NOT_SUBMITTED)

    evidence = validate_success(api.get_evidence_item(built["evidence"]["id"], director_headers))
    assert evidence["validation_state"] == "DRAFT"
    assert evidence["reviewed_by_user_id"] is None

    standard = read_standard(built["standard"]["id"])
    assert standard["validated_evidence_count"] == 0
    assert standard["compliance_state"] == "MAPPED"


def test_validate_submitted_evidence_by_active_owner_reports_segregation_of_duties(
    api, director_headers
):
    """PRD §2.11: "Segregation of duties: the reviewing `X-User-ID` is not the `owner_user_id` of any owner assignment with `status` `ACTIVE` on the standard — `ERR_SEGREGATION_OF_DUTIES`, 403, on the `VALIDATE` and `REJECT` actions of `POST /accreditation/evidence-items/{id}/transition`."
    PRD §3.2: "The reviewing principal must not be the `owner_user_id` of any `ACTIVE` owner assignment on the standard, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "`VALIDATE` requires the item to be in `SUBMITTED`; from any other `validation_state` it is rejected with `ERR_EVIDENCE_NOT_SUBMITTED`."

    Design: Difficulty/priority_pair_validation_conflict/evidence_state_error_precedes_segregation_referential_error
    """
    built = _setup_owner_validating_own_evidence(submitted=True)

    # Only the lower-priority independence defect remains: the item really is SUBMITTED.
    assert built["evidence"]["validation_state"] == "SUBMITTED"

    response = api.transition_evidence_item(
        built["evidence"]["id"],
        {"action": "VALIDATE", "review_note": "Self-approval attempt on a submitted item"},
        make_evidence_validator_headers("owner-1"),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    evidence = validate_success(api.get_evidence_item(built["evidence"]["id"], director_headers))
    assert evidence["validation_state"] == "SUBMITTED"
    assert evidence["reviewed_by_user_id"] is None

    standard = read_standard(built["standard"]["id"])
    assert standard["validated_evidence_count"] == 0
    assert standard["compliance_state"] == "MAPPED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / ticket_verify_requires_closed_rounding_session
# ---------------------------------------------------------------------------

def test_verify_remediated_ticket_while_session_open_is_rejected(
    api, safety_officer_headers, director_headers
):
    """PRD §2.11: "`VERIFY` and `FAIL_VERIFICATION` require the ticket's rounding session `state` to be `CLOSED` — `ERR_SESSION_NOT_CLOSED`, 409, on `POST /accreditation/deficiency-tickets/{id}/transition`."
    PRD §3.5: "The ticket's rounding session must be `CLOSED`, else `ERR_SESSION_NOT_CLOSED`."
    PRD §3.5: "Closing matters operationally because verification is only available on a closed session: the rounding has to be finished before its findings can be signed off."
    PRD §3.5: "**Fifth**, `penalty_points` is set from the severity — one point for `LOW`, three for `MODERATE`, seven for `HIGH`, fifteen for `IMMEDIATE_THREAT`."

    Design: Difficulty/cross_entity_state_dependency/ticket_verify_requires_closed_rounding_session
    """
    built = _setup_remediated_ticket_in_open_session()

    assert built["session"]["state"] == "OPEN"
    assert built["ticket"]["state"] == "REMEDIATED"
    assert built["unit"]["open_deficiency_penalty_points"] == 3

    response = api.transition_deficiency_ticket(
        built["ticket"]["id"], {"action": "VERIFY"}, safety_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_SESSION_NOT_CLOSED)

    ticket = validate_success(api.get_deficiency_ticket(built["ticket"]["id"], director_headers))
    assert ticket["state"] == "REMEDIATED"
    assert ticket["verified_by_user_id"] is None
    assert read_unit(built["unit"]["id"])["open_deficiency_penalty_points"] == 3


def test_verify_remediated_ticket_succeeds_once_session_is_closed(api):
    """PRD §2.11: "`VERIFY` and `FAIL_VERIFICATION` require the ticket's rounding session `state` to be `CLOSED` — `ERR_SESSION_NOT_CLOSED`, 409, on `POST /accreditation/deficiency-tickets/{id}/transition`."
    PRD §3.5: "The `SafetyOfficer` closes it, the server requires that no ticket of that session sits in `ESCALATED` — otherwise the request is rejected with `ERR_ESCALATED_TICKET_BLOCKS_CLOSE` — and on success the session moves `OPEN → CLOSED` with `closed_at` stamped from the logical clock and its `version` advanced."
    PRD §3.5: "`VERIFY` moves a ticket `REMEDIATED → VERIFIED` and is reserved to the `SafetyOfficer` — a `UnitManager` attempting it is refused, since no unit may verify its own remediation."
    PRD §3.5: "Verification stamps `verified_by_user_id` with the acting principal and releases the ticket's `penalty_points` from the unit's `open_deficiency_penalty_points`."
    PRD §2.9: "Raising a ticket adds its points; verifying a ticket removes them; escalating a ticket that gains severity replaces its old contribution with the new one."

    Design: Difficulty/cross_entity_state_dependency/ticket_verify_requires_closed_rounding_session
    """
    built = _setup_remediated_ticket_in_open_session()
    assert built["unit"]["open_deficiency_penalty_points"] == 3

    closed = close_rounding_session(built["session"]["id"])
    assert closed["state"] == "CLOSED"

    verified = ticket_action(built["ticket"]["id"], "VERIFY")
    assert verified["state"] == "VERIFIED"

    unit = read_unit(built["unit"]["id"])
    assert unit["open_deficiency_penalty_points"] == 0
    assert unit["posture"] == "OPEN"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / evidence_submit_requires_mapped_standard
# ---------------------------------------------------------------------------

def test_submit_evidence_on_unmapped_standard_is_rejected(api, director_headers):
    """PRD §2.11: "`SUBMIT` requires the standard's `compliance_state` not to be `UNMAPPED` and the submitting `X-User-ID` to hold an `ACTIVE` owner assignment on that standard — `ERR_STANDARD_UNMAPPED`, 422, on `POST /accreditation/evidence-items/{id}/transition`."
    PRD §3.2: "Two conditions gate the action, and both are reported through the same code: the standard's `compliance_state` must not be `UNMAPPED`, and the submitting principal must hold an owner assignment on that standard with `status` `ACTIVE`."
    PRD §3.2: "A failure of either is rejected with `ERR_STANDARD_UNMAPPED`."
    PRD §3.1: "The new standard begins at `compliance_state` `UNMAPPED`, with `active_owner_count` and `validated_evidence_count` at zero and `last_noncompliant_observed_at` null."

    Design: Difficulty/cross_entity_state_dependency/evidence_submit_requires_mapped_standard
    """
    built = _setup_unmapped_standard_with_draft_evidence()
    assert built["standard"]["compliance_state"] == "UNMAPPED"
    assert built["evidence"]["validation_state"] == "DRAFT"

    response = api.transition_evidence_item(
        built["evidence"]["id"], {"action": "SUBMIT"}, make_standard_owner_headers("owner-1")
    )
    validate_error(response, ApiErrorId.ERR_STANDARD_UNMAPPED)

    evidence = validate_success(api.get_evidence_item(built["evidence"]["id"], director_headers))
    assert evidence["validation_state"] == "DRAFT"
    assert evidence["submitted_by_user_id"] is None


def test_submit_evidence_succeeds_once_standard_is_mapped(api):
    """PRD §2.11: "`SUBMIT` requires the standard's `compliance_state` not to be `UNMAPPED` and the submitting `X-User-ID` to hold an `ACTIVE` owner assignment on that standard — `ERR_STANDARD_UNMAPPED`, 422, on `POST /accreditation/evidence-items/{id}/transition`."
    PRD §3.1: "If that count moved from zero to one, the standard transitions `UNMAPPED → MAPPED` and its chapter's `mapped_standard_count` increases by one — the count only moves on that zero-to-one edge, so a second owner leaves it alone."
    PRD §3.2: "Submitting for review moves the item `DRAFT → SUBMITTED`, or `REJECTED → SUBMITTED` on a resubmission — the rejection loop is unbounded, and an owner may keep revising and resubmitting a document indefinitely."
    PRD §3.2: "On success the item records `submitted_by_user_id` as the acting principal's identifier and its `version` advances."

    Design: Difficulty/cross_entity_state_dependency/evidence_submit_requires_mapped_standard
    """
    built = _setup_unmapped_standard_with_draft_evidence()
    assert built["standard"]["compliance_state"] == "UNMAPPED"

    assign_owner(built["standard"]["id"], "owner-1", "PRIMARY")

    standard = read_standard(built["standard"]["id"])
    assert standard["active_owner_count"] == 1
    assert standard["compliance_state"] == "MAPPED"

    submitted = evidence_action(
        built["evidence"]["id"], "SUBMIT", make_standard_owner_headers("owner-1")
    )
    assert submitted["validation_state"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "owner-1"

    assert read_chapter(built["chapter"]["id"])["mapped_standard_count"] == 1
    assert read_standard(built["standard"]["id"])["validated_evidence_count"] == 0


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / finding_creation_requires_active_survey_window
# ---------------------------------------------------------------------------

def test_record_finding_on_eligible_window_is_rejected(
    api, external_surveyor_headers, director_headers
):
    """PRD §2.11: "Recording a finding requires the window's `window_state` to be `ACTIVE_SURVEY` — `ERR_SURVEY_NOT_ACTIVE`, 409, on `POST /accreditation/survey-windows/{id}/findings`."
    PRD §3.7: "During an active survey, only the `ExternalSurveyor` writes findings, and the window's `window_state` must be `ACTIVE_SURVEY` or the write is refused with `ERR_SURVEY_NOT_ACTIVE`."
    PRD §3.6: "Activation deliberately does **not** touch `window_state`, which may perfectly well still be `PROJECTED` — the whole point of the thirty-day lead is that the command center stands up before the window opens."
    PRD §2.4: "Second, the **survey eligibility re-evaluation**: every survey window whose `window_state` is `PROJECTED` and whose `predicted_open_date` is at or before the new clock while its `predicted_close_date` is at or after the new clock moves to `window_state` `ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/finding_creation_requires_active_survey_window
    """
    built = _setup_eligible_window_with_activated_command_center()

    assert built["window"]["command_center_state"] == "ACTIVATED"
    assert built["window"]["window_state"] == "ELIGIBLE"

    response = api.create_finding(
        built["window"]["id"],
        {
            "standard_id": built["standard"]["id"],
            "unit_id": built["unit"]["id"],
            "observed_noncompliance_count": 2,
            "sampled_count": 10,
            "patient_harm_observed": False,
        },
        external_surveyor_headers,
    )
    validate_error(response, ApiErrorId.ERR_SURVEY_NOT_ACTIVE)

    findings, meta = validate_paginated(
        api.list_findings(director_headers, {"survey_window_id": built["window"]["id"]})
    )
    assert meta["total_count"] == 0
    assert findings == []


def test_record_finding_succeeds_once_survey_is_open(
    api, external_surveyor_headers, director_headers
):
    """PRD §2.11: "Recording a finding requires the window's `window_state` to be `ACTIVE_SURVEY` — `ERR_SURVEY_NOT_ACTIVE`, 409, on `POST /accreditation/survey-windows/{id}/findings`."
    PRD §3.6: "It has two declared entry points: `ELIGIBLE → ACTIVE_SURVEY` for the initial survey and `CLOSED → ACTIVE_SURVEY` for a follow-up survey, making the survey dimension cyclic too."
    PRD §3.7: "First, `noncompliance_rate` is the observed count divided by the sampled count, rounded half up to four decimal places; every subsequent comparison uses that rounded value, not the raw quotient."
    PRD §3.7: "Second, the rate produces a `classification`: it is `LIMITED` when the rate is strictly below 0.3400, `PATTERN` when the rate is at or above 0.3400 but strictly below 0.8000, and `WIDESPREAD` when the rate is at or above 0.8000."
    PRD §3.7: "The tier index comes from the referenced standard's own `risk_tier`: zero for `SITUATIONAL_DECISION_RULE`, one for `INDIRECT_IMPACT` and two for `DIRECT_IMPACT`."
    PRD §3.7: "That capped index yields the `risk_level`: `LOW` when the index is one or less, `MODERATE` when it is exactly two, `HIGH` when it is three or four, and `IMMEDIATE_THREAT` when it is five or more."

    Design: Difficulty/cross_entity_state_dependency/finding_creation_requires_active_survey_window
    """
    built = _setup_eligible_window_with_activated_command_center()

    opened = validate_success(
        api.transition_survey_window(
            built["window"]["id"], {"action": "OPEN_SURVEY"}, director_headers
        )
    )
    assert opened["window_state"] == "ACTIVE_SURVEY"

    finding = validate_success(
        api.create_finding(
            built["window"]["id"],
            {
                "standard_id": built["standard"]["id"],
                "unit_id": built["unit"]["id"],
                "observed_noncompliance_count": 2,
                "sampled_count": 10,
                "patient_harm_observed": False,
            },
            external_surveyor_headers,
        ),
        201,
    )

    assert float(finding["noncompliance_rate"]) == 0.2000
    assert finding["classification"] == "LIMITED"
    assert finding["risk_level"] == "LOW"
    assert finding["state"] == "DRAFT"

    findings, meta = validate_paginated(
        api.list_findings(director_headers, {"survey_window_id": built["window"]["id"]})
    )
    assert meta["total_count"] == 1
    assert len(findings) == 1
