"""Record-level contracts: the defaults a registration applies, the fields the
server stamps for itself, the write-once coverage grid, and the by-id reads.
"""

from test_helpers import (
    ANALYST_ONE,
    COORDINATOR_SEVEN,
    INITIAL_LOGICAL_CLOCK_STAMP,
    LIAISON_ONE,
    MANAGER_ONE,
    REMOVE,
    REVIEWER_ONE,
    UNKNOWN_UUID,
    add_item,
    api_client,
    approve_analysis,
    assert_billable_to_derived,
    assert_study,
    assert_study_ledger_zeroed,
    assert_write_once_identity,
    create_charge_payload,
    create_coverage_item_payload,
    create_study_payload,
    create_visit_charge_route_payload,
    create_calendar,
    add_visit,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_analyst_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_manager_headers,
    make_reviewer_headers,
    open_analysis,
    read_analysis,
    register_study,
    set_clock,
    submit_analysis,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStudyRegistrationRecord:
    """What a registration writes when the client supplies only the minimum."""

    def test_01_registering_a_protocol_applies_every_declared_default(self):
        """Six required inputs in, and the server fills the enum defaults, the
        whole ledger, the counters and the identity fields itself.

        PRD §3.1: "A new study opens with `lifecycle_status` at `DRAFT`,
        `budget_status` at `NOT_BUILT`, `qct_determination` at `UNDETERMINED`,
        `qct_basis` at null, every ledger position at zero, and — as clause 3 of
        the posture rule dictates — `billing_hold_posture` at `PAYER_BLOCKED`."

        Design: Corner/entities/create_study_returns_201_with_every_declared_default
        """
        set_clock("2026-08-01T00:00:00Z")
        response = api_client.create_study(
            create_study_payload(
                protocol_number="AMC-2390-C01", title="Corner creation probe"
            ),
            make_manager_headers(MANAGER_ONE),
        )
        data = validate_success(response, 201)
        assert_study(data)

        assert data["lifecycle_status"] == "DRAFT"
        assert data["budget_status"] == "NOT_BUILT"
        assert data["qct_determination"] == "UNDETERMINED"
        assert data["qct_basis"] is None
        assert data["billing_hold_posture"] == "PAYER_BLOCKED"
        # The registry number is null until the trial is registered (§3.1) and
        # this request omitted it.
        assert data["registry_number"] is None
        assert_study_ledger_zeroed(data)
        # Both §2.8 counters are sums over collections that are still empty.
        assert data["open_finding_count"] == 0
        assert data["rebuild_required_calendar_count"] == 0

        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        assert data["created_at"] == INITIAL_LOGICAL_CLOCK_STAMP

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])

    def test_02_a_by_id_read_returns_the_stored_record_and_is_not_a_mutation(self):
        """The read echoes every supplied input back and leaves the row at
        version 1 however often it is repeated.

        PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on
        every mutation, and `version`, an integer that starts at 1 on creation
        and increments by exactly one on every mutation of that row."

        Design: Corner/entities/get_study_returns_the_stored_record
        """
        set_clock("2026-08-01T00:00:00Z")
        created = register_study(
            protocol_number="AMC-2390-C02",
            title="Corner retrieval probe",
            funding_source="FEDERALLY_FUNDED",
            ind_ide_status="NONE",
            therapeutic_intent=False,
            registry_number="NCT10000101",
        )

        first = validate_success(
            api_client.get_study(created["id"], make_liaison_headers(LIAISON_ONE))
        )
        assert first["id"] == created["id"]
        assert first["protocol_number"] == "AMC-2390-C02"
        assert first["title"] == "Corner retrieval probe"
        assert first["funding_source"] == "FEDERALLY_FUNDED"
        assert first["ind_ide_status"] == "NONE"
        assert first["therapeutic_intent"] is False
        assert first["registry_number"] == "NCT10000101"
        assert first["version"] == 1

        second = validate_success(
            api_client.get_study(created["id"], make_liaison_headers(LIAISON_ONE))
        )
        assert second["version"] == 1
        assert second["updated_at"] == first["updated_at"]

    def test_03_the_registry_number_pattern_is_enforced_on_the_value_not_on_presence(self):
        """`NCT123` is refused, a well-formed identifier is stored, and omitting
        the field altogether is accepted with a null.

        PRD §3.1: "The `registry_number` is the ClinicalTrials.gov identifier;
        it is null until the trial is registered, and whenever it is non-null it
        must consist of the literal characters `NCT` followed by exactly eight
        digits — anything else is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_study_with_malformed_registry_number_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        validate_error(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C09",
                    title="Corner type-constraint probe",
                    registry_number="NCT123",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        _, meta = validate_paginated(
            api_client.list_studies(make_manager_headers(MANAGER_ONE))
        )
        assert meta["total_count"] == 0

        accepted = validate_success(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C09",
                    title="Corner type-constraint probe",
                    registry_number="NCT10000109",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        assert accepted["registry_number"] == "NCT10000109"

        omitted = validate_success(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C09B",
                    title="Corner type-constraint probe",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        assert omitted["registry_number"] is None

    def test_04_a_missing_or_undeclared_funding_source_is_refused_before_anything_persists(self):
        """`funding_source` has no default, so omitting it is a body-shape
        rejection and no row survives; a value outside the enum fails the same
        way.

        PRD §2.11: "Body shape: required fields present, enum members valid,
        integers non-negative where constrained, dates in `YYYY-MM-DD` form, and
        `registry_number` matching the required pattern when supplied —
        `ERR_INVALID_REQUEST` (400), on every POST endpoint."

        Design: Corner/entities/create_study_missing_funding_source_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        validate_error(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C05",
                    title="Corner required-field probe",
                    funding_source=REMOVE,
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )
        _, meta = validate_paginated(
            api_client.list_studies(make_manager_headers(MANAGER_ONE))
        )
        assert meta["total_count"] == 0

        accepted = validate_success(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C05",
                    title="Corner required-field probe",
                    funding_source="INVESTIGATOR_INITIATED",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            201,
        )
        assert accepted["funding_source"] == "INVESTIGATOR_INITIATED"

        # CHARITY_FUNDED is not one of the three declared members.
        validate_error(
            api_client.create_study(
                create_study_payload(
                    protocol_number="AMC-2390-C05B",
                    title="Corner required-field probe",
                    funding_source="CHARITY_FUNDED",
                ),
                make_manager_headers(MANAGER_ONE),
            ),
            "ERR_INVALID_REQUEST",
            400,
        )


class TestCoverageGridRecords:
    """The write-once grid: derived fields, declared defaults, and immutability."""

    def test_05_billable_to_is_derived_from_the_classification_of_each_item(self):
        """Three items on one analysis take three different parties of record,
        and the analysis' classification counters follow.

        PRD §3.2: "`classification` is one of `ROUTINE_CARE`, `RESEARCH_PAID`,
        or `PROMOTIONAL`, and from it the server derives the party of record in
        `billable_to`: `ROUTINE_CARE` items are billable to `PAYER`,
        `RESEARCH_PAID` items to `SPONSOR`, and `PROMOTIONAL` items to `NONE`."

        Design: Corner/entities/coverage_item_billable_to_is_derived_from_classification
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C07", title="Corner computed-field probe"
        )
        analysis = open_analysis(study["id"])

        routine = add_item(
            analysis["id"],
            item_code="80053",
            description="Comprehensive metabolic panel",
            classification="ROUTINE_CARE",
            medicare_coverage_basis="STANDARD_OF_CARE",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=9000,
            negotiated_unit_cents=9000,
            units_per_occurrence=1,
            expected_occurrences=3,
        )
        assert routine["billable_to"] == "PAYER"
        assert_billable_to_derived(routine)

        research = add_item(
            analysis["id"],
            item_code="J9999",
            description="Investigational infusion",
            classification="RESEARCH_PAID",
            medicare_coverage_basis="NOT_COVERED",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=55000,
            negotiated_unit_cents=40000,
            units_per_occurrence=1,
            expected_occurrences=1,
        )
        assert research["billable_to"] == "SPONSOR"
        assert_billable_to_derived(research)

        promotional = validate_success(
            api_client.create_coverage_item(
                create_coverage_item_payload(
                    analysis["id"],
                    read_analysis(analysis["id"])["version"],
                    item_code="A0001",
                    description="Sponsor-supplied dosing diary",
                    classification="PROMOTIONAL",
                    medicare_coverage_basis="NOT_COVERED",
                    budget_category="NOT_BUDGETED",
                    charge_master_unit_cents=1500,
                    negotiated_unit_cents=0,
                    units_per_occurrence=1,
                    expected_occurrences=5,
                ),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert promotional["billable_to"] == "NONE"
        assert_billable_to_derived(promotional)

        # `billable_to` is derived, so it never appeared in any request body.
        after = read_analysis(analysis["id"])
        assert after["item_count"] == 3
        assert after["routine_care_item_count"] == 1
        assert after["research_paid_item_count"] == 1
        assert after["promotional_item_count"] == 1
        assert after["qct_conditional_item_count"] == 0
        assert after["status"] == "DRAFT"
        # One version bump per accepted item, from the analysis' opening 1.
        assert after["version"] == 4

    def test_06_two_omitted_defaults_compose_into_the_routes_expected_amount(self):
        """An item stored without `units_per_occurrence` and a route stored
        without `occurrences` both take 1, so the route prices at exactly the
        item's negotiated unit price.

        PRD §3.4: "Creating one takes a `calendar_visit_id`, a
        `coverage_item_id`, and an optional `occurrences` count that defaults to
        1 and must be at least 1."

        Design: Corner/entities/omitting_units_per_occurrence_defaults_to_one
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C06", title="Corner defaults probe"
        )
        analysis = open_analysis(study["id"])
        item = add_item(
            analysis["id"],
            item_code="J9999",
            description="Investigational infusion",
            classification="RESEARCH_PAID",
            medicare_coverage_basis="NOT_COVERED",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=55000,
            negotiated_unit_cents=40000,
            expected_occurrences=1,
            units_per_occurrence=REMOVE,
        )
        # §3.2: the optional units_per_occurrence "defaults to 1 when omitted".
        assert item["units_per_occurrence"] == 1

        submit_analysis(analysis["id"])
        approve_analysis(analysis["id"], user_id=REVIEWER_ONE)
        calendar = create_calendar(study["id"], analysis["id"])
        visit = add_visit(
            calendar["id"],
            visit_name="Cycle 1 Day 1",
            sequence_index=1,
            target_day_offset=0,
            window_before_days=0,
            window_after_days=3,
        )

        route = validate_success(
            api_client.create_visit_charge_route(
                create_visit_charge_route_payload(visit["id"], item["id"]),
                make_analyst_headers(ANALYST_ONE),
            ),
            201,
        )
        assert route["occurrences"] == 1
        assert route["routing_target"] == "SPONSOR"
        # 1 occurrence * 1 unit * 40,000 cents at the negotiated price.
        assert route["expected_amount_cents"] == 40000

        visits, meta = validate_paginated(
            api_client.list_calendar_visits_of_calendar(
                calendar["id"], make_analyst_headers(ANALYST_ONE)
            )
        )
        assert meta["total_count"] == 1
        assert visits[0]["id"] == visit["id"]
        assert visits[0]["expected_charge_total_cents"] == 40000

    def test_07_a_coverage_item_is_write_once_and_carries_no_version(self):
        """The stored grid row exposes an identity and a creation stamp and
        nothing that would let a client edit it in place.

        PRD §2.4: "Three record types are write-once and therefore carry only
        `id` and `created_at`, with **no** `updated_at` and **no** `version`
        field at all: coverage items, calendar visits, and visit charge routes."

        Design: Corner/entities/coverage_item_is_immutable_and_carries_no_version_field
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C10", title="Corner immutability probe"
        )
        analysis = open_analysis(study["id"])
        item = add_item(
            analysis["id"],
            item_code="80053",
            description="Comprehensive metabolic panel",
            classification="ROUTINE_CARE",
            medicare_coverage_basis="STANDARD_OF_CARE",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=9000,
            negotiated_unit_cents=9000,
            units_per_occurrence=1,
            expected_occurrences=3,
        )
        assert_write_once_identity(item, "coverage item")

        rows, meta = validate_paginated(
            api_client.list_coverage_analysis_items(
                analysis["id"], make_analyst_headers(ANALYST_ONE)
            )
        )
        assert meta["total_count"] == 1
        stored = rows[0]
        assert stored["id"] == item["id"]
        assert stored["created_at"] == item["created_at"]
        assert_write_once_identity(stored, "coverage item")
        # The classification can only be corrected by a new analysis revision,
        # so the stored row still reads exactly as it was written.
        assert stored["classification"] == "ROUTINE_CARE"
        assert stored["billable_to"] == "PAYER"

    def test_08_a_body_carried_analysis_id_that_names_nothing_is_a_404_not_a_412(self):
        """The item add presents a version that is current for a real analysis,
        but names an analysis that does not exist; the existence check runs
        first.

        PRD §2.11: "Existence of the foreign keys carried in the request body:
        `coverage_item_id` on route creation reports
        `ERR_COVERAGE_ITEM_NOT_FOUND`; `coverage_analysis_id` on item creation,
        `source_analysis_id` on calendar creation, and `source_analysis_id` on
        budget build all report `ERR_ANALYSIS_NOT_FOUND`; `calendar_visit_id` on
        subject-visit creation reports `ERR_CALENDAR_VISIT_NOT_FOUND`;
        `charge_id` on finding creation reports `ERR_CHARGE_NOT_FOUND`."

        Design: Corner/entities/coverage_item_with_unknown_analysis_returns_analysis_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C11", title="Corner FK probe"
        )
        analysis = open_analysis(study["id"])
        assert analysis["version"] == 1

        payload = create_coverage_item_payload(
            UNKNOWN_UUID,
            analysis["version"],
            item_code="80053",
            description="Comprehensive metabolic panel",
            classification="ROUTINE_CARE",
            medicare_coverage_basis="STANDARD_OF_CARE",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=9000,
            negotiated_unit_cents=9000,
            units_per_occurrence=1,
            expected_occurrences=3,
        )
        validate_error(
            api_client.create_coverage_item(payload, make_analyst_headers(ANALYST_ONE)),
            "ERR_ANALYSIS_NOT_FOUND",
            404,
        )

        untouched = read_analysis(analysis["id"])
        assert untouched["item_count"] == 0
        assert untouched["version"] == 1

        payload["coverage_analysis_id"] = analysis["id"]
        validate_success(
            api_client.create_coverage_item(payload, make_analyst_headers(ANALYST_ONE)),
            201,
        )


class TestChargeRecordAndCollectionReads:
    """What the server stamps on a charge, and how collections answer."""

    def test_09_an_interface_charge_is_stamped_from_the_caller_and_the_clock(self):
        """None of these fields appears in the request body: the source, the
        acting operator, the unbilled baseline and the coverage expectation are
        all server-side.

        PRD §3.6: "Such a charge takes `source` `INTERFACE_POSTED`, opens
        `UNROUTED` and `UNBILLED` with `unbilled_since` at the current logical
        instant, records the acting user in `posted_by_user_id`, leaves
        `suggested_routing_target` null because no route suggested anything, and
        receives its `expected_routing_target` under the audit view."

        Design: Corner/entities/charge_system_fields_are_server_stamped_from_the_logical_clock
        """
        set_clock("2026-08-01T00:00:00Z")
        study = register_study(
            protocol_number="AMC-2390-C08", title="Corner system-field probe"
        )
        analysis = open_analysis(study["id"])
        add_item(
            analysis["id"],
            item_code="80053",
            description="Comprehensive metabolic panel",
            classification="ROUTINE_CARE",
            medicare_coverage_basis="STANDARD_OF_CARE",
            budget_category="PER_PATIENT",
            charge_master_unit_cents=9000,
            negotiated_unit_cents=9000,
            units_per_occurrence=1,
            expected_occurrences=3,
        )
        submit_analysis(analysis["id"])
        approve_analysis(analysis["id"], user_id=REVIEWER_ONE)

        set_clock("2026-08-07T11:00:00Z")
        charge = validate_success(
            api_client.create_charge(
                create_charge_payload(
                    study["id"],
                    charge_code="80053",
                    service_date="2026-08-07",
                    amount_cents=9000,
                ),
                make_coordinator_headers(COORDINATOR_SEVEN),
            ),
            201,
        )

        assert charge["source"] == "INTERFACE_POSTED"
        assert charge["routing_state"] == "UNROUTED"
        assert charge["billing_state"] == "UNBILLED"
        assert charge["posted_by_user_id"] == COORDINATOR_SEVEN
        assert charge["suggested_routing_target"] is None
        assert charge["unbilled_since"] == "2026-08-07T11:00:00.000Z"
        assert charge["created_at"] == "2026-08-07T11:00:00.000Z"
        # The audit view resolves to the one APPROVED analysis, on which 80053
        # is routine care and therefore billable to the payer.
        assert charge["expected_routing_target"] == "PAYER"
        assert charge["improper_flag"] is False
        # §3.7: "Charges open at `NONE`."
        assert charge["hold_reason"] == "NONE"
        # Only a review stamps these two.
        assert charge["reviewed_by_user_id"] is None
        assert charge["reviewed_at"] is None

    def test_10_reading_an_unknown_charge_by_id_reports_the_charge_specific_404(self):
        """The list form of the same resource answers 200 with an empty page, so
        the 404 belongs to the by-id read.

        PRD §2.11: "Existence of the other path-segment resources, each on its
        own paths: `ERR_ANALYSIS_NOT_FOUND` under
        `/research-billing/coverage-analyses/{id}`, and likewise
        `ERR_CALENDAR_NOT_FOUND`, `ERR_SUBJECT_NOT_FOUND`,
        `ERR_SUBJECT_VISIT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
        `ERR_INVOICE_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`,
        `ERR_AMENDMENT_NOT_FOUND`, and `ERR_ROUTE_NOT_FOUND` (all 404)."

        Design: Corner/entities/get_charge_with_unknown_id_returns_charge_not_found
        """
        set_clock("2026-08-01T00:00:00Z")
        error = validate_error(
            api_client.get_charge(UNKNOWN_UUID, make_reviewer_headers(REVIEWER_ONE)),
            "ERR_CHARGE_NOT_FOUND",
            404,
        )
        assert error["message"].strip() != ""

        rows, meta = validate_paginated(
            api_client.list_charges(make_reviewer_headers(REVIEWER_ONE))
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_11_the_analysis_list_pages_and_reports_the_unpaginated_match_count(self):
        """Two analyses across two studies: one page of one, then the other,
        then the declared defaults return both.

        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
        may not be smaller than 1, and may not be larger than 100. `offset` is
        the number of rows to skip and defaults to 0; it may not be negative."

        Design: Corner/entities/list_coverage_analyses_paginates_with_total_count_and_has_more
        """
        set_clock("2026-08-01T00:00:00Z")
        study_a = register_study(
            protocol_number="AMC-2390-C03A", title="Corner listing probe A"
        )
        study_b = register_study(
            protocol_number="AMC-2390-C03B", title="Corner listing probe B"
        )
        analysis_a = open_analysis(study_a["id"])
        analysis_b = open_analysis(study_b["id"])

        headers = make_reviewer_headers(REVIEWER_ONE)
        first_page, first_meta = validate_paginated(
            api_client.list_coverage_analyses(
                headers, params={"status": "DRAFT", "limit": 1, "offset": 0}
            )
        )
        assert len(first_page) == 1
        assert first_meta["total_count"] == 2
        assert first_meta["has_more"] is True
        assert first_meta["limit"] == 1
        assert first_meta["offset"] == 0

        second_page, second_meta = validate_paginated(
            api_client.list_coverage_analyses(
                headers, params={"status": "DRAFT", "limit": 1, "offset": 1}
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 2
        assert second_meta["has_more"] is False
        assert {first_page[0]["id"], second_page[0]["id"]} == {
            analysis_a["id"],
            analysis_b["id"],
        }

        filtered, filtered_meta = validate_paginated(
            api_client.list_coverage_analyses(
                headers, params={"study_id": study_a["id"]}
            )
        )
        assert filtered_meta["total_count"] == 1
        assert filtered[0]["id"] == analysis_a["id"]

        both, both_meta = validate_paginated(
            api_client.list_coverage_analyses(headers)
        )
        assert both_meta["limit"] == 10
        assert both_meta["offset"] == 0
        assert both_meta["total_count"] == 2
        assert both_meta["has_more"] is False
        assert len(both) == 2
        assert {row["id"] for row in both} == {analysis_a["id"], analysis_b["id"]}
