"""Entity-level contracts: what a create writes, what a read echoes, and what a bad reference costs.

These tests exercise the record-level promises the API makes independently of any workflow: the
initial field values a freshly registered sponsor and site carry, the identity and timestamp shape
of versioned versus append-only rows, the pagination envelope of a collection read, and the
rejections produced by a missing required field, an out-of-enum value and an unresolvable
foreign key.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_append_only_row,
    assert_meal_count_entry,
    assert_pagination_meta,
    assert_site,
    assert_sponsor,
    create_approved_sponsor,
    create_area_eligibility_record_payload,
    create_area_record,
    create_open_day,
    create_site,
    create_site_payload,
    create_sponsor_payload,
    is_valid_uuid,
    make_sponsor_admin_headers,
    make_state_agency_reviewer_headers,
    record_meal_count,
    set_clock,
    setup_program_baseline,
    validate_error,
    validate_paginated,
    validate_success,
)

REVIEWER_HEADERS = make_state_agency_reviewer_headers()

# The intake instant every scenario below registers its records at, and the prefix its
# server-stamped timestamps must therefore carry.
INTAKE_CLOCK = "2026-06-01T00:00:00Z"
INTAKE_PREFIX = "2026-06-01T00:00:00"

# The first service day of the season, which is when the baseline sites start operating.
SERVICE_DAY_CLOCK = "2026-06-08T08:00:00Z"
SERVICE_DAY_PREFIX = "2026-06-08T08:00:00"


def _approved_sponsor_with_area_record() -> tuple:
    """An APPROVED sponsor plus one area income record, both filed at the intake instant."""
    set_clock(INTAKE_CLOCK)
    sponsor = create_approved_sponsor()
    area_record = create_area_record()
    return sponsor, area_record


def _site_count_for_sponsor(api, sponsor_id: str) -> int:
    """How many sites the collection read reports for one sponsor."""
    _, meta = validate_paginated(
        api.list_sites(make_sponsor_admin_headers(sponsor_id), params={"sponsor_id": sponsor_id})
    )
    return meta["total_count"]


class TestSponsorRecordContract:
    """What registering a sponsor writes, and what reading it back returns."""

    def test_sponsor_registration_opens_in_draft_with_zeroed_ledger_counters(self, api):
        """PRD §3.1: "The new record begins in `application_status` `DRAFT` with `version` 1, and its four ledger counters — `advance_paid_cents`, `advance_recovered_cents`, `advance_outstanding_cents` and `reimbursement_paid_cents` — all begin at 0."

        Design: Corner/entities/sponsor_creation_returns_201_with_initial_derived_fields
        """
        set_clock(INTAKE_CLOCK)

        sponsor = validate_success(
            api.create_sponsor(create_sponsor_payload(), REVIEWER_HEADERS), 201
        )

        assert_sponsor(sponsor)
        assert is_valid_uuid(sponsor["id"]), (
            f"the sponsor id must be a server-minted UUID, got {sponsor['id']!r}"
        )
        assert sponsor["application_status"] == "DRAFT", (
            f"a new sponsorship record opens in DRAFT, got {sponsor['application_status']}"
        )
        assert sponsor["version"] == 1, (
            f"a newly created row starts at version 1, got {sponsor['version']}"
        )
        for ledger_field in (
            "advance_paid_cents",
            "advance_recovered_cents",
            "advance_outstanding_cents",
            "reimbursement_paid_cents",
        ):
            assert sponsor[ledger_field] == 0, (
                f"{ledger_field} must begin at 0 on a new sponsor, got {sponsor[ledger_field]}"
            )
        assert sponsor["created_at"].startswith(INTAKE_PREFIX), (
            "created_at is stamped from the logical clock, so it must read "
            f"{INTAKE_PREFIX}, got {sponsor['created_at']}"
        )
        assert _site_count_for_sponsor(api, sponsor["id"]) == 0, (
            "a sponsor registered a moment ago owns no sites yet"
        )

    def test_sponsor_read_echoes_the_registered_identity_fields(self, api):
        """PRD §3.1: "A sponsorship record is opened by the state agency, not by the sponsor: a `StateAgencyReviewer` registers the organization with its `legal_name`, its `sponsor_type` — one of `SCHOOL_FOOD_AUTHORITY`, `GOVERNMENT`, `NONPROFIT` or `CAMP_OPERATOR` — its `experience_status`, which is either `NEW` or `EXPERIENCED` depending on whether the organization ran a summer program in a prior year, and the `program_year` the record covers, which must be 2020 or later."

        Design: Corner/entities/sponsor_retrieval_returns_stored_entity
        """
        set_clock(INTAKE_CLOCK)
        payload = create_sponsor_payload(
            legal_name="Riverbend Community Alliance",
            sponsor_type="NONPROFIT",
            experience_status="EXPERIENCED",
            program_year=2026,
        )
        created = validate_success(api.create_sponsor(payload, REVIEWER_HEADERS), 201)

        read = validate_success(
            api.get_sponsor(created["id"], make_sponsor_admin_headers(created["id"]))
        )

        assert_sponsor(read)
        assert read["id"] == created["id"], (
            "the read must return the same sponsor the registration created"
        )
        assert read["legal_name"] == "Riverbend Community Alliance", (
            f"expected the stored legal_name, got {read['legal_name']}"
        )
        assert read["sponsor_type"] == "NONPROFIT", (
            f"expected the stored sponsor_type NONPROFIT, got {read['sponsor_type']}"
        )
        assert read["experience_status"] == "EXPERIENCED", (
            f"expected the stored experience_status EXPERIENCED, got {read['experience_status']}"
        )
        assert read["program_year"] == 2026, (
            f"expected the stored program_year 2026, got {read['program_year']}"
        )

    def test_sponsor_read_with_unknown_id_reports_sponsor_not_found(self, api):
        """PRD §2.6: "Existence of the referenced records, in this sequence: sponsor (`ERR_SPONSOR_NOT_FOUND`), area eligibility record (`ERR_AREA_RECORD_NOT_FOUND`), sponsor budget (`ERR_BUDGET_NOT_FOUND`), advance payment (`ERR_ADVANCE_NOT_FOUND`), site (`ERR_SITE_NOT_FOUND`), service day (`ERR_SERVICE_DAY_NOT_FOUND`), meal count entry (`ERR_COUNT_ENTRY_NOT_FOUND`), holding-log entry (`ERR_HOLDING_LOG_NOT_FOUND`), monitoring visit (`ERR_VISIT_NOT_FOUND`), corrective action (`ERR_CORRECTIVE_ACTION_NOT_FOUND`), meal claim (`ERR_CLAIM_NOT_FOUND`), claim line item (`ERR_CLAIM_LINE_ITEM_NOT_FOUND`)."

        Design: Corner/entities/get_sponsor_with_unknown_id_returns_not_found
        """
        set_clock(INTAKE_CLOCK)

        response = api.get_sponsor(NON_EXISTENT_UUID, REVIEWER_HEADERS)

        validate_error(response, ApiErrorId.ERR_SPONSOR_NOT_FOUND.value)


class TestSiteListingPagination:
    """The collection read's page window, its total and its ordering key."""

    @staticmethod
    def _three_sites_in_creation_order() -> tuple:
        """One approved sponsor owning Alpha, Bravo and Charlie, each created an hour apart so
        their created_at values order strictly."""
        sponsor, area_record = _approved_sponsor_with_area_record()
        alpha = create_site(sponsor["id"], area_record["id"], name="Alpha Park")
        set_clock("2026-06-01T01:00:00Z")
        bravo = create_site(sponsor["id"], area_record["id"], name="Bravo Park")
        set_clock("2026-06-01T02:00:00Z")
        charlie = create_site(sponsor["id"], area_record["id"], name="Charlie Park")
        return sponsor, [alpha, bravo, charlie]

    def test_site_listing_first_page_reports_the_prefilter_total_and_more_records(self, api):
        """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the envelope's `meta` object, where `total_count` is the number of records matching the filters before pagination is applied and `has_more` indicates whether records remain beyond the current page."

        Design: Corner/entities/site_listing_paginates_with_total_count_and_has_more
        """
        sponsor, sites = self._three_sites_in_creation_order()

        data, meta = validate_paginated(
            api.list_sites(
                make_sponsor_admin_headers(sponsor["id"]),
                params={"sponsor_id": sponsor["id"], "limit": 2, "offset": 0},
            )
        )

        assert len(data) == 2, f"a limit of 2 caps the page at two sites, got {len(data)}"
        assert_pagination_meta(meta, 3, True, expected_limit=2, expected_offset=0)
        assert {site["id"] for site in data} <= {site["id"] for site in sites}, (
            "the page must only contain the sponsor's own sites"
        )

    def test_site_listing_pages_the_collection_in_created_at_ascending_order(self, api):
        """PRD §2.3: "Unless a specific endpoint says otherwise, every list endpoint returns its records sorted by `created_at` in ascending order."

        Design: Corner/entities/site_listing_paginates_with_total_count_and_has_more
        """
        sponsor, sites = self._three_sites_in_creation_order()
        alpha, bravo, charlie = sites
        headers = make_sponsor_admin_headers(sponsor["id"])

        first_page, _ = validate_paginated(
            api.list_sites(
                headers, params={"sponsor_id": sponsor["id"], "limit": 2, "offset": 0}
            )
        )
        second_page, second_meta = validate_paginated(
            api.list_sites(
                headers, params={"sponsor_id": sponsor["id"], "limit": 2, "offset": 2}
            )
        )

        assert [item["id"] for item in first_page] == [alpha["id"], bravo["id"]], (
            "the first page must carry the two oldest sites in created_at order, got "
            f"{[item['name'] for item in first_page]}"
        )
        assert len(second_page) == 1, (
            f"offset 2 of a three-record collection leaves one site, got {len(second_page)}"
        )
        assert second_page[0]["id"] == charlie["id"], (
            f"the last page must carry the newest site, got {second_page[0]['name']}"
        )
        assert_pagination_meta(second_meta, 3, False, expected_limit=2, expected_offset=2)


class TestSiteRegistrationContract:
    """What a site registration validates, defaults and computes for itself."""

    def test_site_registration_without_site_type_is_malformed(self, api):
        """PRD §2.6: "Request well-formedness: required fields present, enum members drawn from their declared sets, integers non-negative where declared, dates written as `YYYY-MM-DD`, clock times written as `HH:MM` on a 24-hour clock, `limit` between 1 and 100, `offset` at least 0, and every `decision`, `to_status` and `method` value inside its declared set — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/site_creation_missing_required_field_rejected
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="No Type Park")
        payload.pop("site_type")

        response = api.create_site(payload, make_sponsor_admin_headers(sponsor["id"]))

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
        assert _site_count_for_sponsor(api, sponsor["id"]) == 0, (
            "a rejected registration must not leave a site behind"
        )

    def test_site_registration_omitting_the_optional_booleans_stores_them_false(self, api):
        """PRD §3.4: "Two optional booleans shape later rules and both default to false: `is_open_air` marks a site serving outdoors with no climate-controlled holding, which is what arms holding-time enforcement in §3.6, and `is_rural` participates with `production_mode` in selecting the reimbursement rate class in §3.8."

        Design: Corner/entities/site_creation_omitting_optional_flags_applies_declared_defaults
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="Defaults Park")
        payload.pop("is_open_air")
        payload.pop("is_rural")

        site = validate_success(
            api.create_site(payload, make_sponsor_admin_headers(sponsor["id"])), 201
        )

        assert_site(site)
        assert site["is_open_air"] is False, (
            f"an omitted is_open_air defaults to false, got {site['is_open_air']!r}"
        )
        assert site["is_rural"] is False, (
            f"an omitted is_rural defaults to false, got {site['is_rural']!r}"
        )
        assert _site_count_for_sponsor(api, sponsor["id"]) == 1, (
            "the accepted registration must be the sponsor's only site"
        )

    def test_new_site_opens_pending_review_not_started_and_undetermined(self, api):
        """PRD §3.4: "A new site opens with `approval_status` `PENDING_REVIEW`, `operating_status` `NOT_STARTED`, `eligibility_basis` `UNDETERMINED`, `claim_hold` false, and `compliance_flag_count` and `voided_day_count` both at 0."

        Design: Corner/entities/site_creation_omitting_optional_flags_applies_declared_defaults
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="Defaults Park")
        payload.pop("is_open_air")
        payload.pop("is_rural")

        site = validate_success(
            api.create_site(payload, make_sponsor_admin_headers(sponsor["id"])), 201
        )

        assert_site(site)
        assert site["approval_status"] == "PENDING_REVIEW", (
            f"a new site opens in PENDING_REVIEW, got {site['approval_status']}"
        )
        assert site["operating_status"] == "NOT_STARTED", (
            f"a new site opens in NOT_STARTED, got {site['operating_status']}"
        )
        assert site["eligibility_basis"] == "UNDETERMINED", (
            f"a new site opens UNDETERMINED, got {site['eligibility_basis']}"
        )
        assert site["claim_hold"] is False, (
            f"a new site opens with claim_hold false, got {site['claim_hold']!r}"
        )
        assert site["compliance_flag_count"] == 0, (
            f"a new site opens with compliance_flag_count 0, got {site['compliance_flag_count']}"
        )
        assert site["voided_day_count"] == 0, (
            f"a new site opens with voided_day_count 0, got {site['voided_day_count']}"
        )

    def test_site_registration_mints_its_own_id_ignoring_a_client_supplied_one(self, api):
        """PRD §2.5: "Every resource is addressed by an `id`, a server-minted UUID carrying no type prefix and never used in a business decision or as a sort key."

        Design: Corner/entities/site_creation_client_supplied_computed_and_system_fields_input_ignored
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="Injected Park")
        payload["id"] = NON_EXISTENT_UUID

        site = validate_success(
            api.create_site(payload, make_sponsor_admin_headers(sponsor["id"])), 201
        )

        assert site["id"] != NON_EXISTENT_UUID, (
            "the server mints the id, so the client-supplied value must not become the site id"
        )
        assert is_valid_uuid(site["id"]), (
            f"the minted id must be a UUID carrying no type prefix, got {site['id']!r}"
        )
        validate_error(
            api.get_site(NON_EXISTENT_UUID, make_sponsor_admin_headers(sponsor["id"])),
            ApiErrorId.ERR_SITE_NOT_FOUND.value,
        )

    def test_site_registration_stamps_created_at_from_the_logical_clock(self, api):
        """PRD §2.5: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits stamped from the logical clock at creation; `created_at` is the only sanctioned tie-break ordering key anywhere in this specification."

        Design: Corner/entities/site_creation_client_supplied_computed_and_system_fields_input_ignored
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="Injected Park")
        payload["created_at"] = "2020-01-01T00:00:00Z"

        site = validate_success(
            api.create_site(payload, make_sponsor_admin_headers(sponsor["id"])), 201
        )

        assert site["created_at"].startswith(INTAKE_PREFIX), (
            "created_at is stamped from the logical clock reading "
            f"{INTAKE_CLOCK}, got {site['created_at']}"
        )

    def test_site_registration_ignores_client_supplied_eligibility_and_void_counter(self, api):
        """PRD §3.4: "A new site opens with `approval_status` `PENDING_REVIEW`, `operating_status` `NOT_STARTED`, `eligibility_basis` `UNDETERMINED`, `claim_hold` false, and `compliance_flag_count` and `voided_day_count` both at 0."

        Design: Corner/entities/site_creation_client_supplied_computed_and_system_fields_input_ignored
        """
        sponsor, area_record = _approved_sponsor_with_area_record()
        payload = create_site_payload(sponsor["id"], area_record["id"], name="Injected Park")
        payload["eligibility_basis"] = "AREA_ELIGIBLE"
        payload["voided_day_count"] = 99

        site = validate_success(
            api.create_site(payload, make_sponsor_admin_headers(sponsor["id"])), 201
        )

        assert_site(site)
        assert site["eligibility_basis"] == "UNDETERMINED", (
            "a new site opens UNDETERMINED whatever basis the request carried, got "
            f"{site['eligibility_basis']}"
        )
        assert site["voided_day_count"] == 0, (
            f"a new site opens with voided_day_count 0, got {site['voided_day_count']}"
        )

    def test_site_registration_naming_an_unknown_area_record_reports_not_found(self, api):
        """PRD §3.4: "A site whose `site_type` is `OPEN`, `RESTRICTED_OPEN` or `MIGRANT` must name an `area_eligibility_record_id`; omitting it is rejected with `ERR_AREA_RECORD_REQUIRED`, and naming a record that does not exist is rejected with `ERR_AREA_RECORD_NOT_FOUND`."

        Design: Corner/entities/site_creation_with_unknown_area_record_returns_not_found
        """
        set_clock(INTAKE_CLOCK)
        sponsor = create_approved_sponsor()
        payload = create_site_payload(
            sponsor["id"], NON_EXISTENT_UUID, name="Orphan Park", site_type="OPEN"
        )

        response = api.create_site(payload, make_sponsor_admin_headers(sponsor["id"]))

        validate_error(response, ApiErrorId.ERR_AREA_RECORD_NOT_FOUND.value)
        assert _site_count_for_sponsor(api, sponsor["id"]) == 0, (
            "an unresolvable area record must not leave an orphan site behind"
        )


class TestAreaEligibilityRecordContract:
    """The curated income record's declared value sets."""

    def test_area_record_with_data_source_outside_its_enum_is_malformed(self, api):
        """PRD §2.6: "Request well-formedness: required fields present, enum members drawn from their declared sets, integers non-negative where declared, dates written as `YYYY-MM-DD`, clock times written as `HH:MM` on a 24-hour clock, `limit` between 1 and 100, `offset` at least 0, and every `decision`, `to_status` and `method` value inside its declared set — `ERR_INVALID_REQUEST`."

        Design: Corner/entities/area_record_invalid_enum_data_source_rejected
        """
        set_clock(INTAKE_CLOCK)
        payload = create_area_eligibility_record_payload(data_source="GUESSWORK")

        response = api.create_area_eligibility_record(payload, REVIEWER_HEADERS)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestMealCountEntryContract:
    """The append-only shape of a point-of-service count row and the attribution it stores."""

    @staticmethod
    def _counted_day() -> tuple:
        """One operating site with an OPEN service day carrying a single 30-meal LUNCH count."""
        scenario = setup_program_baseline(include_budget=False)
        day = create_open_day(scenario["site"]["id"])
        entry = record_meal_count(
            day, meal_type="LUNCH", first_meals=30, second_meals=0, adult_meals=0
        )
        return scenario, day, entry

    def test_meal_count_entry_carries_no_updated_at_and_no_version(self, api):
        """PRD §2.5: "Three record types are append-only and immutable once written, and they are the exception: an `AreaEligibilityRecord`, a `MealCountEntry` and a `HoldingLogEntry` each carry only `id` and `created_at`."

        Design: Corner/entities/meal_count_entry_is_immutable_append_only_with_no_version
        """
        scenario, _, entry = self._counted_day()

        read = validate_success(
            api.get_meal_count_entry(entry["id"], scenario["supervisor_headers"])
        )

        assert_append_only_row(read)
        assert_meal_count_entry(read)
        assert read["created_at"].startswith(SERVICE_DAY_PREFIX), (
            "created_at is stamped from the logical clock reading "
            f"{SERVICE_DAY_CLOCK}, got {read['created_at']}"
        )

    def test_meal_count_entry_posted_without_a_reversal_target_is_an_original(self, api):
        """PRD §3.6: "Supplying `reversal_of_entry_id` sets the new entry's `entry_kind` to `REVERSAL` and its three counts are applied to the day as negatives; leaving the field out sets `entry_kind` to `ORIGINAL`."

        Design: Corner/entities/meal_count_entry_is_immutable_append_only_with_no_version
        """
        scenario, _, entry = self._counted_day()

        read = validate_success(
            api.get_meal_count_entry(entry["id"], scenario["supervisor_headers"])
        )

        assert read["entry_kind"] == "ORIGINAL", (
            "an entry posted with no reversal_of_entry_id is an ORIGINAL, got "
            f"{read['entry_kind']}"
        )

    def test_meal_count_entry_stores_its_marginal_reimbursable_contribution(self, api):
        """PRD §3.6: "Each individual entry also records its own contribution, and that contribution is a **marginal delta** rather than an independent computation: the day's totals are computed immediately before the entry is inserted and again immediately after, and the entry stores the differences as `reimbursable_first_meals` and `reimbursable_second_meals`."

        Design: Corner/entities/meal_count_entry_is_immutable_append_only_with_no_version
        """
        scenario, day, entry = self._counted_day()

        read = validate_success(
            api.get_meal_count_entry(entry["id"], scenario["supervisor_headers"])
        )
        day_read = validate_success(
            api.get_meal_service_day(day["id"], scenario["supervisor_headers"])
        )

        assert read["reimbursable_first_meals"] == 30, (
            "the 30 first meals sit under both the attendance ceiling of 200 and the 150 LUNCH "
            f"meals produced, so the entry contributes all 30, got {read['reimbursable_first_meals']}"
        )
        assert read["reimbursable_second_meals"] == 0, (
            "the entry counted no second meals, so it contributes none, got "
            f"{read['reimbursable_second_meals']}"
        )
        assert day_read["counted_first_meals"] == 30, (
            f"the day nets 30 counted first meals, got {day_read['counted_first_meals']}"
        )
