"""Entity creation, input validation, RBAC, pagination, listing, and terminal-state
lockdown for the Medicare Advantage Enrollment API.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, set_clock,
    create_beneficiary, create_period, assert_beneficiary,
    create_beneficiary_payload, create_plan_payload, create_medigap_policy_payload,
    create_penalty_assessment_payload, NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["enrollment_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_create_beneficiary_returns_system_fields(api):
    """PRD §3.1: "At creation a beneficiary's status is ACTIVE, its part_a_status and
    part_b_status are both NONE, its part_b_effective_date is null, and its
    enrollment_lock is false."
    PRD §2.5: "The version field is an integer that begins at creation and increments
    by one on every mutation of that resource"

    Design: Corner/entities/create_beneficiary_returns_201_with_system_fields
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.create_beneficiary(
        create_beneficiary_payload(full_name="New B", date_of_birth="1959-08-15T00:00:00.000Z"),
        ADMIN)
    ben = validate_success(res, 201)
    assert_beneficiary(ben)
    assert ben["status"] == "ACTIVE"
    assert ben["part_a_status"] == "NONE"
    assert ben["part_b_status"] == "NONE"
    assert ben["enrollment_lock"] is False
    assert ben["version"] == 1


def test_create_beneficiary_dob_on_first_of_month_rejected(api):
    """PRD §3.1: "its day-of-month must not be the 1st. A beneficiary born on the first
    of any month is rejected with ERR_INVALID_REQUEST (HTTP 422)"

    Design: Corner/entities/create_beneficiary_dob_on_first_of_month_returns_invalid_request
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.create_beneficiary(
        create_beneficiary_payload(full_name="Bad DOB", date_of_birth="1959-08-01T00:00:00.000Z"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_beneficiary_missing_full_name_rejected(api):
    """PRD §3.11: "the request body itself is validated - required fields present and
    well-typed, enums in range, the date_of_birth day-of-month not the 1st, cents
    fields integer and within bounds - failing with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/create_beneficiary_missing_full_name_returns_invalid_request
    """
    set_clock("2024-06-01T00:00:00.000Z")
    payload = create_beneficiary_payload()
    del payload["full_name"]
    res = api.create_beneficiary(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_beneficiary_not_found(api):
    """PRD §2.8: "The system validates path identifiers strictly left-to-right and
    rejects the request with ERR_NOT_FOUND (HTTP 404) at the first identifier in the
    path that does not resolve to an existing resource."

    Design: Corner/entities/get_beneficiary_nonexistent_returns_not_found
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.get_beneficiary(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_plan_invalid_star_rating_rejected(api):
    """PRD §3.3: "The star_rating is the CMS rating and must be one of the values 1.0,
    1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, or 5.0"
    PRD §3.11: "the request body itself is validated - required fields present and
    well-typed, enums in range ... - failing with ERR_INVALID_REQUEST (HTTP 422)."

    Design: Corner/entities/plan_invalid_star_rating_enum_returns_invalid_request
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.create_plan(
        create_plan_payload(name="Bad Star", part_type="PART_C", monthly_premium_cents=0,
                            star_rating=4.2, includes_drug_coverage=False), ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_part_d_defaults_zero_accumulators(api):
    """PRD §3.7: "The enrollment is created PENDING, with requested_at from the clock
    and its accumulators total_drug_cost_cents, member_oop_cents, and lep_premium_cents
    all initialized to 0."

    Design: Corner/entities/part_d_enrollment_defaults_zero_accumulators_on_create
    """
    from test_helpers import setup_pending_part_d
    set_clock("2024-11-01T00:00:00.000Z")
    _ben, _iep, _pdp, pde = setup_pending_part_d()
    assert pde["total_drug_cost_cents"] == 0
    assert pde["member_oop_cents"] == 0
    assert pde["lep_premium_cents"] == 0
    assert pde["status"] == "PENDING"


def test_create_part_c_with_nonexistent_plan_not_found(api):
    """PRD §2.8: "when a create request names a foreign resource by beneficiary_id,
    plan_id, enrollment_period_id, or part_d_enrollment_id, a reference to a
    non-existent resource is rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/create_partc_with_nonexistent_plan_returns_not_found
    """
    from test_helpers import create_part_c_enrollment_payload
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="FKB")
    iep = create_period(ben["id"], "IEP")
    res = api.create_part_c_enrollment(
        create_part_c_enrollment_payload(ben["id"], NON_EXISTENT_UUID, iep["id"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_lapse_medigap_after_death_void_rejected(api):
    """PRD §3.9: "An EnrollmentAdmin may lapse an ISSUED policy, requiring it to be
    ISSUED and the beneficiary not DECEASED, moving status to LAPSED and incrementing
    its version."
    PRD §3.2: "Every MedigapPolicy of this beneficiary currently in ISSUED transitions
    to VOIDED, each incrementing its own version."

    Design: Corner/state_machines/lapse_medigap_from_deceased_void_returns_invalid_state
    """
    set_clock("2026-01-05T00:00:00.000Z")
    ben = create_beneficiary(full_name="DeadMG")
    gi = create_period(ben["id"], "GI_MEDIGAP", source_event_date="2026-01-01T00:00:00.000Z")
    mp = validate_success(api.create_medigap_policy(
        create_medigap_policy_payload(ben["id"], gi["id"],
                                      "2026-01-05T00:00:00.000Z", "2027-01-05T00:00:00.000Z"),
        ADMIN), 201)
    validate_success(api.record_death(ben["id"], ADMIN), 200)
    assert validate_success(api.get_medigap_policy(mp["id"], ADMIN), 200)["status"] == "VOIDED"
    res = api.lapse_medigap_policy(mp["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ─── Pagination & listing ─────────────────────────────────────────────────────

def test_pagination_limit_over_max_rejected(api):
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected with
    ERR_VALIDATION_PAGINATION (HTTP 422)."

    Design: Corner/endpoints/pagination_limit_over_max_returns_validation_pagination
    """
    set_clock("2024-06-01T00:00:00.000Z")
    create_beneficiary(full_name="PgB")
    res = api.list_beneficiaries(ADMIN, params={"limit": 101})
    validate_error(res, ApiErrorId.ERR_VALIDATION_PAGINATION.value)


def test_list_beneficiaries_pagination_envelope(api):
    """PRD §2.3: "List responses carry limit, offset, total_count, and has_more inside
    the meta object of the envelope."

    Design: Corner/endpoints/list_beneficiaries_returns_pagination_envelope
    """
    set_clock("2024-06-01T00:00:00.000Z")
    create_beneficiary(full_name="L1")
    create_beneficiary(full_name="L2")
    data, meta = validate_paginated(api.list_beneficiaries(ADMIN, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


# ─── RBAC ─────────────────────────────────────────────────────────────────────

def test_compliance_officer_cannot_create_beneficiary(api):
    """PRD §2.1: "An EnrollmentAdmin is operations staff: they create beneficiaries,
    plans, and enrollment periods"
    PRD §2.1: "When a request's X-User-Role is not permitted to perform the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_create_beneficiary
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.create_beneficiary(
        create_beneficiary_payload(full_name="RbacB"), COMPLIANCE)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_enrollment_admin_cannot_assess_penalty(api):
    """PRD §2.1: "A ComplianceOfficer is audit staff: they place and clear fraud holds,
    and they assess and waive late-enrollment penalties."
    PRD §2.1: "When a request's X-User-Role is not permitted to perform the requested
    operation, the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/enrollment_admin_cannot_assess_penalty
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="RbacP")
    res = api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_D", 7), ADMIN)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header is rejected with ERR_UNAUTHENTICATED
    (HTTP 401). This applies to every endpoint without exception"

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    set_clock("2024-06-01T00:00:00.000Z")
    res = api.list_beneficiaries({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
