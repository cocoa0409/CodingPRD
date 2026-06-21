"""Resource creation, retrieval, listing, defaults, and shape validation across the
employee/catalog/enrollment surface.

Covers Corner/entities, Corner/endpoints (reverse-reachability), and
Corner/cross_cutting_complexity_layers (version increment, EOI-denied no feed).
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated, ApiErrorId,
    create_employee, create_offering, create_tier, setup_eligible_employee,
    create_draft_enrollment, employee_version,
    setup_pending_eoi_enrollment,
    api_client as api,
    TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_create_employee_returns_201_with_system_fields():
    """PRD §3.1: "At creation the system sets eligibility_status to INELIGIBLE for a
    SEASONAL hire and to WAITING for everyone else, and it initializes pay_periods_processed
    to zero."
    PRD §2.4: "an integer version that begins at its initial value and increments by exactly
    one each time the resource is mutated."

    Design: Corner/entities/create_employee_returns_201_with_system_fields
    """
    data = validate_success(api.create_employee({
        "full_name": "Al Bone", "hire_date": "2026-01-01", "employment_type": "FULL_TIME",
        "payroll_schedule": "SEMI_MONTHLY", "monthly_household_income_cents": 500000,
    }, _ADMIN), expected_status=201)
    assert data["version"] == 1, data
    assert data["eligibility_status"] == "WAITING", data
    assert data["pay_periods_processed"] == 0, data


def test_create_seasonal_employee_is_ineligible():
    """PRD §2.7: "A newly created employee begins in WAITING unless their employment_type
    is SEASONAL, in which case they are INELIGIBLE from creation and never become eligible
    to enroll."

    Design: Corner/entities/create_seasonal_employee_is_ineligible
    """
    data = validate_success(api.create_employee({
        "full_name": "Be Cain", "hire_date": "2026-01-01", "employment_type": "SEASONAL",
        "payroll_schedule": "BIWEEKLY", "monthly_household_income_cents": 300000,
    }, _ADMIN), expected_status=201)
    assert data["eligibility_status"] == "INELIGIBLE", data


def test_get_employee_returns_stored_entity():
    """PRD §2.2: "The data field contains the resource object ... operations that create or
    modify a resource will return the created or updated resource object in the data field."

    Design: Corner/entities/get_employee_returns_stored_entity
    """
    emp = create_employee(full_name="Cy Dunn")
    data = validate_success(api.get_employee(emp["id"], _ADMIN))
    assert data["full_name"] == "Cy Dunn", data


def test_list_employees_paginated_envelope():
    """PRD §2.3: "The meta object of a list response carries the four pagination fields
    limit, offset, total_count, and has_more, where total_count is the number of items
    matching the query before pagination and has_more indicates whether items remain beyond
    the current page."

    Design: Corner/entities/list_employees_paginated_envelope
    """
    create_employee(full_name="Em F", employment_type="FULL_TIME", payroll_schedule="SEMI_MONTHLY")
    create_employee(full_name="En G", employment_type="PART_TIME", payroll_schedule="BIWEEKLY")
    data, meta = validate_paginated(api.list_employees(_ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_get_employee_not_found():
    """PRD §2.5: "The first identifier — in the path or, failing that, in the body — that
    does not correspond to an existing resource causes the request to be rejected with
    ERR_NOT_FOUND before any business rule is evaluated."

    Design: Corner/entities/get_employee_not_found
    """
    resp = api.get_employee("00000000-0000-4000-8000-000000000000", _ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_employee_missing_required_field():
    """PRD §2.10: "the request body's shape is validated — required fields present, enum
    values legal, and integers non-negative where constrained — failing with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_employee_missing_required_field
    """
    resp = api.create_employee({
        "full_name": "No Sched", "hire_date": "2026-01-01", "employment_type": "FULL_TIME",
        "monthly_household_income_cents": 500000,
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_employee_invalid_enum():
    """PRD §2.10: "the request body's shape is validated — required fields present, enum
    values legal, and integers non-negative where constrained — failing with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/create_employee_invalid_enum
    """
    resp = api.create_employee({
        "full_name": "Bad Enum", "hire_date": "2026-01-01", "employment_type": "CONTRACTOR",
        "payroll_schedule": "SEMI_MONTHLY", "monthly_household_income_cents": 500000,
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_enrollment_status_draft_and_benefit_type_copied_from_offering():
    """PRD §3.4: "The new enrollment is born in DRAFT, its benefit_type copied from the
    chosen tier's offering, and is associated with its employee through employee_id."

    Design: Corner/entities/enrollment_id_is_system_minted_input_ignored
    """
    emp = create_employee()
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    data = validate_success(api.create_enrollment(emp["id"], {
        "plan_tier_id": tier["id"], "coverage_start_date": "2026-02-01",
    }, _ADMIN), expected_status=201)
    assert data["status"] == "DRAFT", data
    assert data["benefit_type"] == "MEDICAL", data


def test_create_enrollment_against_archived_offering_rejected():
    """PRD §3.2: "Once an offering is ARCHIVED, any attempt to create an enrollment against
    one of its tiers is rejected with ERR_PLAN_ARCHIVED."

    Design: Corner/entities/create_enrollment_against_archived_offering
    """
    emp = create_employee()
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    get_success_data(api.archive_plan_offering(off["id"], _ADMIN))
    resp = api.create_enrollment(emp["id"], {
        "plan_tier_id": tier["id"], "coverage_start_date": "2026-02-01",
    }, _ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_ARCHIVED.value)


def test_reverse_reachability_list_dependents_by_employee():
    """PRD §4 lists "GET /dependents — List dependents, filterable by employee".
    PRD §2.3: "total_count is the number of items matching the query before pagination".

    Design: Corner/endpoints/reverse_reachability_list_dependents_by_employee
    """
    emp = create_employee(full_name="Gh Two")
    get_success_data(api.create_dependent(emp["id"], {
        "relationship": "SPOUSE", "full_name": "Sp Two", "date_of_birth": "1991-01-01"}, _ADMIN))
    get_success_data(api.create_dependent(emp["id"], {
        "relationship": "CHILD", "full_name": "Ch Two", "date_of_birth": "2015-01-01"}, _ADMIN))
    data, meta = validate_paginated(api.list_dependents(_ADMIN, params={"employee_id": emp["id"]}))
    assert meta["total_count"] == 2, meta
    assert all(d["employee_id"] == emp["id"] for d in data), data


def test_employee_version_increments_on_activate():
    """PRD §2.4: "an integer version that begins at its initial value and increments by
    exactly one each time the resource is mutated."
    PRD §3.4: "the enrollment's version is incremented, and the employee's version is
    incremented as well."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    emp = setup_eligible_employee()
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev1 = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(enr["id"], {"expected_employee_version": ev1}, _ADMIN))
    v_after = employee_version(emp["id"])
    assert v_after == ev1 + 1, (ev1, v_after)


def test_eoi_denied_emits_no_carrier_feed_record():
    """PRD §3.4: "as a compensating action, the linked enrollment reverts from PENDING_EOI
    back to DRAFT with its version incremented — and, deliberately, no carrier feed record
    is emitted on denial."

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_eoi_denied_no_feed_record
    """
    ctx = setup_pending_eoi_enrollment(coverage_amount_cents=30000000,
                                       guaranteed_issue_amount_cents=15000000,
                                       rate_per_1000_monthly_cents=25)
    enr_id = ctx["enrollment"]["id"]
    get_success_data(api.decide_eoi_request(ctx["eoi_request"]["id"], {"decision": "DENIED"}, _COMPLIANCE))
    enr = get_success_data(api.get_enrollment(enr_id, _ADMIN))
    assert enr["status"] == "DRAFT", enr
    records = get_success_data(api.list_carrier_feed_records(_ADMIN, params={"enrollment_id": enr_id}))
    assert len(records) == 0, records
