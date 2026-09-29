"""The resource contract itself: computed fields present on create, defaults,
system fields, retrieval fidelity, listing, the 404 families, body validation,
the version-less ledger row and the flat topology's two-way indexes.
"""

from test_helpers import (
    AcademicTermStatus,
    ApiErrorId,
    LedgerEntryType,
    LedgerReasonCode,
    MISSING_UUID,
    PublisherAgreementStatus,
    ReconciliationStatus,
    SectionIaStatus,
    assert_money,
    assert_ratio,
    assert_term_shape,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_compliance_officer_headers,
    make_faculty_headers,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_SECTION = {"section_number": "002"}
CHEM_SECTION = {
    "subject_code": "CHEM",
    "catalog_number": "105",
    "section_number": "001",
    "instructor_user_id": "fac-6",
    "max_concurrent_titles": 1,
}


class TestTermCreationContract:
    """The create response is already the whole resource, computed fields included."""

    def test_total_term_days_is_the_inclusive_span_and_the_row_is_version_one(
            self, api, program_admin):
        """PRD §3.1: "From those two dates the server derives `total_term_days` as
        the number of days from the start date through the end date inclusive —
        their difference in days, plus one."

        Design: Corner/entities/entity_term_create_returns_computed_total_term_days_and_common_fields
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")

        term = validate_success(
            api.create_term(factories.term_payload(), program_admin),
            expected_status=201,
        )
        assert_term_shape(term)
        # 2026-08-24 through 2026-12-11 inclusive, unrelated to instructional_days.
        assert term["total_term_days"] == 110
        assert term["instructional_days"] == 75
        assert term["status"] == AcademicTermStatus.PLANNING.value
        assert term["ia_section_count"] == 0
        assert term["closed_at"] is None
        assert term["opt_out_window_days"] == 14

        assert term["version"] == 1
        assert is_valid_uuid(term["id"])
        assert is_iso8601_timestamp(term["created_at"])
        assert term["created_at"] == "2026-07-01T00:00:00.000Z"
        assert term["updated_at"] == term["created_at"]

        assert fixtures.read_term(api, term["id"]) == term


class TestOptionalInputDefaults:
    """Three optional inputs, three defaults that move money or capacity."""

    def test_term_and_agreement_defaults_appear_in_the_create_response(
            self, api, program_admin):
        """PRD §3.1: "`opt_out_window_days` is optional, must be at least 1, and
        defaults to 14 — a nominal two-week opt-out window measured from each
        charge's own posting instant."

        PRD §3.2: "`max_list_price_pct` is a hard ceiling on the per-student price
        expressed as a fraction of the title's list price; it is optional, must be
        greater than 0 and at most 1, and defaults to 0.60 — sixty percent of
        list."

        Design: Corner/entities/entity_defaults_applied_when_optional_inputs_omitted
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")

        term = validate_success(
            api.create_term(
                factories.term_payload(opt_out_window_days=factories.REMOVE),
                program_admin,
            ),
            expected_status=201,
        )
        assert term["opt_out_window_days"] == 14

        agreement = validate_success(
            api.create_agreement(
                factories.agreement_payload(max_list_price_pct=factories.REMOVE),
                program_admin,
            ),
            expected_status=201,
        )
        assert_ratio(agreement["max_list_price_pct"], 0.60)
        assert agreement["status"] == PublisherAgreementStatus.DRAFT.value
        assert (agreement["reconciliation_status"]
                == ReconciliationStatus.NOT_STARTED.value)
        assert agreement["settled_amount_cents"] is None
        assert fixtures.read_agreement(api, agreement["id"])["max_list_price_pct"] \
            == agreement["max_list_price_pct"]

    def test_a_section_defaults_to_two_concurrent_titles(self, api, registrar):
        """PRD §3.3: "The section also names the `instructor_user_id` — the opaque
        `Faculty` operator identifier that owns adoption authoring for this section
        — and optionally `max_concurrent_titles`, an integer of at least 1 that
        defaults to 2 and caps how many approved access windows may cover any
        single calendar date."

        Design: Corner/entities/entity_defaults_applied_when_optional_inputs_omitted
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)

        section = validate_success(
            api.create_section(
                factories.section_payload(
                    term["id"], max_concurrent_titles=factories.REMOVE
                ),
                registrar,
            ),
            expected_status=201,
        )
        assert section["max_concurrent_titles"] == 2
        assert section["inclusive_access_flag"] is False
        assert section["ia_status"] == SectionIaStatus.NOT_FLAGGED.value

        stored = fixtures.read_section(api, section["id"])
        assert stored["max_concurrent_titles"] == 2
        assert stored["billing_basis_enrollment_count"] is None


class TestComputedFieldsAreNotInputs:
    """A client that tries to seed a computed or system field gets a 400."""

    def test_seeding_a_balance_a_posture_or_an_identifier_is_rejected_outright(
            self, api, program_admin, registrar):
        """PRD §2.11: "3. Request body shape on every write: required fields
        present, types correct, enum members recognized, numeric ranges respected,
        and unknown fields rejected outright — `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD §2.5: "Every resource in this system carries an `id`: a server-minted
        UUID, with no type prefix and no client control over its value."

        Design: Corner/entities/entity_computed_and_system_fields_cannot_be_supplied_in_request_body
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)

        response = api.create_student(
            factories.student_payload(bursar_balance_cents=5000), registrar
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_student(
            factories.student_payload(external_id="S-2002", full_name="Eli Braun",
                                      id=MISSING_UUID),
            registrar,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_student(
            factories.student_payload(external_id="S-2003", full_name="Fay Idris",
                                      version=7),
            registrar,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_section(
            factories.section_payload(term["id"], ia_status="BILLED"), registrar
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_term(
            factories.spring_term_payload(status="OPEN"), program_admin
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        for lister, expected in ((api.list_students(registrar), 0),
                                 (api.list_sections(program_admin), 0),
                                 (api.list_terms(program_admin), 1)):
            _, meta = validate_paginated(lister)
            assert meta["total_count"] == expected


class TestSystemFieldsAcrossAMutation:
    """id and created_at are frozen; updated_at and version move."""

    def test_one_transition_lifts_the_version_and_refreshes_updated_at(self, api):
        """PRD §2.5: "All resources except `LedgerEntry` additionally carry
        `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation of that resource — including mutations the
        server performs on its own initiative as part of a cascade, and including
        recomputation of derived fields such as counters and rates."

        Design: Corner/entities/entity_system_fields_minted_by_server_and_version_increments_on_write
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        created = fixtures.create_term(api)
        assert created["version"] == 1

        fixtures.set_clock(api, "2026-07-02T08:30:00Z")
        opened = fixtures.open_term(api, created["id"])

        assert opened["status"] == AcademicTermStatus.OPEN.value
        assert opened["version"] == 2
        assert opened["id"] == created["id"]
        assert opened["created_at"] == "2026-07-01T00:00:00.000Z"
        assert opened["updated_at"] == "2026-07-02T08:30:00.000Z"
        assert opened["closed_at"] is None
        assert opened["ia_section_count"] == 0


class TestAgreementRetrievalFidelity:
    """The negotiated parameters round-trip untouched, because the formula reads them."""

    def test_every_pricing_parameter_reads_back_exactly_as_stored(self, api):
        """PRD §2.6: "Percentage and rate inputs — `admin_fee_pct`,
        `bookstore_margin_pct`, `max_list_price_pct`, `rebate_pct` — are exact
        decimal fractions and are applied as given, never pre-rounded."

        Design: Corner/entities/entity_agreement_retrieval_returns_stored_row
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        created = fixtures.create_agreement(api)

        stored = validate_success(
            api.get_agreement(created["id"], make_compliance_officer_headers())
        )
        assert stored["id"] == created["id"]
        assert stored["agreement_code"] == "PUB-A"
        assert_ratio(stored["admin_fee_pct"], 0.05)
        assert_ratio(stored["bookstore_margin_pct"], 0.12)
        assert_ratio(stored["rebate_pct"], 0.03)
        assert_ratio(stored["max_list_price_pct"], 0.60)
        assert_money(stored["price_floor_cents"], 2500)
        assert_money(stored["rebate_threshold_cents"], 16500)
        assert stored["status"] == PublisherAgreementStatus.DRAFT.value
        assert stored["reconciliation_status"] == ReconciliationStatus.NOT_STARTED.value
        assert stored["settled_amount_cents"] is None
        assert stored["suspend_reason_note"] is None
        assert stored["version"] == 1


class TestSectionListing:
    """total_count reports the filtered population, never the page."""

    def test_paging_and_filtering_report_the_population_not_the_page(
            self, api, program_admin, compliance_officer):
        """PRD §2.3: "Both are echoed in the `meta` object of the envelope alongside
        `total_count` (the number of items matching the query before pagination)
        and `has_more` (true when items remain beyond the current page)."

        Design: Corner/entities/entity_section_listing_pagination_and_filter
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)
        fixtures.create_section(api, term["id"])
        fixtures.create_section(api, term["id"], **SECOND_SECTION)
        fixtures.create_section(api, term["id"], **CHEM_SECTION)

        first_page, meta = validate_paginated(
            api.list_sections(program_admin,
                              {"term_id": term["id"], "limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

        second_page, meta = validate_paginated(
            api.list_sections(program_admin,
                              {"term_id": term["id"], "limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["offset"] == 2

        # The instructor filter narrows the population itself.
        owned, meta = validate_paginated(
            api.list_sections(program_admin,
                              {"term_id": term["id"], "instructor_user_id": "fac-1"})
        )
        assert len(owned) == 2
        assert meta["total_count"] == 2

        flagged, meta = validate_paginated(
            api.list_term_sections(term["id"], compliance_officer,
                                   {"ia_status": SectionIaStatus.FLAGGED.value})
        )
        assert flagged == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

        for row in first_page + second_page:
            assert row["ia_status"] == SectionIaStatus.NOT_FLAGGED.value
            assert row["enrolled_count"] == 0


class TestNotFoundFamilies:
    """Thirteen resource families, thirteen distinct 404 identifiers."""

    def test_each_path_identifier_reports_its_own_not_found_error(self, api,
                                                                 program_admin):
        """PRD §2.11: "The identifier names used in paths are `term_id`,
        `student_id`, `agreement_id`, `title_id`, `tier_id`, `section_id`,
        `adoption_id`, `enrollment_id`, `charge_id`, `entry_id`, `request_id`,
        `run_id` and `report_id`, and they map to `ERR_TERM_NOT_FOUND`,
        `ERR_STUDENT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_TITLE_NOT_FOUND`,
        `ERR_TIER_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`,
        `ERR_ENROLLMENT_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`,
        `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_OPT_OUT_REQUEST_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND` and `ERR_REPORT_NOT_FOUND` respectively, all HTTP 404."

        Design: Corner/entities/entity_unknown_path_ids_return_specific_not_found_errors
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")

        probes = (
            (api.get_term, ApiErrorId.TERM_NOT_FOUND),
            (api.get_student, ApiErrorId.STUDENT_NOT_FOUND),
            (api.get_agreement, ApiErrorId.AGREEMENT_NOT_FOUND),
            (api.get_title, ApiErrorId.TITLE_NOT_FOUND),
            (api.get_pricing_tier, ApiErrorId.TIER_NOT_FOUND),
            (api.get_section, ApiErrorId.SECTION_NOT_FOUND),
            (api.get_adoption, ApiErrorId.ADOPTION_NOT_FOUND),
            (api.get_enrollment, ApiErrorId.ENROLLMENT_NOT_FOUND),
            (api.get_charge, ApiErrorId.CHARGE_NOT_FOUND),
            (api.get_ledger_entry, ApiErrorId.LEDGER_ENTRY_NOT_FOUND),
            (api.get_opt_out_request, ApiErrorId.OPT_OUT_REQUEST_NOT_FOUND),
            (api.get_reconciliation_run, ApiErrorId.RUN_NOT_FOUND),
            (api.get_disclosure_report, ApiErrorId.REPORT_NOT_FOUND),
        )
        for read, expected in probes:
            # The probe id is a well-formed UUID, so the 404 comes from lookup.
            validate_error(read(MISSING_UUID, program_admin), expected.value)

        _, meta = validate_paginated(api.list_terms(program_admin))
        assert meta["total_count"] == 0


class TestRequiredFieldsPrecedeEverything:
    """Priority 3 body validation runs before FK resolution and every date gate."""

    def test_a_missing_required_field_is_reported_before_any_later_check(
            self, api, program_admin, registrar):
        """PRD §2.11: "3. Request body shape on every write: required fields
        present, types correct, enum members recognized, numeric ranges respected,
        and unknown fields rejected outright — `ERR_INVALID_REQUEST` (HTTP 400)."

        PRD §2.11: "5. Body foreign keys resolve, in declaration order — the 404
        family above."

        Design: Corner/entities/entity_missing_required_fields_rejected
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)
        agreement = fixtures.create_agreement(api)
        section = fixtures.create_section(api, term["id"])
        student = fixtures.create_student(api)

        response = api.create_title(
            factories.title_payload(agreement["id"], isbn=factories.REMOVE),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_term(
            factories.spring_term_payload(census_date=factories.REMOVE), program_admin
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        # enrolled_on missing outranks both the FK check and the calendar gates.
        response = api.create_enrollment(
            factories.enrollment_payload(section["id"], student["id"],
                                         enrolled_on=factories.REMOVE),
            registrar,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        # reason_code missing outranks the unresolvable charge_id.
        response = api.create_opt_out_request(
            factories.opt_out_request_payload(MISSING_UUID,
                                              reason_code=factories.REMOVE),
            make_student_headers(student["id"]),
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        for listing in (api.list_titles(program_admin),
                        api.list_enrollments(registrar),
                        api.list_opt_out_requests(program_admin)):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == 0


class TestRangeAndEnumConstraints:
    """Constraints bite at their declared bounds, not merely on type."""

    def test_money_and_enum_constraints_on_the_catalog_are_all_four_hundreds(
            self, api, program_admin):
        """PRD §3.2: "A title has an `isbn` that must be unique within its
        agreement, a printed `title` string, a `list_price_cents` that must be
        greater than 0 — this is the savings baseline the state disclosure compares
        against — and a `format` that is either `DIGITAL` or `DIGITAL_PLUS_PRINT`."

        PRD §3.2: "Each band declares `min_enrollment`, an inclusive lower bound of
        at least 1, an optional `max_enrollment` that is an inclusive upper bound
        and, when omitted or null, means the band is unbounded above, and the
        `per_student_price_cents` negotiated for that band, which must be greater
        than 0. When `max_enrollment` is supplied it must not be smaller than
        `min_enrollment`."

        Design: Corner/entities/entity_type_and_range_constraints_rejected
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        agreement = fixtures.create_agreement(api)
        title = fixtures.create_title(api, agreement["id"])

        response = api.create_title(
            factories.title_payload(agreement["id"], isbn="978-0-11-000009-0",
                                    title="Audio Companion", list_price_cents=9000,
                                    format="AUDIO"),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_title(
            factories.title_payload(agreement["id"], isbn="978-0-11-000010-0",
                                    title="Free Reader", list_price_cents=0),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        # Rejected at body validation, never reaching the band-overlap check.
        response = api.create_pricing_tier(
            title["id"],
            factories.pricing_tier_payload(min_enrollment=3, max_enrollment=1,
                                           per_student_price_cents=8000),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_pricing_tier(
            title["id"],
            factories.pricing_tier_payload(min_enrollment=1, max_enrollment=2,
                                           per_student_price_cents=0),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_pricing_tier(
            title["id"],
            factories.pricing_tier_payload(min_enrollment=0, max_enrollment=2,
                                           per_student_price_cents=8000),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        _, tier_meta = validate_paginated(
            api.list_title_pricing_tiers(title["id"], program_admin)
        )
        assert tier_meta["total_count"] == 0
        _, title_meta = validate_paginated(api.list_titles(program_admin))
        assert title_meta["total_count"] == 1

    def test_rate_ceilings_narrative_counts_and_state_codes_are_range_checked(
            self, api, program_admin, compliance_officer):
        """PRD §3.2: "`admin_fee_pct` is the campus administrative fee added on top
        of the negotiated band price and must lie between 0 and 0.25 inclusive."

        PRD §3.1: "Separately, `instructional_days` — an integer of at least 1 — is
        the registrar's published count of teaching days; it appears in the
        disclosure narrative and enters no calculation."

        PRD §3.9: "A **DisclosureReport** is opened against a term with a payload
        carrying the `term_id` and a `reporting_state_code` of exactly two uppercase
        letters; only one report may exist per pairing of term and state code."

        Design: Corner/entities/entity_type_and_range_constraints_rejected
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)

        response = api.create_agreement(
            factories.agreement_payload(publisher_name="Overpriced Press",
                                        agreement_code="PUB-Z", admin_fee_pct=0.26),
            program_admin,
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        response = api.create_term(
            factories.spring_term_payload(instructional_days=0), program_admin
        )
        validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        for bad_code in ("ca", "CAL"):
            response = api.create_disclosure_report(
                factories.disclosure_report_payload(term["id"],
                                                    reporting_state_code=bad_code),
                compliance_officer,
            )
            validate_error(response, ApiErrorId.INVALID_REQUEST.value)

        _, agreement_meta = validate_paginated(api.list_agreements(program_admin))
        assert agreement_meta["total_count"] == 0
        _, term_meta = validate_paginated(api.list_terms(program_admin))
        assert term_meta["total_count"] == 1
        _, report_meta = validate_paginated(
            api.list_disclosure_reports(compliance_officer)
        )
        assert report_meta["total_count"] == 0


class TestLedgerEntryImmutability:
    """The one resource with no version and no updated_at."""

    def test_a_ledger_row_carries_only_id_and_created_at_of_the_common_fields(
            self, api, bursar_officer):
        """PRD §2.5: "A `LedgerEntry` is different: it carries only `id` and
        `created_at`."

        PRD §2.5: "Each `LedgerEntry` also records `posted_at`, the logical-clock
        instant at which the movement was appended, and `source_event`, a string
        naming the API operation that appended it, written as the operation's HTTP
        method, a space, and the operation's path template — for example `POST
        /opt-out-requests/{request_id}/grant` for a movement appended by granting
        an opt-out."

        Design: Corner/entities/entity_ledger_entry_is_immutable_and_carries_no_version_field
        """
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z",
            roster=(("S-1001", "Ada Lin"),),
        )
        rows, meta = validate_paginated(
            api.list_charge_ledger_entries(scenario["charge_ids"][0], bursar_officer)
        )
        assert meta["total_count"] == 1

        entry = validate_success(api.get_ledger_entry(rows[0]["id"], bursar_officer))
        assert entry["id"] == rows[0]["id"]
        assert entry["created_at"] == "2026-08-24T09:00:00.000Z"
        assert "version" not in entry
        assert "updated_at" not in entry

        assert entry["charge_id"] == scenario["charge_ids"][0]
        assert entry["student_id"] == scenario["student_ids"][0]
        assert entry["entry_type"] == LedgerEntryType.CHARGE.value
        assert entry["reason_code"] == LedgerReasonCode.INITIAL_POST.value
        assert_money(entry["amount_cents"], 9450)
        assert entry["posted_at"] == "2026-08-24T09:00:00.000Z"
        assert entry["source_event"] == "POST /sections/{section_id}/post-charges"


class TestBodyForeignKeyResolution:
    """Parents are body foreign keys here, so integrity is a body check."""

    def test_each_unresolvable_body_key_yields_its_parents_own_404(
            self, api, program_admin, registrar):
        """PRD §2.11: "Foreign keys supplied in a request body are resolved after
        the path and in a fixed declaration order: `term_id`, then `agreement_id`,
        then `title_id`, then `section_id`, then `student_id`, then
        `enrollment_id`, then `adoption_id`, then `charge_id`, then
        `supersedes_adoption_id`, then `supersedes_run_id`. Each unresolved key
        yields the same 404 identifier as its path counterpart;
        `supersedes_adoption_id` yields `ERR_ADOPTION_NOT_FOUND` and
        `supersedes_run_id` yields `ERR_RUN_NOT_FOUND`."

        Design: Corner/entities/entity_unresolvable_body_foreign_keys_rejected
        """
        fixtures.set_clock(api, "2026-07-01T00:00:00Z")
        term = fixtures.create_term(api)
        section = fixtures.create_section(api, term["id"])

        response = api.create_title(factories.title_payload(MISSING_UUID),
                                    program_admin)
        validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND.value)

        response = api.create_section(
            factories.section_payload(MISSING_UUID, section_number="002"), registrar
        )
        validate_error(response, ApiErrorId.TERM_NOT_FOUND.value)

        # section_id resolves and student_id does not.
        response = api.create_enrollment(
            factories.enrollment_payload(section["id"], MISSING_UUID), registrar
        )
        validate_error(response, ApiErrorId.STUDENT_NOT_FOUND.value)

        # The title 404 is raised before the stale-version and window checks.
        response = api.create_adoption(
            factories.adoption_payload(section["id"], MISSING_UUID,
                                       section["version"]),
            make_faculty_headers(),
        )
        validate_error(response, ApiErrorId.TITLE_NOT_FOUND.value)

        for listing, expected in ((api.list_titles(program_admin), 0),
                                  (api.list_enrollments(registrar), 0),
                                  (api.list_adoptions(program_admin), 0),
                                  (api.list_sections(registrar), 1)):
            _, meta = validate_paginated(listing)
            assert meta["total_count"] == expected


class TestFlatTopologyReverseIndexes:
    """Every foreign key is readable from both ends, and the ends must agree."""

    def test_the_filtered_collection_and_the_sub_resource_read_return_one_row_each(
            self, api, bursar_officer, program_admin, registrar):
        """PRD §2.3: "- Charges may be filtered by `enrollment_id`, `adoption_id`,
        `student_id`, `billing_status` and `access_status`; a charge's ledger
        movements by `entry_type`; a charge's opt-out requests by `status`."

        PRD §2.3: "- Ledger movements may be filtered by `charge_id`, `student_id`,
        `entry_type` and `reason_code`."

        Design: Corner/entities/entity_flat_topology_reverse_indexes_agree_with_sub_resource_reads
        """
        scenario = fixtures.setup_billed_section(
            api, setup_clock="2026-07-01T00:00:00Z",
            roster=(("S-1001", "Ada Lin"),),
        )
        charge_id = scenario["charge_ids"][0]
        student_id = scenario["student_ids"][0]

        by_filter, filter_meta = validate_paginated(
            api.list_charges(bursar_officer, {"student_id": student_id})
        )
        by_path, path_meta = validate_paginated(
            api.list_student_charges(student_id, bursar_officer)
        )
        assert filter_meta["total_count"] == path_meta["total_count"] == 1
        assert by_filter[0]["id"] == by_path[0]["id"] == charge_id

        rows_by_filter, ledger_filter_meta = validate_paginated(
            api.list_ledger_entries(bursar_officer, {"charge_id": charge_id})
        )
        rows_by_path, ledger_path_meta = validate_paginated(
            api.list_charge_ledger_entries(charge_id, bursar_officer)
        )
        assert ledger_filter_meta["total_count"] == ledger_path_meta["total_count"] == 1
        assert rows_by_filter[0]["id"] == rows_by_path[0]["id"]
        assert_money(rows_by_filter[0]["amount_cents"], 9450)
        assert rows_by_filter[0]["reason_code"] == LedgerReasonCode.INITIAL_POST.value

        tiers_by_filter, tier_filter_meta = validate_paginated(
            api.list_pricing_tiers(program_admin, {"title_id": scenario["title_id"]})
        )
        tiers_by_path, tier_path_meta = validate_paginated(
            api.list_title_pricing_tiers(scenario["title_id"], program_admin)
        )
        assert tier_filter_meta["total_count"] == tier_path_meta["total_count"] == 2
        assert ({tier["id"] for tier in tiers_by_filter}
                == {tier["id"] for tier in tiers_by_path})

        _, adoption_meta = validate_paginated(
            api.list_charges(program_admin, {"adoption_id": scenario["adoption_id"]})
        )
        assert adoption_meta["total_count"] == 1

        by_enrollment, enrollment_meta = validate_paginated(
            api.list_enrollment_charges(scenario["enrollment_ids"][0], registrar)
        )
        assert enrollment_meta["total_count"] == 1
        assert by_enrollment[0]["enrollment_id"] == scenario["enrollment_ids"][0]

        charge = by_filter[0]
        assert_money(charge["gross_price_cents"], 9450)
        assert_ratio(charge["proration_pct"], 1.0000)
        assert_money(charge["billed_amount_cents"], 9450)
        assert_money(charge["net_billed_cents"], 9450)
        assert_money(charge["publisher_share_cents"], 8316)
