"""Queue B — §1.6 error corners on configuration: the typed 404 family, the two
registration guards on a restaurant unit, the chain-wide job-role code, and the two
statutory activation guards that are properties of the unit rather than of the policy."""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    ApiErrorId,
    assert_instant_equals,
    new_draft_policy,
    new_location,
    read_location,
    read_policy,
    set_logical_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import create_location_payload

CLOCK = "2026-08-10T12:00:00Z"

MISSING_EMPLOYEE = "11111111-1111-4111-8111-111111111111"
MISSING_POLICY = "22222222-2222-4222-8222-222222222222"
MISSING_PERIOD = "33333333-3333-4333-8333-333333333333"
MISSING_POOL = "44444444-4444-4444-8444-444444444444"
MISSING_PAY_LINE = "55555555-5555-4555-8555-555555555555"
MISSING_DISPUTE = "66666666-6666-4666-8666-666666666666"
MISSING_CORRECTION = "77777777-7777-4777-8777-777777777777"
MISSING_JOB_ROLE = "88888888-8888-4888-8888-888888888888"
MISSING_ASSIGNMENT = "99999999-9999-4999-8999-999999999999"
MISSING_CHARGE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MISSING_ALLOCATION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# ---------------------------------------------------------------------------
# errors / unknown_identifiers_return_typed_not_found_errors
# ---------------------------------------------------------------------------
def test_eleven_addressable_resources_answer_with_seven_codes_and_one_fallback(api):
    """Well-formed ids that name nothing are 404 errors, never empty 200 successes.

    PRD §1.4: "Every templated identifier in the path resolves to a stored row, checked
    left to right, all 404, on every endpoint that has a templated path segment. Each
    identifier has its own code: a `location_id` that names no stored Location raises
    `ERR_LOCATION_NOT_FOUND`; an `employee_id` or `raised_by_employee_id` that names no
    stored Employee raises `ERR_EMPLOYEE_NOT_FOUND`; a `policy_id` that names no stored
    TipPoolPolicy raises `ERR_POLICY_NOT_FOUND`; a `pay_period_id` that names no stored
    PayPeriod raises `ERR_PAY_PERIOD_NOT_FOUND`; a `shift_id` that names no stored Shift
    raises `ERR_SHIFT_NOT_FOUND`; a `pool_id` that names no stored ShiftTipPool raises
    `ERR_POOL_NOT_FOUND`; a `pay_line_id` that names no stored PayLine raises
    `ERR_PAY_LINE_NOT_FOUND`; a `dispute_id` that names no stored Dispute raises
    `ERR_DISPUTE_NOT_FOUND`; a `correction_id` or `supersedes_correction_id` that names
    no stored BackWageCorrection raises `ERR_CORRECTION_NOT_FOUND`; and a `job_role_id`,
    `role_assignment_id`, `service_charge_id` or `allocation_id` that names no stored
    JobRole, EmployeeRoleAssignment, ServiceChargeEvent or PoolAllocation respectively
    raises `ERR_RECORD_NOT_FOUND`."

    Design: Corner/errors/unknown_identifiers_return_typed_not_found_errors
    """
    set_logical_clock()

    typed = [
        (api.get_employee(MISSING_EMPLOYEE, ADMIN), ApiErrorId.ERR_EMPLOYEE_NOT_FOUND),
        (api.get_tip_pool_policy(MISSING_POLICY, ADMIN), ApiErrorId.ERR_POLICY_NOT_FOUND),
        (
            api.get_pay_period(MISSING_PERIOD, ADMIN),
            ApiErrorId.ERR_PAY_PERIOD_NOT_FOUND,
        ),
        (api.get_shift_tip_pool(MISSING_POOL, ADMIN), ApiErrorId.ERR_POOL_NOT_FOUND),
        (api.get_pay_line(MISSING_PAY_LINE, ADMIN), ApiErrorId.ERR_PAY_LINE_NOT_FOUND),
        (api.get_dispute(MISSING_DISPUTE, ADMIN), ApiErrorId.ERR_DISPUTE_NOT_FOUND),
        (
            api.get_back_wage_correction(MISSING_CORRECTION, ADMIN),
            ApiErrorId.ERR_CORRECTION_NOT_FOUND,
        ),
    ]
    for response, error_id in typed:
        validate_error(response, error_id.value)

    shared = [
        api.get_job_role(MISSING_JOB_ROLE, ADMIN),
        api.get_role_assignment(MISSING_ASSIGNMENT, ADMIN),
        api.get_service_charge(MISSING_CHARGE, ADMIN),
        api.get_pool_allocation(MISSING_ALLOCATION, ADMIN),
    ]
    for response in shared:
        validate_error(response, ApiErrorId.ERR_RECORD_NOT_FOUND.value)

    for response, _error_id in typed:
        assert response.status_code == 404, "an unknown id is never a 200 with null data"
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
            "the ids are well-formed, they simply name nothing"
        )


# ---------------------------------------------------------------------------
# errors / location_and_job_role_catalog_configuration_rejected
# ---------------------------------------------------------------------------
def test_both_limbs_of_each_registration_guard_and_the_unit_that_passes(api):
    """A cash wage may be neither too low nor too high, and the fee cap is exactly conditional.

    PRD §2.4: "A unit that sets `tip_credit_enabled` to true must satisfy the stricter
    form of the cash-wage rule: `cash_wage_cents` must be at least 213 and strictly below
    `applicable_min_wage_cents`, and a registration that breaks either bound is rejected
    with `ERR_CASH_WAGE_BELOW_FLOOR` (HTTP 422)."
    PRD §3.1: "`CAPPED_BPS` means the state permits a deduction but caps it, and in that
    case `cc_fee_cap_bps` is required, must be greater than 0, and must lie between 1 and
    1000 basis points inclusive. Supplying `cc_fee_cap_bps` under either of the other two
    policies is just as wrong as omitting it under `CAPPED_BPS`, and both mistakes surface
    as `ERR_CC_FEE_CAP_REQUIRED`."
    PRD §2.4: "From those two inputs the server derives `applicable_min_wage_cents` as the
    greater of the federal minimum wage of 725 cents and the unit's
    `state_min_wage_cents`."
    PRD §2.4: "Where the unit claims a tip credit, that claim is capped per hour: the
    server derives `max_tip_credit_per_hour_cents` as `applicable_min_wage_cents` minus
    `cash_wage_cents`."
    PRD §3.1: "Registration derives three further figures on the unit and nothing else:
    `applicable_min_wage_cents` and `max_tip_credit_per_hour_cents` per §2.4, and
    `pending_pool_cents`, which is set to 0 and whose `version` therefore begins at 1."

    Design: Corner/errors/location_and_job_role_catalog_configuration_rejected
    """
    set_logical_clock()

    validate_error(
        api.create_location(
            create_location_payload(name="Below Floor Unit", cash_wage_cents=200), ADMIN
        ),
        ApiErrorId.ERR_CASH_WAGE_BELOW_FLOOR.value,
    )
    validate_error(
        api.create_location(
            create_location_payload(name="No Headroom Unit", cash_wage_cents=725), ADMIN
        ),
        ApiErrorId.ERR_CASH_WAGE_BELOW_FLOOR.value,
    )
    validate_error(
        api.create_location(
            create_location_payload(
                name="Uncapped Unit",
                state_code="NY",
                state_min_wage_cents=1500,
                cash_wage_cents=1000,
                cc_fee_policy="CAPPED_BPS",
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_CC_FEE_CAP_REQUIRED.value,
    )
    validate_error(
        api.create_location(
            create_location_payload(
                name="Overspecified Unit",
                state_code="NY",
                state_min_wage_cents=1500,
                cash_wage_cents=1000,
                cc_fee_policy="ACTUAL_ONLY",
                cc_fee_cap_bps=200,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_CC_FEE_CAP_REQUIRED.value,
    )

    albany = new_location(
        name="Albany Unit",
        state_code="NY",
        state_min_wage_cents=1500,
        cash_wage_cents=1000,
        cc_fee_policy="CAPPED_BPS",
        cc_fee_cap_bps=200,
    )
    assert albany["applicable_min_wage_cents"] == 1500, "the greater of 725 and 1500"
    assert albany["max_tip_credit_per_hour_cents"] == 500, "1500 less the 1000 cash wage"
    assert albany["cc_fee_cap_bps"] == 200
    assert albany["pending_pool_cents"] == 0
    assert albany["version"] == 1

    _rows, meta = validate_paginated(api.list_locations(ADMIN))
    assert meta["total_count"] == 1, "the four rejections persisted nothing"


def test_the_job_role_code_is_unique_across_the_whole_chain(api):
    """The same code twice is a 409 even under a different title.

    PRD §3.1: "`code` must be unique across every job role in the chain; a collision is
    refused with `ERR_DUPLICATE_JOB_ROLE_CODE`."
    PRD §3.1: "Job roles are defined chain-wide rather than per unit, because a `SERVER`
    at one unit is a `SERVER` at all of them."

    Design: Corner/errors/location_and_job_role_catalog_configuration_rejected
    """
    set_logical_clock()
    first = validate_success(
        api.create_job_role(
            {
                "code": "SERVER",
                "title": "Server",
                "tip_status": "TIPPED",
                "is_management": False,
                "pool_contribution_pct_bps": 1500,
                "pool_share_points": 10,
                "side_work_eligible": True,
            },
            ADMIN,
        ),
        expected_status=201,
    )
    assert first["code"] == "SERVER"

    validate_error(
        api.create_job_role(
            {
                "code": "SERVER",
                "title": "Banquet Server",
                "tip_status": "TIPPED",
                "is_management": False,
                "pool_contribution_pct_bps": 1200,
                "pool_share_points": 9,
                "side_work_eligible": True,
            },
            ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_JOB_ROLE_CODE.value,
    )

    _rows, meta = validate_paginated(api.list_job_roles(ADMIN))
    assert meta["total_count"] == 1, "uniqueness is global rather than per unit"


# ---------------------------------------------------------------------------
# errors / policy_activation_state_law_guards_rejected
# ---------------------------------------------------------------------------
def _two_unit_policy_world() -> dict:
    """A Texas unit that claims a tip credit and a California unit that does not, with
    four DRAFT policies: the back-of-house shape and the fee-passing shape at each."""
    set_logical_clock()
    texas = new_location()
    california = new_location(
        name="Oakland Unit",
        state_code="CA",
        state_min_wage_cents=1650,
        cash_wage_cents=1650,
        tip_credit_enabled=False,
        cc_fee_policy="PROHIBITED",
        service_charge_treatment="TIPS",
    )
    return {
        "texas": texas,
        "california": california,
        "boh_tx": new_draft_policy(
            texas["id"],
            pool_type="ALL_NON_MANAGEMENT",
            share_basis="POINTS_ONLY",
            cc_fee_pass_through=False,
        ),
        "fee_ca": new_draft_policy(
            california["id"], share_basis="POINTS_ONLY", cc_fee_pass_through=True
        ),
        "boh_ca": new_draft_policy(
            california["id"],
            pool_type="ALL_NON_MANAGEMENT",
            share_basis="POINTS_ONLY",
            cc_fee_pass_through=False,
        ),
        "fee_tx": new_draft_policy(texas["id"], cc_fee_pass_through=True),
    }


def test_the_statutory_activation_guards_read_the_unit_not_the_policy(api):
    """A back-of-house pool and a fee pass-through are each refused by the wrong unit.

    PRD §3.3: "Then, if `pool_type` is `ALL_NON_MANAGEMENT`, the unit's
    `tip_credit_enabled` must be false, because back-of-house employees may share in a
    pool only where no tip credit is taken; otherwise
    `ERR_POOL_TYPE_REQUIRES_NO_TIP_CREDIT`."
    PRD §3.3: "Then, if `cc_fee_pass_through` is true, the unit's `cc_fee_policy` must not
    be `PROHIBITED`, because that state forbids deducting processing fees from tips at
    all; otherwise `ERR_CC_FEE_DEDUCTION_PROHIBITED`."
    PRD §3.3: "A drafted policy has `status` `DRAFT` and `activated_at` null."
    PRD §3.3: "Fifth, the unit's `version` is incremented by exactly 1, so any second
    activation replayed with the same `expected_location_version` fails."

    Design: Corner/errors/policy_activation_state_law_guards_rejected
    """
    world = _two_unit_policy_world()

    validate_error(
        api.activate_tip_pool_policy(
            world["boh_tx"]["id"],
            {"expected_location_version": world["texas"]["version"]},
            COMPLIANCE,
        ),
        ApiErrorId.ERR_POOL_TYPE_REQUIRES_NO_TIP_CREDIT.value,
    )
    validate_error(
        api.activate_tip_pool_policy(
            world["fee_ca"]["id"],
            {"expected_location_version": world["california"]["version"]},
            COMPLIANCE,
        ),
        ApiErrorId.ERR_CC_FEE_DEDUCTION_PROHIBITED.value,
    )

    for key in ("boh_tx", "fee_ca"):
        refused = read_policy(world[key]["id"])
        assert refused["status"] == "DRAFT"
        assert refused["activated_at"] is None

    assert read_location(world["texas"]["id"])["version"] == 1, (
        "a rejected activation performs no write, so the presented version stays valid"
    )
    assert read_location(world["california"]["id"])["version"] == 1


def test_each_refused_shape_is_lawful_at_the_other_unit(api):
    """The identical policy shapes activate once they are pointed at the right unit.

    PRD §3.3: "Activation is reserved to a `ComplianceOfficer` and is the sole operation
    in the whole system that advances a unit's `version`; that is precisely what makes the
    optimistic-concurrency check of §2.7 observable."
    PRD §3.3: "First, the newly active policy's `activated_at` is stamped with the current
    logical instant."
    PRD §3.3: "Then, if `pool_type` is `ALL_NON_MANAGEMENT`, the unit's
    `tip_credit_enabled` must be false, because back-of-house employees may share in a
    pool only where no tip credit is taken; otherwise
    `ERR_POOL_TYPE_REQUIRES_NO_TIP_CREDIT`."
    PRD §3.3: "Then, if `cc_fee_pass_through` is true, the unit's `cc_fee_policy` must not
    be `PROHIBITED`, because that state forbids deducting processing fees from tips at
    all; otherwise `ERR_CC_FEE_DEDUCTION_PROHIBITED`."

    Design: Corner/errors/policy_activation_state_law_guards_rejected
    """
    world = _two_unit_policy_world()

    boh_ca = validate_success(
        api.activate_tip_pool_policy(
            world["boh_ca"]["id"],
            {"expected_location_version": world["california"]["version"]},
            COMPLIANCE,
        )
    )
    assert boh_ca["status"] == "ACTIVE", (
        "the same ALL_NON_MANAGEMENT shape that failed at the Texas unit"
    )
    assert_instant_equals(boh_ca["activated_at"], CLOCK, "activated_at")

    fee_tx = validate_success(
        api.activate_tip_pool_policy(
            world["fee_tx"]["id"],
            {"expected_location_version": world["texas"]["version"]},
            COMPLIANCE,
        )
    )
    assert fee_tx["status"] == "ACTIVE", (
        "the same cc_fee_pass_through true that failed at the California unit"
    )

    assert read_location(world["california"]["id"])["version"] == 2
    assert read_location(world["texas"]["id"])["version"] == 2, (
        "each successful activation bumps only its own unit"
    )
    assert read_policy(world["boh_tx"]["id"])["status"] == "DRAFT", (
        "the refused Texas back-of-house draft was never revived"
    )
