"""Fiscal years and enrollment projections: creation defaults, field
validation, listing/pagination, weighted pupils, certification, and the
OPEN-state gate (PRD §2.3, §3.1)."""
from test_helpers import (
    ApiErrorId, assert_enrollment_projection, assert_fiscal_year,
    assert_version_incremented, create_fiscal_year_payload,
    create_projection_payload, get_success_data, set_clock,
    validate_error, validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    add_projection, add_revenue_estimate, add_budget_line, certify_projection,
    create_budget_version, create_fiscal_year, create_open_fiscal_year,
    setup_adopted_budget,
)
from test_helpers.test_users import TEST_USERS

BA = TEST_USERS["budget_analyst_headers"]
BM = TEST_USERS["business_manager_headers"]
AU = TEST_USERS["auditor_headers"]


class TestFiscalYearCreation:
    def test_create_fiscal_year_applies_system_defaults(self, api):
        """PRD §3.1: "A new fiscal year begins in `DRAFT` status, with
        `authorized_fte_total` and `open_position_count` both zero."
        PRD §2.4: "Every resource carries an `id` — a server-minted UUID with
        no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value
        with three fractional digits (for example `2026-08-01T00:00:00.000Z`)."

        Design: Corner/entities/create_fiscal_year_applies_system_defaults
        """
        resp = api.create_fiscal_year(create_fiscal_year_payload(), BM)
        data = validate_success(resp, 201)
        assert_fiscal_year(data)
        assert data["status"] == "DRAFT"
        assert data["authorized_fte_total"] == 0
        assert data["open_position_count"] == 0

    def test_create_fiscal_year_missing_required_field(self, api):
        """PRD §2.9: "**Request-body shape** — required fields present, types
        correct, enum members valid (`ERR_INVALID_REQUEST`, HTTP 400)."
        PRD §3.1 lists `fte_ceiling` among the fiscal year's creation inputs.

        Design: Corner/entities/create_fiscal_year_missing_required_field_returns_invalid_request
        """
        payload = create_fiscal_year_payload()
        del payload["fte_ceiling"]
        resp = api.create_fiscal_year(payload, BM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        # Nothing is persisted.
        _, meta = validate_paginated(api.list_fiscal_years(AU))
        assert meta["total_count"] == 0

    def test_create_fiscal_year_end_before_start(self, api):
        """PRD §3.1: "The `end_date` must fall after the `start_date`, and a
        violation is rejected with `ERR_INVALID_FIELD_VALUE`."

        Design: Corner/entities/create_fiscal_year_end_before_start_returns_invalid_field_value
        """
        resp = api.create_fiscal_year(
            create_fiscal_year_payload(start_date="2028-07-01",
                                       end_date="2028-06-30"), BM)
        validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE, 422)


class TestFiscalYearListing:
    def test_fiscal_year_list_paginates_with_limit_and_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to
        0." and "Unless otherwise specified, every list endpoint returns its
        items ordered by `created_at` ascending — a stable creation order,
        with no id-based ordering anywhere in the API."

        Design: Corner/entities/fiscal_year_list_paginates_with_limit_and_offset
        """
        labels = [f"FY{i:04d}" for i in range(1, 13)]
        # Advance the clock between creates so created_at strictly increases.
        for i, label in enumerate(labels):
            set_clock(f"2026-08-{i + 1:02d}T00:00:00Z")
            create_fiscal_year(label=label)

        page1, meta1 = validate_paginated(
            api.list_fiscal_years(AU, params={"limit": 10}))
        assert [row["label"] for row in page1] == labels[:10]
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_fiscal_years(AU, params={"limit": 10, "offset": 10}))
        assert [row["label"] for row in page2] == labels[10:]
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False


class TestFiscalYearStateGate:
    def test_projection_create_on_draft_fiscal_year_rejected(self, api):
        """PRD §3.1: "Opening the year — `DRAFT` → `OPEN`, an action that
        increments the fiscal year's `version` — admits the creation of
        enrollment projections, budget versions, and bond proposals;
        attempting any of these against a year that is not `OPEN` fails with
        `ERR_FISCAL_YEAR_NOT_OPEN`."

        Design: Corner/validations/projection_create_on_draft_fiscal_year_rejected
        """
        fy = create_fiscal_year()  # stays DRAFT
        resp = api.create_enrollment_projection(
            fy["id"], create_projection_payload("ELEMENTARY", 1200), BA)
        validate_error(resp, ApiErrorId.ERR_FISCAL_YEAR_NOT_OPEN, 409)

    def test_double_open_fiscal_year_rejected(self, api):
        """PRD §3.1: "Opening the year — `DRAFT` → `OPEN`, an action that
        increments the fiscal year's `version` — admits the creation of
        enrollment projections, budget versions, and bond proposals" — the
        trigger exists only from DRAFT, and PRD §2.9 stage 8: "**State
        admission** — the target entity's state machine admits the requested
        transition, and child creation finds its parent in a mutable state
        (`ERR_INVALID_STATE`, `ERR_FISCAL_YEAR_NOT_OPEN`,
        `ERR_BUDGET_VERSION_NOT_DRAFT`, `ERR_BUDGET_VERSION_NOT_HEARING_HELD`,
        `ERR_EXPENDITURE_NOT_REVIEWED`, HTTP 409)."

        Design: Corner/state_machines/double_open_fiscal_year_rejected
        """
        fy = create_open_fiscal_year()
        resp = api.open_fiscal_year(fy["id"], BM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_close_fiscal_year_without_adopted_budget_rejected(self, api):
        """PRD §3.1: "Closing the year moves it `OPEN` → `CLOSED`, requires
        that some budget version of the year has reached `ADOPTED` (otherwise
        `ERR_NO_ADOPTED_BUDGET_VERSION`), sweeps every hearing of every
        version of the year that is still `NOTICE_PUBLISHED` to `CANCELLED`,
        and increments the fiscal year's `version`."

        Design: Corner/validations/close_fiscal_year_without_adopted_budget_rejected
        """
        fy = create_open_fiscal_year()
        create_budget_version(fy["id"])  # DRAFT only — never adopted
        resp = api.close_fiscal_year(fy["id"], BM)
        validate_error(resp, ApiErrorId.ERR_NO_ADOPTED_BUDGET_VERSION, 409)

    def test_close_terminal_fiscal_year_rejected_invalid_state(self, api):
        """PRD §3.1: "Closing the year moves it `OPEN` → `CLOSED`, requires
        that some budget version of the year has reached `ADOPTED` (otherwise
        `ERR_NO_ADOPTED_BUDGET_VERSION`), sweeps every hearing of every
        version of the year that is still `NOTICE_PUBLISHED` to `CANCELLED`,
        and increments the fiscal year's `version`." — once CLOSED, no further
        transition exists, so a second close is the generic from-state
        violation of PRD §2.9 stage 8: "**State admission** — the target
        entity's state machine admits the requested transition, and child
        creation finds its parent in a mutable state (`ERR_INVALID_STATE`,
        `ERR_FISCAL_YEAR_NOT_OPEN`, `ERR_BUDGET_VERSION_NOT_DRAFT`,
        `ERR_BUDGET_VERSION_NOT_HEARING_HELD`, `ERR_EXPENDITURE_NOT_REVIEWED`,
        HTTP 409)."

        Design: Corner/state_machines/close_terminal_fiscal_year_rejected_invalid_state
        """
        ctx = setup_adopted_budget()
        fy_id = ctx["fy"]["id"]
        closed = validate_success(api.close_fiscal_year(fy_id, BM), 200)
        assert closed["status"] == "CLOSED"
        resp = api.close_fiscal_year(fy_id, BM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestEnrollmentProjections:
    def test_enrollment_projection_computes_weighted_pupils(self, api):
        """PRD §3.1: "the server derives `weighted_pupils_projected` by
        multiplying the projected count by the band's weight — 1.00 for
        `ELEMENTARY`, 1.05 for `MIDDLE`, and 1.15 for `HIGH` — and rounding
        half-up to a whole pupil" and "Each projection starts `PROVISIONAL`,
        and both `actual_pupils` and `weighted_pupils_certified` remain null
        until certification."

        Design: Corner/entities/enrollment_projection_computes_weighted_pupils
        """
        fy = create_open_fiscal_year()
        resp = api.create_enrollment_projection(
            fy["id"], create_projection_payload("MIDDLE", 800), BA)
        data = validate_success(resp, 201)
        assert_enrollment_projection(data)
        # round_half_up(800 * 1.05, 0) == 840
        assert data["weighted_pupils_projected"] == 840
        assert data["weighted_pupils_certified"] is None
        assert data["actual_pupils"] is None
        assert data["status"] == "PROVISIONAL"

    def test_duplicate_grade_band_projection_rejected(self, api):
        """PRD §3.1: "The band — `grade_band`, one of `ELEMENTARY`, `MIDDLE`,
        or `HIGH` — is unique within the fiscal year: a second projection for
        a band already filed in that year is rejected with
        `ERR_DUPLICATE_GRADE_BAND`."

        Design: Corner/entities/duplicate_grade_band_projection_rejected
        """
        fy = create_open_fiscal_year()
        add_projection(fy["id"], "ELEMENTARY", 1200)
        resp = api.create_enrollment_projection(
            fy["id"], create_projection_payload("ELEMENTARY", 900), BA)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_GRADE_BAND, 409)

    def test_certify_projection_computes_certified_weight(self, api):
        """PRD §3.1: "Certification records the actuals, derives
        `weighted_pupils_certified` from the actual count using the same band
        weight and the same half-up rounding to a whole pupil, retains the
        provisional weighted figure alongside it, moves the projection
        `PROVISIONAL` → `CERTIFIED`, and increments the projection's
        `version`."

        Design: Corner/entities/certify_projection_computes_certified_weight
        """
        fy = create_open_fiscal_year()
        ep = add_projection(fy["id"], "HIGH", 1000)
        assert ep["weighted_pupils_projected"] == 1150
        certified = validate_success(
            api.certify_enrollment_projection(
                ep["id"], {"actual_pupils": 1020}, BM), 200)
        assert_enrollment_projection(certified)
        # round_half_up(1020 * 1.15, 0) == 1173
        assert certified["weighted_pupils_certified"] == 1173
        assert certified["weighted_pupils_projected"] == 1150
        assert certified["status"] == "CERTIFIED"
        assert_version_incremented(certified["version"], ep["version"])

    def test_weighted_pupils_round_half_up_at_fractional_boundary(self, api):
        """PRD §3.1: "the server derives `weighted_pupils_projected` by
        multiplying the projected count by the band's weight — 1.00 for
        `ELEMENTARY`, 1.05 for `MIDDLE`, and 1.15 for `HIGH` — and rounding
        half-up to a whole pupil."

        Design: Corner/calculations/weighted_pupils_round_half_up_at_fractional_boundary
        """
        fy = create_open_fiscal_year()
        resp = api.create_enrollment_projection(
            fy["id"], create_projection_payload("HIGH", 1001), BA)
        data = validate_success(resp, 201)
        # 1001 * 1.15 = 1151.15 -> round_half_up to a whole pupil -> 1151
        assert data["weighted_pupils_projected"] == 1151
