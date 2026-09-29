"""Multi-hop consequences of a single lease-buyout decision.

One tower company exercising its right of first refusal, one adjudicator upholding a
landowner dispute, and one administrator pulling capital back out of a pool each set off a
chain that crosses several aggregates: deal stage, reserved capital, portfolio posture and a
sibling deal on the other side of the pool; or dispute, stream servicing condition, pledged
collateral and the warehouse lender's borrowing base. Every link is re-read from the API
after the single triggering call.
"""

from test_helpers import (
    AcquisitionStatus,
    ApiErrorId,
    CapitalPosture,
    CapitalState,
    ComplianceState,
    DealStage,
    DisputeStatus,
    DisputeType,
    OfferStatus,
    PledgeStatus,
    RofrNoticeStatus,
    RofrState,
    Scenario,
    ServicingStatus,
    assert_borrowing_base,
    assert_fields,
    assert_pledge_eligible_value,
    assert_portfolio_ledger_balances,
    assert_utilization_and_posture,
    adjust_capital,
    bps_of,
    build_chain,
    build_facility_with_pledge,
    build_two_deals_on_one_portfolio,
    create_portfolio,
    draw_advance,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_tower_company_agent_headers,
    make_treasury_officer_headers,
    open_dispute,
    read_facility,
    transition_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)

# The canonical seed offer of 36,000,000 cents sits in the top broker tier (gross at or
# above 30,000,000 cents pays 150 bps), so the commitment the pool must set aside is
# 36,000,000 + 540,000 = 36,540,000 cents.
ACCEPTED_OFFER_CENTS = 36_000_000
COMMITMENT_CENTS = 36_540_000

# A pool of 40,600,000 cents carrying that one commitment sits at exactly
# 36,540,000 * 10000 / 40,600,000 = 9000 bps, the inclusive frozen rung.
FROZEN_POOL_CENTS = 40_600_000
FROZEN_POOL_AVAILABLE_CENTS = 4_060_000

# A pool of 50,000,000 cents carrying the same commitment sits at 7308 bps and is OPEN.
OPEN_POOL_CENTS = 50_000_000
OPEN_POOL_UTILIZATION_BPS = 7308

ADVANCE_DRAWN_CENTS = 25_000_000


def _frozen_pool_with_refusal_deal_and_parked_sibling(api, sibling_milestone: str) -> Scenario:
    """One pool funding a refusal-encumbered deal A and a sibling deal B on outreach.

    Deal A reaches DILIGENCE by having its offer accepted, which reserves the whole
    9000-bps worth of the pool and therefore freezes the pool underneath deal B.
    """
    portfolio = create_portfolio(api, total_capital_cents=FROZEN_POOL_CENTS)
    leg_a = build_chain(
        api,
        "offer_sent",
        existing=Scenario(portfolio=portfolio),
        tower_company={"rofr_required": True, "rofr_window_days": 30},
        tower_site={"site_code": "NE-4001"},
        landowner={"legal_name": "Owner_a LLC", "contact_email": "owner_a@x.example"},
    )
    leg_b = build_chain(
        api,
        sibling_milestone,
        existing=Scenario(portfolio=portfolio),
        tower_site={"site_code": "NE-4002"},
        landowner={"legal_name": "Owner_b LLC", "contact_email": "owner_b@x.example"},
    )

    # Acceptance reserves deal A's commitment; the pool lands on 9000 bps and freezes,
    # which parks sibling deal B.
    leg_a["offer"] = validate_success(
        api.transition_offer(leg_a.offer_id, {"action": "ACCEPT"}, headers=leg_a.landowner_headers)
    )
    leg_a["rofr_notice"] = validate_success(
        api.serve_rofr_notice(leg_a.deal_id, {}, headers=make_acquisition_analyst_headers()), 201
    )
    return Scenario(portfolio=portfolio, deal_a=leg_a, deal_b=leg_b)


def _read_notice(api, deal_id: str, notice_id: str) -> dict:
    notices, _meta = validate_paginated(
        api.list_rofr_notices(deal_id, headers=make_acquisition_analyst_headers())
    )
    matches = [notice for notice in notices if notice["id"] == notice_id]
    assert matches, f"refusal notice {notice_id} is absent from deal {deal_id}"
    return matches[0]


# ===========================================================================
# A tower company exercising its refusal right unwinds capital and thaws the pool
# ===========================================================================


def test_refusal_exercise_releases_reserved_capital_and_thaws_the_parked_sibling_deal(api):
    """A tower company exercising its right of first refusal loses us deal A, releases the
    capital deal A had reserved, drops the pool out of FROZEN, and resumes the sibling deal
    that the freeze had parked.

    PRD 3.6: "An exercise takes the notice `SERVED → EXERCISED`, stamps the same two fields, moves the deal's `rofr_state` to `EXERCISED`, and takes the deal away from us: `DILIGENCE → ROFR_LOST`, capital `RESERVED → RELEASED`, stream to `LOST`, portfolio ledger recomputed."
    PRD 3.1: "When a later recomputation moves the posture out of `FROZEN`, those parked deals resume: `CAPITAL_HOLD → OUTREACH`."
    PRD 2.10: "A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`."

    Design: Difficulty/transitive_cascade/rofr_exercise_cascades_deal_capital_portfolio_posture_and_sibling_deal
    """
    world = _frozen_pool_with_refusal_deal_and_parked_sibling(api, "outreach")
    deal_a, deal_b = world.deal_a, world.deal_b

    # The freeze has already cascaded: the pool is at exactly 9000 bps and deal B is parked.
    frozen = validate_success(api.get_portfolio(world.portfolio["id"], headers=make_platform_admin_headers()))
    assert_fields(
        frozen,
        {
            "committed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": FROZEN_POOL_AVAILABLE_CENTS,
            "utilization_bps": 9000,
            "capital_posture": CapitalPosture.FROZEN.value,
        },
        label="portfolio before the exercise",
    )
    parked = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(parked, {"stage": DealStage.CAPITAL_HOLD.value}, label="sibling deal before the exercise")

    exercised = validate_success(
        api.respond_to_rofr_notice(
            deal_a["rofr_notice"]["id"],
            {"decision": "EXERCISE"},
            headers=make_tower_company_agent_headers(deal_a.tower_company_id),
        )
    )
    assert_fields(exercised, {"status": RofrNoticeStatus.EXERCISED.value}, label="exercise response")

    # Hop 1 — the notice itself.
    notice = _read_notice(api, deal_a.deal_id, deal_a["rofr_notice"]["id"])
    assert_fields(
        notice,
        {"status": RofrNoticeStatus.EXERCISED.value, "window_days_snapshot": 30},
        label="refusal notice",
    )

    # Hop 2 and 3 — deal A loses its stage and releases its capital.
    lost_deal = validate_success(api.get_deal(deal_a.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        lost_deal,
        {
            "rofr_state": RofrState.EXERCISED.value,
            "stage": DealStage.ROFR_LOST.value,
            "capital_state": CapitalState.RELEASED.value,
        },
        label="deal lost to the refusal",
    )
    stream_a = validate_success(
        api.get_lease_stream(deal_a.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(stream_a, {"acquisition_status": AcquisitionStatus.LOST.value}, label="lease stream under the lost deal")

    # Hop 4 — the pool ledger unwinds and the posture leaves FROZEN.
    thawed = validate_success(api.get_portfolio(world.portfolio["id"], headers=make_platform_admin_headers()))
    assert_fields(
        thawed,
        {
            "committed_capital_cents": 0,
            "deployed_capital_cents": 0,
            "available_capital_cents": FROZEN_POOL_CENTS,
            "utilization_bps": 0,
            "capital_posture": CapitalPosture.OPEN.value,
            "active_deal_count": 1,
        },
        label="portfolio after the exercise",
    )
    assert_portfolio_ledger_balances(thawed)
    assert_utilization_and_posture(thawed)

    # Hop 5 — the sibling deal resumes outreach.
    resumed = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        resumed,
        {"stage": DealStage.OUTREACH.value, "capital_state": CapitalState.UNCOMMITTED.value},
        label="sibling deal after the exercise",
    )


def test_refusal_exercise_returns_the_parked_sibling_deal_to_a_sendable_outreach_stage(api):
    """While the pool is frozen the parked sibling deal cannot send its drafted offer; the
    tower company's exercise releases deal A's capital, thaws the pool, and the resumed
    sibling deal accepts the same send.

    PRD 3.6: "An exercise takes the notice `SERVED → EXERCISED`, stamps the same two fields, moves the deal's `rofr_state` to `EXERCISED`, and takes the deal away from us: `DILIGENCE → ROFR_LOST`, capital `RESERVED → RELEASED`, stream to `LOST`, portfolio ledger recomputed."
    PRD 3.1: "When a later recomputation moves the posture out of `FROZEN`, those parked deals resume: `CAPITAL_HOLD → OUTREACH`."
    PRD 3.5: "It requires the deal's `stage` to be `OUTREACH` or `NEGOTIATION`, requires the landowner not to be at `DO_NOT_CONTACT`, requires the offer's `amount_cents` to be less than or equal to the pinned valuation's `max_bid_cents` — a violation is `ERR_OFFER_EXCEEDS_GUARDRAIL` — and requires that no other offer on the deal is currently sitting in `SENT` or `COUNTERED`, since only one proposal may be live at a time and a second is refused with `ERR_OFFER_ALREADY_OUTSTANDING`."

    Design: Difficulty/transitive_cascade/rofr_exercise_cascades_deal_capital_portfolio_posture_and_sibling_deal
    """
    world = _frozen_pool_with_refusal_deal_and_parked_sibling(api, "offer_draft")
    deal_a, deal_b = world.deal_a, world.deal_b

    # Parked at CAPITAL_HOLD, the sibling deal is not at a stage that admits a send.
    parked = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(parked, {"stage": DealStage.CAPITAL_HOLD.value}, label="sibling deal while the pool is frozen")
    blocked = api.transition_offer(
        deal_b.offer_id, {"action": "SEND"}, headers=make_acquisition_analyst_headers()
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_DEAL_STAGE.value)

    validate_success(
        api.respond_to_rofr_notice(
            deal_a["rofr_notice"]["id"],
            {"decision": "EXERCISE"},
            headers=make_tower_company_agent_headers(deal_a.tower_company_id),
        )
    )

    notice = _read_notice(api, deal_a.deal_id, deal_a["rofr_notice"]["id"])
    assert_fields(notice, {"status": RofrNoticeStatus.EXERCISED.value}, label="refusal notice")

    lost_deal = validate_success(api.get_deal(deal_a.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        lost_deal,
        {
            "rofr_state": RofrState.EXERCISED.value,
            "stage": DealStage.ROFR_LOST.value,
            "capital_state": CapitalState.RELEASED.value,
        },
        label="deal lost to the refusal",
    )
    stream_a = validate_success(
        api.get_lease_stream(deal_a.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(stream_a, {"acquisition_status": AcquisitionStatus.LOST.value}, label="lease stream under the lost deal")

    thawed = validate_success(api.get_portfolio(world.portfolio["id"], headers=make_platform_admin_headers()))
    assert_fields(
        thawed,
        {
            "committed_capital_cents": 0,
            "available_capital_cents": FROZEN_POOL_CENTS,
            "utilization_bps": 0,
            "capital_posture": CapitalPosture.OPEN.value,
        },
        label="portfolio after the exercise",
    )

    resumed = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(resumed, {"stage": DealStage.OUTREACH.value}, label="sibling deal after the exercise")

    # The resumed stage now admits the send that was refused a moment ago.
    sent = validate_success(
        api.transition_offer(deal_b.offer_id, {"action": "SEND"}, headers=make_acquisition_analyst_headers())
    )
    assert_fields(sent, {"status": OfferStatus.SENT.value, "round_number": 1}, label="sibling offer")
    negotiating = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        negotiating,
        {"stage": DealStage.NEGOTIATION.value, "negotiation_rounds": 1},
        label="sibling deal after the send",
    )


# ===========================================================================
# An upheld landowner dispute reaches the warehouse lender's borrowing base
# ===========================================================================


def _acquired_stream_pledged_with_advance_and_open_dispute(api) -> Scenario:
    """A closed deal whose acquired stream is pledged, advanced against, and disputed."""
    scenario = build_facility_with_pledge(api)
    scenario["facility"] = draw_advance(api, scenario.facility_id, ADVANCE_DRAWN_CENTS)
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.PROPERTY_USE.value,
        description="Storage containers placed outside the leased area",
    )
    return scenario


def test_upheld_dispute_impairs_stream_and_drives_its_pledge_ineligible(api):
    """Upholding a landowner dispute impairs the lease stream, which makes the stream's
    pledge ineligible at a full haircut, which collapses the facility's borrowing base and
    leaves the lender in a borrowing-base deficit against advances already drawn.

    PRD 3.8: "**`UPHOLD`** is available from either `OPEN → UPHELD` or `REOPENED → UPHELD` with no precondition; it stamps `resolved_at`, drives the stream's servicing condition to `IMPAIRED` — `PERFORMING → IMPAIRED` or `WATCHLIST → IMPAIRED` — makes every pledge of that stream that was in `PLEDGED` become `INELIGIBLE` with its `eligible_value_cents` driven to zero, and recomputes the holding facility's `pledged_eligible_total_cents`, `borrowing_base_cents`, and `compliance_state`."
    PRD 3.9: "`compliance_state` is `BORROWING_BASE_DEFICIT` whenever `advances_outstanding_cents` is strictly greater than `borrowing_base_cents`, and `COMPLIANT` otherwise."

    Design: Difficulty/transitive_cascade/dispute_upheld_cascades_stream_impairment_pledge_ineligibility_and_facility_deficit
    """
    scenario = _acquired_stream_pledged_with_advance_and_open_dispute(api)
    basis_cents = scenario["valuation"]["value_cents"]

    # Baseline: a performing stream carries no haircut, so the base is the full advance rate
    # against the modelled value and the drawn advance sits inside it.
    before = read_facility(api, scenario.facility_id)
    assert_fields(
        before,
        {
            "pledged_eligible_total_cents": basis_cents,
            "borrowing_base_cents": bps_of(basis_cents, before["advance_rate_bps"]),
            "advances_outstanding_cents": ADVANCE_DRAWN_CENTS,
            "compliance_state": ComplianceState.COMPLIANT.value,
        },
        label="facility before the dispute is upheld",
    )
    assert_borrowing_base(before)

    upheld = transition_dispute(api, scenario["dispute"]["id"], "UPHOLD", make_platform_admin_headers())
    assert_fields(upheld, {"status": DisputeStatus.UPHELD.value}, label="uphold response")

    # Hop 1 — the dispute is adjudicated against the landowner's counterparty.
    dispute = validate_success(api.get_dispute(scenario["dispute"]["id"], headers=make_platform_admin_headers()))
    assert_fields(dispute, {"status": DisputeStatus.UPHELD.value}, label="dispute case")
    assert dispute["resolved_at"], "an upheld dispute stamps resolved_at"

    # Hop 2 — the stream's servicing condition is driven to IMPAIRED.
    stream = validate_success(
        api.get_lease_stream(scenario.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(
        stream, {"servicing_status": ServicingStatus.IMPAIRED.value}, label="lease stream under the dispute"
    )

    # Hop 3 — every pledge of that stream goes ineligible with no eligible value.
    pledge = validate_success(
        api.get_collateral_pledge(scenario["pledge"]["id"], headers=make_treasury_officer_headers())
    )
    assert_fields(
        pledge,
        {
            "status": PledgeStatus.INELIGIBLE.value,
            "haircut_bps": 10000,
            "eligible_value_cents": 0,
            "basis_value_cents": basis_cents,
        },
        label="collateral pledge of the impaired stream",
    )
    assert_pledge_eligible_value(pledge)

    # Hop 4 — the facility that financed the stream falls into deficit.
    after = read_facility(api, scenario.facility_id)
    assert_fields(
        after,
        {
            "pledged_eligible_total_cents": 0,
            "borrowing_base_cents": 0,
            "advances_outstanding_cents": ADVANCE_DRAWN_CENTS,
            "compliance_state": ComplianceState.BORROWING_BASE_DEFICIT.value,
        },
        label="facility after the dispute is upheld",
    )
    assert_borrowing_base(after)


def test_upheld_dispute_collapses_the_borrowing_base_and_blocks_a_further_advance(api):
    """The same adjudication chain, read from the lender's side: once the impaired stream's
    pledge contributes nothing, the borrowing base is zero and no further advance may be
    drawn against it.

    PRD 3.8: "**`UPHOLD`** is available from either `OPEN → UPHELD` or `REOPENED → UPHELD` with no precondition; it stamps `resolved_at`, drives the stream's servicing condition to `IMPAIRED` — `PERFORMING → IMPAIRED` or `WATCHLIST → IMPAIRED` — makes every pledge of that stream that was in `PLEDGED` become `INELIGIBLE` with its `eligible_value_cents` driven to zero, and recomputes the holding facility's `pledged_eligible_total_cents`, `borrowing_base_cents`, and `compliance_state`."
    PRD 3.9: "When the pledged stream's `servicing_status` becomes `IMPAIRED` or `DELINQUENT`, the pledge is reclassified `PLEDGED → INELIGIBLE`, its `eligible_value_cents` is driven to zero, and the facility's `pledged_eligible_total_cents`, `borrowing_base_cents`, and `compliance_state` are recomputed."
    PRD 3.9: "The draw is permitted only when `advances_outstanding_cents` plus the requested amount is less than or equal to `borrowing_base_cents`; an over-draw is refused with `ERR_ADVANCE_EXCEEDS_BORROWING_BASE` and HTTP 402."

    Design: Difficulty/transitive_cascade/dispute_upheld_cascades_stream_impairment_pledge_ineligibility_and_facility_deficit
    """
    scenario = _acquired_stream_pledged_with_advance_and_open_dispute(api)
    basis_cents = scenario["valuation"]["value_cents"]
    baseline_base = bps_of(basis_cents, scenario["facility"]["advance_rate_bps"])
    assert baseline_base > ADVANCE_DRAWN_CENTS, "the drawn advance must start inside the borrowing base"

    transition_dispute(api, scenario["dispute"]["id"], "UPHOLD", make_platform_admin_headers())

    dispute = validate_success(api.get_dispute(scenario["dispute"]["id"], headers=make_platform_admin_headers()))
    assert_fields(dispute, {"status": DisputeStatus.UPHELD.value}, label="dispute case")

    stream = validate_success(
        api.get_lease_stream(scenario.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert_fields(
        stream, {"servicing_status": ServicingStatus.IMPAIRED.value}, label="lease stream under the dispute"
    )

    pledges, _meta = validate_paginated(
        api.list_collateral_pledges(
            {"facility_id": scenario.facility_id}, headers=make_treasury_officer_headers()
        )
    )
    assert len(pledges) == 1, f"the facility should hold exactly one pledge, got {len(pledges)}"
    assert_fields(
        pledges[0],
        {"status": PledgeStatus.INELIGIBLE.value, "eligible_value_cents": 0, "haircut_bps": 10000},
        label="pledge listed under the facility",
    )

    facility = read_facility(api, scenario.facility_id)
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": 0,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": 0,
            "advances_outstanding_cents": ADVANCE_DRAWN_CENTS,
            "compliance_state": ComplianceState.BORROWING_BASE_DEFICIT.value,
        },
        label="facility after the dispute is upheld",
    )
    assert_borrowing_base(facility)

    # With the base collapsed to zero, even one further cent breaches it.
    over_draw = api.create_advance(
        scenario.facility_id, {"amount_cents": 1}, headers=make_treasury_officer_headers()
    )
    validate_error(over_draw, ApiErrorId.ERR_ADVANCE_EXCEEDS_BORROWING_BASE.value)


# ===========================================================================
# Shrinking the pool freezes posture and parks the sibling deal on outreach
# ===========================================================================


def test_capital_withdrawal_freezes_the_pool_and_parks_the_outreach_sibling_deal(api):
    """Pulling capital out of the pool leaves the committed amount untouched but shrinks the
    denominator, which lifts utilization to the frozen rung, which parks the sibling deal
    still out on outreach while the already-reserved deal keeps its diligence stage.

    PRD 3.1: "After the adjustment the whole ledger, including `utilization_bps` and `capital_posture`, is recomputed, and the adjustment returns the updated portfolio rather than an adjustment record."
    PRD 3.1: "Posture follows utilization through a two-rung ladder evaluated from the top: when `utilization_bps` is at or above 9000 — that is, ninety percent of the pool or more is spoken for — `capital_posture` is `FROZEN`; otherwise, when `utilization_bps` is at or above 7500, it is `CONSTRAINED`; otherwise it is `OPEN`."
    PRD 3.1: "When the recomputation moves `capital_posture` into `FROZEN`, every deal on that portfolio sitting in stage `OUTREACH` is parked: `OUTREACH → CAPITAL_HOLD`."

    Design: Difficulty/transitive_cascade/capital_withdrawal_cascades_posture_freeze_to_sibling_outreach_deal_hold
    """
    world = build_two_deals_on_one_portfolio(
        api,
        total_capital_cents=OPEN_POOL_CENTS,
        site_codes=("NE-5001", "NE-5002"),
        milestones=("offer_accepted", "outreach"),
    )
    deal_a, deal_b = world.deal_a, world.deal_b

    before = validate_success(api.get_portfolio(world.portfolio["id"], headers=make_platform_admin_headers()))
    assert_fields(
        before,
        {
            "total_capital_cents": OPEN_POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": OPEN_POOL_CENTS - COMMITMENT_CENTS,
            "utilization_bps": OPEN_POOL_UTILIZATION_BPS,
            "capital_posture": CapitalPosture.OPEN.value,
        },
        label="portfolio before the withdrawal",
    )
    assert_fields(
        validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers())),
        {"stage": DealStage.OUTREACH.value},
        label="sibling deal before the withdrawal",
    )

    # Hop 1 — the withdrawal recomputes the whole ledger and returns the portfolio.
    adjusted = adjust_capital(
        api, world.portfolio["id"], -(OPEN_POOL_CENTS - FROZEN_POOL_CENTS), "Redeploy to the southeast program"
    )
    assert_fields(
        adjusted,
        {
            "total_capital_cents": FROZEN_POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": FROZEN_POOL_AVAILABLE_CENTS,
            "utilization_bps": 9000,
            "capital_posture": CapitalPosture.FROZEN.value,
        },
        label="capital adjustment response",
    )

    # Hop 2 — the re-read pool confirms the frozen posture at exactly 9000 bps.
    frozen = validate_success(api.get_portfolio(world.portfolio["id"], headers=make_platform_admin_headers()))
    assert_fields(
        frozen,
        {
            "total_capital_cents": FROZEN_POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "deployed_capital_cents": 0,
            "available_capital_cents": FROZEN_POOL_AVAILABLE_CENTS,
            "utilization_bps": 9000,
            "capital_posture": CapitalPosture.FROZEN.value,
        },
        label="portfolio after the withdrawal",
    )
    assert_portfolio_ledger_balances(frozen)
    assert_utilization_and_posture(frozen)

    # Hop 3 — only the outreach sibling is parked; the reserved deal is untouched.
    parked = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        parked,
        {"stage": DealStage.CAPITAL_HOLD.value, "capital_state": CapitalState.UNCOMMITTED.value},
        label="sibling deal after the withdrawal",
    )
    reserved = validate_success(api.get_deal(deal_a.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        reserved,
        {"stage": DealStage.DILIGENCE.value, "capital_state": CapitalState.RESERVED.value},
        label="reserved deal after the withdrawal",
    )


def test_staged_capital_withdrawals_park_the_outreach_deal_only_at_the_frozen_rung(api):
    """A first withdrawal lifts utilization into CONSTRAINED and leaves the sibling deal out
    on outreach; only the second withdrawal, which lands utilization on exactly 9000 basis
    points, freezes the pool and parks that deal.

    PRD 3.1: "Posture follows utilization through a two-rung ladder evaluated from the top: when `utilization_bps` is at or above 9000 — that is, ninety percent of the pool or more is spoken for — `capital_posture` is `FROZEN`; otherwise, when `utilization_bps` is at or above 7500, it is `CONSTRAINED`; otherwise it is `OPEN`."
    PRD 3.1: "Both rungs are inclusive, so a portfolio sitting at exactly 9000 basis points is frozen and one sitting at exactly 7500 is constrained."
    PRD 3.1: "When the recomputation moves `capital_posture` into `FROZEN`, every deal on that portfolio sitting in stage `OUTREACH` is parked: `OUTREACH → CAPITAL_HOLD`."

    Design: Difficulty/transitive_cascade/capital_withdrawal_cascades_posture_freeze_to_sibling_outreach_deal_hold
    """
    world = build_two_deals_on_one_portfolio(
        api,
        total_capital_cents=OPEN_POOL_CENTS,
        site_codes=("NE-5001", "NE-5002"),
        milestones=("offer_accepted", "outreach"),
    )
    deal_a, deal_b = world.deal_a, world.deal_b
    portfolio_id = world.portfolio["id"]

    # First withdrawal: 45,000,000 of capital against 36,540,000 committed is 8120 bps.
    constrained = adjust_capital(api, portfolio_id, -5_000_000, "Partial redeployment")
    assert_fields(
        constrained,
        {
            "total_capital_cents": 45_000_000,
            "committed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": 45_000_000 - COMMITMENT_CENTS,
            "utilization_bps": 8120,
            "capital_posture": CapitalPosture.CONSTRAINED.value,
        },
        label="portfolio after the first withdrawal",
    )
    assert_utilization_and_posture(constrained)
    still_out = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        still_out,
        {"stage": DealStage.OUTREACH.value},
        label="sibling deal while the pool is merely constrained",
    )

    # Second withdrawal: the pool lands on exactly the inclusive frozen rung.
    frozen_response = adjust_capital(api, portfolio_id, -4_400_000, "Redeploy to the southeast program")
    assert_fields(
        frozen_response,
        {
            "total_capital_cents": FROZEN_POOL_CENTS,
            "available_capital_cents": FROZEN_POOL_AVAILABLE_CENTS,
            "utilization_bps": 9000,
            "capital_posture": CapitalPosture.FROZEN.value,
        },
        label="capital adjustment response",
    )

    frozen = validate_success(api.get_portfolio(portfolio_id, headers=make_platform_admin_headers()))
    assert_fields(
        frozen,
        {
            "total_capital_cents": FROZEN_POOL_CENTS,
            "committed_capital_cents": COMMITMENT_CENTS,
            "available_capital_cents": FROZEN_POOL_AVAILABLE_CENTS,
            "utilization_bps": 9000,
            "capital_posture": CapitalPosture.FROZEN.value,
        },
        label="portfolio at the frozen rung",
    )
    assert_portfolio_ledger_balances(frozen)
    assert_utilization_and_posture(frozen)

    parked = validate_success(api.get_deal(deal_b.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        parked,
        {"stage": DealStage.CAPITAL_HOLD.value, "capital_state": CapitalState.UNCOMMITTED.value},
        label="sibling deal once the pool freezes",
    )
    reserved = validate_success(api.get_deal(deal_a.deal_id, headers=make_acquisition_analyst_headers()))
    assert_fields(
        reserved,
        {"stage": DealStage.DILIGENCE.value, "capital_state": CapitalState.RESERVED.value},
        label="reserved deal once the pool freezes",
    )
