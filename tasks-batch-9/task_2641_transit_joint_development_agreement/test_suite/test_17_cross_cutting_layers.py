"""Layered checks: a version guard that the guarded write itself invalidates, and
a lifetime counter that a refused attempt must not spend."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    build_context,
    build_shared_facility,
    create_staging_window_payload,
    create_valuation_payload,
    decide_staging_window,
    extend_negotiation_period_payload,
    make_developer_headers,
    read_shared_facility,
    read_site,
    validate_error,
    validate_paginated,
    validate_success,
)

BASSWOOD_SITE = {
    "site_code": "TJD-C-056",
    "name": "Basswood Spur Parcel",
    "address_line": "56 Basswood Sp",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

COTTONWOOD_SITE = {
    "site_code": "TJD-C-057",
    "name": "Cottonwood Way Parcel",
    "address_line": "57 Cottonwood Wy",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "LOCAL_ONLY",
    "federal_interest_pct": 0,
    "transit_facility_present": False,
}

DOGWOOD_SITE = {
    "site_code": "TJD-C-058",
    "name": "Dogwood Landing Parcel",
    "address_line": "58 Dogwood Ld",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestStaleSiteVersion:
    """Pricing a parcel twice from one site read: the first write is what makes the
    second read stale."""

    def test_the_second_appraisal_must_re_read_the_site_the_first_one_moved(
            self, api, valuation_officer):
        """PRD §2.10: "Recording a fair market value determination for a site
        (`POST /jda/sites/{id}/valuations`) requires `expected_site_version` as a
        mandatory field in the request body, carrying the `version` of the
        `AgencySite` as the client last observed it. If that value does not equal the
        site's current `version`, the request is rejected with
        `ERR_STALE_SITE_VERSION` (HTTP 412). A new valuation legitimately supersedes
        the site's previously certified valuation, so a create against a freshly
        re-read site would succeed on its own; the point of the check is to force the
        valuation officer to re-read the site — and therefore its current federal
        interest basis and readiness tier — before pricing the parcel again." The
        guarded write is itself a mutation of the parent, since PRD §3.2 says "The
        site's `federal_interest_basis_cents` is set to the appraised value multiplied
        by `federal_interest_pct` and divided by 100, rounded half up, and
        `federal_interest_unencumbered_cents` is recomputed as that basis less
        whatever is already in `federal_interest_encumbered_cents`; the site's
        `version` is bumped by 1. A determination is created in `DRAFT` with
        `certified_at` null", and PRD §2.4 pins the step size: an "integer `version`
        that starts at 1 when the record is created and increments by exactly 1 on
        every mutation of that record." A parcel that has never been appraised starts
        the ledger empty, because PRD §3.1 says "A new site opens in `INVENTORIED`
        with `readiness_composite_score` and `readiness_tier` both null, all three
        federal-interest ledger fields at 0". PRD §3.2 fixes the floor: "Under
        `TRANSIT_SUPPORTIVE_BELOW_MARKET` the floor is the appraised value less the
        transit-supportive credit, but never below the federal interest floor —
        whichever of those two figures is larger wins."

        Design: Corner/cross_cutting_layers/corner_stale_site_version_rejects_second_valuation_create
        """
        ctx = build_context(stage="RELEASED",
                            site_overrides=dict(BASSWOOD_SITE))
        site_id = ctx["site"]["id"]
        site_v1 = ctx["site"]["version"]
        assert_money(ctx["site"]["federal_interest_basis_cents"], 0,
                     "federal_interest_basis_cents")

        first = api.create_valuation(
            site_id,
            create_valuation_payload(site_v1, method="INCOME_APPROACH",
                                     appraised_value_cents=48_500_000,
                                     transit_supportive_use_pct=60,
                                     affordable_units_pct=25,
                                     transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
                                     effective_date="2026-08-20"),
            valuation_officer)

        valuation_a = validate_success(first, expected_status=201)
        assert_money(valuation_a["permissible_floor_cents"], 36_375_000,
                     "permissible_floor_cents")
        after_first = read_site(site_id)
        site_v2 = after_first["version"]
        assert site_v2 == site_v1 + 1
        assert_money(after_first["federal_interest_basis_cents"], 1_212_500,
                     "federal_interest_basis_cents")
        second_body = create_valuation_payload(
            site_v1, method="SALES_COMPARISON",
            appraised_value_cents=50_000_000, transit_supportive_use_pct=60,
            affordable_units_pct=25,
            transfer_basis="TRANSIT_SUPPORTIVE_BELOW_MARKET",
            effective_date="2026-08-21")
        stale = api.create_valuation(site_id, second_body, valuation_officer)
        validate_error(stale, ApiErrorId.STALE_SITE_VERSION,
                       expected_status=412)
        recorded, meta = validate_paginated(api.list_site_valuations(
            site_id, valuation_officer))
        assert meta["total_count"] == 1
        assert recorded[0]["id"] == valuation_a["id"]
        second_body["expected_site_version"] = site_v2
        valuation_b = validate_success(api.create_valuation(
            site_id, second_body, valuation_officer), expected_status=201)
        assert valuation_b["status"] == "DRAFT"
        after_second = read_site(site_id)
        assert after_second["version"] == site_v2 + 1
        assert_money(after_second["federal_interest_basis_cents"], 1_250_000,
                     "federal_interest_basis_cents")
        assert validate_success(api.get_valuation(
            valuation_a["id"], valuation_officer))["status"] == "DRAFT"
        assert validate_success(api.get_valuation(
            valuation_b["id"], valuation_officer))["status"] == "DRAFT"


class TestStaleFacilityVersion:
    """Two different writes move the same facility, and only one of them touches
    capacity — both invalidate a held version."""

    def test_a_request_and_an_approval_each_bump_the_facility_by_exactly_one(
            self, api):
        """PRD §2.10: "Requesting a construction staging window
        (`POST /jda/staging-windows`) requires `expected_facility_version` as a
        mandatory field in the request body, carrying the `version` of the target
        `SharedFacility` as the client last observed it. If that value does not equal
        the facility's current `version`, the request is rejected with
        `ERR_STALE_FACILITY_VERSION` (HTTP 412). Another window's approval or closure
        will have changed the facility's remaining capacity, and a request placed
        against a freshly re-read facility would succeed on its own; the check forces
        the developer to re-read `available_bay_capacity` rather than book against a
        figure that no longer holds." A bare request moves the version without moving
        the capacity, since PRD §3.9 says "A successful request creates the window in
        `REQUESTED` with `capacity_released` false and `rejection_reason` null, and
        bumps the shared facility's `version` by 1 — which is exactly why the next
        requester must re-read the facility", while the decision is the write that
        spends bays: "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`, bumps the facility's
        `version` by 1, and leaves `capacity_released` false so the bays are known to
        be still out." PRD §3.9 fixes the opening figures — "A newly registered
        facility opens with `available_bay_capacity` equal to its `total_bay_capacity`
        and `version` at 1" — and PRD §2.4 fixes the step: an "integer `version` that
        starts at 1 when the record is created and increments by exactly 1 on every
        mutation of that record."

        Design: Corner/cross_cutting_layers/corner_stale_facility_version_rejects_staging_request
        """
        ctx = build_context(stage="BOARD_APPROVED", negotiation_via="direct",
                            site_overrides=dict(COTTONWOOD_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            resolution_number="R-2026-157")
        agreement_id = ctx["agreement"]["id"]
        developer_headers = make_developer_headers(ctx["developer"]["id"])
        facility = build_shared_facility(ctx["site"]["id"],
                                         total_bay_capacity=6)
        facility_v1 = validate_success(api.get_shared_facility(
            facility["id"], developer_headers))
        sf_v1 = facility_v1["version"]
        assert facility_v1["available_bay_capacity"] == 6

        window_a = validate_success(api.create_staging_window(
            create_staging_window_payload(agreement_id, facility["id"], sf_v1,
                                          start_at="2026-08-16T08:00:00Z",
                                          end_at="2026-08-18T08:00:00Z",
                                          bays_occupied=3,
                                          purpose="Crane pad"),
            developer_headers), expected_status=201)

        assert window_a["status"] == "REQUESTED"
        after_request = read_shared_facility(facility["id"])
        sf_v2 = after_request["version"]
        assert sf_v2 == sf_v1 + 1
        assert after_request["available_bay_capacity"] == 6
        second_body = create_staging_window_payload(
            agreement_id, facility["id"], sf_v1,
            start_at="2026-08-20T08:00:00Z", end_at="2026-08-22T08:00:00Z",
            bays_occupied=2, purpose="Material lay-down")
        validate_error(api.create_staging_window(second_body,
                                                 developer_headers),
                       ApiErrorId.STALE_FACILITY_VERSION, expected_status=412)
        second_body["expected_facility_version"] = sf_v2
        window_b = validate_success(api.create_staging_window(
            second_body, developer_headers), expected_status=201)
        assert window_b["status"] == "REQUESTED"
        assert decide_staging_window(window_a["id"],
                                    "APPROVE")["status"] == "APPROVED"
        after_approval = read_shared_facility(facility["id"])
        sf_v3 = after_approval["version"]
        assert after_approval["available_bay_capacity"] == 3
        assert sf_v3 == sf_v2 + 2
        third_body = create_staging_window_payload(
            agreement_id, facility["id"], sf_v2,
            start_at="2026-08-24T08:00:00Z", end_at="2026-08-26T08:00:00Z",
            bays_occupied=1, purpose="Punch list access")
        validate_error(api.create_staging_window(third_body,
                                                 developer_headers),
                       ApiErrorId.STALE_FACILITY_VERSION, expected_status=412)
        third_body["expected_facility_version"] = sf_v3
        window_c = validate_success(api.create_staging_window(
            third_body, developer_headers), expected_status=201)
        assert window_c["status"] == "REQUESTED"
        windows, meta = validate_paginated(api.list_staging_windows(
            developer_headers, params={"shared_facility_id": facility["id"]}))
        assert meta["total_count"] == 3
        assert {window["id"] for window in windows} == {
            window_a["id"], window_b["id"], window_c["id"]}


class TestExtensionCeilingIsCumulative:
    """The ceiling counts every extension the period ever took, and a refused
    attempt spends nothing."""

    def test_two_extensions_are_granted_and_the_third_is_refused_outright(
            self, api, real_estate_officer):
        """PRD §3.5: "Negotiations run long, so a period may be extended, but only
        twice. An extension supplies a `new_end_date` and is refused four ways: a
        period whose status is not `ACTIVE` or `EXTENDED` reports
        `ERR_NEGOTIATION_PERIOD_NOT_ACTIVE`; a period whose `extension_count` has
        already reached the ceiling of two reports `ERR_MAX_EXTENSIONS_REACHED`, so a
        third extension attempt on the same period always fails; a `new_end_date` that
        is not strictly later than the current `end_date` reports
        `ERR_INVALID_INTERVAL`; and an extended interval that collides closed-closed
        with a sibling `ACTIVE` or `EXTENDED` period on the same site reports
        `ERR_NEGOTIATION_PERIOD_OVERLAP`. On success `end_date` is replaced by
        `new_end_date` and `extension_count` is increased by 1. The first extension
        advances the period `ACTIVE → EXTENDED`; the second is a self-loop
        `EXTENDED → EXTENDED` that leaves the state unchanged while pushing
        `extension_count` to its ceiling of two." The period being counted arrived
        through the award of PRD §3.4: "The solicitation moves `CLOSED → AWARDED`. The
        awarded proposal moves `SUBMITTED → SELECTED` or `SHORTLISTED → SELECTED`
        (hop 1). Because that proposal became `SELECTED`, a new exclusive negotiation
        period is created over the supplied interval with `status` `ACTIVE`,
        `extension_count` 0, `start_date` from `negotiation_start_date` and `end_date`
        from `negotiation_end_date` (hop 2). Because that period became `ACTIVE`, the
        site moves `SOLICITATION_READY → UNDER_AGREEMENT` with its `version` bumped by
        1 (hop 3)".

        Design: Corner/cross_cutting_layers/corner_extension_ceiling_is_cumulative_not_windowed
        """
        ctx = build_context(stage="NEGOTIATION", negotiation_via="award",
                            site_overrides=dict(DOGWOOD_SITE),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            period_start_date="2026-08-15",
                            period_end_date="2026-09-15")
        period_id = ctx["period"]["id"]
        assert ctx["period"]["status"] == "ACTIVE"
        assert ctx["period"]["extension_count"] == 0

        first = validate_success(api.extend_negotiation_period(
            period_id, extend_negotiation_period_payload("2026-10-15"),
            real_estate_officer))

        assert first["status"] == "EXTENDED"
        assert first["extension_count"] == 1
        assert first["end_date"] == "2026-10-15"
        validate_error(api.extend_negotiation_period(
            period_id, extend_negotiation_period_payload("2026-10-01"),
            real_estate_officer), ApiErrorId.INVALID_INTERVAL,
            expected_status=422)
        second = validate_success(api.extend_negotiation_period(
            period_id, extend_negotiation_period_payload("2026-11-15"),
            real_estate_officer))
        assert second["status"] == "EXTENDED"
        assert second["extension_count"] == 2
        assert second["end_date"] == "2026-11-15"
        validate_error(api.extend_negotiation_period(
            period_id, extend_negotiation_period_payload("2026-12-15"),
            real_estate_officer), ApiErrorId.MAX_EXTENSIONS_REACHED,
            expected_status=409)
        final = validate_success(api.get_negotiation_period(
            period_id, real_estate_officer))
        assert final["status"] == "EXTENDED"
        assert final["extension_count"] == 2
        assert final["end_date"] == "2026-11-15"
        assert read_site(ctx["site"]["id"])["status"] == "UNDER_AGREEMENT"
        assert validate_success(api.get_proposal(
            ctx["proposal"]["id"], real_estate_officer))["status"] == "SELECTED"
