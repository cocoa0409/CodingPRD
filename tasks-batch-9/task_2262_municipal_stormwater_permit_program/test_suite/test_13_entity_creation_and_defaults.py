"""What creation writes by itself, and what a request may not write for it."""

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_cents, assert_common_fields, assert_page_meta
from test_helpers.test_users import (
    CLERK_HEADERS,
    IDDE_HEADERS,
    IDDE_ONE,
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    OPERATIONS_HEADERS,
    OPERATIONS_ONE,
)

CLIENT_SUPPLIED_ID = "11111111-1111-1111-1111-111111111111"


class TestPermitTermCreationDefaults:
    """A term created from the three mandatory fields alone."""

    def test_01_every_optional_field_falls_back_to_its_declared_default(self):
        """Three fields in, and the server writes the rest.

        PRD: "`tmdl_applicable` defaults to false, in which case both
        `tmdl_pollutant` and `tmdl_wla_lb_per_year` remain null." And: "Two utility
        parameters are also set at this point and both are optional: `eru_sqft`, the
        equivalent residential unit denominator in square feet of impervious area,
        which defaults to 3000 and may not be below 100; and
        `funding_target_cents`, the annual program funding target in cents, which
        defaults to 0 and may not be negative."

        Design: Corner/entities/permit_term_creation_applies_every_declared_default
        """
        term = validate_success(
            api_client.create_permit_term(
                factories.permit_term_payload(
                    permit_number="MS4-2026-DEFAULTS",
                    tmdl_applicable=None,
                    eru_sqft=None,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert term["tmdl_applicable"] is False, "the allocation flag defaults to false"
        assert term["tmdl_pollutant"] is None, "no pollutant is named without a flag"
        assert term["tmdl_wla_lb_per_year"] is None, "no allocation ceiling is written"
        assert term["eru_sqft"] == 3000, "the equivalent residential unit defaults to 3000"
        assert_cents(term["funding_target_cents"], 0, "funding_target_cents")

    def test_02_the_derived_posture_and_ledger_start_empty(self):
        """The whole posture census reads zero on a term with no children.

        PRD: "A newly created term has `status` `DRAFT`, `compliance_posture`
        `COMPLIANT`, and `behind_measure_count`, `exceeding_outfall_count`,
        `total_assessed_penalty_cents` and `projected_annual_revenue_cents` all at 0,
        with `funding_adequacy_status` reading `ADEQUATE`; `activated_at`,
        `expired_at` and `last_compiled_at` are all null."

        Design: Corner/entities/permit_term_creation_applies_every_declared_default
        """
        response = api_client.create_permit_term(
            factories.permit_term_payload(
                permit_number="MS4-2026-DEFAULTS", tmdl_applicable=None, eru_sqft=None
            ),
            MANAGER_HEADERS,
        )
        term = validate_success(response, 201)

        assert response.json()["response_type"] == "object", (
            "a single created resource is returned as an object"
        )
        assert term["status"] == "DRAFT", "a new term opens in DRAFT"
        assert term["compliance_posture"] == "COMPLIANT", "an empty term is compliant"
        assert term["behind_measure_count"] == 0, "no measure exists to be behind"
        assert term["exceeding_outfall_count"] == 0, "no outfall has been assessed"
        assert_cents(
            term["total_assessed_penalty_cents"], 0, "total_assessed_penalty_cents"
        )
        assert_cents(
            term["projected_annual_revenue_cents"], 0, "projected_annual_revenue_cents"
        )
        assert term["funding_adequacy_status"] == "ADEQUATE", (
            "a zero target is met by zero revenue"
        )
        assert term["activated_at"] is None, "nothing has been activated"
        assert term["expired_at"] is None, "nothing has expired"
        assert term["last_compiled_at"] is None, "nothing has been compiled"

    def test_03_the_four_system_managed_properties_are_minted_by_the_server(self):
        """Version one, and the two timestamps agree before any mutation.

        PRD: "`version` (integer): an integer that increments by one on every
        mutation of the row." And: "`updated_at` (string): an ISO 8601 UTC timestamp
        in the same format, refreshed on every mutation of the row, including
        mutations that only rewrite derived fields."

        Design: Corner/entities/permit_term_creation_applies_every_declared_default
        """
        term = validate_success(
            api_client.create_permit_term(
                factories.permit_term_payload(
                    permit_number="MS4-2026-DEFAULTS", tmdl_applicable=None, eru_sqft=None
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert_common_fields(term, expected_version=1)
        assert term["updated_at"] == term["created_at"], (
            "an unmutated row carries the same two timestamps"
        )


class TestPermitTermRetrievalAndListing:
    """Three terms, two pages and one filter."""

    @pytest.fixture
    def three_terms(self):
        """One DRAFT term per permit year, created oldest first."""
        first = fx.create_permit_term(
            permit_number="MS4-2024-A",
            term_start_date="2024-01-01",
            term_end_date="2024-12-31",
        )
        second = fx.create_permit_term(
            permit_number="MS4-2025-A",
            term_start_date="2025-01-01",
            term_end_date="2025-12-31",
        )
        third = fx.create_permit_term(
            permit_number="MS4-2026-A",
            term_start_date="2026-01-01",
            term_end_date="2026-12-31",
        )
        return [first, second, third]

    def test_04_the_first_page_reports_the_full_count_and_more_to_come(
        self, three_terms
    ):
        """Two of three rows, and `has_more` says so.

        PRD: "Every list response reports `limit`, `offset`, `total_count` and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/permit_term_retrieval_and_listing_report_pagination_metadata
        """
        response = api_client.list_permit_terms(MANAGER_HEADERS, {"limit": 2, "offset": 0})
        terms, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array", (
            "a collection is returned as an array"
        )
        assert len(terms) == 2, f"a limit of 2 returns two rows, got {len(terms)}"
        assert_page_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

    def test_05_the_last_page_carries_the_remainder_and_closes(self, three_terms):
        """One row remains beyond the offset, and nothing after it.

        PRD: "`offset` is the number of rows skipped before the page begins; it
        defaults to 0 and may not be negative."

        Design: Corner/entities/permit_term_retrieval_and_listing_report_pagination_metadata
        """
        terms, meta = validate_paginated(
            api_client.list_permit_terms(MANAGER_HEADERS, {"limit": 2, "offset": 2})
        )

        assert len(terms) == 1, f"one row is left past the offset, got {len(terms)}"
        assert_page_meta(meta, limit=2, offset=2, total_count=3, has_more=False)

    def test_06_a_single_read_answers_with_the_named_row(self, three_terms):
        """The middle term is fetched by its own identifier.

        PRD: "The `data` field contains the resource object or an array of resource
        objects."

        Design: Corner/entities/permit_term_retrieval_and_listing_report_pagination_metadata
        """
        term = validate_success(
            api_client.get_permit_term(three_terms[1]["id"], MANAGER_HEADERS)
        )

        assert term["id"] == three_terms[1]["id"], "the named row is returned"
        assert term["permit_number"] == "MS4-2025-A", (
            "the second term is the 2025 permit"
        )

    def test_07_a_filter_that_matches_nothing_empties_the_count_too(self, three_terms):
        """`total_count` follows the filter, not the table.

        PRD: "Collections accept optional equality filters, and a filter that is
        omitted does not narrow the result. Permit terms filter on `status` and
        `compliance_posture`."

        Design: Corner/entities/permit_term_retrieval_and_listing_report_pagination_metadata
        """
        terms, meta = validate_paginated(
            api_client.list_permit_terms(MANAGER_HEADERS, {"status": "ACTIVE"})
        )

        assert terms == [], "no term has been activated"
        assert meta["total_count"] == 0, (
            f"the count is the filtered count, got {meta['total_count']}"
        )


NOT_FOUND_READS = [
    (
        "permit_term",
        ApiErrorId.ERR_PERMIT_TERM_NOT_FOUND,
        lambda: api_client.get_permit_term(NON_EXISTENT_UUID, MANAGER_HEADERS),
    ),
    (
        "control_measure",
        ApiErrorId.ERR_CONTROL_MEASURE_NOT_FOUND,
        lambda: api_client.get_control_measure(NON_EXISTENT_UUID, MANAGER_HEADERS),
    ),
    (
        "outfall",
        ApiErrorId.ERR_OUTFALL_NOT_FOUND,
        lambda: api_client.get_outfall(NON_EXISTENT_UUID, MANAGER_HEADERS),
    ),
    (
        "observation",
        ApiErrorId.ERR_OBSERVATION_NOT_FOUND,
        lambda: api_client.validate_observation(
            NON_EXISTENT_UUID,
            factories.validate_observation_payload("VALIDATE"),
            MANAGER_HEADERS,
        ),
    ),
    (
        "illicit_discharge_case",
        ApiErrorId.ERR_CASE_NOT_FOUND,
        lambda: api_client.get_illicit_discharge_case(NON_EXISTENT_UUID, IDDE_HEADERS),
    ),
    (
        "construction_site",
        ApiErrorId.ERR_CONSTRUCTION_SITE_NOT_FOUND,
        lambda: api_client.get_construction_site(NON_EXISTENT_UUID, INSPECTOR_HEADERS),
    ),
    (
        "post_construction_facility",
        ApiErrorId.ERR_FACILITY_NOT_FOUND,
        lambda: api_client.get_post_construction_facility(
            NON_EXISTENT_UUID, INSPECTOR_HEADERS
        ),
    ),
    (
        "inspection",
        ApiErrorId.ERR_INSPECTION_NOT_FOUND,
        lambda: api_client.get_inspection(NON_EXISTENT_UUID, INSPECTOR_HEADERS),
    ),
    (
        "enforcement_action",
        ApiErrorId.ERR_ENFORCEMENT_ACTION_NOT_FOUND,
        lambda: api_client.get_enforcement_action(NON_EXISTENT_UUID, OFFICER_HEADERS),
    ),
    (
        "account",
        ApiErrorId.ERR_ACCOUNT_NOT_FOUND,
        lambda: api_client.get_account(NON_EXISTENT_UUID, CLERK_HEADERS),
    ),
    (
        "fee_credit_application",
        ApiErrorId.ERR_CREDIT_APPLICATION_NOT_FOUND,
        lambda: api_client.get_fee_credit_application(NON_EXISTENT_UUID, CLERK_HEADERS),
    ),
    (
        "annual_report",
        ApiErrorId.ERR_ANNUAL_REPORT_NOT_FOUND,
        lambda: api_client.get_annual_report(NON_EXISTENT_UUID, MANAGER_HEADERS),
    ),
]


class TestPathIdentifiersThatResolveToNothing:
    """Each entity kind answers with the 404 that belongs to it."""

    @pytest.mark.parametrize(
        "entity, error_id, call",
        NOT_FOUND_READS,
        ids=[case[0] for case in NOT_FOUND_READS],
    )
    def test_08_each_entity_returns_its_own_not_found_code(
        self, draft_term, entity, error_id, call
    ):
        """A well-formed identifier that exists in no table is a 404.

        PRD: "**Path existence.** Every identifier in the path must resolve to a
        stored row, yielding the 404 belonging to that entity kind."

        Design: Corner/entities/path_ids_that_resolve_to_nothing_return_the_entity_specific_not_found
        """
        error = validate_error(call(), error_id.value, 404)

        assert error["error_id"] == error_id.value, (
            f"the {entity} read must name its own not-found code"
        )
        assert isinstance(error["message"], str) and error["message"], (
            f"the {entity} error must carry a human-readable message"
        )

    def test_09_the_stored_row_is_untouched_by_every_missed_lookup(self, draft_term):
        """Twelve failed reads leave the one real row at version one.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/entities/path_ids_that_resolve_to_nothing_return_the_entity_specific_not_found
        """
        for _, _, call in NOT_FOUND_READS:
            call()

        term = fx.read_term(draft_term["id"])
        assert term["version"] == 1, "the stored term was never mutated"
        assert term["status"] == "DRAFT", "the stored term is still in DRAFT"


BODY_FK_CASES = {
    "control_measure_names_no_term": (
        ApiErrorId.ERR_PERMIT_TERM_NOT_FOUND,
        lambda ctx: api_client.create_control_measure(
            factories.control_measure_payload(
                NON_EXISTENT_UUID, "PUBLIC_EDUCATION", measurable_goal_target=12.00
            ),
            MANAGER_HEADERS,
        ),
    ),
    "facility_names_no_site": (
        ApiErrorId.ERR_CONSTRUCTION_SITE_NOT_FOUND,
        lambda ctx: api_client.create_post_construction_facility(
            factories.facility_payload(
                NON_EXISTENT_UUID,
                "PRIVATE",
                design_capacity_cf=4000.00,
                service_area_acres=1.00,
            ),
            INSPECTOR_HEADERS,
        ),
    ),
    "credit_application_names_no_account": (
        ApiErrorId.ERR_ACCOUNT_NOT_FOUND,
        lambda ctx: api_client.create_fee_credit_application(
            factories.credit_application_payload(
                NON_EXISTENT_UUID, ctx["account"]["version"], requested_credit_pct=0.1000
            ),
            CLERK_HEADERS,
        ),
    ),
    "enforcement_action_names_no_case": (
        ApiErrorId.ERR_CASE_NOT_FOUND,
        lambda ctx: api_client.create_enforcement_action(
            factories.enforcement_action_payload(
                "NOTICE_OF_VIOLATION",
                illicit_discharge_case_id=NON_EXISTENT_UUID,
                violation_days=0,
            ),
            OFFICER_HEADERS,
        ),
    ),
    "annual_report_names_no_term": (
        ApiErrorId.ERR_PERMIT_TERM_NOT_FOUND,
        lambda ctx: api_client.create_annual_report(
            factories.annual_report_payload(NON_EXISTENT_UUID), MANAGER_HEADERS
        ),
    ),
}


class TestBodyForeignKeysThatResolveToNothing:
    """A key in the body is dereferenced before any business rule runs."""

    @pytest.fixture
    def fk_context(self):
        """A real DRAFT term and a real account, so only the key under test is bogus."""
        term = fx.create_permit_term()
        account = fx.create_account(
            term["id"],
            parcel_id="P-1000",
            parcel_class="COMMERCIAL",
            impervious_area_sqft=9020.0,
            owner_name="Ada Owner",
        )
        return {"term": term, "account": account}

    @pytest.mark.parametrize("case_key", list(BODY_FK_CASES), ids=list(BODY_FK_CASES))
    def test_10_an_unresolvable_body_key_is_the_named_entity_404(
        self, fk_context, case_key
    ):
        """The 404 belongs to the entity the key points at.

        PRD: "**Body referential integrity.** Every foreign key supplied in a request
        body must resolve, again yielding the entity's 404. This layer sits
        deliberately above every fiscal and safety rule: a credit application naming a
        facility that does not exist is `ERR_FACILITY_NOT_FOUND`, never a
        credit-ceiling failure."

        Design: Corner/entities/body_foreign_keys_that_resolve_to_nothing_return_not_found_at_priority_50
        """
        error_id, call = BODY_FK_CASES[case_key]

        validate_error(call(fk_context), error_id.value, 404)

    def test_11_the_missing_account_outranks_the_version_guard_it_satisfies(
        self, fk_context
    ):
        """The application carries the live version of a real account and still 404s.

        PRD: "**Optimistic concurrency.** The version guards of §2.6 fire here, before
        any state or business rule, so that a stale writer is told it is stale rather
        than told its business intent is wrong."

        Design: Corner/entities/body_foreign_keys_that_resolve_to_nothing_return_not_found_at_priority_50
        """
        current = fx.read_account(fk_context["account"]["id"])
        assert current["version"] == fk_context["account"]["version"], (
            "the captured version is still the account's current version"
        )

        response = api_client.create_fee_credit_application(
            factories.credit_application_payload(
                NON_EXISTENT_UUID, current["version"], requested_credit_pct=0.1000
            ),
            CLERK_HEADERS,
        )

        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)

    def test_12_no_partial_child_row_survives_any_of_the_five_refusals(self, fk_context):
        """The real term gained neither a measure nor a report.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/entities/body_foreign_keys_that_resolve_to_nothing_return_not_found_at_priority_50
        """
        for _, call in BODY_FK_CASES.values():
            call(fk_context)

        _, measure_meta = validate_paginated(
            api_client.list_term_control_measures(
                fk_context["term"]["id"], MANAGER_HEADERS
            )
        )
        assert measure_meta["total_count"] == 0, (
            f"no measure was written, got {measure_meta['total_count']}"
        )

        _, report_meta = validate_paginated(
            api_client.list_term_annual_reports(fk_context["term"]["id"], MANAGER_HEADERS)
        )
        assert report_meta["total_count"] == 0, (
            f"no report was written, got {report_meta['total_count']}"
        )


def _term_without_end_date():
    return factories.permit_term_payload(
        permit_number="MS4-2027-A",
        term_start_date="2027-01-01",
        term_end_date=None,
        tmdl_applicable=None,
        eru_sqft=None,
    )


def _site_without_acreage(term_id):
    payload = factories.construction_site_payload(
        term_id, site_name="SITE-NULL", operator_name="Nullworks"
    )
    del payload["disturbed_acres"]
    return payload


MISSING_FIELD_CASES = {
    "permit_term_without_end_date": lambda ctx: api_client.create_permit_term(
        _term_without_end_date(), MANAGER_HEADERS
    ),
    "outfall_without_priority_tier": lambda ctx: api_client.create_outfall(
        factories.outfall_payload(
            ctx["term"]["id"],
            "OF-91",
            drainage_area_acres=12.00,
            priority_tier=None,
            baseline_concentration_mg_per_l=0.20,
            design_runoff_kl=8000.00,
        ),
        MANAGER_HEADERS,
    ),
    "site_without_disturbed_acres": lambda ctx: api_client.create_construction_site(
        _site_without_acreage(ctx["term"]["id"]), INSPECTOR_HEADERS
    ),
}


RANGE_AND_ENUM_CASES = {
    "priority_tier_outside_the_enum": lambda ctx: api_client.create_outfall(
        factories.outfall_payload(
            ctx["term"]["id"],
            "OF-92",
            drainage_area_acres=12.00,
            priority_tier="URGENT",
            baseline_concentration_mg_per_l=0.20,
            design_runoff_kl=8000.00,
        ),
        MANAGER_HEADERS,
    ),
    "weight_above_the_range": lambda ctx: api_client.create_control_measure(
        factories.control_measure_payload(
            ctx["term"]["id"], "PUBLIC_EDUCATION", measurable_goal_target=12.00, weight=6
        ),
        MANAGER_HEADERS,
    ),
    "disturbed_acres_below_the_floor": lambda ctx: api_client.create_construction_site(
        factories.construction_site_payload(
            ctx["term"]["id"],
            site_name="SITE-TINY",
            disturbed_acres=0.50,
            operator_name="Tinyworks",
        ),
        INSPECTOR_HEADERS,
    ),
    "eru_sqft_below_the_floor": lambda ctx: api_client.create_permit_term(
        factories.permit_term_payload(
            permit_number="MS4-2028-A",
            term_start_date="2028-01-01",
            term_end_date="2028-12-31",
            eru_sqft=50,
        ),
        MANAGER_HEADERS,
    ),
    "start_date_that_is_not_iso_8601": lambda ctx: api_client.create_permit_term(
        factories.permit_term_payload(
            permit_number="MS4-2029-A",
            term_start_date="01-01-2029",
            term_end_date="2029-12-31",
        ),
        MANAGER_HEADERS,
    ),
}


class TestRequestShapeIsSettledBeforeAnyLookup:
    """Omissions, unknown enum members and out-of-range numbers are all one error."""

    @pytest.fixture
    def shape_context(self):
        """One DRAFT term, so every foreign key in the rejected bodies is valid."""
        return {"term": fx.create_permit_term()}

    @pytest.mark.parametrize(
        "case_key", list(MISSING_FIELD_CASES), ids=list(MISSING_FIELD_CASES)
    )
    def test_13_a_missing_required_field_is_a_request_shape_failure(
        self, shape_context, case_key
    ):
        """Every other field is valid and the omission still answers first.

        PRD: "**Request shape.** Missing required body fields, wrong types, unknown
        enum members, out-of-range numbers, malformed ISO 8601 values and
        out-of-range pagination all yield `ERR_VALIDATION` (400)."

        Design: Corner/entities/missing_required_body_fields_are_rejected_before_any_lookup
        """
        response = MISSING_FIELD_CASES[case_key](shape_context)

        error = validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)
        assert isinstance(error["message"], str) and error["message"], (
            "the rejection explains what was wrong with the request"
        )

    def test_14_none_of_the_incomplete_bodies_became_a_row(self, shape_context):
        """One term exists, and it has neither an outfall nor a site.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/entities/missing_required_body_fields_are_rejected_before_any_lookup
        """
        for call in MISSING_FIELD_CASES.values():
            call(shape_context)

        _, term_meta = validate_paginated(api_client.list_permit_terms(MANAGER_HEADERS))
        assert term_meta["total_count"] == 1, (
            f"the incomplete term was not created, got {term_meta['total_count']}"
        )

        _, outfall_meta = validate_paginated(
            api_client.list_term_outfalls(shape_context["term"]["id"], MANAGER_HEADERS)
        )
        assert outfall_meta["total_count"] == 0, "no outfall was written"

        _, site_meta = validate_paginated(
            api_client.list_term_construction_sites(
                shape_context["term"]["id"], MANAGER_HEADERS
            )
        )
        assert site_meta["total_count"] == 0, "no construction site was written"

    @pytest.mark.parametrize(
        "case_key", list(RANGE_AND_ENUM_CASES), ids=list(RANGE_AND_ENUM_CASES)
    )
    def test_15_enum_and_range_breaches_are_shape_failures_not_domain_failures(
        self, shape_context, case_key
    ):
        """An unknown tier, an over-range weight, a small site, a small unit, a bad date.

        PRD: "This layer also covers the cross-field shape rules: `term_end_date`
        must be strictly later than `term_start_date`, `disturbed_acres` must be at
        least 1.00, `requested_credit_pct` must be greater than 0.0000 and at most
        0.5000, `weight` must be between 1 and 5 inclusive, an inspection's
        `period_end` may not precede its `period_start`, and a term declaring
        `tmdl_applicable` true must supply both `tmdl_pollutant` and
        `tmdl_wla_lb_per_year`."

        Design: Corner/entities/enum_and_range_constraints_are_enforced_on_input_fields
        """
        response = RANGE_AND_ENUM_CASES[case_key](shape_context)

        validate_error(response, ApiErrorId.ERR_VALIDATION.value, 400)

    def test_16_the_rejected_values_left_the_term_childless(self, shape_context):
        """Five refusals, and the term still owns nothing.

        PRD: "An optional `weight` between 1 and 5 inclusive, defaulting to 1, fixes
        how heavily the measure counts in the annual compliance index." And: "Nothing
        is persisted when a request is rejected — no partial writes, no counter
        increments, no cascades."

        Design: Corner/entities/enum_and_range_constraints_are_enforced_on_input_fields
        """
        for call in RANGE_AND_ENUM_CASES.values():
            call(shape_context)

        term_id = shape_context["term"]["id"]
        for lister, label in (
            (api_client.list_term_outfalls, "outfalls"),
            (api_client.list_term_control_measures, "control measures"),
            (api_client.list_term_construction_sites, "construction sites"),
        ):
            _, meta = validate_paginated(lister(term_id, MANAGER_HEADERS))
            assert meta["total_count"] == 0, (
                f"the term must own no {label}, got {meta['total_count']}"
            )

        _, term_meta = validate_paginated(api_client.list_permit_terms(MANAGER_HEADERS))
        assert term_meta["total_count"] == 1, (
            f"neither rejected term was created, got {term_meta['total_count']}"
        )


class TestServerOwnedFieldsIgnoreClientInput:
    """A payload may carry system fields; the server derives them anyway."""

    def test_17_an_outfall_derives_its_own_state_identity_and_version(self, draft_term):
        """Status, screening dimension, id and version are all server-minted.

        PRD: "A new outfall has `status` `ACTIVE`, `screening_status` `NOT_SCREENED`,
        `tmdl_status` `NOT_ASSESSED`, an empty `sweeping_runs` list,
        `swept_lane_miles_ytd` at 0.00, `screening_count` and `open_case_count` at 0,
        `last_screened_at` and `last_assessed_year` null, and
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb` and
        `last_assessed_net_load_lb` at 0.00."

        Design: Corner/entities/system_and_computed_fields_ignore_extra_field_input
        """
        outfall = validate_success(
            api_client.create_outfall(
                factories.outfall_payload(
                    draft_term["id"],
                    "OF-93",
                    drainage_area_acres=12.00,
                    priority_tier="LOW",
                    baseline_concentration_mg_per_l=0.20,
                    design_runoff_kl=8000.00,
                    status="RETIRED",
                    screening_status="SUSPECT",
                    screening_count=99,
                    id=CLIENT_SUPPLIED_ID,
                    version=42,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert outfall["status"] == "ACTIVE", "a new outfall is ACTIVE, never RETIRED"
        assert outfall["screening_status"] == "NOT_SCREENED", (
            "the screening dimension starts unscreened"
        )
        assert outfall["screening_count"] == 0, "no screening has been recorded"
        assert outfall["tmdl_status"] == "NOT_ASSESSED", "no assessment has been run"
        assert outfall["id"] != CLIENT_SUPPLIED_ID, "the identifier is server-minted"
        assert_common_fields(outfall, expected_version=1)
        assert outfall["updated_at"] == outfall["created_at"], (
            "an unmutated row carries the same two timestamps"
        )

    def test_18_a_site_derives_both_dimensions_and_its_control_requirement(
        self, draft_term
    ):
        """Two-and-a-half acres requires a permanent control, whatever the payload says.

        PRD: "On creation the server derives `post_construction_control_required`,
        setting it true exactly when `disturbed_acres` is 2.00 or more, and
        initialises `plan_review_round` and `stop_work_count` to 0,
        `open_deficiency_score` to 0, `open_enforcement_count` to 0, and
        `esc_plan_reference`, `stop_work_reason` and `closed_at` to null."

        Design: Corner/entities/system_and_computed_fields_ignore_extra_field_input
        """
        site = validate_success(
            api_client.create_construction_site(
                factories.construction_site_payload(
                    draft_term["id"],
                    site_name="SITE-J",
                    disturbed_acres=2.50,
                    operator_name="Juniper Civil",
                    plan_status="APPROVED",
                    field_status="ACTIVE_DISTURBANCE",
                    stop_work_count=7,
                ),
                INSPECTOR_HEADERS,
            ),
            201,
        )

        assert site["plan_status"] == "SUBMITTED", (
            "plan review starts at SUBMITTED, not at the requested APPROVED"
        )
        assert site["field_status"] == "PRE_CONSTRUCTION", (
            "the field dimension starts before construction"
        )
        assert site["stop_work_count"] == 0, "no order has been issued"
        assert site["plan_review_round"] == 0, "no review round has run"
        assert site["open_deficiency_score"] == 0, "no deficiency has been scored"
        assert site["post_construction_control_required"] is True, (
            "2.50 acres is at or above the two-acre threshold"
        )


class TestObservationCreationDerivations:
    """One outfall, two observation kinds and two disjoint derivations."""

    @pytest.fixture
    def monitored_outfall(self):
        """An ACTIVE term whose OF-01 carries the design assumptions of §3.7."""
        program = fx.setup_active_program(
            outfall_codes=("OF-01",),
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        return {"term_id": program["term_id"], "outfall": program["outfalls"]["OF-01"]}

    def test_19_a_sample_stamps_its_recorder_and_carries_its_own_load(
        self, monitored_outfall
    ):
        """0.45 mg/L over 40000 kL is 39.6832 pounds, awaiting adjudication.

        PRD: "`sample_load_lb` is the sample's `pollutant_concentration_mg_per_l`
        multiplied by its `runoff_volume_kl`, multiplied by the unit conversion factor
        0.00220462 pounds per milligram-per-litre-kilolitre, rounded to 4 decimal
        places. A sample is stored with `validation_status` `PENDING` and must be
        adjudicated before it counts."

        Design: Corner/entities/observation_creation_stamps_the_recorder_and_derives_the_sample_load
        """
        sample = validate_success(
            api_client.create_observation(
                monitored_outfall["outfall"]["id"],
                factories.sample_payload(
                    "2026-07-20T09:00:00Z",
                    pollutant_concentration_mg_per_l=0.45,
                    runoff_volume_kl=40000,
                    field_notes="First flush grab sample",
                ),
                OPERATIONS_HEADERS,
            ),
            201,
        )

        assert sample["recorded_by_user_id"] == OPERATIONS_ONE, (
            "the acting operator is captured as the recorder"
        )
        assert sample["validation_status"] == "PENDING", "a new sample is unadjudicated"
        assert sample["sample_load_lb"] == pytest.approx(39.6832, abs=0.0001), (
            f"expected a sample load of 39.6832 lb, got {sample['sample_load_lb']}"
        )
        assert sample["screening_result"] is None, "a sample has no screening result"
        assert sample["validated_at"] is None, "nothing has been adjudicated"

    def test_20_a_screening_is_never_adjudicated_and_carries_no_load(
        self, monitored_outfall
    ):
        """The two observation kinds fill disjoint halves of the same row.

        PRD: "Screenings are stored with `validation_status` `NOT_APPLICABLE` and a
        null `sample_load_lb`; samples are stored with a null `screening_result`, as
        described in §3.7." And: "If `dry_weather_flow_present` is false, the result
        is `CLEAR` — no flow means no discharge, and no indicator is consulted."

        Design: Corner/entities/observation_creation_stamps_the_recorder_and_derives_the_sample_load
        """
        screening = validate_success(
            api_client.create_observation(
                monitored_outfall["outfall"]["id"],
                factories.screening_payload(
                    "2026-07-25T09:00:00Z",
                    dry_weather_flow_present=False,
                    indicator_bacteria_mpn=None,
                    indicator_surfactant_mg_per_l=None,
                    indicator_ammonia_mg_per_l=None,
                ),
                IDDE_HEADERS,
            ),
            201,
        )

        assert screening["recorded_by_user_id"] == IDDE_ONE, (
            "the investigator is captured as the recorder"
        )
        assert screening["validation_status"] == "NOT_APPLICABLE", (
            "a screening is permanently outside the adjudication track"
        )
        assert screening["screening_result"] == "CLEAR", "no flow reads clear"
        assert screening["sample_load_lb"] is None, "a screening carries no load"

    def test_21_recording_a_sample_is_not_an_assessment(self, monitored_outfall):
        """The screening counters move; the load-assessment fields do not.

        PRD: "Every dry-weather screening stamps the outfall's `last_screened_at` with
        the observation's `observed_at` and increments `screening_count` by one. A
        `CLEAR` result moves `screening_status` from `NOT_SCREENED` to `CLEAR`."

        Design: Corner/entities/observation_creation_stamps_the_recorder_and_derives_the_sample_load
        """
        outfall_id = monitored_outfall["outfall"]["id"]
        fx.record_sample(outfall_id, "2026-07-20T09:00:00Z", 0.45, 40000)
        fx.record_screening(
            outfall_id,
            "2026-07-25T09:00:00Z",
            dry_weather_flow_present=False,
            indicator_bacteria_mpn=None,
            indicator_surfactant_mg_per_l=None,
            indicator_ammonia_mg_per_l=None,
        )

        outfall = fx.read_outfall(outfall_id)
        assert outfall["screening_count"] == 1, "only the screening is counted"
        assert outfall["last_screened_at"] == "2026-07-25T09:00:00Z", (
            "the screening instant is stamped"
        )
        assert outfall["screening_status"] == "CLEAR", "a clear visit reads clear"
        assert outfall["open_case_count"] == 0, "no case was opened"
        assert outfall["last_assessed_gross_load_lb"] == pytest.approx(0.00, abs=0.01), (
            "recording a sample assesses nothing"
        )
        assert outfall["tmdl_status"] == "NOT_ASSESSED", "no assessment has been run"


class TestSubResourceReadsAreScopedToTheirParent:
    """Two terms holding identically coded children."""

    @pytest.fixture
    def two_terms(self):
        """Term A and term B, each with one measure, one outfall and one account."""
        term_a = fx.create_permit_term(
            permit_number="MS4-2026-A",
            term_start_date="2026-01-01",
            term_end_date="2026-12-31",
        )
        term_b = fx.create_permit_term(
            permit_number="MS4-2027-B",
            term_start_date="2027-01-01",
            term_end_date="2027-12-31",
        )
        measure_a = validate_success(
            api_client.create_control_measure(
                factories.control_measure_payload(
                    term_a["id"], "PUBLIC_EDUCATION", measurable_goal_target=12.00
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        measure_b = validate_success(
            api_client.create_control_measure(
                factories.control_measure_payload(
                    term_b["id"], "PUBLIC_EDUCATION", measurable_goal_target=8.00
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        outfall_a = fx.create_outfall(
            term_a["id"],
            "OF-01",
            receiving_water="Mill Creek",
            drainage_area_acres=45.00,
            priority_tier="HIGH",
            baseline_concentration_mg_per_l=0.45,
            design_runoff_kl=20000,
        )
        outfall_b = fx.create_outfall(
            term_b["id"],
            "OF-01",
            receiving_water="Bell Slough",
            drainage_area_acres=10.00,
            priority_tier="LOW",
            baseline_concentration_mg_per_l=0.10,
            design_runoff_kl=5000,
        )
        account_a = fx.create_account(
            term_a["id"], parcel_id="P-1000", owner_name="A Owner"
        )
        account_b = fx.create_account(
            term_b["id"], parcel_id="P-1000", owner_name="B Owner"
        )
        site = fx.create_site(
            term_a["id"],
            site_name="SITE-K",
            operator_name="Kestrel Build",
            disturbed_acres=2.50,
        )
        facility = fx.create_facility(
            site["id"], "PRIVATE", design_capacity_cf=4000.00, service_area_acres=2.50
        )
        return {
            "term_a": term_a,
            "term_b": term_b,
            "measure_a": measure_a,
            "measure_b": measure_b,
            "outfall_a": outfall_a,
            "outfall_b": outfall_b,
            "account_a": account_a,
            "account_b": account_b,
            "site": site,
            "facility": facility,
        }

    def test_22_each_nested_read_returns_only_its_own_parents_children(self, two_terms):
        """Four nested reads, four single-row answers, no sibling leakage.

        PRD: "Several collections are reachable both at their own top-level path and
        as a sub-resource read under the row they belong to: a term's control
        measures, outfalls, construction sites, accounts and annual reports; an
        outfall's observations; a site's permanent controls."

        Design: Corner/entities/sub_resource_reads_return_only_the_children_of_the_named_parent
        """
        measures, measure_meta = validate_paginated(
            api_client.list_term_control_measures(
                two_terms["term_a"]["id"], MANAGER_HEADERS
            )
        )
        assert measure_meta["total_count"] == 1, "term A owns exactly one measure"
        assert measures[0]["id"] == two_terms["measure_a"]["id"], (
            "the sibling term's measure must not appear"
        )

        outfalls, outfall_meta = validate_paginated(
            api_client.list_term_outfalls(two_terms["term_b"]["id"], MANAGER_HEADERS)
        )
        assert outfall_meta["total_count"] == 1, "term B owns exactly one outfall"
        assert outfalls[0]["id"] == two_terms["outfall_b"]["id"], (
            "both outfalls are coded OF-01, and only term B's is returned"
        )

        accounts, account_meta = validate_paginated(
            api_client.list_term_accounts(two_terms["term_a"]["id"], CLERK_HEADERS)
        )
        assert account_meta["total_count"] == 1, "term A bills exactly one parcel"
        assert accounts[0]["id"] == two_terms["account_a"]["id"], (
            "both accounts are parcel P-1000, and only term A's is returned"
        )

    def test_23_a_sites_permanent_controls_are_scoped_to_that_site(self, two_terms):
        """The one inventoried control answers with its pending agreement.

        PRD: "a `PRIVATE` facility is created with `agreement_status` `PENDING`
        because a privately owned control must carry a recorded maintenance
        agreement."

        Design: Corner/entities/sub_resource_reads_return_only_the_children_of_the_named_parent
        """
        facilities, meta = validate_paginated(
            api_client.list_site_post_construction_facilities(
                two_terms["site"]["id"], INSPECTOR_HEADERS
            )
        )

        assert meta["total_count"] == 1, f"one control is inventoried, got {meta['total_count']}"
        assert facilities[0]["id"] == two_terms["facility"]["id"], (
            "the site's own control is returned"
        )
        assert facilities[0]["agreement_status"] == "PENDING", (
            "a private control opens on the agreement track"
        )


class TestScopedNaturalKeys:
    """One key is global; the other three are per term."""

    @pytest.fixture
    def keyed_program(self):
        """Term A holding PUBLIC_EDUCATION, OF-01 and parcel P-1000; term B empty."""
        term_a = fx.create_permit_term(
            permit_number="MS4-2026-A",
            term_start_date="2026-01-01",
            term_end_date="2026-12-31",
        )
        term_b = fx.create_permit_term(
            permit_number="MS4-2027-B",
            term_start_date="2027-01-01",
            term_end_date="2027-12-31",
        )
        validate_success(
            api_client.create_control_measure(
                factories.control_measure_payload(
                    term_a["id"], "PUBLIC_EDUCATION", measurable_goal_target=12.00
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        fx.create_outfall(
            term_a["id"],
            "OF-01",
            receiving_water="Mill Creek",
            drainage_area_acres=45.00,
            priority_tier="HIGH",
            baseline_concentration_mg_per_l=0.45,
            design_runoff_kl=20000,
        )
        fx.create_account(term_a["id"], parcel_id="P-1000", owner_name="A Owner")
        return {"term_a": term_a, "term_b": term_b}

    @pytest.mark.parametrize(
        "key, error_id",
        [
            ("permit_number", ApiErrorId.ERR_DUPLICATE_PERMIT_NUMBER),
            ("measure_code", ApiErrorId.ERR_DUPLICATE_MEASURE_CODE),
            ("outfall_code", ApiErrorId.ERR_DUPLICATE_OUTFALL_CODE),
            ("parcel_id", ApiErrorId.ERR_DUPLICATE_PARCEL_ID),
        ],
    )
    def test_24_a_collision_inside_the_scope_names_its_own_duplicate_code(
        self, keyed_program, key, error_id
    ):
        """Each of the four natural keys reports its own conflict.

        PRD: "**Scoped uniqueness.** `permit_number` is unique across all permit
        terms; `measure_code` is unique per term; `outfall_code` is unique per term;
        `parcel_id` is unique per term. Collisions yield
        `ERR_DUPLICATE_PERMIT_NUMBER`, `ERR_DUPLICATE_MEASURE_CODE`,
        `ERR_DUPLICATE_OUTFALL_CODE` and `ERR_DUPLICATE_PARCEL_ID` respectively, all
        HTTP 409."

        Design: Corner/entities/scoped_natural_keys_reject_duplicates_but_allow_reuse_across_terms
        """
        term_a_id = keyed_program["term_a"]["id"]
        calls = {
            "permit_number": lambda: api_client.create_permit_term(
                factories.permit_term_payload(
                    permit_number="MS4-2026-A",
                    term_start_date="2026-02-01",
                    term_end_date="2026-11-30",
                ),
                MANAGER_HEADERS,
            ),
            "measure_code": lambda: api_client.create_control_measure(
                factories.control_measure_payload(
                    term_a_id, "PUBLIC_EDUCATION", measurable_goal_target=4.00
                ),
                MANAGER_HEADERS,
            ),
            "outfall_code": lambda: api_client.create_outfall(
                factories.outfall_payload(
                    term_a_id,
                    "OF-01",
                    drainage_area_acres=9.00,
                    priority_tier="LOW",
                    baseline_concentration_mg_per_l=0.10,
                    design_runoff_kl=5000,
                ),
                MANAGER_HEADERS,
            ),
            "parcel_id": lambda: api_client.create_account(
                factories.account_payload(
                    term_a_id,
                    "P-1000",
                    "COMMERCIAL",
                    9020.0,
                    owner_name="A Owner Again",
                ),
                CLERK_HEADERS,
            ),
        }

        validate_error(calls[key](), error_id.value, 409)

    def test_25_the_same_three_values_are_free_under_a_second_term(self, keyed_program):
        """Per-term scoping means term B may reuse every code term A holds.

        PRD: "Under the term the manager registers **control measures**, one per
        minimum control measure, by supplying the `permit_term_id` of the owning term,
        the `measure_code`, and the `measurable_goal_target` for the permit year — a
        non-negative number with 2 decimal places, counted in whatever unit the
        measure uses, whether education events, inspections or lane miles."

        Design: Corner/entities/scoped_natural_keys_reject_duplicates_but_allow_reuse_across_terms
        """
        measure = validate_success(
            api_client.create_control_measure(
                factories.control_measure_payload(
                    keyed_program["term_b"]["id"],
                    "PUBLIC_EDUCATION",
                    measurable_goal_target=8.00,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        assert measure["permit_term_id"] == keyed_program["term_b"]["id"], (
            "the reused code belongs to the second term"
        )
        assert measure["measure_code"] == "PUBLIC_EDUCATION", (
            "the very code that collided under term A is accepted under term B"
        )

    def test_26_the_refused_duplicates_left_the_first_term_as_it_was(self, keyed_program):
        """Term A still holds one measure, one outfall and one account.

        PRD: "Nothing is persisted when a request is rejected — no partial writes, no
        counter increments, no cascades."

        Design: Corner/entities/scoped_natural_keys_reject_duplicates_but_allow_reuse_across_terms
        """
        term_a_id = keyed_program["term_a"]["id"]
        api_client.create_permit_term(
            factories.permit_term_payload(
                permit_number="MS4-2026-A",
                term_start_date="2026-02-01",
                term_end_date="2026-11-30",
            ),
            MANAGER_HEADERS,
        )
        api_client.create_control_measure(
            factories.control_measure_payload(
                term_a_id, "PUBLIC_EDUCATION", measurable_goal_target=4.00
            ),
            MANAGER_HEADERS,
        )
        api_client.create_account(
            factories.account_payload(term_a_id, "P-1000", "COMMERCIAL", 9020.0),
            CLERK_HEADERS,
        )

        _, measure_meta = validate_paginated(
            api_client.list_term_control_measures(term_a_id, MANAGER_HEADERS)
        )
        assert measure_meta["total_count"] == 1, "term A still holds one measure"

        _, account_meta = validate_paginated(
            api_client.list_term_accounts(term_a_id, CLERK_HEADERS)
        )
        assert account_meta["total_count"] == 1, "term A still bills one parcel"

        _, term_meta = validate_paginated(api_client.list_permit_terms(MANAGER_HEADERS))
        assert term_meta["total_count"] == 2, (
            f"the duplicate term was never created, got {term_meta['total_count']}"
        )
