"""Cascades that travel several rows deep from one board decision.

Each test builds its own register through the endpoints the PRD declares,
because the board's database is empty at the start of every test.
"""
from datetime import datetime

import pytest

from test_helpers import (
    affirm_and_certify,
    audit_action,
    create_accredited_provider,
    create_attorney,
    create_cycle,
    create_self_certified_course,
    credit_allocation_entry,
    dispose_complaint,
    file_code_verified_record,
    file_credit_record,
    file_complaint,
    list_fee_assessments,
    make_board_admin_headers,
    open_audit,
    read_attorney,
    read_audit,
    read_course,
    read_credit_record,
    read_cycle,
    read_cycle_summary,
    read_provider,
    validate_success,
)

DISPOSER = "board-review-5"
INTAKE = "board-intake-3"
REVOCATION_REASON = "Session length confirmed at 180 minutes; credit was overstated."


def _instant(value):
    """Parses a wire timestamp so two spellings of the same instant compare."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual, expected, label):
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def build_certified_cycle_with_successor():
    """Two live sessions, a period certified on the strength of both, and the
    successor period that inherited the surplus. Returns a dict of the rows."""
    provider = create_accredited_provider(
        name="Lakeshore Trial Advocacy Institute", provider_type="LAW_SCHOOL"
    )
    course_one = create_self_certified_course(
        provider,
        title="Trial Advocacy Intensive",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=1200,
        presented_at="2024-03-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[
            credit_allocation_entry("ETHICS", 180),
            credit_allocation_entry("TECHNOLOGY", 60),
            credit_allocation_entry("BIAS_ELIMINATION", 120),
            credit_allocation_entry("GENERAL", 840),
        ],
    )
    course_two = create_self_certified_course(
        provider,
        title="Deposition Skills Workshop",
        delivery_format="LIVE_IN_PERSON",
        total_minutes=900,
        presented_at="2024-05-01T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 900)],
    )
    attorney = create_attorney(
        bar_number="BAR-6006",
        full_name="Helena Brzezinski",
        admission_date="2009-04-01T00:00:00Z",
        compliance_group="GROUP_2",
        principal_office_jurisdiction="ST",
    )
    cycle_one = create_cycle(
        attorney["id"], "2024-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        carryover_election="CARRY_FORWARD",
    )
    record_one = file_code_verified_record(
        attorney, course_one, attended_minutes=1200,
        completion_date="2024-03-02T05:00:00Z",
    )
    record_two = file_code_verified_record(
        attorney, course_two, attended_minutes=900,
        completion_date="2024-05-02T00:00:00Z",
    )
    cycle_one = affirm_and_certify(
        cycle_one["id"], attorney["id"], carryover_election="CARRY_FORWARD"
    )
    cycle_two = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z",
        previous_cycle_id=cycle_one["id"], carryover_election="CARRY_FORWARD",
    )
    # Guards on the starting position: the period closed as satisfied on the
    # strength of both sessions and handed a surplus to the successor.
    assert cycle_one["credit_status"] == "SATISFIED", cycle_one
    assert cycle_one["earned_countable_minutes"] == 2100, cycle_one
    assert cycle_one["earned_live_minutes"] == 2100, cycle_one
    assert cycle_one["carryover_out_general_minutes"] == 300, cycle_one
    assert cycle_one["carryover_out_ethics_minutes"] == 0, cycle_one
    assert cycle_two["carryover_in_general_minutes"] == 300, cycle_two
    assert cycle_two["carryover_in_ethics_minutes"] == 0, cycle_two
    complaint = file_complaint(
        "COURSE", course_two["id"], filer_user_id=INTAKE,
        allegation="The workshop awarded 15 hours for a 3-hour session.",
        allegation_category="MISREPRESENTED_CREDIT",
    )
    dispose_complaint(complaint["id"], "OPEN_REVIEW", DISPOSER)
    return {
        "provider": provider,
        "course_one": course_one,
        "course_two": course_two,
        "attorney": attorney,
        "cycle_one": cycle_one,
        "cycle_two": cycle_two,
        "record_one": record_one,
        "record_two": record_two,
        "complaint": complaint,
    }


def substantiate(api, complaint_id):
    """The board decision that heads the cascade."""
    response = api.complaint_disposition(
        complaint_id,
        {"action": "SUBSTANTIATE", "disposition_reason": REVOCATION_REASON},
        make_board_admin_headers(DISPOSER),
    )
    return validate_success(response, expected_status=200)


def test_substantiated_course_complaint_revokes_the_course_and_voids_its_verified_record(api):
    """Against a course, the course moves to `REVOKED` from `APPROVED`,
    `SUSPENDED_PENDING_REVIEW` or `EXPIRED`; that revocation copies the
    `disposition_reason` into the course's `denial_reason` and voids every
    `VERIFIED` credit record earned at that course, stamping each with a
    `void_reason` of `COURSE_REVOKED`; each void re-runs the owning cycle's
    credit application; and that re-run can revert a `SATISFIED` cycle to
    `OPEN` as §3.8 describes, which in turn rewrites the successor cycle's
    `carryover_in_general_minutes` and `carryover_in_ethics_minutes` to zero
    and re-derives its figures. Both `SUBSTANTIATED` and `DISMISSED` are
    terminal. On a course: `credited_minutes_total` is the sum of its
    allocation minutes, which must equal `total_minutes`, and
    `verified_credit_record_count` is the number of credit records for that
    course currently in the verified state — incremented when a record becomes
    verified and decremented when a verified record is voided. Every credit
    record of the cycle that was *not* in this variant's input set has its
    `countable_minutes` rewritten to zero, so the persisted per-record figures
    always reconcile against the cycle's earned totals for whichever variant
    last ran.

    Design: Difficulty/transitive_cascade/substantiated_course_complaint_unwinds_a_satisfied_cycle_and_the_successor_carryover
    """
    state = build_certified_cycle_with_successor()

    disposed = substantiate(api, state["complaint"]["id"])

    assert disposed["status"] == "SUBSTANTIATED", disposed
    revoked = read_course(state["course_two"]["id"])
    assert revoked["status"] == "REVOKED", revoked
    assert revoked["denial_reason"] == REVOCATION_REASON, revoked
    assert revoked["verified_credit_record_count"] == 0, revoked
    voided = read_credit_record(state["record_two"]["id"])
    assert voided["status"] == "VOIDED", voided
    assert voided["void_reason"] == "COURSE_REVOKED", voided
    assert voided["countable_minutes"] == 0, voided


def test_course_revocation_reopens_the_satisfied_cycle_and_counts_a_recertification(api):
    """When a `VERIFIED` credit record inside a `SATISFIED` cycle is voided —
    by board adjudication, or by the revocation of the course it was earned at
    — the final variant is re-run, and if that re-run now leaves any
    deficiency, the cycle moves `credit_status` from `SATISFIED` back to
    `OPEN`. Its `certified_at` reverts to null, both `carryover_out_*` figures
    are reset to zero, and the attorney's `pending_recertification_count`
    rises by one — that counter exists precisely to record how many times one
    of this attorney's settled periods has been reopened by a downstream void.
    The **final** variant includes only those in `VERIFIED`. Live minutes are
    never capped. When every record in the input set has been processed, the
    overall countable total becomes `earned_countable_minutes`, the three
    specialty running totals become `earned_ethics_minutes`,
    `earned_technology_minutes` and `earned_bias_minutes`, and the running
    live total becomes `earned_live_minutes`.

    Design: Difficulty/transitive_cascade/substantiated_course_complaint_unwinds_a_satisfied_cycle_and_the_successor_carryover
    """
    state = build_certified_cycle_with_successor()

    substantiate(api, state["complaint"]["id"])

    reopened = read_cycle(state["cycle_one"]["id"])
    assert reopened["credit_status"] == "OPEN", reopened
    assert reopened["certified_at"] is None, reopened
    assert reopened["earned_countable_minutes"] == 1200, reopened
    assert reopened["earned_live_minutes"] == 1200, reopened
    assert reopened["carryover_out_general_minutes"] == 0, reopened
    assert reopened["carryover_out_ethics_minutes"] == 0, reopened
    attorney = read_attorney(state["attorney"]["id"])
    assert attorney["pending_recertification_count"] == 1, attorney


def test_course_revocation_rewrites_the_successor_carryover_to_zero(api):
    """The reversion then cascades in exactly the conserved way described
    above: any cycle whose `previous_cycle_id` names the reopened cycle has
    its `carryover_in_general_minutes` and `carryover_in_ethics_minutes`
    rewritten to zero and its own figures re-derived. The effective total for
    the period is `earned_countable_minutes` plus
    `carryover_in_general_minutes` plus `carryover_in_ethics_minutes` —
    carried-in ethics minutes count toward the general requirement as well as
    their own. The four shortfalls are then: the total shortfall, being
    `required_total_minutes` less the effective total, floored at zero; the
    ethics shortfall, being `required_ethics_minutes` less the effective
    ethics figure, floored at zero; the technology shortfall, being
    `required_technology_minutes` less `earned_technology_minutes`, floored at
    zero; and the bias shortfall, being `required_bias_minutes` less
    `earned_bias_minutes`, floored at zero.

    Design: Difficulty/transitive_cascade/substantiated_course_complaint_unwinds_a_satisfied_cycle_and_the_successor_carryover
    """
    state = build_certified_cycle_with_successor()

    substantiate(api, state["complaint"]["id"])

    successor = read_cycle(state["cycle_two"]["id"])
    assert successor["carryover_in_general_minutes"] == 0, successor
    assert successor["carryover_in_ethics_minutes"] == 0, successor
    summary = read_cycle_summary(state["cycle_two"]["id"])
    assert summary["projected_final_deficiency_total_minutes"] == 1800, summary


def test_course_revocation_leaves_the_other_session_and_its_verified_record_alone(api):
    """Against a course, the course moves to `REVOKED` from `APPROVED`,
    `SUSPENDED_PENDING_REVIEW` or `EXPIRED`; that revocation copies the
    `disposition_reason` into the course's `denial_reason` and voids every
    `VERIFIED` credit record earned at that course, stamping each with a
    `void_reason` of `COURSE_REVOKED`; each void re-runs the owning cycle's
    credit application; and that re-run can revert a `SATISFIED` cycle to
    `OPEN` as §3.8 describes, which in turn rewrites the successor cycle's
    `carryover_in_general_minutes` and `carryover_in_ethics_minutes` to zero
    and re-derives its figures. On a course: `credited_minutes_total` is the
    sum of its allocation minutes, which must equal `total_minutes`, and
    `verified_credit_record_count` is the number of credit records for that
    course currently in the verified state — incremented when a record becomes
    verified and decremented when a verified record is voided. The **final**
    variant includes only those in `VERIFIED`.

    Design: Difficulty/transitive_cascade/substantiated_course_complaint_unwinds_a_satisfied_cycle_and_the_successor_carryover
    """
    state = build_certified_cycle_with_successor()

    substantiate(api, state["complaint"]["id"])

    untouched_course = read_course(state["course_one"]["id"])
    assert untouched_course["status"] == "APPROVED", untouched_course
    assert untouched_course["denial_reason"] is None, untouched_course
    assert untouched_course["verified_credit_record_count"] == 1, untouched_course
    untouched_record = read_credit_record(state["record_one"]["id"])
    assert untouched_record["status"] == "VERIFIED", untouched_record
    assert untouched_record["void_reason"] is None, untouched_record
    assert untouched_record["countable_minutes"] == 1200, untouched_record


def test_course_revocation_rescores_the_sponsor_without_moving_its_accreditation(api):
    """When the revoked course has a sponsoring provider, that provider also
    takes `substantiated_complaint_count` plus one and a recomputed
    `risk_score`. And a substantiated complaint whose subject is a *course*
    raises the sponsoring provider's `substantiated_complaint_count` and
    re-scores it, but never moves its `accreditation_status`. The complaint
    rate is `substantiated_complaint_count` divided by three, capped at 1.0 —
    three substantiated complaints saturate the term. `risk_score` is then the
    delinquency rate weighted at 0.35, plus the complaint rate weighted at
    0.30, plus the finding rate weighted at 0.25, plus the staleness rate
    weighted at 0.10, and the sum is rounded half-up to two decimal places.

    Design: Difficulty/transitive_cascade/substantiated_course_complaint_unwinds_a_satisfied_cycle_and_the_successor_carryover
    """
    state = build_certified_cycle_with_successor()

    substantiate(api, state["complaint"]["id"])

    sponsor = read_provider(state["provider"]["id"])
    assert sponsor["accreditation_status"] == "ACCREDITED", sponsor
    assert sponsor["substantiated_complaint_count"] == 1, sponsor
    assert sponsor["risk_score"] == pytest.approx(0.1, abs=1e-9), sponsor


AUDITOR = "board-audit-7"


def build_sponsor_awaiting_a_sanction():
    """An accredited sponsor with three self-certified self-study modules, one
    attorney holding three claims against them — one already verified by the
    minted code, two still awaiting an affirmation — and an audit engagement
    standing at findings issued. Returns a dict of the rows."""
    provider = create_accredited_provider(
        name="Summit Bar Review Services", provider_type="GOVERNMENT"
    )
    course_one = create_self_certified_course(
        provider,
        title="Self-Study: Municipal Practice",
        delivery_format="SELF_STUDY",
        total_minutes=300,
        presented_at="2026-06-10T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("GENERAL", 300)],
    )
    course_two = create_self_certified_course(
        provider,
        title="Self-Study: Records Retention",
        delivery_format="SELF_STUDY",
        total_minutes=180,
        presented_at="2026-06-20T09:00:00Z",
        attendance_verification_method="AFFIRMATION_ONLY",
        credit_allocations=[credit_allocation_entry("GENERAL", 180)],
    )
    course_three = create_self_certified_course(
        provider,
        title="Self-Study: Open Meetings Act",
        delivery_format="SELF_STUDY",
        total_minutes=240,
        presented_at="2026-06-25T09:00:00Z",
        attendance_verification_method="ATTENDANCE_CODE",
        credit_allocations=[credit_allocation_entry("GENERAL", 240)],
    )
    attorney = create_attorney(
        bar_number="BAR-7007",
        full_name="Rafael Ortega",
        admission_date="2013-11-01T00:00:00Z",
        compliance_group="GROUP_3",
        principal_office_jurisdiction="ST",
    )
    cycle = create_cycle(
        attorney["id"], "2026-01-01T00:00:00Z", "2028-01-01T00:00:00Z"
    )
    verified_record = file_code_verified_record(
        attorney, course_three, attended_minutes=240,
        completion_date="2026-07-01T00:00:00Z",
    )
    pending_record_one = file_credit_record(
        attorney, course_one["id"], verification_method="AFFIRMATION",
        attended_minutes=300, completion_date="2026-07-05T00:00:00Z",
        certificate_reference=None,
    )
    pending_record_two = file_credit_record(
        attorney, course_two["id"], verification_method="AFFIRMATION",
        attended_minutes=180, completion_date="2026-07-10T00:00:00Z",
        certificate_reference=None,
    )
    audit = open_audit(
        provider["id"], "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z",
        trigger_type="RANDOM",
    )
    audit = audit_action(audit["id"], "DRAW_SAMPLE", audit["version"])
    audit = audit_action(
        audit["id"], "ISSUE_FINDINGS", audit["version"], findings_count=2
    )
    # Guards on the starting position: the two waiting claims are still live,
    # so the provisional run has already spent the self-study allowance.
    assert audit["status"] == "FINDINGS_ISSUED", audit
    assert audit["sample_size"] == 2, audit
    assert read_credit_record(pending_record_one["id"])["status"] == "PENDING_VERIFICATION"
    assert read_credit_record(pending_record_two["id"])["status"] == "PENDING_VERIFICATION"
    assert read_cycle(cycle["id"])["earned_countable_minutes"] == 360, read_cycle(cycle["id"])
    return {
        "provider": provider,
        "course_one": course_one,
        "course_two": course_two,
        "course_three": course_three,
        "attorney": attorney,
        "cycle": cycle,
        "verified_record": verified_record,
        "pending_record_one": pending_record_one,
        "pending_record_two": pending_record_two,
        "audit": audit,
    }


def close_sanctioned(api, audit):
    """The board decision that heads the cascade."""
    response = api.provider_audit_action(
        audit["id"],
        {
            "action": "CLOSE_SANCTIONED",
            "expected_audit_version": audit["version"],
            "sanction_type": "SUSPENSION",
        },
        make_board_admin_headers(AUDITOR),
    )
    return validate_success(response, expected_status=200)


def test_audit_suspension_sanction_suspends_the_sponsor_and_its_self_certified_courses(api):
    """`CLOSE_SANCTIONED` requires `findings_count` of at least one and a
    supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps
    `closed_at`, records the sanction, writes `last_audit_closed_at`, and
    assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the
    provider for 250000 cents. `PROBATION` then moves the provider `ACCREDITED
    → PROBATIONARY`; `SUSPENSION` moves it to `SUSPENDED` from either
    `ACCREDITED` or `PROBATIONARY`, which suspends that sponsor's
    self-certified courses, which in turn rejects those courses' credit records
    still awaiting verification — the same chain §3.1 describes. Both branches
    set `self_certification_enabled` to false and both run the
    sponsor-suspension cascade: every course of that sponsor that is currently
    `APPROVED`, was approved through the self-certification pathway, and has
    not yet reached its `expires_at` moves `APPROVED → SUSPENDED_PENDING_REVIEW`.
    The only difference between the branches is scoring: leaving `ACCREDITED`
    also switches `risk_score_variant` to `REVIEWED_WEIGHTING` and re-scores
    under it, whereas a sponsor leaving `PROBATIONARY` was already being scored
    that way.

    Design: Difficulty/transitive_cascade/audit_suspension_sanction_rejects_only_the_pending_credit_records_of_suspended_courses
    """
    state = build_sponsor_awaiting_a_sanction()

    closed = close_sanctioned(api, state["audit"])

    assert closed["status"] == "SANCTIONED", closed
    assert closed["sanction_type"] == "SUSPENSION", closed
    assert_same_instant(closed["closed_at"], "2026-08-01T00:00:00Z", "audit closed_at")
    sponsor = read_provider(state["provider"]["id"])
    assert sponsor["accreditation_status"] == "SUSPENDED", sponsor
    assert sponsor["self_certification_enabled"] is False, sponsor
    assert sponsor["risk_score_variant"] == "REVIEWED_WEIGHTING", sponsor
    assert_same_instant(
        sponsor["last_audit_closed_at"], "2026-08-01T00:00:00Z", "last_audit_closed_at"
    )
    for key in ("course_one", "course_two", "course_three"):
        suspended = read_course(state[key]["id"])
        assert suspended["status"] == "SUSPENDED_PENDING_REVIEW", suspended


def test_audit_suspension_rejects_only_the_records_still_awaiting_verification(api):
    """Sponsor suspension or lapse moves a self-certified `APPROVED` course
    whose `expires_at` is still in the future to `SUSPENDED_PENDING_REVIEW`,
    and that move itself rejects every credit record for that course still
    awaiting verification, stamping each with a `void_reason` of
    `SPONSOR_NOT_IN_GOOD_STANDING` and re-running the owning cycle's credit
    application. The **provisional** variant includes the cycle's records in
    `PENDING_VERIFICATION` and `VERIFIED`. Records in `REJECTED` or `VOIDED`
    participate in neither variant, ever. While a cycle's `credit_status` is
    `OPEN`, the provisional result is what gets persisted into the cycle's
    `earned_*` fields and into each record's `countable_minutes`.

    Design: Difficulty/transitive_cascade/audit_suspension_sanction_rejects_only_the_pending_credit_records_of_suspended_courses
    """
    state = build_sponsor_awaiting_a_sanction()

    close_sanctioned(api, state["audit"])

    for key in ("pending_record_one", "pending_record_two"):
        rejected = read_credit_record(state[key]["id"])
        assert rejected["status"] == "REJECTED", rejected
        assert rejected["void_reason"] == "SPONSOR_NOT_IN_GOOD_STANDING", rejected
        assert rejected["countable_minutes"] == 0, rejected
    cycle = read_cycle(state["cycle"]["id"])
    assert cycle["earned_countable_minutes"] == 240, cycle
    assert cycle["credit_status"] == "OPEN", cycle


def test_audit_suspension_leaves_the_already_verified_record_alone(api):
    """Sponsor suspension or lapse moves a self-certified `APPROVED` course
    whose `expires_at` is still in the future to `SUSPENDED_PENDING_REVIEW`,
    and that move itself rejects every credit record for that course still
    awaiting verification, stamping each with a `void_reason` of
    `SPONSOR_NOT_IN_GOOD_STANDING` and re-running the owning cycle's credit
    application. On a course: `credited_minutes_total` is the sum of its
    allocation minutes, which must equal `total_minutes`, and
    `verified_credit_record_count` is the number of credit records for that
    course currently in the verified state — incremented when a record becomes
    verified and decremented when a verified record is voided. Records in
    `REJECTED` or `VOIDED` participate in neither variant, ever.

    Design: Difficulty/transitive_cascade/audit_suspension_sanction_rejects_only_the_pending_credit_records_of_suspended_courses
    """
    state = build_sponsor_awaiting_a_sanction()

    close_sanctioned(api, state["audit"])

    survivor = read_credit_record(state["verified_record"]["id"])
    assert survivor["status"] == "VERIFIED", survivor
    assert survivor["void_reason"] is None, survivor
    assert survivor["countable_minutes"] == 240, survivor
    assert read_course(state["course_three"]["id"])["verified_credit_record_count"] == 1
    assert read_course(state["course_one"]["id"])["verified_credit_record_count"] == 0


def test_audit_suspension_assesses_the_sanction_fee_against_the_sponsor_and_rescores_it(api):
    """`CLOSE_SANCTIONED` requires `findings_count` of at least one and a
    supplied `sanction_type` of `PROBATION` or `SUSPENSION`; it stamps
    `closed_at`, records the sanction, writes `last_audit_closed_at`, and
    assesses a `FeeAssessment` of `fee_type` `AUDIT_SANCTION` against the
    provider for 250000 cents. Attorney-side assessments carry `attorney_id`
    and, where a specific compliance period produced them, `cycle_id`;
    provider-side assessments carry `provider_id` instead and leave the
    attorney fields null. An assessment created by a batch run also records
    `assessed_by_sweep_id`, the identifier of the run that created it;
    assessments created by any other action leave that field null. The finding
    rate is `audit_findings_count` divided by a denominator that depends on the
    variant below, again capped at 1.0. Under `REVIEWED_WEIGHTING`, used for
    every other `accreditation_status` — `APPLIED`, `PROBATIONARY`,
    `SUSPENDED`, `LAPSED` or `DENIED` — the denominator is
    `courses_total_count` (again treated as one when zero), because every
    course such a sponsor offers passed board review. `risk_score` is then the
    delinquency rate weighted at 0.35, plus the complaint rate weighted at
    0.30, plus the finding rate weighted at 0.25, plus the staleness rate
    weighted at 0.10, and the sum is rounded half-up to two decimal places. On
    an audit action that cascades a change to the provider's own
    `accreditation_status`, the recomputation happens **after** that cascade
    lands, so the variant chosen reflects the provider's post-cascade standing
    rather than its standing on arrival.

    Design: Difficulty/transitive_cascade/audit_suspension_sanction_rejects_only_the_pending_credit_records_of_suspended_courses
    """
    state = build_sponsor_awaiting_a_sanction()

    close_sanctioned(api, state["audit"])

    assessments = list_fee_assessments(
        provider_id=state["provider"]["id"], fee_type="AUDIT_SANCTION"
    )
    assert len(assessments) == 1, assessments
    sanction_fee = assessments[0]
    assert sanction_fee["amount_cents"] == 250000, sanction_fee
    assert sanction_fee["status"] == "ASSESSED", sanction_fee
    assert sanction_fee["provider_id"] == state["provider"]["id"], sanction_fee
    assert sanction_fee["attorney_id"] is None, sanction_fee
    assert sanction_fee["cycle_id"] is None, sanction_fee
    assert sanction_fee["assessed_by_sweep_id"] is None, sanction_fee
    sponsor = read_provider(state["provider"]["id"])
    assert sponsor["audit_findings_count"] == 2, sponsor
    assert sponsor["courses_total_count"] == 3, sponsor
    assert sponsor["risk_score"] == pytest.approx(0.17, abs=1e-9), sponsor
    assert read_audit(state["audit"]["id"])["findings_count"] == 2
