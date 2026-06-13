"""Entity CRUD / endpoint tests: creation defaults, required fields, type constraints,
not-found, listing/pagination, computed fields, uniqueness, immutability, and assorted
action endpoints.

Queue B (Corner): entities.* and endpoints.* instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_employer,
    create_pay_period,
    create_worker,
    post_time_entry,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["payroll_officer_headers"]


# ===========================================================================
# Queue B — entities / create_employer_returns_201_with_computed_defaults
# ===========================================================================
def test_create_employer_returns_201_with_computed_defaults(api):
    """PRD §3.1: "At creation the employer's `posture` is initialized to `HEALTHY` and its
    `outstanding_principal_cents` is initialized to 0."
    PRD §2.4: "Each also carries a `version`, an integer that starts at the resource's creation
    value and increments by one on every mutation".
    PRD §4: "Operations that create a new, stand-alone resource return a `201 Created` status
    code."

    Design: Corner/entities/create_employer_returns_201_with_computed_defaults
    """
    get_success_data(api.set_clock("2026-06-01T00:00:00Z", ADMIN))
    created = validate_success(
        api.create_employer({"legal_name": "Acme", "state_code": "CA",
                             "pay_frequency": "WEEKLY", "funding_balance_cents": 100000}, ADMIN),
        expected_status=201,
    )
    assert created["posture"] == "HEALTHY"
    assert created["outstanding_principal_cents"] == 0
    assert created["version"] == 1


# ===========================================================================
# Queue B — entities / create_employer_missing_legal_name_returns_invalid_request
# ===========================================================================
def test_create_employer_missing_legal_name_returns_invalid_request(api):
    """PRD §3.1: "An employer is created with a `legal_name`, a `state_code` naming the US state
    of payroll (for example, CA or TX), and a `pay_frequency`".
    PRD §2.11: "Request well-formedness — all required fields present, enums within their allowed
    sets, numbers within declared bounds — is checked fifth, yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_employer_missing_legal_name_returns_invalid_request
    """
    resp = api.create_employer({"state_code": "CA", "pay_frequency": "WEEKLY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — entities / create_employer_invalid_pay_frequency_enum_returns_invalid_request
# ===========================================================================
def test_create_employer_invalid_pay_frequency_enum_returns_invalid_request(api):
    """PRD §3.1: "a `pay_frequency`, which must be one of `WEEKLY`, `BIWEEKLY`, or `SEMIMONTHLY`."
    PRD §2.11: "Request well-formedness — all required fields present, enums within their allowed
    sets, numbers within declared bounds — is checked fifth, yielding `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_employer_invalid_pay_frequency_enum_returns_invalid_request
    """
    resp = api.create_employer({"legal_name": "Acme", "state_code": "CA", "pay_frequency": "DAILY"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — entities / get_employer_nonexistent_returns_not_found
# ===========================================================================
def test_get_employer_nonexistent_returns_not_found(api):
    """PRD §2.10: "For any request whose path names a resource, the system first confirms that
    path resource exists ... The first path identifier that does not resolve yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_employer_nonexistent_returns_not_found
    """
    resp = api.get_employer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue B — entities / list_workers_paginated_envelope
# ===========================================================================
def test_list_workers_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope, where `total_count` reflects the full size of the
    filtered collection and `has_more` indicates whether further pages remain."

    Two workers, limit=1 => page of 1, total_count 2, has_more true.

    Design: Corner/entities/list_workers_paginated_envelope
    """
    employer = create_employer()
    create_worker(employer["id"], external_payroll_ref="EMP-1", full_name="Wanda")
    create_worker(employer["id"], external_payroll_ref="EMP-2", full_name="Walt", hourly_rate_cents=2500)

    resp = api.list_workers(OFFICER, params={"employer_id": employer["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return 1 item; got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2; got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true with another page; got {meta['has_more']}"


# ===========================================================================
# Queue B — entities / computed_fields_ignored_when_supplied_on_create
# ===========================================================================
def test_worker_computed_tenure_and_available_on_create(api):
    """PRD §3.2: "The worker's `tenure_days` is computed as the whole number of days between the
    server clock and `hire_date`, taking the floor; this value selects the worker's advance limit
    policy tier."
    PRD §3.4: "of what this worker has earned so far in the employer's current open or locked pay
    period, how much may still be advanced after accounting for advances already committed against
    the same period?"

    Clock 2026-06-01, hire 2025-06-01 => tenure 365; no time entries => net available 0.

    Design: Corner/entities/computed_fields_ignored_when_supplied_on_create
    """
    employer = create_employer()
    worker = validate_success(
        api.create_worker({"employer_id": employer["id"], "external_payroll_ref": "EMP-1",
                           "full_name": "Wanda", "hourly_rate_cents": 2000,
                           "hire_date": "2025-06-01T00:00:00Z"}, OFFICER),
        expected_status=201,
    )
    assert worker["tenure_days"] == 365, f"tenure must be 365; got {worker['tenure_days']}"
    assert worker["net_available_earnings_cents"] == 0, (
        f"no time entries => available 0; got {worker['net_available_earnings_cents']}"
    )


# ===========================================================================
# Queue B — entities / duplicate_external_payroll_ref_rejected
# ===========================================================================
def test_duplicate_external_payroll_ref_rejected(api):
    """PRD §3.2: "The `external_payroll_ref` must be unique per employer among workers that are
    not terminated; reusing one that is already held by a non-terminated worker for the same
    employer is rejected with `ERR_DUPLICATE_PAYROLL_REF`."

    Design: Corner/entities/duplicate_external_payroll_ref_rejected
    """
    employer = create_employer()
    create_worker(employer["id"], external_payroll_ref="EMP-1", full_name="Wanda")

    resp = api.create_worker({"employer_id": employer["id"], "external_payroll_ref": "EMP-1",
                              "full_name": "Walt", "hourly_rate_cents": 2500,
                              "hire_date": "2025-06-01T00:00:00Z"}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYROLL_REF.value)


# ===========================================================================
# Queue B — entities / time_entry_immutable_no_version_field
# ===========================================================================
def test_time_entry_has_no_version_and_computed_gross(api):
    """PRD §2.4: "A `TimeEntry` and a `Repayment` are write-once ledger rows: each carries only an
    `id` and a `created_at`. Neither a `TimeEntry` nor a `Repayment` carries an `updated_at` or a
    `version` field — those fields are absent entirely for these two entities."
    PRD §3.3: "Each entry also exposes a per-entry display value, `gross_earned_cents`, computed
    by rounding the product of `hours_worked` and the worker's `hourly_rate_cents` half up to
    whole cents."

    4h @ 2000 => gross_earned_cents 8000; the row exposes id + created_at but no version/updated_at.

    Design: Corner/entities/time_entry_immutable_no_version_field
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    te = validate_success(
        api.create_time_entry({"pay_period_id": period["id"], "worker_id": worker["id"],
                               "shift_start_at": "2026-06-02T08:00:00Z",
                               "shift_end_at": "2026-06-02T12:00:00Z", "hours_worked": 4.0}, OFFICER),
        expected_status=201,
    )
    assert te["gross_earned_cents"] == 8000, f"gross must be round(4*2000)=8000; got {te['gross_earned_cents']}"
    assert "version" not in te, "TimeEntry must not expose a version field"
    assert "updated_at" not in te, "TimeEntry must not expose an updated_at field"


# ===========================================================================
# Queue B — endpoints / cross_employer_reference_rejected_on_advance_create
# ===========================================================================
def test_cross_employer_reference_rejected_on_advance_create(api):
    """PRD §2.10: "For an advance creation, a repayment batch creation, and a time entry creation,
    the system resolves the body's foreign keys ... and confirms they exist and share a single
    `employer_id`. A body foreign key that exists but belongs to a different employer (or a worker
    and pay period whose employers disagree) is rejected with `ERR_CROSS_EMPLOYER_REFERENCE` (HTTP
    422)."

    Worker under emp1, pay period under emp2 => ERR_CROSS_EMPLOYER_REFERENCE (422).

    Design: Corner/endpoints/cross_employer_reference_rejected_on_advance_create
    """
    emp1 = create_employer(legal_name="Acme", state_code="CA")
    emp2 = create_employer(clock=None, legal_name="Beta", state_code="TX")
    worker = create_worker(emp1["id"], external_payroll_ref="EMP-1")
    pp2 = create_pay_period(emp2["id"])
    w_v = validate_success(api.get_worker(worker["id"], OFFICER))["version"]

    resp = api.create_advance({"worker_id": worker["id"], "pay_period_id": pp2["id"],
                               "requested_principal_cents": 3000, "disbursement_speed": "STANDARD",
                               "tip_cents": 0, "expected_worker_version": w_v}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_CROSS_EMPLOYER_REFERENCE.value)


# ===========================================================================
# Queue B — endpoints / funding_deposit_lifts_restricted_posture
# ===========================================================================
def test_funding_deposit_increases_balance_keeps_healthy(api):
    """PRD §3.1: "A `PlatformAdmin` can top up the pool at any time by depositing an
    `amount_cents`, which is added to `funding_balance_cents`; the deposit then triggers a
    recomputation of `posture`, which may lift a `RESTRICTED` employer back toward `HEALTHY` once
    the pool again covers outstanding exposure."

    Healthy employer funding 1000; deposit 9000 => funding 10000, posture stays HEALTHY.

    Design: Corner/endpoints/funding_deposit_lifts_restricted_posture
    """
    employer = create_employer(funding_balance_cents=1000)
    updated = validate_success(api.funding_deposit(employer["id"], {"amount_cents": 9000}, ADMIN))
    assert updated["funding_balance_cents"] == 10000, (
        f"deposit must add to balance; got {updated['funding_balance_cents']}"
    )
    assert updated["posture"] == "HEALTHY"


# ===========================================================================
# Queue B — endpoints / void_time_entry_recomputes_earnings
# ===========================================================================
def test_void_time_entry_recomputes_earnings(api):
    """PRD §3.3: "A `PayrollOfficer` may void a posted time entry, which sets its `status` to
    `VOIDED` and recomputes the affected period and worker earnings."
    PRD §3.3: "only `POSTED` entries count toward earnings and toward overlap detection."

    Voiding the only POSTED entry sets status VOIDED and drops gross_accrued_cents back to 0.

    Design: Corner/endpoints/void_time_entry_recomputes_earnings
    """
    employer = create_employer()
    period = create_pay_period(employer["id"])
    worker = create_worker(employer["id"])
    te = post_time_entry(period["id"], worker["id"], "2026-06-02T08:00:00Z", "2026-06-02T12:00:00Z", 4.0)

    voided = validate_success(api.void_time_entry(te["id"], OFFICER))
    assert voided["status"] == "VOIDED"
    pp = validate_success(api.get_pay_period(period["id"], OFFICER))
    assert pp["gross_accrued_cents"] == 0, (
        f"voiding the only entry must drop gross to 0; got {pp['gross_accrued_cents']}"
    )
