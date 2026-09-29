"""Endpoint surfaces of the lease-buyout pipeline, read and written one call at a time.

Each test drives a single declared endpoint — a settlement projection, a landowner patch,
a tenancy reclassification, an escrow funding attempt, a collateral pledge, a filtered
collection, a dispute dismissal, an amendment booking — and then reads the result back
through the endpoints an operator would actually use, checking the values the PRD pins
for the resource, its parents and the collection envelope.
"""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    THRESHOLDS,
    adjust_capital,
    approve_valuation,
    assert_collection_page,
    assert_fields,
    bps_of,
    build_asset_graph,
    closed_deal,
    create_facility,
    create_portfolio,
    create_tower_site,
    create_valuation,
    deal_in_diligence,
    ids_of,
    make_landowner_headers,
    make_tower_company_agent_headers,
    open_dispute,
    transition_dispute,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- Figures the PRD's own formulas produce from the canonical seed stream ---------
# PRD 3.7 keys the broker tier on gross: 36,000,000 cents sits at or above the
# 30,000,000-cent rung, so the fee is 150 bps and the commitment is gross plus that fee.
ACCEPTED_GROSS_CENTS = 36_000_000
EXPECTED_BROKER_FEE_CENTS = bps_of(ACCEPTED_GROSS_CENTS, THRESHOLDS["BROKER_FEE_BPS_HIGH"])
EXPECTED_COMMITMENT_CENTS = ACCEPTED_GROSS_CENTS + EXPECTED_BROKER_FEE_CENTS

# PRD 3.4 walked over forty years on the canonical stream (3,600,000 cents of annual rent,
# a 300-bps fixed escalator, 180 remaining months, a score of 40 pricing at 1000 bps, and
# the 2000-bps renewal haircut on every year past the fifteen contracted ones).
CANONICAL_LUMP_SUM_VALUE_CENTS = 44_627_011

# PRD 3.9: a PERFORMING stream carries a zero haircut, so eligible value equals basis, and
# the borrowing base is that pool times the facility's advance rate.
FACILITY_ADVANCE_RATE_BPS = 6500
WIDE_OPEN_CONCENTRATION_LIMIT_BPS = 10_000
EXPECTED_ELIGIBLE_VALUE_CENTS = CANONICAL_LUMP_SUM_VALUE_CENTS
EXPECTED_BORROWING_BASE_CENTS = bps_of(EXPECTED_ELIGIBLE_VALUE_CENTS, FACILITY_ADVANCE_RATE_BPS)

# PRD 3.8: a RENT_INCREASE halves the deal's headline participation, truncating toward zero.
DEAL_REVENUE_SHARE_BPS = 2500
RENT_INCREASE_GROSS_CENTS = 1_000_002
RENT_INCREASE_SHARE_BPS = DEAL_REVENUE_SHARE_BPS // 2
RENT_INCREASE_LANDOWNER_CENTS = bps_of(RENT_INCREASE_GROSS_CENTS, RENT_INCREASE_SHARE_BPS)
RENT_INCREASE_ACQUIRER_CENTS = RENT_INCREASE_GROSS_CENTS - RENT_INCREASE_LANDOWNER_CENTS

# PRD 3.7 pins the settlement projection to exactly these eleven fields.
SETTLEMENT_FIELDS = (
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
)


# ===========================================================================
# The settlement projection
# ===========================================================================


def test_settlement_projection_mirrors_the_closed_deal_ledger(api, treasury_headers, manager_headers):
    """The settlement read on a closed deal carries the eleven pinned figures, and the
    escrow triple reconciles: what was funded equals what was disbursed plus what was held back.

    PRD 3.7: "A read-only settlement projection is available for any deal, returning `deal_id`, `agreed_consideration_cents`, `broker_fee_bps`, `broker_fee_cents`, `holdback_cents`, `net_landowner_proceeds_cents`, `total_commitment_cents`, `escrow_funded_cents`, `escrow_disbursed_cents`, `escrow_holdback_cents`, and `escrow_refunded_cents`."
    PRD 3.7: "The broker tier is keyed on **gross**, on a ladder evaluated from the top: a gross at or above 30,000,000 cents — three hundred thousand dollars — sets `broker_fee_bps` to 150; failing that, a gross at or above 10,000,000 cents — one hundred thousand dollars — sets it to 200; anything below that sets it to 250."
    PRD 3.7: "`net_landowner_proceeds_cents` is gross less `holdback_cents`, and `total_commitment_cents` — the figure the portfolio actually has to set aside — is gross plus `broker_fee_cents`."
    PRD 3.7: "It takes capital `RESERVED → ESCROWED` and sets `escrow_funded_cents` equal to `total_commitment_cents`."
    PRD 3.7: "Capital moves `ESCROWED → DISBURSED`, with `escrow_disbursed_cents` set to the sum of `net_landowner_proceeds_cents` and `broker_fee_cents` and `escrow_holdback_cents` set to `holdback_cents`, so that the disbursement and the retained holdback together account for everything that was funded."

    Design: Corner/endpoints/computed_read_settlement_projection_matches_the_closed_deal_ledger
    """
    scenario = closed_deal(api)

    settlement = validate_success(api.get_settlement(scenario.deal_id, headers=treasury_headers))

    assert set(settlement.keys()) == set(SETTLEMENT_FIELDS), (
        "the settlement projection must expose exactly the eleven fields PRD 3.7 pins, got "
        f"{sorted(settlement.keys())}"
    )
    assert_fields(
        settlement,
        {
            "deal_id": scenario.deal_id,
            "agreed_consideration_cents": ACCEPTED_GROSS_CENTS,
            "broker_fee_bps": THRESHOLDS["BROKER_FEE_BPS_HIGH"],
            "broker_fee_cents": EXPECTED_BROKER_FEE_CENTS,
            "holdback_cents": 0,
            "net_landowner_proceeds_cents": ACCEPTED_GROSS_CENTS,
            "total_commitment_cents": EXPECTED_COMMITMENT_CENTS,
            "escrow_funded_cents": EXPECTED_COMMITMENT_CENTS,
            "escrow_disbursed_cents": EXPECTED_COMMITMENT_CENTS,
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "settlement projection",
    )
    assert (
        settlement["escrow_disbursed_cents"] + settlement["escrow_holdback_cents"]
        == settlement["escrow_funded_cents"]
    ), "the disbursement and the retained holdback must together account for the funding"

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert_fields(
        deal,
        {
            "stage": "CLOSED",
            "easement_status": "RECORDED",
            "escrow_holdback_cents": 0,
            "escrow_refunded_cents": 0,
        },
        "closed deal",
    )
    assert deal["recording_ref"], "closing stores the county recording reference on the deal"


# ===========================================================================
# The landowner patch surface
# ===========================================================================


def test_suppressing_outreach_forces_do_not_contact_and_reads_back(api, analyst_headers, servicing_headers):
    """Patching a landowner with suppress_outreach true overrides the progression-derived
    status, and the single-resource read returns that override with the untouched email.

    PRD 3.2: "Setting `suppress_outreach` to true forces `outreach_status` to `DO_NOT_CONTACT`, which is the one value the progression logic never produces on its own; setting it back to false restores whatever value the offer and deal progression implies."
    PRD 2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation of the resource."

    Design: Corner/endpoints/standard_crud_landowner_patch_toggles_suppression_and_reads_back
    """
    scenario = build_asset_graph(api, tenancies=())
    landowner = scenario.landowner
    assert_fields(
        landowner,
        {"outreach_status": "NEW", "version": 1, "open_dispute_count": 0},
        "freshly registered landowner",
    )
    original_email = landowner["contact_email"]

    patched = validate_success(
        api.update_landowner(scenario.landowner_id, {"suppress_outreach": True}, headers=analyst_headers)
    )
    assert_fields(
        patched,
        {"outreach_status": "DO_NOT_CONTACT", "contact_email": original_email, "version": 2},
        "suppressed landowner",
    )

    read_back = validate_success(api.get_landowner(scenario.landowner_id, headers=servicing_headers))
    assert_fields(
        read_back,
        {"outreach_status": "DO_NOT_CONTACT", "contact_email": original_email, "version": 2},
        "landowner read back",
    )


def test_clearing_suppression_restores_the_progression_status_and_keeps_the_new_email(
    api, analyst_headers, admin_headers
):
    """A second patch that clears suppression and corrects the email restores the
    progression-derived NEW, since this landowner has no offers, and keeps the new address.

    PRD 3.2: "A `PlatformAdmin` or `AcquisitionAnalyst` may patch a landowner to correct `contact_email`, and may pass a `suppress_outreach` boolean."
    PRD 3.2: "Setting `suppress_outreach` to true forces `outreach_status` to `DO_NOT_CONTACT`, which is the one value the progression logic never produces on its own; setting it back to false restores whatever value the offer and deal progression implies."
    PRD 3.2: "Its `outreach_status` is initialized to `NEW` and thereafter tracks the progression of offers and deals through `CONTACTED`, `NEGOTIATING`, `UNDER_CONTRACT`, and `CLOSED`."

    Design: Corner/endpoints/standard_crud_landowner_patch_toggles_suppression_and_reads_back
    """
    scenario = build_asset_graph(api, tenancies=())
    validate_success(
        api.update_landowner(scenario.landowner_id, {"suppress_outreach": True}, headers=analyst_headers)
    )

    restored = validate_success(
        api.update_landowner(
            scenario.landowner_id,
            {"contact_email": "estate@hollis.example", "suppress_outreach": False},
            headers=admin_headers,
        )
    )
    assert_fields(
        restored,
        {
            "outreach_status": "NEW",
            "contact_email": "estate@hollis.example",
            "version": 3,
            "open_dispute_count": 0,
        },
        "landowner after suppression is lifted",
    )

    read_back = validate_success(api.get_landowner(scenario.landowner_id, headers=admin_headers))
    assert_fields(
        read_back,
        {"outreach_status": "NEW", "contact_email": "estate@hollis.example", "version": 3},
        "landowner read back",
    )


# ===========================================================================
# Reclassifying a carrier tenancy
# ===========================================================================


def test_holdover_reclassification_lowers_the_stream_score_and_stales_the_valuation(
    api, servicing_headers, manager_headers, analyst_headers
):
    """Moving the only tenancy to HOLDOVER costs five points, keeps it inside the active
    roster, and marks the stream's approved price stale rather than deleting it.

    PRD 3.3: "A `ServicingAgent` may later reclassify a tenancy's `status` to `ACTIVE`, `HOLDOVER`, or `TERMINATED`."
    PRD 3.3: "If the tenancy's `status` is `HOLDOVER`, subtract five points from the rounded figure as a holdover penalty."
    PRD 3.3: "Store on the tenancy, as its `quality_points`, that same figure rounded half up to a whole number."
    PRD 3.3: "`active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`."
    PRD 3.3: "It also invalidates pricing: every valuation on that stream in `DRAFT` or `APPROVED` is moved to `STALE`, because its snapshotted score no longer matches the live score."
    PRD 2.3: "Carrier tenancies under a stream may be filtered by `status` and by `tenancy_type`."
    PRD 2.3: "Stream valuations under a stream may be filtered by `status` and by `method`."

    Design: Corner/endpoints/action_endpoint_holdover_status_change_repoints_the_score_and_stales_the_valuation
    """
    scenario = build_asset_graph(api)
    tenancy = scenario.tenancies[0]
    valuation = approve_valuation(api, create_valuation(api, scenario.lease_stream_id)["id"])
    assert_fields(
        valuation,
        {"status": "APPROVED", "tenancy_quality_score_snapshot": 40, "value_cents": CANONICAL_LUMP_SUM_VALUE_CENTS},
        "approved valuation before the roster moves",
    )

    reclassified = validate_success(
        api.set_tenancy_status(tenancy["id"], {"status": "HOLDOVER"}, headers=servicing_headers)
    )
    assert_fields(reclassified, {"status": "HOLDOVER", "quality_points": 35}, "reclassified tenancy")

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))
    assert_fields(
        stream,
        {
            "tenancy_quality_score": 35,
            "active_tenancy_count": 1,
            "anchor_carrier_name": tenancy["carrier_name"],
        },
        "stream after the holdover penalty",
    )

    holdover_rows, holdover_meta = validate_paginated(
        api.list_tenancies(scenario.lease_stream_id, params={"status": "HOLDOVER"}, headers=servicing_headers)
    )
    assert_collection_page(holdover_meta, total_count=1, item_count=len(holdover_rows), has_more=False)
    assert ids_of(holdover_rows) == [tenancy["id"]], "the HOLDOVER filter must return the reclassified tenancy"

    stale_rows, stale_meta = validate_paginated(
        api.list_valuations(scenario.lease_stream_id, params={"status": "STALE"}, headers=manager_headers)
    )
    assert_collection_page(stale_meta, total_count=1, item_count=len(stale_rows), has_more=False)
    assert ids_of(stale_rows) == [valuation["id"]], "the approved valuation must survive as a STALE row"
    assert stale_rows[0]["value_cents"] == CANONICAL_LUMP_SUM_VALUE_CENTS, (
        "staling a valuation must not rewrite the price it computed"
    )


# ===========================================================================
# Escrow funding is gated on the deal's stage
# ===========================================================================


def test_escrow_funding_before_clearance_is_refused_on_the_deal_stage(api, treasury_headers, manager_headers):
    """A deal in DILIGENCE already holds reserved capital, yet funding escrow is refused
    because clearance has not been reached, and no escrow figure is written.

    PRD 3.7: "**Escrow funding** is the `TreasuryOfficer`'s step, and it is permitted only from `capital_state` `RESERVED` while the deal's `stage` is `CLEAR_TO_CLOSE`."
    PRD 2.8: "**Deal stage admits the action** — the deal's `stage` permits the operation; otherwise `ERR_INVALID_DEAL_STAGE` (409)."
    PRD 2.8: "Checks are evaluated in the following order, and the **first** failing check determines the response; later checks are not evaluated once an earlier one has failed."

    Design: Corner/endpoints/conditional_action_escrow_funding_before_clearance_rejected
    """
    scenario = deal_in_diligence(api)
    before = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert_fields(
        before,
        {"stage": "DILIGENCE", "capital_state": "RESERVED", "escrow_funded_cents": 0},
        "deal awaiting diligence",
    )

    validate_error(
        api.fund_escrow(scenario.deal_id, headers=treasury_headers),
        ApiErrorId.ERR_INVALID_DEAL_STAGE.value,
    )

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert_fields(
        deal,
        {"stage": "DILIGENCE", "capital_state": "RESERVED", "escrow_funded_cents": 0},
        "deal after the refused funding",
    )

    portfolio = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    assert_fields(
        portfolio,
        {"committed_capital_cents": EXPECTED_COMMITMENT_CENTS, "deployed_capital_cents": 0},
        "portfolio ledger after the refused funding",
    )


# ===========================================================================
# Pledging a stream links two ends and both are resolved
# ===========================================================================


def test_pledging_an_unknown_stream_leaves_the_facility_intact_and_the_retry_links_it(
    api, treasury_headers, manager_headers
):
    """A pledge naming a stream that does not exist is a body-reference failure that writes
    nothing, so the same facility version still admits the retry that creates the link.

    PRD 2.8: "**Body foreign-key existence** — every reference carried in the request body resolves; otherwise the matching not-found error (404)."
    PRD 2.9: "A pledge creation naming a `lease_stream_id` that does not resolve yields `ERR_LEASE_STREAM_NOT_FOUND`; a deal creation naming an unresolvable `portfolio_id`, `lease_stream_id`, or `valuation_id` yields `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, or `ERR_VALUATION_NOT_FOUND` respectively; a facility creation naming an unresolvable `portfolio_id` yields `ERR_PORTFOLIO_NOT_FOUND`; a tower site naming an unresolvable `tower_company_id` yields `ERR_TOWER_COMPANY_NOT_FOUND`; and a lease stream naming an unresolvable `tower_site_id` or `landowner_id` yields `ERR_TOWER_SITE_NOT_FOUND` or `ERR_LANDOWNER_NOT_FOUND`."
    PRD 2.7: "Its value must equal the target `FinancingFacility`'s current `version`."
    PRD 3.9: "`basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream."
    PRD 3.9: "`haircut_bps` is read from the stream's `servicing_status` — zero basis points while `PERFORMING`, 3000 while on `WATCHLIST`, 5000 while `DELINQUENT`, and the full 10000 while `IMPAIRED`."
    PRD 3.9: "Finally, `borrowing_base_cents` is that concentration-adjusted pool multiplied by `advance_rate_bps`, divided by ten thousand, rounded half up to a whole number of cents."
    PRD 2.3: "Financing facilities under a portfolio may be filtered by `compliance_state`."

    Design: Corner/endpoints/cross_reference_link_pledge_requires_both_facility_and_stream_to_exist
    """
    scenario = closed_deal(api)
    facility = create_facility(
        api,
        scenario.portfolio_id,
        advance_rate_bps=FACILITY_ADVANCE_RATE_BPS,
        valuation_basis="MARK_TO_MODEL",
        carrier_concentration_limit_bps=WIDE_OPEN_CONCENTRATION_LIMIT_BPS,
    )
    pinned_version = facility["version"]
    assert_fields(
        facility,
        {"version": 1, "pledged_stream_count": 0, "borrowing_base_cents": 0, "compliance_state": "COMPLIANT"},
        "freshly opened facility",
    )

    body = {
        "lease_stream_id": UNKNOWN_UUID,
        "pledge_start_date": "2026-08-01",
        "pledge_end_date": "2026-12-31",
        "expected_facility_version": pinned_version,
    }
    validate_error(
        api.create_pledge(facility["id"], body, headers=treasury_headers),
        ApiErrorId.ERR_LEASE_STREAM_NOT_FOUND.value,
    )

    body["lease_stream_id"] = scenario.lease_stream_id
    pledge = validate_success(api.create_pledge(facility["id"], body, headers=treasury_headers), 201)
    assert_fields(
        pledge,
        {
            "facility_id": facility["id"],
            "lease_stream_id": scenario.lease_stream_id,
            "status": "PLEDGED",
            "valuation_basis_snapshot": "MARK_TO_MODEL",
            "basis_value_cents": CANONICAL_LUMP_SUM_VALUE_CENTS,
            "haircut_bps": THRESHOLDS["HAIRCUT_BPS_PERFORMING"],
            "eligible_value_cents": EXPECTED_ELIGIBLE_VALUE_CENTS,
        },
        "collateral pledge",
    )
    assert pledge["basis_value_cents"] == scenario.valuation["value_cents"], (
        "a MARK_TO_MODEL pledge takes its basis from the stream's approved valuation"
    )

    refreshed = validate_success(api.get_financing_facility(facility["id"], headers=treasury_headers))
    assert_fields(
        refreshed,
        {
            "pledged_stream_count": 1,
            "pledged_eligible_total_cents": EXPECTED_ELIGIBLE_VALUE_CENTS,
            "concentration_excess_cents": 0,
            "borrowing_base_cents": EXPECTED_BORROWING_BASE_CENTS,
            "advances_outstanding_cents": 0,
            "compliance_state": "COMPLIANT",
        },
        "facility after the pledge",
    )

    rows, meta = validate_paginated(
        api.list_portfolio_financing_facilities(
            scenario.portfolio_id, params={"compliance_state": "COMPLIANT"}, headers=manager_headers
        )
    )
    assert_collection_page(meta, total_count=1, item_count=len(rows), has_more=False)
    assert ids_of(rows) == [facility["id"]], "the portfolio's facility list must return the compliant facility"


# ===========================================================================
# Portfolio listing partitions on the recomputed posture
# ===========================================================================


def test_portfolio_list_filtered_by_capital_posture_reflects_the_recomputed_ledger(
    api, manager_headers, treasury_headers
):
    """Withdrawing every free cent from a pool that already carries a reserved deal drives
    utilization to the whole and freezes it, so the posture filter separates it from an untouched pool.

    PRD 3.1: "Utilization is measured against the whole pool: let *used* be the sum of `committed_capital_cents` and `deployed_capital_cents`; then `utilization_bps` is zero when `total_capital_cents` is zero, and otherwise is *used* multiplied by ten thousand, divided by `total_capital_cents`, and rounded half up to a whole number of basis points."
    PRD 3.1: "Posture follows utilization through a two-rung ladder evaluated from the top: when `utilization_bps` is at or above 9000 — that is, ninety percent of the pool or more is spoken for — `capital_posture` is `FROZEN`; otherwise, when `utilization_bps` is at or above 7500, it is `CONSTRAINED`; otherwise it is `OPEN`."
    PRD 3.1: "At every moment the three balances must add back to the whole: `available_capital_cents` plus `committed_capital_cents` plus `deployed_capital_cents` equals `total_capital_cents`."
    PRD 2.10: "A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`."
    PRD 2.3: "Portfolios may be filtered by `capital_posture`."
    PRD 2.3: "The `meta` object of a collection response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."

    Design: Corner/endpoints/computed_read_portfolio_list_filtered_by_capital_posture_reflects_the_ledger
    """
    scenario = deal_in_diligence(api)
    idle_pool = create_portfolio(
        api,
        name="Mid-Atlantic Tower Aggregation",
        program_code="MA-AGG-02",
        total_capital_cents=25_000_000,
    )

    reserved_pool = validate_success(api.get_portfolio(scenario.portfolio_id, headers=manager_headers))
    free_capital = reserved_pool["available_capital_cents"]
    assert free_capital == reserved_pool["total_capital_cents"] - EXPECTED_COMMITMENT_CENTS, (
        "available capital is the pool less the reserved commitment"
    )

    drained = adjust_capital(api, scenario.portfolio_id, -free_capital, memo="Return uninvested capital")
    assert_fields(
        drained,
        {
            "total_capital_cents": EXPECTED_COMMITMENT_CENTS,
            "committed_capital_cents": EXPECTED_COMMITMENT_CENTS,
            "deployed_capital_cents": 0,
            "available_capital_cents": 0,
            "utilization_bps": 10_000,
            "capital_posture": "FROZEN",
            "active_deal_count": 1,
        },
        "fully committed portfolio",
    )

    frozen_rows, frozen_meta = validate_paginated(
        api.list_portfolios(params={"capital_posture": "FROZEN"}, headers=manager_headers)
    )
    assert_collection_page(frozen_meta, total_count=1, item_count=len(frozen_rows), has_more=False)
    assert ids_of(frozen_rows) == [scenario.portfolio_id], "only the drained pool may answer the FROZEN filter"

    open_rows, open_meta = validate_paginated(
        api.list_portfolios(params={"capital_posture": "OPEN"}, headers=manager_headers)
    )
    assert_collection_page(open_meta, total_count=1, item_count=len(open_rows), has_more=False)
    assert ids_of(open_rows) == [idle_pool["id"]], "only the untouched pool may answer the OPEN filter"

    single_read = validate_success(api.get_portfolio(scenario.portfolio_id, headers=treasury_headers))
    assert_fields(
        single_read,
        {"utilization_bps": 10_000, "available_capital_cents": 0, "capital_posture": "FROZEN"},
        "single read of the frozen portfolio",
    )
    assert (
        single_read["available_capital_cents"]
        + single_read["committed_capital_cents"]
        + single_read["deployed_capital_cents"]
        == single_read["total_capital_cents"]
    ), "the three balances must add back to the whole pool"

    idle_read = validate_success(api.get_portfolio(idle_pool["id"], headers=treasury_headers))
    assert_fields(
        idle_read,
        {"utilization_bps": 0, "capital_posture": "OPEN", "active_deal_count": 0},
        "single read of the idle portfolio",
    )


# ===========================================================================
# Tower site listing and the derived child count
# ===========================================================================


def test_tower_site_filters_are_independent_and_the_site_read_shows_its_stream_count(
    api, title_headers, manager_headers
):
    """The state and structure filters on the site list partition independently, and the
    single-resource read reports the number of rent streams recorded beneath each site.

    PRD 2.3: "Tower sites may be filtered by `tower_company_id`, by `state_code`, and by `structure_type`."
    PRD 3.2: "The site's own `lease_stream_count` is derived from the streams recorded beneath it."
    PRD 3.2: "A **TowerSite** hangs off a tower company by way of a `tower_company_id` and describes the physical location: a `site_code` unique across all sites, a `state_code`, a `ground_area_sqft` footprint of at least one square foot, and a `structure_type` drawn from `MONOPOLE`, `LATTICE`, `GUYED`, and `ROOFTOP`."

    Design: Corner/endpoints/standard_crud_tower_site_listing_filters_and_single_read_expose_the_child_count
    """
    scenario = build_asset_graph(
        api,
        tower_site={"site_code": "NE-7101", "state_code": "NY", "structure_type": "MONOPOLE"},
        tenancies=(),
    )
    rooftop_site = create_tower_site(
        api,
        scenario.tower_company_id,
        site_code="NE-7102",
        state_code="NY",
        structure_type="ROOFTOP",
    )
    jersey_site = create_tower_site(
        api,
        scenario.tower_company_id,
        site_code="NE-7103",
        state_code="NJ",
        structure_type="LATTICE",
    )

    ny_rows, ny_meta = validate_paginated(api.list_tower_sites(params={"state_code": "NY"}, headers=title_headers))
    assert_collection_page(ny_meta, total_count=2, item_count=len(ny_rows), has_more=False)
    assert set(ids_of(ny_rows)) == {scenario.tower_site_id, rooftop_site["id"]}, (
        "the state filter must return both New York sites and not the New Jersey one"
    )

    rooftop_rows, rooftop_meta = validate_paginated(
        api.list_tower_sites(params={"structure_type": "ROOFTOP"}, headers=title_headers)
    )
    assert_collection_page(rooftop_meta, total_count=1, item_count=len(rooftop_rows), has_more=False)
    assert ids_of(rooftop_rows) == [rooftop_site["id"]], "the structure filter must not leak the monopole or lattice"

    tenanted_read = validate_success(api.get_tower_site(scenario.tower_site_id, headers=manager_headers))
    assert_fields(
        tenanted_read,
        {"lease_stream_count": 1, "structure_type": "MONOPOLE", "state_code": "NY", "site_code": "NE-7101"},
        "site carrying a rent stream",
    )

    empty_read = validate_success(api.get_tower_site(jersey_site["id"], headers=manager_headers))
    assert_fields(
        empty_read,
        {"lease_stream_count": 0, "state_code": "NJ", "structure_type": "LATTICE"},
        "site with no rent stream",
    )


# ===========================================================================
# A deal's child collections and the stage filter
# ===========================================================================


def test_deal_child_collections_and_stage_filter_scope_to_the_live_deal(
    api, analyst_headers, manager_headers, lender_headers
):
    """A deal in diligence answers the DILIGENCE stage filter and not the CLOSED one, and
    each of its child collections returns only its own accepted offer, title report and notice.

    PRD 2.3: "Deals may be filtered by `portfolio_id`, by `lease_stream_id`, by `valuation_id`, by `stage`, and by `capital_state`."
    PRD 2.3: "Offers under a deal may be filtered by `status`."
    PRD 2.3: "Right-of-first-refusal notices under a deal may be filtered by `status`."
    PRD 3.6: "A fresh report is stamped with `ordered_at` from the current instant, opens at `review_status` `ORDERED` and `consent_status` `NOT_REQUIRED`, and starts with `mortgage_present` false, `lender_name` unset, and `exception_count` and `open_exception_count` at zero."
    PRD 3.6: "Serving snapshots the tower company's `rofr_window_days` into `window_days_snapshot` — later edits to the tower company do not move an already-served window — sets `served_at` and `window_start` to the current instant, sets `window_end` to `window_days_snapshot` days after `window_start`, opens the notice at `status` `SERVED`, and moves the deal's `rofr_state` to `PENDING`."

    Design: Corner/endpoints/standard_crud_deal_child_collections_and_stage_filtered_listing_read_back
    """
    scenario = deal_in_diligence(api, tower_company={"rofr_required": True, "rofr_window_days": 30})

    title_report = validate_success(
        api.create_title_report(scenario.deal_id, {"snda_required": False}, headers=analyst_headers), 201
    )
    assert_fields(
        title_report,
        {"deal_id": scenario.deal_id, "review_status": "ORDERED", "consent_status": "NOT_REQUIRED"},
        "ordered title report",
    )
    notice = validate_success(api.serve_rofr_notice(scenario.deal_id, {}, headers=analyst_headers), 201)
    assert_fields(
        notice,
        {"deal_id": scenario.deal_id, "status": "SERVED", "window_days_snapshot": 30},
        "served refusal notice",
    )

    diligence_rows, diligence_meta = validate_paginated(
        api.list_deals(
            params={"stage": "DILIGENCE", "portfolio_id": scenario.portfolio_id}, headers=manager_headers
        )
    )
    assert_collection_page(diligence_meta, total_count=1, item_count=len(diligence_rows), has_more=False)
    assert ids_of(diligence_rows) == [scenario.deal_id], "the DILIGENCE filter must return the live deal"

    closed_rows, closed_meta = validate_paginated(
        api.list_deals(params={"stage": "CLOSED", "portfolio_id": scenario.portfolio_id}, headers=manager_headers)
    )
    assert_collection_page(closed_meta, total_count=0, item_count=len(closed_rows), has_more=False)
    assert closed_rows == [], "a deal still in diligence must not answer the CLOSED filter"

    offer_rows, offer_meta = validate_paginated(
        api.list_offers(scenario.deal_id, params={"status": "ACCEPTED"}, headers=manager_headers)
    )
    assert_collection_page(offer_meta, total_count=1, item_count=len(offer_rows), has_more=False)
    assert ids_of(offer_rows) == [scenario.offer_id], "the accepted offer must be the only ACCEPTED row"

    report_rows, report_meta = validate_paginated(
        api.list_title_reports(scenario.deal_id, headers=lender_headers)
    )
    assert_collection_page(report_meta, total_count=1, item_count=len(report_rows), has_more=False)
    assert ids_of(report_rows) == [title_report["id"]], "the title-report list is scoped to this deal"

    notice_rows, notice_meta = validate_paginated(
        api.list_rofr_notices(
            scenario.deal_id,
            params={"status": "SERVED"},
            headers=make_tower_company_agent_headers(scenario.tower_company_id),
        )
    )
    assert_collection_page(notice_meta, total_count=1, item_count=len(notice_rows), has_more=False)
    assert ids_of(notice_rows) == [notice["id"]], "the SERVED filter must return the outstanding notice"

    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert_fields(deal, {"stage": "DILIGENCE", "rofr_state": "PENDING"}, "deal with an open refusal window")


# ===========================================================================
# Dismissing a dispute restores the stream
# ===========================================================================


def test_dismissing_a_reopened_dispute_restores_the_stream_and_shows_in_both_reads(
    api, servicing_headers, admin_headers, manager_headers
):
    """Dismissing a reopened access dispute stamps its resolution, leaves the historical
    cure attempt in place, empties the landowner's open count and lifts the stream off watch.

    PRD 3.8: "The first-pass transition out of `OPEN` also degrades the stream's servicing condition, `PERFORMING → WATCHLIST`, which in turn re-haircuts every pledge of that stream and recomputes the borrowing base of the facility holding them; a stream already on `WATCHLIST` stays there."
    PRD 3.8: "**`REOPEN`** takes the case `CURE_PENDING → REOPENED` and leaves the stream on `WATCHLIST`, awaiting another attempt."
    PRD 3.8: "**`DISMISS`** is likewise available from either `OPEN → DISMISSED` or `REOPENED → DISMISSED` with no precondition; it stamps `resolved_at`, and in both cases the landowner's `open_dispute_count` is recomputed, with a dismissal from `REOPENED` additionally restoring the stream `WATCHLIST → PERFORMING` when no other non-terminal dispute remains on it."
    PRD 3.8: "Starting a cure increments `cure_attempts` and sets `cure_deadline` to thirty days after the current instant — on the first pass from `OPEN` the deadline is set, and on a repeat pass from `REOPENED` it is reset."
    PRD 2.3: "Disputes under a stream may be filtered by `status` and by `dispute_type`."

    Design: Corner/endpoints/action_endpoint_dispute_dismissal_restores_the_stream_and_is_visible_in_both_reads
    """
    scenario = closed_deal(api)
    landowner_headers = make_landowner_headers(scenario.landowner_id)

    dispute = open_dispute(api, scenario.lease_stream_id, landowner_id=scenario.landowner_id)
    assert_fields(dispute, {"status": "OPEN", "dispute_type": "ACCESS", "cure_attempts": 0}, "opened dispute")

    in_cure = transition_dispute(api, dispute["id"], "START_CURE", servicing_headers)
    assert_fields(in_cure, {"status": "CURE_PENDING", "cure_attempts": 1}, "dispute in cure")
    watchlisted = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=manager_headers))
    assert watchlisted["servicing_status"] == "WATCHLIST", (
        f"the first cure attempt puts the stream on watch, got {watchlisted['servicing_status']!r}"
    )

    reopened = transition_dispute(api, dispute["id"], "REOPEN", landowner_headers)
    assert_fields(reopened, {"status": "REOPENED", "cure_attempts": 1}, "reopened dispute")

    dismissed = validate_success(
        api.transition_dispute(dispute["id"], {"action": "DISMISS"}, headers=admin_headers)
    )
    assert_fields(dismissed, {"status": "DISMISSED", "cure_attempts": 1}, "dismissed dispute")
    assert dismissed["resolved_at"], "a dismissal stamps resolved_at"

    open_rows, open_meta = validate_paginated(
        api.list_disputes(scenario.lease_stream_id, params={"status": "OPEN"}, headers=manager_headers)
    )
    assert_collection_page(open_meta, total_count=0, item_count=len(open_rows), has_more=False)
    assert open_rows == [], "no OPEN dispute may remain on the stream after the dismissal"

    single_read = validate_success(api.get_dispute(dispute["id"], headers=servicing_headers))
    assert_fields(
        single_read,
        {"status": "DISMISSED", "cure_attempts": 1, "dispute_type": "ACCESS"},
        "dismissed dispute read back",
    )

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=manager_headers))
    assert_fields(
        stream,
        {"servicing_status": "PERFORMING", "acquisition_status": "ACQUIRED"},
        "stream after the dismissal",
    )

    landowner = validate_success(api.get_landowner(scenario.landowner_id, headers=servicing_headers))
    assert landowner["open_dispute_count"] == 0, (
        f"the landowner's open dispute count must return to zero, got {landowner['open_dispute_count']}"
    )


# ===========================================================================
# A rent increase halves the revenue share
# ===========================================================================


def test_rent_increase_amendment_halves_the_share_and_is_isolated_by_event_type(
    api, servicing_headers, manager_headers
):
    """A rent increase on an acquired stream applies half the deal's participation rate,
    splits the net exactly, and is the only row the event-type filter returns.

    PRD 3.8: "For a `RENT_INCREASE`, `effective_pass_through_cents` is zero and `share_bps_applied` is the deal's `revenue_share_bps` divided by two and truncated toward zero, on the reasoning that an escalation the acquirer already paid for warrants only half participation."
    PRD 3.8: "From there, `net_amount_cents` is `gross_amount_cents` less `effective_pass_through_cents`."
    PRD 3.8: "`landowner_share_cents` is `net_amount_cents` multiplied by `share_bps_applied`, divided by ten thousand, rounded half up to a whole number of cents."
    PRD 3.8: "`acquirer_share_cents` is `net_amount_cents` less `landowner_share_cents`, so the two shares always exhaust the net exactly."
    PRD 3.8: "The stream's `cumulative_revenue_share_landowner_cents` and `cumulative_revenue_share_acquirer_cents` then accumulate these **per-event rounded** figures."
    PRD 3.8: "The event opens at `status` `RECORDED`."
    PRD 2.3: "Amendment events under a stream may be filtered by `event_type` and by `status`."

    Design: Corner/endpoints/action_endpoint_rent_increase_amendment_halves_the_share_and_lists_by_event_type
    """
    scenario = closed_deal(api, deal={"revenue_share_bps": DEAL_REVENUE_SHARE_BPS})
    deal = validate_success(api.get_deal(scenario.deal_id, headers=manager_headers))
    assert deal["revenue_share_bps"] == DEAL_REVENUE_SHARE_BPS, (
        "the closed deal must carry the headline participation rate the split halves"
    )

    event = validate_success(
        api.create_amendment_event(
            scenario.lease_stream_id,
            {
                "event_type": "RENT_INCREASE",
                "gross_amount_cents": RENT_INCREASE_GROSS_CENTS,
                "effective_date": "2026-10-01",
            },
            headers=servicing_headers,
        ),
        201,
    )
    assert_fields(
        event,
        {
            "lease_stream_id": scenario.lease_stream_id,
            "event_type": "RENT_INCREASE",
            "gross_amount_cents": RENT_INCREASE_GROSS_CENTS,
            "effective_pass_through_cents": 0,
            "net_amount_cents": RENT_INCREASE_GROSS_CENTS,
            "share_bps_applied": RENT_INCREASE_SHARE_BPS,
            "landowner_share_cents": RENT_INCREASE_LANDOWNER_CENTS,
            "acquirer_share_cents": RENT_INCREASE_ACQUIRER_CENTS,
            "status": "RECORDED",
        },
        "rent increase amendment event",
    )
    assert event["landowner_share_cents"] + event["acquirer_share_cents"] == event["net_amount_cents"], (
        "the two shares must exhaust the net exactly"
    )

    rows, meta = validate_paginated(
        api.list_amendment_events(
            scenario.lease_stream_id,
            params={"event_type": "RENT_INCREASE", "status": "RECORDED"},
            headers=manager_headers,
        )
    )
    assert_collection_page(meta, total_count=1, item_count=len(rows), has_more=False)
    assert ids_of(rows) == [event["id"]], "the event-type filter must isolate the rent increase"

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=manager_headers))
    assert_fields(
        stream,
        {
            "cumulative_revenue_share_landowner_cents": RENT_INCREASE_LANDOWNER_CENTS,
            "cumulative_revenue_share_acquirer_cents": RENT_INCREASE_ACQUIRER_CENTS,
        },
        "stream revenue-share ledger",
    )
