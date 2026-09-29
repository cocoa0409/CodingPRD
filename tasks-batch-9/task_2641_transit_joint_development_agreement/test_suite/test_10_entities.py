"""Record-level checks: the fields each type declares, its server-side defaults,
its computed values, and the not-found and integrity rules that guard its
parents."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUIDS,
    assert_common_fields,
    assert_immutable_event_fields,
    assert_money,
    assert_pagination_meta,
    assert_request_envelope_meta,
    assert_score,
    build_assessment,
    build_certified_valuation,
    build_context,
    build_developer,
    build_proposal,
    build_shared_facility,
    build_site,
    certify_assessment,
    create_assessment_payload,
    create_developer_payload,
    create_local_only_site_payload,
    create_maintenance_charge_payload,
    create_agreement_payload,
    create_site_payload,
    create_solicitation_payload,
    maintenance_line_item,
    read_site,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

NIL_UUID = "00000000-0000-0000-0000-000000000000"

CEDAR_EAST_SITE = {
    "site_code": "TJD-C-002",
    "name": "Cedar East Parcel",
    "address_line": "2 Cedar East",
    "parcel_area_sqft": 61000,
    "acquisition_funding_source": "FEDERAL_GRANT",
    "federal_interest_pct": 2.5,
    "transit_facility_present": False,
}


class TestAgencySiteRecord:
    """What a parcel looks like the instant it is added to the inventory, and
    what happens when the parcel named does not exist or the payload is short."""

    def test_a_new_parcel_carries_the_declared_defaults_and_a_success_envelope(
            self, api, real_estate_officer):
        """PRD §3.1: "A new site opens in `INVENTORIED` with
        `readiness_composite_score` and `readiness_tier` both null, all three
        federal-interest ledger fields at 0, and `version` at 1." The
        `transit_facility_present` flag is "optional ... false when omitted", and
        PRD §4 fixes the code: "Creating a new resource returns HTTP 201 with the
        created resource in `data`." PRD §2.2 fixes the envelope: "The
        `response_type` is either "object" for a single resource or "array" for a
        list of resources."

        Design: Corner/entities/corner_site_creation_returns_declared_fields_and_defaults
        """
        set_logical_clock()

        response = api.create_site(create_local_only_site_payload(
            site_code="TJD-C-001", name="Cedar Junction Parcel",
            address_line="1 Cedar Junction", parcel_area_sqft=54000),
            real_estate_officer)

        site = validate_success(response, expected_status=201)
        body = response.json()
        assert body["response_type"] == "object"
        assert_request_envelope_meta(body["meta"])
        assert site["status"] == "INVENTORIED"
        assert site["readiness_tier"] is None
        assert site["readiness_composite_score"] is None
        assert_money(site["federal_interest_basis_cents"], 0,
                     "federal_interest_basis_cents")
        assert site["transit_facility_present"] is False
        assert site["version"] == 1
        assert site["site_code"] == "TJD-C-001"
        assert site["parcel_area_sqft"] == 54000

    def test_reading_the_parcel_back_returns_the_stored_row_unrecomputed(
            self, api, grants_compliance_officer):
        """PRD §4: "Fetch one agency site with its computed readiness score, tier
        and federal-interest ledger fields", and PRD §3.1: "A new site opens in
        `INVENTORIED` with `readiness_composite_score` and `readiness_tier` both
        null". Nothing about a parcel with no assessment yet invents a readiness
        number, so the read reports exactly the two funding fields recorded at
        intake — PRD §3.1: "`acquisition_funding_source` is one of
        `FEDERAL_GRANT`, `LOCAL_ONLY` or `MIXED`, and `federal_interest_pct` is
        the percentage of the parcel's value in which the grantor retains an
        interest".

        Design: Corner/entities/corner_site_retrieval_returns_stored_representation
        """
        set_logical_clock()
        site = build_site(**CEDAR_EAST_SITE)

        fetched = validate_success(api.get_site(site["id"],
                                                grants_compliance_officer))

        assert fetched["site_code"] == "TJD-C-002"
        assert fetched["parcel_area_sqft"] == 61000
        assert fetched["acquisition_funding_source"] == "FEDERAL_GRANT"
        assert fetched["federal_interest_pct"] == 2.5
        assert fetched["status"] == "INVENTORIED"
        assert fetched["readiness_composite_score"] is None
        assert fetched["readiness_tier"] is None

    def test_fetching_a_parcel_that_was_never_created_reports_the_site(
            self, api, real_estate_officer):
        """PRD §2.9: "The first segment that names a record which does not exist
        decides the response, with its own not-found code: `ERR_SITE_NOT_FOUND`
        ... all at HTTP 404." PRD §2.2 fixes the shape of that answer: "The
        `error_id` is a unique, machine-readable string that identifies the
        specific error" and "The `message` provides a human-readable explanation
        of what went wrong."

        Design: Corner/entities/corner_get_unknown_site_returns_site_not_found
        """
        set_logical_clock()

        response = api.get_site(NIL_UUID, real_estate_officer)

        error = validate_error(response, ApiErrorId.SITE_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"]
        assert response.json()["response_type"] == "error"

    def test_a_parcel_with_no_funding_source_is_malformed_and_creates_nothing(
            self, api, real_estate_officer):
        """PRD §3.1 makes the field part of the parcel's funding history: "Two
        fields describe the parcel's funding history and drive everything federal
        that follows: `acquisition_funding_source` is one of `FEDERAL_GRANT`,
        `LOCAL_ONLY` or `MIXED`". PRD §2.11 ranks the shape check: "Request shape
        — required fields present, types correct, enum values inside their
        declared sets, numeric ranges honoured, structure-conditional money fields
        supplied, and `limit` inside 1 through 100 (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/corner_site_create_missing_funding_source_rejected
        """
        set_logical_clock()

        response = api.create_site(create_site_payload(
            site_code="TJD-C-005", name="Cedar Gap Parcel",
            address_line="5 Cedar Gap", parcel_area_sqft=40000,
            federal_interest_pct=0, acquisition_funding_source=None),
            real_estate_officer)

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        sites, meta = validate_paginated(api.list_sites(real_estate_officer))
        assert meta["total_count"] == 0
        assert [site for site in sites if site["site_code"] == "TJD-C-005"] == []


class TestReadinessAssessmentRecord:
    """The assessment's server-computed and server-minted fields, and the parent
    parcel it hangs from."""

    @staticmethod
    def _local_only_site(site_code: str, name: str, address_line: str):
        set_logical_clock()
        return build_site(site_code=site_code, name=name,
                          address_line=address_line, parcel_area_sqft=48000,
                          acquisition_funding_source="LOCAL_ONLY",
                          federal_interest_pct=0,
                          transit_facility_present=False)

    def test_intake_computes_the_preliminary_mean_and_leaves_the_tier_null(
            self, api, real_estate_officer):
        """PRD §3.1: "While the assessment is a `DRAFT`, `variant_applied` is
        `PRELIMINARY` and `composite_score` is simply the unweighted arithmetic
        mean of the four sub-scores — their sum divided by four, rounded half up
        to two decimal places. The preliminary variant is an intake screen: it
        ignores `encumbrance_count` and the site's `federal_interest_pct`
        entirely, and it leaves `tier` null." Sub-scores of 90, 80, 70 and 60 sum
        to 300, so the mean is 75.00. PRD §3.1 adds that creating the record
        "bumps the parent site's `version` by 1 even though nothing about the
        site itself changed".

        Design: Corner/entities/corner_assessment_composite_score_computed_at_intake
        """
        site = self._local_only_site("TJD-C-006", "Cedar Ridge Parcel",
                                     "6 Cedar Ridge")

        response = api.create_assessment(site["id"], create_assessment_payload(
            environmental_score=90, utility_score=80, access_score=70,
            entitlement_score=60, encumbrance_count=0,
            assessment_notes="Intake screen"), real_estate_officer)

        assessment = validate_success(response, expected_status=201)
        assert_score(assessment["composite_score"], 75.00, "composite_score")
        assert assessment["variant_applied"] == "PRELIMINARY"
        assert assessment["tier"] is None
        assert assessment["status"] == "DRAFT"
        assert read_site(site["id"])["version"] == site["version"] + 1

    def test_the_four_system_fields_come_from_the_server_not_the_body(
            self, api, real_estate_officer):
        """PRD §2.4: "Every persisted record carries an `id` that is a
        server-minted UUID with no type prefix — clients never supply it — and a
        `created_at` timestamp in ISO 8601 UTC form with exactly three fractional
        digits", plus "an integer `version` that starts at 1 when the record is
        created". PRD §2.5 pins the instant those stamps read: "Before the clock
        is ever set, the logical current UTC instant is `2026-08-01T00:00:00Z`."
        PRD §3.1: "A newly recorded assessment lands in `DRAFT` with
        `certified_at` null" and "an optional `assessment_notes` free-text field
        defaults to the empty string".

        Design: Corner/entities/corner_assessment_system_fields_generated_by_server
        """
        site = self._local_only_site("TJD-C-007", "Cedar Hollow Parcel",
                                     "7 Cedar Hollow")

        response = api.create_assessment(site["id"], create_assessment_payload(
            environmental_score=90, utility_score=80, access_score=70,
            entitlement_score=60, encumbrance_count=0), real_estate_officer)

        assessment = validate_success(response, expected_status=201)
        assert_common_fields(assessment, "assessment")
        assert assessment["version"] == 1
        assert assessment["created_at"].startswith("2026-08-01T00:00:00")
        assert assessment["updated_at"].startswith("2026-08-01T00:00:00")
        assert assessment["certified_at"] is None
        assert assessment["status"] == "DRAFT"
        assert assessment["assessment_notes"] == ""

    def test_an_assessment_under_an_unknown_parcel_reports_the_parcel(
            self, api, real_estate_officer):
        """PRD §2.9: "Path segments are resolved strictly **left to right**, in
        this order: site, then assessment", and "The first segment that names a
        record which does not exist decides the response, with its own not-found
        code: `ERR_SITE_NOT_FOUND`". The path is resolved before the body, since
        "Foreign keys supplied in a request body are resolved after every path
        segment has been resolved".

        Design: Corner/entities/corner_assessment_under_unknown_parent_site_not_found
        """
        set_logical_clock()

        response = api.create_assessment(UNKNOWN_UUIDS["SITE"],
                                         create_assessment_payload(),
                                         real_estate_officer)

        validate_error(response, ApiErrorId.SITE_NOT_FOUND)
        sites, meta = validate_paginated(api.list_sites(real_estate_officer))
        assert meta["total_count"] == 0


class TestDeveloperRecord:
    """A development partner registered with nothing but a name and an address."""

    def test_the_two_optional_postures_fall_back_to_their_declared_defaults(
            self, api, real_estate_officer):
        """PRD §3.3: "A `RealEstateOfficer` registers a development partner with a
        `legal_name` and a `contact_email`, plus two optional postures that are
        recorded once at registration and are not editable afterwards:
        `prequalified`, false when omitted, records whether the partner has passed
        agency prequalification, and `debarment_status`, `CLEAR` when omitted, is
        one of `CLEAR`, `SUSPENDED` or `DEBARRED`." PRD §4: "Creating a new
        resource returns HTTP 201 with the created resource in `data`."

        Design: Corner/entities/corner_developer_defaults_applied_when_flags_omitted
        """
        set_logical_clock()

        response = api.create_developer(create_developer_payload(
            legal_name="Dogwood Station Ventures LLC",
            contact_email="dev-d@example.com"), real_estate_officer)

        developer = validate_success(response, expected_status=201)
        assert developer["prequalified"] is False
        assert developer["debarment_status"] == "CLEAR"
        assert developer["legal_name"] == "Dogwood Station Ventures LLC"
        assert developer["version"] == 1


class TestSolicitationRecord:
    """A solicitation whose type is outside the declared set."""

    def test_an_undeclared_solicitation_type_creates_no_solicitation(
            self, api, real_estate_officer):
        """PRD §2.11 ranks the shape check third: "Request shape — required fields
        present, types correct, enum values inside their declared sets, numeric
        ranges honoured, structure-conditional money fields supplied, and `limit`
        inside 1 through 100 (`ERR_INVALID_REQUEST`)." The declared set is fixed
        by PRD §3.3: "a `solicitation_type` of `RFP`, `RFQ` or
        `UNSOLICITED_RESPONSE`", so `RFI` is outside it and the released parcel is
        left where it was.

        Design: Corner/entities/corner_solicitation_invalid_type_enum_rejected
        """
        ctx = build_context(stage="RELEASED", site_overrides={
            "site_code": "TJD-C-008", "name": "Cedar Flats Parcel",
            "address_line": "8 Cedar Flats", "parcel_area_sqft": 61000,
            "acquisition_funding_source": "FEDERAL_GRANT",
            "federal_interest_pct": 2.5, "transit_facility_present": False})

        response = api.create_solicitation(
            ctx["site"]["id"],
            create_solicitation_payload(solicitation_type="RFI"),
            real_estate_officer)

        validate_error(response, ApiErrorId.INVALID_REQUEST)
        _, meta = validate_paginated(api.list_site_solicitations(
            ctx["site"]["id"], real_estate_officer))
        assert meta["total_count"] == 0
        assert read_site(ctx["site"]["id"])["status"] == "SOLICITATION_READY"


class TestProposalListing:
    """Three proposals on one solicitation, walked two at a time."""

    def test_two_pages_report_the_same_total_and_flip_has_more(
            self, api, real_estate_officer):
        """PRD §2.3: "`limit` defaults to 10 when omitted, may not be lower than 1
        and may not exceed 100", "`offset` defaults to 0 and counts records
        skipped from the head of the ordered result", and "The `meta` block of a
        list response carries `limit`, `offset`, `total_count` (the number of
        records matching the filters before pagination is applied) and `has_more`
        (true when records remain beyond the current page)." PRD §2.2: "The
        `response_type` is either "object" for a single resource or "array" for a
        list of resources."

        Design: Corner/entities/corner_proposal_listing_pagination_total_count_and_has_more
        """
        ctx = build_context(stage="SOLICITATION_ISSUED", site_overrides={
            "site_code": "TJD-C-003", "name": "Cedar West Parcel",
            "address_line": "3 Cedar West", "parcel_area_sqft": 61000,
            "acquisition_funding_source": "FEDERAL_GRANT",
            "federal_interest_pct": 2.5, "transit_facility_present": False},
            developer_overrides={"prequalified": True,
                                 "debarment_status": "CLEAR"},
            solicitation_overrides={"affordable_housing_min_pct": 15})
        solicitation_id = ctx["solicitation"]["id"]
        developer_b = build_developer(legal_name="Birch Union Development Co",
                                      contact_email="dev-b@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        developer_c = build_developer(legal_name="Cypress Transit Holdings LLC",
                                      contact_email="dev-c@example.com",
                                      prequalified=True,
                                      debarment_status="CLEAR")
        proposal_ids = {
            build_proposal(solicitation_id, ctx["developer"]["id"])["id"],
            build_proposal(solicitation_id, developer_b["id"])["id"],
            build_proposal(solicitation_id, developer_c["id"])["id"],
        }

        first_response = api.list_proposals(
            real_estate_officer,
            params={"solicitation_id": solicitation_id, "limit": 2, "offset": 0})
        second_response = api.list_proposals(
            real_estate_officer,
            params={"solicitation_id": solicitation_id, "limit": 2, "offset": 2})

        first_page, first_meta = validate_paginated(first_response)
        second_page, second_meta = validate_paginated(second_response)
        assert len(first_page) == 2
        assert_pagination_meta(first_meta, total_count=3, has_more=True,
                               limit=2, offset=0)
        assert len(second_page) == 1
        assert_pagination_meta(second_meta, total_count=3, has_more=False,
                               limit=2, offset=2)
        assert first_response.json()["response_type"] == "array"
        assert second_response.json()["response_type"] == "array"
        assert first_page[0]["id"] in proposal_ids
        assert second_page[0]["id"] in proposal_ids
        assert second_page[0]["id"] != first_page[0]["id"]


class TestMaintenanceChargeRecord:
    """The one record type in the domain that is an event rather than a row that
    can be revised."""

    def test_an_agency_maintained_facility_posts_a_charge_with_no_version_field(
            self, api, transit_operations_manager):
        """PRD §2.4: "`MaintenanceCharge` is the single exception. A maintenance
        charge is an immutable event record: once posted it is never amended,
        there is no update operation for it, and it carries only `id` and
        `created_at`. It has neither `updated_at` nor `version`, and callers must
        not expect either field on it." PRD §3.9 pins the split for this posture:
        "`effective_share_applied` is one whole when the facility's
        `maintenance_responsibility` is `DEVELOPER`, zero when it is `AGENCY`",
        and "`total_cost_cents` is the plain sum of every line item's
        `cost_cents`, and `agency_share_cents` is `total_cost_cents` less
        `developer_share_cents`". Lines of 10,000 and 20,000 cents therefore total
        30,000 with the whole of it on the agency.

        Design: Corner/entities/corner_maintenance_charge_is_immutable_event_without_version
        """
        ctx = build_context(stage="DRAFTING", negotiation_via="award",
                            site_overrides={
                                "site_code": "TJD-C-009",
                                "name": "Cedar Bay Parcel",
                                "address_line": "9 Cedar Bay",
                                "parcel_area_sqft": 61000,
                                "acquisition_funding_source": "FEDERAL_GRANT",
                                "federal_interest_pct": 2.5,
                                "transit_facility_present": False},
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        facility = build_shared_facility(ctx["site"]["id"],
                                         facility_type="BUS_BAY",
                                         total_bay_capacity=6,
                                         maintenance_responsibility="AGENCY",
                                         cost_share_pct_developer=None)

        response = api.create_maintenance_charge(
            facility["id"],
            create_maintenance_charge_payload(
                ctx["agreement"]["id"],
                [maintenance_line_item("Sweeping", 10_000),
                 maintenance_line_item("Lighting", 20_000)],
                period_start="2026-09-01", period_end="2026-09-30"),
            transit_operations_manager)

        charge = validate_success(response, expected_status=201)
        assert_score(charge["effective_share_applied"], 0.00,
                     "effective_share_applied")
        assert_money(charge["total_cost_cents"], 30_000, "total_cost_cents")
        assert_money(charge["developer_share_cents"], 0, "developer_share_cents")
        assert_money(charge["agency_share_cents"], 30_000, "agency_share_cents")
        assert_immutable_event_fields(charge, "charge")
        _, meta = validate_paginated(api.list_facility_maintenance_charges(
            facility["id"], transit_operations_manager))
        assert meta["total_count"] == 1


class TestAgreementJunction:
    """The agreement joins four parents, so the parents have to agree with each
    other and not merely exist."""

    def test_a_valuation_belonging_to_another_parcel_cannot_back_the_agreement(
            self, api, real_estate_officer):
        """PRD §3.6: "The referenced valuation's site must be the same site the
        agreement names, and the referenced proposal's solicitation must belong to
        that same site, otherwise `ERR_VALUATION_SITE_MISMATCH`." Both identifiers
        resolve, so the junction rule is the only thing that can refuse the draft
        — PRD §2.9: "Foreign keys supplied in a request body are resolved after
        every path segment has been resolved, and among themselves in body-field
        declaration order".

        Design: Corner/entities/corner_agreement_graph_junction_rejects_valuation_from_another_site
        """
        ctx = build_context(stage="VALUATION", negotiation_via="award",
                            site_overrides={
                                "site_code": "TJD-C-010",
                                "name": "Cedar Loop Parcel A",
                                "address_line": "10 Cedar Loop",
                                "parcel_area_sqft": 61000,
                                "acquisition_funding_source": "FEDERAL_GRANT",
                                "federal_interest_pct": 2.5,
                                "transit_facility_present": False},
                            developer_overrides={"prequalified": True,
                                                 "debarment_status": "CLEAR"})
        site_b = build_site(site_code="TJD-C-011",
                            name="Cedar Loop Parcel B",
                            address_line="11 Cedar Loop",
                            parcel_area_sqft=52000,
                            acquisition_funding_source="FEDERAL_GRANT",
                            federal_interest_pct=2.5,
                            transit_facility_present=False)
        certify_assessment(build_assessment(site_b["id"])["id"])
        valuation_b = build_certified_valuation(site_b["id"])
        assert ctx["site"]["status"] == "UNDER_AGREEMENT"

        response = api.create_agreement(create_agreement_payload(
            ctx["site"]["id"], ctx["developer"]["id"], ctx["proposal"]["id"],
            valuation_b["id"]), real_estate_officer)

        validate_error(response, ApiErrorId.VALUATION_SITE_MISMATCH)
        _, meta = validate_paginated(api.list_agreements(
            real_estate_officer, params={"site_id": ctx["site"]["id"]}))
        assert meta["total_count"] == 0
        assert read_site(ctx["site"]["id"])["status"] == "UNDER_AGREEMENT"
        assert valuation_b["site_id"] == site_b["id"]
