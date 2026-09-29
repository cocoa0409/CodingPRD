"""Stale pins on the two pinned write paths, and parent counters that fall back.

An analyst prices a stream against the version they read, a servicing agent edits the
tenancy roster underneath them, and the valuation they submit must be refused as stale and
then accepted once they re-read; a treasury officer batching two streams into one warehouse
has the first pledge consume the facility version the second was pinned to; and a deal that
is terminated out of diligence together with a dispute that is dismissed must drive the
portfolio's active deal count and the landowner's open dispute count back down again.
"""

from test_helpers import (
    PM_CLOSER_USER_ID,
    AcquisitionStatus,
    ApiErrorId,
    CarrierCreditTier,
    DealStage,
    DisputeStatus,
    DisputeType,
    PledgeStatus,
    ServicingStatus,
    TenancyType,
    ValuationBasis,
    ValuationMethod,
    add_tenancy,
    build_asset_graph,
    build_two_closed_deals,
    create_facility,
    deal_in_diligence,
    make_acquisition_analyst_headers,
    make_platform_admin_headers,
    make_portfolio_manager_headers,
    make_servicing_agent_headers,
    make_treasury_officer_headers,
    open_dispute,
    pledge_payload,
    read_facility,
    read_lease_stream,
    terminate_payload,
    transition_dispute,
    valuation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The colocation the servicing agent bolts onto the roster while the analyst is pricing.
LATE_COLOCATION = {
    "carrier_name": "Meridian Mobile",
    "carrier_credit_tier": CarrierCreditTier.SPECULATIVE.value,
    "tenancy_type": TenancyType.COLOCATION.value,
    "monthly_rent_share_cents": 90_000,
    "term_end_date": "2034-06-30",
}

# One five-year collateral period, reused so both pledge legs differ only in their pin.
PLEDGE_START_DATE = "2026-09-01"
PLEDGE_END_DATE = "2031-08-31"


# ===========================================================================
# Pricing pinned to a stream version a roster write has already superseded
# ===========================================================================


def test_valuation_pinned_to_the_stream_version_read_before_a_colocation_was_added_is_refused(api):
    """An analyst reads the stream, a servicing agent adds a colocation, and the analyst's
    valuation pinned to the version read before that roster write is refused with nothing written.

    PRD §3.3: "Every write to the roster — adding a tenancy or reclassifying one — recomputes `tenancy_quality_score`, `anchor_carrier_name`, and `active_tenancy_count`, and advances the stream's `version`."
    PRD §2.7: "A create request carrying an older number was therefore computed against inputs that no longer hold, and it is rejected with `ERR_STALE_LEASE_STREAM_VERSION` (HTTP 412) rather than written against changed inputs."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_valuation_pinned_to_a_superseded_stream_version_rejected_then_retried
    """
    scenario = build_asset_graph(api)
    stream_id = scenario.lease_stream_id
    version_the_analyst_read = read_lease_stream(api, stream_id)["version"]

    add_tenancy(api, stream_id, headers=make_servicing_agent_headers(), **LATE_COLOCATION)

    version_after_roster_write = read_lease_stream(api, stream_id)["version"]
    assert version_after_roster_write != version_the_analyst_read, (
        "adding a carrier tenancy must advance the owning stream's version, but it stayed at "
        f"{version_the_analyst_read}"
    )

    stale = api.create_valuation(
        stream_id,
        valuation_payload(
            version_the_analyst_read, method=ValuationMethod.LUMP_SUM_PERPETUAL.value
        ),
        headers=make_acquisition_analyst_headers(),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LEASE_STREAM_VERSION.value, 412)

    rows, meta = validate_paginated(
        api.list_valuations(stream_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 0, (
        f"the rejected valuation must not have been written, but the stream carries {meta['total_count']}"
    )
    assert rows == [], f"expected no valuation rows on the stream, got {rows}"


def test_valuation_retried_on_the_refreshed_stream_version_snapshots_the_new_quality_score(api):
    """After the stale refusal the analyst re-reads the stream and resubmits, and the accepted
    valuation snapshots the score that now includes the speculative colocation.

    PRD §3.3: "Take the tenancy's base credit points from its `carrier_credit_tier`: forty points for `INVESTMENT_GRADE`, twenty-five for `CROSSOVER`, ten for `SPECULATIVE`."
    PRD §3.3: "Multiply those base points by the type multiplier for its `tenancy_type`: one exactly for `ANCHOR`, six tenths for `COLOCATION`."
    PRD §3.3: "The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred."
    PRD §3.4: "Computation begins by snapshotting the stream's live `tenancy_quality_score` into `tenancy_quality_score_snapshot`."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_valuation_pinned_to_a_superseded_stream_version_rejected_then_retried
    """
    scenario = build_asset_graph(api)
    stream_id = scenario.lease_stream_id
    version_the_analyst_read = read_lease_stream(api, stream_id)["version"]
    # One investment-grade anchor: 40 points times one, so the score is 40.
    assert scenario.lease_stream["tenancy_quality_score"] == 40

    add_tenancy(api, stream_id, headers=make_servicing_agent_headers(), **LATE_COLOCATION)

    stale = api.create_valuation(
        stream_id,
        valuation_payload(
            version_the_analyst_read, method=ValuationMethod.LUMP_SUM_PERPETUAL.value
        ),
        headers=make_acquisition_analyst_headers(),
    )
    validate_error(stale, ApiErrorId.ERR_STALE_LEASE_STREAM_VERSION.value, 412)

    refreshed = read_lease_stream(api, stream_id)
    # 40.00 for the investment-grade anchor plus 10 times six tenths for the speculative
    # colocation is 46.00, which rounds to 46.
    assert refreshed["tenancy_quality_score"] == 46, (
        f"the recomputed score is {refreshed['tenancy_quality_score']}, expected 46"
    )

    retry = api.create_valuation(
        stream_id,
        valuation_payload(
            refreshed["version"], method=ValuationMethod.LUMP_SUM_PERPETUAL.value
        ),
        headers=make_acquisition_analyst_headers(),
    )
    priced = validate_success(retry, 201)
    assert priced["tenancy_quality_score_snapshot"] == 46, (
        f"the retry snapshotted {priced['tenancy_quality_score_snapshot']}, expected the live score 46"
    )
    assert priced["tenancy_quality_score_snapshot"] == refreshed["tenancy_quality_score"]

    rows, meta = validate_paginated(
        api.list_valuations(stream_id, headers=make_acquisition_analyst_headers())
    )
    assert meta["total_count"] == 1, (
        f"only the retry may have been written, but the stream carries {meta['total_count']} valuations"
    )
    assert [row["id"] for row in rows] == [priced["id"]]


# ===========================================================================
# Pledging pinned to a facility version a sibling pledge has already consumed
# ===========================================================================


def _two_acquired_streams_and_a_warehouse(api):
    """One capital pool, two independently closed deals, and a warehouse facility over them."""
    scenario = build_two_closed_deals(
        api,
        total_capital_cents=200_000_000,
        site_codes=("NE-1042", "NE-2088"),
        landowner_names=("Hollis Farm LLC", "Delaney Orchards LLC"),
        landowner_emails=("owner@hollis.example", "owner@delaney.example"),
        recording_refs=("BK1420-PG318", "BK1421-PG042"),
    )
    scenario["facility"] = create_facility(
        api,
        scenario.portfolio_id,
        advance_rate_bps=6500,
        valuation_basis=ValuationBasis.MARK_TO_MODEL.value,
        carrier_concentration_limit_bps=10000,
    )
    return scenario


def test_second_pledge_pinned_to_the_facility_version_the_first_pledge_consumed_is_refused(api):
    """Two pledges are prepared against one freshly read facility version; the first consumes it,
    so the second — on a different acquired stream, inside the concentration limit — is refused as stale.

    PRD §2.7: "Pledge admission depends on the facility's current borrowing base, concentration headroom, and `compliance_state`, all of which move on every pledge, release, and advance."
    PRD §2.7: "A request pinned to an older facility version was decided against superseded headroom and is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_pledge_pinned_to_a_facility_version_consumed_by_a_sibling_pledge_rejected
    """
    scenario = _two_acquired_streams_and_a_warehouse(api)
    facility_id = scenario.facility_id
    version_read_once = read_facility(api, facility_id)["version"]

    first = api.create_pledge(
        facility_id,
        pledge_payload(
            scenario.deal_a.lease_stream_id,
            version_read_once,
            pledge_start_date=PLEDGE_START_DATE,
            pledge_end_date=PLEDGE_END_DATE,
        ),
        headers=make_treasury_officer_headers(),
    )
    validate_success(first, 201)

    second = api.create_pledge(
        facility_id,
        pledge_payload(
            scenario.deal_b.lease_stream_id,
            version_read_once,
            pledge_start_date=PLEDGE_START_DATE,
            pledge_end_date=PLEDGE_END_DATE,
        ),
        headers=make_treasury_officer_headers(),
    )
    validate_error(second, ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412)

    facility = read_facility(api, facility_id)
    assert facility["version"] != version_read_once, (
        "the admitted pledge must have advanced the facility's version, but it stayed at "
        f"{version_read_once}"
    )
    assert facility["pledged_stream_count"] == 1, (
        f"the refused pledge must not have been written, but pledged_stream_count is "
        f"{facility['pledged_stream_count']}"
    )
    _, meta = validate_paginated(
        api.list_collateral_pledges(
            params={"facility_id": facility_id}, headers=make_treasury_officer_headers()
        )
    )
    assert meta["total_count"] == 1, (
        f"the facility should hold exactly one pledge, but the collection reports {meta['total_count']}"
    )


def test_stale_facility_pin_is_reported_ahead_of_an_overlapping_pledge_period(api):
    """A re-pledge of the same stream over the same days is both stale and period-overlapping, and
    the refusal names the staleness rather than the overlap.

    PRD §2.8: "Because the version checks sit at positions 10 and 11, a request that is both stale and business-invalid reports staleness, not the business problem."
    PRD §2.7: "A request pinned to an older facility version was decided against superseded headroom and is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_pledge_pinned_to_a_facility_version_consumed_by_a_sibling_pledge_rejected
    """
    scenario = _two_acquired_streams_and_a_warehouse(api)
    facility_id = scenario.facility_id
    stream_a = scenario.deal_a.lease_stream_id
    version_read_once = read_facility(api, facility_id)["version"]

    admitted = api.create_pledge(
        facility_id,
        pledge_payload(
            stream_a,
            version_read_once,
            pledge_start_date=PLEDGE_START_DATE,
            pledge_end_date=PLEDGE_END_DATE,
        ),
        headers=make_treasury_officer_headers(),
    )
    validate_success(admitted, 201)

    # Same stream, identical closed period: an overlap, and pinned to the consumed version.
    both_wrong = api.create_pledge(
        facility_id,
        pledge_payload(
            stream_a,
            version_read_once,
            pledge_start_date=PLEDGE_START_DATE,
            pledge_end_date=PLEDGE_END_DATE,
        ),
        headers=make_treasury_officer_headers(),
    )
    validate_error(both_wrong, ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412)

    facility = read_facility(api, facility_id)
    assert facility["pledged_stream_count"] == 1, (
        f"the refused pledge must not have been written, but pledged_stream_count is "
        f"{facility['pledged_stream_count']}"
    )


def test_pledge_retried_on_the_refreshed_facility_version_becomes_the_second_pledged_stream(api):
    """After the stale refusal the treasury officer re-reads the facility and resends the identical
    body, which is admitted and leaves the warehouse holding two pledged streams.

    PRD §2.7: "Creating a collateral pledge under a financing facility requires `expected_facility_version` as a mandatory field of the request body."
    PRD §2.7: "Its value must equal the target `FinancingFacility`'s current `version`."
    PRD §3.9: "Creating a pledge recomputes the facility's `pledged_eligible_total_cents`, `concentration_excess_cents`, `borrowing_base_cents`, `compliance_state`, and `pledged_stream_count`."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_pledge_pinned_to_a_facility_version_consumed_by_a_sibling_pledge_rejected
    """
    scenario = _two_acquired_streams_and_a_warehouse(api)
    facility_id = scenario.facility_id
    version_read_once = read_facility(api, facility_id)["version"]

    first = api.create_pledge(
        facility_id,
        pledge_payload(
            scenario.deal_a.lease_stream_id,
            version_read_once,
            pledge_start_date=PLEDGE_START_DATE,
            pledge_end_date=PLEDGE_END_DATE,
        ),
        headers=make_treasury_officer_headers(),
    )
    pledge_a = validate_success(first, 201)

    stale_body = pledge_payload(
        scenario.deal_b.lease_stream_id,
        version_read_once,
        pledge_start_date=PLEDGE_START_DATE,
        pledge_end_date=PLEDGE_END_DATE,
    )
    validate_error(
        api.create_pledge(facility_id, stale_body, headers=make_treasury_officer_headers()),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value,
        412,
    )

    refreshed_version = read_facility(api, facility_id)["version"]
    assert refreshed_version != version_read_once

    retry_body = dict(stale_body, expected_facility_version=refreshed_version)
    pledge_b = validate_success(
        api.create_pledge(facility_id, retry_body, headers=make_treasury_officer_headers()), 201
    )
    assert pledge_b["status"] == PledgeStatus.PLEDGED.value, (
        f"the retried pledge opened at {pledge_b['status']}, expected PLEDGED"
    )
    assert pledge_b["id"] != pledge_a["id"]

    facility = read_facility(api, facility_id)
    assert facility["pledged_stream_count"] == 2, (
        f"pledged_stream_count is {facility['pledged_stream_count']}, expected 2 for the two "
        "admitted pledges and none for the refused attempt"
    )


# ===========================================================================
# Parent counters reconciled downwards by two different child lifecycles
# ===========================================================================


def _diligence_deal_with_one_open_access_dispute(api):
    """A deal at DILIGENCE with capital RESERVED, plus one OPEN access dispute on its stream."""
    scenario = deal_in_diligence(api)
    scenario["dispute"] = open_dispute(
        api,
        scenario.lease_stream_id,
        landowner_id=scenario.landowner_id,
        dispute_type=DisputeType.ACCESS.value,
        description="locked gate blocked the crew",
    )
    return scenario


def test_portfolio_active_deal_count_falls_back_when_the_diligence_deal_is_terminated(api):
    """The pool counts its one live deal, and terminating that deal out of diligence takes the
    count and the committed capital back to zero while the stream returns to the funnel.

    PRD §2.10: "A portfolio's `active_deal_count` specifically counts the deals on that portfolio whose `stage` is none of `CLOSED`, `DEAD`, `ROFR_LOST`, and `TERMINATED`."
    PRD §3.7: "In both cases the deal's capital moves to `RELEASED`, the stream returns to `PROSPECT`, and the portfolio's ledger is recomputed."
    PRD §3.1: "`committed_capital_cents` is the sum of `total_commitment_cents` across deals whose `capital_state` is `RESERVED` or `ESCROWED`."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_parent_counters_fall_back_when_a_deal_is_terminated_and_a_dispute_dismissed
    """
    scenario = _diligence_deal_with_one_open_access_dispute(api)

    before = validate_success(
        api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers())
    )
    assert before["active_deal_count"] == 1, (
        f"active_deal_count is {before['active_deal_count']} before termination, expected 1"
    )
    assert before["committed_capital_cents"] > 0, (
        "the accepted offer must have reserved capital before the deal is terminated"
    )

    terminated = validate_success(
        api.terminate_deal(
            scenario.deal_id,
            terminate_payload("landowner withdrew from talks"),
            headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
        )
    )
    assert terminated["stage"] == DealStage.TERMINATED.value, (
        f"the deal sits at {terminated['stage']}, expected TERMINATED"
    )

    after = validate_success(
        api.get_portfolio(scenario.portfolio_id, headers=make_platform_admin_headers())
    )
    assert after["active_deal_count"] == 0, (
        f"active_deal_count is {after['active_deal_count']} after termination, expected 0"
    )
    assert after["committed_capital_cents"] == 0, (
        f"committed_capital_cents is {after['committed_capital_cents']} after the release, expected 0"
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["acquisition_status"] == AcquisitionStatus.PROSPECT.value, (
        f"the stream is {stream['acquisition_status']}, expected PROSPECT after termination"
    )


def test_landowner_open_dispute_count_falls_back_when_the_access_dispute_is_dismissed(api):
    """The landowner carries one open access dispute, and dismissing it takes the count back to
    zero on a stream that never left its performing servicing condition.

    PRD §2.10: "Counters are maintained by the writes that affect them: a tower company's `site_count`, a tower site's `lease_stream_count`, a lease stream's `active_tenancy_count`, a landowner's `open_dispute_count`, a portfolio's `active_deal_count`, and a facility's `pledged_stream_count` all move as their children are created, retired, or reclassified."
    PRD §3.8: "**`DISMISS`** is likewise available from either `OPEN → DISMISSED` or `REOPENED → DISMISSED` with no precondition; it stamps `resolved_at`, and in both cases the landowner's `open_dispute_count` is recomputed, with a dismissal from `REOPENED` additionally restoring the stream `WATCHLIST → PERFORMING` when no other non-terminal dispute remains on it."
    PRD §3.2: "Recording a stream increments the site's `lease_stream_count` and initializes the stream's derived surface: `tenancy_quality_score` at zero, `anchor_carrier_name` at the literal string `UNASSIGNED`, `acquisition_status` at `PROSPECT`, `servicing_status` at `PERFORMING`, `rent_redirection_status` at `NOT_APPLICABLE`, `active_tenancy_count` at zero, and both `cumulative_revenue_share_landowner_cents` and `cumulative_revenue_share_acquirer_cents` at zero."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_parent_counters_fall_back_when_a_deal_is_terminated_and_a_dispute_dismissed
    """
    scenario = _diligence_deal_with_one_open_access_dispute(api)

    before = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert before["open_dispute_count"] == 1, (
        f"open_dispute_count is {before['open_dispute_count']} before the dismissal, expected 1"
    )

    validate_success(
        api.terminate_deal(
            scenario.deal_id,
            terminate_payload("landowner withdrew from talks"),
            headers=make_portfolio_manager_headers(PM_CLOSER_USER_ID),
        )
    )
    dismissed = transition_dispute(
        api, scenario.dispute["id"], "DISMISS", make_platform_admin_headers()
    )
    assert dismissed["status"] == DisputeStatus.DISMISSED.value, (
        f"the dispute sits at {dismissed['status']}, expected DISMISSED"
    )

    after = validate_success(
        api.get_landowner(scenario.landowner_id, headers=make_acquisition_analyst_headers())
    )
    assert after["open_dispute_count"] == 0, (
        f"open_dispute_count is {after['open_dispute_count']} after the dismissal, expected 0"
    )

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["servicing_status"] == ServicingStatus.PERFORMING.value, (
        f"the stream is {stream['servicing_status']}, expected PERFORMING since no cure was started "
        "and no dispute was upheld"
    )
