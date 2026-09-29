"""Resource contracts: field sets, envelopes, defaults, 404 families and shape.

PRD §2.2: "The `response_type` is either "object" for a single resource or
"array" for a list of resources."
"""
import pytest
from test_helpers import (
    assert_same_instant,
    ApiErrorId,
    api_client,
    assert_beneficial_use_record,
    assert_error_envelope,
    assert_request_meta,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    create_deposit_payload,
    ANALYST,
    DECIDER,
    HEARING_OFFICER,
    add_point_of_diversion,
    create_claimant,
    create_water_right,
    create_water_right_payload,
    draft_application,
    make_claimant_headers,
    read_account,
    read_right,
    reserve_lease,
    set_clock,
    setup_authorized_headgate_account,
    setup_base_right,
    setup_certified_right,
    setup_documented_right,
)

CLOCK = "2026-03-01T00:00:00Z"
MISSING_RIGHT = "00000000-0000-0000-0000-0000000000aa"
MISSING_CLAIMANT = "00000000-0000-0000-0000-0000000000bb"
MISSING_POD = "00000000-0000-0000-0000-0000000000cc"
MISSING_STUDY = "00000000-0000-0000-0000-0000000000dd"


class TestWaterRightCreationAndRetrieval:
    """PRD §3.1 — the documented shape of a newly filed right."""

    def test_creation_returns_the_whole_declared_field_set(self):
        """PRD §3.1: "A new right lands in `UNADJUDICATED` with all four volume
        buckets at 0.00, so nothing is transferable until a consumptive-use study
        has been certified, and its forfeiture assessment is run immediately so that
        `forfeiture_risk_score` and `forfeiture_risk_band` are populated from
        birth."

        PRD §2.5: "Every persisted resource carries an `id` that is a server-minted
        UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC form with
        three fractional digits." The eight input fields come back verbatim alongside
        them, and
        the row is stamped from the logical clock rather than from wall time.

        Design: Corner/entities/entity_creation_water_right_returns_declared_field_set
        """
        set_clock(CLOCK)
        claimant = create_claimant()

        right = validate_success(
            api_client.create_water_right(
                create_water_right_payload(claimant["id"]), ANALYST
            ),
            expected_status=201,
        )

        assert right["claimant_id"] == claimant["id"]
        assert right["right_number"] == "WR-2198-001"
        assert right["priority_date"] == "1901-05-01T00:00:00Z"
        assert right["source_stream_code"] == "SNK-14"
        assert right["purpose_of_use"] == "IRRIGATION"
        assert right["place_of_use_acres"] == pytest.approx(120.00, abs=0.01)
        assert right["authorized_diversion_af"] == pytest.approx(400.00, abs=0.01)
        assert right["authorized_rate_cfs"] == pytest.approx(5.000, abs=0.0005)
        assert right["status"] == "UNADJUDICATED"
        assert right["certified_hcu_af"] == pytest.approx(0.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(0.00, abs=0.01)
        # PRD §3.1 requires only that the assessment "is run immediately so that
        # `forfeiture_risk_score` and `forfeiture_risk_band` are populated from
        # birth"; PRD §3.2's formula fixes what those values are. At the 2026
        # clock the window is 2016 through 2025 with no record in it, so all ten
        # years are non-use: 10 x 9 = 90 for the run, plus 30 x (1 - 0) = 30 for
        # zero utilization, with no unverified ratio, no suspension penalty and
        # no meter credit. The raw 120 is "clamped into the range zero through
        # one hundred", and 100.00 is "70.00 or above", so the band reads HIGH.
        assert right["forfeiture_risk_score"] == pytest.approx(100.00, abs=0.01)
        assert right["forfeiture_risk_band"] == "HIGH"
        assert right["consecutive_nonuse_years"] == 10
        assert right["pending_review_count"] == 0
        assert is_valid_uuid(right["id"])
        assert_same_instant(right["created_at"], CLOCK, "created_at")
        assert_same_instant(right["updated_at"], CLOCK, "updated_at")
        assert right["version"] == 1

    def test_retrieval_reads_back_the_stored_row_unchanged(self):
        """PRD §3.1: "Retrieving a single right returns its full four-bucket ledger
        together with its risk figures."

        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
        the request that starts with `req_`." Reading the right back as a different
        role returns the same values the write returned.

        Design: Corner/entities/entity_retrieval_water_right_reads_back_stored_row
        """
        bundle = setup_documented_right(CLOCK)

        response = api_client.get_water_right(bundle["right"]["id"], DECIDER)

        body = response.json()
        assert response.status_code == 200
        assert_request_meta(body)
        assert body["response_type"] == "object"
        right = body["data"]
        assert right["id"] == bundle["right"]["id"]
        assert right["right_number"] == "WR-2198-001"
        assert right["authorized_diversion_af"] == pytest.approx(400.00, abs=0.01)
        assert right["authorized_rate_cfs"] == pytest.approx(5.000, abs=0.0005)
        assert right["status"] == "UNADJUDICATED"
        assert right["version"] == 1


class TestListEnvelopeAndPagination:
    """PRD §2.3 — "Every list response reports `limit`, `offset`, `total_count` and
    `has_more` inside `meta`."
    """

    def test_pagination_walks_three_rights_two_at_a_time(self):
        """PRD §2.3: "List endpoints accept `limit` and `offset` as query
        parameters."

        Three rights exist for one claimant. A first page of two reports
        `total_count` 3 with `has_more` true, and the second page returns the single
        remaining row with `has_more` false. A `status` filter of `ACTIVE` composes
        with the count: PRD §3.1 — "Rights can be listed with optional filters on
        `claimant_id`, on `status`, and on `forfeiture_risk_band`" — and none of the
        three has been perfected.

        Design: Corner/entities/entity_listing_water_rights_paginated_array_envelope
        """
        set_clock(CLOCK)
        claimant = create_claimant()
        create_water_right(claimant["id"])
        create_water_right(
            claimant["id"],
            right_number="WR-2198-002",
            priority_date="1912-06-01T00:00:00Z",
            purpose_of_use="MUNICIPAL",
            place_of_use_acres=0.00,
            authorized_diversion_af=250.00,
            authorized_rate_cfs=3.000,
        )
        create_water_right(
            claimant["id"],
            right_number="WR-2198-003",
            priority_date="1930-04-15T00:00:00Z",
            source_stream_code="SNK-22",
            purpose_of_use="STOCKWATER",
            place_of_use_acres=5.00,
            authorized_diversion_af=10.00,
            authorized_rate_cfs=0.500,
        )

        first_page, first_meta = validate_paginated(
            api_client.list_water_rights(
                HEARING_OFFICER,
                params={"claimant_id": claimant["id"], "limit": 2, "offset": 0},
            )
        )
        second_page, second_meta = validate_paginated(
            api_client.list_water_rights(
                HEARING_OFFICER,
                params={"claimant_id": claimant["id"], "limit": 2, "offset": 2},
            )
        )
        filtered, filtered_meta = validate_paginated(
            api_client.list_water_rights(HEARING_OFFICER, params={"status": "ACTIVE"})
        )

        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["has_more"] is False
        assert second_meta["offset"] == 2
        assert len(filtered) == 0
        assert filtered_meta["total_count"] == 0
        assert filtered_meta["has_more"] is False

    def test_omitted_pagination_params_take_the_declared_defaults(self):
        """PRD §2.3: "`limit` defaults to 10 when omitted, with a minimum of 1 and
        a maximum of 100; `offset` defaults to 0 and may not be negative."

        Twelve drafts exist on one certified right — PRD §3.4: "No volume is
        escrowed, `escrowed_af` reads 0.00, and no bucket on the right has moved" —
        so the volume budget never limits how many can be filed. An unparameterised
        listing returns ten of them.

        Design: Corner/entities/entity_listing_default_pagination_when_params_omitted
        """
        bundle = setup_certified_right()
        for _ in range(12):
            draft_application(bundle["right"]["id"], bundle["study"]["id"], 1.00)

        listed, meta = validate_paginated(
            api_client.list_transfer_applications(
                DECIDER, params={"water_right_id": bundle["right"]["id"]}
            )
        )

        assert len(listed) == 10
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 12
        assert meta["has_more"] is True


class TestDeclaredDefaultsAndDerivedFields:
    """PRD §2.5 — optional inputs, server-stamped audit fields and derived
    counters are three separate categories of field."""

    def test_omitted_optional_inputs_take_their_declared_defaults(self):
        """PRD §3.1: "and an optional `bank_enrolled` flag that defaults to false."

        PRD §3.5: "an optional `return_flow_credit_af` of zero or more at 2 decimal
        places that defaults to 0.00 when omitted". Neither field is supplied, so a `SEASONAL_AVERAGE` analysis of a
        100.00 AF request grosses 78.00 and nets exactly the same 78.00 — the two
        figures can only coincide because both deductions defaulted to zero.

        Design: Corner/entities/entity_defaults_omitted_optional_inputs_take_declared_defaults
        """
        bundle = setup_certified_right()
        application = draft_application(
            bundle["right"]["id"], bundle["study"]["id"], 100.00
        )

        right = read_right(bundle["right"]["id"])
        analysis = get_success_data(
            api_client.create_injury_analysis(
                application["id"],
                {"method": "SEASONAL_AVERAGE", "pod_move_miles": 0.00},
                ANALYST,
            )
        )

        assert right["bank_enrolled"] is False
        assert analysis["return_flow_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["offset_af"] == pytest.approx(0.00, abs=0.01)
        assert analysis["status"] == "DRAFT"
        assert analysis["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert analysis["net_injury_af"] == pytest.approx(78.00, abs=0.01)
        assert application["status"] == "DRAFT"
        assert application["revision_round"] == 0
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert application["protest_deadline"] is None
        assert application["unresolved_protest_count"] == 0
        assert application["mitigation_fee_total_usd"] == pytest.approx(0.00, abs=0.01)

    def test_audit_fields_come_from_the_caller_and_from_the_transition(self):
        """PRD §2.1: "The server records it where a transition writes it — as
        `reported_by_user_id` on a `BeneficialUseRecord`, as `certified_by_user_id`
        on an `HcuStudy` ... but never compares it to any entity's `id`."

        PRD §3.1: "The service stamps `reported_by_user_id` with the calling operator
        identifier", so a record filed by the claimant carries the claimant's own
        id. PRD §3.3 quantifies a study at creation, so the `DRAFT` row already
        reports 195.000 while `certified_by_user_id` and `certified_at` are still
        null.

        Design: Corner/entities/entity_system_fields_are_server_stamped_and_input_ignored
        """
        bundle = setup_base_right(clock=CLOCK, use_years=(2023, 2024))
        claimant_id = bundle["claimant"]["id"]

        record = validate_success(
            api_client.create_beneficial_use_record(
                bundle["right"]["id"],
                {
                    "use_year": 2025,
                    "reported_diversion_af": 300.000,
                    "irrigated_acres": 100.00,
                    "verification_source": "METER",
                },
                make_claimant_headers(claimant_id),
            ),
            expected_status=201,
        )
        study = get_success_data(
            api_client.create_hcu_study(
                bundle["right"]["id"],
                {
                    "method": "DIVERSION_BASED",
                    "study_period_start_year": 2023,
                    "study_period_end_year": 2025,
                },
                ANALYST,
            )
        )

        assert record["reported_by_user_id"] == claimant_id
        assert is_valid_uuid(record["id"])
        assert_same_instant(record["created_at"], CLOCK, "created_at")
        assert study["status"] == "DRAFT"
        assert study["certified_by_user_id"] is None
        assert study["certified_at"] is None
        assert study["qualifying_year_count"] == 3
        assert study["average_annual_cu_af"] == pytest.approx(195.000, abs=0.0005)
        assert study["transferable_cu_af"] == pytest.approx(195.00, abs=0.01)

    def test_claimant_counters_are_derived_from_the_application_set(self):
        """PRD §3.1: "`open_application_count` is the number of transfer applications
        on this claimant's rights whose status is one of `DRAFT`, `SUBMITTED`,
        `PROTEST_PERIOD`, `UNDER_PROTEST`, `REVISION_REQUESTED` or
        `READY_FOR_DECISION`."

        PRD §3.4: submission is the moment the counter has something to count —
        "On the right, `encumbered_af` increases by that same amount and
        `transferable_af` decreases by it". No condition has been priced, so
        `outstanding_fee_balance_usd` never leaves 0.00.

        Design: Corner/entities/entity_computed_fields_claimant_counters_are_derived_not_input
        """
        bundle = setup_certified_right()
        application = draft_application(
            bundle["right"]["id"], bundle["study"]["id"], 100.00
        )

        before = get_success_data(
            api_client.get_claimant(bundle["claimant"]["id"], ANALYST)
        )
        get_success_data(
            api_client.submit_transfer_application(
                application["id"], read_right(bundle["right"]["id"])["version"], ANALYST
            )
        )
        after = get_success_data(
            api_client.get_claimant(bundle["claimant"]["id"], ANALYST)
        )

        assert before["open_application_count"] == 1
        assert before["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert before["standing_status"] == "IN_GOOD_STANDING"
        assert after["open_application_count"] == 1
        assert after["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"


class TestResourceNotFoundFamilies:
    """PRD §2.4 — "Path parameters are resolved strictly left to right, and the
    error returned belongs to the leftmost segment that fails to resolve."
    """

    def test_documentation_resources_each_report_their_own_missing_code(self):
        """PRD §2.4: "The parallel existence codes are `ERR_CLAIMANT_NOT_FOUND`,
        `ERR_POINT_OF_DIVERSION_NOT_FOUND`, `ERR_HCU_STUDY_NOT_FOUND` ... each at
        HTTP 404."

        PRD §2.4: "Foreign keys supplied in a request body are resolved with the
        same rigour ... and a body foreign key that does not resolve yields the
        corresponding not-found code at HTTP 404." One claimant and one right
        already exist, so none of these answers can be an artefact of an empty
        table, and the refused creation leaves the right count at one.

        Design: Corner/entities/entity_not_found_documentation_family_returns_404
        """
        set_clock(CLOCK)
        claimant = create_claimant()
        create_water_right(claimant["id"])

        right_404 = api_client.get_water_right(MISSING_RIGHT, ANALYST)
        claimant_404 = api_client.get_claimant(MISSING_CLAIMANT, ANALYST)
        pod_404 = api_client.get_point_of_diversion(MISSING_POD, ANALYST)
        study_404 = api_client.get_hcu_study(MISSING_STUDY, ANALYST)
        body_fk_404 = api_client.create_water_right(
            create_water_right_payload(MISSING_CLAIMANT, right_number="WR-2198-999"),
            ANALYST,
        )

        error = validate_error(
            right_404, ApiErrorId.ERR_WATER_RIGHT_NOT_FOUND.value, expected_status=404
        )
        assert_error_envelope(error)
        assert right_404.json()["response_type"] == "error"
        validate_error(
            claimant_404, ApiErrorId.ERR_CLAIMANT_NOT_FOUND.value, expected_status=404
        )
        validate_error(
            pod_404,
            ApiErrorId.ERR_POINT_OF_DIVERSION_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            study_404, ApiErrorId.ERR_HCU_STUDY_NOT_FOUND.value, expected_status=404
        )
        validate_error(
            body_fk_404, ApiErrorId.ERR_CLAIMANT_NOT_FOUND.value, expected_status=404
        )
        _rights, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 1

    def test_transfer_phase_resources_each_report_their_own_missing_code(self):
        """PRD §2.4: "The parallel existence codes are ...
        `ERR_TRANSFER_APPLICATION_NOT_FOUND`, `ERR_INJURY_ANALYSIS_NOT_FOUND`,
        `ERR_PROTEST_NOT_FOUND`, `ERR_APPROVAL_CONDITION_NOT_FOUND` ... each at HTTP
        404."

        Injury analyses and approval conditions only ever exist as children of an
        application, yet PRD §2.6 gives each of them its own top-level read path, so
        each answers with its own code rather than with the parent's.

        Design: Corner/entities/entity_not_found_transfer_family_returns_404
        """
        set_clock(CLOCK)

        responses = {
            ApiErrorId.ERR_TRANSFER_APPLICATION_NOT_FOUND: api_client.get_transfer_application(
                "00000000-0000-0000-0000-0000000000a1", HEARING_OFFICER
            ),
            ApiErrorId.ERR_INJURY_ANALYSIS_NOT_FOUND: api_client.get_injury_analysis(
                "00000000-0000-0000-0000-0000000000a2", HEARING_OFFICER
            ),
            ApiErrorId.ERR_PROTEST_NOT_FOUND: api_client.get_protest(
                "00000000-0000-0000-0000-0000000000a3", HEARING_OFFICER
            ),
            ApiErrorId.ERR_APPROVAL_CONDITION_NOT_FOUND: api_client.get_approval_condition(
                "00000000-0000-0000-0000-0000000000a4", HEARING_OFFICER
            ),
        }

        for expected, response in responses.items():
            error = validate_error(response, expected.value, expected_status=404)
            assert_error_envelope(error)
            assert response.json()["response_type"] == "error"
            assert error["message"].strip() != ""

    def test_banking_paths_resolve_before_any_body_foreign_key(self):
        """PRD §2.4: "A request naming a right that does not exist fails with
        `ERR_WATER_RIGHT_NOT_FOUND` (HTTP 404) before anything nested beneath that
        right is examined."

        The four banking and adjudication reads each answer with their own code, and
        a deposit posted into an unknown account whose body also names an unknown
        `water_right_id` reports the account: the path segment is resolved first, so
        neither the body foreign key nor the version precondition of PRD §2.7 is
        ever reached.

        Design: Corner/entities/entity_not_found_banking_and_adjudication_family_returns_404
        """
        set_clock(CLOCK)
        missing_account = "00000000-0000-0000-0000-0000000000b1"

        account_404 = api_client.get_water_bank_account(missing_account, ADJUDICATOR)
        lease_404 = api_client.get_lease_assignment(
            "00000000-0000-0000-0000-0000000000b2", ADJUDICATOR
        )
        docket_404 = api_client.get_decree_docket(
            "00000000-0000-0000-0000-0000000000b3", ADJUDICATOR
        )
        claim_404 = api_client.get_adjudication_claim(
            "00000000-0000-0000-0000-0000000000b4", ADJUDICATOR
        )
        deposit_404 = api_client.create_deposit(
            missing_account,
            create_deposit_payload(
                "00000000-0000-0000-0000-0000000000b5", 10.00, 1
            ),
            ADJUDICATOR,
        )

        validate_error(
            account_404,
            ApiErrorId.ERR_WATER_BANK_ACCOUNT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            lease_404,
            ApiErrorId.ERR_LEASE_ASSIGNMENT_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            docket_404,
            ApiErrorId.ERR_DECREE_DOCKET_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            claim_404,
            ApiErrorId.ERR_ADJUDICATION_CLAIM_NOT_FOUND.value,
            expected_status=404,
        )
        validate_error(
            deposit_404,
            ApiErrorId.ERR_WATER_BANK_ACCOUNT_NOT_FOUND.value,
            expected_status=404,
        )


class TestRequestShapeConstraints:
    """PRD §2.11 — "request-body well-formedness (`ERR_INVALID_REQUEST`)" sits above
    every business rule, so a malformed payload never reaches the domain.
    """

    def test_mandatory_and_field_level_input_rules_are_both_enforced(self):
        """PRD §3.1: "The payload names the `claimant_id` of the holder of record, a
        `right_number` of 1 to 40 characters ... the `priority_date` established by
        first beneficial use".

        PRD §3.1: a claimant registration "takes a `legal_name` of 1 to 160
        non-blank characters, a `contact_email` that must contain an at-sign because
        it is the notice address to which protests and decisions are served, and an
        `entity_type` drawn from `INDIVIDUAL`, `IRRIGATION_DISTRICT`, `MUNICIPALITY`
        and `TRIBE`." Presence and the field-level constraint are the same rule, so
        an address without an at-sign is refused exactly like an absent
        `entity_type`, and nothing is persisted by any of the three attempts.

        Design: Corner/entities/entity_required_fields_missing_inputs_rejected
        """
        set_clock(CLOCK)
        claimant = create_claimant()
        no_priority_date = create_water_right_payload(claimant["id"])
        del no_priority_date["priority_date"]

        missing_date = api_client.create_water_right(no_priority_date, ANALYST)
        missing_entity_type = api_client.create_claimant(
            {"legal_name": "Rill Farms", "contact_email": "rill@example.test"}, ANALYST
        )
        bad_email = api_client.create_claimant(
            {
                "legal_name": "Rill Farms",
                "contact_email": "rill-at-example",
                "entity_type": "INDIVIDUAL",
            },
            ANALYST,
        )

        for response in (missing_date, missing_entity_type, bad_email):
            validate_error(
                response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
            )
        _rights, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 0
        assert (
            get_success_data(api_client.get_claimant(claimant["id"], ANALYST))["id"]
            == claimant["id"]
        )

    def test_enum_membership_and_numeric_ranges_are_enforced(self):
        """PRD §3.1: "a `purpose_of_use` drawn from `IRRIGATION`, `MUNICIPAL`,
        `STOCKWATER`, `INDUSTRIAL` and `INSTREAM_FLOW` ... an
        `authorized_diversion_af` face-value annual limit strictly greater than
        zero".

        PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a
        negative `offset`, is rejected with `ERR_INVALID_REQUEST` (HTTP 400)." All
        four defects are body- or query-shape defects, and none of them creates a
        row.

        Design: Corner/entities/entity_type_constraints_enum_and_range_violations_rejected
        """
        set_clock(CLOCK)
        claimant = create_claimant()

        bad_enum = api_client.create_water_right(
            create_water_right_payload(claimant["id"], purpose_of_use="RECREATION"),
            ANALYST,
        )
        zero_volume = api_client.create_water_right(
            create_water_right_payload(
                claimant["id"],
                right_number="WR-2198-002",
                authorized_diversion_af=0.00,
            ),
            ANALYST,
        )
        limit_too_large = api_client.list_water_rights(
            ANALYST, params={"limit": 101, "offset": 0}
        )
        negative_offset = api_client.list_water_rights(
            ANALYST, params={"limit": 10, "offset": -1}
        )

        for response in (bad_enum, zero_volume, limit_too_large, negative_offset):
            validate_error(
                response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
            )
        _rights, meta = validate_paginated(api_client.list_water_rights(ANALYST))
        assert meta["total_count"] == 0

    def test_the_two_window_constraints_share_a_code_but_not_a_strictness(self):
        """PRD §3.3: "A study declares a `method` ... and a study period given as
        `study_period_start_year` and `study_period_end_year`, both inclusive
        calendar years, with the end year at least equal to the start year. An end
        year earlier than the start year is `ERR_INVALID_WINDOW` (HTTP 422)."

        PRD §3.9: the lease payload carries "`lease_start_date`, a `lease_end_date`
        strictly after it", and PRD §3.9 prices a malformed window as
        `ERR_INVALID_WINDOW` too — "The window must be well-formed, otherwise
        `ERR_INVALID_WINDOW` (422)." So equality is legal for a study period and
        illegal for a lease window, under one error id. The accepted single-year
        study takes the PRD §3.3 haircut because "the comparison is strict, so
        exactly three qualifying years takes no haircut while two years does".

        Design: Corner/entities/entity_type_constraints_inverted_windows_rejected
        """
        bundle = setup_authorized_headgate_account(deposit_af=90.00)

        inverted_study = api_client.create_hcu_study(
            bundle["right"]["id"],
            {
                "method": "DIVERSION_BASED",
                "study_period_start_year": 2025,
                "study_period_end_year": 2024,
            },
            ANALYST,
        )
        empty_lease_window = reserve_lease(
            bundle["account"]["id"],
            bundle["right"]["id"],
            bundle["pod"]["id"],
            "2026-05-01T00:00:00Z",
            "2026-05-01T00:00:00Z",
            10.00,
        )
        single_year_study = api_client.create_hcu_study(
            bundle["right"]["id"],
            {
                "method": "DIVERSION_BASED",
                "study_period_start_year": 2025,
                "study_period_end_year": 2025,
            },
            ANALYST,
        )

        validate_error(
            inverted_study, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422
        )
        validate_error(
            empty_lease_window, ApiErrorId.ERR_INVALID_WINDOW.value, expected_status=422
        )
        leases, lease_meta = validate_paginated(
            api_client.list_lease_assignments(
                ANALYST, params={"water_right_id": bundle["right"]["id"]}
            )
        )
        assert leases == []
        assert lease_meta["total_count"] == 0
        assert read_account(bundle["account"]["id"])[
            "available_credit_af"
        ] == pytest.approx(90.00, abs=0.01)
        study = get_success_data(single_year_study, expected_status=201)
        assert study["qualifying_year_count"] == 1
        assert study["average_annual_cu_af"] == pytest.approx(195.000, abs=0.0005)
        assert study["short_history_haircut_applied"] is True
        assert study["transferable_cu_af"] == pytest.approx(165.75, abs=0.01)


class TestOwnershipAndGraphTopology:
    """PRD §2.1 — "water rights, transfer applications, protests, approval
    conditions, water bank accounts, lease assignments, decree dockets and
    adjudication claims are all addressed directly, and only beneficial-use records,
    consumptive-use studies, points of diversion, injury analyses and an
    application's approval-condition listing are reached through a parent path."
    """

    def test_use_records_are_an_append_only_evidence_ledger(self):
        """PRD §3.1: "Annual beneficial use is reported into an append-only evidence
        ledger, and claimants may file their own reports alongside analysts and the
        adjudicator."

        The record is the one entity with no revisable surface: PRD §2.5 gives most
        rows an `updated_at` and a `version`, but this ledger row carries neither,
        and PRD §3.1 offers no revision route — "Only one record may exist per right
        per calendar year" — so a correction can only ever be another year's row.
        PRD §3.1: "Records beneath a right can be listed with optional
        `use_year_from` and `use_year_to` bounds."

        Design: Corner/entities/entity_immutability_beneficial_use_record_cannot_be_updated
        """
        set_clock(CLOCK)
        claimant = create_claimant()
        right = create_water_right(claimant["id"])

        record = validate_success(
            api_client.create_beneficial_use_record(
                right["id"],
                {
                    "use_year": 2024,
                    "reported_diversion_af": 300.000,
                    "irrigated_acres": 100.00,
                    "verification_source": "METER",
                },
                ANALYST,
            ),
            expected_status=201,
        )

        assert_beneficial_use_record(record)
        assert record["water_right_id"] == right["id"]
        assert record["use_year"] == 2024
        assert record["reported_diversion_af"] == pytest.approx(300.000, abs=0.0005)
        assert record["irrigated_acres"] == pytest.approx(100.00, abs=0.01)
        assert record["verification_source"] == "METER"
        assert is_iso8601_timestamp(record["created_at"])
        listed, meta = validate_paginated(
            api_client.list_beneficial_use_records(
                right["id"], ANALYST, params={"use_year_from": 2024, "use_year_to": 2024}
            )
        )
        assert meta["total_count"] == 1
        assert listed[0]["id"] == record["id"]

    def test_a_headgate_belongs_to_exactly_one_right(self):
        """PRD §3.1: "A headgate is registered beneath its right as a point of
        diversion."

        PRD §2.4: "A request naming a right that does not exist fails with
        `ERR_WATER_RIGHT_NOT_FOUND` (HTTP 404) before anything nested beneath that
        right is examined", so an orphan headgate is never created. The two rights
        share one claimant and one stream, yet the headgate registered under the
        first never appears beneath the second. PRD §3.1: "A new headgate always
        starts in `PROPOSED` ... Points of diversion beneath a right can be listed
        with an optional `status` filter."

        Design: Corner/entities/entity_parent_relationship_pod_is_scoped_to_its_water_right
        """
        set_clock(CLOCK)
        claimant = create_claimant()
        first = create_water_right(claimant["id"])
        second = create_water_right(
            claimant["id"],
            right_number="WR-2198-002",
            priority_date="1912-06-01T00:00:00Z",
            place_of_use_acres=60.00,
            authorized_diversion_af=200.00,
            authorized_rate_cfs=2.500,
        )
        headgate = add_point_of_diversion(first["id"])

        orphan = api_client.create_point_of_diversion(
            MISSING_RIGHT,
            {
                "legal_description": "orphan headgate",
                "stream_reach_code": "SNK-14-Z",
                "max_rate_cfs": 1.000,
                "stream_miles_from_headwater": 10.00,
            },
            ANALYST,
        )

        validate_error(
            orphan, ApiErrorId.ERR_WATER_RIGHT_NOT_FOUND.value, expected_status=404
        )
        empty, empty_meta = validate_paginated(
            api_client.list_points_of_diversion(second["id"], ANALYST)
        )
        assert empty == []
        assert empty_meta["total_count"] == 0
        owned, owned_meta = validate_paginated(
            api_client.list_points_of_diversion(
                first["id"], ANALYST, params={"status": "PROPOSED"}
            )
        )
        assert owned_meta["total_count"] == 1
        assert owned[0]["id"] == headgate["id"]
        assert owned[0]["water_right_id"] == first["id"]
        assert owned[0]["status"] == "PROPOSED"

    def test_a_lease_is_reachable_from_each_of_its_three_parents(self):
        """PRD §3.9: "Leases can be listed by all five roles with optional filters on
        `water_bank_account_id`, `water_right_id`, `point_of_diversion_id` and `status`,
        and a single lease can be read to inspect its settlement figures and suspension
        history."

        A lease is the junction of an account, a right and a headgate, so the single
        reserved row answers to all three foreign-key filters. The `status` filter
        composes with them rather than replacing them: PRD §3.9 — "The lease is
        created in `RESERVED`, `committed_credit_af` increases and
        `available_credit_af` decreases by `requested_af`" — so a filter on `ACTIVE`
        finds nothing.

        Design: Corner/entities/entity_graph_topology_lease_is_a_three_parent_junction
        """
        bundle = setup_authorized_headgate_account(deposit_af=90.00)
        lease = get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                bundle["right"]["id"],
                bundle["pod"]["id"],
                "2026-04-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                20.00,
                diversion_rate_cfs=1.000,
            )
        )

        for param in ("water_bank_account_id", "water_right_id", "point_of_diversion_id"):
            key = {
                "water_bank_account_id": bundle["account"]["id"],
                "water_right_id": bundle["right"]["id"],
                "point_of_diversion_id": bundle["pod"]["id"],
            }[param]
            found, meta = validate_paginated(
                api_client.list_lease_assignments(DECIDER, params={param: key})
            )
            assert meta["total_count"] == 1, f"lease not reachable via {param}"
            assert found[0]["id"] == lease["id"]
            assert found[0]["water_bank_account_id"] == bundle["account"]["id"]
            assert found[0]["water_right_id"] == bundle["right"]["id"]
            assert found[0]["point_of_diversion_id"] == bundle["pod"]["id"]
            assert found[0]["status"] == "RESERVED"

        _actives, active_meta = validate_paginated(
            api_client.list_lease_assignments(DECIDER, params={"status": "ACTIVE"})
        )
        assert active_meta["total_count"] == 0
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(90.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(20.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(70.00, abs=0.01)
        assert account["posture"] == "OPEN"

    def test_a_new_docket_opens_with_zeroed_rollups(self):
        """PRD §3.10: "The docket opens in phase `OPEN_FOR_CLAIMS` with
        `claim_count`, `decreed_claim_count` and `total_decreed_af` all zeroed, and
        any of the five roles may read it to inspect its phase and rolled-up
        counters."

        PRD §3.10: "Opening a docket names a `basin_code` of 1 to 24 characters, a
        `docket_number` unique across all dockets ... and a `claim_filing_deadline`
        that is an *exclusive* cut-off." The follow-up read returns identical
        counters, so nothing drifts between the write and the read.

        Design: Corner/entities/entity_creation_decree_docket_starts_open_for_claims
        """
        set_clock(CLOCK)

        docket = validate_success(
            api_client.create_decree_docket(
                {
                    "basin_code": "BASIN-01",
                    "docket_number": "DKT-2198-A",
                    "claim_filing_deadline": "2026-06-01T00:00:00Z",
                },
                ADJUDICATOR,
            ),
            expected_status=201,
        )
        reread = get_success_data(
            api_client.get_decree_docket(docket["id"], ADJUDICATOR)
        )

        assert docket["phase"] == "OPEN_FOR_CLAIMS"
        assert docket["basin_code"] == "BASIN-01"
        assert docket["docket_number"] == "DKT-2198-A"
        assert_same_instant(docket["claim_filing_deadline"], "2026-06-01T00:00:00Z", "claim_filing_deadline")
        assert docket["claim_count"] == 0
        assert docket["decreed_claim_count"] == 0
        assert docket["total_decreed_af"] == pytest.approx(0.00, abs=0.01)
        assert docket["version"] == 1
        assert_same_instant(docket["created_at"], CLOCK, "created_at")
        assert reread == docket
