"""
Queue B — §1.9 section ``state_machines``.

The forks, cycles, guarded arms and terminal lockdowns of the six state machines
in this API, together with the side effects each arm is contractually obliged to
fire — or to leave strictly alone.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers.api_errors import (
    ERR_APPLICATION_INVALID_STATE,
    ERR_AUTHORIZATION_INVALID_STATE,
    ERR_CAMPAIGN_CLOSED,
    ERR_DENOMINATIONAL_APPROVAL_REQUIRED,
    ERR_LOAN_ALREADY_ORIGINATED,
    ERR_PLEDGE_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_fields,
    assert_id_order,
    assert_iso_equal,
    assert_loan_ledger,
    assert_nulls,
    assert_pagination_meta,
    assert_ratio,
    assert_score,
)
from test_helpers.factories import (
    board_verification_payload,
    committee_decision_payload,
    construction_completion_payload,
    covenant_test_payload,
    denominational_decision_payload,
    draw_disbursement_payload,
    draw_rejection_payload,
    installment_payload,
    loan_payload,
    pledge_payload,
    return_to_draft_payload,
    submit_underwriting_payload,
    term_extension_payload,
    waiver_payload,
    workout_approval_payload,
    workout_plan_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    build_draft_authorization,
    build_draw_request,
    build_institution,
    build_pledge,
    build_pledge_campaign,
    build_submitted_authorization,
    chain_through_assignment,
    chain_through_loan,
    record_installment,
    refer_to_committee,
    render_committee_decision,
)
from test_helpers.test_users import (
    COMMITTEE_1,
    COMMITTEE_MEMBER,
    COMMITTEE_MEMBER_2,
    CREDIT_ANALYST,
    GOVERNANCE_OFFICER,
    LOAN_SERVICER,
    OFFICER_1,
    make_institution_representative_headers,
)

PRESBYTERY = "Presbytery of the Southeast"

# An institution that owes a denominational decision (PRD §3.2).
DENOMINATIONAL_INSTITUTION = {
    "requires_denominational_approval": True,
    "endowment_market_value_cents": None,
}

CAMPAIGN = {
    "campaign_name": "Building For Generations",
    "goal_cents": 120000000,
    "pledge_period_months": 36,
    "sponsor_collection_rate_bps": 9500,
}


def _board_verify(api, packet_id):
    return get_success_data(
        api.board_verify_governance_authorization(
            packet_id, board_verification_payload(), GOVERNANCE_OFFICER
        )
    )


def test_board_verification_lands_on_board_verified_where_a_denomination_must_approve(api):
    """
    The fork's far arm: verification stops at BOARD_VERIFIED, owing a decision.

    PRD §3.2: "Where the institution's `requires_denominational_approval` is true,
    the packet moves `SUBMITTED → BOARD_VERIFIED` and still owes a denominational
    decision."

    PRD §3.2: "On success the computed quorum is stored as `board_quorum_pct`,
    `verified_by_user_id` is set to the acting `X-User-ID`, and `version` advances by
    1."

    Design: Corner/state_machines/board_verification_forks_to_board_verified_when_denomination_must_approve
    """
    institution = build_institution(api, **DENOMINATIONAL_INSTITUTION)
    packet = build_submitted_authorization(
        api, institution["id"], denominational_body=PRESBYTERY
    )

    verified = _board_verify(api, packet["id"])

    assert_fields(verified, status="BOARD_VERIFIED", verified_by_user_id=OFFICER_1)
    assert_ratio(verified["board_quorum_pct"], 0.6667, "board_quorum_pct")
    assert_fields(verified, revision_round=0, denominational_body=PRESBYTERY)
    assert_nulls(verified, "denominational_decision_note")


def test_board_verification_lands_on_authorized_where_no_denomination_is_owed(api):
    """
    The identical call, the other arm: straight to AUTHORIZED, same side effects.

    PRD §3.2: "Where it is false, the very same act moves the packet `SUBMITTED →
    AUTHORIZED` outright, and the packet is immediately usable for a referral."

    PRD §3.2: "Both branches store the quorum, both stamp the verifier and both
    advance the version; only the destination state differs."

    Design: Corner/state_machines/board_verification_forks_straight_to_authorized_without_denominational_obligation
    """
    institution = build_institution(api, endowment_market_value_cents=None)
    packet = build_submitted_authorization(api, institution["id"])

    verified = _board_verify(api, packet["id"])

    assert_fields(verified, status="AUTHORIZED", verified_by_user_id=OFFICER_1)
    assert_ratio(verified["board_quorum_pct"], 0.6667, "board_quorum_pct")
    assert_nulls(verified, "denominational_body", "denominational_decision_note")


def test_denominational_rejection_then_return_to_draft_reopens_the_same_packet(api):
    """
    REJECT, rework, resubmit: one packet, revision_round 1, fields cleared.

    PRD §3.2: "`APPROVE` moves the packet `BOARD_VERIFIED → AUTHORIZED`; `REJECT`
    moves it `BOARD_VERIFIED → DENOM_REJECTED`."

    PRD §3.2: "That closes the governance cycle: `revision_round` rises by 1,
    `denominational_decision_note` and `verified_by_user_id` are both cleared to
    null, `version` advances by 1, and the packet may be reworked and resubmitted
    without opening a new one."

    Design: Corner/state_machines/denominational_rejection_then_return_to_draft_increments_revision_round
    """
    institution = build_institution(api, **DENOMINATIONAL_INSTITUTION)
    rep = make_institution_representative_headers(institution["id"])
    packet = build_submitted_authorization(
        api, institution["id"], denominational_body=PRESBYTERY
    )
    _board_verify(api, packet["id"])

    rejected = get_success_data(
        api.denominational_decision(
            packet["id"],
            denominational_decision_payload(
                "REJECT", note="Presbytery wants a revised debt schedule"
            ),
            GOVERNANCE_OFFICER,
        )
    )
    assert_fields(
        rejected,
        status="DENOM_REJECTED",
        denominational_decision_note="Presbytery wants a revised debt schedule",
    )

    reworked = get_success_data(
        api.return_governance_authorization_to_draft(
            packet["id"],
            return_to_draft_payload(rework_note="Reworking the amortization schedule"),
            rep,
        )
    )
    assert_fields(reworked, status="DRAFT", revision_round=1)
    assert_nulls(reworked, "denominational_decision_note", "verified_by_user_id")

    resubmitted = get_success_data(
        api.submit_governance_authorization(packet["id"], {}, rep)
    )
    assert_fields(resubmitted, status="SUBMITTED")
    assert resubmitted["id"] == packet["id"], "the cycle must reuse the same packet"

    rows, meta = validate_paginated(
        api.list_governance_authorizations(
            GOVERNANCE_OFFICER, {"institution_id": institution["id"]}
        )
    )
    assert_pagination_meta(meta, total_count=1)
    assert_id_order(rows, [packet["id"]])


def test_board_verification_on_a_draft_packet_is_a_state_conflict(api):
    """
    The act is declared from SUBMITTED only; a DRAFT packet refuses it.

    PRD §3.2: "Every one of these four governance acts is refused with
    `ERR_AUTHORIZATION_INVALID_STATE` when the packet does not occupy the state the
    act departs from — board verification attempted on a `DRAFT` packet, for
    instance, or a return-to-draft attempted on a packet still in `SUBMITTED`."

    Design: Corner/state_machines/board_verification_on_a_draft_packet_conflicts_with_the_declared_from_state
    """
    institution = build_institution(api, endowment_market_value_cents=None)
    packet = build_draft_authorization(api, institution["id"])

    validate_error(
        api.board_verify_governance_authorization(
            packet["id"], board_verification_payload(), GOVERNANCE_OFFICER
        ),
        ERR_AUTHORIZATION_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(
        api.get_governance_authorization(packet["id"], GOVERNANCE_OFFICER)
    )
    assert_fields(unchanged, status="DRAFT")
    assert_nulls(unchanged, "board_quorum_pct", "verified_by_user_id")


def test_denominational_decision_without_a_named_body_strands_the_packet(api):
    """
    Priority 18 passes — the packet *is* BOARD_VERIFIED — and priority 32 still bites.

    PRD §3.2: "A packet whose `denominational_body` is null cannot take a decision at
    all and is refused with `ERR_DENOMINATIONAL_APPROVAL_REQUIRED` — which is also
    why an institution that requires denominational approval can never reach
    `AUTHORIZED` without naming the body that grants it."

    Design: Corner/state_machines/denominational_decision_on_a_packet_with_no_body_returns_approval_required
    """
    institution = build_institution(api, **DENOMINATIONAL_INSTITUTION)
    packet = build_submitted_authorization(api, institution["id"])
    verified = _board_verify(api, packet["id"])
    assert_fields(verified, status="BOARD_VERIFIED")
    assert_nulls(verified, "denominational_body")

    validate_error(
        api.denominational_decision(
            packet["id"],
            denominational_decision_payload("APPROVE", note="Presbytery consent on file"),
            GOVERNANCE_OFFICER,
        ),
        ERR_DENOMINATIONAL_APPROVAL_REQUIRED,
        422,
    )

    stranded = get_success_data(
        api.get_governance_authorization(packet["id"], GOVERNANCE_OFFICER)
    )
    assert_fields(stranded, status="BOARD_VERIFIED")
    assert_nulls(stranded, "denominational_decision_note")


def test_installment_covering_the_whole_pledge_fulfils_it_and_moves_the_buckets(api):
    """
    ACTIVE → FULFILLED in one payment; the cash stays counted, the balance does not.

    PRD §3.3: "Once the applied installment brings `collected_cents` to or above
    `pledged_amount_cents`, the pledge moves `ACTIVE → FULFILLED`: its pledged amount
    leaves `active_pledged_cents` and enters `fulfilled_pledged_cents`, both projected
    values are recomputed, and the pledge's `version` advances by 1."

    PRD §3.3: "Pledges in `LAPSED` or `FULFILLED` status contribute nothing beyond the
    cash already counted in the collected total."

    PRD §3.3: "The first is a maturity condition: `total_pledged_cents` must have
    reached the floor of the goal multiplied by 90 percent, which keeps a brand-new
    campaign with no pledges at all comfortably in `OPEN`."

    Design: Corner/state_machines/pledge_reaching_its_full_amount_becomes_fulfilled_and_moves_campaign_buckets
    """
    institution = build_institution(api)
    campaign = build_pledge_campaign(api, institution["id"], **CAMPAIGN)
    pledge = build_pledge(
        api,
        campaign["id"],
        donor_tier="GENERAL",
        pledged_amount_cents=10000000,
        installment_count=12,
    )

    fulfilled = record_installment(api, pledge["id"], 1, "PAID", 10000000)
    assert_fields(
        fulfilled,
        status="FULFILLED",
        collected_cents=10000000,
        payments_made_count=1,
        missed_payments_count=0,
    )

    reread = get_success_data(api.get_pledge_campaign(campaign["id"], CREDIT_ANALYST))
    assert_fields(
        reread,
        total_pledged_cents=10000000,
        active_pledged_cents=0,
        fulfilled_pledged_cents=10000000,
        lapsed_pledged_cents=0,
        collected_to_date_cents=10000000,
        attrition_adjusted_value_cents=10000000,
        status="OPEN",
    )


def test_installment_against_a_fulfilled_pledge_is_refused_and_changes_nothing(api):
    """
    FULFILLED is terminal, so collected_cents can never overshoot the pledge.

    PRD §3.3: "`FULFILLED` is terminal."

    PRD §2.10: "The pledge is `ACTIVE` for an installment record or a lapse, and
    `LAPSED` for a reinstatement — `ERR_PLEDGE_INVALID_STATE` (HTTP 409), on those
    three pledge actions."

    Design: Corner/state_machines/installment_recorded_on_a_fulfilled_pledge_returns_pledge_invalid_state
    """
    institution = build_institution(api)
    campaign = build_pledge_campaign(api, institution["id"], **CAMPAIGN)
    pledge = build_pledge(
        api,
        campaign["id"],
        donor_tier="GENERAL",
        pledged_amount_cents=10000000,
        installment_count=12,
    )
    record_installment(api, pledge["id"], 1, "PAID", 10000000)

    validate_error(
        api.record_pledge_payment(
            pledge["id"], installment_payload(2, "PAID", 500000), LOAN_SERVICER
        ),
        ERR_PLEDGE_INVALID_STATE,
        409,
    )

    unchanged = get_success_data(api.get_pledge(pledge["id"], LOAN_SERVICER))
    assert_fields(
        unchanged, status="FULFILLED", collected_cents=10000000, payments_made_count=1
    )


def test_second_close_and_a_pledge_against_a_closed_campaign_are_both_refused(api):
    """
    CLOSED freezes the campaign — and the guard is not an optimistic-concurrency failure.

    PRD §3.3: "`CLOSED` is terminal, and a second close attempt against it is refused
    with `ERR_CAMPAIGN_CLOSED`."

    PRD §3.3: "In both cases the campaign moves to `CLOSED` and its `version` advances
    by 1; in both cases the campaign is frozen, and no further pledge creation,
    installment recording or reinstatement is accepted afterwards."

    Design: Corner/state_machines/closing_an_already_closed_campaign_returns_campaign_closed
    """
    institution = build_institution(api)
    rep = make_institution_representative_headers(institution["id"])
    campaign = build_pledge_campaign(api, institution["id"], **CAMPAIGN)

    closed = get_success_data(
        api.close_pledge_campaign(campaign["id"], {"close_note": "Campaign concluded"}, rep)
    )
    assert_fields(closed, status="CLOSED")

    validate_error(
        api.close_pledge_campaign(campaign["id"], {"close_note": "Closing again"}, rep),
        ERR_CAMPAIGN_CLOSED,
        409,
    )

    # The declared version is the current one, so position 17 cannot fire here.
    validate_error(
        api.create_pledge(
            pledge_payload(
                campaign["id"],
                closed["version"],
                donor_tier="LEAD",
                pledged_amount_cents=5000000,
                installment_count=10,
            ),
            CREDIT_ANALYST,
        ),
        ERR_CAMPAIGN_CLOSED,
        409,
    )

    _, meta = validate_paginated(
        api.list_pledges(CREDIT_ANALYST, {"pledge_campaign_id": campaign["id"]})
    )
    assert_pagination_meta(meta, total_count=0)


def test_committee_decline_unwinds_the_collateral_into_lien_history(api):
    """
    DECLINE is the only arm of the fork that releases the security.

    PRD §3.6: "A **declining** decision moves the application `COMMITTEE_REVIEW →
    DECLINED`, stores the submitted note as `revision_reason`, and releases the
    collateral: every asset assigned to this application has its
    `assigned_loan_application_id`, `lien_position`, `lien_effective_from` and
    `lien_effective_to` cleared to null, with the occupation just ended appended to
    that asset's `lien_history` exactly as an explicit release would append it."

    PRD §3.4: "The release appends the occupation just ended to `lien_history` as a
    record carrying `loan_application_id`, `lien_position`, `effective_from`,
    `effective_to` and `released_at`, with the list held in ascending `released_at`
    order and never rewritten once appended."

    PRD §3.4: "An asset with no current assignment is valued as though it would take
    a first lien."

    Design: Corner/state_machines/committee_decline_releases_every_assigned_asset_into_lien_history
    """
    chain = chain_through_assignment(api)
    refer_to_committee(api, chain.loan_application_id)

    declined = render_committee_decision(
        api,
        chain.loan_application_id,
        "DECLINE",
        note="Debt service too thin for the campaign risk",
    )
    assert_fields(
        declined,
        status="DECLINED",
        decided_by_user_id=COMMITTEE_1,
        revision_reason="Debt service too thin for the campaign risk",
        revision_count=0,
    )

    asset = chain.read_asset()
    assert_nulls(
        asset,
        "assigned_loan_application_id",
        "lien_position",
        "lien_effective_from",
        "lien_effective_to",
    )
    assert len(asset["lien_history"]) == 1, (
        f"expected exactly one released occupation, got {asset['lien_history']!r}"
    )
    entry = asset["lien_history"][0]
    assert_fields(
        entry, loan_application_id=chain.loan_application_id, lien_position=1
    )
    assert_iso_equal(entry["effective_from"], "2026-08-01T00:00:00Z", "effective_from")
    assert_iso_equal(entry["effective_to"], "2031-08-01T00:00:00Z", "effective_to")
    assert entry["released_at"] is not None, "released_at must be stamped on release"
    assert_fields(asset, lending_value_cents=225000000)


def test_draw_rejection_records_the_note_and_leaves_the_whole_ledger_alone(api):
    """
    The REJECTED arm touches the draw only: no approval, no reservation, no cash.

    PRD §3.7: "Rejection is the sibling arm: on a `SUBMITTED` draw it stores the
    submitted `inspector_note`, moves the draw `SUBMITTED → REJECTED`, advances the
    draw's `version` by 1, and leaves every ledger figure on the loan untouched."

    PRD §3.7: "`REJECTED` is terminal."

    Design: Corner/state_machines/draw_rejection_leaves_every_loan_ledger_field_untouched
    """
    chain = chain_through_loan(api)
    draw = build_draw_request(
        api, chain.loan_id, requested_amount_cents=112500000, percent_complete=0.4000
    )

    rejected = get_success_data(
        api.reject_draw_request(
            draw["id"],
            draw_rejection_payload(inspector_note="Builder certification missing"),
            LOAN_SERVICER,
        )
    )
    assert_fields(
        rejected, status="REJECTED", inspector_note="Builder certification missing"
    )
    assert_nulls(rejected, "approved_amount_cents", "retainage_cents", "net_disbursed_cents")

    loan = chain.read_loan()
    assert_loan_ledger(
        loan,
        reserved_draw_cents=0,
        undrawn_commitment_cents=225000000,
        disbursed_principal_cents=0,
        retainage_held_cents=0,
        outstanding_principal_cents=0,
        interest_reserve_shortfall_cents=1500000,
        servicing_status="PENDING_FIRST_DRAW",
        risk_posture="OPEN",
    )


def test_construction_completion_cancels_the_undrawn_balance_and_frees_retainage(api):
    """
    One hop: undrawn → cancelled, retainage held → released, and B stays OPEN.

    PRD §3.7: "Both variants perform the same two ledger movements — the whole of
    `undrawn_commitment_cents` moves into `cancelled_commitment_cents` and
    `undrawn_commitment_cents` is set to 0, and the whole of `retainage_held_cents`
    moves into `retainage_released_cents` and `retainage_held_cents` is set to 0 — and
    both advance `version` by 1."

    PRD §2.11: "Retainage is conserved in the same spirit: cash withheld from a
    disbursement accumulates in `retainage_held_cents`, and the only path out of that
    bucket is into `retainage_released_cents` at construction completion."

    PRD §3.7: "Below a completion fraction of 0.5000 the rate is 10 percent; from
    0.5000 up to but not including 0.9000 it is 5 percent; at 0.9000 and above it is 0
    percent."

    Design: Corner/state_machines/construction_completion_cancels_undrawn_commitment_and_releases_retainage
    """
    chain = chain_through_loan(api, loan_overrides={"interest_reserve_shortfall_cents": 0})
    draw = build_approved_draw(
        api, chain.loan_id, requested_amount_cents=112500000, percent_complete=0.4000
    )
    get_success_data(
        api.disburse_draw_request(draw["id"], draw_disbursement_payload(), LOAN_SERVICER)
    )

    completed = get_success_data(
        api.construction_completion(
            chain.loan_id,
            construction_completion_payload(completion_note="Certificate of occupancy issued"),
            LOAN_SERVICER,
        )
    )
    assert_loan_ledger(
        completed,
        servicing_status="AMORTIZING",
        risk_posture="OPEN",
        undrawn_commitment_cents=0,
        cancelled_commitment_cents=112500000,
        retainage_held_cents=0,
        retainage_released_cents=5625000,
        disbursed_principal_cents=112500000,
        outstanding_principal_cents=112500000,
    )

    disbursed = get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER))
    assert_fields(
        disbursed,
        status="DISBURSED",
        retainage_cents=5625000,
        interest_reserve_applied_cents=0,
        inspection_fee_cents=45000,
        net_disbursed_cents=106830000,
    )
    assert_ratio(
        disbursed["completion_pct_at_disbursement"], 0.5000, "completion_pct_at_disbursement"
    )


def test_funded_application_separates_repeat_origination_from_late_workflow_acts(api):
    """
    Priority 26 owns the repeat origination; priority 19 owns everything else.

    PRD §3.6: "Attempting origination against an application in `DRAFT`,
    `UNDERWRITING`, `COMMITTEE_REVIEW`, `REVISION_REQUESTED` or `DECLINED` is refused
    with `ERR_APPLICATION_INVALID_STATE`; attempting a second origination against the
    `FUNDED` application the first one produced is refused instead with
    `ERR_LOAN_ALREADY_ORIGINATED`."

    PRD §2.10: "At origination this position answers every status other than
    `APPROVED`, with one carve-out: a `FUNDED` application that a loan already
    references is deferred to position 26 so that `ERR_LOAN_ALREADY_ORIGINATED` stays
    reachable."

    PRD §3.6: "Any of the three attempted while the application is not in
    `COMMITTEE_REVIEW` is refused with `ERR_APPLICATION_INVALID_STATE`, as is a
    submit-underwriting attempt on an application that is neither `DRAFT` nor
    `REVISION_REQUESTED`, or a referral attempt on an application that is not in
    `UNDERWRITING`."

    Design: Corner/state_machines/application_state_guards_separate_repeat_origination_from_late_underwriting
    """
    chain = chain_through_loan(api)

    validate_error(
        api.create_loan(
            loan_payload(chain.loan_application_id, interest_reserve_shortfall_cents=0),
            LOAN_SERVICER,
        ),
        ERR_LOAN_ALREADY_ORIGINATED,
        409,
    )
    validate_error(
        api.submit_underwriting(
            chain.loan_application_id,
            submit_underwriting_payload(analyst_note="Trying to re-underwrite a funded deal"),
            CREDIT_ANALYST,
        ),
        ERR_APPLICATION_INVALID_STATE,
        409,
    )
    validate_error(
        api.committee_decision(
            chain.loan_application_id,
            committee_decision_payload("DECLINE", note="Too late"),
            COMMITTEE_MEMBER_2,
        ),
        ERR_APPLICATION_INVALID_STATE,
        409,
    )

    rows, meta = validate_paginated(
        api.list_loans(LOAN_SERVICER, {"loan_application_id": chain.loan_application_id})
    )
    assert_pagination_meta(meta, total_count=1)
    assert_id_order(rows, [chain.loan_id])

    application = chain.read_application()
    assert_fields(
        application,
        status="FUNDED",
        giving_basis="AUDITED_ONLY",
        decided_by_user_id=COMMITTEE_1,
    )


def test_waived_covenant_that_fails_again_re_enters_the_soft_breach_window(api):
    """
    WAIVED → BREACH_PENDING_CURE, fail count back to 1, posture WATCH not RESTRICTED.

    PRD §3.8: "A failing test moves it `WAIVED → BREACH_PENDING_CURE` and sets
    `consecutive_fail_count` to 1, re-entering the soft-breach window rather than
    jumping straight back to `BREACHED`, and may move the loan's posture back to
    `WATCH`."

    PRD §3.8: "Otherwise, if any covenant on this loan is `BREACH_PENDING_CURE`, the
    posture is `WATCH`."

    PRD §3.8: "The denominator is the loan's current `annual_debt_service_cents`
    divided by 100 and rounded half up to whole dollars; "current" matters, because an
    approved term-extension workout may have lowered it."

    Design: Corner/state_machines/waived_covenant_that_fails_again_re_enters_breach_pending_cure
    """
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)

    get_success_data(api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER))
    breached = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    assert_fields(breached, status="BREACHED", consecutive_fail_count=2)

    waived = get_success_data(
        api.waive_covenant(
            covenant["id"],
            waiver_payload(waiver_note="Committee waives the 2026Q3 breach"),
            COMMITTEE_MEMBER,
        )
    )
    assert_fields(waived, status="WAIVED", waiver_count=1)

    retested = get_success_data(
        api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER)
    )
    assert_fields(
        retested,
        status="BREACH_PENDING_CURE",
        consecutive_fail_count=1,
        test_count=3,
        waiver_count=1,
        last_test_result="FAIL",
        last_test_numerator_dollars=432001,
        last_test_denominator_dollars=360000,
    )
    assert_ratio(retested["last_test_ratio"], 1.2000, "last_test_ratio")

    loan = chain.read_loan()
    assert_fields(loan, risk_posture="WATCH", servicing_status="PENDING_FIRST_DRAW")


def test_approving_a_successor_workout_supersedes_its_predecessor_without_unwinding_it(api):
    """
    The predecessor's retuned term and debt service survive; the deferral stacks on top.

    PRD §3.9: "Where the plan named a predecessor, that predecessor moves `APPROVED →
    SUPERSEDED`, which is terminal, and its own `version` advances by 1."

    PRD §3.9: "Nothing the predecessor did is unwound: a successor's ledger effects
    apply on top of the predecessor's, so a second forgiveness plan forgives further
    principal rather than replacing the first forgiveness."

    PRD §3.9: "`PAYMENT_DEFERRAL` raises the loan's `deferred_payments_count` by
    `deferral_months`, accumulating across successive plans."

    PRD §3.9: "The four component scores are then weighted: 35 percent on
    `membership_trend_points`, 25 percent on `giving_trend_points`, 20 percent on
    `community_points` and 20 percent on `denominational_points`."

    Design: Corner/state_machines/workout_approval_supersedes_its_predecessor_and_retunes_the_loan
    """
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    get_success_data(api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER))

    first = get_success_data(
        api.create_workout_plan(
            term_extension_payload(
                chain.loan_id,
                chain.read_loan()["version"],
                extension_months=60,
                denominational_support_letter=True,
                narrative="Presbytery backs a five-year extension",
            ),
            LOAN_SERVICER,
        ),
        201,
    )
    get_success_data(
        api.approve_workout_plan(
            first["id"],
            workout_approval_payload(approval_note="Extension approved"),
            COMMITTEE_MEMBER,
        )
    )

    second = get_success_data(
        api.create_workout_plan(
            workout_plan_payload(
                chain.loan_id,
                chain.read_loan()["version"],
                deferral_months=6,
                denominational_support_letter=True,
                narrative="Six months of deferral on top of the extension",
                predecessor_workout_plan_id=first["id"],
            ),
            LOAN_SERVICER,
        ),
        201,
    )

    approved = get_success_data(
        api.approve_workout_plan(
            second["id"],
            workout_approval_payload(approval_note="Deferral approved"),
            COMMITTEE_MEMBER,
        )
    )
    assert_fields(approved, status="APPROVED", approved_by_user_id=COMMITTEE_1)
    assert_fields(
        approved,
        membership_trend_points=100,
        giving_trend_points=100,
        community_points=60,
        denominational_points=100,
    )
    assert_score(approved["mission_impact_score"], 92.00)

    superseded = get_success_data(api.get_workout_plan(first["id"], LOAN_SERVICER))
    assert_fields(superseded, status="SUPERSEDED", extension_months=60)

    loan = chain.read_loan()
    assert_fields(
        loan,
        term_months=300,
        annual_debt_service_cents=28800000,
        deferred_payments_count=6,
        risk_posture="WORKOUT_GATED",
        servicing_status="PENDING_FIRST_DRAW",
    )


def test_a_waiver_recovers_the_posture_but_only_reinstatement_restores_the_reservation(api):
    """
    The revert arm is explicit: SUSPENDED survives the waiver until a servicer acts.

    PRD §3.7: "Suspended draws are never reinstated automatically."

    PRD §3.7: "Once the posture recovers, a `LoanServicer` must reinstate each one
    explicitly with a `reinstatement_note`: the draw moves `SUSPENDED → APPROVED`, the
    loan's `reserved_draw_cents` rises again by the approved amount, and `version`
    advances by 1 on the draw and on the loan."

    PRD §3.8: "Recovery runs the other way and is partial by design — curing or
    waiving the breached covenant while another remains in its cure window yields
    `RESTRICTED → WATCH`, and bringing every covenant on the loan to `COMPLIANT` or
    `WAIVED` yields `RESTRICTED → OPEN` or `WATCH → OPEN` — but suspended draws stay
    suspended until a servicer reinstates them one by one."

    Design: Corner/state_machines/suspended_draw_reinstates_only_after_the_posture_recovers
    """
    chain = chain_through_loan(api)
    draw = build_approved_draw(
        api,
        chain.loan_id,
        project_phase="SHELL",
        requested_amount_cents=60000000,
        percent_complete=0.2500,
    )
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.3000)
    get_success_data(api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER))
    get_success_data(api.run_covenant_test(covenant["id"], covenant_test_payload(), LOAN_SERVICER))
    get_success_data(
        api.waive_covenant(
            covenant["id"], waiver_payload(waiver_note="Committee waives the breach"), COMMITTEE_MEMBER
        )
    )

    still_suspended = get_success_data(api.get_draw_request(draw["id"], LOAN_SERVICER))
    assert_fields(still_suspended, status="SUSPENDED", approved_amount_cents=60000000)

    reinstated = get_success_data(
        api.reinstate_draw_request(
            draw["id"],
            {"reinstatement_note": "Waiver on file, draw resumes"},
            LOAN_SERVICER,
        )
    )
    assert_fields(reinstated, status="APPROVED", approved_amount_cents=60000000)

    loan = chain.read_loan()
    assert_loan_ledger(
        loan,
        reserved_draw_cents=60000000,
        undrawn_commitment_cents=225000000,
        disbursed_principal_cents=0,
        risk_posture="OPEN",
        servicing_status="PENDING_FIRST_DRAW",
    )
