"""Route-level checks: which parent a nested collection hangs off, what a
single-resource read replays, and which filters a collection honours."""

from test_helpers import (
    ApiErrorId,
    assert_money,
    build_approved_staging_window,
    build_board_approved_with_shared_facility,
    build_context,
    build_disposition_request,
    build_maintenance_charge,
    build_shared_facility,
    build_valuation,
    create_staging_window_payload,
    maintenance_line_item,
    make_developer_headers,
    read_shared_facility,
    staging_decision_payload,
    validate_error,
    validate_paginated,
    validate_success,
    UNKNOWN_UUIDS,
)

WALNUT_SITE = {
    "site_code": "TJD-C-040",
    "name": "Walnut Terminal Parcel",
    "address_line": "40 Walnut Ter",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


def _site(site_code: str, name: str, address_line: str) -> dict:
    site = dict(WALNUT_SITE)
    site.update(site_code=site_code, name=name, address_line=address_line)
    return site


class TestSiteChildCollections:
    """Each of a parcel's four child collections, and the single read of the same
    record."""

    def test_every_child_collection_returns_its_own_parents_child(
            self, api, real_estate_officer, valuation_officer,
            transit_operations_manager):
        """PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
        `total_count` (the number of records matching the filters before pagination
        is applied) and `has_more` (true when records remain beyond the current
        page)." The parents are the ones the PRD declares: PRD §3.2 says a
        determination's "`site_id` comes from the path rather than the body", PRD §3.9
        says a shared facility's "`site_id` comes from the path", and a freshly
        registered facility is untouched — "A newly registered facility opens with
        `available_bay_capacity` equal to its `total_bay_capacity` and `version` at
        1." PRD §3.2 adds that "A determination is created in `DRAFT` with
        `certified_at` null".

        Design: Corner/endpoints/corner_site_child_collections_and_single_reads
        """
        ctx = build_context(stage="SOLICITATION_ISSUED",
                            site_overrides=_site("TJD-C-040",
                                                 "Walnut Terminal Parcel",
                                                 "40 Walnut Ter"))
        site_id = ctx["site"]["id"]
        valuation = build_valuation(site_id)
        facility = build_shared_facility(site_id, total_bay_capacity=6)

        assessments, assessment_meta = validate_paginated(
            api.list_site_assessments(site_id, real_estate_officer))
        assert assessment_meta["total_count"] == 1
        assert assessment_meta["has_more"] is False
        assert assessments[0]["id"] == ctx["assessment"]["id"]
        assert validate_success(api.get_assessment(
            ctx["assessment"]["id"], real_estate_officer))["id"] == \
            ctx["assessment"]["id"]

        solicitations, solicitation_meta = validate_paginated(
            api.list_site_solicitations(site_id, real_estate_officer))
        assert solicitation_meta["total_count"] == 1
        assert solicitation_meta["has_more"] is False
        assert solicitations[0]["id"] == ctx["solicitation"]["id"]
        assert validate_success(api.get_solicitation(
            ctx["solicitation"]["id"], real_estate_officer))["id"] == \
            ctx["solicitation"]["id"]

        valuations, valuation_meta = validate_paginated(
            api.list_site_valuations(site_id, valuation_officer))
        assert valuation_meta["total_count"] == 1
        assert valuation_meta["has_more"] is False
        assert valuations[0]["id"] == valuation["id"]
        read_valuation = validate_success(api.get_valuation(valuation["id"],
                                                            valuation_officer))
        assert read_valuation["id"] == valuation["id"]
        assert read_valuation["status"] == "DRAFT"

        facilities, facility_meta = validate_paginated(
            api.list_site_shared_facilities(site_id, transit_operations_manager))
        assert facility_meta["total_count"] == 1
        assert facility_meta["has_more"] is False
        assert facilities[0]["id"] == facility["id"]
        read_facility = validate_success(api.get_shared_facility(
            facility["id"], transit_operations_manager))
        assert read_facility["id"] == facility["id"]
        assert read_facility["available_bay_capacity"] == 6

        developer = validate_success(api.get_developer(ctx["developer"]["id"],
                                                      real_estate_officer))
        assert developer["id"] == ctx["developer"]["id"]


class TestAgreementReadReplaysStoredMoney:
    """The three computed money fields come back off the record, not out of a
    fresh computation with different inputs."""

    def test_the_reread_agreement_carries_the_figures_drafting_stored(
            self, api, real_estate_officer):
        """PRD §3.6 works the drafting arithmetic: "a `GROUND_LEASE` with 2,000,000
        cents of base rent, 12,000,000 cents of projected gross revenue and a
        five-hundredths revenue share yields a participation of 600,000 and a subtotal
        of 2,600,000, which falls in the eight-hundredths tier; with 50 of 200 units
        committed as affordable the three-hundredths bonus applies, giving eleven
        hundredths; the capital credit is 286,000 and the annual revenue to the agency
        is 2,314,000." PRD §3.6 capitalises that: "Continuing the worked case,
        2,314,000 capitalised over twenty years is 46,280,000 cents". The federal
        dimension opens where PRD §3.6 puts it — "Its federal dimension is initialised
        from the parcel: `federal_approval_status` starts at `NOT_REQUIRED` when the
        site's `federal_interest_pct` is exactly 0, and at `NOT_SUBMITTED`
        otherwise." PRD §3.5 fixes the period: "A directly granted period is created
        with `status` `ACTIVE`, `extension_count` 0 and `termination_reason` null. If
        the site was `SOLICITATION_READY` it moves `SOLICITATION_READY →
        UNDER_AGREEMENT` with its `version` bumped by 1".

        Design: Corner/endpoints/corner_agreement_computed_money_fields_survive_reread
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="direct",
                            site_overrides=_site("TJD-C-041",
                                                 "Walnut Yard Parcel",
                                                 "41 Walnut Yd"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        assert ctx["period"]["status"] == "ACTIVE"
        assert ctx["period"]["extension_count"] == 0
        assert ctx["site"]["status"] == "UNDER_AGREEMENT"
        assert_money(ctx["agreement"]["capital_credit_cents"], 286_000,
                     "capital_credit_cents")
        assert_money(ctx["agreement"]["annual_revenue_to_agency_cents"],
                     2_314_000, "annual_revenue_to_agency_cents")
        assert_money(ctx["agreement"]["consideration_value_cents"], 46_280_000,
                     "consideration_value_cents")

        agreement = validate_success(api.get_agreement(ctx["agreement"]["id"],
                                                       real_estate_officer))

        assert_money(agreement["capital_credit_cents"], 286_000,
                     "capital_credit_cents")
        assert_money(agreement["annual_revenue_to_agency_cents"], 2_314_000,
                     "annual_revenue_to_agency_cents")
        assert_money(agreement["consideration_value_cents"], 46_280_000,
                     "consideration_value_cents")
        assert agreement["federal_approval_status"] == "NOT_SUBMITTED"
        agreements, meta = validate_paginated(api.list_agreements(
            real_estate_officer,
            params={"negotiation_status": "DRAFTING", "limit": 10, "offset": 0}))
        assert meta["total_count"] == 1
        assert agreements[0]["id"] == ctx["agreement"]["id"]


class TestStagingWindowBodyParents:
    """The staging request names two parents in the body, and both must resolve
    before anything is written."""

    def test_each_bogus_parent_is_named_in_turn_and_the_valid_pair_links_both(
            self, api, real_estate_officer, transit_operations_manager):
        """PRD §2.9: "Foreign keys supplied in a request body are resolved after every
        path segment has been resolved, and among themselves in body-field declaration
        order: `site_id`, then `developer_id`, then `proposal_id`, then `valuation_id`,
        then `jda_id`, then `shared_facility_id`. An unknown body reference reports
        `ERR_SITE_NOT_FOUND`, `ERR_DEVELOPER_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`,
        `ERR_VALUATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND` or
        `ERR_SHARED_FACILITY_NOT_FOUND` respectively." PRD §3.9 names the two the
        request carries: a developer "requests a **staging window**, naming the
        `jda_id` of the agreement whose construction needs the space and the
        `shared_facility_id` of the facility whose units it will occupy". A valid
        request stops at `REQUESTED` — "A successful request creates the window in
        `REQUESTED` with `capacity_released` false and `rejection_reason` null" — and
        reserves nothing, because PRD §3.9 gives capacity away only on approval:
        "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`".

        Design: Corner/endpoints/corner_staging_window_link_requires_both_declared_parents
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="direct",
                            period_start_date="2026-08-15",
                            period_end_date="2027-01-15",
                            site_overrides=_site("TJD-C-042",
                                                 "Walnut Depot Parcel",
                                                 "42 Walnut Dp"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        facility = build_shared_facility(ctx["site"]["id"], total_bay_capacity=6)
        developer_headers = make_developer_headers(ctx["developer"]["id"])
        assert facility["available_bay_capacity"] == 6

        unknown_agreement = api.create_staging_window(
            create_staging_window_payload(
                UNKNOWN_UUIDS["AGREEMENT"], facility["id"], facility["version"],
                start_at="2026-08-16T08:00:00Z", end_at="2026-08-20T08:00:00Z",
                bays_occupied=2, purpose="Material laydown"),
            developer_headers)

        validate_error(unknown_agreement, ApiErrorId.AGREEMENT_NOT_FOUND)

        unknown_facility = api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], UNKNOWN_UUIDS["SHARED_FACILITY"],
                facility["version"],
                start_at="2026-08-16T08:00:00Z", end_at="2026-08-20T08:00:00Z",
                bays_occupied=2, purpose="Material laydown"),
            developer_headers)

        validate_error(unknown_facility, ApiErrorId.SHARED_FACILITY_NOT_FOUND)

        accepted = api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], facility["id"], facility["version"],
                start_at="2026-08-16T08:00:00Z", end_at="2026-08-20T08:00:00Z",
                bays_occupied=2, purpose="Material laydown"),
            developer_headers)

        window = validate_success(accepted, expected_status=201)
        assert window["status"] == "REQUESTED"
        assert window["capacity_released"] is False
        assert window["rejection_reason"] is None
        assert window["jda_id"] == ctx["agreement"]["id"]
        assert window["shared_facility_id"] == facility["id"]
        assert read_shared_facility(facility["id"])["available_bay_capacity"] == 6
        _, meta = validate_paginated(api.list_staging_windows(
            transit_operations_manager,
            params={"shared_facility_id": facility["id"]}))
        assert meta["total_count"] == 1


class TestStagingRejectBranch:
    """The reject branch needs a reason and spends no bays."""

    def test_rejection_demands_a_reason_and_leaves_the_capacity_and_version_alone(
            self, api, transit_operations_manager):
        """PRD §3.9: "A `TransitOperationsManager` decides a requested window by
        supplying a `decision` of `APPROVE` or `REJECT`, plus a `rejection_reason`
        that is mandatory and must be non-empty on the reject branch (its absence
        being `ERR_INVALID_REQUEST`) and is ignored on the approve branch." The two
        branches then part company: "`REQUESTED → REJECTED` records the supplied
        `rejection_reason` and touches neither the facility's
        `available_bay_capacity` nor its `version` — a rejected window consumes
        nothing." The bays were never out to begin with, since only approval spends
        them: "`REQUESTED → APPROVED` decreases the shared facility's
        `available_bay_capacity` by the window's `bays_occupied`, bumps the
        facility's `version` by 1".

        Design: Corner/endpoints/corner_staging_decision_reject_branch_needs_reason_and_spares_capacity
        """
        ctx = build_context(stage="BOARD_APPROVED", negotiation_via="award",
                            period_start_date="2026-08-15",
                            period_end_date="2027-01-15",
                            site_overrides=_site("TJD-C-043",
                                                 "Walnut Court Parcel",
                                                 "43 Walnut Ct"),
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"},
                            solicitation_overrides={"min_proposals_required": 1,
                                                    "joint_use_required": False},
                            proposal_overrides={"joint_use_committed": False},
                            agreement_overrides={"joint_use_committed": False},
                            resolution_number="R-2026-143")
        facility = build_shared_facility(ctx["site"]["id"], total_bay_capacity=6)
        window = validate_success(api.create_staging_window(
            create_staging_window_payload(
                ctx["agreement"]["id"], facility["id"], facility["version"],
                start_at="2026-08-16T08:00:00Z", end_at="2026-08-20T08:00:00Z",
                bays_occupied=2, purpose="Material laydown"),
            make_developer_headers(ctx["developer"]["id"])), expected_status=201)
        facility_before = read_shared_facility(facility["id"])
        assert window["status"] == "REQUESTED"
        assert facility_before["available_bay_capacity"] == 6

        no_reason = api.decide_staging_window(window["id"],
                                             staging_decision_payload("REJECT"),
                                             transit_operations_manager)

        validate_error(no_reason, ApiErrorId.INVALID_REQUEST)

        rejected = validate_success(api.decide_staging_window(
            window["id"],
            staging_decision_payload(
                "REJECT",
                rejection_reason="Conflicts with scheduled bay resurfacing"),
            transit_operations_manager))

        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == \
            "Conflicts with scheduled bay resurfacing"
        facility_after = read_shared_facility(facility["id"])
        assert facility_after["available_bay_capacity"] == 6
        assert facility_after["version"] == facility_before["version"]


class TestAgreementAndFacilityChildCollections:
    """The collections hanging off an agreement and off a facility, and the
    staging filters, on a site carrying every child at once."""

    def test_each_collection_returns_only_its_own_rows_and_the_filters_bite(
            self, api, real_estate_officer, grants_compliance_officer,
            transit_operations_manager):
        """PRD §3.8 pins the pledge: "The slice this filing pledges is
        `federal_interest_amount_cents`: the site's `federal_interest_basis_cents`
        multiplied by the agreement's `site_area_share_pct` and divided by 100,
        rounded half up to a whole cent", and works it — "a parcel appraised at
        48,500,000 cents with a federal interest of two and a half percent has a basis
        of 1,212,500 cents; an agreement disposing of sixty percent of the parcel
        pledges 727,500 cents and leaves 485,000 cents unencumbered" — filing being
        created "with `determination` `PENDING` and `determined_at` null". PRD §3.9
        makes the charge a junction of two parents: a manager posts one "against a
        shared facility — the charge's `shared_facility_id` comes from the path —
        naming the `jda_id` of the agreement being charged the developer share", and
        the money is the PRD's own worked case: "With `maintenance_responsibility`
        `SHARED`, a `cost_share_pct_developer` of thirty-five hundredths and three
        line items of 41,250 cents each, every line rounds from 14,437.5 up to 14,438,
        giving a `developer_share_cents` of 43,314 against a `total_cost_cents` of
        123,750 and an `agency_share_cents` of 80,436." PRD §2.3 fixes the filters:
        "The staging window list is ordered by `start_at` ascending then `created_at`
        ascending, and accepts optional `jda_id`, `shared_facility_id` and `status`
        filters."

        Design: Corner/endpoints/corner_agreement_and_facility_child_collections_and_filters
        """
        site = dict(WALNUT_SITE)
        site.update(site_code="TJD-C-044", name="Walnut Station Parcel",
                    address_line="44 Walnut Stn", transit_facility_present=True)
        ctx = build_board_approved_with_shared_facility(
            negotiation_via="award",
            period_start_date="2026-08-15", period_end_date="2027-01-15",
            site_overrides=site,
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"min_proposals_required": 1,
                                    "joint_use_required": False},
            proposal_overrides={"joint_use_committed": False},
            agreement_overrides={"joint_use_committed": False,
                                 "site_area_share_pct": 60},
            resolution_number="R-2026-144",
            facility_overrides={"total_bay_capacity": 6,
                                "maintenance_responsibility": "SHARED",
                                "cost_share_pct_developer": 0.35})
        agreement_id = ctx["agreement"]["id"]
        facility_id = ctx["facility"]["id"]
        assert ctx["replacement"]["status"] == "INTERIM_IN_PLACE"
        disposition = build_disposition_request(agreement_id)
        window = build_approved_staging_window(
            agreement_id, facility_id, ctx["developer"]["id"],
            start_at="2026-08-16T08:00:00Z", end_at="2026-08-20T08:00:00Z",
            bays_occupied=2, purpose="Material laydown")
        charge = build_maintenance_charge(
            facility_id, agreement_id,
            [maintenance_line_item("Bay sweeping", 41_250),
             maintenance_line_item("Lighting service", 41_250),
             maintenance_line_item("Signage refresh", 41_250)])

        requests, request_meta = validate_paginated(
            api.list_agreement_disposition_requests(
                agreement_id, grants_compliance_officer,
                params={"limit": 10, "offset": 0}))
        assert request_meta["total_count"] == 1
        assert requests[0]["id"] == disposition["id"]
        assert requests[0]["determination"] == "PENDING"
        assert_money(requests[0]["federal_interest_amount_cents"], 727_500,
                     "federal_interest_amount_cents")

        replacements, replacement_meta = validate_paginated(
            api.list_agreement_facility_replacements(
                agreement_id, transit_operations_manager,
                params={"status": "INTERIM_IN_PLACE", "limit": 10, "offset": 0}))
        assert replacement_meta["total_count"] == 1
        assert replacements[0]["id"] == ctx["replacement"]["id"]
        assert replacements[0]["status"] == "INTERIM_IN_PLACE"

        from_agreement, agreement_charge_meta = validate_paginated(
            api.list_agreement_maintenance_charges(
                agreement_id, real_estate_officer,
                params={"limit": 10, "offset": 0}))
        assert agreement_charge_meta["total_count"] == 1
        assert from_agreement[0]["id"] == charge["id"]
        assert_money(from_agreement[0]["total_cost_cents"], 123_750,
                     "total_cost_cents")

        from_facility, facility_charge_meta = validate_paginated(
            api.list_facility_maintenance_charges(
                facility_id, transit_operations_manager,
                params={"limit": 10, "offset": 0}))
        assert facility_charge_meta["total_count"] == 1
        assert from_facility[0]["id"] == charge["id"]
        assert_money(from_facility[0]["developer_share_cents"], 43_314,
                     "developer_share_cents")
        assert_money(from_facility[0]["agency_share_cents"], 80_436,
                     "agency_share_cents")

        developer_headers = make_developer_headers(ctx["developer"]["id"])
        approved, approved_meta = validate_paginated(api.list_staging_windows(
            developer_headers,
            params={"jda_id": agreement_id, "status": "APPROVED",
                    "limit": 10, "offset": 0}))
        assert approved_meta["total_count"] == 1
        assert approved[0]["id"] == window["id"]
        assert approved[0]["status"] == "APPROVED"

        rejected, rejected_meta = validate_paginated(api.list_staging_windows(
            developer_headers,
            params={"shared_facility_id": facility_id, "status": "REJECTED",
                    "limit": 10, "offset": 0}))
        assert rejected == []
        assert rejected_meta["total_count"] == 0
