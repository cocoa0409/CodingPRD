"""Program design, tax type terms, the window lifecycle and paging.

Covers the root aggregate of PRD §3.1 and §3.8: what a designed program
persists, which optional inputs fall back to declared defaults, how the
eligible-term set gates opening, how half-open term windows coexist, and how
the logical clock of PRD §2.4 dates every row it touches.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    AUDITOR_ONE_HEADERS,
    CANONICAL_CLOCK,
    CANONICAL_CLOCK_RENDERED,
    CANONICAL_WINDOW_CLOSE_AT,
    CANONICAL_WINDOW_CLOSE_AT_RENDERED,
    CANONICAL_WINDOW_OPEN_AT,
    DEFAULT_CLOCK_UTC_RENDERED,
    DEFAULT_INSTALLMENT_MAX_COUNT,
    DEFAULT_PAGE_LIMIT,
    DEFAULT_PROSPECTIVE_COMPLIANCE_MONTHS,
    ApiErrorId,
    add_tax_type_term,
    assert_audit_fields,
    assert_error_data_shape,
    assert_fields,
    assert_list_total,
    assert_page,
    assert_timestamp_with_millis,
    create_program,
    is_valid_uuid,
    program_payload,
    read_program,
    register_taxpayer,
    set_clock,
    setup_reconciled_program,
    tax_type_term_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProgramDesign:
    """`POST /amnesty/programs` and its declared field set (PRD §3.1)."""

    def test_designed_program_persists_every_declared_field(self, api):
        """A designed program echoes its inputs and mints its counters at zero.

        PRD §3.1: "On creation the program's `status` is `DRAFT`, `closed_at`
        and `final_realization_pct` are null, and `collected_cents`,
        `waived_total_cents`, `reinstated_total_cents`, `participant_count`
        and `nonparticipant_count` all read 0."

        PRD §2.4: "Every persisted resource carries an `id` that the server
        mints as a UUID with no type prefix, and a `created_at` timestamp
        expressed as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/Table 1 Entities/program_creation_persists_every_declared_field
        """
        set_clock(api, CANONICAL_CLOCK)

        response = api.create_program(
            program_payload(prospective_compliance_months=48, installment_max_count=6),
            ADMIN_HEADERS,
        )
        program = validate_success(response, 201)

        assert is_valid_uuid(program["id"]), program["id"]
        assert_audit_fields(program, expected_version=1)
        assert_timestamp_with_millis(program["created_at"])
        assert_timestamp_with_millis(program["updated_at"])
        assert_fields(
            program,
            name="FY27 Amnesty",
            lookback_months=36,
            prospective_compliance_months=48,
            installment_max_count=6,
            status="DRAFT",
            closed_at=None,
            collected_cents=0,
            waived_total_cents=0,
            reinstated_total_cents=0,
            participant_count=0,
            nonparticipant_count=0,
            final_realization_pct=None,
        )

        persisted = read_program(api, program["id"])
        assert_fields(
            persisted,
            status="DRAFT",
            closed_at=None,
            final_realization_pct=None,
            collected_cents=0,
            waived_total_cents=0,
            reinstated_total_cents=0,
            participant_count=0,
            nonparticipant_count=0,
        )

    def test_optional_inputs_fall_back_to_their_declared_defaults(self, api):
        """Omitted optionals take the defaults the PRD names, not zero or null.

        PRD §3.1: "Two further inputs are optional and carry defaults:
        `prospective_compliance_months`, the commitment length copied onto each
        agreement, defaults to 36 and must lie between 12 and 120 inclusive; and
        `installment_max_count`, the ceiling on how many installments any plan
        under this program may schedule, defaults to 12 and must lie between 1
        and 24 inclusive."

        PRD §3.1: "It may also set `requires_prior_nonfiler`, which defaults to
        false"

        PRD §3.2: "The optional `is_registered` flag, which defaults to true"

        Design: Corner/Table 1 Entities/optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(api, CANONICAL_CLOCK)

        program = create_program(api)
        assert_fields(
            program,
            prospective_compliance_months=DEFAULT_PROSPECTIVE_COMPLIANCE_MONTHS,
            installment_max_count=DEFAULT_INSTALLMENT_MAX_COUNT,
        )

        term = add_tax_type_term(api, program["id"])
        assert_fields(
            term,
            requires_prior_nonfiler=False,
            penalty_waiver_pct=None,
            interest_waiver_pct=None,
        )

        taxpayer = register_taxpayer(
            api, legal_name="Larkspur Freight LLC", tin_last4="3319"
        )
        assert_fields(
            taxpayer,
            is_registered=True,
            escalation_tier="T0",
            compliance_behavior_score=100,
            nonparticipant_flag=False,
            open_case_count=0,
            open_enforcement_action_count=0,
            nonfiler_period_count=0,
        )

    def test_program_without_window_close_at_is_rejected(self, api):
        """A required input with no default cannot be omitted.

        PRD §2.4: "A malformed date or timestamp, a missing required field, a
        wrong type, an enum value outside its declared set, a monetary field
        that is not a positive integer number of cents where positivity is
        declared, or a percentage outside the inclusive range 0.00 through 1.00,
        all produce `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/Table 1 Entities/program_creation_missing_required_window_close_at_is_rejected
        """
        set_clock(api, CANONICAL_CLOCK)

        payload = program_payload()
        del payload["window_close_at"]

        validate_error(
            api.create_program(payload, ADMIN_HEADERS), ApiErrorId.INVALID_REQUEST
        )
        assert_list_total(api.list_programs(ADMIN_HEADERS), 0)


class TestTaxTypeTerms:
    """Eligible tax type terms and their half-open windows (PRD §3.1, §2.10)."""

    def test_term_under_an_unknown_program_reports_the_parent_not_found(self, api):
        """The nested route resolves its path parent before anything else.

        PRD §2.5: "Identifiers embedded in a URL path are resolved strictly left
        to right, and the leftmost identifier that fails to resolve decides the
        error. A request naming a tax type term under a program that does not
        exist fails with `ERR_PROGRAM_NOT_FOUND` before the term is ever looked
        up."

        Design: Corner/Table 1 Entities/term_creation_under_unknown_program_returns_not_found
        """
        set_clock(api, CANONICAL_CLOCK)

        validate_error(
            api.create_tax_type_term(
                "00000000-0000-4000-8000-000000000001",
                tax_type_term_payload(),
                ADMIN_HEADERS,
            ),
            ApiErrorId.PROGRAM_NOT_FOUND,
        )

    def test_tax_type_outside_the_declared_enum_is_rejected(self, api):
        """Enum membership is closed, and the same call with a member succeeds.

        PRD §2.10: "Tax types, wherever they appear, are `SALES_USE`,
        `CORPORATE_INCOME`, `PERSONAL_INCOME`, `WITHHOLDING` and `EXCISE_FUEL`."

        PRD §2.4: "an enum value outside its declared set" produces
        `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/Table 1 Entities/invalid_tax_type_enum_member_is_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)

        validate_error(
            api.create_tax_type_term(
                program["id"],
                tax_type_term_payload(tax_type="PROPERTY_TAX"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
        )

        validate_success(
            api.create_tax_type_term(
                program["id"], tax_type_term_payload(), ADMIN_HEADERS
            ),
            201,
        )
        assert_list_total(
            api.list_program_tax_type_terms(program["id"], ADMIN_HEADERS), 1
        )

    def test_terms_touching_at_a_shared_endpoint_coexist(self, api):
        """Half-open windows that merely touch are not an overlap.

        PRD §2.10: "A `ProgramTaxTypeTerm` publishes a **half-open** eligible
        window: `eligible_period_start` is inclusive and `eligible_period_end`
        is exclusive. Two terms of the same program and tax type whose windows
        touch at a shared endpoint — one term's `eligible_period_end` equal to
        the next term's `eligible_period_start` — do **not** overlap and may
        coexist."

        Design: Difficulty/resource_temporal_overlap/term_windows_are_half_open_so_touching_endpoints_are_allowed
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)

        early = add_tax_type_term(
            api,
            program["id"],
            eligible_period_start="2020-01-01",
            eligible_period_end="2023-01-01",
        )
        assert_fields(early, eligible_period_end="2023-01-01")

        late = validate_success(
            api.create_tax_type_term(
                program["id"],
                tax_type_term_payload(
                    eligible_period_start="2023-01-01",
                    eligible_period_end="2026-07-01",
                    penalty_waiver_pct=0.80,
                    interest_waiver_pct=0.40,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(
            late,
            eligible_period_start="2023-01-01",
            penalty_waiver_pct=0.80,
            interest_waiver_pct=0.40,
        )

    def test_genuinely_overlapping_term_window_is_refused(self, api):
        """A window that straddles an existing one for the same tax type collides.

        PRD §3.1: "A term whose window overlaps an existing term of the same
        program and the same tax type is refused with
        `ERR_TAX_TYPE_TERM_WINDOW_OVERLAP`; because the windows are half-open,
        terms that merely touch at an endpoint are fine."

        Design: Difficulty/resource_temporal_overlap/term_windows_are_half_open_so_touching_endpoints_are_allowed
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)
        add_tax_type_term(
            api,
            program["id"],
            eligible_period_start="2020-01-01",
            eligible_period_end="2023-01-01",
        )
        add_tax_type_term(
            api,
            program["id"],
            eligible_period_start="2023-01-01",
            eligible_period_end="2026-07-01",
        )

        validate_error(
            api.create_tax_type_term(
                program["id"],
                tax_type_term_payload(
                    eligible_period_start="2022-06-01",
                    eligible_period_end="2024-01-01",
                ),
                ADMIN_HEADERS,
            ),
            ApiErrorId.TAX_TYPE_TERM_WINDOW_OVERLAP,
        )

    def test_overlap_is_scoped_to_one_tax_type(self, api):
        """The same span under a different tax type is not an overlap at all.

        PRD §3.1: "A term whose window overlaps an existing term of the same
        program and the same tax type is refused with
        `ERR_TAX_TYPE_TERM_WINDOW_OVERLAP`; because the windows are half-open,
        terms that merely touch at an endpoint are fine."

        Design: Difficulty/resource_temporal_overlap/term_windows_are_half_open_so_touching_endpoints_are_allowed
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)
        add_tax_type_term(
            api,
            program["id"],
            eligible_period_start="2020-01-01",
            eligible_period_end="2023-01-01",
        )
        add_tax_type_term(
            api,
            program["id"],
            eligible_period_start="2023-01-01",
            eligible_period_end="2026-07-01",
        )

        other = validate_success(
            api.create_tax_type_term(
                program["id"],
                tax_type_term_payload(
                    tax_type="CORPORATE_INCOME",
                    eligible_period_start="2022-06-01",
                    eligible_period_end="2024-01-01",
                    min_liability_cents=100000,
                    requires_prior_nonfiler=True,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(other, tax_type="CORPORATE_INCOME", requires_prior_nonfiler=True)

        assert_list_total(
            api.list_program_tax_type_terms(
                program["id"], ADMIN_HEADERS, {"limit": 100}
            ),
            3,
        )
        assert_list_total(
            api.list_program_tax_type_terms(
                program["id"], ADMIN_HEADERS, {"tax_type": "SALES_USE"}
            ),
            2,
        )


class TestWindowOpening:
    """`POST /amnesty/programs/{id}/open` and its preconditions (PRD §3.1)."""

    def test_opening_with_no_eligible_term_is_refused_and_writes_nothing(self, api):
        """An empty eligible-term set blocks the transition out of `DRAFT`.

        PRD §3.1: "at least one tax type term must exist for the program — an
        empty set is refused with `ERR_NO_ELIGIBLE_TAX_TYPE_TERMS`"

        Design: Difficulty/boundary_precision_check/empty_tax_type_term_set_blocks_opening_until_one_exists
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)

        validate_error(
            api.open_program(program["id"], ADMIN_HEADERS),
            ApiErrorId.NO_ELIGIBLE_TAX_TYPE_TERMS,
        )

        unchanged = read_program(api, program["id"])
        assert_fields(unchanged, status="DRAFT", version=program["version"])

    def test_opening_succeeds_once_a_single_term_exists(self, api):
        """Adding one term is enough, and opening only moves `status` and `version`.

        PRD §3.1: "The only effects are that `status` becomes `OPEN` and the
        program's `version` advances by one."

        Design: Difficulty/boundary_precision_check/empty_tax_type_term_set_blocks_opening_until_one_exists
        """
        set_clock(api, CANONICAL_CLOCK)
        program = create_program(api)
        validate_error(
            api.open_program(program["id"], ADMIN_HEADERS),
            ApiErrorId.NO_ELIGIBLE_TAX_TYPE_TERMS,
        )

        term = add_tax_type_term(api, program["id"])
        assert_fields(
            term, penalty_waiver_pct=None, interest_waiver_pct=None,
            requires_prior_nonfiler=False,
        )

        opened = validate_success(api.open_program(program["id"], ADMIN_HEADERS))
        assert_fields(
            opened,
            status="OPEN",
            version=program["version"] + 1,
            closed_at=None,
            collected_cents=0,
            participant_count=0,
        )
        assert_list_total(
            api.list_program_tax_type_terms(program["id"], ADMIN_HEADERS), 1
        )

    def test_reconciled_program_refuses_every_further_lifecycle_call(self, api):
        """`RECONCILED` is terminal: reconcile, close and open all conflict.

        PRD §2.6: "The governing `AmnestyProgram` must be in the state the
        operation requires — `DRAFT` to add tax type terms or to open, `OPEN` to
        participate, `CLOSED` to reconcile or to issue post-program actions —
        otherwise `ERR_PROGRAM_NOT_DRAFT`, `ERR_PROGRAM_NOT_OPEN` or
        `ERR_PROGRAM_NOT_CLOSED` (409)."

        PRD §3.1: "`RECONCILED` is terminal."

        PRD §3.8: "Before reconciliation `final_realization_pct` is null."

        Design: Corner/Table 2 State Machines/reconciled_program_cannot_be_reconciled_or_closed_again
        """
        ctx = setup_reconciled_program(api)
        program_id = ctx["program"]["id"]
        reconciled_version = ctx["program"]["version"]

        assert_fields(ctx["program"], status="RECONCILED")
        assert ctx["program"]["final_realization_pct"] == pytest.approx(
            0.0000, abs=0.00005
        )
        assert ctx["program"]["closed_at"] == CANONICAL_WINDOW_CLOSE_AT_RENDERED

        validate_error(
            api.reconcile_program(program_id, ADMIN_HEADERS),
            ApiErrorId.PROGRAM_NOT_CLOSED,
        )
        validate_error(
            api.close_program(program_id, ADMIN_HEADERS), ApiErrorId.PROGRAM_NOT_OPEN
        )
        validate_error(
            api.open_program(program_id, ADMIN_HEADERS), ApiErrorId.PROGRAM_NOT_DRAFT
        )

        after = read_program(api, program_id)
        assert_fields(after, status="RECONCILED", version=reconciled_version)


class TestProgramListing:
    """Filtering and the pagination window of PRD §2.3."""

    def test_program_listing_reports_the_full_filtered_total(self, api):
        """`total_count` counts the filtered set, `has_more` the rows beyond it.

        PRD §2.3: "`total_count` is the size of the full filtered result set
        before the window is applied and `has_more` states whether rows remain
        beyond it."

        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10,
        its minimum accepted value is 1 and its maximum accepted value is 100.
        `offset` skips rows from the front of the result set; it defaults to 0
        and its minimum accepted value is 0."

        Design: Corner/Table 1 Entities/program_listing_paginates_with_total_count_and_has_more
        """
        set_clock(api, CANONICAL_CLOCK)
        create_program(api, name="Amnesty Alpha")
        create_program(
            api,
            name="Amnesty Bravo",
            lookback_months=24,
            base_penalty_waiver_pct=0.80,
            base_interest_waiver_pct=0.40,
            post_program_penalty_multiplier=1.50,
            revenue_forecast_cents=50000000,
        )
        create_program(
            api,
            name="Amnesty Charlie",
            lookback_months=12,
            base_penalty_waiver_pct=0.50,
            base_interest_waiver_pct=0.25,
            post_program_penalty_multiplier=3.00,
            revenue_forecast_cents=25000000,
        )

        assert_page(
            api.list_programs(AUDITOR_ONE_HEADERS, {"limit": 2, "offset": 0}),
            expected_total=3,
            expected_rows=2,
            expected_limit=2,
            expected_offset=0,
            expected_has_more=True,
        )
        assert_page(
            api.list_programs(AUDITOR_ONE_HEADERS, {"limit": 2, "offset": 2}),
            expected_total=3,
            expected_rows=1,
            expected_limit=2,
            expected_offset=2,
            expected_has_more=False,
        )
        assert_page(
            api.list_programs(AUDITOR_ONE_HEADERS, {"status": "OPEN"}),
            expected_total=0,
            expected_rows=0,
            expected_has_more=False,
        )
        assert_page(
            api.list_programs(AUDITOR_ONE_HEADERS),
            expected_total=3,
            expected_rows=3,
            expected_limit=DEFAULT_PAGE_LIMIT,
            expected_offset=0,
        )

    def test_pagination_outside_its_declared_bounds_is_rejected(self, api):
        """A `limit` above 100 or a negative `offset` is a 400, not a clamp.

        PRD §2.3: "A `limit` outside the inclusive range 1 through 100, or a
        negative `offset`, is rejected with `ERR_INVALID_PAGINATION` (HTTP
        400)."

        Design: Corner/Table 4 Validations/pagination_outside_one_to_hundred_is_rejected
        """
        set_clock(api, CANONICAL_CLOCK)
        create_program(api)

        validate_error(
            api.list_programs(ADMIN_HEADERS, {"limit": 101}),
            ApiErrorId.INVALID_PAGINATION,
        )
        validate_error(
            api.list_programs(ADMIN_HEADERS, {"limit": 10, "offset": -1}),
            ApiErrorId.INVALID_PAGINATION,
        )
        assert_page(
            api.list_programs(ADMIN_HEADERS, {"limit": 100, "offset": 0}),
            expected_total=1,
            expected_rows=1,
            expected_limit=100,
            expected_offset=0,
            expected_has_more=False,
        )


class TestLogicalClock:
    """The test-clock capability of PRD §2.4."""

    def test_clock_endpoint_dates_every_row_written_after_it_moves(self, api):
        """Rows are dated by the clock at write time and are not retro-dated.

        PRD §2.4: "That capability takes a `to_iso8601` instant, returns the new
        clock value as `current_utc`, and modifies no business entity. Before
        any such call the clock reads `2026-08-01T00:00:00Z`."

        Design: Corner/Table 5 Endpoints/clock_endpoint_drives_every_temporal_read
        """
        default_clock_program = create_program(api, name="Default Clock Program")
        assert default_clock_program["created_at"] == DEFAULT_CLOCK_UTC_RENDERED

        moved = validate_success(api.set_clock(CANONICAL_CLOCK, ADMIN_HEADERS))
        # PRD pins the value ("returns the new clock value as `current_utc`") but
        # not its rendering: the clock is not a business entity, and the PRD's own
        # example clock value carries no fractional digits.
        assert moved["current_utc"] in (CANONICAL_CLOCK, CANONICAL_CLOCK_RENDERED), (
            moved["current_utc"]
        )

        moved_clock_program = create_program(api, name="Moved Clock Program")
        assert moved_clock_program["created_at"] == CANONICAL_CLOCK_RENDERED

        unchanged = read_program(api, default_clock_program["id"])
        assert unchanged["created_at"] == DEFAULT_CLOCK_UTC_RENDERED
        assert_fields(unchanged, status="DRAFT", version=1)
        assert_fields(moved_clock_program, status="DRAFT", version=1)


def test_program_error_envelope_carries_only_the_error_id_and_message(api):
    """An unknown taxpayer id yields the entity-specific 404, not an empty 200.

    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    PRD §2.5: "Identifiers embedded in a URL path are resolved strictly left to
    right, and the leftmost identifier that fails to resolve decides the error."

    Design: Corner/Table 1 Entities/taxpayer_read_with_unknown_id_returns_not_found
    """
    set_clock(api, CANONICAL_CLOCK)

    response = api.get_taxpayer(
        "00000000-0000-4000-8000-000000000000", ADMIN_HEADERS
    )
    validate_error(response, ApiErrorId.TAXPAYER_NOT_FOUND)

    body = response.json()
    assert body["response_type"] == "error", body["response_type"]
    assert_error_data_shape(body["data"])
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carries unexpected keys: {sorted(body['meta'])}"
    )


def test_window_instants_are_echoed_as_supplied(api):
    """The designed window is stored as the administrator declared it.

    PRD §3.1: "The design payload gives the program a `name`, fixes the
    participation window with `window_open_at` and `window_close_at`"

    Design: Corner/Table 1 Entities/program_creation_persists_every_declared_field
    """
    set_clock(api, CANONICAL_CLOCK)
    program = create_program(api)

    assert program["window_open_at"].startswith(CANONICAL_WINDOW_OPEN_AT[:19])
    assert program["window_close_at"].startswith(CANONICAL_WINDOW_CLOSE_AT[:19])

    rows, meta = validate_paginated(api.list_programs(ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == program["id"]
