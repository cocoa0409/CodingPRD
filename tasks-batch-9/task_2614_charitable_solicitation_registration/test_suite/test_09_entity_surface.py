"""The entity surface: what a create echoes, what a read returns, what a list filters.

These are the plain contracts underneath every workflow — server-minted
identifiers, documented defaults, derived expense figures, scoped child
collections and the not-found codes that guard every reference.
"""

import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    NON_EXISTENT_UUID,
    REGULATOR,
    ApiErrorId,
    api_client,
    california_profile_payload,
    create_disclosure_statement,
    create_financial_statement,
    create_fundraiser,
    create_officer,
    create_officer_pair,
    create_organization,
    create_solicitation_activity,
    draft_contract,
    draft_promotion,
    financial_statement_payload,
    is_valid_uuid,
    list_financial_statements,
    make_fundraiser_agent_headers,
    open_filing,
    organization_payload,
    read_organization,
    read_registration,
    register_fundraiser_in_state,
    registration_document_payload,
    request_extension,
    seed_california_profile,
    seed_state_profile,
    setup_delinquent_filing,
    setup_filed_contract,
    solicitation_activity_payload,
    state_profile_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStateProfileCreation:
    """The configuration row is echoed back exactly as it was declared."""

    def test_a_fully_specified_profile_is_echoed_field_for_field_at_version_one(self):
        """PRD §2.7: "A `StateProfile` row, keyed by its two-letter `state_code`, is
        the sole source of every jurisdictional parameter". PRD §2.5: "Every resource
        carries a server-minted `id` formatted as a bare UUID with no type prefix,
        and a `created_at` timestamp in ISO 8601 UTC with three fractional digits"
        alongside "`version`, an integer that starts at 1 on creation and increments
        by exactly one on every mutation of that row".

        Design: Corner/entities/state_profile_create_echoes_every_declared_field
        """
        payload = california_profile_payload(
            disclosure_required_clauses=[
                "REGISTRATION_DISCLOSURE",
                "FINANCIAL_STATEMENT_AVAILABILITY",
            ]
        )

        response = api_client.create_state_profile(payload, ADMIN)
        profile = validate_success(response, 201)
        envelope = response.json()

        assert profile["state_code"] == "CA", (
            f"The two-letter key is stored verbatim, got {profile['state_code']}"
        )
        assert profile["renewal_due_rule"] == "FYE_PLUS_4M_15D", (
            f"The deadline rule is echoed, got {profile['renewal_due_rule']}"
        )
        assert profile["audit_threshold_cents"] == 200_000_000, (
            f"The audit threshold is echoed, got {profile['audit_threshold_cents']}"
        )
        assert profile["disclosure_required_clauses"] == [
            "REGISTRATION_DISCLOSURE",
            "FINANCIAL_STATEMENT_AVAILABILITY",
        ], f"The clause list is echoed, got {profile['disclosure_required_clauses']}"
        assert profile["version"] == 1, (
            f"A freshly created row is at version 1, got {profile['version']}"
        )
        assert is_valid_uuid(profile["id"]), (
            f"The identifier is a bare UUID, got {profile['id']}"
        )
        assert envelope["meta"]["api_request_id"].startswith("req_"), (
            "Every envelope carries a request identifier prefixed req_, got "
            f"{envelope['meta']['api_request_id']}"
        )
        assert envelope["response_type"] == "object", (
            f"A single resource is an object, got {envelope['response_type']}"
        )

    def test_a_renewal_rule_outside_the_declared_enum_is_refused(self):
        """PRD §2.11 rung 3: "Request shape — required fields present, enum values in
        range, integers non-negative where constrained, arrays non-empty where
        constrained, datetimes parseable as ISO 8601 ... → `ERR_INVALID_REQUEST`
        (422). Applies to every endpoint."

        Design: Corner/entities/state_profile_invalid_enum_returns_invalid_request
        """
        response = api_client.create_state_profile(
            state_profile_payload("CA", renewal_due_rule="FYE_PLUS_3M"), ADMIN
        )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        validate_error(
            api_client.get_state_profile("CA", ADMIN),
            ApiErrorId.ERR_STATE_PROFILE_NOT_FOUND.value,
        )


class TestOrganizationRead:
    """A read of a charity shows the derived side of the record."""

    def test_a_new_charity_reads_back_with_every_derived_field_at_its_default(self):
        """PRD §3.1: "Creation initialises the derived side of the record and clients
        may not set any of it: `solicitation_posture` starts at `CLEAR`,
        `filing_posture` at `CURRENT`, `registered_state_count` and
        `delinquent_registration_count` at 0, `ceased_state_codes` at an empty list,
        and `penalty_outstanding_cents` at 0."

        Design: Corner/entities/organization_read_returns_stored_and_derived_fields
        """
        seed_state_profile("CA")
        created = create_organization()

        organization = validate_success(
            api_client.get_organization(created["id"], COMPLIANCE)
        )

        assert organization["id"] == created["id"]
        assert organization["legal_name"] == "Harbor Light Foundation", (
            f"The stored name is unchanged, got {organization['legal_name']}"
        )
        assert organization["fiscal_year_end_month"] == 6, (
            f"The fiscal year end is unchanged, got {organization['fiscal_year_end_month']}"
        )
        assert organization["solicitation_posture"] == "CLEAR"
        assert organization["filing_posture"] == "CURRENT"
        assert organization["registered_state_count"] == 0
        assert organization["delinquent_registration_count"] == 0
        assert organization["ceased_state_codes"] == []
        assert organization["penalty_outstanding_cents"] == 0

    def test_an_unused_uuid_on_the_path_reports_the_organization_not_found_code(self):
        """PRD §2.9: "The first identifier in the path that names no existing row
        determines the error, and the server stops there rather than continuing to
        evaluate deeper segments or the request body: ... an organization read or
        amendment reports `ERR_ORGANIZATION_NOT_FOUND` ... All nine carry HTTP 404."

        Design: Corner/entities/organization_read_with_unknown_id_returns_not_found
        """
        seed_state_profile("CA")

        response = api_client.get_organization(NON_EXISTENT_UUID, COMPLIANCE)

        validate_error(response, ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value)
        assert response.json()["response_type"] == "error", (
            "A failure uses the error envelope, got "
            f"{response.json()['response_type']}"
        )


class TestFilingListPagination:
    """Two filings, one per page."""

    def _two_draft_filings(self):
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()
        statement = create_financial_statement(organization)
        first = open_filing(
            organization["id"],
            statement["id"],
            "CA",
            fiscal_year=2025,
            coverage_start="2024-07-01T00:00:00Z",
            coverage_end="2025-07-01T00:00:00Z",
        )
        second = open_filing(organization["id"], statement["id"], "CA")
        return organization, first, second

    def test_a_one_row_page_reports_the_full_total_and_more_to_come(self):
        """PRD §2.3: "`limit` caps the number of records returned; it defaults to 10
        when omitted, may not be smaller than 1, and may not be larger than 100.
        `offset` is the number of records to skip and defaults to 0. Both are echoed
        back in the `meta` object of the envelope alongside `total_count` (the number
        of records matching the filters before pagination is applied) and `has_more`
        (true when records remain beyond the current page)." PRD §2.3 also fixes the
        order: "every list is sorted by `created_at` ascending".

        Design: Corner/entities/state_registration_list_paginates_with_total_count_and_has_more
        """
        organization, first, _second = self._two_draft_filings()

        rows, meta = validate_paginated(
            api_client.list_state_registrations(
                COMPLIANCE,
                params={"organization_id": organization["id"], "limit": 1, "offset": 0},
            )
        )

        assert len(rows) == 1, f"The page holds one row, got {len(rows)}"
        assert meta["total_count"] == 2, (
            f"Both filings match the filter, got {meta['total_count']}"
        )
        assert meta["has_more"] is True, "A second page remains"
        assert meta["limit"] == 1, f"The limit is echoed, got {meta['limit']}"
        assert rows[0]["id"] == first["id"], (
            "Creation order puts the 2025 filing first"
        )

    def test_the_second_page_returns_the_later_row_and_reports_nothing_further(self):
        """PRD §2.3: "`offset` is the number of records to skip and defaults to 0.
        Both are echoed back in the `meta` object of the envelope alongside
        `total_count` (the number of records matching the filters before pagination
        is applied) and `has_more` (true when records remain beyond the current
        page)."

        Design: Corner/entities/state_registration_list_paginates_with_total_count_and_has_more
        """
        organization, _first, second = self._two_draft_filings()

        rows, meta = validate_paginated(
            api_client.list_state_registrations(
                COMPLIANCE,
                params={"organization_id": organization["id"], "limit": 1, "offset": 1},
            )
        )

        assert meta["total_count"] == 2, (
            f"The total ignores pagination, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "Nothing remains beyond the second row"
        assert rows[0]["id"] == second["id"], (
            "The 2026 filing was created second"
        )


class TestFinancialStatementCreation:
    """Required inputs, documented defaults and two derived figures."""

    def test_omitting_contributions_is_a_request_shape_failure_that_writes_nothing(self):
        """PRD §3.2: "The preparer supplies `total_revenue_cents`, which must be at
        least as large as `contributions_cents`; `contributions_cents`, the money
        given by the public and excluding government grants". PRD §2.11 rung 3:
        "Request shape — required fields present, enum values in range ... →
        `ERR_INVALID_REQUEST` (422). Applies to every endpoint."

        Design: Corner/entities/financial_statement_missing_required_field_rejected
        """
        seed_state_profile("CA")
        organization = create_organization()
        payload = financial_statement_payload(organization["id"], organization["version"])
        del payload["contributions_cents"]

        response = api_client.create_financial_statement(payload, COMPLIANCE)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert read_organization(organization["id"])["version"] == 1, (
            "A refused statement leaves the organization's version alone"
        )
        assert list_financial_statements(organization["id"]) == [], (
            "No statement row was written"
        )

    def test_the_two_expense_figures_are_derived_from_the_three_expense_inputs(self):
        """PRD §3.2: "Two figures are derived on creation.
        `functional_expense_total_cents` is the sum of the program, fundraising and
        management expense amounts. `program_ratio` is the program expense divided by
        that functional expense total, rounded half up to four decimal places, and is
        defined as `0.0` whenever the functional expense total is zero". PRD §3.2 also
        fixes the status: "A newly created statement takes `statement_status` of
        `CURRENT`; the server, never the client, owns that field."

        Design: Corner/entities/financial_statement_computed_expense_fields_derived_from_inputs
        """
        seed_state_profile("CA", assurance_basis="GROSS_REVENUE")
        organization = create_organization()

        statement = create_financial_statement(organization)

        assert statement["functional_expense_total_cents"] == 24_000_000, (
            "18,000,000 + 4,000,000 + 2,000,000, got "
            f"{statement['functional_expense_total_cents']}"
        )
        assert statement["program_ratio"] == pytest.approx(0.75, abs=0.01), (
            "18,000,000 of program expense over a 24,000,000 functional total, got "
            f"{statement['program_ratio']}"
        )
        assert statement["statement_status"] == "CURRENT", (
            f"The server owns the status, got {statement['statement_status']}"
        )


class TestDocumentedDefaults:
    """Every optional field falls back to a documented value."""

    def test_a_minimal_profile_falls_back_to_every_documented_rule_default(self):
        """PRD §3.1: the donor clause "fires when `donor_count` is at least the
        state's `donor_count_trigger`, which defaults to 25 donors", the money clause
        "fires when `contributions_cents` is at least the state's
        `contribution_trigger_cents`, which defaults to $25,000 — that is, 2,500,000
        cents", and the third "fires when the state's `online_presence_counts` flag is
        true (its default is false)". PRD §3.5: "its `extension_allowed` must be true
        (the default is false) and its `extension_max_days` must be at least 1 (the
        default is 0)". PRD §3.8: "The base is the state's
        `disclosure_required_clauses`, which defaults to an empty list." PRD §3.9:
        "that month's charge is the state's `late_fee_base_cents` (default 2,000
        cents) multiplied by one plus the state's `late_fee_escalation_pct` (default
        0.1)".

        Design: Corner/entities/optional_field_defaults_applied_when_omitted
        """
        profile = seed_state_profile(
            "WY",
            renewal_due_rule="CALENDAR_MAY_15",
            assurance_basis="CONTRIBUTIONS_ONLY",
            review_threshold_cents=25_000_000,
            audit_threshold_cents=100_000_000,
        )

        assert profile["donor_count_trigger"] == 25, (
            f"The donor trigger defaults to 25, got {profile['donor_count_trigger']}"
        )
        assert profile["contribution_trigger_cents"] == 2_500_000, (
            "The money trigger defaults to 2,500,000 cents, got "
            f"{profile['contribution_trigger_cents']}"
        )
        assert profile["online_presence_counts"] is False, (
            f"Online presence is off by default, got {profile['online_presence_counts']}"
        )
        assert profile["extension_allowed"] is False, (
            f"Extensions are off by default, got {profile['extension_allowed']}"
        )
        assert profile["extension_max_days"] == 0, (
            f"No days are allowed by default, got {profile['extension_max_days']}"
        )
        assert profile["disclosure_required_clauses"] == [], (
            "No clause is required by default, got "
            f"{profile['disclosure_required_clauses']}"
        )
        assert profile["late_fee_base_cents"] == 2_000, (
            f"The late base defaults to 2,000 cents, got {profile['late_fee_base_cents']}"
        )
        assert profile["late_fee_escalation_pct"] == pytest.approx(0.1, abs=0.01), (
            f"The escalation defaults to 0.1, got {profile['late_fee_escalation_pct']}"
        )

    def test_a_minimal_charity_and_statement_fall_back_to_their_own_defaults(self):
        """PRD §3.1: "Two optional flags round out the profile:
        `has_online_donation_page`, which defaults to false and declares whether the
        charity operates an interactive online giving page, and `lifecycle_status`,
        which defaults to `ACTIVE` and may otherwise be `DISSOLVED`." PRD §3.2:
        "optionally `government_grant_cents`, which defaults to 0" and "One further
        optional field, `assurance_level`, records the level of independent assurance
        actually obtained; it defaults to `NONE` and may otherwise be `REVIEW` or
        `AUDIT`."

        Design: Corner/entities/optional_field_defaults_applied_when_omitted
        """
        seed_state_profile(
            "WY",
            renewal_due_rule="CALENDAR_MAY_15",
            review_threshold_cents=25_000_000,
            audit_threshold_cents=100_000_000,
        )
        organization_body = organization_payload(
            legal_name="Prairie Trust",
            ein="223456789",
            domicile_state_code="WY",
            fiscal_year_end_month=12,
        )
        del organization_body["has_online_donation_page"]
        organization = validate_success(
            api_client.create_organization(organization_body, COMPLIANCE), 201
        )

        statement_body = financial_statement_payload(
            organization["id"],
            organization["version"],
            fiscal_year=2025,
            total_revenue_cents=1_000_000,
            contributions_cents=900_000,
            program_expense_cents=700_000,
            fundraising_expense_cents=200_000,
            management_expense_cents=100_000,
        )
        del statement_body["assurance_level"]
        statement = validate_success(
            api_client.create_financial_statement(statement_body, COMPLIANCE), 201
        )

        assert organization["has_online_donation_page"] is False, (
            "The online giving flag defaults to false, got "
            f"{organization['has_online_donation_page']}"
        )
        assert organization["lifecycle_status"] == "ACTIVE", (
            f"A new charity is active, got {organization['lifecycle_status']}"
        )
        assert statement["assurance_level"] == "NONE", (
            f"No assurance was obtained, got {statement['assurance_level']}"
        )
        assert statement["government_grant_cents"] == 0, (
            f"Grants default to nothing, got {statement['government_grant_cents']}"
        )
        assert statement["statement_status"] == "CURRENT", (
            f"The new statement is authoritative, got {statement['statement_status']}"
        )


class TestSolicitationActivityIsAnEvent:
    """The activity row is history, not a mutable record."""

    def test_an_activity_row_carries_no_version_and_no_updated_at(self):
        """PRD §2.5: "`SolicitationActivity` is the single exception. It is an
        immutable event record: it carries `id` and `created_at` only, and both
        `updated_at` and `version` are absent from its representation." PRD §3.1 fixes
        the scoring: "`trigger_reasons` lists whichever clauses fired in the canonical
        order `DONOR_COUNT`, then `CONTRIBUTION_TOTAL`, then
        `TARGETED_ONLINE_PRESENCE`".

        Design: Corner/entities/solicitation_activity_is_an_immutable_event_row
        """
        seed_california_profile()
        organization = create_organization()

        activity = validate_success(
            api_client.create_solicitation_activity(
                solicitation_activity_payload(
                    organization["id"],
                    "CA",
                    donor_count=40,
                    contributions_cents=900_000,
                    channels=["MAIL"],
                ),
                COMPLIANCE,
            ),
            201,
        )

        assert activity["triggers_registration"] is True, (
            "Forty donors clears the twenty-five donor trigger, got "
            f"{activity['triggers_registration']}"
        )
        assert activity["trigger_reasons"] == ["DONOR_COUNT"], (
            "Only the donor clause fired, got " f"{activity['trigger_reasons']}"
        )
        assert "version" not in activity, (
            f"An event row carries no version, got {activity.get('version')}"
        )
        assert "updated_at" not in activity, (
            f"An event row is never updated, got {activity.get('updated_at')}"
        )
        assert is_valid_uuid(activity["id"]), (
            f"It still carries an identifier, got {activity['id']}"
        )


class TestBodyForeignKeyResolution:
    """A dangling body reference is a not-found, resolved in a fixed order."""

    def test_a_document_naming_no_filing_reports_the_registration_not_found_code(self):
        """PRD §2.9: "Foreign keys arriving in a request body are resolved in a fixed
        order so that the reported error is deterministic when more than one is wrong:
        `organization_id` first, then `state_code` or every element of `state_codes`,
        then `financial_statement_id`, then `registration_id`, then
        `prepared_by_officer_id` ... a dangling `registration_id` or
        `supersedes_registration_id` reports `ERR_REGISTRATION_NOT_FOUND`."

        Design: Corner/entities/registration_document_with_unknown_parent_returns_not_found
        """
        seed_state_profile("CA")
        organization = create_organization()
        preparer = create_officer(organization["id"], "Sam Okoye", "SECRETARY")

        response = api_client.create_registration_document(
            registration_document_payload(NON_EXISTENT_UUID, preparer["id"]),
            COMPLIANCE,
        )

        validate_error(response, ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value)


class TestContractGraphIsSymmetric:
    """One contract row is reachable from the charity side and the firm side."""

    def test_the_same_contract_is_listed_by_organization_and_by_fundraiser(self):
        """PRD §3.6: "A contract is created in `DRAFT` by a compliance officer" and
        "Contracts can be listed filtered by `organization_id`, `fundraiser_id`,
        `state_code` or `status`, read individually, filed, and terminated."

        Design: Corner/entities/many_to_many_contract_is_reachable_from_both_endpoints_of_the_graph
        """
        seed_california_profile()
        organization = create_organization()
        fundraiser = create_fundraiser(
            legal_name="Northline Donor Services",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        register_fundraiser_in_state(fundraiser["id"], "CA")
        contract = draft_contract(
            organization["id"],
            fundraiser["id"],
            ["CA"],
            compensation_type="PERCENT_OF_GROSS",
            percent_of_gross=0.15,
            flat_fee_cents=0,
        )

        charity_side, charity_meta = validate_paginated(
            api_client.list_fundraising_contracts(
                COMPLIANCE, params={"organization_id": organization["id"]}
            )
        )
        firm_side, firm_meta = validate_paginated(
            api_client.list_fundraising_contracts(
                REGULATOR, params={"fundraiser_id": fundraiser["id"]}
            )
        )

        assert charity_meta["total_count"] == 1, (
            f"The charity has exactly one contract, got {charity_meta['total_count']}"
        )
        assert firm_meta["total_count"] == 1, (
            f"The firm has exactly one contract, got {firm_meta['total_count']}"
        )
        assert charity_side[0]["id"] == contract["id"] == firm_side[0]["id"], (
            "Both endpoints of the graph reach the same row, got "
            f"{charity_side[0]['id']} and {firm_side[0]['id']}"
        )
        assert charity_side[0]["status"] == "DRAFT", (
            f"A contract is created in DRAFT, got {charity_side[0]['status']}"
        )
        assert firm_side[0]["filing_due_date"] == "2026-08-11T00:00:00.000Z", (
            "An August 1 start plus California's ten filing days, got "
            f"{firm_side[0]['filing_due_date']}"
        )


class TestChildCollectionsAreScoped:
    """A charity's child collections belong to that charity and filter cleanly."""

    def _two_charities(self):
        seed_california_profile(
            disclosure_required_clauses=[
                "REGISTRATION_DISCLOSURE",
                "FINANCIAL_STATEMENT_AVAILABILITY",
            ]
        )
        seed_state_profile("NV", assurance_basis="GROSS_REVENUE")
        first = create_organization()
        second = create_organization(
            legal_name="Cedar Ridge Alliance",
            ein="223456789",
            domicile_state_code="NV",
            fiscal_year_end_month=12,
        )
        return first, second

    def test_activities_and_statements_narrow_to_one_state_and_one_fiscal_year(self):
        """PRD §3.1: "Organizations can be listed, optionally filtered by
        `domicile_state_code`, `lifecycle_status` or `solicitation_posture`, and each
        organization's solicitation activity, financial statements, officer
        disclosures and disclosure statements are all reachable as child collections
        of the organization." PRD §3.2: "An organization's statements can be listed,
        optionally narrowed to a single `fiscal_year`".

        Design: Corner/entities/organization_child_collections_are_scoped_and_filtered
        """
        first, second = self._two_charities()
        california_activity = create_solicitation_activity(
            first["id"], "CA", donor_count=40, contributions_cents=3_000_000
        )
        create_solicitation_activity(
            first["id"],
            "NV",
            donor_count=10,
            contributions_cents=400_000,
            channels=["EMAIL"],
        )
        create_financial_statement(
            first,
            fiscal_year=2025,
            total_revenue_cents=18_000_000,
            contributions_cents=15_000_000,
            assurance_level="NONE",
        )
        current_statement = create_financial_statement(first)

        charities, charity_meta = validate_paginated(
            api_client.list_organizations(
                COMPLIANCE, params={"domicile_state_code": "CA"}
            )
        )
        activities, activity_meta = validate_paginated(
            api_client.list_organization_solicitation_activities(
                first["id"], COMPLIANCE, params={"state_code": "CA"}
            )
        )
        statements, statement_meta = validate_paginated(
            api_client.list_organization_financial_statements(
                first["id"], COMPLIANCE, params={"fiscal_year": 2026}
            )
        )

        assert charity_meta["total_count"] == 1, (
            "Only one of the two charities is domiciled in California, got "
            f"{charity_meta['total_count']}"
        )
        assert charities[0]["id"] == first["id"]
        assert activity_meta["total_count"] == 1, (
            f"One of the two activity rows is Californian, got {activity_meta['total_count']}"
        )
        assert activities[0]["id"] == california_activity["id"]
        assert statement_meta["total_count"] == 1, (
            f"One statement covers fiscal 2026, got {statement_meta['total_count']}"
        )
        assert statements[0]["id"] == current_statement["id"]
        assert len(list_financial_statements(second["id"])) == 0, (
            "The second charity has no statements of its own"
        )

    def test_officers_narrow_to_the_certifying_flag_and_disclosures_to_one_state(self):
        """PRD §3.8: "An organization's officer roster can be listed, optionally
        narrowed by `is_certifying_officer`" and "Disclosure statements can be listed
        for an organization and narrowed by `state_code` or `material_type`."

        Design: Corner/entities/organization_child_collections_are_scoped_and_filtered
        """
        first, second = self._two_charities()
        certifier, _preparer = create_officer_pair(first["id"])
        disclosure = create_disclosure_statement(
            first["id"],
            "CA",
            included_clauses=[
                "REGISTRATION_DISCLOSURE",
                "FINANCIAL_STATEMENT_AVAILABILITY",
            ],
        )

        officers, officer_meta = validate_paginated(
            api_client.list_organization_officer_disclosures(
                first["id"], COMPLIANCE, params={"is_certifying_officer": "true"}
            )
        )
        disclosures, disclosure_meta = validate_paginated(
            api_client.list_organization_disclosure_statements(
                first["id"], COMPLIANCE, params={"state_code": "CA"}
            )
        )
        _others, other_meta = validate_paginated(
            api_client.list_organization_officer_disclosures(second["id"], COMPLIANCE)
        )

        assert officer_meta["total_count"] == 1, (
            f"Only the president certifies, got {officer_meta['total_count']}"
        )
        assert officers[0]["id"] == certifier["id"]
        assert disclosure_meta["total_count"] == 1, (
            f"One Californian disclosure statement, got {disclosure_meta['total_count']}"
        )
        assert disclosures[0]["id"] == disclosure["id"]
        assert disclosures[0]["compliance_status"] == "COMPLIANT", (
            "Both required clauses are present, got "
            f"{disclosures[0]['compliance_status']}"
        )
        assert other_meta["total_count"] == 0, (
            f"The second charity has no roster, got {other_meta['total_count']}"
        )


class TestExtensionHistoryCollection:
    """The extension history of one filing lists in order and narrows by status."""

    def test_a_second_request_supersedes_the_first_and_only_one_stays_pending(self):
        """PRD §3.5: "Every earlier request on the same `registration_id` in `PENDING`
        or in `GRANTED` transitions to `SUPERSEDED` with `decided_at` stamped at the
        current logical clock and its own `version` incremented. Superseding a
        `PENDING` request has no effect on the deadline, since none had been granted."
        PRD §3.5: "A filing's extension history can be listed in creation order and
        narrowed by `status`, which is how an examiner distinguishes a live grant from
        a superseded one."

        Design: Corner/entities/extension_request_collection_shows_the_supersede_chain
        """
        seed_california_profile()
        organization = create_organization()
        statement = create_financial_statement(organization)
        filing = open_filing(organization["id"], statement["id"], "CA")

        first = request_extension(filing["id"], filing["version"], "STATE_HARDSHIP", 45)
        reread = read_registration(filing["id"])
        second = request_extension(
            filing["id"], reread["version"], "IRS_990_EXTENSION", 180
        )

        history, history_meta = validate_paginated(
            api_client.list_registration_extension_requests(filing["id"], COMPLIANCE)
        )
        pending, pending_meta = validate_paginated(
            api_client.list_registration_extension_requests(
                filing["id"], COMPLIANCE, params={"status": "PENDING"}
            )
        )
        statuses = {row["id"]: row["status"] for row in history}

        assert history_meta["total_count"] == 2, (
            f"Both requests are kept as history, got {history_meta['total_count']}"
        )
        assert [row["id"] for row in history] == [first["id"], second["id"]], (
            f"The history lists in creation order, got {[row['id'] for row in history]}"
        )
        assert statuses[first["id"]] == "SUPERSEDED", (
            f"The earlier request was superseded, got {statuses[first['id']]}"
        )
        assert pending_meta["total_count"] == 1, (
            f"Only one request is still live, got {pending_meta['total_count']}"
        )
        assert pending[0]["id"] == second["id"], (
            f"The live request is the newer one, got {pending[0]['id']}"
        )
        assert pending[0]["granted_days"] == 0, (
            f"A pending request has granted nothing yet, got {pending[0]['granted_days']}"
        )
        assert pending[0]["decided_at"] is None, (
            f"A pending request is undecided, got {pending[0]['decided_at']}"
        )
        assert read_registration(filing["id"])["effective_due_date"] == filing[
            "renewal_due_date"
        ], "Superseding a pending request leaves the deadline where it was"


class TestSweptActionAndDocumentViews:
    """What the sweep wrote is what the detail read and the document list show."""

    def test_the_sweeps_notice_reads_back_identically_from_the_list_and_the_detail(self):
        """PRD §3.9: "Enforcement actions can be listed filtered by
        `organization_id`, `registration_id`, `state_code`, `action_type` or `status`,
        and read individually."

        Design: Corner/entities/swept_action_detail_and_document_list_reflect_the_sweep
        """
        ctx = setup_delinquent_filing(sweep_at="2026-11-15T00:00:00Z")
        registration_id = ctx["registration"]["id"]

        listed, meta = validate_paginated(
            api_client.list_enforcement_actions(
                REGULATOR, params={"registration_id": registration_id}
            )
        )
        detail = validate_success(
            api_client.get_enforcement_action(listed[0]["id"], REGULATOR)
        )

        assert meta["total_count"] == 1, (
            f"The sweep raised exactly one action, got {meta['total_count']}"
        )
        assert detail == listed[0], (
            "The detail read and the list row are the same representation"
        )
        assert detail["action_type"] == "DELINQUENCY_NOTICE", (
            f"A sweep raises a delinquency notice, got {detail['action_type']}"
        )
        assert detail["status"] == "OPEN", (
            f"The notice is born OPEN, got {detail['status']}"
        )
        assert detail["penalty_cents"] == 2_004, (
            f"One day late is one accrual month at the base, got {detail['penalty_cents']}"
        )
        assert detail["cure_deadline"] == "2026-12-15T00:00:00.000Z", (
            f"The sweep clock plus thirty whole days, got {detail['cure_deadline']}"
        )
        assert detail["state_code"] == "CA", (
            f"The state is the filing's own, got {detail['state_code']}"
        )

    def test_the_document_list_narrows_to_one_doc_type_of_the_swept_filing(self):
        """PRD §2.9: "a dangling `registration_id` or `supersedes_registration_id`
        reports `ERR_REGISTRATION_NOT_FOUND`". PRD §3.4: an `APPROVE` decision "sets
        `review_status` to `ACCEPTED` on every document of the filing".

        Design: Corner/entities/swept_action_detail_and_document_list_reflect_the_sweep
        """
        ctx = setup_delinquent_filing(sweep_at="2026-11-15T00:00:00Z")
        registration_id = ctx["registration"]["id"]

        reports, report_meta = validate_paginated(
            api_client.list_registration_documents(
                COMPLIANCE,
                params={
                    "registration_id": registration_id,
                    "doc_type": "REVIEW_REPORT",
                },
            )
        )

        assert report_meta["total_count"] == 1, (
            f"One review report is attached, got {report_meta['total_count']}"
        )
        assert reports[0]["review_status"] == "ACCEPTED", (
            "The approval accepted every document and the sweep did not undo it, got "
            f"{reports[0]['review_status']}"
        )
        assert read_registration(registration_id)["status"] == "DELINQUENT", (
            "The filing itself was swept into delinquency"
        )
        assert read_organization(ctx["organization"]["id"])[
            "penalty_outstanding_cents"
        ] == 2_004, "The notice's penalty is on the charity's ledger"


class TestFundraiserSideReads:
    """The firm's own agent sees its registrations and its contract."""

    def _firm_with_a_filed_contract(self):
        seed_california_profile()
        organization = create_organization()
        ctx = setup_filed_contract(
            organization["id"],
            ["CA"],
            fundraiser_overrides={
                "legal_name": "Northline Donor Services",
                "bond_amount_cents": 2_500_000,
                "bond_expires_at": "2028-12-31T00:00:00Z",
            },
            contract_overrides={
                "compensation_type": "PERCENT_OF_GROSS",
                "percent_of_gross": 0.15,
                "flat_fee_cents": 0,
            },
        )
        ctx["organization"] = organization
        return ctx

    def test_the_firms_agent_reads_its_own_state_registrations_and_its_contract(self):
        """PRD §3.6: "A firm's registrations can be listed for that firm and narrowed
        by `state_code` or `status`." PRD §2.1: "A `FundraiserAgent` acts for a single
        `ProfessionalFundraiser` and may only see and act on that firm's own
        registrations and contracts."

        Design: Corner/entities/fundraiser_side_reads_return_registrations_contract_and_promotion
        """
        ctx = self._firm_with_a_filed_contract()
        fundraiser_id = ctx["fundraiser"]["id"]
        agent = make_fundraiser_agent_headers(fundraiser_id)

        registrations, meta = validate_paginated(
            api_client.list_fundraiser_registrations(
                fundraiser_id, agent, params={"state_code": "CA"}
            )
        )
        contract = validate_success(
            api_client.get_fundraising_contract(ctx["contract"]["id"], agent)
        )

        assert meta["total_count"] == 1, (
            f"The firm is registered in one state, got {meta['total_count']}"
        )
        assert registrations[0]["state_code"] == "CA"
        assert registrations[0]["status"] == "ACTIVE", (
            f"A registration with a sufficient bond is ACTIVE, got {registrations[0]['status']}"
        )
        assert contract["id"] == ctx["contract"]["id"]
        assert contract["status"] == "FILED", (
            f"The contract was filed by this same agent, got {contract['status']}"
        )
        assert contract["filing_due_date"] == "2026-08-11T00:00:00.000Z", (
            "An August 1 start plus ten filing days, got "
            f"{contract['filing_due_date']}"
        )
        assert contract["fundraiser_id"] == fundraiser_id

    def test_the_charitys_promotion_is_listed_by_organization_and_read_by_id(self):
        """PRD §3.7: "Promotions can be listed filtered by `organization_id`,
        `coventurer_id`, `state_code` or `status`, and read individually." PRD §3.7:
        "`projected_benefit_cents` is the forward-looking benefit estimate: the larger
        of `guaranteed_minimum_cents` and the product of `per_unit_cents` and
        `projected_units`."

        Design: Corner/entities/fundraiser_side_reads_return_registrations_contract_and_promotion
        """
        ctx = self._firm_with_a_filed_contract()
        coventurer = create_fundraiser(
            legal_name="BrightMart Retail Co",
            fundraiser_type="COMMERCIAL_COVENTURER",
            bond_amount_cents=2_500_000,
            bond_expires_at="2028-12-31T00:00:00Z",
        )
        register_fundraiser_in_state(coventurer["id"], "CA")
        promotion = draft_promotion(
            ctx["organization"]["id"], coventurer["id"], ["CA"]
        )

        promotions, meta = validate_paginated(
            api_client.list_coventure_promotions(
                COMPLIANCE, params={"organization_id": ctx["organization"]["id"]}
            )
        )
        detail = validate_success(
            api_client.get_coventure_promotion(promotion["id"], COMPLIANCE)
        )

        assert meta["total_count"] == 1, (
            f"The charity is running one campaign, got {meta['total_count']}"
        )
        assert promotions[0]["id"] == promotion["id"]
        assert promotions[0]["projected_benefit_cents"] == 750_000, (
            "250 per unit across 3,000 projected units, got "
            f"{promotions[0]['projected_benefit_cents']}"
        )
        assert detail["status"] == "DRAFT", (
            f"The campaign has not been filed yet, got {detail['status']}"
        )
        assert detail["coventurer_id"] == coventurer["id"], (
            f"The commercial partner is recorded, got {detail['coventurer_id']}"
        )
        assert detail["final_benefit_cents"] == 0, (
            f"Nothing has been settled yet, got {detail['final_benefit_cents']}"
        )
