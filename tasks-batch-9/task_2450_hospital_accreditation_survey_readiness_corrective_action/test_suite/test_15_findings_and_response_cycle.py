"""Survey findings, condition-level escalation, and the evidence-of-standards-
compliance response cycle: its guards, its precedence, and its stale-view
protection."""

from test_helpers import (
    ApiErrorId,
    create_survey_window,
    create_unit,
    esc_submission_payload,
    read_chapter,
    read_finding,
    read_standard,
    set_clock,
    setup_closed_survey_condition_level_finding,
    setup_closed_survey_ld_finding,
    setup_mapped_chapter,
    submit_esc,
    validate_error,
    validate_paginated,
    validate_success,
)

CYCLE_2026_ANCHOR = "2025-03-15T00:00:00Z"


# ===========================================================================
# Corner/endpoints
# ===========================================================================


def test_escalate_action_applies_every_side_effect(api, director_headers, external_surveyor_headers):
    """PRD §3.7: "`condition_level` is true when either the `risk_level` came out as `IMMEDIATE_THREAT`, or the `classification` came out as `WIDESPREAD` while the referenced standard's `risk_tier` is `DIRECT_IMPACT` — the second branch is what catches a hospital-wide failure of a high-impact standard even when no harm was observed."

    PRD §3.7: "On success the finding moves `RESPONSE_PENDING → CONDITION_LEVEL_ESCALATED`, the referenced standard is driven to `DEFICIENT` with `last_noncompliant_observed_at` stamped from the current logical clock — carrying the same chapter-counter and `AT_RISK` consequences described in §3.4, including the return of that chapter's submitted self-assessments for reassessment — and the owning window has `follow_up_required` set to true with `follow_up_due_at` set to `survey_closed_at` plus sixty days."

    PRD §3.1: "It flips from `ON_TRACK` to `AT_RISK` as soon as either the chapter accumulates two or more deficient standards or its overstatement escalations reach two."

    Design: Corner/endpoints/escalate_action_endpoint_applies_all_side_effects
    """
    built = setup_closed_survey_condition_level_finding(
        unit_name="OR-12", unit_type="OR", bed_count=6
    )

    assert built["finding"]["condition_level"] is True
    assert built["window"]["survey_closed_at"] == "2026-09-25T00:00:00.000Z"

    set_clock("2026-09-28T00:00:00Z")

    escalated = validate_success(
        api.escalate_finding(
            built["finding"]["id"],
            {"rationale": "Immediate jeopardy to patients"},
            external_surveyor_headers,
        )
    )

    assert escalated["state"] == "CONDITION_LEVEL_ESCALATED"

    standard = read_standard(built["standard"]["id"])

    assert standard["compliance_state"] == "DEFICIENT"
    assert standard["last_noncompliant_observed_at"] == "2026-09-28T00:00:00.000Z"

    window = validate_success(
        api.get_survey_window(built["window"]["id"], director_headers)
    )

    assert window["follow_up_required"] is True
    assert window["follow_up_due_at"] == "2026-11-24T00:00:00.000Z"

    chapter = read_chapter(built["chapter"]["id"])

    assert chapter["deficient_standard_count"] == 1
    assert chapter["readiness_flag"] == "ON_TRACK"


# ===========================================================================
# Corner/validations
# ===========================================================================


def test_sample_count_error_precedes_survey_not_active(
    api, director_headers, external_surveyor_headers
):
    """PRD §2.11: "The lower the number below, the earlier the check runs; the first check that fails produces the response, and no later check is evaluated."

    PRD §2.11: "Sample sanity: `sampled_count` at least 1, and `observed_noncompliance_count` at least 1 and no greater than `sampled_count` — `ERR_SAMPLE_COUNT_INVALID`, 422, on `POST /accreditation/survey-windows/{id}/findings`."

    PRD §2.11: "Recording a finding requires the window's `window_state` to be `ACTIVE_SURVEY` — `ERR_SURVEY_NOT_ACTIVE`, 409, on `POST /accreditation/survey-windows/{id}/findings`."

    PRD §3.7: "The counts must be coherent — `sampled_count` at least one, and `observed_noncompliance_count` at least one and no greater than `sampled_count` — or the write is refused with `ERR_SAMPLE_COUNT_INVALID`."

    Design: Corner/validations/sample_count_error_precedes_survey_not_active
    """
    built = setup_mapped_chapter(
        code="EM",
        name="Emergency Management",
        weight_pct=20,
        evidence_min_count=1,
        standard_code="EM.02.01.01",
        title="Emergency operations plan",
        risk_tier="INDIRECT_IMPACT",
    )
    unit = create_unit("MED-10", "MED_SURG", 22)
    window = create_survey_window("CYCLE-2026", CYCLE_2026_ANCHOR)

    assert window["window_state"] == "PROJECTED"

    rejected = api.create_finding(
        window["id"],
        {
            "standard_id": built["standard"]["id"],
            "unit_id": unit["id"],
            "sampled_count": 5,
            "observed_noncompliance_count": 6,
            "patient_harm_observed": False,
        },
        external_surveyor_headers,
    )

    validate_error(rejected, ApiErrorId.ERR_SAMPLE_COUNT_INVALID)

    after = validate_success(api.get_survey_window(window["id"], director_headers))

    assert after["condition_level_finding_count"] == 0


def test_esc_submission_without_leadership_signoff_rejected(api, standard_owner_headers):
    """PRD §2.11: "`leadership_signoff` is true — `ERR_LEADERSHIP_SIGNOFF_REQUIRED`, 422, on `POST /accreditation/survey-findings/{id}/esc-submissions`."

    PRD §3.8: "`leadership_signoff` must be true, else `ERR_LEADERSHIP_SIGNOFF_REQUIRED` — an unsigned plan is not a plan."

    PRD §3.6: "Every finding of this window still in `DRAFT` moves to `RESPONSE_PENDING`, and each gets both `initial_response_due_at` and `response_due_at` set to `survey_closed_at` plus that finding's own `response_deadline_days` days, counted as exact twenty-four-hour multiples."

    Design: Corner/validations/esc_submission_without_leadership_signoff_rejected
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    assert finding["state"] == "RESPONSE_PENDING"

    rejected = api.create_esc_submission(
        finding["id"],
        esc_submission_payload(finding["version"], leadership_signoff=False),
        standard_owner_headers,
    )

    validate_error(rejected, ApiErrorId.ERR_LEADERSHIP_SIGNOFF_REQUIRED)

    after = read_finding(finding["id"])

    assert after["submission_count"] == 0
    assert after["version"] == finding["version"]
    assert after["state"] == "RESPONSE_PENDING"


def test_esc_submission_by_non_owner_returns_submitter_not_standard_owner(
    api, second_standard_owner_headers, director_headers
):
    """PRD §2.11: "The submitting `X-User-ID` holds an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY` — `ERR_SUBMITTER_NOT_STANDARD_OWNER`, 422, on `POST /accreditation/survey-findings/{id}/esc-submissions`."

    PRD §2.10: "An evidence-of-standards-compliance submission must come from a principal holding an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY`; a `SECONDARY` owner, or a principal with no active assignment at all, is rejected with `ERR_SUBMITTER_NOT_STANDARD_OWNER` (HTTP 422)."

    PRD §3.8: "And the submitting principal must hold an owner assignment on the finding's standard with `status` `ACTIVE` and `designation` `PRIMARY`, else `ERR_SUBMITTER_NOT_STANDARD_OWNER`."

    Design: Corner/validations/esc_submission_by_non_owner_returns_submitter_not_standard_owner
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    rejected = api.create_esc_submission(
        finding["id"],
        esc_submission_payload(finding["version"], leadership_signoff=True),
        second_standard_owner_headers,
    )

    validate_error(rejected, ApiErrorId.ERR_SUBMITTER_NOT_STANDARD_OWNER)

    after = read_finding(finding["id"])

    assert after["state"] == "RESPONSE_PENDING"
    assert after["submission_count"] == 0

    submissions, meta = validate_paginated(
        api.list_esc_submissions(finding["id"], director_headers)
    )

    assert meta["total_count"] == 0
    assert submissions == []


def test_esc_submission_after_response_due_at_returns_window_closed(
    api, standard_owner_headers
):
    """PRD §2.11: "The logical clock is at or before the finding's `response_due_at`, equality still being inside the window — `ERR_ESC_WINDOW_CLOSED`, 422, on `POST /accreditation/survey-findings/{id}/esc-submissions`."

    PRD §3.8: "The logical clock must be at or before the finding's `response_due_at`, equality still counting as inside the window, else `ERR_ESC_WINDOW_CLOSED`."

    PRD §3.6: "Every finding of this window still in `DRAFT` moves to `RESPONSE_PENDING`, and each gets both `initial_response_due_at` and `response_due_at` set to `survey_closed_at` plus that finding's own `response_deadline_days` days, counted as exact twenty-four-hour multiples."

    PRD §3.7: "And `response_deadline_days` is forty-five when the `risk_level` is `HIGH` or `IMMEDIATE_THREAT`, and sixty otherwise."

    Design: Corner/validations/esc_submission_after_response_due_at_returns_window_closed
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    assert finding["response_due_at"] == "2026-11-24T00:00:00.000Z"

    set_clock("2026-11-25T00:00:00Z")

    rejected = api.create_esc_submission(
        finding["id"],
        esc_submission_payload(finding["version"]),
        standard_owner_headers,
    )

    validate_error(rejected, ApiErrorId.ERR_ESC_WINDOW_CLOSED)

    after = read_finding(finding["id"])

    assert after["state"] == "RESPONSE_PENDING"
    assert after["submission_count"] == 0


def test_esc_review_on_response_pending_finding_rejected(api, external_surveyor_headers):
    """PRD §2.11: "The finding's `state` permits the operation: a submission from `RESPONSE_PENDING`, `CONDITION_LEVEL_ESCALATED` or `CLARIFICATION_REQUESTED`; a review from `RESPONSE_SUBMITTED`; an escalation from `RESPONSE_PENDING` — `ERR_FINDING_NOT_AWAITING_RESPONSE`, 409, on `POST /accreditation/survey-findings/{id}/esc-submissions`, `POST /accreditation/survey-findings/{id}/esc-review` and `POST /accreditation/survey-findings/{id}/escalate`."

    PRD §3.8: "The accrediting body then rules on the newest round, and only the `ExternalSurveyor` may do so, only while the finding is in `RESPONSE_SUBMITTED`, else `ERR_FINDING_NOT_AWAITING_RESPONSE`."

    Design: Corner/validations/esc_review_on_response_pending_finding_rejected
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    assert finding["state"] == "RESPONSE_PENDING"

    rejected = api.esc_review(
        finding["id"],
        {"decision": "ACCEPTED", "decision_note": "Premature acceptance"},
        external_surveyor_headers,
    )

    validate_error(rejected, ApiErrorId.ERR_FINDING_NOT_AWAITING_RESPONSE)

    after = read_finding(finding["id"])

    assert after["state"] == "RESPONSE_PENDING"
    assert after["clarification_round_count"] == 0
    assert after["accepted_at"] is None


def test_escalate_non_condition_level_finding_rejected(
    api, director_headers, external_surveyor_headers
):
    """PRD §2.11: "Escalation requires `condition_level` to be true — `ERR_NOT_CONDITION_LEVEL`, 422, on `POST /accreditation/survey-findings/{id}/escalate`."

    PRD §3.7: "It is permitted only from `RESPONSE_PENDING` — from any other finding state it is refused with `ERR_FINDING_NOT_AWAITING_RESPONSE` — and it requires the finding's `condition_level` to be true, refusing otherwise with `ERR_NOT_CONDITION_LEVEL`."

    PRD §3.7: "On success the finding moves `RESPONSE_PENDING → CONDITION_LEVEL_ESCALATED`, the referenced standard is driven to `DEFICIENT` with `last_noncompliant_observed_at` stamped from the current logical clock — carrying the same chapter-counter and `AT_RISK` consequences described in §3.4, including the return of that chapter's submitted self-assessments for reassessment — and the owning window has `follow_up_required` set to true with `follow_up_due_at` set to `survey_closed_at` plus sixty days."

    PRD §3.6: "`follow_up_required` is then set according to whether the window's `condition_level_finding_count` is at least one."

    Design: Corner/validations/escalate_non_condition_level_finding_rejected
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    assert finding["condition_level"] is False
    assert built["window"]["follow_up_required"] is False

    rejected = api.escalate_finding(
        finding["id"], {"rationale": "Surveyor judgement call"}, external_surveyor_headers
    )

    validate_error(rejected, ApiErrorId.ERR_NOT_CONDITION_LEVEL)

    assert read_finding(finding["id"])["state"] == "RESPONSE_PENDING"
    assert read_standard(built["standard"]["id"])["compliance_state"] == "MAPPED"

    window = validate_success(
        api.get_survey_window(built["window"]["id"], director_headers)
    )

    assert window["follow_up_required"] is False
    assert window["follow_up_due_at"] is None


def test_esc_submission_with_all_rules_satisfied_succeeds(api, standard_owner_headers):
    """PRD §3.8: "On success the finding's `submission_count` increases by one and a submission record is created with `submission_round` equal to that new count — one for the first submission, two for the resubmission after a first clarification, and so on — with `submitted_by_user_id` stamped from the acting owner, `decision` at `PENDING` and `decision_note` null."

    PRD §3.8: "The finding moves to `RESPONSE_SUBMITTED`, and its `version` advances."

    PRD §2.5: "Two resources are append-only records of a moment and therefore carry **only** `id` and `created_at`: `TracerObservation` and `EscSubmission`."

    Design: Corner/validations/esc_submission_all_rules_satisfied_succeeds
    """
    built = setup_closed_survey_ld_finding()
    finding = built["finding"]

    submission = validate_success(
        api.create_esc_submission(
            finding["id"],
            esc_submission_payload(finding["version"], leadership_signoff=True),
            standard_owner_headers,
        ),
        201,
    )

    assert submission["submission_round"] == 1
    assert submission["decision"] == "PENDING"
    assert submission["decision_note"] is None
    assert submission["submitted_by_user_id"] == "owner-1"
    assert "version" not in submission
    assert "updated_at" not in submission

    after = read_finding(finding["id"])

    assert after["state"] == "RESPONSE_SUBMITTED"
    assert after["submission_count"] == 1
    assert after["version"] == finding["version"] + 1
    assert after["response_due_at"] == finding["response_due_at"]


# ===========================================================================
# Corner/cross_cutting_complexity_layers
# ===========================================================================


def test_replayed_finding_version_rejects_second_esc_submission(
    api, director_headers, standard_owner_headers
):
    """PRD §2.7: "Submitting evidence of standards compliance — `POST /accreditation/survey-findings/{id}/esc-submissions` — requires a non-optional `expected_finding_version` field in the request body carrying the client's last observed `version` of the target `SurveyFinding`."

    PRD §2.7: "If that value does not equal the finding's current `version` at write time, the request is rejected with `ERR_STALE_FINDING_VERSION` (HTTP 412)."

    PRD §2.11: "Stale-view rejection: `expected_unit_version` equals `HospitalUnit.version`, and `expected_finding_version` equals `SurveyFinding.version` — `ERR_STALE_UNIT_VERSION` or `ERR_STALE_FINDING_VERSION`, 412, on `POST /accreditation/mock-tracers` and `POST /accreditation/survey-findings/{id}/esc-submissions`."

    PRD §3.8: "The finding moves to `RESPONSE_SUBMITTED`, and its `version` advances."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_finding_version_rejects_esc_submission
    """
    built = setup_closed_survey_ld_finding(unit_name="MED-16")
    finding = read_finding(built["finding"]["id"])
    first_version = finding["version"]

    first = submit_esc(finding["id"], expected_finding_version=first_version)

    assert first["submission_round"] == 1

    replayed = api.create_esc_submission(
        finding["id"],
        esc_submission_payload(first_version, leadership_signoff=True),
        standard_owner_headers,
    )

    validate_error(replayed, ApiErrorId.ERR_STALE_FINDING_VERSION)

    after = read_finding(finding["id"])

    assert after["submission_count"] == 1
    assert after["state"] == "RESPONSE_SUBMITTED"

    submissions, meta = validate_paginated(
        api.list_esc_submissions(finding["id"], director_headers)
    )

    assert meta["total_count"] == 1
    assert len(submissions) == 1
