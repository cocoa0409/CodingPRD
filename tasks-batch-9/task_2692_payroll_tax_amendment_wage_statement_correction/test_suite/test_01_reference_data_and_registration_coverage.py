"""Reference data, registration coverage and the immutable payroll evidence rows.

Employers, taxing agencies, agency-account registrations, employees and payroll
register lines are the world every correction case lives in, so this file covers
their creation shapes, their derived and defaulted fields, the quarter-range
overlap rule that governs registrations, and the two common-field profiles.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ACCOUNT_PERIOD_OVERLAP,
    ERR_CORRECTION_CASE_NOT_FOUND,
    ERR_EMPLOYER_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_evidence_common_fields,
    assert_pagination,
    assert_period_ordinals,
)
from test_helpers.constants import (
    CANON_CLOCK,
    DEFAULT_LIMIT,
    OPEN_ENDED_PERIOD_ORDINAL,
    UNKNOWN_CASE_ID,
    period_ordinal,
)
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, PREPARER_HEADERS


class TestEmployerRegistration:
    def test_employer_creation_returns_every_declared_field(self, api):
        """Registering an employer answers 201 with the four supplied fields and
        the three derived counters seeded to zero.

        PRD: "Three derived counters are seeded to zero at registration and are never writable thereafter: `open_exposure_cents`, `open_remediation_count` and `granted_abatement_count`."

        Design: Corner/entities/employer_creation_returns_every_declared_field
        """
        response = api.create_employer(
            f.employer_payload(
                legal_name="Acme Manufacturing",
                fein="12-3456789",
                deposit_schedule="SEMIWEEKLY",
                authorization_limit_cents=5000000,
            ),
            ADMIN_HEADERS,
        )
        employer = validate_success(response, 201)

        assert_common_fields(employer)
        assert employer["legal_name"] == "Acme Manufacturing"
        assert employer["fein"] == "12-3456789"
        assert employer["deposit_schedule"] == "SEMIWEEKLY"
        assert employer["authorization_limit_cents"] == 5000000
        assert employer["open_exposure_cents"] == 0
        assert employer["open_remediation_count"] == 0
        assert employer["granted_abatement_count"] == 0
        assert employer["version"] == 1

    def test_employer_system_fields_are_server_minted_and_client_input_ignored(self, api):
        """A client-supplied `id` and client-supplied derived counters are ignored:
        the row is reachable only under the server-minted identifier.

        PRD: "Every persisted row carries an `id` that is a server-minted UUID."

        Design: Corner/entities/employer_system_fields_are_server_minted_and_client_input_ignored
        """
        employer = validate_success(
            api.create_employer(
                f.employer_payload(
                    id="client-supplied-id",
                    open_exposure_cents=999999,
                    open_remediation_count=7,
                    granted_abatement_count=3,
                    version=42,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert employer["id"] != "client-supplied-id"
        assert employer["open_exposure_cents"] == 0
        assert employer["open_remediation_count"] == 0
        assert employer["granted_abatement_count"] == 0
        assert employer["version"] == 1

        validate_error(
            api.get_employer("client-supplied-id", ADMIN_HEADERS), ERR_EMPLOYER_NOT_FOUND, 404
        )
        assert validate_success(api.get_employer(employer["id"], ADMIN_HEADERS))["id"] == (
            employer["id"]
        )

    def test_patch_employer_updates_only_the_supplied_fields(self, api):
        """Two successive single-field adjustments each move exactly one axis and
        each increment the employer's version.

        PRD: "Employers can later be adjusted along exactly two axes — `deposit_schedule` and `authorization_limit_cents` — and any such adjustment increments the employer's `version`."

        Design: Corner/endpoints/patch_employer_updates_only_the_supplied_fields
        """
        employer = fx.make_employer(api)
        assert employer["version"] == 1

        first = validate_success(
            api.patch_employer(
                employer["id"], f.employer_patch_payload(deposit_schedule="MONTHLY"), ADMIN_HEADERS
            )
        )
        assert first["deposit_schedule"] == "MONTHLY"
        assert first["authorization_limit_cents"] == 5000000
        assert first["legal_name"] == employer["legal_name"]
        assert first["version"] == 2

        second = validate_success(
            api.patch_employer(
                employer["id"],
                f.employer_patch_payload(authorization_limit_cents=9000000),
                ADMIN_HEADERS,
            )
        )
        assert second["authorization_limit_cents"] == 9000000
        assert second["deposit_schedule"] == "MONTHLY"
        assert second["version"] == 3


class TestTaxAgency:
    def test_tax_agency_retrieval_returns_the_stored_row(self, api):
        """A state agency reads back with the whole regime it was created with.

        PRD: "Four numbers define its arithmetic: `interest_rate_bps_annual` is the annual statutory interest rate in basis points, between 0 and 10000; `interest_method` is either `STATUTORY_DAILY` or `DEPOSIT_WEIGHTED` and selects which interest variant every amendment for this agency uses; `penalty_multiplier_bps` is an agency-specific scaling between 0 and 20000 applied to the floored gross penalty; and `min_days_between_amendments`, a non-negative whole-day count, is the cooling-off buffer measured from the previous amendment's transmission for the same employer, agency, tax year and quarter slot."

        Design: Corner/entities/tax_agency_retrieval_returns_the_stored_row
        """
        created = validate_success(
            api.create_tax_agency(
                f.state_agency_payload(
                    agency_code="NY-WH",
                    level="STATE",
                    jurisdiction_code="NY",
                    interest_rate_bps_annual=1200,
                    interest_method="DEPOSIT_WEIGHTED",
                    penalty_multiplier_bps=7500,
                    min_days_between_amendments=30,
                    amendment_window_days=1095,
                    requires_registration=True,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        fetched = validate_success(api.get_tax_agency(created["id"], ADMIN_HEADERS))

        assert_common_fields(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["agency_code"] == "NY-WH"
        assert fetched["level"] == "STATE"
        assert fetched["jurisdiction_code"] == "NY"
        assert fetched["interest_rate_bps_annual"] == 1200
        assert fetched["interest_method"] == "DEPOSIT_WEIGHTED"
        assert fetched["penalty_multiplier_bps"] == 7500
        assert fetched["min_days_between_amendments"] == 30
        assert fetched["amendment_window_days"] == 1095
        assert fetched["requires_registration"] is True


class TestRegistrationCoverage:
    def test_agency_account_defaults_applied_when_optional_fields_omitted(self, api):
        """A registration created with only the mandatory opening quarter lands in
        PENDING with an open-ended closing ordinal and every optional field null.

        PRD: "Both closing fields may be omitted, in which case the coverage is open-ended."

        Design: Corner/entities/agency_account_defaults_applied_when_optional_fields_omitted
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)

        account = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_common_fields(account)
        assert account["account_number"] is None
        assert account["effective_to_tax_year"] is None
        assert account["effective_to_quarter"] is None
        assert account["retroactive"] is False
        assert account["registration_status"] == "PENDING"
        assert account["activated_at"] is None
        assert account["from_period_ordinal"] == period_ordinal(2025, 1)
        assert account["to_period_ordinal"] == OPEN_ENDED_PERIOD_ORDINAL

    @pytest.mark.parametrize(
        "from_year,from_quarter,to_year,to_quarter,expected_from,expected_to",
        [
            (2025, 1, 2025, 3, 8100, 8102),
            (2025, 3, 2026, 2, 8102, 8105),
        ],
    )
    def test_agency_account_period_ordinals_computed_from_year_and_quarter(
        self, api, from_year, from_quarter, to_year, to_quarter, expected_from, expected_to
    ):
        """Both coverage ordinals are derived by the tax year times four plus the
        quarter minus one, never supplied by the client.

        PRD: "Quarters are compared through a single integer coordinate called a **period ordinal**, computed as the tax year multiplied by four plus the quarter minus one."

        Design: Corner/entities/agency_account_period_ordinals_computed_from_year_and_quarter
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)

        account = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=from_year,
                    effective_from_quarter=from_quarter,
                    effective_to_tax_year=to_year,
                    effective_to_quarter=to_quarter,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        assert_period_ordinals(account, expected_from, expected_to)
        assert account["from_period_ordinal"] == period_ordinal(from_year, from_quarter)
        assert account["to_period_ordinal"] == period_ordinal(to_year, to_quarter)

    def test_agency_account_activate_moves_pending_to_active(self, api):
        """Activation with an account number turns a pending registration into live
        coverage and increments its version.

        PRD: "On the ordinary branch, `PENDING → ACTIVE` records the supplied `account_number`, stamps `activated_at` with the current logical instant, and increments the registration's `version` by 1."

        Design: Corner/state_machines/agency_account_activate_moves_pending_to_active
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)
        account = validate_success(
            api.create_agency_account(
                f.agency_account_payload(employer["id"], agency["id"]), ADMIN_HEADERS
            ),
            201,
        )
        assert account["registration_status"] == "PENDING"

        activated = validate_success(
            api.activate_agency_account(
                account["id"], {"account_number": "NY-99123"}, ADMIN_HEADERS
            )
        )

        assert activated["registration_status"] == "ACTIVE"
        assert activated["account_number"] == "NY-99123"
        assert activated["version"] == 2

    def test_activate_side_effects_record_account_number_and_activation_instant(self, api):
        """The activation instant is read from the logical clock, not from wall time,
        and the coverage ordinals are untouched by activation.

        PRD: "Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to real wall-clock time."

        Design: Corner/state_machines/activate_side_effects_record_account_number_and_activation_instant
        """
        fx.set_clock(api, "2026-03-15T00:00:00Z")
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)
        account = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )

        activated = validate_success(
            api.activate_agency_account(
                account["id"], {"account_number": "NY-99123"}, ADMIN_HEADERS
            )
        )

        assert activated["account_number"] == "NY-99123"
        assert activated["activated_at"].startswith("2026-03-15T00:00:00")
        assert activated["version"] == 2
        assert_period_ordinals(activated, 8100, OPEN_ENDED_PERIOD_ORDINAL)

    def test_second_activate_on_an_active_account_returns_invalid_state(self, api):
        """Activation is reachable only from a pending form, so repeating it on live
        coverage is a state error and leaves the row untouched.

        PRD: "Activation is what turns either pending form into live coverage, and it requires an `account_number` in the request body: without it the activation cannot proceed."

        Design: Corner/state_machines/second_activate_on_an_active_account_returns_invalid_state
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)
        account = validate_success(
            api.create_agency_account(
                f.agency_account_payload(employer["id"], agency["id"]), ADMIN_HEADERS
            ),
            201,
        )
        validate_success(
            api.activate_agency_account(
                account["id"], {"account_number": "NY-99123"}, ADMIN_HEADERS
            )
        )

        validate_error(
            api.activate_agency_account(
                account["id"], {"account_number": "NY-99999"}, ADMIN_HEADERS
            ),
            ERR_INVALID_STATE,
            409,
        )

        unchanged = validate_success(api.get_agency_account(account["id"], ADMIN_HEADERS))
        assert unchanged["registration_status"] == "ACTIVE"
        assert unchanged["account_number"] == "NY-99123"
        assert unchanged["version"] == 2

    def test_overlapping_quarter_ranges_are_refused_on_every_live_sibling_status(self, api):
        """A new registration whose closed-closed ordinal interval intersects a live
        sibling's interval is refused, both while the sibling is pending and once it
        is active.

        PRD: "Two registrations for the same employer and agency may not cover overlapping quarter ranges: if the closed-closed ordinal interval of a new registration intersects the interval of any sibling registration for that employer-agency pair whose `registration_status` is `PENDING`, `RETRO_PENDING`, `ACTIVE` or `RETRO_ACTIVE`, the creation is refused with `ERR_ACCOUNT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agency_account_quarter_ranges_reject_overlap_but_admit_adjacency
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)

        sibling = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                    effective_to_tax_year=2025,
                    effective_to_quarter=2,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_period_ordinals(sibling, 8100, 8101)
        assert sibling["registration_status"] == "PENDING"

        # 8101..8103 intersects 8100..8101 at 8101 while the sibling is PENDING.
        validate_error(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=2,
                    effective_to_tax_year=2025,
                    effective_to_quarter=4,
                ),
                ADMIN_HEADERS,
            ),
            ERR_ACCOUNT_PERIOD_OVERLAP,
            409,
        )

        # An open-ended range starting at 8100 swallows the sibling entirely.
        validate_error(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                ),
                ADMIN_HEADERS,
            ),
            ERR_ACCOUNT_PERIOD_OVERLAP,
            409,
        )

        validate_success(
            api.activate_agency_account(
                sibling["id"], {"account_number": "NY-99123"}, ADMIN_HEADERS
            )
        )

        # ACTIVE blocks exactly as PENDING did.
        validate_error(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=2,
                    effective_to_tax_year=2025,
                    effective_to_quarter=4,
                ),
                ADMIN_HEADERS,
            ),
            ERR_ACCOUNT_PERIOD_OVERLAP,
            409,
        )

        rows, meta = validate_paginated(
            api.list_agency_accounts({"employer_id": employer["id"]}, ADMIN_HEADERS)
        )
        assert_pagination(meta, total_count=1)
        assert len(rows) == 1

    def test_adjacent_quarter_ranges_are_explicitly_permitted(self, api):
        """Ranges that merely touch — the new opening ordinal exactly one greater
        than a sibling's closing ordinal — are adjacent, not overlapping.

        PRD: "Ranges that merely touch — where the new registration's opening ordinal is exactly one greater than a sibling's closing ordinal — are adjacent, not overlapping, and are explicitly permitted."

        Design: Difficulty/resource_temporal_overlap/agency_account_quarter_ranges_reject_overlap_but_admit_adjacency
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_state_agency(api)

        first = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=1,
                    effective_to_tax_year=2025,
                    effective_to_quarter=2,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_period_ordinals(first, 8100, 8101)

        # 8102 is exactly one greater than 8101.
        second = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2025,
                    effective_from_quarter=3,
                    effective_to_tax_year=2025,
                    effective_to_quarter=4,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_period_ordinals(second, 8102, 8103)

        # 8104 is exactly one greater than 8103, and the tail is open-ended.
        third = validate_success(
            api.create_agency_account(
                f.agency_account_payload(
                    employer["id"],
                    agency["id"],
                    effective_from_tax_year=2026,
                    effective_from_quarter=1,
                ),
                ADMIN_HEADERS,
            ),
            201,
        )
        assert_period_ordinals(third, 8104, OPEN_ENDED_PERIOD_ORDINAL)

        rows, meta = validate_paginated(
            api.list_agency_accounts({"employer_id": employer["id"]}, ADMIN_HEADERS)
        )
        assert_pagination(meta, total_count=3)
        assert len(rows) == 3


class TestRosterAndPayrollEvidence:
    def test_create_employee_missing_required_full_name_returns_invalid_request(self, api):
        """`full_name` is mandatory, so omitting it fails body validation before any
        row is written.

        PRD: "Employees are added to an employer's roster with an `employer_id`, a `full_name` of 1 to 120 characters, `national_id_last4` written as exactly four digits, and a `mailing_state_code` of exactly two upper-case characters that governs where paper statements are delivered."

        Design: Corner/entities/create_employee_missing_required_full_name_returns_invalid_request
        """
        employer = fx.make_employer(api)

        validate_error(
            api.create_employee(
                f.employee_payload(employer["id"], full_name=f.OMIT), ANALYST_HEADERS
            ),
            ERR_INVALID_REQUEST,
            400,
        )

        rows, meta = validate_paginated(
            api.list_employees({"employer_id": employer["id"]}, ANALYST_HEADERS)
        )
        assert_pagination(meta, total_count=0)
        assert rows == []

    def test_register_line_with_quarter_five_returns_invalid_request(self, api):
        """The calendar has exactly four quarters, so a fifth quarter has no derivable
        period and fails general body validation.

        PRD: "For a return covering the first quarter the original due date is the thirtieth of April of the same tax year at midnight UTC; for the second quarter, the thirty-first of July of the same tax year; for the third quarter, the thirty-first of October of the same tax year; and for the fourth quarter, the thirty-first of January of the *following* calendar year."
        PRD: "Schema validation follows, in three steps: general body validation (`ERR_INVALID_REQUEST`), then pagination bounds on list endpoints (`ERR_INVALID_PAGINATION`), then the repayment-specific arithmetic and year-ordering rule (`ERR_INVALID_RECOVERY_YEAR`)."

        Design: Corner/entities/register_line_with_quarter_five_returns_invalid_request
        """
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        employee = fx.make_employee(api, employer["id"])

        validate_error(
            api.create_register_line(
                f.register_line_payload(
                    employer["id"], employee["id"], agency["id"], quarter=5
                ),
                ANALYST_HEADERS,
            ),
            ERR_INVALID_REQUEST,
            400,
        )

    def test_payroll_register_line_is_immutable_and_carries_no_version(self, api):
        """A posted line carries only `id` and `created_at`, and its workday share
        defaults to the whole line.

        PRD: "Register lines are never modified after posting: they carry no `version` field and no `updated_at`."

        Design: Corner/entities/payroll_register_line_is_immutable_and_carries_no_version
        """
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        employee = fx.make_employee(api, employer["id"])

        line = validate_success(
            api.create_register_line(
                f.register_line_payload(
                    employer["id"],
                    employee["id"],
                    agency["id"],
                    taxable_wage_cents=3000000,
                    withheld_cents=450000,
                ),
                ANALYST_HEADERS,
            ),
            201,
        )

        assert_evidence_common_fields(line)
        assert line["posting_status"] == "POSTED"
        assert line["workday_ratio_bps"] == 10000
        assert line["taxable_wage_cents"] == 3000000
        assert line["withheld_cents"] == 450000

        fetched = validate_success(api.get_register_line(line["id"], ANALYST_HEADERS))
        assert_evidence_common_fields(fetched)

    def test_register_line_with_unknown_employer_fk_returns_not_found(self, api):
        """A body reference to a row that does not exist is an existence failure,
        answered with that entity's own not-found error.

        PRD: "Every such reference must name an existing row of the entity it points at, and a dangling reference produces the same 404 code family: an unknown employer reference yields `ERR_EMPLOYER_NOT_FOUND`, an unknown agency reference `ERR_TAX_AGENCY_NOT_FOUND`, an unknown employee reference `ERR_EMPLOYEE_NOT_FOUND`, an unknown case reference `ERR_CORRECTION_CASE_NOT_FOUND`, an unknown predecessor amendment reference `ERR_AMENDED_RETURN_NOT_FOUND`, and an unknown predecessor statement reference `ERR_STATEMENT_NOT_FOUND`."

        Design: Corner/entities/register_line_with_unknown_employer_fk_returns_not_found
        """
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        employee = fx.make_employee(api, employer["id"])

        validate_error(
            api.create_register_line(
                f.register_line_payload(UNKNOWN_CASE_ID, employee["id"], agency["id"]),
                ANALYST_HEADERS,
            ),
            ERR_EMPLOYER_NOT_FOUND,
            404,
        )


class TestCorrectionCaseDiscovery:
    def test_correction_case_listing_paginates_with_total_count_and_has_more(self, api):
        """Three cases windowed two at a time report the pre-window match count and
        whether rows remain beyond the window.

        PRD: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before the window is applied and `has_more` indicates whether rows remain beyond the current window."

        Design: Corner/entities/correction_case_listing_paginates_with_total_count_and_has_more
        """
        fx.set_clock(api, CANON_CLOCK)
        employer = fx.make_employer(api)
        agency = fx.make_federal_agency(api)
        for quarter in (1, 2, 3):
            fx.make_correction_case(api, employer["id"], agency["id"], quarter=quarter)

        first_rows, first_meta = validate_paginated(
            api.list_correction_cases(
                {"employer_id": employer["id"], "limit": 2, "offset": 0}, ANALYST_HEADERS
            )
        )
        assert len(first_rows) == 2
        assert_pagination(first_meta, limit=2, offset=0, total_count=3, has_more=True)

        second_rows, second_meta = validate_paginated(
            api.list_correction_cases(
                {"employer_id": employer["id"], "limit": 2, "offset": 2}, ANALYST_HEADERS
            )
        )
        assert len(second_rows) == 1
        assert_pagination(second_meta, limit=2, offset=2, total_count=3, has_more=False)

        default_rows, default_meta = validate_paginated(
            api.list_correction_cases({"employer_id": employer["id"]}, ANALYST_HEADERS)
        )
        assert_pagination(default_meta, limit=DEFAULT_LIMIT, offset=0, total_count=3, has_more=False)
        assert len(default_rows) == 3

    def test_get_correction_case_with_unknown_id_returns_not_found(self, api):
        """An unknown case identifier yields the case-specific not-found error.

        PRD: "Consequently there is no left-to-right path hierarchy to validate: each endpoint carries at most one path parameter, and that parameter must name an existing row of its own entity or the request fails with HTTP 404 carrying the entity-specific code — `ERR_EMPLOYER_NOT_FOUND`, `ERR_TAX_AGENCY_NOT_FOUND`, `ERR_AGENCY_ACCOUNT_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`, `ERR_REGISTER_LINE_NOT_FOUND`, `ERR_DEPOSIT_RECORD_NOT_FOUND`, `ERR_FILED_RETURN_NOT_FOUND`, `ERR_CORRECTION_CASE_NOT_FOUND`, `ERR_DISCREPANCY_NOT_FOUND`, `ERR_AMENDED_RETURN_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_WAGE_REPAYMENT_NOT_FOUND`, `ERR_AGENCY_NOTICE_NOT_FOUND` or `ERR_CONTROL_REMEDIATION_NOT_FOUND`."

        Design: Corner/entities/get_correction_case_with_unknown_id_returns_not_found
        """
        validate_error(
            api.get_correction_case(UNKNOWN_CASE_ID, PREPARER_HEADERS),
            ERR_CORRECTION_CASE_NOT_FOUND,
            404,
        )
