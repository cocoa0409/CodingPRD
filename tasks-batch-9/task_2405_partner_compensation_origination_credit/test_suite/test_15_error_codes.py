"""Refusal codes: the twelve not-found codes, the claim, assessment, ballot and
award lifecycle refusals, the pool that cannot fund publication, the departure
and transition refusals, and the header gate that runs before the role gate."""

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    UNKNOWN_UUID,
    abstain_ballot_payload,
    adjudicate_claim_payload,
    advance_cycle,
    advance_cycle_payload,
    approx2,
    approx4,
    assign_peer_review,
    cast_ballot,
    cast_ballot_payload,
    create_assessment,
    create_billable_record,
    create_committee_member,
    create_credit_arbiter,
    create_credit_claim_payload,
    create_cycle,
    create_cycle_payload,
    create_matter,
    create_partner,
    create_peer_review_payload,
    create_self_assessment_payload,
    cycle_version,
    dispute_claim_payload,
    draw_ledger,
    draw_run_payload,
    effectuate_transition,
    effectuate_transition_payload,
    file_claim,
    find_allocation,
    find_award,
    find_ballot,
    is_iso8601_timestamp,
    make_committee_member_headers,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    make_headers_with_empty_role,
    make_headers_without_role,
    make_headers_without_user_id,
    make_partner_headers,
    make_unrecognised_role_headers,
    matter_allocations,
    matter_version,
    notice_of_departure_payload,
    peer_review_recuse_payload,
    peer_review_score_payload,
    read_assessment,
    read_cycle,
    read_matter,
    read_partner,
    read_claim,
    read_transition,
    review_decision_payload,
    score_peer_review,
    setup_accepted_assessment,
    setup_deliberation_cycle,
    setup_proposed_transition,
    setup_published_discretionary_award,
    submit_assessment,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
    verify_record,
    void_transition,
    void_transition_payload,
)


def test_unknown_ids_report_the_cycle_partner_matter_and_allocation_codes(api):
    """PRD 2.10: "Identifiers in a path are resolved strictly left to right, and
    the first one that fails to resolve determines the response." "A request for
    a credit allocation under a matter that does not exist therefore reports the
    missing matter, not the missing allocation."

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_uuid
    """
    admin = make_cycle_admin_headers()

    validate_error(
        api.get_cycle(UNKNOWN_UUID, admin), ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_partner(UNKNOWN_UUID, admin), ApiErrorId.ERR_PARTNER_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_matter(UNKNOWN_UUID, admin), ApiErrorId.ERR_MATTER_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_credit_allocation(UNKNOWN_UUID, admin),
        ApiErrorId.ERR_ALLOCATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_matter_credit_allocations(UNKNOWN_UUID, admin),
        ApiErrorId.ERR_MATTER_NOT_FOUND.value,
        404,
    )


def test_unknown_ids_report_the_record_claim_assessment_and_review_codes(api):
    """PRD 2.10: "The resulting 404 carries the code belonging to that
    identifier's own resource type: `ERR_CYCLE_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_MATTER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND` or `ERR_TRANSITION_NOT_FOUND`."

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_uuid
    """
    admin = make_cycle_admin_headers()

    validate_error(
        api.get_contribution_record(UNKNOWN_UUID, admin),
        ApiErrorId.ERR_RECORD_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_credit_claim(UNKNOWN_UUID, admin), ApiErrorId.ERR_CLAIM_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_self_assessment(UNKNOWN_UUID, admin),
        ApiErrorId.ERR_ASSESSMENT_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.get_peer_review(UNKNOWN_UUID, admin), ApiErrorId.ERR_REVIEW_NOT_FOUND.value, 404
    )


def test_unknown_ids_report_the_ballot_award_payment_and_transition_codes(api):
    """PRD 2.10: "The resulting 404 carries the code belonging to that
    identifier's own resource type: `ERR_CYCLE_NOT_FOUND`,
    `ERR_PARTNER_NOT_FOUND`, `ERR_MATTER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND` or `ERR_TRANSITION_NOT_FOUND`."

    Design: Corner/errors/every_not_found_code_is_reachable_with_an_unknown_uuid
    """
    admin = make_cycle_admin_headers()

    validate_error(
        api.get_ballot(UNKNOWN_UUID, admin), ApiErrorId.ERR_BALLOT_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_award(UNKNOWN_UUID, admin), ApiErrorId.ERR_AWARD_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_draw_payment(UNKNOWN_UUID, admin), ApiErrorId.ERR_PAYMENT_NOT_FOUND.value, 404
    )
    validate_error(
        api.get_credit_transition(UNKNOWN_UUID, admin),
        ApiErrorId.ERR_TRANSITION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api.list_draw_payments(UNKNOWN_UUID, admin), ApiErrorId.ERR_AWARD_NOT_FOUND.value, 404
    )


def test_claim_lifecycle_refusals_end_with_the_arbiter_conflict(api):
    """PRD 3.4: "A claim that is not in `SUBMITTED` yields
    `ERR_CLAIM_NOT_DISPUTABLE`; a partner attempting to dispute their own claim
    is refused with `ERR_DISPUTER_IS_CLAIMANT`; and the cycle must still be in
    `OPEN_INTAKE`, failing which the window error applies." "Whatever the
    decision, the arbiter must supply the `expected_matter_version` required by
    section 2.8, and no arbiter may decide a claim in which they are the
    claimant, the disputer, or the claimed matter's billing or responsible
    attorney — such a request is refused with `ERR_ARBITER_CONFLICT`."

    Design: Corner/errors/claim_lifecycle_refusals_including_the_arbiter_conflict
    """
    cycle = create_cycle(api)
    claimant = create_partner(api, full_name="Ada Origin")
    rival = create_partner(api, full_name="Rip Rival", practice_group="TAX")
    arbiter = create_credit_arbiter(api, full_name="Arya Arbiter", practice_group="REGULATORY")
    matter = create_matter(
        api,
        billing_attorney_id=claimant["id"],
        responsible_attorney_id=arbiter["id"],
    )
    opening_version = matter["version"]

    claim = file_claim(
        api,
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        claimant_id=claimant["id"],
        requested_pct=100.00,
    )

    duplicate = api.create_credit_claim(
        create_credit_claim_payload(
            cycle_id=cycle["id"],
            matter_id=matter["id"],
            requested_pct=50.00,
            narrative="A second claim over the same matter in the same cycle.",
        ),
        make_partner_headers(claimant["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)

    early_dispute = api.dispute_credit_claim(
        claim["id"], dispute_claim_payload(), make_partner_headers(rival["id"])
    )
    validate_error(early_dispute, ApiErrorId.ERR_CLAIM_NOT_DISPUTABLE.value, 409)

    submitted = submit_claim(api, claim["id"], claimant["id"])
    assert submitted["state"] == "SUBMITTED"

    self_dispute = api.dispute_credit_claim(
        claim["id"], dispute_claim_payload(), make_partner_headers(claimant["id"])
    )
    validate_error(self_dispute, ApiErrorId.ERR_DISPUTER_IS_CLAIMANT.value, 403)

    conflicted = api.adjudicate_credit_claim(
        claim["id"],
        adjudicate_claim_payload(
            "ALLOCATE", matter_version(api, matter["id"]), approved_pct=100.00
        ),
        make_credit_arbiter_headers(arbiter["id"]),
    )
    validate_error(conflicted, ApiErrorId.ERR_ARBITER_CONFLICT.value, 403)

    unchanged_claim = read_claim(api, claim["id"])
    assert unchanged_claim["state"] == "SUBMITTED"
    assert unchanged_claim["disputing_partner_id"] is None
    unchanged_matter = read_matter(api, matter["id"])
    assert unchanged_matter["origination_pct_assigned"] == approx2(0.00)
    assert unchanged_matter["version"] == opening_version


def test_assessment_and_review_refusals_while_the_stage_windows_are_shut(api):
    """PRD 3.6: "The cycle must be in stage `SELF_ASSESSMENT` and the logical
    clock's current date must fall on or before that cycle's
    `assessment_deadline_on`; either failure reports
    `ERR_ASSESSMENT_WINDOW_CLOSED`." "One assignment may exist per pairing of
    assessment and reviewer, a duplicate being
    `ERR_DUPLICATE_REVIEW_ASSIGNMENT`, and a partner may not be assigned to
    review their own assessment — that attempt is `ERR_SELF_REVIEW_FORBIDDEN`."

    Design: Corner/errors/assessment_and_peer_review_refusals_across_the_stage_windows
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(api)
    subject = create_partner(api, full_name="Ada Origin")
    member = create_committee_member(api, full_name="Cass Committee", practice_group="TAX")
    assessment = create_assessment(api, cycle_id=cycle["id"], partner_id=subject["id"])

    duplicate = api.create_self_assessment(
        create_self_assessment_payload(
            cycle_id=cycle["id"],
            narrative="A second account of the same year for the same cycle.",
        ),
        make_partner_headers(subject["id"]),
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ASSESSMENT.value, 409)

    premature_accept = api.review_decision_self_assessment(
        assessment["id"],
        review_decision_payload("ACCEPT"),
        make_committee_member_headers(member["id"]),
    )
    validate_error(premature_accept, ApiErrorId.ERR_ASSESSMENT_NOT_REVIEWABLE.value, 409)

    self_review = api.create_peer_review(
        create_peer_review_payload(assessment["id"], subject["id"]), admin
    )
    validate_error(self_review, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN.value, 403)

    review = assign_peer_review(api, assessment["id"], member["id"])
    duplicate_review = api.create_peer_review(
        create_peer_review_payload(assessment["id"], member["id"]), admin
    )
    validate_error(duplicate_review, ApiErrorId.ERR_DUPLICATE_REVIEW_ASSIGNMENT.value, 409)

    early_score = api.decide_peer_review(
        review["id"], peer_review_score_payload(), make_partner_headers(member["id"])
    )
    validate_error(early_score, ApiErrorId.ERR_REVIEW_WINDOW_CLOSED.value, 409)

    early_submit = api.submit_self_assessment(
        assessment["id"], {}, make_partner_headers(subject["id"])
    )
    validate_error(early_submit, ApiErrorId.ERR_ASSESSMENT_WINDOW_CLOSED.value, 409)

    untouched = read_assessment(api, assessment["id"])
    assert untouched["state"] == "DRAFT"
    assert untouched["scored_review_count"] == 0
    assert untouched["mean_peer_score"] == approx4(0.0000)


def test_a_submitted_assessment_and_a_scored_review_refuse_a_second_decision(api):
    """PRD 3.6: "Only the owning partner may submit, and only a `DRAFT` row may
    be submitted — otherwise `ERR_ASSESSMENT_NOT_MUTABLE`." "The reviewer must be
    the review's own `reviewer_partner_id`, the review must currently be
    `ASSIGNED` (otherwise `ERR_REVIEW_ALREADY_DECIDED`), the reviewer must not be
    the assessment's own partner (otherwise `ERR_SELF_REVIEW_FORBIDDEN`), and the
    assessment's cycle must be in `SELF_ASSESSMENT` or `PEER_REVIEW` (otherwise
    `ERR_REVIEW_WINDOW_CLOSED`)."

    Design: Corner/errors/assessment_and_peer_review_refusals_across_the_stage_windows
    """
    cycle = create_cycle(api)
    subject = create_partner(api, full_name="Ada Origin")
    member = create_committee_member(api, full_name="Cass Committee", practice_group="TAX")
    assessment = create_assessment(api, cycle_id=cycle["id"], partner_id=subject["id"])
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    review = assign_peer_review(api, assessment["id"], member["id"])

    submitted = submit_assessment(api, assessment["id"], subject["id"])
    assert submitted["state"] == "SUBMITTED"

    resubmit = api.submit_self_assessment(
        assessment["id"], {}, make_partner_headers(subject["id"])
    )
    validate_error(resubmit, ApiErrorId.ERR_ASSESSMENT_NOT_MUTABLE.value, 409)

    scored = score_peer_review(api, review["id"], member["id"], 4, 4, 4)
    assert scored["state"] == "SCORED"
    assert read_assessment(api, assessment["id"])["scored_review_count"] == 1

    late_recusal = api.decide_peer_review(
        review["id"], peer_review_recuse_payload(), make_partner_headers(member["id"])
    )
    validate_error(late_recusal, ApiErrorId.ERR_REVIEW_ALREADY_DECIDED.value, 409)

    unchanged = validate_success(api.get_peer_review(review["id"], make_cycle_admin_headers()))
    assert unchanged["state"] == "SCORED"
    assert unchanged["composite_score"] == approx4(4.0000)


def test_a_proposed_award_refuses_a_draw_a_true_up_and_publication_without_quorum(api):
    """PRD 3.9: "Three conditions guard it: the award's `award_state` must be
    `PUBLISHED`, and the award's cycle must be in `AWARDS_PUBLISHED` or
    `TRUE_UP_OPEN` — either failure is `ERR_AWARD_NOT_DRAWABLE` — and no
    un-reversed ledger row of kind `SCHEDULED_DRAW` may already exist on this
    award for that pairing of year and month, a collision being
    `ERR_DRAW_PERIOD_ALREADY_PAID`."

    Design: Corner/errors/ballot_and_award_readiness_refusals_including_the_reopen_bound
    """
    admin = make_cycle_admin_headers()
    scenario = setup_deliberation_cycle(api)
    award = find_award(api, scenario["cycle"]["id"], scenario["subject"]["id"])
    assert award["award_state"] == "PROPOSED"

    early_draw = api.draw_run(award["id"], draw_run_payload(2026, 1), admin)
    validate_error(early_draw, ApiErrorId.ERR_AWARD_NOT_DRAWABLE.value, 409)

    early_true_up = api.true_up(award["id"], {}, admin)
    validate_error(early_true_up, ApiErrorId.ERR_AWARD_NOT_TRUE_UP_READY.value, 409)

    without_quorum = api.advance_cycle(
        scenario["cycle"]["id"], advance_cycle_payload("AWARDS_PUBLISHED"), admin
    )
    validate_error(without_quorum, ApiErrorId.ERR_QUORUM_NOT_MET.value, 409)

    cycle = read_cycle(api, scenario["cycle"]["id"])
    assert cycle["state"] == "DELIBERATION"
    assert cycle["discretionary_pool_cents"] == 0
    assert draw_ledger(api, award["id"]) == []


def test_a_ballot_refuses_points_above_the_cap_and_a_second_decision(api):
    """PRD 3.7: "Separately from the schema range, a `points_proposed` above the
    per-ballot ceiling of 1000.00 points is a business-constraint breach reported
    as `ERR_POINTS_CAP_EXCEEDED` rather than as a malformed payload — and when a
    committee member casts their own ballot with points above that ceiling, the
    self-vote refusal wins, as section 2.11 sets out." "In every case the ballot
    must be in `PENDING`, failing which `ERR_BALLOT_ALREADY_DECIDED`; the acting
    member must be the ballot's own `committee_member_id`, failing which the
    ownership rule applies; and the ballot's cycle must be in stage
    `DELIBERATION`, failing which `ERR_INVALID_CYCLE_TRANSITION`."

    Design: Corner/errors/ballot_and_award_readiness_refusals_including_the_reopen_bound
    """
    scenario = setup_deliberation_cycle(api)
    cycle_id = scenario["cycle"]["id"]
    member = scenario["committee"][0]
    ballot = scenario["ballots"][0]
    version_before = cycle_version(api, cycle_id)

    over_cap = api.cast_ballot(
        ballot["id"],
        cast_ballot_payload(1500.00, version_before),
        make_committee_member_headers(member["id"]),
    )
    validate_error(over_cap, ApiErrorId.ERR_POINTS_CAP_EXCEEDED.value, 409)

    cast = cast_ballot(
        api,
        ballot_id=ballot["id"],
        committee_member_id=member["id"],
        points_proposed=800.00,
        expected_cycle_version=version_before,
    )
    assert cast["state"] == "CAST"
    assert cast["points_proposed"] == approx2(800.00)

    second_decision = api.cast_ballot(
        ballot["id"],
        abstain_ballot_payload(cycle_version(api, cycle_id)),
        make_committee_member_headers(member["id"]),
    )
    validate_error(second_decision, ApiErrorId.ERR_BALLOT_ALREADY_DECIDED.value, 409)

    still_cast = find_ballot(api, cycle_id, scenario["subject"]["id"], member["id"])
    assert still_cast["state"] == "CAST"
    assert still_cast["points_proposed"] == approx2(800.00)


def test_a_cycle_reopens_once_and_then_refuses_both_a_reopen_and_closure(api):
    """PRD 3.8: "`AWARDS_PUBLISHED → DELIBERATION` is the reconsideration reopen,
    and it is bounded twice over: the cycle's `reopen_count` must still be below
    1, and no award of the cycle may have reached payment state `TRUED_UP` or
    `SETTLED`; either failure is `ERR_CYCLE_NOT_REOPENABLE`." "`TRUE_UP_OPEN →
    CLOSED` requires the cycle's `unsettled_award_count` — the number of its
    awards whose payment state is anything other than `SETTLED` — to be exactly
    0, failing which `ERR_AWARDS_NOT_SETTLED`."

    Design: Corner/errors/ballot_and_award_readiness_refusals_including_the_reopen_bound
    """
    admin = make_cycle_admin_headers()
    scenario = setup_published_discretionary_award(api)
    cycle_id = scenario["cycle"]["id"]

    reopened = advance_cycle(api, cycle_id, "DELIBERATION")
    assert reopened["state"] == "DELIBERATION"
    assert reopened["reopen_count"] == 1
    republished = advance_cycle(api, cycle_id, "AWARDS_PUBLISHED")
    assert republished["state"] == "AWARDS_PUBLISHED"

    second_reopen = api.advance_cycle(cycle_id, advance_cycle_payload("DELIBERATION"), admin)
    validate_error(second_reopen, ApiErrorId.ERR_CYCLE_NOT_REOPENABLE.value, 409)

    true_up_open = advance_cycle(api, cycle_id, "TRUE_UP_OPEN")
    assert true_up_open["state"] == "TRUE_UP_OPEN"
    assert true_up_open["unsettled_award_count"] == 1

    early_close = api.advance_cycle(cycle_id, advance_cycle_payload("CLOSED"), admin)
    validate_error(early_close, ApiErrorId.ERR_AWARDS_NOT_SETTLED.value, 409)

    cycle = read_cycle(api, cycle_id)
    assert cycle["state"] == "TRUE_UP_OPEN"
    assert cycle["reopen_count"] == 1
    assert cycle["confidentiality_locked"] is False


def test_verifying_an_already_verified_record_is_refused(api):
    """PRD 3.3: "Verification sets `verified` to true and `verified_at` to the
    logical clock's current instant; a record whose `verified` is already true
    cannot be verified twice and the second attempt yields
    `ERR_RECORD_ALREADY_VERIFIED` with HTTP 409."

    Design: Corner/errors/verifying_an_already_verified_record_is_refused
    """
    cycle = create_cycle(api)
    partner = create_partner(api, full_name="Ada Origin")
    matter = create_matter(api, billing_attorney_id=partner["id"])
    record = create_billable_record(
        api,
        partner_id=partner["id"],
        cycle_id=cycle["id"],
        matter_id=matter["id"],
        hours=10.00,
    )

    verified = verify_record(api, record["id"])
    assert verified["verified"] is True
    assert is_iso8601_timestamp(verified["verified_at"])
    assert verified["verified_at"].startswith("2026-08-01T00:00:00")

    again = api.verify_contribution_record(record["id"], {}, make_cycle_admin_headers())
    validate_error(again, ApiErrorId.ERR_RECORD_ALREADY_VERIFIED.value, 409)

    unchanged = validate_success(
        api.get_contribution_record(record["id"], make_cycle_admin_headers())
    )
    assert unchanged["verified"] is True
    assert unchanged["version"] == verified["version"]
    assert read_partner(api, partner["id"])["verified_billable_hours"] == approx2(10.00)
    working = [
        row for row in matter_allocations(api, matter["id"]) if row["credit_role"] == "WORKING"
    ]
    assert len(working) == 1
    assert working[0]["credit_pct"] == approx2(100.00)


def test_an_unfundable_lockstep_obligation_stops_publication(api):
    """PRD 3.8: "If any shortfall survives both cuts the waterfall fails with
    `ERR_POOL_INSUFFICIENT`; otherwise `formula_pool_cents` is 0." "Every subject
    partner that has ballots in this cycle must have at least two of them in
    `CAST`, failing which `ERR_QUORUM_NOT_MET`; and the pool waterfall must close
    without residual deficit, failing which `ERR_POOL_INSUFFICIENT` and the
    entire advance is rejected with all four pool fields left at their pre-call
    values."

    Design: Corner/errors/an_unfundable_lockstep_obligation_stops_publication
    """
    admin = make_cycle_admin_headers()
    cycle = create_cycle(
        api,
        distributable_pool_cents=100_000_000,
        lockstep_unit_cents=20_000_000,
        discretionary_pool_pct=0.5000,
    )
    lockstep = create_partner(
        api,
        full_name="Lee Lockstep",
        compensation_model="LOCKSTEP",
        lockstep_step=10,
    )
    reviewers = [
        create_committee_member(api, full_name=f"Cass Committee {n + 1}") for n in range(2)
    ]
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    setup_accepted_assessment(
        api,
        cycle_id=cycle["id"],
        subject_id=lockstep["id"],
        reviewer_ids=[member["id"] for member in reviewers],
    )
    advance_cycle(api, cycle["id"], "PEER_REVIEW")
    deliberating = advance_cycle(api, cycle["id"], "DELIBERATION")

    unfundable = api.advance_cycle(
        cycle["id"], advance_cycle_payload("AWARDS_PUBLISHED"), admin
    )
    validate_error(unfundable, ApiErrorId.ERR_POOL_INSUFFICIENT.value, 409)

    unchanged = read_cycle(api, cycle["id"])
    assert unchanged["state"] == "DELIBERATION"
    assert unchanged["version"] == deliberating["version"]
    assert unchanged["lockstep_reserved_cents"] == 0
    assert unchanged["discretionary_pool_cents"] == 0
    assert unchanged["formula_pool_cents"] == 0
    assert unchanged["haircut_applied_pct"] == approx4(0.0000)

    award = find_award(api, cycle["id"], lockstep["id"])
    assert award["award_state"] == "PROPOSED"
    assert award["basis_model"] == "LOCKSTEP"
    assert award["target_award_cents"] == 0


def test_notice_and_effectuation_refuse_a_second_attempt(api):
    """PRD 3.1: "Notice may only be given for a partner whose `status` is
    currently `ACTIVE`, and a second attempt is refused with
    `ERR_PARTNER_NOT_DEPARTING`; the effective date must fall on or after the
    logical clock's current date, and an earlier date is rejected as a malformed
    request." "A transition that is not currently `PROPOSED` is refused with
    `ERR_TRANSITION_NOT_PENDING`; a departing partner whose `status` is not
    `NOTICE_GIVEN` yields `ERR_PARTNER_NOT_DEPARTING`; a successor whose `status`
    is not `ACTIVE`, or who is the departing partner themselves, yields
    `ERR_SUCCESSOR_NOT_ELIGIBLE`; and an `effective_on` that is not strictly
    later than the departing originating allocation's `credit_from` is rejected
    as a malformed request, since a transfer cannot take effect before the credit
    it transfers began."

    Design: Corner/errors/departure_and_credit_transition_refusals
    """
    admin = make_cycle_admin_headers()
    scenario = setup_proposed_transition(api)
    departing = scenario["departing"]
    successor = scenario["successor"]
    matter_id = scenario["matter"]["id"]

    second_notice = api.notice_of_departure(
        departing["id"], notice_of_departure_payload("2026-12-31"), admin
    )
    validate_error(second_notice, ApiErrorId.ERR_PARTNER_NOT_DEPARTING.value, 409)

    effective = effectuate_transition(
        api,
        transition_id=scenario["transition"]["id"],
        successor_partner_id=successor["id"],
        effective_on="2026-12-31",
        matter_id=matter_id,
    )
    assert effective["state"] == "EFFECTIVE"
    assert effective["successor_partner_id"] == successor["id"]
    assert read_partner(api, departing["id"])["status"] == "DEPARTED"

    replay = api.effectuate_credit_transition(
        scenario["transition"]["id"],
        effectuate_transition_payload(
            successor["id"], "2026-12-31", matter_version(api, matter_id)
        ),
        admin,
    )
    validate_error(replay, ApiErrorId.ERR_TRANSITION_NOT_PENDING.value, 409)

    settled = read_transition(api, scenario["transition"]["id"])
    assert settled["state"] == "EFFECTIVE"
    assert settled["void_reason"] is None
    rows = matter_allocations(api, matter_id)
    assert find_allocation(rows, "ORIGINATING", successor["id"], "ACTIVE") is not None
    assert find_allocation(rows, "ORIGINATING", departing["id"], "TRANSFERRED") is not None
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)


def test_a_voided_transition_cannot_be_voided_again(api):
    """PRD 3.1: "Both require a `void_reason` — absent, the request is malformed —
    and both require the `expected_matter_version`; a transition already in
    `VOIDED` cannot be voided again and yields `ERR_TRANSITION_NOT_VOIDABLE`."
    "Voiding from `PROPOSED` is deliberately inert on the credit ledger: it
    records `void_reason`, moves the transition to `VOIDED`, touches no
    allocation at all because none was ever moved, and increments both the
    matter's `version` and the transition's own `version`."

    Design: Corner/errors/departure_and_credit_transition_refusals
    """
    scenario = setup_proposed_transition(api)
    matter_id = scenario["matter"]["id"]

    voided = void_transition(
        api,
        transition_id=scenario["transition"]["id"],
        void_reason="The departure was withdrawn before any credit moved.",
        matter_id=matter_id,
    )
    assert voided["state"] == "VOIDED"
    assert voided["void_reason"] == "The departure was withdrawn before any credit moved."

    again = api.void_credit_transition(
        scenario["transition"]["id"],
        void_transition_payload(
            "A second cancellation of the same transition.", matter_version(api, matter_id)
        ),
        make_cycle_admin_headers(),
    )
    validate_error(again, ApiErrorId.ERR_TRANSITION_NOT_VOIDABLE.value, 409)

    unchanged = read_transition(api, scenario["transition"]["id"])
    assert unchanged["state"] == "VOIDED"
    assert unchanged["void_reason"] == "The departure was withdrawn before any credit moved."
    assert unchanged["version"] == voided["version"]
    rows = matter_allocations(api, matter_id)
    assert find_allocation(
        rows, "ORIGINATING", scenario["departing"]["id"], "ACTIVE"
    ) is not None


def test_missing_headers_are_refused_before_the_role_gate(api):
    """PRD 2.1: "If either header is absent or present but empty, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the
    request is examined." "A value of `X-User-Role` that is not one of those
    five, or that is one of them but is not authorised for the endpoint being
    called, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    Design: Corner/errors/missing_headers_are_refused_before_the_role_gate
    """
    validate_error(
        api.create_cycle(create_cycle_payload(), NO_AUTH_HEADERS),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.list_cycles(NO_AUTH_HEADERS), ApiErrorId.ERR_UNAUTHENTICATED.value, 401
    )
    validate_error(
        api.create_cycle(create_cycle_payload(), make_headers_without_user_id("CycleAdmin")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_cycle(
            create_cycle_payload(), make_headers_without_role("11111111-1111-4111-8111-111111111111")
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_cycle(
            create_cycle_payload(),
            make_headers_with_empty_role("11111111-1111-4111-8111-111111111111"),
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    validate_error(
        api.create_cycle(
            create_cycle_payload(),
            make_unrecognised_role_headers("11111111-1111-4111-8111-111111111111"),
        ),
        ApiErrorId.ERR_ROLE_NOT_PERMITTED.value,
        403,
    )

    rows, meta = validate_paginated(api.list_cycles(make_cycle_admin_headers()))
    assert rows == []
    assert meta["total_count"] == 0
