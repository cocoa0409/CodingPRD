"""Arithmetic detail of the buyout pipeline: how a carrier roster becomes a quality score,
how that score picks a discount tier and drives the forty-year present value and the bid
ceiling, how an accepted offer resolves into a broker fee and a dispute holdback, and how a
pledged stream's basis, servicing haircut and set membership move a facility's borrowing base.
"""

from datetime import datetime, timezone

from test_helpers import (
    CarrierCreditTier,
    ComplianceState,
    DisputeAction,
    DisputeStatus,
    DisputeType,
    PledgeStatus,
    ServicingStatus,
    TenancyStatus,
    TenancyType,
    THRESHOLDS,
    ValuationBasis,
    ValuationMethod,
    ValuationStatus,
    assert_borrowing_base,
    assert_facility,
    assert_fields,
    assert_has_fields,
    assert_lease_stream,
    assert_max_bid_ceiling,
    assert_pledge,
    assert_pledge_eligible_value,
    assert_portfolio_ledger_balances,
    assert_settlement_arithmetic,
    assert_utilization_and_posture,
    assert_valuation,
    bps_of,
    build_asset_graph,
    build_facility_with_pledge,
    build_two_closed_deals,
    create_facility,
    create_pledge,
    deal_in_outreach,
    get_success_data,
    make_acquisition_analyst_headers,
    make_landowner_headers,
    make_platform_admin_headers,
    make_servicing_agent_headers,
    make_treasury_officer_headers,
    offer_payload,
    open_dispute,
    read_facility,
    read_lease_stream,
    valuation_payload,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Rosters and figures the PRD's own formulas produce from the canonical stream
# (3,600,000 cents of annual rent, FIXED_PCT at 300 bps, 180 remaining months).
# ---------------------------------------------------------------------------

CROSSOVER_ANCHOR = {
    "carrier_name": "Cascade Cellular",
    "carrier_credit_tier": CarrierCreditTier.CROSSOVER.value,
    "tenancy_type": TenancyType.ANCHOR.value,
    "monthly_rent_share_cents": 210_000,
}
SPECULATIVE_COLOCATION = {
    "carrier_name": "Bluewave Mobile",
    "carrier_credit_tier": CarrierCreditTier.SPECULATIVE.value,
    "tenancy_type": TenancyType.COLOCATION.value,
    "monthly_rent_share_cents": 80_000,
}
SECOND_INVESTMENT_GRADE_ANCHOR = {"carrier_name": "Ridgeline Towers"}
INVESTMENT_GRADE_COLOCATION = {
    "carrier_name": "Northline Broadband",
    "tenancy_type": TenancyType.COLOCATION.value,
    "monthly_rent_share_cents": 120_000,
}

VALUE_AT_1250_BPS = 34_987_613
VALUE_AT_1000_BPS = 44_627_011
VALUE_AT_700_BPS = 64_151_290
MAX_BID_AT_1250_BPS = 36_736_994
MAX_BID_AT_1000_BPS = 46_858_362
MAX_BID_AT_700_BPS = 67_358_855


def _list_tenancies(api, lease_stream_id):
    """Return the stream's roster keyed by carrier name, plus the collection meta."""
    rows, meta = validate_paginated(
        api.list_tenancies(lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    return {row["carrier_name"]: row for row in rows}, meta


def _lump_sum_valuation(api, lease_stream_id):
    """Compute a fresh LUMP_SUM_PERPETUAL valuation against the stream's current version."""
    version = read_lease_stream(api, lease_stream_id)["version"]
    payload = valuation_payload(version, method=ValuationMethod.LUMP_SUM_PERPETUAL.value)
    return validate_success(
        api.create_valuation(lease_stream_id, payload, headers=make_acquisition_analyst_headers()), 201
    )


# ===========================================================================
# A crossover anchor beside a speculative colocation prices on the lowest rung
# ===========================================================================


def test_crossover_anchor_and_speculative_colocation_score_thirty_one_points(api):
    """A CROSSOVER anchor earns twenty-five points and a SPECULATIVE colocation six, so the
    roster totals thirty-one — strictly below every named tier boundary.

    PRD 3.3: "Take the tenancy's base credit points from its `carrier_credit_tier`: forty points for `INVESTMENT_GRADE`, twenty-five for `CROSSOVER`, ten for `SPECULATIVE`."
    PRD 3.3: "Multiply those base points by the type multiplier for its `tenancy_type`: one exactly for `ANCHOR`, six tenths for `COLOCATION`."
    PRD 3.3: "Store on the tenancy, as its `quality_points`, that same figure rounded half up to a whole number."

    Design: Corner/calculations/correct_result_crossover_anchor_plus_speculative_colocation_values_at_the_below_forty_tier
    """
    scenario = build_asset_graph(
        api, tenancies=[dict(CROSSOVER_ANCHOR), dict(SPECULATIVE_COLOCATION)]
    )

    roster, meta = _list_tenancies(api, scenario.lease_stream_id)
    assert meta["total_count"] == 2, f"the roster should hold two tenancies, meta says {meta['total_count']}"
    assert_fields(
        roster["Cascade Cellular"],
        {"carrier_credit_tier": CarrierCreditTier.CROSSOVER.value, "quality_points": 25},
        "CROSSOVER anchor",
    )
    assert_fields(
        roster["Bluewave Mobile"],
        {"carrier_credit_tier": CarrierCreditTier.SPECULATIVE.value, "quality_points": 6},
        "SPECULATIVE colocation",
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert_lease_stream(stream)
    assert_fields(
        stream,
        {
            "tenancy_quality_score": 31,
            "active_tenancy_count": 2,
            "anchor_carrier_name": "Cascade Cellular",
        },
        "LeaseStream",
    )


def test_score_thirty_one_prices_the_perpetual_stream_on_the_below_forty_tier(api):
    """A score of thirty-one falls through every inclusive rung to the 1250 basis-point tier,
    and the forty-year walk with a renewal haircut past year fifteen values the rent at
    34,987,613 cents with a 36,736,994-cent ceiling.

    PRD 3.4: "That snapshot picks the base discount tier from a four-rung ladder evaluated from the top down: a score of 80 or more prices at 700 basis points; failing that, a score of 60 or more prices at 850; failing that, a score of 40 or more prices at 1000; and anything below 40 prices at 1250."
    PRD 3.4: "**Under the `LUMP_SUM_PERPETUAL` method**, `discount_rate_bps` is the base tier unmodified and `horizon_years` is fixed at forty years."
    PRD 3.4: "The number of years the rent is actually contracted for is `remaining_term_months` divided by twelve and truncated toward zero."
    PRD 3.4: "If *y* is strictly greater than the contracted-years count, the year lies beyond the signed term and its present value is reduced by a renewal-risk haircut of 2000 basis points — that is, multiplied by the quantity one less two thousand divided by ten thousand."
    PRD 3.4: "`value_cents` is the sum of those rounded per-year figures."
    PRD 3.4: "`FIXED_PCT` gives the stream's `escalator_pct_bps` verbatim."
    PRD 3.4: "`max_bid_cents` is `value_cents` multiplied by 10500 basis points divided by ten thousand — one hundred five percent of model value — rounded half up to a whole number of cents."

    Design: Corner/calculations/correct_result_crossover_anchor_plus_speculative_colocation_values_at_the_below_forty_tier
    """
    scenario = build_asset_graph(
        api, tenancies=[dict(CROSSOVER_ANCHOR), dict(SPECULATIVE_COLOCATION)]
    )

    valuation = _lump_sum_valuation(api, scenario.lease_stream_id)

    assert_valuation(valuation)
    assert_fields(
        valuation,
        {
            "method": ValuationMethod.LUMP_SUM_PERPETUAL.value,
            "tenancy_quality_score_snapshot": 31,
            "discount_rate_bps": THRESHOLDS["DISCOUNT_BPS_SCORE_BELOW_40"],
            "growth_rate_bps": 300,
            "horizon_years": THRESHOLDS["LUMP_SUM_HORIZON_YEARS"],
            "value_cents": VALUE_AT_1250_BPS,
            "max_bid_cents": MAX_BID_AT_1250_BPS,
            "status": ValuationStatus.DRAFT.value,
        },
        "StreamValuation",
    )
    assert_max_bid_ceiling(valuation)
    assert valuation["value_cents"] != VALUE_AT_1000_BPS, (
        "a score of 31 must not be priced on the score-40 rung of 1000 basis points"
    )


# ===========================================================================
# A terminated tenancy leaves the quality-score input set
# ===========================================================================


def test_terminating_the_second_anchor_drops_the_stream_score_to_forty(api):
    """Two active investment-grade anchors score eighty; reclassifying one to TERMINATED
    removes it from the input set, so the live score falls to forty, the roster count to one,
    and the valuation computed at eighty is invalidated.

    PRD 3.3: "The **tenancy quality score** is the number that drives pricing, and it is computed only from tenancies whose `status` is `ACTIVE` or `HOLDOVER` — terminated occupancies contribute nothing."
    PRD 3.3: "`active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`."
    PRD 3.3: "`anchor_carrier_name` is the `carrier_name` of the earliest-created tenancy whose `tenancy_type` is `ANCHOR` and whose `status` is `ACTIVE` or `HOLDOVER`; when no such tenancy exists, `anchor_carrier_name` is the literal string `UNASSIGNED`."
    PRD 3.3: "It also invalidates pricing: every valuation on that stream in `DRAFT` or `APPROVED` is moved to `STALE`, because its snapshotted score no longer matches the live score."

    Design: Corner/calculations/input_set_filtering_terminated_tenancy_leaves_the_quality_score_input_set
    """
    scenario = build_asset_graph(api, tenancies=[{}, dict(SECOND_INVESTMENT_GRADE_ANCHOR)])
    priced_at_eighty = _lump_sum_valuation(api, scenario.lease_stream_id)
    assert_fields(
        priced_at_eighty,
        {
            "tenancy_quality_score_snapshot": 80,
            "discount_rate_bps": THRESHOLDS["DISCOUNT_BPS_SCORE_80_PLUS"],
            "value_cents": VALUE_AT_700_BPS,
        },
        "StreamValuation priced at score 80",
    )

    dropped = scenario.tenancies[1]
    reclassified = validate_success(
        api.set_tenancy_status(
            dropped["id"],
            {"status": TenancyStatus.TERMINATED.value},
            headers=make_servicing_agent_headers(),
        )
    )
    assert reclassified["status"] == TenancyStatus.TERMINATED.value

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert_fields(
        stream,
        {
            "tenancy_quality_score": 40,
            "active_tenancy_count": 1,
            "anchor_carrier_name": "Vantage Wireless",
        },
        "LeaseStream after the termination",
    )

    valuations, meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1, f"only one valuation exists, meta says {meta['total_count']}"
    assert valuations[0]["id"] == priced_at_eighty["id"]
    assert valuations[0]["status"] == ValuationStatus.STALE.value, (
        f"the valuation snapshotted at score 80 must be STALE, got {valuations[0]['status']!r}"
    )


def test_repricing_after_the_termination_moves_the_stream_to_the_score_forty_tier(api):
    """The narrowed input set reprices the same rent on the 1000 basis-point rung, so a fresh
    valuation lands at 44,627,011 cents rather than the 64,151,290 the two-anchor roster
    supported.

    PRD 3.3: "The **tenancy quality score** is the number that drives pricing, and it is computed only from tenancies whose `status` is `ACTIVE` or `HOLDOVER` — terminated occupancies contribute nothing."
    PRD 3.4: "That snapshot picks the base discount tier from a four-rung ladder evaluated from the top down: a score of 80 or more prices at 700 basis points; failing that, a score of 60 or more prices at 850; failing that, a score of 40 or more prices at 1000; and anything below 40 prices at 1250."
    PRD 3.4: "The year's present value is then rounded half up to a whole number of cents."
    PRD 3.4: "`max_bid_cents` is `value_cents` multiplied by 10500 basis points divided by ten thousand — one hundred five percent of model value — rounded half up to a whole number of cents."

    Design: Corner/calculations/input_set_filtering_terminated_tenancy_leaves_the_quality_score_input_set
    """
    scenario = build_asset_graph(api, tenancies=[{}, dict(SECOND_INVESTMENT_GRADE_ANCHOR)])
    priced_at_eighty = _lump_sum_valuation(api, scenario.lease_stream_id)
    get_success_data(
        api.set_tenancy_status(
            scenario.tenancies[1]["id"],
            {"status": TenancyStatus.TERMINATED.value},
            headers=make_servicing_agent_headers(),
        )
    )

    repriced = _lump_sum_valuation(api, scenario.lease_stream_id)

    assert_valuation(repriced)
    assert_fields(
        repriced,
        {
            "tenancy_quality_score_snapshot": 40,
            "discount_rate_bps": THRESHOLDS["DISCOUNT_BPS_SCORE_40_PLUS"],
            "growth_rate_bps": 300,
            "horizon_years": THRESHOLDS["LUMP_SUM_HORIZON_YEARS"],
            "value_cents": VALUE_AT_1000_BPS,
            "max_bid_cents": MAX_BID_AT_1000_BPS,
        },
        "StreamValuation repriced at score 40",
    )
    assert priced_at_eighty["value_cents"] - repriced["value_cents"] == VALUE_AT_700_BPS - VALUE_AT_1000_BPS, (
        "dropping one anchor out of the input set is worth exactly "
        f"{VALUE_AT_700_BPS - VALUE_AT_1000_BPS} cents of model value"
    )


# ===========================================================================
# A released pledge leaves the borrowing-base input set
# ===========================================================================


def _facility_holding_two_identical_pledges(api):
    """Two closed deals on identical streams, both pledged into one MARK_TO_MODEL facility."""
    scenario = build_two_closed_deals(api, total_capital_cents=100_000_000)
    scenario["facility"] = create_facility(
        api,
        scenario.portfolio_id,
        advance_rate_bps=6500,
        valuation_basis=ValuationBasis.MARK_TO_MODEL.value,
        carrier_concentration_limit_bps=10000,
    )
    scenario["pledge_a"] = create_pledge(api, scenario.facility_id, scenario.deal_a.lease_stream_id)
    scenario["pledge_b"] = create_pledge(api, scenario.facility_id, scenario.deal_b.lease_stream_id)
    scenario["facility"] = read_facility(api, scenario.facility_id)
    return scenario


def test_releasing_one_of_two_identical_pledges_zeroes_that_row_only(api):
    """Two pledges of 44,627,011 cents each pool to 89,254,022 and a 58,015,114-cent base;
    releasing one zeroes the released row's eligible value while its sibling keeps its full
    performing basis.

    PRD 3.9: "First, `pledged_eligible_total_cents` is the sum of `eligible_value_cents` across the facility's pledges in `PLEDGED`."
    PRD 3.9: "A release sets `eligible_value_cents` to zero, recomputes the facility's `pledged_eligible_total_cents` and `borrowing_base_cents`, and decrements `pledged_stream_count`."
    PRD 3.9: "`eligible_value_cents` is then zero whenever the pledge's `status` is `INELIGIBLE` or `RELEASED` or the stream's `servicing_status` is `IMPAIRED`, and otherwise is `basis_value_cents` multiplied by the quantity one less `haircut_bps` divided by ten thousand, rounded half up to a whole number of cents."

    Design: Corner/calculations/input_set_filtering_released_pledge_leaves_the_borrowing_base_input_set
    """
    scenario = _facility_holding_two_identical_pledges(api)
    assert_fields(
        scenario["facility"],
        {
            "pledged_eligible_total_cents": 89_254_022,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": 58_015_114,
            "pledged_stream_count": 2,
        },
        "FinancingFacility holding both pledges",
    )

    released = validate_success(
        api.release_collateral_pledge(
            scenario["pledge_b"]["id"], headers=make_treasury_officer_headers()
        )
    )

    assert_pledge(released)
    assert_fields(
        released,
        {"status": PledgeStatus.RELEASED.value, "eligible_value_cents": 0},
        "released CollateralPledge",
    )
    assert released["basis_value_cents"] == VALUE_AT_1000_BPS, (
        "the release zeroes the eligible value, not the recorded basis"
    )
    assert_pledge_eligible_value(released)

    survivor = validate_success(
        api.get_collateral_pledge(scenario["pledge_a"]["id"], headers=make_treasury_officer_headers())
    )
    assert_fields(
        survivor,
        {
            "status": PledgeStatus.PLEDGED.value,
            "haircut_bps": THRESHOLDS["HAIRCUT_BPS_PERFORMING"],
            "basis_value_cents": VALUE_AT_1000_BPS,
            "eligible_value_cents": VALUE_AT_1000_BPS,
        },
        "surviving CollateralPledge",
    )
    assert_pledge_eligible_value(survivor)


def test_the_borrowing_base_halves_when_one_pledge_leaves_the_pledged_set(api):
    """With the released row out of the sum, the eligible pool falls to 44,627,011 cents and the
    base to 29,007,557 at the 6500 basis-point advance rate, with no concentration excess.

    PRD 3.9: "First, `pledged_eligible_total_cents` is the sum of `eligible_value_cents` across the facility's pledges in `PLEDGED`."
    PRD 3.9: "Second comes the carrier concentration test, keyed on each pledged stream's `anchor_carrier_name`: the per-carrier ceiling is the gross eligible pool multiplied by `carrier_concentration_limit_bps`, divided by ten thousand, rounded half up to a whole number of cents; each anchor carrier's total is the sum of `eligible_value_cents` across the pledges whose streams name that carrier as anchor; and `concentration_excess_cents` is the sum, across carriers, of the amount by which a carrier's total exceeds the ceiling, counting zero for any carrier at or below the ceiling."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Corner/calculations/input_set_filtering_released_pledge_leaves_the_borrowing_base_input_set
    """
    scenario = _facility_holding_two_identical_pledges(api)
    base_before = scenario["facility"]["borrowing_base_cents"]
    assert base_before == 58_015_114

    get_success_data(
        api.release_collateral_pledge(
            scenario["pledge_b"]["id"], headers=make_treasury_officer_headers()
        )
    )

    facility = read_facility(api, scenario.facility_id)
    assert_facility(facility)
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": VALUE_AT_1000_BPS,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": 29_007_557,
            "pledged_stream_count": 1,
            "advances_outstanding_cents": 0,
            "compliance_state": ComplianceState.COMPLIANT.value,
        },
        "FinancingFacility after the release",
    )
    assert_borrowing_base(facility)
    assert facility["borrowing_base_cents"] == bps_of(VALUE_AT_1000_BPS, 6500)


# ===========================================================================
# The watchlist haircut is the declared three thousand basis points
# ===========================================================================


def test_starting_a_cure_haircuts_the_pledge_by_three_thousand_basis_points(api):
    """Starting a cure on an open dispute pushes the acquired stream to WATCHLIST, which
    re-haircuts its pledge at 3000 basis points — 44,627,011 becomes 31,238,908 — while the
    recorded basis is left alone.

    PRD 3.8: "The first-pass transition out of `OPEN` also degrades the stream's servicing condition, `PERFORMING → WATCHLIST`, which in turn re-haircuts every pledge of that stream and recomputes the borrowing base of the facility holding them; a stream already on `WATCHLIST` stays there."
    PRD 3.8: "Starting a cure increments `cure_attempts` and sets `cure_deadline` to thirty days after the current instant — on the first pass from `OPEN` the deadline is set, and on a repeat pass from `REOPENED` it is reset."
    PRD 3.9: "`haircut_bps` is read from the stream's `servicing_status` — zero basis points while `PERFORMING`, 3000 while on `WATCHLIST`, 5000 while `DELINQUENT`, and the full 10000 while `IMPAIRED`."
    PRD 3.9: "`eligible_value_cents` is then zero whenever the pledge's `status` is `INELIGIBLE` or `RELEASED` or the stream's `servicing_status` is `IMPAIRED`, and otherwise is `basis_value_cents` multiplied by the quantity one less `haircut_bps` divided by ten thousand, rounded half up to a whole number of cents."

    Design: Corner/calculations/constants_applied_watchlist_haircut_uses_the_declared_three_thousand_bps
    """
    scenario = build_facility_with_pledge(api)
    dispute = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
    )

    cured = validate_success(
        api.transition_dispute(
            dispute["id"],
            {"action": DisputeAction.START_CURE.value},
            headers=make_servicing_agent_headers(),
        )
    )

    assert_fields(
        cured,
        {"status": DisputeStatus.CURE_PENDING.value, "cure_attempts": 1},
        "DisputeCase after START_CURE",
    )
    deadline = datetime.fromisoformat(cured["cure_deadline"].replace("Z", "+00:00"))
    assert deadline == datetime(2026, 8, 31, tzinfo=timezone.utc), (
        f"cure_deadline should be thirty days after 2026-08-01T00:00:00Z, got {cured['cure_deadline']!r}"
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["servicing_status"] == ServicingStatus.WATCHLIST.value

    pledge = validate_success(
        api.get_collateral_pledge(scenario["pledge"]["id"], headers=make_treasury_officer_headers())
    )
    assert_fields(
        pledge,
        {
            "status": PledgeStatus.PLEDGED.value,
            "haircut_bps": THRESHOLDS["HAIRCUT_BPS_WATCHLIST"],
            "basis_value_cents": VALUE_AT_1000_BPS,
            "eligible_value_cents": 31_238_908,
        },
        "CollateralPledge on a WATCHLIST stream",
    )
    assert_pledge_eligible_value(pledge)
    assert pledge["eligible_value_cents"] == bps_of(VALUE_AT_1000_BPS, 10000 - 3000)


def test_the_watchlist_haircut_shrinks_the_borrowing_base_to_twenty_million(api):
    """A performing pledge supports a 29,007,557-cent base; once the cure moves the stream to
    WATCHLIST the eligible pool is 31,238,908 and the base falls to 20,305,290.

    PRD 3.9: "First, `pledged_eligible_total_cents` is the sum of `eligible_value_cents` across the facility's pledges in `PLEDGED`."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."
    PRD 3.9: "`haircut_bps` is read from the stream's `servicing_status` — zero basis points while `PERFORMING`, 3000 while on `WATCHLIST`, 5000 while `DELINQUENT`, and the full 10000 while `IMPAIRED`."
    PRD 2.5: "Wherever a calculation must land on an integer, the rounding method is **round half up**: a value whose fractional remainder is exactly one half rounds away from zero to the next integer of larger magnitude."

    Design: Corner/calculations/constants_applied_watchlist_haircut_uses_the_declared_three_thousand_bps
    """
    scenario = build_facility_with_pledge(api)
    assert_fields(
        scenario["facility"],
        {
            "pledged_eligible_total_cents": VALUE_AT_1000_BPS,
            "borrowing_base_cents": 29_007_557,
            "pledged_stream_count": 1,
        },
        "FinancingFacility while the stream is PERFORMING",
    )
    dispute = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
    )

    get_success_data(
        api.transition_dispute(
            dispute["id"],
            {"action": DisputeAction.START_CURE.value},
            headers=make_servicing_agent_headers(),
        )
    )

    facility = read_facility(api, scenario.facility_id)
    assert_facility(facility)
    assert_fields(
        facility,
        {
            "pledged_eligible_total_cents": 31_238_908,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": 20_305_290,
            "pledged_stream_count": 1,
            "compliance_state": ComplianceState.COMPLIANT.value,
        },
        "FinancingFacility after the watchlist haircut",
    )
    assert_borrowing_base(facility)
    assert facility["borrowing_base_cents"] == bps_of(31_238_908, 6500)


# ===========================================================================
# One acceptance rounds the fee down and the holdback up
# ===========================================================================


def _accept_a_thirty_million_and_twenty_cent_offer(api):
    """Outreach, one open dispute, then a sent offer of exactly 30,000,020 cents."""
    scenario = deal_in_outreach(api)
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.PROPERTY_USE.value,
        description="Equipment staged outside the leased area",
    )
    scenario["offer"] = get_success_data(
        api.create_offer(
            scenario.deal_id,
            offer_payload(amount_cents=30_000_020),
            headers=make_acquisition_analyst_headers(),
        )
    )
    get_success_data(
        api.transition_offer(
            scenario.offer_id, {"action": "SEND"}, headers=make_acquisition_analyst_headers()
        )
    )
    return scenario


def test_settlement_rounds_the_broker_fee_down_and_the_dispute_holdback_up(api):
    """On a gross of 30,000,020 cents the 150 basis-point broker fee is 450,000.30 and rounds
    down to 450,000, while the single dispute's 250 basis-point holdback is exactly 750,000.50
    and rounds up to 750,001.

    PRD 3.7: "The broker tier is keyed on **gross**, on a ladder evaluated from the top: a gross at or above 30,000,000 cents — three hundred thousand dollars — sets `broker_fee_bps` to 150; failing that, a gross at or above 10,000,000 cents — one hundred thousand dollars — sets it to 200; anything below that sets it to 250."
    PRD 3.7: "`broker_fee_cents` is gross multiplied by `broker_fee_bps`, divided by ten thousand, rounded half up to a whole number of cents."
    PRD 3.7: "The holdback rate is that count multiplied by 250 basis points, capped at 1000 basis points — so from four unresolved disputes onward the holdback stops growing at ten percent of gross."
    PRD 3.7: "`holdback_cents` is gross multiplied by that capped rate, divided by ten thousand, rounded half up to a whole number of cents."
    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."
    PRD 2.5: "Wherever a calculation must land on an integer, the rounding method is **round half up**: a value whose fractional remainder is exactly one half rounds away from zero to the next integer of larger magnitude."
    PRD 3.7: "A read-only settlement projection is available for any deal, returning `deal_id`, `agreed_consideration_cents`, `broker_fee_bps`, `broker_fee_cents`, `holdback_cents`, `net_landowner_proceeds_cents`, `total_commitment_cents`, `escrow_funded_cents`, `escrow_disbursed_cents`, `escrow_holdback_cents`, and `escrow_refunded_cents`."

    Design: Corner/calculations/precision_settlement_holdback_half_cent_rounds_half_up_while_the_fee_rounds_down
    """
    scenario = _accept_a_thirty_million_and_twenty_cent_offer(api)

    accepted = validate_success(
        api.transition_offer(
            scenario.offer_id,
            {"action": "ACCEPT"},
            headers=make_landowner_headers(scenario.landowner_id),
        )
    )
    assert accepted["amount_cents"] == 30_000_020

    settlement = validate_success(
        api.get_settlement(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert_has_fields(
        settlement,
        (
            "deal_id",
            "agreed_consideration_cents",
            "broker_fee_bps",
            "broker_fee_cents",
            "holdback_cents",
            "net_landowner_proceeds_cents",
            "total_commitment_cents",
            "escrow_funded_cents",
            "escrow_disbursed_cents",
            "escrow_holdback_cents",
            "escrow_refunded_cents",
        ),
        "SettlementProjection",
    )
    assert_fields(
        settlement,
        {
            "deal_id": scenario.deal_id,
            "agreed_consideration_cents": 30_000_020,
            "broker_fee_bps": THRESHOLDS["BROKER_FEE_BPS_HIGH"],
            "broker_fee_cents": 450_000,
            "holdback_cents": 750_001,
            "net_landowner_proceeds_cents": 29_250_019,
            "total_commitment_cents": 30_450_020,
        },
        "SettlementProjection",
    )
    assert_settlement_arithmetic(settlement, expected_open_dispute_count=1)


def test_the_rounded_commitment_reserves_thirty_million_four_hundred_fifty_thousand(api):
    """The commitment the pool sets aside is gross plus the rounded-down fee, so committed
    capital is 30,450,020 cents, available capital 19,549,980, and utilization exactly 6090
    basis points of the 50,000,000-cent pool.

    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."
    PRD 3.1: "`committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`."
    PRD 3.1: "`available_capital_cents` is `total_capital_cents` less `committed_capital_cents` less `deployed_capital_cents`."
    PRD 3.1: "Utilization is measured against the whole pool: let *used* be the sum of `committed_capital_cents` and `deployed_capital_cents`; then `utilization_bps` is zero when `total_capital_cents` is zero, and otherwise is *used* multiplied by ten thousand, divided by `total_capital_cents`, and rounded half up to a whole number of basis points."

    Design: Corner/calculations/precision_settlement_holdback_half_cent_rounds_half_up_while_the_fee_rounds_down
    """
    scenario = _accept_a_thirty_million_and_twenty_cent_offer(api)

    get_success_data(
        api.transition_offer(
            scenario.offer_id,
            {"action": "ACCEPT"},
            headers=make_landowner_headers(scenario.landowner_id),
        )
    )

    deal = validate_success(api.get_deal(scenario.deal_id, headers=make_acquisition_analyst_headers()))
    assert deal["capital_state"] == "RESERVED"
    assert deal["agreed_consideration_cents"] == 30_000_020

    portfolio = validate_success(
        api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers())
    )
    assert_fields(
        portfolio,
        {
            "total_capital_cents": 50_000_000,
            "committed_capital_cents": 30_450_020,
            "deployed_capital_cents": 0,
            "available_capital_cents": 19_549_980,
            "utilization_bps": 6090,
        },
        "Portfolio ledger after the reservation",
    )
    assert_portfolio_ledger_balances(portfolio)
    assert_utilization_and_posture(portfolio)


# ===========================================================================
# The score total is clamped to one hundred before the tier lookup
# ===========================================================================


def test_three_investment_grade_tenancies_clamp_the_stream_score_at_one_hundred(api):
    """Two anchors at forty points each plus a colocation at twenty-four total 104, yet the
    stream reports one hundred while each tenancy keeps its own uncapped points.

    PRD 3.3: "Multiply those base points by the type multiplier for its `tenancy_type`: one exactly for `ANCHOR`, six tenths for `COLOCATION`."
    PRD 3.3: "Store on the tenancy, as its `quality_points`, that same figure rounded half up to a whole number."
    PRD 3.3: "The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred."

    Design: Corner/calculations/weighted_scoring_total_clamped_to_one_hundred_before_the_tier_lookup
    """
    roster_overrides = [
        {},
        dict(SECOND_INVESTMENT_GRADE_ANCHOR),
        dict(INVESTMENT_GRADE_COLOCATION, headers=make_servicing_agent_headers()),
    ]
    scenario = build_asset_graph(api, tenancies=roster_overrides)

    roster, meta = _list_tenancies(api, scenario.lease_stream_id)
    assert meta["total_count"] == 3, f"three tenancies were added, meta says {meta['total_count']}"
    assert roster["Vantage Wireless"]["quality_points"] == 40
    assert roster["Ridgeline Towers"]["quality_points"] == 40
    assert roster["Northline Broadband"]["quality_points"] == 24, (
        "an INVESTMENT_GRADE colocation is forty points at six tenths, which is twenty-four"
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert_lease_stream(stream)
    assert_fields(
        stream,
        {
            "tenancy_quality_score": THRESHOLDS["STREAM_SCORE_MAX"],
            "active_tenancy_count": 3,
            "anchor_carrier_name": "Vantage Wireless",
        },
        "LeaseStream with a 104-point roster",
    )
    assert (
        roster["Vantage Wireless"]["quality_points"]
        + roster["Ridgeline Towers"]["quality_points"]
        + roster["Northline Broadband"]["quality_points"]
        == 104
    ), "the clamp belongs to the total, so the per-tenancy points still sum above one hundred"


def test_the_clamped_score_of_one_hundred_prices_on_the_seven_hundred_basis_point_tier(api):
    """The clamped total of one hundred, not the raw 104, is snapshotted and looked up, giving
    the top rung of 700 basis points and a value of 64,151,290 cents.

    PRD 3.3: "The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred."
    PRD 3.4: "That snapshot picks the base discount tier from a four-rung ladder evaluated from the top down: a score of 80 or more prices at 700 basis points; failing that, a score of 60 or more prices at 850; failing that, a score of 40 or more prices at 1000; and anything below 40 prices at 1250."
    PRD 3.4: "`value_cents` is the sum of those rounded per-year figures."
    PRD 3.4: "`max_bid_cents` is `value_cents` multiplied by 10500 basis points divided by ten thousand — one hundred five percent of model value — rounded half up to a whole number of cents."

    Design: Corner/calculations/weighted_scoring_total_clamped_to_one_hundred_before_the_tier_lookup
    """
    scenario = build_asset_graph(
        api,
        tenancies=[
            {},
            dict(SECOND_INVESTMENT_GRADE_ANCHOR),
            dict(INVESTMENT_GRADE_COLOCATION, headers=make_servicing_agent_headers()),
        ],
    )

    valuation = _lump_sum_valuation(api, scenario.lease_stream_id)

    assert_valuation(valuation)
    assert_fields(
        valuation,
        {
            "tenancy_quality_score_snapshot": 100,
            "discount_rate_bps": THRESHOLDS["DISCOUNT_BPS_SCORE_80_PLUS"],
            "growth_rate_bps": 300,
            "horizon_years": THRESHOLDS["LUMP_SUM_HORIZON_YEARS"],
            "value_cents": VALUE_AT_700_BPS,
            "max_bid_cents": MAX_BID_AT_700_BPS,
        },
        "StreamValuation on a clamped score",
    )
    assert_max_bid_ceiling(valuation)


# ===========================================================================
# A pledge takes its basis from the facility, not from the stream's valuation
# ===========================================================================


def test_a_cost_basis_facility_pledges_at_the_closed_deal_commitment(api):
    """A COST_BASIS facility freezes that choice on the pledge and values the collateral at the
    closed deal's 36,540,000-cent commitment, ignoring the stream's larger approved valuation of
    44,627,011.

    PRD 3.9: "`valuation_basis_snapshot` copies the facility's `valuation_basis` at the moment of pledging, so later edits to the facility do not revalue existing collateral."
    PRD 3.9: "`basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream."
    PRD 3.9: "`eligible_value_cents` is then zero whenever the pledge's `status` is `INELIGIBLE` or `RELEASED` or the stream's `servicing_status` is `IMPAIRED`, and otherwise is `basis_value_cents` multiplied by the quantity one less `haircut_bps` divided by ten thousand, rounded half up to a whole number of cents."

    Design: Corner/calculations/variant_selection_pledge_snapshots_the_facility_basis_rather_than_the_valuation
    """
    scenario = build_facility_with_pledge(
        api,
        facility={"valuation_basis": ValuationBasis.COST_BASIS.value, "facility_name": "Warehouse C"},
    )
    settlement = validate_success(
        api.get_settlement(scenario.deal_id, headers=make_acquisition_analyst_headers())
    )
    assert settlement["total_commitment_cents"] == 36_540_000
    assert scenario["valuation"]["value_cents"] == VALUE_AT_1000_BPS, (
        "the approved valuation is present and strictly larger than the deal's commitment"
    )

    pledge = validate_success(
        api.get_collateral_pledge(scenario["pledge"]["id"], headers=make_treasury_officer_headers())
    )

    assert_pledge(pledge)
    assert_fields(
        pledge,
        {
            "lease_stream_id": scenario.lease_stream_id,
            "status": PledgeStatus.PLEDGED.value,
            "valuation_basis_snapshot": ValuationBasis.COST_BASIS.value,
            "basis_value_cents": 36_540_000,
            "haircut_bps": THRESHOLDS["HAIRCUT_BPS_PERFORMING"],
            "eligible_value_cents": 36_540_000,
        },
        "CollateralPledge on a COST_BASIS facility",
    )
    assert_pledge_eligible_value(pledge)
    assert pledge["basis_value_cents"] == settlement["total_commitment_cents"]


def test_the_cost_basis_borrowing_base_follows_the_commitment_not_the_model_value(api):
    """The cost-basis pool of 36,540,000 cents at a 6500 basis-point advance rate supports
    23,751,000 — not the 29,007,557 the stream's model value would have produced.

    PRD 3.9: "`basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream."
    PRD 3.9: "First, `pledged_eligible_total_cents` is the sum of `eligible_value_cents` across the facility's pledges in `PLEDGED`."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."

    Design: Corner/calculations/variant_selection_pledge_snapshots_the_facility_basis_rather_than_the_valuation
    """
    scenario = build_facility_with_pledge(
        api,
        facility={"valuation_basis": ValuationBasis.COST_BASIS.value, "facility_name": "Warehouse C"},
    )

    facility = read_facility(api, scenario.facility_id)

    assert_facility(facility)
    assert_fields(
        facility,
        {
            "valuation_basis": ValuationBasis.COST_BASIS.value,
            "advance_rate_bps": 6500,
            "pledged_eligible_total_cents": 36_540_000,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": 23_751_000,
            "pledged_stream_count": 1,
            "compliance_state": ComplianceState.COMPLIANT.value,
        },
        "FinancingFacility on a cost basis",
    )
    assert_borrowing_base(facility)
    assert facility["borrowing_base_cents"] == bps_of(36_540_000, 6500)
    assert facility["borrowing_base_cents"] != bps_of(VALUE_AT_1000_BPS, 6500), (
        "a cost-basis facility must not lend against the stream's model value"
    )
