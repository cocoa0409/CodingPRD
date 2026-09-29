"""Lifecycle checks on the entities the lease-buyout pipeline is built from: opening a
capital pool, recording the asset graph and its rent stream, reading a stream back with
its derived tenancy surface, paging and filtering the stream register, rejecting
malformed or dangling references, materializing declared defaults, and navigating the
collateral pledge that joins an acquired stream to a warehouse facility.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    UNKNOWN_UUID,
    UNKNOWN_UUID_ALT,
    add_tenancy,
    approve_valuation,
    assert_borrowing_base,
    assert_collection_page,
    assert_common_fields,
    assert_landowner,
    assert_lease_stream,
    assert_pledge,
    assert_pledge_eligible_value,
    assert_portfolio,
    assert_tenancy,
    build_asset_graph,
    closed_deal,
    create_facility,
    create_landowner,
    create_lease_stream,
    create_pledge,
    create_tower_company,
    create_tower_site,
    create_valuation,
    ids_of,
    is_valid_uuid,
    portfolio_payload,
    read_facility,
    read_lease_stream,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(timestamp: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable instant."""
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def test_new_portfolio_opens_with_a_fully_available_capital_ledger(api, admin_headers):
    """Opening a capital pool returns 201 and every derived ledger field is initialized
    from an empty deal set rather than left unset.

    PRD 3.1: "On creation the pool's derived ledger is fully initialized: `committed_capital_cents` and `deployed_capital_cents` at zero, `available_capital_cents` equal to `total_capital_cents`, `utilization_bps` at zero, `capital_posture` at `OPEN`, and `active_deal_count` at zero."
    PRD 4: "Operations that mint a new resource return `201 Created`."
    PRD 2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation of the resource."

    Design: Corner/entities/creation_portfolio_initializes_capital_ledger_at_zero_utilization
    """
    payload = portfolio_payload(
        name="Northeast Tower Aggregation",
        program_code="NE-AGG-01",
        total_capital_cents=50_000_000,
    )

    portfolio = validate_success(api.create_portfolio(payload, headers=admin_headers), 201)

    assert_portfolio(portfolio)
    assert portfolio["name"] == "Northeast Tower Aggregation"
    assert portfolio["program_code"] == "NE-AGG-01"
    assert portfolio["total_capital_cents"] == 50_000_000
    assert portfolio["committed_capital_cents"] == 0
    assert portfolio["deployed_capital_cents"] == 0
    assert portfolio["available_capital_cents"] == 50_000_000
    assert portfolio["utilization_bps"] == 0
    assert portfolio["capital_posture"] == "OPEN"
    assert portfolio["active_deal_count"] == 0
    assert portfolio["version"] == 1


def test_reading_a_lease_stream_returns_its_rent_terms_and_live_tenancy_surface(api, analyst_headers):
    """Reading one lease stream echoes the rent terms exactly as submitted and also serves
    the tenancy-derived fields, so the read is not a partial projection of the record.

    PRD 3.2: "Recording one requires the `tower_site_id` it sits on, the `landowner_id` who receives the rent, a `current_annual_rent_cents` of at least one cent, an `escalator_type` drawn from `NONE`, `FIXED_PCT`, and `CPI_CAPPED`, and a `remaining_term_months` between 1 and 600 inclusive."
    PRD 3.2: "Recording a stream increments the site's `lease_stream_count` and initializes the stream's derived surface: `tenancy_quality_score` at zero, `anchor_carrier_name` at the literal string `UNASSIGNED`, `acquisition_status` at `PROSPECT`, `servicing_status` at `PERFORMING`, `rent_redirection_status` at `NOT_APPLICABLE`, `active_tenancy_count` at zero, and both `cumulative_revenue_share_landowner_cents` and `cumulative_revenue_share_acquirer_cents` at zero."
    PRD 3.3: "Take the tenancy's base credit points from its `carrier_credit_tier`: forty points for `INVESTMENT_GRADE`, twenty-five for `CROSSOVER`, ten for `SPECULATIVE`."
    PRD 3.3: "`anchor_carrier_name` is the `carrier_name` of the earliest-created tenancy whose `tenancy_type` is `ANCHOR` and whose `status` is `ACTIVE` or `HOLDOVER`; when no such tenancy exists, `anchor_carrier_name` is the literal string `UNASSIGNED`."
    PRD 3.3: "`active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`."

    Design: Corner/entities/retrieval_lease_stream_returns_stored_inputs_and_derived_tenancy_fields
    """
    scenario = build_asset_graph(
        api,
        lease_stream={
            "current_annual_rent_cents": 3_600_000,
            "escalator_type": "FIXED_PCT",
            "escalator_pct_bps": 300,
            "remaining_term_months": 180,
        },
        tenancies=[
            {
                "carrier_name": "Vantage Wireless",
                "carrier_credit_tier": "INVESTMENT_GRADE",
                "tenancy_type": "ANCHOR",
                "monthly_rent_share_cents": 250_000,
                "term_end_date": "2034-06-30",
            }
        ],
    )

    stream = validate_success(api.get_lease_stream(scenario.lease_stream_id, headers=analyst_headers))

    assert_lease_stream(stream)
    assert stream["tower_site_id"] == scenario.tower_site_id
    assert stream["landowner_id"] == scenario.landowner_id
    assert stream["current_annual_rent_cents"] == 3_600_000
    assert stream["escalator_type"] == "FIXED_PCT"
    assert stream["escalator_pct_bps"] == 300
    assert stream["remaining_term_months"] == 180
    assert stream["tenancy_quality_score"] == 40
    assert stream["anchor_carrier_name"] == "Vantage Wireless"
    assert stream["active_tenancy_count"] == 1
    assert stream["acquisition_status"] == "PROSPECT"
    assert stream["servicing_status"] == "PERFORMING"
    assert stream["rent_redirection_status"] == "NOT_APPLICABLE"
    assert stream["cumulative_revenue_share_landowner_cents"] == 0
    assert stream["cumulative_revenue_share_acquirer_cents"] == 0


def test_stream_register_filters_on_acquisition_status_before_it_pages(api, analyst_headers):
    """The stream register applies the acquisition-status filter first and reports the
    filtered row count in the envelope meta, so paging walks the filtered set in
    creation order.

    PRD 2.3: "The `meta` object of a collection response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` counts every row matching the filters before the page window is applied and `has_more` is true when rows remain beyond the current window."
    PRD 2.3: "Lease streams may be filtered by `tower_site_id`, by `landowner_id`, by `acquisition_status`, and by `servicing_status`."
    PRD 2.3: "Unless a specific narrative says otherwise, every collection is ordered by `created_at` ascending."

    Design: Corner/entities/listing_lease_streams_filtered_by_acquisition_status_with_pagination
    """
    company = create_tower_company(api)
    owner = create_landowner(api)
    stream_ids = []
    for site_code in ("NE-7001", "NE-7002", "NE-7003"):
        site = create_tower_site(api, company["id"], site_code=site_code)
        stream_ids.append(create_lease_stream(api, site["id"], owner["id"])["id"])

    first_page, first_meta = validate_paginated(
        api.list_lease_streams(params={"acquisition_status": "PROSPECT", "limit": 2, "offset": 0}, headers=analyst_headers)
    )
    second_page, second_meta = validate_paginated(
        api.list_lease_streams(params={"acquisition_status": "PROSPECT", "limit": 2, "offset": 2}, headers=analyst_headers)
    )
    acquired_page, acquired_meta = validate_paginated(
        api.list_lease_streams(params={"acquisition_status": "ACQUIRED"}, headers=analyst_headers)
    )

    assert_collection_page(first_meta, total_count=3, item_count=len(first_page), has_more=True)
    assert len(first_page) == 2
    assert ids_of(first_page) == stream_ids[:2]

    assert_collection_page(second_meta, total_count=3, item_count=len(second_page), has_more=False)
    assert len(second_page) == 1
    assert ids_of(second_page) == stream_ids[2:]

    assert acquired_page == []
    assert acquired_meta["total_count"] == 0
    assert acquired_meta["has_more"] is False

    for item in first_page + second_page:
        assert_common_fields(item, label="LeaseStream")


def test_unknown_stream_id_in_the_path_is_an_existence_failure(api, analyst_headers):
    """A well-formed but unknown identifier in the path is refused as a missing lease
    stream rather than as a malformed request, and the stream that does exist is left
    untouched.

    PRD 2.8: "**Path resource existence** — every identifier in the URL path resolves to a live resource, checked outermost segment first; otherwise the matching not-found error (404)."
    PRD 2.9: "The not-found vocabulary is per entity: `ERR_PORTFOLIO_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_TOWER_COMPANY_NOT_FOUND`, `ERR_TOWER_SITE_NOT_FOUND`, `ERR_LANDOWNER_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, `ERR_TENANCY_NOT_FOUND`, `ERR_VALUATION_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_TITLE_REPORT_NOT_FOUND`, `ERR_ROFR_NOTICE_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_PLEDGE_NOT_FOUND`, and `ERR_AMENDMENT_NOT_FOUND`."

    Design: Corner/entities/not_found_lease_stream_unknown_uuid_returns_404
    """
    scenario = build_asset_graph(api, tenancies=())

    response = api.get_lease_stream(UNKNOWN_UUID, headers=analyst_headers)

    validate_error(response, ApiErrorId.ERR_LEASE_STREAM_NOT_FOUND.value)

    survivor = read_lease_stream(api, scenario.lease_stream_id)
    assert survivor["version"] == 1


def test_recording_a_stream_without_its_annual_rent_is_rejected(api, analyst_headers):
    """A lease stream whose annual rent is omitted is a shape violation caught before any
    business rule runs, and no stream row survives the attempt.

    PRD 3.2: "Recording one requires the `tower_site_id` it sits on, the `landowner_id` who receives the rent, a `current_annual_rent_cents` of at least one cent, an `escalator_type` drawn from `NONE`, `FIXED_PCT`, and `CPI_CAPPED`, and a `remaining_term_months` between 1 and 600 inclusive."
    PRD 2.8: "**Request shape** — required fields are present, types and enumerations are legal, minimum and maximum bounds hold, and dates and timestamps parse; otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/required_fields_missing_current_annual_rent_rejected
    """
    company = create_tower_company(api)
    site = create_tower_site(api, company["id"])
    owner = create_landowner(api)

    response = api.create_lease_stream(
        {
            "tower_site_id": site["id"],
            "landowner_id": owner["id"],
            "escalator_type": "FIXED_PCT",
            "escalator_pct_bps": 300,
            "remaining_term_months": 180,
        },
        headers=analyst_headers,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    site_after = validate_success(api.get_tower_site(site["id"], headers=analyst_headers))
    assert site_after["lease_stream_count"] == 0

    _, meta = validate_paginated(api.list_lease_streams(headers=analyst_headers))
    assert meta["total_count"] == 0


def test_omitted_optional_inputs_are_stored_at_their_declared_defaults(
    api, admin_headers, analyst_headers, treasury_headers
):
    """Optional inputs left out of a create body are materialized at the values the
    contract declares rather than stored empty, all the way from the tower company's
    refusal settings to the facility's concentration limit.

    PRD 3.2: "A **TowerCompany** is registered with its `legal_name` and a `notice_email` to which refusal notices are addressed, plus two optional refusal settings: `rofr_required`, a boolean that defaults to false, and `rofr_window_days`, which defaults to 30 and must fall between 1 and 90 days inclusive."
    PRD 3.2: "An optional `escalator_pct_bps` defaults to 0 and must fall between 0 and 1000 basis points inclusive."
    PRD 3.4: "An `escalator_type` of `NONE` gives a growth rate of zero."
    PRD 3.5: "Two optional terms round out the paperwork: `easement_term_years`, defaulting to 0 and bounded between 0 and 99 inclusive, which is what a long-term easement is measured in; and `revenue_share_bps`, defaulting to 2500 and bounded between 0 and 5000 inclusive, which is the landowner's participation in future upside after closing."
    PRD 3.5: "A new deal starts at `stage` `ORIGINATION` and `capital_state` `UNCOMMITTED`, increments its portfolio's `active_deal_count`, and takes its initial `rofr_state` from the tower company standing over the stream's site: `PENDING` when that company's `rofr_required` is true, and `NOT_REQUIRED` when it is false."
    PRD 3.9: "A `TreasuryOfficer` opens a **FinancingFacility** against a portfolio by supplying the `portfolio_id`, a `facility_name`, an `advance_rate_bps` between 1 and 9500 basis points inclusive, a `valuation_basis` of either `MARK_TO_MODEL` or `COST_BASIS`, and optionally a `carrier_concentration_limit_bps` that defaults to 5000 and must fall between 1 and 10000 inclusive."
    PRD 3.9: "A fresh facility carries `pledged_eligible_total_cents`, `concentration_excess_cents`, `borrowing_base_cents`, `advances_outstanding_cents`, and `pledged_stream_count` at zero, and `compliance_state` at `COMPLIANT`."

    Design: Corner/entities/defaults_omitted_optional_inputs_apply_declared_default_values
    """
    portfolio = validate_success(
        api.create_portfolio(portfolio_payload(total_capital_cents=50_000_000), headers=admin_headers), 201
    )

    company = validate_success(
        api.create_tower_company(
            {"legal_name": "Summit Towers LLC", "notice_email": "rofr@summit.example"}, headers=admin_headers
        ),
        201,
    )
    assert company["rofr_required"] is False
    assert company["rofr_window_days"] == 30

    site = create_tower_site(api, company["id"])
    owner = create_landowner(api)

    stream = validate_success(
        api.create_lease_stream(
            {
                "tower_site_id": site["id"],
                "landowner_id": owner["id"],
                "current_annual_rent_cents": 3_600_000,
                "escalator_type": "NONE",
                "remaining_term_months": 180,
            },
            headers=analyst_headers,
        ),
        201,
    )
    assert stream["escalator_pct_bps"] == 0

    add_tenancy(api, stream["id"])
    valuation = create_valuation(api, stream["id"])
    assert valuation["growth_rate_bps"] == 0
    approve_valuation(api, valuation["id"])

    deal = validate_success(
        api.create_deal(
            {
                "portfolio_id": portfolio["id"],
                "lease_stream_id": stream["id"],
                "valuation_id": valuation["id"],
                "easement_type": "PERPETUAL_EASEMENT",
            },
            headers=analyst_headers,
        ),
        201,
    )
    assert deal["revenue_share_bps"] == 2500
    assert deal["easement_term_years"] == 0
    assert deal["rofr_state"] == "NOT_REQUIRED"

    facility = validate_success(
        api.create_financing_facility(
            {
                "portfolio_id": portfolio["id"],
                "facility_name": "Warehouse A",
                "advance_rate_bps": 6500,
                "valuation_basis": "MARK_TO_MODEL",
            },
            headers=treasury_headers,
        ),
        201,
    )
    assert facility["carrier_concentration_limit_bps"] == 5000
    assert facility["compliance_state"] == "COMPLIANT"
    assert facility["pledged_eligible_total_cents"] == 0
    assert facility["concentration_excess_cents"] == 0
    assert facility["borrowing_base_cents"] == 0
    assert facility["advances_outstanding_cents"] == 0
    assert facility["pledged_stream_count"] == 0


def test_adding_a_colocation_re_derives_the_stream_quality_surface(api, analyst_headers, servicing_headers):
    """Each tenancy write re-derives the stream's quality score, anchor identity and
    active count instead of freezing them at creation, and a colocation's fractional
    contribution is carried into the stream score at two decimals.

    PRD 3.3: "Take the tenancy's base credit points from its `carrier_credit_tier`: forty points for `INVESTMENT_GRADE`, twenty-five for `CROSSOVER`, ten for `SPECULATIVE`."
    PRD 3.3: "Multiply those base points by the type multiplier for its `tenancy_type`: one exactly for `ANCHOR`, six tenths for `COLOCATION`."
    PRD 3.3: "Store on the tenancy, as its `quality_points`, that same figure rounded half up to a whole number."
    PRD 3.3: "The stream's `tenancy_quality_score` is then the sum of the **two-decimal figures produced at step five** — not the sum of the whole-number `quality_points` values written onto the tenancies — with that sum rounded half up to a whole number and finally clamped into the inclusive range from zero to one hundred."
    PRD 3.3: "A new tenancy begins life with `status` `ACTIVE`."
    PRD 3.3: "On a stream that has not been acquired, a new tenancy's `redirection_notice_status` is `NOT_APPLICABLE`."
    PRD 3.3: "`anchor_carrier_name` is the `carrier_name` of the earliest-created tenancy whose `tenancy_type` is `ANCHOR` and whose `status` is `ACTIVE` or `HOLDOVER`; when no such tenancy exists, `anchor_carrier_name` is the literal string `UNASSIGNED`."
    PRD 3.3: "`active_tenancy_count` counts the tenancies in `ACTIVE` or `HOLDOVER`."

    Design: Corner/entities/computed_fields_tenancy_mix_drives_score_anchor_and_active_count
    """
    scenario = build_asset_graph(api, tenancies=())

    anchor = validate_success(
        api.create_tenancy(
            scenario.lease_stream_id,
            {
                "carrier_name": "Vantage Wireless",
                "carrier_credit_tier": "INVESTMENT_GRADE",
                "tenancy_type": "ANCHOR",
                "monthly_rent_share_cents": 250_000,
                "term_end_date": "2034-06-30",
            },
            headers=analyst_headers,
        ),
        201,
    )
    colocation = validate_success(
        api.create_tenancy(
            scenario.lease_stream_id,
            {
                "carrier_name": "Bluewave Mobile",
                "carrier_credit_tier": "SPECULATIVE",
                "tenancy_type": "COLOCATION",
                "monthly_rent_share_cents": 80_000,
                "term_end_date": "2034-06-30",
            },
            headers=servicing_headers,
        ),
        201,
    )

    assert_tenancy(anchor)
    assert_tenancy(colocation)
    assert anchor["quality_points"] == 40
    assert anchor["status"] == "ACTIVE"
    assert anchor["redirection_notice_status"] == "NOT_APPLICABLE"
    assert colocation["quality_points"] == 6
    assert colocation["status"] == "ACTIVE"
    assert colocation["redirection_notice_status"] == "NOT_APPLICABLE"

    stream = read_lease_stream(api, scenario.lease_stream_id)
    assert stream["tenancy_quality_score"] == 46
    assert stream["anchor_carrier_name"] == "Vantage Wireless"
    assert stream["active_tenancy_count"] == 2


def test_landowner_identity_and_timestamps_come_from_the_logical_clock(api, analyst_headers):
    """A landowner's id, timestamps and version are server-assigned, its stamps read the
    logical clock rather than wall time, and correcting the contact address counts as a
    mutation that advances both the version and the update stamp.

    PRD 2.4: "`id` — a server-minted UUID. It carries no type prefix and clients never supply it."
    PRD 2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation."
    PRD 2.4: "`updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource."
    PRD 2.4: "`version` — an integer that starts at 1 on creation and increments by one on every mutation of the resource."
    PRD 2.6: "Offer expiries, refusal windows, mortgagee-consent validity, cure deadlines, and every stored timestamp such as `sent_at`, `served_at`, `ordered_at`, `consent_requested_at`, `decided_at`, `responded_at`, `resolved_at`, `approved_at`, and `recorded_at` all derive from this clock."
    PRD 3.2: "Its `outreach_status` is initialized to `NEW` and thereafter tracks the progression of offers and deals through `CONTACTED`, `NEGOTIATING`, `UNDER_CONTRACT`, and `CLOSED`."
    PRD 3.2: "A `PlatformAdmin` or `AcquisitionAnalyst` may patch a landowner to correct `contact_email`, and may pass a `suppress_outreach` boolean."

    Design: Corner/entities/system_fields_id_timestamps_and_version_generated_from_logical_clock
    """
    set_clock(api, "2026-09-15T12:00:00Z")

    created = validate_success(
        api.create_landowner(
            {"legal_name": "Hollis Farm LLC", "entity_type": "LLC", "contact_email": "owner@hollis.example"},
            headers=analyst_headers,
        ),
        201,
    )

    assert_landowner(created)
    assert is_valid_uuid(created["id"])
    assert _instant(created["created_at"]) == _instant("2026-09-15T12:00:00Z")
    assert _instant(created["updated_at"]) == _instant(created["created_at"])
    assert created["version"] == 1
    assert created["outreach_status"] == "NEW"
    assert created["open_dispute_count"] == 0

    set_clock(api, "2026-09-16T12:00:00Z")
    patched = validate_success(
        api.update_landowner(created["id"], {"contact_email": "estate@hollis.example"}, headers=analyst_headers)
    )

    assert patched["id"] == created["id"]
    assert patched["contact_email"] == "estate@hollis.example"
    assert patched["version"] == 2
    assert _instant(patched["created_at"]) == _instant("2026-09-15T12:00:00Z")
    assert _instant(patched["updated_at"]) == _instant("2026-09-16T12:00:00Z")
    assert patched["outreach_status"] == "NEW"


def test_illegal_enum_members_and_out_of_range_rates_are_refused(api, analyst_headers):
    """Enumeration membership and numeric bounds are both enforced at the shape layer, so
    a misspelled escalator, an escalator rate above its ceiling and an unknown structure
    type are each refused and nothing is written.

    PRD 2.8: "**Request shape** — required fields are present, types and enumerations are legal, minimum and maximum bounds hold, and dates and timestamps parse; otherwise `ERR_INVALID_REQUEST` (400)."
    PRD 3.2: "Recording one requires the `tower_site_id` it sits on, the `landowner_id` who receives the rent, a `current_annual_rent_cents` of at least one cent, an `escalator_type` drawn from `NONE`, `FIXED_PCT`, and `CPI_CAPPED`, and a `remaining_term_months` between 1 and 600 inclusive."
    PRD 3.2: "An optional `escalator_pct_bps` defaults to 0 and must fall between 0 and 1000 basis points inclusive."
    PRD 3.2: "A **TowerSite** hangs off a tower company by way of a `tower_company_id` and describes the physical location: a `site_code` unique across all sites, a `state_code`, a `ground_area_sqft` footprint of at least one square foot, and a `structure_type` drawn from `MONOPOLE`, `LATTICE`, `GUYED`, and `ROOFTOP`."
    PRD 3.2: "Registering a site increments its tower company's `site_count`."

    Design: Corner/entities/type_constraints_invalid_escalator_enum_and_out_of_range_bps_rejected
    """
    company = create_tower_company(api)
    site = create_tower_site(api, company["id"], site_code="NE-1042")
    owner = create_landowner(api)

    bad_enum = api.create_lease_stream(
        {
            "tower_site_id": site["id"],
            "landowner_id": owner["id"],
            "current_annual_rent_cents": 3_600_000,
            "escalator_type": "FIXED_PERCENT",
            "remaining_term_months": 180,
        },
        headers=analyst_headers,
    )
    validate_error(bad_enum, ApiErrorId.ERR_INVALID_REQUEST.value)

    bad_range = api.create_lease_stream(
        {
            "tower_site_id": site["id"],
            "landowner_id": owner["id"],
            "current_annual_rent_cents": 3_600_000,
            "escalator_type": "FIXED_PCT",
            "escalator_pct_bps": 1001,
            "remaining_term_months": 180,
        },
        headers=analyst_headers,
    )
    validate_error(bad_range, ApiErrorId.ERR_INVALID_REQUEST.value)

    bad_structure = api.create_tower_site(
        {
            "tower_company_id": company["id"],
            "site_code": "NE-1043",
            "state_code": "NY",
            "ground_area_sqft": 2500,
            "structure_type": "TREE",
        },
        headers=analyst_headers,
    )
    validate_error(bad_structure, ApiErrorId.ERR_INVALID_REQUEST.value)

    _, meta = validate_paginated(api.list_lease_streams(headers=analyst_headers))
    assert meta["total_count"] == 0

    _, site_meta = validate_paginated(api.list_tower_sites(headers=analyst_headers))
    assert site_meta["total_count"] == 1


def test_recording_a_stream_on_an_unknown_tower_site_names_the_missing_site(api, analyst_headers):
    """A body reference that does not resolve is refused as a missing parent keyed to the
    entity actually named, so an unknown tower site reports the tower site and not the
    landowner that does resolve.

    PRD 2.8: "**Body foreign-key existence** — every reference carried in the request body resolves; otherwise the matching not-found error (404)."
    PRD 2.9: "A pledge creation naming a `lease_stream_id` that does not resolve yields `ERR_LEASE_STREAM_NOT_FOUND`; a deal creation naming an unresolvable `portfolio_id`, `lease_stream_id`, or `valuation_id` yields `ERR_PORTFOLIO_NOT_FOUND`, `ERR_LEASE_STREAM_NOT_FOUND`, or `ERR_VALUATION_NOT_FOUND` respectively; a facility creation naming an unresolvable `portfolio_id` yields `ERR_PORTFOLIO_NOT_FOUND`; a tower site naming an unresolvable `tower_company_id` yields `ERR_TOWER_COMPANY_NOT_FOUND`; and a lease stream naming an unresolvable `tower_site_id` or `landowner_id` yields `ERR_TOWER_SITE_NOT_FOUND` or `ERR_LANDOWNER_NOT_FOUND`."

    Design: Corner/entities/parent_relationships_lease_stream_with_unknown_tower_site_rejected
    """
    owner = create_landowner(api)

    response = api.create_lease_stream(
        {
            "tower_site_id": UNKNOWN_UUID_ALT,
            "landowner_id": owner["id"],
            "current_annual_rent_cents": 3_600_000,
            "escalator_type": "FIXED_PCT",
            "escalator_pct_bps": 300,
            "remaining_term_months": 180,
        },
        headers=analyst_headers,
    )

    validate_error(response, ApiErrorId.ERR_TOWER_SITE_NOT_FOUND.value)

    _, meta = validate_paginated(api.list_lease_streams(headers=analyst_headers))
    assert meta["total_count"] == 0


def test_a_pledged_stream_is_reachable_from_both_its_facility_and_its_stream(api, treasury_headers, manager_headers):
    """One acquired stream pledged into two facilities over non-adjacent periods is
    queryable from either side of the association, and each pledge values itself off the
    stream's approved model value at a performing haircut.

    PRD 2.3: "Collateral pledges may be filtered by `facility_id`, by `lease_stream_id`, and by `status`."
    PRD 2.11: "A candidate pledge starting on the exact day an existing pledge ends conflicts with it; a candidate starting the following day does not."
    PRD 3.9: "`valuation_basis_snapshot` copies the facility's `valuation_basis` at the moment of pledging, so later edits to the facility do not revalue existing collateral."
    PRD 3.9: "`basis_value_cents` follows that snapshot: under `MARK_TO_MODEL` it is the stream's `APPROVED` valuation's `value_cents`; under `COST_BASIS` it is the closed deal's `total_commitment_cents` for that stream."
    PRD 3.9: "`haircut_bps` is read from the stream's `servicing_status` — zero basis points while `PERFORMING`, 3000 while on `WATCHLIST`, 5000 while `DELINQUENT`, and the full 10000 while `IMPAIRED`."
    PRD 2.10: "Counters are maintained by the writes that affect them: a tower company's `site_count`, a tower site's `lease_stream_count`, a lease stream's `active_tenancy_count`, a landowner's `open_dispute_count`, a portfolio's `active_deal_count`, and a facility's `pledged_stream_count` all move as their children are created, retired, or reclassified."

    Design: Corner/entities/graph_collateral_pledge_junction_is_navigable_from_both_facility_and_stream
    """
    scenario = closed_deal(api)
    model_value_cents = scenario["valuation"]["value_cents"]

    facility_a = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse A",
        valuation_basis="MARK_TO_MODEL",
        carrier_concentration_limit_bps=10000,
    )
    facility_b = create_facility(
        api,
        scenario.portfolio_id,
        facility_name="Warehouse B",
        valuation_basis="MARK_TO_MODEL",
        carrier_concentration_limit_bps=10000,
    )

    pledge_a = create_pledge(
        api,
        facility_a["id"],
        scenario.lease_stream_id,
        pledge_start_date="2026-08-01",
        pledge_end_date="2026-12-31",
    )
    pledge_b = create_pledge(
        api,
        facility_b["id"],
        scenario.lease_stream_id,
        pledge_start_date="2027-01-01",
        pledge_end_date="2027-06-30",
    )

    by_stream, stream_meta = validate_paginated(
        api.list_collateral_pledges(params={"lease_stream_id": scenario.lease_stream_id}, headers=treasury_headers)
    )
    assert stream_meta["total_count"] == 2
    assert sorted(ids_of(by_stream)) == sorted([pledge_a["id"], pledge_b["id"]])

    by_facility, facility_meta = validate_paginated(
        api.list_collateral_pledges(params={"facility_id": facility_a["id"], "status": "PLEDGED"}, headers=treasury_headers)
    )
    assert facility_meta["total_count"] == 1
    assert ids_of(by_facility) == [pledge_a["id"]]

    read_b = validate_success(api.get_collateral_pledge(pledge_b["id"], headers=manager_headers))

    for pledge, facility in ((pledge_a, facility_a), (read_b, facility_b)):
        assert_pledge(pledge)
        assert pledge["facility_id"] == facility["id"]
        assert pledge["lease_stream_id"] == scenario.lease_stream_id
        assert pledge["status"] == "PLEDGED"
        assert pledge["valuation_basis_snapshot"] == "MARK_TO_MODEL"
        assert pledge["basis_value_cents"] == model_value_cents
        assert pledge["haircut_bps"] == 0
        assert pledge["eligible_value_cents"] == model_value_cents
        assert_pledge_eligible_value(pledge)

    assert read_b["pledge_start_date"] == "2027-01-01"
    assert read_b["pledge_end_date"] == "2027-06-30"

    for facility_id in (facility_a["id"], facility_b["id"]):
        facility = read_facility(api, facility_id)
        assert facility["pledged_stream_count"] == 1
        assert facility["pledged_eligible_total_cents"] == model_value_cents
        assert facility["advance_rate_bps"] == TEST_DEFAULTS["ADVANCE_RATE_BPS"]
        assert_borrowing_base(facility)
