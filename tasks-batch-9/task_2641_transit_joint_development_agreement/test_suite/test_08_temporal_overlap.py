"""Two occupied resources with two different interval geometries: the parcel's
closed-closed dealing dates and the facility's half-open staging instants."""

from test_helpers import (
    ApiErrorId,
    build_approved_staging_window,
    build_context,
    build_developer,
    build_negotiation_period,
    build_shared_facility,
    create_fee_proposal_payload,
    create_negotiation_period_payload,
    create_staging_window_payload,
    build_board_approved_agreement,
    get_success_data,
    make_developer_headers,
    read_shared_facility,
    validate_error,
    validate_paginated,
    validate_success,
)

OLIVE_STREET_SITE = {
    "site_code": "TJD-D-001",
    "name": "Olive Street Transit Frontage",
    "address_line": "3 Olive St",
    "parcel_area_sqft": 69000,
    "acquisition_funding_source": "MIXED",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}

POPLAR_YARD_SITE = {
    "site_code": "TJD-D-002",
    "name": "Poplar Yard Staging Site",
    "address_line": "44 Poplar Yard",
    "parcel_area_sqft": 105000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestNegotiationPeriodBoundaryDay:
    """An incumbent period ending 2026-10-15 and a rival that wants that very
    day, then the day after."""

    @staticmethod
    def _site_with_an_incumbent_period(api):
        ctx = build_context(
            stage="PROPOSAL",
            site_overrides=dict(OLIVE_STREET_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"solicitation_type": "UNSOLICITED_RESPONSE",
                                    "min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False})
        rival = build_developer(legal_name="Birch Union Development Co",
                               contact_email="dev-b@example.com",
                               prequalified=True, debarment_status="CLEAR")
        ctx["rival_developer"] = rival
        ctx["rival_proposal"] = get_success_data(api.create_proposal(
            ctx["solicitation"]["id"],
            create_fee_proposal_payload(rival["id"],
                                        proposed_purchase_price_cents=42_000_000,
                                        affordable_units=36, total_units=180,
                                        transit_ridership_uplift=1200,
                                        design_compliance_score=70,
                                        joint_use_committed=False),
            make_developer_headers(rival["id"])))
        ctx["period"] = build_negotiation_period(
            ctx["site"]["id"], ctx["proposal"]["id"],
            start_date="2026-08-15", end_date="2026-10-15")
        return ctx

    def test_sharing_the_single_boundary_day_is_a_collision(
            self, api, real_estate_officer):
        """PRD §3.5: "A candidate interval collides with an existing period on
        the same site whenever the candidate's `start_date` is on or before the
        other's `end_date` and the other's `start_date` is on or before the
        candidate's `end_date` — which means that sharing even a single boundary
        day is a collision, not an adjacency." Only live periods count: "Only
        periods whose status is `ACTIVE` or `EXTENDED` are considered". "A
        collision is reported as `ERR_NEGOTIATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/negotiation_period_closed_closed_boundary_day_collision
        """
        ctx = self._site_with_an_incumbent_period(api)
        assert ctx["period"]["status"] == "ACTIVE"
        assert ctx["period"]["end_date"] == "2026-10-15"

        response = api.create_negotiation_period(
            ctx["site"]["id"],
            create_negotiation_period_payload(ctx["rival_proposal"]["id"],
                                              "2026-10-15", "2026-12-15"),
            real_estate_officer)

        validate_error(response, ApiErrorId.NEGOTIATION_PERIOD_OVERLAP)

    def test_starting_the_day_after_the_incumbent_ends_is_accepted(
            self, api, real_estate_officer):
        """PRD §3.5: "sharing even a single boundary day is a collision, not an
        adjacency" — so a candidate opening the following day collides with
        nothing, and "A directly granted period is created with `status`
        `ACTIVE`, `extension_count` 0 and `termination_reason` null."

        Design: Difficulty/resource_temporal_overlap/negotiation_period_closed_closed_boundary_day_collision
        """
        ctx = self._site_with_an_incumbent_period(api)
        validate_error(api.create_negotiation_period(
            ctx["site"]["id"],
            create_negotiation_period_payload(ctx["rival_proposal"]["id"],
                                              "2026-10-15", "2026-12-15"),
            real_estate_officer),
            ApiErrorId.NEGOTIATION_PERIOD_OVERLAP)

        second = validate_success(api.create_negotiation_period(
            ctx["site"]["id"],
            create_negotiation_period_payload(ctx["rival_proposal"]["id"],
                                              "2026-10-16", "2026-12-15"),
            real_estate_officer), expected_status=201)

        assert second["status"] == "ACTIVE"
        assert second["start_date"] == "2026-10-16"
        periods, meta = validate_paginated(api.list_negotiation_periods(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert meta["total_count"] == 2
        site = validate_success(api.get_site(ctx["site"]["id"],
                                             real_estate_officer))
        assert site["status"] == "UNDER_AGREEMENT"


class TestStagingWindowAdjacencyAndAggregateCapacity:
    """Six bays, one window taking four and its neighbour taking two, then a
    request that genuinely overlaps both."""

    @staticmethod
    def _facility_with_two_adjacent_windows():
        ctx = build_board_approved_agreement(
            negotiation_via="award",
            site_overrides=dict(POPLAR_YARD_SITE),
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False},
            resolution_number="R-2026-120")
        ctx["facility"] = build_shared_facility(
            ctx["site"]["id"], facility_type="BUS_BAY", total_bay_capacity=6,
            maintenance_responsibility="AGENCY", cost_share_pct_developer=0)
        ctx["window_1"] = build_approved_staging_window(
            ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
            start_at="2026-09-01T08:00:00Z", end_at="2026-09-08T08:00:00Z",
            bays_occupied=4, purpose="Phase 1 laydown")
        ctx["window_2"] = build_approved_staging_window(
            ctx["agreement"]["id"], ctx["facility"]["id"], ctx["developer"]["id"],
            start_at="2026-09-08T08:00:00Z", end_at="2026-09-15T08:00:00Z",
            bays_occupied=2, purpose="Phase 2 laydown")
        ctx["facility"] = read_shared_facility(ctx["facility"]["id"])
        return ctx

    def test_a_window_starting_where_its_neighbour_ends_is_no_overlap(
            self, api, transit_operations_manager):
        """PRD §3.9: "Two windows overlap if and only if the first starts
        strictly before the second ends and the second starts strictly before
        the first ends; adjacency, where one window's `end_at` is exactly
        another's `start_at`, is never an overlap." Both windows may therefore be
        approved, and the ledger follows: "it is the `total_bay_capacity` less
        the sum of `bays_occupied` across that facility's `APPROVED` windows".

        Design: Difficulty/resource_temporal_overlap/staging_window_half_open_adjacency_allowed_aggregate_capacity_rejected
        """
        ctx = self._facility_with_two_adjacent_windows()

        assert ctx["window_1"]["status"] == "APPROVED"
        assert ctx["window_2"]["status"] == "APPROVED"
        assert ctx["facility"]["available_bay_capacity"] == 0
        windows, meta = validate_paginated(api.list_staging_windows(
            transit_operations_manager,
            params={"shared_facility_id": ctx["facility"]["id"]}))
        assert meta["total_count"] == 2

    def test_an_overlapping_request_peaks_above_the_facility_capacity(
            self, api, transit_operations_manager):
        """PRD §3.9: "Peak occupancy is then the candidate window's own
        `bays_occupied` plus the largest simultaneous total the conflicting
        windows reach", and "The check passes when peak occupancy is at most the
        facility's `total_bay_capacity`, and fails with
        `ERR_STAGING_CAPACITY_EXCEEDED`." The refusal happens at request time:
        "a window whose interval would already push the facility over its
        `total_bay_capacity` is refused at request with
        `ERR_STAGING_CAPACITY_EXCEEDED`".

        Design: Difficulty/resource_temporal_overlap/staging_window_half_open_adjacency_allowed_aggregate_capacity_rejected
        """
        ctx = self._facility_with_two_adjacent_windows()
        facility_version = ctx["facility"]["version"]

        response = api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], ctx["facility"]["id"], facility_version,
                start_at="2026-09-03T08:00:00Z", end_at="2026-09-05T08:00:00Z",
                bays_occupied=3, purpose="Crane pad overlap"),
            make_developer_headers(ctx["developer"]["id"]))

        validate_error(response, ApiErrorId.STAGING_CAPACITY_EXCEEDED)
        facility = read_shared_facility(ctx["facility"]["id"])
        assert facility["available_bay_capacity"] == 0
