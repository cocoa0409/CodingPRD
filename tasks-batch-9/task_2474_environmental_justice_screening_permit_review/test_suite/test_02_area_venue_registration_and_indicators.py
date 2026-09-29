"""Reference-data registration and burden-indicator filing.

Screening areas, venues, facilities and burden indicators are the foundation
every later workflow reads from, so their defaults, their validation and their
optimistic version guard are proved here.
"""

from test_helpers import (
    CATEGORY_HEALTH,
    DATA_STATUS_CURRENT,
    DESIGNATION_UNDESIGNATED,
    FACILITY_TYPE_MINOR_SOURCE,
    INDICATOR_STATUS_ACTIVE,
    UNKNOWN_AREA_FK,
    UNKNOWN_AREA_ID,
    VENUE_ACTIVE,
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    ApiErrorId,
    assert_amount,
    assert_area_components,
    assert_area_scores,
    assert_array_envelope,
    assert_common_fields,
    assert_created,
    assert_empty_listing,
    assert_field,
    assert_object_envelope,
    assert_page,
    assert_rejected,
    burden_indicator_payload,
    facility_payload,
    page_params,
    read_area,
    screening_area_payload,
    venue_payload,
)


class TestScreeningAreaRegistration:
    """PRD §3.1 pins every derived field of a freshly registered area."""

    def test_registration_applies_the_declared_zero_baseline(self, api, clock):
        """A brand-new area reports the whole empty-input-set baseline at once.

        PRD §3.1: "A freshly registered area has no indicators, so its scoring
        pass runs over an empty input set: `demographic_component_statewide`,
        `health_component_statewide` and `pollution_component_statewide` are all
        0.00, `ej_screen_score_statewide` and `ej_screen_score_county` are both
        0.00, `active_indicator_count` is 0, `enforcement_burden_points` is 0,
        `permitted_load_tpy` is 0.00, `open_complaint_count` and `open_plan_count`
        are both 0, `designation` is `UNDESIGNATED` and `data_status` is
        `CURRENT`."
        PRD §3.1: "That same 10.0 percent threshold sets the boolean
        `translation_required` on the area, which is recomputed on every scoring
        run."

        Design: Corner/entities/screening_area_creation_applies_computed_defaults_and_envelope
        """
        response = api.create_screening_area(
            screening_area_payload(
                area_code="BG-06-901",
                county="Madera",
                population=900,
                limited_english_pct=5.0,
                baseline_load_tpy=100.00,
            ),
            ADMIN_HEADERS,
        )

        area = assert_created(response)
        assert_object_envelope(response)
        assert_common_fields(area, expected_version=1)

        assert_area_components(area, pollution=0.00, health=0.00, demographic=0.00)
        assert_area_scores(area, statewide=0.00, county=0.00)
        assert_field(area, "active_indicator_count", 0)
        assert_field(area, "enforcement_burden_points", 0)
        assert_amount(area.get("permitted_load_tpy"), 0.00, "permitted_load_tpy")
        assert_field(area, "open_plan_count", 0)
        assert_field(area, "open_complaint_count", 0)
        assert_field(area, "designation", DESIGNATION_UNDESIGNATED)
        assert_field(area, "data_status", DATA_STATUS_CURRENT)
        # The translation trigger sits at 10.0 percent, so 5.0 leaves it clear.
        assert_field(area, "translation_required", False)

    def test_duplicate_area_code_is_rejected(self, api, area_a):
        """A second area may not reuse a registered `area_code`.

        PRD §2.10: "Screening area: `area_code` is not already in use — otherwise
        `ERR_AREA_CODE_DUPLICATE` (409)."

        Design: Corner/validations/duplicate_area_code_rejected
        """
        response = api.create_screening_area(
            screening_area_payload(
                area_code="BG-06-101",
                county="Kern",
                population=3900,
                limited_english_pct=4.0,
                baseline_load_tpy=150.00,
                required_translation_languages=[],
            ),
            ADMIN_HEADERS,
        )

        assert_rejected(response, ApiErrorId.AREA_CODE_DUPLICATE)

        original = read_area(api, area_a["area_id"])
        assert_field(original, "population", 4200)
        assert_amount(original.get("baseline_load_tpy"), 400.00, "baseline_load_tpy")

    def test_translation_languages_are_required_at_the_ten_percent_trigger(
        self, api, clock
    ):
        """The language-access requirement switches on at exactly 10.0 percent.

        PRD §3.1: "when `limited_english_pct` is **at least 10.0**,
        `required_translation_languages` must be non-empty, and an empty list in
        that case is refused with `ERR_TRANSLATION_LANGUAGES_REQUIRED`."

        Design: Corner/validations/translation_languages_required_when_limited_english_at_trigger
        """
        above = api.create_screening_area(
            screening_area_payload(
                area_code="BG-06-910",
                county="Kern",
                population=3000,
                limited_english_pct=12.5,
                baseline_load_tpy=300.00,
                required_translation_languages=[],
            ),
            ADMIN_HEADERS,
        )
        assert_rejected(above, ApiErrorId.TRANSLATION_LANGUAGES_REQUIRED)

        below = api.create_screening_area(
            screening_area_payload(
                area_code="BG-06-911",
                county="Kern",
                population=3000,
                limited_english_pct=9.9,
                baseline_load_tpy=300.00,
                required_translation_languages=[],
            ),
            ADMIN_HEADERS,
        )
        accepted = assert_created(below)

        stored = read_area(api, accepted["id"])
        assert_field(stored, "translation_required", False)
        assert_field(stored, "required_translation_languages", [])

    def test_unknown_area_id_returns_the_area_not_found_code(self, api, clock):
        """A path id that resolves to nothing yields the family's 404.

        PRD §2.9: "Each resource family has its own not-found code:
        `ERR_SCREENING_AREA_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`,
        `ERR_PLAN_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`,
        `ERR_CONDITION_NOT_FOUND`, `ERR_DECISION_NOT_FOUND`,
        `ERR_COMPLAINT_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."

        Design: Corner/entities/screening_area_get_with_unknown_id_returns_not_found
        """
        response = api.get_screening_area(UNKNOWN_AREA_ID, ANALYST_HEADERS)

        assert_rejected(response, ApiErrorId.SCREENING_AREA_NOT_FOUND)

    def test_recertifying_a_current_area_is_rejected(self, api, area_h):
        """Recertification only makes sense for burden data that went stale.

        PRD §3.1: "Recertification of an area whose `data_status` is already
        `CURRENT` is refused with `ERR_AREA_NOT_STALE`."

        Design: Corner/errors/recertify_on_a_current_area_rejected
        """
        response = api.recertify_screening_area(area_h["area_id"], ADMIN_HEADERS)

        assert_rejected(response, ApiErrorId.AREA_NOT_STALE)

        stored = read_area(api, area_h["area_id"])
        assert_field(stored, "data_status", DATA_STATUS_CURRENT)
        assert_field(stored, "version", 1)


class TestVenueRegistration:
    """PRD §3.5 gives a venue's status a declared default."""

    def test_venue_status_defaults_to_active_when_omitted(self, api, clock):
        """Omitting `status` registers an active venue with an empty ledger.

        PRD §3.5: "A venue's `status` may be supplied at registration and
        defaults to `ACTIVE`; the alternative is `DECOMMISSIONED`." and "Each
        venue carries a slot-occupancy ledger, `booked_meeting_count`, which
        starts at 0 and always equals the number of meetings currently
        `SCHEDULED` at that venue."

        Design: Corner/entities/venue_status_defaults_to_active_when_omitted
        """
        response = api.create_venue(
            venue_payload(
                name="Madera Library Meeting Room",
                address="45 Yosemite Ave, Madera CA",
                capacity=60,
                transit_accessible=True,
                ada_accessible=True,
                interpretation_capable=False,
            ),
            ADMIN_HEADERS,
        )

        venue = assert_created(response)
        assert_field(venue, "status", VENUE_ACTIVE)
        assert_field(venue, "booked_meeting_count", 0)
        assert_field(venue, "interpretation_capable", False)


class TestFacilityRegistration:
    """PRD §2.10 rung 6 resolves body foreign keys before anything else."""

    def test_facility_naming_an_unknown_area_is_rejected(self, api, clock):
        """A facility cannot be registered into an area that does not exist.

        PRD §2.9: "Foreign keys carried in a request body are resolved after path
        identifiers and before any business rule, and they are checked in this
        declaration order: `screening_area_id`, then `facility_id`, then
        `permit_application_id`, then `participation_plan_id`, then `venue_id`,
        then `prior_application_id`." and "The first unresolved key decides the
        error, using the same per-family codes; both `permit_application_id` and
        `prior_application_id` report `ERR_APPLICATION_NOT_FOUND`."

        Design: Corner/entities/facility_create_with_unknown_screening_area_rejected
        """
        response = api.create_facility(
            facility_payload(
                screening_area_id=UNKNOWN_AREA_FK,
                name="Ghost Plant",
                facility_type=FACILITY_TYPE_MINOR_SOURCE,
                distance_to_area_centroid_m=900,
            ),
            ADMIN_HEADERS,
        )

        assert_rejected(response, ApiErrorId.SCREENING_AREA_NOT_FOUND)


class TestBurdenIndicatorFiling:
    """PRD §3.1 and §2.10 items 12-14 police every indicator filing."""

    def test_missing_county_percentile_is_a_malformed_request(self, api, area_h):
        """A required numeric field cannot simply be left out.

        PRD §2.10: "The body and query string are well formed: required fields
        present, types correct, enum members recognised, numeric ranges respected
        (`proposed_emissions_tpy` greater than 0, `population` at least 1,
        `capacity` at least 1, `ends_at` strictly later than `starts_at`, `limit`
        within 1 through 100, `offset` at least 0, dates and timestamps valid ISO
        8601) — otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

        Design: Corner/entities/burden_indicator_missing_county_percentile_rejected
        """
        response = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="PM25",
                raw_value=10.00,
                statewide_percentile=70.00,
                county_percentile=None,
                vintage_year=2024,
                expected_screening_area_version=area_h["area_v0"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.INVALID_REQUEST)

        stored = read_area(api, area_h["area_id"])
        assert_field(stored, "active_indicator_count", 0)
        assert_field(stored, "version", 1)

    def test_percentile_above_one_hundred_is_out_of_range(self, api, area_h):
        """Percentiles are bounded on both sides, inclusive.

        PRD §3.1: "Both percentiles must lie between 0.00 and 100.00 inclusive,
        or the filing is refused with `ERR_PERCENTILE_OUT_OF_RANGE`."

        Design: Corner/entities/burden_indicator_percentile_above_range_rejected
        """
        response = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="PM25",
                raw_value=10.00,
                statewide_percentile=105.00,
                county_percentile=60.00,
                vintage_year=2024,
                expected_screening_area_version=area_h["area_v0"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.PERCENTILE_OUT_OF_RANGE)

        assert_field(read_area(api, area_h["area_id"]), "active_indicator_count", 0)
        assert_empty_listing(
            api.list_burden_indicators(area_h["area_id"], ANALYST_HEADERS)
        )

    def test_category_disagreeing_with_the_code_is_rejected(self, api, area_h):
        """`PM25` is a pollution indicator and may not be filed as health data.

        PRD §3.1: "A submitted `category` that disagrees with the code's canonical
        family is refused with `ERR_INDICATOR_CATEGORY_MISMATCH`."

        Design: Corner/validations/indicator_category_mismatch_rejected
        """
        response = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="PM25",
                raw_value=12.40,
                statewide_percentile=70.00,
                county_percentile=60.00,
                vintage_year=2024,
                expected_screening_area_version=area_h["area_v0"],
                category=CATEGORY_HEALTH,
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(response, ApiErrorId.INDICATOR_CATEGORY_MISMATCH)

        stored = read_area(api, area_h["area_id"])
        assert_field(stored, "version", 1)
        assert_field(stored, "active_indicator_count", 0)

    def test_vintage_year_outside_the_validity_window_is_rejected(self, api, area_h):
        """2020 is six years behind the 2026 clock; 2021 is exactly five.

        PRD §3.1: "`vintage_year` must be no earlier than the clock year minus
        **five** and no later than the clock year itself, both bounds inclusive,
        or the filing is refused with `ERR_INDICATOR_VINTAGE_INVALID`."

        Design: Corner/validations/indicator_vintage_older_than_validity_window_rejected
        """
        too_old = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="PM25",
                raw_value=12.40,
                statewide_percentile=70.00,
                county_percentile=60.00,
                vintage_year=2020,
                expected_screening_area_version=area_h["area_v0"],
            ),
            ANALYST_HEADERS,
        )
        assert_rejected(too_old, ApiErrorId.INDICATOR_VINTAGE_INVALID)

        on_the_boundary = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="PM25",
                raw_value=12.40,
                statewide_percentile=70.00,
                county_percentile=60.00,
                vintage_year=2021,
                expected_screening_area_version=area_h["area_v0"],
            ),
            ANALYST_HEADERS,
        )
        indicator = assert_created(on_the_boundary)
        assert_field(indicator, "area_version_after", 2)

        stored = read_area(api, area_h["area_id"])
        assert_field(stored, "active_indicator_count", 1)
        assert_field(stored, "version", 2)

    def test_stale_area_version_guard_blocks_a_second_filing(self, api, area_h):
        """The version captured before the first filing cannot drive the second.

        PRD §2.7: "Filing a burden indicator (`POST /ej/burden-indicators`)
        requires `expected_screening_area_version`, carrying the client's last
        observed `version` of the target `ScreeningArea`." and "If it does not
        equal that area's current `version`, the request is rejected with
        `ERR_STALE_AREA_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_area_version_on_indicator_create_rejected
        """
        first = assert_created(
            api.create_burden_indicator(
                burden_indicator_payload(
                    screening_area_id=area_h["area_id"],
                    indicator_code="PM25",
                    raw_value=12.40,
                    statewide_percentile=70.00,
                    county_percentile=60.00,
                    vintage_year=2024,
                    expected_screening_area_version=area_h["area_v0"],
                ),
                ANALYST_HEADERS,
            )
        )
        assert_field(first, "area_version_after", 2)

        stale = api.create_burden_indicator(
            burden_indicator_payload(
                screening_area_id=area_h["area_id"],
                indicator_code="ASTHMA_ED_RATE",
                raw_value=55.00,
                statewide_percentile=65.00,
                county_percentile=50.00,
                vintage_year=2024,
                expected_screening_area_version=area_h["area_v0"],
            ),
            ANALYST_HEADERS,
        )

        assert_rejected(stale, ApiErrorId.STALE_AREA_VERSION)

        stored = read_area(api, area_h["area_id"])
        assert_field(stored, "version", 2)
        assert_field(stored, "active_indicator_count", 1)
        assert_page(
            api.list_burden_indicators(area_h["area_id"], ANALYST_HEADERS),
            expected_rows=1,
            expected_total=1,
            expected_has_more=False,
        )

    def test_indicator_listing_paginates_with_a_stable_total(self, api, area_a):
        """Two pages of two rows report the same total and flip `has_more`.

        PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`
        and `has_more` inside the `meta` object of the envelope." and "Unless a
        specific endpoint states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/burden_indicator_listing_paginates_with_total_count
        """
        first_page = api.list_burden_indicators(
            area_a["area_id"],
            ANALYST_HEADERS,
            params=page_params(limit=2, offset=0, status=INDICATOR_STATUS_ACTIVE),
        )
        assert_array_envelope(first_page)
        assert_page(first_page, expected_rows=2, expected_total=4, expected_has_more=True)

        second_page = api.list_burden_indicators(
            area_a["area_id"],
            ANALYST_HEADERS,
            params=page_params(limit=2, offset=2, status=INDICATOR_STATUS_ACTIVE),
        )
        assert_page(second_page, expected_rows=2, expected_total=4, expected_has_more=False)

        stored = read_area(api, area_a["area_id"])
        assert_field(stored, "active_indicator_count", 4)
        assert_amount(
            stored.get("ej_screen_score_statewide"), 74.03, "ej_screen_score_statewide"
        )
