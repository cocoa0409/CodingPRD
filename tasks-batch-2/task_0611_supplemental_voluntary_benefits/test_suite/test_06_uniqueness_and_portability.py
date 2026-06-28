"""Uniqueness collisions, portability conversion (premium, OCC, already-ported),
and version semantics.

Difficulty queue A: resource_temporal_overlap.
Corner queue B: calculations (portability premium), errors (already-ported,
duplicate-schedule-event, payroll-non-active), cross_cutting (OCC, version).
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    fixtures,
    ApiErrorId,
    factories,
    make_employee_headers,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / duplicate_nonterminal_enrollment_same_product
# ---------------------------------------------------------------------------
def test_duplicate_nonterminal_enrollment_same_product_rejected(api):
    """PRD §3.5: "An employee may hold at most one non-terminal enrollment per
    product, where non-terminal means `lifecycle_status` in `PENDING` or
    `ACTIVE`; a second such enrollment in the same product is rejected with
    `ERR_DUPLICATE_ENROLLMENT`."

    Design: Difficulty/resource_temporal_overlap/duplicate_nonterminal_enrollment_same_product_collides
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment()
    payload = factories.create_enrollment_payload(
        employee["id"], prod["id"], period["id"]
    )
    validate_error(
        api.create_enrollment(payload, _ADMIN),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT,
    )


def test_first_pending_enrollment_remains_after_duplicate_rejected(api):
    """PRD §3.5: "a second such enrollment in the same product is rejected with
    `ERR_DUPLICATE_ENROLLMENT`."

    Design: Difficulty/resource_temporal_overlap/duplicate_nonterminal_enrollment_same_product_collides
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment()
    payload = factories.create_enrollment_payload(
        employee["id"], prod["id"], period["id"]
    )
    api.create_enrollment(payload, _ADMIN)
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["lifecycle_status"] == "PENDING"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / duplicate_pay_period_index_collides
# ---------------------------------------------------------------------------
def test_duplicate_pay_period_index_rejected(api):
    """PRD §3.7: "The `pay_period_index` is a monotonic sequence number within the
    benefit year and must be unique per enrollment; a second posting reusing an
    index already recorded for the enrollment is rejected with
    `ERR_DUPLICATE_PAY_PERIOD`"

    Design: Difficulty/resource_temporal_overlap/duplicate_pay_period_index_collides
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    payload = factories.create_payroll_deduction_payload(0, "POSTED")
    validate_error(
        api.post_payroll_deduction(enr["id"], payload, _PAYROLL),
        ApiErrorId.ERR_DUPLICATE_PAY_PERIOD,
    )


def test_distinct_pay_period_index_accepted(api):
    """PRD §3.7: "The `pay_period_index` is a monotonic sequence number within the
    benefit year and must be unique per enrollment"

    Design: Difficulty/resource_temporal_overlap/duplicate_pay_period_index_collides
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment()
    fixtures.post_deduction(enr["id"], 0, "POSTED")
    payload = factories.create_payroll_deduction_payload(1, "POSTED")
    data = validate_success(api.post_payroll_deduction(enr["id"], payload, _PAYROLL), 201)
    assert data["pay_period_index"] == 1


# ---------------------------------------------------------------------------
# Corner: calculations / portability_premium_uses_product_base_with_loadup
# ---------------------------------------------------------------------------
def test_portability_premium_uses_product_base_with_loadup(api):
    """PRD §3.10: "The ported weekly premium is computed from the product's base
    `weekly_premium_cents` — deliberately the product base, not the enrollment's
    surcharged premium — scaled by one plus the product's `portability_loadup_bps`
    divided by 10000, with the result rounded half-up to whole cents."

    Design: Corner/calculations/portability_premium_uses_product_base_with_loadup
    """
    emp, prod, period, employee, enr, version = (
        fixtures.setup_terminated_enrollment_for_port(
            product_overrides={"weekly_premium_cents": 1200, "portability_loadup_bps": 1000}
        )
    )
    emp_headers = make_employee_headers(employee["id"])
    payload = factories.create_portability_conversion_payload(version)
    pc = validate_success(
        api.create_portability_conversion(enr["id"], payload, emp_headers), 201
    )
    # round_half_up(1200 * (1 + 1000/10000)) = round_half_up(1320) = 1320
    assert pc["direct_bill_weekly_cents"] == 1320
    assert pc["status"] == "CONVERTED"
    enr_data = validate_success(api.get_enrollment(enr["id"], emp_headers))
    assert enr_data["lifecycle_status"] == "PORTED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / occ_stale_enrollment_version_on_port
# ---------------------------------------------------------------------------
def test_port_with_stale_version_rejected(api):
    """PRD §2.9: "The server compares it to the enrollment's current `version`; if
    they do not match ... the create is rejected with
    `ERR_STALE_ENROLLMENT_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_enrollment_version_on_port
    """
    emp, prod, period, employee, enr, version = (
        fixtures.setup_terminated_enrollment_for_port()
    )
    emp_headers = make_employee_headers(employee["id"])
    payload = factories.create_portability_conversion_payload(version - 1)
    validate_error(
        api.create_portability_conversion(enr["id"], payload, emp_headers),
        ApiErrorId.ERR_STALE_ENROLLMENT_VERSION,
    )
    data = validate_success(api.get_enrollment(enr["id"], emp_headers))
    assert data["lifecycle_status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Corner: errors / already_ported_on_second_conversion
# ---------------------------------------------------------------------------
def test_second_port_on_converted_enrollment_rejected(api):
    """PRD §3.10: "The enrollment must be `TERMINATED`, and there must be no
    existing `CONVERTED` portability conversion for it; an attempt to port a
    policy that is not terminated, or that already has a converted conversion, is
    rejected with `ERR_ALREADY_PORTED`."

    Design: Corner/errors/already_ported_on_second_conversion
    """
    emp, prod, period, employee, enr, version = (
        fixtures.setup_terminated_enrollment_for_port()
    )
    emp_headers = make_employee_headers(employee["id"])
    first = factories.create_portability_conversion_payload(version)
    validate_success(
        api.create_portability_conversion(enr["id"], first, emp_headers), 201
    )
    refreshed = validate_success(api.get_enrollment(enr["id"], emp_headers))
    second = factories.create_portability_conversion_payload(refreshed["version"])
    validate_error(
        api.create_portability_conversion(enr["id"], second, emp_headers),
        ApiErrorId.ERR_ALREADY_PORTED,
    )


# ---------------------------------------------------------------------------
# Corner: errors / duplicate_schedule_event_on_same_product
# ---------------------------------------------------------------------------
def test_duplicate_schedule_event_rejected(api):
    """PRD §3.2: "A schedule line names an `event_code` ... that must be unique
    within its product; a second line attempting to reuse an `event_code` already
    present on the product is rejected with `ERR_DUPLICATE_SCHEDULE_EVENT`."

    Design: Corner/errors/duplicate_schedule_event_on_same_product
    """
    employer = fixtures.create_employer()
    product = fixtures.create_product(employer["id"])
    fixtures.add_schedule_item(product["id"], event_code="FRACTURE", flat_benefit_cents=200000)
    dup = factories.create_schedule_item_payload(
        product["id"], event_code="FRACTURE", flat_benefit_cents=250000
    )
    validate_error(
        api.create_schedule_item(dup, _ADMIN),
        ApiErrorId.ERR_DUPLICATE_SCHEDULE_EVENT,
    )


# ---------------------------------------------------------------------------
# Corner: errors / payroll_on_non_active_enrollment_rejected
# ---------------------------------------------------------------------------
def test_payroll_on_pending_enrollment_rejected(api):
    """PRD §3.7: "A posting is permitted only while the enrollment's
    `lifecycle_status` is `ACTIVE`; posting against a non-active enrollment is
    rejected with `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/errors/payroll_on_non_active_enrollment_rejected
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment()
    payload = factories.create_payroll_deduction_payload(0, "POSTED")
    validate_error(
        api.post_payroll_deduction(enr["id"], payload, _PAYROLL),
        ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE,
    )


# ---------------------------------------------------------------------------
# Corner: cross_cutting / version_increments_on_each_mutation
# ---------------------------------------------------------------------------
def test_enrollment_version_starts_at_one_and_increments_on_activate(api):
    """PRD §2.4: "an integer `version` that begins at its initial value on creation
    and increments by one on every mutation of the resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
    """
    emp, prod, period, employee, enr, items = fixtures.create_pending_enrollment()
    assert enr["version"] == 1
    activated = validate_success(api.activate_enrollment(enr["id"], _ADMIN))
    assert activated["version"] == 2


# ---------------------------------------------------------------------------
# Corner: cross_cutting / derived_total_deduction_reconciled_on_second_activation
# ---------------------------------------------------------------------------
def test_total_deduction_reconciles_across_two_active_enrollments(api):
    """PRD §3.4: "the value is the sum of `weekly_deduction_cents` over every
    enrollment of this employee whose `lifecycle_status` is `ACTIVE`; enrollments
    in any other lifecycle state contribute nothing."

    Design: Corner/cross_cutting_complexity_layers/derived_total_deduction_reconciled_on_second_activation
    """
    employer, prod1, period, items = fixtures.setup_open_product_and_period(
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0,
                           "product_name": "DrvPlan1"},
        schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}],
    )
    prod2 = fixtures.create_product(
        employer["id"], policy_type="HOSPITAL_INDEMNITY", product_name="DrvPlan2",
        weekly_premium_cents=1200, eoi_surcharge_bps=0,
    )
    fixtures.add_schedule_item(prod2["id"], event_code="HOSP_ADMIT", flat_benefit_cents=100000)
    fixtures.open_product(prod2["id"])
    employee = fixtures.create_employee(employer["id"])
    fixtures.set_clock("2026-03-15T00:00:00Z")
    enr1 = validate_success(
        api.create_enrollment(
            factories.create_enrollment_payload(employee["id"], prod1["id"], period["id"]),
            _ADMIN,
        ),
        201,
    )
    enr2 = validate_success(
        api.create_enrollment(
            factories.create_enrollment_payload(employee["id"], prod2["id"], period["id"]),
            _ADMIN,
        ),
        201,
    )
    api.activate_enrollment(enr1["id"], _ADMIN)
    api.activate_enrollment(enr2["id"], _ADMIN)
    data = validate_success(api.get_employee(employee["id"], _ADMIN))
    assert data["total_weekly_deduction_cents"] == 2400
