"""Reference integrity, required-field shape and enumerated-value rejection on the
creation and read paths of the commuter benefit program.

Every test builds its own program state through the documented endpoints and
then proves both the returned error identifier and the absence of any row the
rejected request would have written.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    PROGRAM_ADMIN,
    factories,
    fixtures,
)
from test_helpers.api_errors import (
    ERR_ACCOUNT_MISMATCH,
    ERR_ELECTION_NOT_FOUND,
    ERR_EMPLOYEE_NOT_FOUND,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
)

# Well-formed identifiers that resolve to nothing in an empty database.
UNKNOWN_ELECTION_ID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_EMPLOYEE_ID = "00000000-0000-4000-8000-0000000000ee"


def test_01_unknown_election_id_returns_the_election_scoped_not_found_code(api):
    """A syntactically valid but unknown election id in the path yields the
    entity-scoped 404 code and creates nothing.

    PRD 2.6: "Path parameters are resolved strictly left to right, and the first
    identifier that fails to resolve determines the error returned."
    PRD 2.6: "A failure yields HTTP 404 carrying the code for the entity that could
    not be found: `ERR_EMPLOYER_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_ELECTION_WINDOW_NOT_FOUND`, `ERR_BENEFIT_CATEGORY_NOT_FOUND`,
    `ERR_BENEFIT_ACCOUNT_NOT_FOUND`, `ERR_ELECTION_NOT_FOUND`,
    `ERR_TRANSIT_MEDIA_NOT_FOUND`, `ERR_ORDER_BATCH_NOT_FOUND`,
    `ERR_MEDIA_ORDER_NOT_FOUND`, `ERR_CARD_TRANSACTION_NOT_FOUND`,
    `ERR_SUBSTANTIATION_CLAIM_NOT_FOUND` or `ERR_PAYROLL_FILE_NOT_FOUND`."

    Design: Corner/entities/election_get_with_unknown_id_returns_election_not_found
    """
    error = validate_error(
        api.get_election(UNKNOWN_ELECTION_ID, PROGRAM_ADMIN), ERR_ELECTION_NOT_FOUND
    )

    assert error["error_id"] == ERR_ELECTION_NOT_FOUND
    assert isinstance(error.get("message"), str) and error["message"], (
        "an error payload must carry a human-readable message alongside error_id"
    )

    _rows, meta = validate_paginated(api.list_elections(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"a failed read must create no election, found {meta['total_count']}"
    )


def test_02_employer_registration_without_a_program_cap_is_rejected(api):
    """program_cap_cents is required at registration, so omitting it is a request
    shape failure rather than a silent default.

    PRD 3.1: "Three money ceilings are required at registration:
    `transit_group_limit_cents`, the monthly pre-tax exclusion limit shared by the
    whole transit side of the program; `parking_group_limit_cents`, the equivalent
    monthly limit for parking; and `program_cap_cents`, an aggregate ceiling on
    funded pre-tax exclusion across the entire employer."
    PRD 2.7: "Request shape: every required body field present, JSON types matching
    the declared field types, integer fields at or above their declared minimum,
    `benefit_month`, `period_month` and `assessment_month` matching exactly the
    four-digit year, a hyphen, and the two-digit month, ISO 8601 datetimes parsing,
    and `coverage_end_at` strictly after `coverage_start_at` —
    `ERR_INVALID_REQUEST`. Applies to every POST, PUT and PATCH endpoint."

    Design: Corner/entities/employer_create_missing_program_cap_returns_invalid_request
    """
    payload = {
        "legal_name": "No Cap Co",
        "region_code": "US-TX-AUS",
        "transit_group_limit_cents": 30000,
        "parking_group_limit_cents": 30000,
    }

    validate_error(api.create_employer(payload, PROGRAM_ADMIN), ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(api.list_employers(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"a rejected registration must create no employer, found {meta['total_count']}"
    )


def _enum_guard_employer(api):
    """A DRAFT employer to enrol against."""
    return fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Enum Guard Co",
        region_code="US-TX-AUS",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )


def test_03_enrolment_with_an_undeclared_payroll_cycle_is_rejected(api):
    """A payroll cycle outside the declared set is an enumerated-value failure, not
    a shape failure.

    PRD 3.1: "An enrolment payload names the `employer_id`, the employer-side
    payroll identifier `external_ref` (between 1 and 64 characters, and unique
    within an employer), the `work_region_code` where the employee reports — drawn
    from the same five-region set — and the deduction cadence `payroll_cycle`,
    either `SEMI_MONTHLY` or `MONTHLY`, which the payroll integration honours."
    PRD 2.7: "Enumerated values: every enum-typed body or query field carrying a
    value from that field's declared set, covering `region_code`,
    `work_region_code`, `category_type`, `eligible_category_type`, `media_type`,
    `payroll_cycle`, `spill_policy`, `rollover_policy`, `doc_type`,
    `rejection_reason`, the `reason` supplied when reporting media undelivered, the
    acknowledgement `outcome`, and the `entry_type` and `status` values used as
    list filters — `ERR_INVALID_ENUM_VALUE`. Applies to every endpoint accepting an
    enum body or query field."

    Design: Corner/entities/employee_create_with_unknown_payroll_cycle_returns_invalid_enum_value
    """
    employer = _enum_guard_employer(api)

    validate_error(
        api.create_employee(
            factories.employee_payload(
                employer["id"],
                external_ref="AUS-ENUM",
                work_region_code="US-TX-AUS",
                payroll_cycle="WEEKLY",
                hire_date="2026-02-01T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        ERR_INVALID_ENUM_VALUE,
    )

    _rows, meta = validate_paginated(api.list_employees(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"a rejected enrolment must create no employee, found {meta['total_count']}"
    )
    assert fixtures.read_employer(api, employer["id"])["enrolled_employee_count"] == 0


def test_04_enrolment_with_a_declared_payroll_cycle_is_accepted(api):
    """The other member of the declared cadence set is accepted and echoed, which is
    what makes the rejection of an undeclared value observable.

    PRD 3.1: "An enrolment payload names the `employer_id`, the employer-side
    payroll identifier `external_ref` (between 1 and 64 characters, and unique
    within an employer), the `work_region_code` where the employee reports — drawn
    from the same five-region set — and the deduction cadence `payroll_cycle`,
    either `SEMI_MONTHLY` or `MONTHLY`, which the payroll integration honours."
    PRD 3.1: "A new employee opens in `status` `ACTIVE` with `termination_date`
    null, `substantiation_hold` false and `repayment_due_cents` at zero; enrolment
    also recomputes the employer's `enrolled_employee_count` and advances
    `Employer.version` by 1."

    Design: Corner/entities/employee_create_with_unknown_payroll_cycle_returns_invalid_enum_value
    """
    employer = _enum_guard_employer(api)

    employee = validate_success(
        api.create_employee(
            factories.employee_payload(
                employer["id"],
                external_ref="AUS-ENUM",
                work_region_code="US-TX-AUS",
                payroll_cycle="SEMI_MONTHLY",
                hire_date="2026-02-01T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )

    assert employee["payroll_cycle"] == "SEMI_MONTHLY"
    assert employee["status"] == "ACTIVE"
    assert employee["termination_date"] is None
    assert employee["substantiation_hold"] is False
    assert employee["repayment_due_cents"] == 0


def test_05_benefit_account_naming_an_unknown_employee_returns_employee_not_found(api):
    """A body-supplied employee reference must resolve, and the failure carries the
    employee-scoped 404 code rather than the category code or a 422.

    PRD 2.6: "The same 404 family applies to identifiers supplied in a request
    **body** rather than a path."
    PRD 2.6: "Every creation payload that names another record — `employer_id`,
    `employee_id`, `election_window_id`, `benefit_category_id`, `transit_media_id`,
    `election_id`, `order_batch_id`, `card_transaction_id` — must resolve to an
    existing row, and the failure carries the same per-entity code (with a body
    `order_batch_id` reported as `ERR_ORDER_BATCH_NOT_FOUND`, a body
    `card_transaction_id` as `ERR_CARD_TRANSACTION_NOT_FOUND`, and a non-resolving
    benefit account as `ERR_BENEFIT_ACCOUNT_NOT_FOUND`)."
    PRD 3.1: "A benefit account is opened for one `employee_id` in one
    `benefit_category_id`, and the pair must be unique — that pair is exactly how an
    election later resolves which account it belongs to."

    Design: Corner/entities/benefit_account_create_with_unknown_employee_returns_employee_not_found
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000}
        ],
        legal_name="FK Guard Co",
        region_code="US-TX-AUS",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    category = built["categories"][0]

    validate_error(
        api.create_benefit_account(
            factories.benefit_account_payload(UNKNOWN_EMPLOYEE_ID, category["id"]),
            PROGRAM_ADMIN,
        ),
        ERR_EMPLOYEE_NOT_FOUND,
    )

    _rows, meta = validate_paginated(api.list_benefit_accounts(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"a rejected account create must open no account, found {meta['total_count']}"
    )


def test_06_election_for_a_category_without_a_paired_account_returns_account_mismatch(api):
    """The employee and the parking category both exist under the same active
    program, but no account exists for that pair, so the election is refused instead
    of an account being opened implicitly.

    PRD 3.3: "The service resolves `benefit_account_id` itself, as the unique
    benefit account whose `employee_id` and `benefit_category_id` both match the
    election; if no such account exists, or if the resolved account's `employee_id`
    or `benefit_category_id` fails to match the election's, the create is refused
    with `ERR_ACCOUNT_MISMATCH`."
    PRD 3.2: "A new window is created in `status` `SCHEDULED` with `locked_at` null
    and `election_count` at zero; that counter tracks elections in the window whose
    `funding_status` is `PENDING`, `HELD`, `FUNDED` or `SETTLED`."

    Design: Corner/entities/election_referencing_category_without_account_returns_account_mismatch
    """
    built = fixtures.make_active_employer(
        api,
        PROGRAM_ADMIN,
        categories=[
            {"category_type": "TRANSIT_PASS", "monthly_exclusion_limit_cents": 30000},
            {"category_type": "PARKING", "monthly_exclusion_limit_cents": 30000},
        ],
        legal_name="Pairwise Integrity Co",
        region_code="US-TX-AUS",
        transit_group_limit_cents=30000,
        parking_group_limit_cents=30000,
        program_cap_cents=5000000,
    )
    employer = built["employer"]
    transit_category, parking_category = built["categories"]

    enrolled = fixtures.make_enrolled_employee(
        api,
        employer["id"],
        transit_category["id"],
        PROGRAM_ADMIN,
        external_ref="AUS-PAIR-1",
        work_region_code="US-TX-AUS",
        hire_date="2026-02-01T00:00:00Z",
    )
    employee = enrolled["employee"]
    transit_account = enrolled["account"]

    window = fixtures.make_open_window(
        api,
        employer["id"],
        PROGRAM_ADMIN,
        benefit_month="2026-08",
        opens_at="2026-07-01T00:00:00Z",
        cutoff_at="2026-08-20T00:00:00Z",
    )

    validate_error(
        api.create_election(
            factories.election_payload(
                employee["id"],
                window["id"],
                parking_category["id"],
                transit_account["version"],
                pretax_amount_cents=5000,
                posttax_amount_cents=0,
            ),
            PROGRAM_ADMIN,
        ),
        ERR_ACCOUNT_MISMATCH,
    )

    assert fixtures.read_window(api, window["id"])["election_count"] == 0
    refreshed_parking = validate_success(
        api.get_benefit_category(parking_category["id"], PROGRAM_ADMIN)
    )
    assert refreshed_parking["active_election_count"] == 0
    refreshed_account = fixtures.read_account(api, transit_account["id"])
    assert refreshed_account["version"] == transit_account["version"], (
        "a refused election must not advance the untouched account's version"
    )
    _rows, meta = validate_paginated(api.list_elections(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"a refused election must create no row, found {meta['total_count']}"
    )
