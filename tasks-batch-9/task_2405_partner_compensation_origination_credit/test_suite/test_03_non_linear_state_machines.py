"""Non-linear state machines: the bounded claim remand loop, the two
independent award dimensions, and the assessment return loop that rewinds a
second entity."""

from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    adjudicate_claim_payload,
    advance_cycle,
    approx2,
    approx4,
    assign_peer_review,
    contribute_capital,
    create_assessment,
    create_committee_member,
    create_cycle,
    create_partner,
    dispute_claim,
    find_allocation,
    get_success_data,
    make_committee_member_headers,
    make_credit_arbiter_headers,
    make_cycle_admin_headers,
    matter_allocations,
    matter_version,
    read_assessment,
    read_award,
    read_claim,
    read_cycle,
    read_matter,
    read_partner,
    review_decision_payload,
    score_peer_review,
    setup_disputed_claim,
    setup_trued_up_award,
    submit_assessment,
    submit_claim,
    validate_error,
    validate_success,
)


def test_remand_loop_is_traversable_twice_and_then_refused(api):
    """PRD 3.4: "It is bounded: a claim whose `remand_count` has already reached
    2 may not be remanded a third time, and the attempt reports
    `ERR_CLAIM_NOT_ADJUDICABLE`." "On a permitted remand the dispute is unwound —
    `disputing_partner_id`, `contested_pct` and `dispute_grounds` are all cleared
    — the arbiter's `remand_reason` is recorded, `revision_count` and
    `remand_count` each increment by 1, and the claim's `state` returns to
    `DRAFT`."

    Design: Difficulty/non_linear_state_machine/credit_claim_remand_cycle_bounded_at_max_remands
    """
    scenario = setup_disputed_claim(api, remands=0)
    claim_id = scenario["claim"]["id"]
    matter_id = scenario["matter"]["id"]
    claimant_id = scenario["claimant"]["id"]
    disputer_id = scenario["disputer"]["id"]
    arbiter_id = scenario["arbiter"]["id"]

    for expected_count in (1, 2):
        remanded = adjudicate_claim(
            api,
            claim_id=claim_id,
            arbiter_id=arbiter_id,
            decision="REMAND",
            matter_id=matter_id,
            remand_reason=f"Provide more detail, round {expected_count}.",
        )
        assert remanded["state"] == "DRAFT"
        assert remanded["remand_count"] == expected_count
        assert remanded["revision_count"] == expected_count
        assert remanded["disputing_partner_id"] is None
        assert remanded["contested_pct"] is None
        assert remanded["dispute_grounds"] is None
        submit_claim(api, claim_id, claimant_id)
        dispute_claim(
            api,
            claim_id,
            disputer_id,
            contested_pct=50.00,
            dispute_grounds="Unchanged position.",
        )

    version_before = matter_version(api, matter_id)
    response = api.adjudicate_credit_claim(
        claim_id,
        adjudicate_claim_payload("REMAND", version_before, remand_reason="One more round."),
        make_credit_arbiter_headers(arbiter_id),
    )
    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_ADJUDICABLE.value, 409)

    claim = read_claim(api, claim_id)
    assert claim["state"] == "DISPUTED"
    assert claim["remand_count"] == 2
    assert claim["revision_count"] == 2
    assert matter_version(api, matter_id) == version_before


def test_split_still_closes_a_claim_that_exhausted_its_remands(api):
    """PRD 3.4: "One originating allocation is created for `claimant_partner_id`
    at `approved_pct` with `source` of `CLAIM_ALLOCATED` and one for
    `disputing_partner_id` at `counterparty_pct` with `source` of
    `SHARING_CONVENTION`."

    Design: Difficulty/non_linear_state_machine/credit_claim_remand_cycle_bounded_at_max_remands
    """
    scenario = setup_disputed_claim(api, remands=2)
    claim_id = scenario["claim"]["id"]
    matter_id = scenario["matter"]["id"]

    response = api.adjudicate_credit_claim(
        claim_id,
        adjudicate_claim_payload(
            "SPLIT",
            matter_version(api, matter_id),
            approved_pct=60.00,
            counterparty_pct=40.00,
        ),
        make_credit_arbiter_headers(scenario["arbiter"]["id"]),
    )
    claim = validate_success(response, 200)

    assert claim["state"] == "ALLOCATED"
    assert claim["approved_pct"] == approx2(60.00)
    assert claim["counterparty_pct"] == approx2(40.00)
    assert claim["remand_count"] == 2

    rows = matter_allocations(api, matter_id, state="ACTIVE")
    claimant_row = find_allocation(rows, "ORIGINATING", scenario["claimant"]["id"])
    disputer_row = find_allocation(rows, "ORIGINATING", scenario["disputer"]["id"])
    assert claimant_row["credit_pct"] == approx2(60.00)
    assert claimant_row["source"] == "CLAIM_ALLOCATED"
    assert disputer_row["credit_pct"] == approx2(40.00)
    assert disputer_row["source"] == "SHARING_CONVENTION"
    assert read_matter(api, matter_id)["origination_pct_assigned"] == approx2(100.00)


def test_true_up_moves_only_the_payment_dimension(api):
    """PRD 3.9: "The combinations are genuinely orthogonal: an award may be
    published and pending, published and drawing, proposed and pending after a
    reopen, or published and settled." "Only after those appends is
    `capital_shortfall_cents` evaluated, again as `target_capital_cents` less the
    now-updated `capital_account_balance_cents` floored at 0 — and it is that
    figure which selects the payment dimension: `SETTLED` when the shortfall is
    0, `TRUED_UP` otherwise."

    Design: Difficulty/non_linear_state_machine/award_state_and_payment_state_are_independent_dimensions
    """
    bundle = setup_trued_up_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    cycle = read_cycle(api, bundle["cycle"]["id"])
    subject = read_partner(api, bundle["subject"]["id"])
    award = read_award(api, bundle["award"]["id"])

    assert subject["committee_points"] == approx2(700.00)
    assert cycle["total_committee_points"] == approx2(700.00)
    assert cycle["discretionary_pool_cents"] == 20_000_000
    assert cycle["formula_pool_cents"] == 80_000_000
    assert award["target_award_cents"] == 20_000_000
    assert award["draw_schedule_monthly_cents"] == 1_333_333
    assert award["draw_paid_cents"] == 2_666_666
    assert award["final_award_cents"] == 20_000_000
    assert award["true_up_delta_cents"] == 17_333_334
    assert award["capital_call_cents"] == 30_000_000
    assert award["capital_shortfall_cents"] == 12_666_666
    assert award["payment_state"] == "TRUED_UP"
    assert award["award_state"] == "PUBLISHED"


def test_finalization_waits_for_settlement_driven_by_the_cycle(api):
    """PRD 3.9: "A `CycleAdmin` credits a partner's capital account by supplying
    an `amount_cents` together with the `expected_partner_version` required by
    section 2.8; the contribution increases `capital_account_balance_cents` by
    that amount, which re-derives `capital_shortfall_cents` on every trued-up
    award of that partner and moves any award whose shortfall reaches 0 from
    `TRUED_UP` to `SETTLED` with its `version` incremented."

    Design: Difficulty/non_linear_state_machine/award_state_and_payment_state_are_independent_dimensions
    """
    bundle = setup_trued_up_award(
        api, subject_overrides={"target_capital_cents": 30_000_000}
    )
    contribute_capital(api, partner_id=bundle["subject"]["id"], amount_cents=12_666_666)

    award = read_award(api, bundle["award"]["id"])
    assert award["payment_state"] == "SETTLED"
    assert award["award_state"] == "PUBLISHED"
    assert award["capital_shortfall_cents"] == 0
    assert award["true_up_delta_cents"] == 17_333_334
    assert read_partner(api, bundle["subject"]["id"])["capital_account_balance_cents"] == 30_000_000

    closed = advance_cycle(api, bundle["cycle"]["id"], "CLOSED")
    award = read_award(api, bundle["award"]["id"])
    assert closed["state"] == "CLOSED"
    assert closed["confidentiality_locked"] is True
    assert closed["unsettled_award_count"] == 0
    assert award["award_state"] == "FINALIZED"
    assert award["payment_state"] == "SETTLED"


def _submitted_assessment_with_two_scores(api):
    """Cycle in SELF_ASSESSMENT, one SUBMITTED assessment, two SCORED reviews."""
    cycle = create_cycle(api)
    subject = create_partner(
        api, full_name="Dana Subject", compensation_model="DISCRETIONARY", admission_year=2012
    )
    first = create_committee_member(api, full_name="Cora Chair", practice_group="TAX")
    second = create_committee_member(api, full_name="Milo Member", practice_group="IP")
    advance_cycle(api, cycle["id"], "SELF_ASSESSMENT")
    assessment = create_assessment(
        api,
        cycle_id=cycle["id"],
        partner_id=subject["id"],
        claimed_origination_pct_total=0.00,
        claimed_non_billable_hours=0.00,
    )
    submit_assessment(api, assessment["id"], subject["id"])
    reviews = []
    for member, scores in ((first, (4, 4, 4)), (second, (5, 4, 3))):
        review = assign_peer_review(api, assessment["id"], member["id"])
        reviews.append(score_peer_review(api, review["id"], member["id"], *scores))
    return {
        "cycle": cycle,
        "subject": subject,
        "committee": [first, second],
        "assessment": assessment,
        "reviews": reviews,
    }


def test_return_rewinds_every_scored_peer_review(api):
    """PRD 3.6: "Returning is expensive by design: every peer review on the
    assessment that had reached `SCORED` is reset to `ASSIGNED` with
    `technical_score`, `collaboration_score`, `client_service_score`,
    `composite_score` and `comment` all cleared, and that reset re-derives
    `scored_review_count` and `mean_peer_score` back down."

    Design: Difficulty/non_linear_state_machine/self_assessment_return_cycle_resets_peer_review_dimension
    """
    scenario = _submitted_assessment_with_two_scores(api)
    assessment_id = scenario["assessment"]["id"]
    before = read_assessment(api, assessment_id)
    assert before["scored_review_count"] == 2
    assert before["mean_peer_score"] == approx4(4.1250)

    returned = get_success_data(
        api.review_decision_self_assessment(
            assessment_id,
            review_decision_payload("RETURN", reason="Quantify the two cross-sell introductions."),
            make_committee_member_headers(scenario["committee"][0]["id"]),
        )
    )
    assert returned["state"] == "DRAFT"
    assert returned["revision_count"] == 1
    assert returned["scored_review_count"] == 0
    assert returned["mean_peer_score"] == approx4(0.0000)

    admin = make_cycle_admin_headers()
    for review in scenario["reviews"]:
        reset = get_success_data(api.get_peer_review(review["id"], admin))
        assert reset["state"] == "ASSIGNED"
        assert reset["composite_score"] is None
        assert reset["technical_score"] is None
        assert reset["collaboration_score"] is None
        assert reset["client_service_score"] is None


def test_resubmission_and_rescoring_restore_the_roll_up(api):
    """PRD 3.6: "A returned assessment must therefore be re-submitted *and*
    re-scored from scratch before it can be accepted, which is the whole
    difference between the two branches."

    Design: Difficulty/non_linear_state_machine/self_assessment_return_cycle_resets_peer_review_dimension
    """
    scenario = _submitted_assessment_with_two_scores(api)
    assessment_id = scenario["assessment"]["id"]
    get_success_data(
        api.review_decision_self_assessment(
            assessment_id,
            review_decision_payload("RETURN", reason="Quantify the two cross-sell introductions."),
            make_committee_member_headers(scenario["committee"][0]["id"]),
        )
    )

    resubmitted = submit_assessment(api, assessment_id, scenario["subject"]["id"])
    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["scored_review_count"] == 0

    rescored = []
    for review, member, scores in zip(
        scenario["reviews"], scenario["committee"], ((4, 4, 4), (5, 4, 3))
    ):
        rescored.append(score_peer_review(api, review["id"], member["id"], *scores))

    assert rescored[0]["composite_score"] == approx4(4.0000)
    assert rescored[1]["composite_score"] == approx4(4.2500)
    final = read_assessment(api, assessment_id)
    assert final["scored_review_count"] == 2
    assert final["mean_peer_score"] == approx4(4.1250)
    assert final["revision_count"] == 1
