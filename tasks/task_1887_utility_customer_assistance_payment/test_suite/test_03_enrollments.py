"""Enrollments: computed discount, lapse/recertify cycle, one-ACTIVE capacity."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, assert_date_eq, assert_enrollment,
    create_account, submit_application, create_verified_application,
    get_enrollment_for_application, create_active_enrollment, set_clock, run_sweep,
    TEST_USERS, make_csr_headers,
    INCOME_TIER_2,
)

CSR = TEST_USERS["csr_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]


def test_enrollment_computed_discount_pct_tier2(api):
    """PRD §3.3: "The enrollment's `discount_pct` is the bill-discount percentage
    keyed to its `tier`: 50 percent for `TIER_1`, 30 percent for `TIER_2`, and 15
    percent for `TIER_3`."
    PRD §3.3: "The enrollment row keeps its lineage through `application_id`, the
    verified application that justified it, and `account_id` copied from that
    application."

    Design: Corner/entities/enrollment_computed_discount_pct_tier2
    """
    account = create_account(service_address="4 Computed Ct")
    app = create_verified_application(account["id"], **INCOME_TIER_2)
    enrollment = get_enrollment_for_application(app["id"])
    assert_enrollment(enrollment)
    assert enrollment["tier"] == "TIER_2"
    assert enrollment["discount_pct"] == 30
    assert enrollment["status"] == "PENDING"
    assert enrollment["application_id"] == app["id"]


def test_enrollment_lapse_then_recertify_cycle(api):
    """PRD §3.3: "When the daily sweep finds the clock date has reached an `ACTIVE`
    enrollment's `recert_due_on`, the enrollment lapses: status becomes `LAPSED`
    and `lapsed_on` records the clock date."
    PRD §3.3: "recertification returns the enrollment to `ACTIVE`, updates its
    `tier` and `discount_pct` from the new application, resets `recert_due_on` to
    the clock date plus 365 days, and clears `lapsed_on` to null."

    Design: Corner/state_machines/enrollment_lapse_then_recertify_cycle
    """
    account = create_account(service_address="12 Recert Rd")
    app1, enrollment = create_active_enrollment(account["id"])  # activated 2026-08-01
    assert_date_eq(enrollment["recert_due_on"], "2027-08-01", "recert_due_on")

    set_clock("2027-08-01T00:00:00Z")
    sweep = run_sweep()
    assert sweep["enrollments_lapsed"] == 1
    mid = validate_success(api.get_enrollment(enrollment["id"], SPECIALIST), 200)
    assert mid["status"] == "LAPSED"
    assert_date_eq(mid["lapsed_on"], "2027-08-01", "lapsed_on")

    app2 = create_verified_application(account["id"], **INCOME_TIER_2)
    resp = api.recertify_enrollment(
        enrollment["id"], {"new_application_id": app2["id"]}, SPECIALIST)
    renewed = validate_success(resp, 200)
    assert renewed["status"] == "ACTIVE"
    assert renewed["tier"] == "TIER_2", "tier adopted from the new application"
    assert renewed["discount_pct"] == 30
    # 2027-08-01 + 365 days = 2028-07-31 (2028 is a leap year: 2028-02-29
    # falls inside the window), per PRD's verbatim "plus 365 days".
    assert_date_eq(renewed["recert_due_on"], "2028-07-31", "recert_due_on")
    assert renewed["lapsed_on"] is None


def test_second_enrollment_activation_rejected(api):
    """PRD §3.3: "Activation requires that no other enrollment is `ACTIVE` on the
    same account — a conflict fails with `ERR_ACTIVE_ENROLLMENT_EXISTS`
    (HTTP 422) — and that the enrollment is still `PENDING`, with any other
    from-state rejected as `ERR_INVALID_STATE` (HTTP 409); the generic state check
    is evaluated before the one-active-account constraint."

    Design: Corner/validations/second_enrollment_activation_rejected
    """
    account = create_account(service_address="37 Enroll Excess")
    app1 = create_verified_application(
        account["id"], household_size=1, gross_annual_income_cents=500_000,
        current_month_income_cents=40_000)
    e1 = get_enrollment_for_application(app1["id"])
    app2 = create_verified_application(
        account["id"], household_size=1, gross_annual_income_cents=600_000,
        current_month_income_cents=50_000)
    e2 = get_enrollment_for_application(app2["id"])

    first = validate_success(api.activate_enrollment(e1["id"], CSR), 200)
    assert first["status"] == "ACTIVE"
    resp = api.activate_enrollment(e2["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_ENROLLMENT_EXISTS)
    stayed = validate_success(api.get_enrollment(e2["id"], SPECIALIST), 200)
    assert stayed["status"] == "PENDING"
