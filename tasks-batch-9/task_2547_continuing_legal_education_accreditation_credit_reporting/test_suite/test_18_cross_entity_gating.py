"""Gates that depend on the state of a *different* record than the one addressed.

Two of them live here: a sponsor's promotion out of probation, which waits on one
of that sponsor's audits reaching CLEARED, and the board's verification of a
credit record, which waits on the standing of the course the credit was earned
at.
"""
from datetime import datetime

from test_helpers import (
    adjudicate_record,
    api_client,
    assert_version_unchanged,
    audit_action,
    create_accredited_provider,
    create_attorney,
    create_cycle,
    create_probationary_provider,
    create_self_certified_course,
    factories,
    file_complaint,
    list_fee_assessments,
    make_attorney_headers,
    make_provider_admin_headers,
    open_audit,
    read_course,
    read_credit_record,
    read_cycle,
    read_provider,
    review_action,
    run_sweep,
    submit_application,
    substantiate_complaint,
    validate_error,
    validate_success,
)


# --- Local helpers ---------------------------------------------------------

def _as_instant(value: str) -> datetime:
    """Parses a wire timestamp so two spellings of the same instant compare
    equal."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _file_pending_record(attorney_id, course_id, verification_method,
                         attended_minutes, completion_date,
                         certificate_reference=None):
    """Files one credit claim that waits for verification, omitting the
    certificate reference unless the method actually needs it."""
    payload = factories.create_credit_record_payload(
        attorney_id,
        course_id,
        verification_method=verification_method,
        attended_minutes=attended_minutes,
        completion_date=completion_date,
    )
    if certificate_reference is None:
        payload.pop("certificate_reference", None)
    else:
        payload["certificate_reference"] = certificate_reference
    return validate_success(
        api_client.create_credit_record(payload, make_attorney_headers(attorney_id)),
        expected_status=201,
    )


def _probationary_sponsor_with_a_sample_pool():
    """A COMMERCIAL sponsor on probation holding one board-approved course
    inside the window an audit will examine. Returns (provider, course)."""
    provider = create_probationary_provider(
        name="Ironwood Continuing Education LLC", provider_type="COMMERCIAL"
    )
    course = create_self_certified_course(
        provider,
        title="Probationary Sponsor Self-Study",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-06-10T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[factories.credit_allocation_entry("GENERAL", 180)],
    )
    application = submit_application(
        course["id"], make_provider_admin_headers(provider["id"])
    )
    review_action(application["id"], "APPROVE", "reviewer-beta")
    return read_provider(provider["id"]), read_course(course["id"])


def _grant_full(provider_id, expected_provider_version, headers):
    return api_client.provider_accreditation_action(
        provider_id,
        {"action": "GRANT_FULL", "expected_provider_version": expected_provider_version},
        headers,
    )


# =========================================================================
# A sponsor leaves probation only once one of its own audits has cleared
# =========================================================================

def test_grant_full_from_probation_is_refused_while_the_sponsor_has_no_audit(
        api, board_headers):
    """PRD §3.1: "`GRANT_FULL` on a `PROBATIONARY` sponsor moves it `PROBATIONARY → ACCREDITED`, and it is gated on a cross-entity fact: at least one audit of that same sponsor must have reached `CLEARED`."
    PRD §3.1: "Without such an audit the request is `ERR_NO_CLEARED_AUDIT`."

    Design: Difficulty/cross_entity_state_dependency/provider_cannot_leave_probation_until_one_of_its_audits_reaches_cleared
    """
    provider, _course = _probationary_sponsor_with_a_sample_pool()
    before = read_provider(provider["id"])
    assert before["accreditation_status"] == "PROBATIONARY", (
        "the sponsor must sit on probation before the gate is exercised"
    )

    response = _grant_full(provider["id"], before["version"], board_headers)
    validate_error(response, "ERR_NO_CLEARED_AUDIT")

    after = read_provider(provider["id"])
    assert after["accreditation_status"] == "PROBATIONARY", (
        "a refused promotion must leave the sponsor on probation, got "
        f"{after['accreditation_status']}"
    )
    assert after["self_certification_enabled"] is False, (
        "a refused promotion must not switch self-certification on"
    )
    assert_version_unchanged(before, after)


def test_grant_full_from_probation_is_refused_while_the_only_audit_is_sampled(
        api, board_headers):
    """PRD §2.8: "A provider may leave `PROBATIONARY` for `ACCREDITED` only when at least one of that provider's audits has reached `CLEARED` — otherwise `ERR_NO_CLEARED_AUDIT` (409)."
    PRD §3.1: "Without such an audit the request is `ERR_NO_CLEARED_AUDIT`."

    Design: Difficulty/cross_entity_state_dependency/provider_cannot_leave_probation_until_one_of_its_audits_reaches_cleared
    """
    provider, course = _probationary_sponsor_with_a_sample_pool()
    audit = open_audit(
        provider["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "RISK_BASED"
    )
    assert float(audit["risk_score_at_open"]) == 0.0, (
        f"a sponsor with no history opens at risk 0.0, got {audit['risk_score_at_open']}"
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    assert audit["status"] == "SAMPLED", (
        f"the audit must be drawn but not closed, got {audit['status']}"
    )
    assert audit["sample_size"] == 1, (
        f"a pool of one yields a short sample of one, got {audit['sample_size']}"
    )
    assert audit["sampled_course_ids"] == [course["id"]], (
        "the only eligible course must be the sampled one, got "
        f"{audit['sampled_course_ids']}"
    )

    before = read_provider(provider["id"])
    response = _grant_full(provider["id"], before["version"], board_headers)
    validate_error(response, "ERR_NO_CLEARED_AUDIT")

    after = read_provider(provider["id"])
    assert after["accreditation_status"] == "PROBATIONARY", (
        "an audit that has only been sampled does not unlock the promotion, got "
        f"{after['accreditation_status']}"
    )
    assert_version_unchanged(before, after)


def test_grant_full_from_probation_succeeds_once_an_audit_reaches_cleared(
        api, board_headers):
    """PRD §3.1: "`GRANT_FULL` on a `PROBATIONARY` sponsor moves it `PROBATIONARY → ACCREDITED`, and it is gated on a cross-entity fact: at least one audit of that same sponsor must have reached `CLEARED`."
    PRD §3.1: "This promotion flips `self_certification_enabled` to true and re-scores the sponsor under `SELF_CERTIFIED_WEIGHTING`; it does not start a new term and does not raise a new annual fee, because the term granted at probation is still running."
    PRD §3.9: "`CLOSE_CLEARED` requires `findings_count` of at most one, stamps `closed_at` with the current instant, sets `sanction_type` to `NONE`, writes that instant into the provider's `last_audit_closed_at` — which resets the staleness term of the score — and unlocks the sponsor's `PROBATIONARY → ACCREDITED` gate described in §3.1."

    Design: Difficulty/cross_entity_state_dependency/provider_cannot_leave_probation_until_one_of_its_audits_reaches_cleared
    """
    provider, _course = _probationary_sponsor_with_a_sample_pool()
    term_end_at_probation = read_provider(provider["id"])["accreditation_term_end"]

    audit = open_audit(
        provider["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "RISK_BASED"
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    audit = audit_action(
        audit["id"], "ISSUE_FINDINGS", audit["version"], findings_count=1
    )
    audit = audit_action(audit["id"], "CLOSE_CLEARED", audit["version"])
    assert audit["status"] == "CLEARED", (
        f"one finding is still clearable, got {audit['status']}"
    )
    assert audit["sanction_type"] == "NONE", (
        f"a cleared audit carries no sanction, got {audit['sanction_type']}"
    )
    assert _as_instant(audit["closed_at"]) == _as_instant("2026-08-01T00:00:00Z"), (
        f"closed_at must be the current logical instant, got {audit['closed_at']}"
    )

    before = read_provider(provider["id"])
    assert _as_instant(before["last_audit_closed_at"]) == _as_instant(
        "2026-08-01T00:00:00Z"
    ), (
        "the closing instant must be written onto the sponsor, got "
        f"{before['last_audit_closed_at']}"
    )

    granted = validate_success(
        _grant_full(provider["id"], before["version"], board_headers)
    )
    assert granted["accreditation_status"] == "ACCREDITED", (
        "a cleared audit unlocks the promotion, got "
        f"{granted['accreditation_status']}"
    )
    assert granted["self_certification_enabled"] is True, (
        "the promotion flips self-certification on"
    )
    assert granted["risk_score_variant"] == "SELF_CERTIFIED_WEIGHTING", (
        f"the promotion re-scores under the self-certified weighting, got "
        f"{granted['risk_score_variant']}"
    )
    assert _as_instant(granted["accreditation_term_end"]) == _as_instant(
        term_end_at_probation
    ), (
        "the promotion does not start a new term: "
        f"{granted['accreditation_term_end']} vs {term_end_at_probation}"
    )
    annual_fees = list_fee_assessments(
        provider_id=provider["id"], fee_type="PROVIDER_ANNUAL"
    )
    assert len(annual_fees) == 1, (
        "the promotion raises no fresh annual fee, so only the fee raised at "
        f"probation stands: {annual_fees}"
    )


# =========================================================================
# Verifying a credit turns on the standing of the course it was earned at
# =========================================================================

def _two_records_whose_courses_diverge():
    """One sponsor, two approved courses and one attorney holding a claim on
    each. A batch run then expires the live course, and a substantiated
    complaint revokes the self-study course, so the two claims stay identical
    in their own state while their courses part ways."""
    provider = create_accredited_provider(
        name="Copper Canyon Bar Institute", provider_type="BAR_ASSOCIATION"
    )
    self_study = create_self_certified_course(
        provider,
        title="Self-Study: Fee Splitting",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-06-01T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[factories.credit_allocation_entry("ETHICS", 180)],
    )
    live = create_self_certified_course(
        provider,
        title="Live Seminar: Discovery Sanctions",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=180,
        presented_at="2026-06-05T09:00:00Z",
        attendance_verification_method="CERTIFICATE",
        credit_allocations=[factories.credit_allocation_entry("GENERAL", 180)],
    )
    attorney = create_attorney(
        bar_number="BAR-1212", full_name="Imelda Rojas",
        admission_date="2017-05-01T00:00:00Z", compliance_group="GROUP_2",
    )
    cycle = create_cycle(attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z")
    record_on_self_study = _file_pending_record(
        attorney["id"], self_study["id"], "AFFIRMATION", 180, "2026-06-02T00:00:00Z"
    )
    record_on_live = _file_pending_record(
        attorney["id"], live["id"], "CERTIFICATE", 180, "2026-06-05T12:00:00Z",
        certificate_reference="CERT-7781",
    )
    sweep = run_sweep()
    complaint = file_complaint(
        "COURSE", self_study["id"],
        allegation="The self-study materials were never delivered to registrants.",
        allegation_category="NO_SHOW_FACULTY",
    )
    substantiate_complaint(
        complaint["id"], disposer_user_id="board-review-12",
        disposition_reason="Materials confirmed undelivered.",
    )
    return {
        "provider": provider, "self_study": self_study, "live": live,
        "attorney": attorney, "cycle": cycle, "sweep": sweep,
        "record_on_self_study": record_on_self_study,
        "record_on_live": record_on_live,
    }


def test_verify_is_permitted_when_the_records_course_has_merely_expired(api):
    """PRD §3.5: "`VERIFY` moves a `PENDING_VERIFICATION` record to `VERIFIED`, and it is permitted while the course is `APPROVED` **or** `EXPIRED` — an expired course may still be adjudicated for attendance that was completed before expiry — raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application."
    PRD §3.2: "A batch run moves any `APPROVED` course whose `expires_at` has been reached or passed to `EXPIRED` and counts it in that run's `courses_expired` tally."
    PRD §3.6: "While a cycle's `credit_status` is `OPEN`, the provisional result is what gets persisted into the cycle's `earned_*` fields and into each record's `countable_minutes`."

    Design: Difficulty/cross_entity_state_dependency/credit_record_verification_depends_on_its_course_being_approved_or_merely_expired
    """
    world = _two_records_whose_courses_diverge()
    assert world["sweep"]["courses_expired"] == 1, (
        "only the live course has reached its expiry, got "
        f"{world['sweep']['courses_expired']}"
    )
    assert world["sweep"]["delinquencies_issued"] == 0, (
        "no filing deadline has passed, got "
        f"{world['sweep']['delinquencies_issued']}"
    )
    live = read_course(world["live"]["id"])
    assert live["status"] == "EXPIRED", (
        f"the live course must have expired, got {live['status']}"
    )

    verified = adjudicate_record(world["record_on_live"]["id"], "VERIFY")
    assert verified["status"] == "VERIFIED", (
        "a claim on an expired course still verifies, got "
        f"{verified['status']}"
    )
    assert verified["countable_minutes"] == 180, (
        f"the whole session must count, got {verified['countable_minutes']}"
    )
    assert read_course(world["live"]["id"])["verified_credit_record_count"] == 1, (
        "verification raises the course's verified count by one"
    )
    cycle = read_cycle(world["cycle"]["id"])
    assert cycle["earned_countable_minutes"] == 360, (
        "the still-pending ethics claim counts alongside the verified one while "
        f"the period is open, got {cycle['earned_countable_minutes']}"
    )
    assert cycle["earned_live_minutes"] == 180, (
        f"only the live session is live minutes, got {cycle['earned_live_minutes']}"
    )


def test_verify_is_refused_when_the_records_course_was_revoked(api, board_headers):
    """PRD §3.5: "`VERIFY` moves a `PENDING_VERIFICATION` record to `VERIFIED`, and it is permitted while the course is `APPROVED` **or** `EXPIRED` — an expired course may still be adjudicated for attendance that was completed before expiry — raising the course's `verified_credit_record_count` by one and re-running the owning cycle's credit application."
    PRD §3.9: "Against a course, the course moves to `REVOKED` from `APPROVED`, `SUSPENDED_PENDING_REVIEW` or `EXPIRED`; that revocation copies the `disposition_reason` into the course's `denial_reason` and voids every `VERIFIED` credit record earned at that course, stamping each with a `void_reason` of `COURSE_REVOKED`; each void re-runs the owning cycle's credit application; and that re-run can revert a `SATISFIED` cycle to `OPEN` as §3.8 describes, which in turn rewrites the successor cycle's `carryover_in_general_minutes` and `carryover_in_ethics_minutes` to zero and re-derives its figures."

    Design: Difficulty/cross_entity_state_dependency/credit_record_verification_depends_on_its_course_being_approved_or_merely_expired
    """
    world = _two_records_whose_courses_diverge()
    revoked_course = read_course(world["self_study"]["id"])
    assert revoked_course["status"] == "REVOKED", (
        f"the substantiated complaint revokes the course, got {revoked_course['status']}"
    )
    record_before = read_credit_record(world["record_on_self_study"]["id"])
    assert record_before["status"] == "PENDING_VERIFICATION", (
        "the revocation reaches only records already verified, so this claim is "
        f"untouched, got {record_before['status']}"
    )
    cycle_before = read_cycle(world["cycle"]["id"])

    response = api_client.credit_record_adjudication(
        world["record_on_self_study"]["id"], {"action": "VERIFY"}, board_headers
    )
    validate_error(response, "ERR_INVALID_STATE_TRANSITION")

    record_after = read_credit_record(world["record_on_self_study"]["id"])
    assert record_after["status"] == "PENDING_VERIFICATION", (
        "the refused adjudication leaves the claim where it was, got "
        f"{record_after['status']}"
    )
    assert record_after["void_reason"] is None, (
        f"a refused adjudication writes no reason, got {record_after['void_reason']!r}"
    )
    cycle_after = read_cycle(world["cycle"]["id"])
    assert cycle_after["earned_ethics_minutes"] == 180, (
        "the ethics minutes of the still-pending claim are untouched, got "
        f"{cycle_after['earned_ethics_minutes']}"
    )
    assert_version_unchanged(cycle_before, cycle_after)
