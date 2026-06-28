"""Entity CRUD/validation, state-transition preconditions, listing/pagination,
and RBAC.

Corner queue B only: entities, state_machines, validations (pagination),
endpoints (listing), calculations (section125), rbac.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    fixtures,
    ApiErrorId,
    factories,
    NON_EXISTENT_UUID,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
_PAYROLL = TEST_USERS["payroll_headers"]
_EMPLOYEE = TEST_USERS["employee_headers"]


# ---------------------------------------------------------------------------
# Corner: entities / create_employer_returns_201_with_defaults
# ---------------------------------------------------------------------------
def test_create_employer_applies_defaults(api):
    """PRD §3.1: "The `section_125_plan_active` flag declares whether the employer
    sponsors a Section 125 cafeteria plan; it defaults to true when omitted and
    gates pre-tax elections. The `pay_periods_per_year` field sets payroll
    frequency and defaults to 52 when omitted"

    Design: Corner/entities/create_employer_returns_201_with_defaults
    """
    data = validate_success(
        api.create_employer({"legal_name": "Solo Co"}, _ADMIN), 201
    )
    assert data["section_125_plan_active"] is True
    assert data["pay_periods_per_year"] == 52
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1


# ---------------------------------------------------------------------------
# Corner: entities / get_employer_nonexistent_returns_not_found
# ---------------------------------------------------------------------------
def test_get_unknown_employer_returns_not_found(api):
    """PRD §2.7: "every resource identifier named in a path or request body ...
    must resolve to a real record. Identifiers are validated left-to-right in the
    order they appear, and the first unresolved identifier short-circuits the
    request with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_employer_nonexistent_returns_not_found
    """
    validate_error(
        api.get_employer(NON_EXISTENT_UUID, _ADMIN),
        ApiErrorId.ERR_NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# Corner: entities / create_plan_product_missing_required_field_rejected
# ---------------------------------------------------------------------------
def test_create_product_missing_premium_rejected(api):
    """PRD §3.2: "A product is created with a `policy_type` ... a base
    `weekly_premium_cents` (the per-week cost at guaranteed issue, before
    pay-period conversion, which must be zero or greater)"

    Design: Corner/entities/create_plan_product_missing_required_field_rejected
    """
    employer = fixtures.create_employer()
    payload = {
        "employer_id": employer["id"],
        "policy_type": "ACCIDENT",
        "product_name": "X",
        "annual_benefit_cap_cents": 500000,
    }
    validate_error(
        api.create_plan_product(payload, _ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


# ---------------------------------------------------------------------------
# Corner: entities / create_plan_product_bad_enum_policy_type_rejected
# ---------------------------------------------------------------------------
def test_create_product_bad_policy_type_rejected(api):
    """PRD §3.2: "A product is created with a `policy_type` of `ACCIDENT`,
    `CRITICAL_ILLNESS`, or `HOSPITAL_INDEMNITY`"

    Design: Corner/entities/create_plan_product_bad_enum_policy_type_rejected
    """
    employer = fixtures.create_employer()
    payload = factories.create_plan_product_payload(
        employer["id"], policy_type="DENTAL"
    )
    validate_error(
        api.create_plan_product(payload, _ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


# ---------------------------------------------------------------------------
# Corner: entities / disbursement_account_bad_routing_number_rejected
# ---------------------------------------------------------------------------
def test_disbursement_account_bad_routing_number_rejected(api):
    """PRD §3.4: "a `routing_number` that must be exactly 9 digits ... A non-9-digit
    routing number is a field-level validation failure."

    Design: Corner/entities/disbursement_account_bad_routing_number_rejected
    """
    employer = fixtures.create_employer()
    employee = fixtures.create_employee(employer["id"])
    payload = factories.create_disbursement_account_payload(
        employee["id"], routing_number="12345"
    )
    validate_error(
        api.create_disbursement_account(payload, _ADMIN),
        ApiErrorId.ERR_INVALID_REQUEST,
    )


# ---------------------------------------------------------------------------
# Corner: entities / employee_total_deduction_is_computed_input_ignored
# ---------------------------------------------------------------------------
def test_new_employee_total_deduction_is_zero(api):
    """PRD §3.4: "A new employee starts with `employment_status` of `EMPLOYED`
    (the alternative being `TERMINATED`) and a `total_weekly_deduction_cents` of
    0."

    Design: Corner/entities/employee_total_deduction_is_computed_input_ignored
    """
    employer = fixtures.create_employer()
    payload = factories.create_employee_payload(employer["id"])
    data = validate_success(api.create_employee(payload, _ADMIN), 201)
    assert data["total_weekly_deduction_cents"] == 0
    assert data["employment_status"] == "EMPLOYED"


# ---------------------------------------------------------------------------
# Corner: entities / schedule_item_no_version_field_immutable_entity
# ---------------------------------------------------------------------------
def test_schedule_item_has_no_version_field(api):
    """PRD §2.4: "A `BenefitScheduleItem` is immutable after creation: it carries
    only `id` and `created_at`, and it has neither an `updated_at` nor a `version`
    field."

    Design: Corner/entities/schedule_item_no_version_field_immutable_entity
    """
    employer = fixtures.create_employer()
    product = fixtures.create_product(employer["id"])
    item = fixtures.add_schedule_item(product["id"], event_code="FRACTURE", flat_benefit_cents=200000)
    data = validate_success(api.get_schedule_item(item["id"], _ADMIN))
    assert "version" not in data
    assert "updated_at" not in data
    assert data["flat_benefit_cents"] == 200000


# ---------------------------------------------------------------------------
# Corner: state_machines / start_review_from_under_review_invalid_state
# ---------------------------------------------------------------------------
def test_start_review_on_under_review_claim_invalid_state(api):
    """PRD §3.8: "Beginning review moves the claim from `SUBMITTED` to
    `UNDER_REVIEW` (permitted only from `SUBMITTED`)."

    Design: Corner/state_machines/start_review_from_under_review_invalid_state
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    validate_error(
        api.start_review_claim(claim["id"], _ADJUSTER),
        ApiErrorId.ERR_INVALID_STATE,
    )
    data = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert data["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Corner: state_machines / terminal_paid_claim_cannot_void
# ---------------------------------------------------------------------------
def test_void_on_paid_claim_invalid_state(api):
    """PRD §3.9: "an `APPROVED` claim with no settled disbursement may be
    **voided** by a `ClaimsAdjuster`, moving it from `APPROVED` to the terminal
    `VOIDED` state"

    Design: Corner/state_machines/terminal_paid_claim_cannot_void
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim, disb = fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    validate_error(
        api.void_claim(claim["id"], _ADJUSTER),
        ApiErrorId.ERR_INVALID_STATE,
    )
    data = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert data["status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner: state_machines / open_product_with_empty_schedule_rejected
# ---------------------------------------------------------------------------
def test_open_product_with_no_schedule_items_rejected(api):
    """PRD §3.2: "A product moves from `DRAFT` to `OPEN` only when at least one
    `BenefitScheduleItem` exists for it; opening a product with no schedule lines
    is rejected with `ERR_SCHEDULE_EMPTY`."

    Design: Corner/state_machines/open_product_with_empty_schedule_rejected
    """
    employer = fixtures.create_employer()
    product = fixtures.create_product(employer["id"])
    validate_error(
        api.open_plan_product(product["id"], _ADMIN),
        ApiErrorId.ERR_SCHEDULE_EMPTY,
    )
    data = validate_success(api.get_plan_product(product["id"], _ADMIN))
    assert data["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Corner: state_machines / pretax_enrollment_activate_blocked_when_section125_inactive
# ---------------------------------------------------------------------------
def test_pretax_activate_blocked_when_section125_inactive(api):
    """PRD §3.6: "if the enrollment was elected `pretax`, the employer's
    `section_125_plan_active` must be true (otherwise `ERR_SECTION125_INACTIVE`)."

    Design: Corner/state_machines/pretax_enrollment_activate_blocked_when_section125_inactive
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment(
        employer_overrides={"section_125_plan_active": False},
        enrollment_overrides={"pretax": True},
    )
    validate_error(
        api.activate_enrollment(enr["id"], _ADMIN),
        ApiErrorId.ERR_SECTION125_INACTIVE,
    )
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["lifecycle_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: calculations / section125_annual_pretax_locked_at_activation
# ---------------------------------------------------------------------------
def test_section125_election_locked_at_activation(api):
    """PRD §3.6: "If the enrollment is pre-tax, activation also creates a
    `Section125Election` in `LOCKED` `status` ... the election's
    `annual_pretax_amount_cents` is locked at the enrollment's frozen
    `weekly_premium_cents` multiplied by 52, representing the irrevocable annual
    pre-tax election."

    Design: Corner/calculations/section125_annual_pretax_locked_at_activation
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment(
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0},
        enrollment_overrides={"pretax": True},
    )
    activated = validate_success(api.activate_enrollment(enr["id"], _ADMIN))
    assert activated["lifecycle_status"] == "ACTIVE"
    rows, _meta = validate_paginated(
        api.list_section125_elections(_ADMIN, params={"enrollment_id": enr["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "LOCKED"
    assert rows[0]["annual_pretax_amount_cents"] == 62400


# ---------------------------------------------------------------------------
# Corner: validations / reference_mismatch_account_not_owned_by_enrollment_employee
# ---------------------------------------------------------------------------
def test_claim_account_not_owned_by_enrollment_employee_rejected(api):
    """PRD §2.7: "when a claim is filed, the named disbursement account must belong
    to the same employee that owns the enrollment ... Any such cross-aggregate
    mismatch is rejected with `ERR_REFERENCE_MISMATCH`."

    Design: Corner/validations/reference_mismatch_account_not_owned_by_enrollment_employee
    """
    employer, prod, period, items = fixtures.setup_open_product_and_period(
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
    )
    emp_x = fixtures.create_employee(employer["id"])
    emp_y = fixtures.create_employee(employer["id"])
    acct_y = fixtures.create_verified_account(emp_y["id"])
    fixtures.set_clock("2026-03-15T00:00:00Z")
    enr_x = validate_success(
        api.create_enrollment(
            factories.create_enrollment_payload(emp_x["id"], prod["id"], period["id"]),
            _ADMIN,
        ),
        201,
    )
    api.activate_enrollment(enr_x["id"], _ADMIN)
    fixtures.post_deduction(enr_x["id"], 0, "POSTED")
    payload = factories.create_claim_payload(
        enr_x["id"], acct_y["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    validate_error(
        api.create_claim(payload, _ADMIN),
        ApiErrorId.ERR_REFERENCE_MISMATCH,
    )


# ---------------------------------------------------------------------------
# Corner: validations / pagination_limit_out_of_bounds_rejected
# ---------------------------------------------------------------------------
def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned and
    defaults to 10 when omitted; its minimum accepted value is 1 and its maximum
    is 100. ... A request whose `limit` or `offset` falls outside these bounds is
    rejected with `ERR_VALIDATION_PAGINATION`."

    Design: Corner/validations/pagination_limit_out_of_bounds_rejected
    """
    fixtures.create_employer()
    validate_error(
        api.list_plan_products(_ADMIN, params={"limit": 500}),
        ApiErrorId.ERR_VALIDATION_PAGINATION,
    )


# ---------------------------------------------------------------------------
# Corner: endpoints / list_enrollments_paginated_envelope
# ---------------------------------------------------------------------------
def test_list_enrollments_returns_paginated_envelope(api):
    """PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope, where
    `total_count` is the count of all matching records before the page window is
    applied and `has_more` indicates whether records remain beyond the current
    page."

    Design: Corner/endpoints/list_enrollments_paginated_envelope
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment()
    rows, meta = validate_paginated(
        api.list_enrollments(_ADMIN, params={"employee_id": employee["id"]})
    )
    assert any(r["id"] == enr["id"] for r in rows)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# Corner: rbac / employee_cannot_approve_claim
# ---------------------------------------------------------------------------
def test_employee_cannot_approve_claim(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/employee_cannot_approve_claim
    """
    from test_helpers import make_employee_headers

    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_and_review_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    emp_headers = make_employee_headers(employee["id"])
    validate_error(
        api.approve_claim(claim["id"], emp_headers),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
    data = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert data["status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# Corner: rbac / missing_user_context_header_rejected
# ---------------------------------------------------------------------------
def test_missing_user_context_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    validate_error(
        api.create_employer({"legal_name": "AuthCo"}, headers={}),
        ApiErrorId.ERR_MISSING_USER_CONTEXT,
    )


# ---------------------------------------------------------------------------
# Corner: rbac / payroll_cannot_create_employer
# ---------------------------------------------------------------------------
def test_payroll_cannot_create_employer(api):
    """PRD §2.1: "No role can perform another role's exclusive operations." and
    §4: "POST `/benefits/employers` | Create an employer | BenefitsAdmin".

    Design: Corner/rbac/payroll_cannot_create_employer
    """
    validate_error(
        api.create_employer({"legal_name": "PrCo"}, _PAYROLL),
        ApiErrorId.ERR_FORBIDDEN_ROLE,
    )
