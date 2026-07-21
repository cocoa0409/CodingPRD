"""Back-reporting: tiered fee (nested max/min), included-allowance zeroing, the
month-limit and month-validity guards, rejection voiding the fee invoice, and the
enrollment-active gate on approval.

Covers the tiered back-report fee, month-limit and month-validity guards, the
rejection-voids-invoice rule, and the enrollment-active approval gate.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_tenant_headers, make_landlord_headers,
    create_lease_payload, create_back_report_payload,
    reset_clock_default, create_tenant, create_landlord, create_plan,
    activate_enrollment, create_enrollment, create_verified_lease, record_payment,
    setup_active_tenant, setup_pending_backreport, back_report_invoice_for, pay_invoice,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _record_three_months(api, landlord_id, lease_id):
    for m in ("2026-03", "2026-04", "2026-05"):
        record_payment(api, landlord_id, lease_id, period_month=m,
                       due_date=f"{m}-05T00:00:00Z", paid_date=f"{m}-05T00:00:00Z")


# --------------------------------------------------------------------------
# Difficulty: combinatorial_formula / back_report_fee nested min/max (mode a)
# --------------------------------------------------------------------------
def test_back_report_billable_months_mode_a(api):
    """PRD §3.6: "the billable count is the requested-month count minus the
    included allowance, or zero if the allowance covers them all."

    Design: Difficulty/combinatorial_formula/back_report_fee_tiered_min_max_mode_a
    """
    ctx = setup_active_tenant(api, plan_overrides={"back_reporting_included_months": 1})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"], property_address="9 Oak Ave")
    _record_three_months(api, ctx["landlord"]["id"], lease["id"])
    th = make_tenant_headers(ctx["tenant"]["id"])
    resp = api.create_back_report_request(th, create_back_report_payload(
        lease["id"], ["2026-03", "2026-04", "2026-05"]))
    data = validate_success(resp, 201)
    assert data["billable_months"] == 2


def test_back_report_fee_cents_mode_a(api):
    """PRD §3.6: "The `fee_cents` is then the billable-month count multiplied by a
    per-month price of two hundred cents, capped so that the fee never exceeds
    three thousand cents — the lesser of those two amounts."

    Design: Difficulty/combinatorial_formula/back_report_fee_tiered_min_max_mode_a
    """
    ctx = setup_active_tenant(api, plan_overrides={"back_reporting_included_months": 1})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"], property_address="9b Oak Ave")
    _record_three_months(api, ctx["landlord"]["id"], lease["id"])
    th = make_tenant_headers(ctx["tenant"]["id"])
    resp = api.create_back_report_request(th, create_back_report_payload(
        lease["id"], ["2026-03", "2026-04", "2026-05"]))
    data = validate_success(resp, 201)
    assert data["fee_cents"] == 400


# --------------------------------------------------------------------------
# Corner: fee zero when within included allowance
# --------------------------------------------------------------------------
def test_back_report_fee_zero_within_allowance(api):
    """PRD §3.6: "or zero if the allowance covers them all."

    Design: Corner/calculations/back_report_fee_zero_when_within_included_allowance
    """
    ctx = setup_active_tenant(api, plan_overrides={"back_reporting_included_months": 6})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"], property_address="35 Zero Ct")
    _record_three_months(api, ctx["landlord"]["id"], lease["id"])
    th = make_tenant_headers(ctx["tenant"]["id"])
    resp = api.create_back_report_request(th, create_back_report_payload(
        lease["id"], ["2026-03", "2026-04", "2026-05"]))
    data = validate_success(resp, 201)
    assert data["billable_months"] == 0
    assert data["fee_cents"] == 0


# --------------------------------------------------------------------------
# Corner: request month-count over the horizon
# --------------------------------------------------------------------------
def test_back_report_over_limit_rejected(api):
    """PRD §3.6: "The count of `requested_months` may not exceed the maximum
    back-reporting horizon of twenty-four months; a longer list is rejected with
    `ERR_BACK_REPORT_LIMIT_EXCEEDED`."

    Design: Corner/validations/backreport_limit_exceeded_returns_error
    """
    reset_clock_default(api)
    plan = create_plan(api)
    tenant = create_tenant(api, full_name="Lena Limit", email="lena@x.com")
    landlord = create_landlord(api)
    create_enrollment(api, tenant["id"], plan["id"])
    th = make_tenant_headers(tenant["id"])
    lease = get_success_data(api.create_lease(th, create_lease_payload(
        tenant["id"], landlord["id"], property_address="40 Limit St",
        lease_start="2023-01-01T00:00:00Z", lease_end="2027-01-01T00:00:00Z")))
    months = ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06",
              "2024-07", "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
              "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06",
              "2025-07", "2025-08", "2025-09", "2025-10", "2025-11", "2025-12", "2026-01"]
    resp = api.create_back_report_request(th, create_back_report_payload(lease["id"], months))
    validate_error(resp, ApiErrorId.ERR_BACK_REPORT_LIMIT_EXCEEDED.value, 422)


# --------------------------------------------------------------------------
# Corner: requested month lacks a RECORDED payment
# --------------------------------------------------------------------------
def test_back_report_month_without_payment_rejected(api):
    """PRD §3.6: "Each individual month must be no older than that same
    twenty-four-month horizon relative to the current month, must not lie in the
    future, and must have a `RECORDED` rent payment on the lease; a month failing
    any of these is rejected with `ERR_BACK_REPORT_MONTHS_INVALID`."

    Design: Corner/validations/backreport_month_without_payment_returns_error
    """
    ctx = setup_active_tenant(api, tenant_overrides={"full_name": "Mia Miss", "email": "mia@x.com"})
    lease = create_verified_lease(api, ctx["tenant"]["id"], ctx["landlord"]["id"], property_address="41 Miss Ave")
    th = make_tenant_headers(ctx["tenant"]["id"])
    resp = api.create_back_report_request(th, create_back_report_payload(lease["id"], ["2026-05"]))
    validate_error(resp, ApiErrorId.ERR_BACK_REPORT_MONTHS_INVALID.value, 422)


# --------------------------------------------------------------------------
# Corner: rejection voids the fee invoice
# --------------------------------------------------------------------------
def test_back_report_reject_voids_fee_invoice(api):
    """PRD §3.6: "A rejection instead moves it from `PENDING` to the terminal
    `REJECTED` and voids the `BACK_REPORT` fee invoice."

    Design: Corner/state_machines/backreport_reject_voids_fee_invoice
    """
    ctx = setup_pending_backreport(api, requested_months=["2026-05"], included_months=0, recorded_month="2026-05")
    th = make_tenant_headers(ctx["tenant"]["id"])
    decided = validate_success(api.decide_back_report_request(
        OFFICER, ctx["back_report"]["id"], {"decision": "REJECTED"}), 200)
    assert decided["status"] == "REJECTED"
    inv = validate_success(api.get_invoice(th, ctx["fee_invoice"]["id"]), 200)
    assert inv["status"] == "VOID"


# --------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / approve blocked until enrollment ACTIVE
# --------------------------------------------------------------------------
def _pending_enrollment_backreport(api, tenant_email):
    reset_clock_default(api)
    plan = create_plan(api, monthly_fee_cents=999, back_reporting_included_months=0)
    tenant = create_tenant(api, full_name="Ada Active", email=tenant_email)
    landlord = create_landlord(api)
    create_enrollment(api, tenant["id"], plan["id"])  # NOT paid -> PENDING_PAYMENT
    lease = create_verified_lease(api, tenant["id"], landlord["id"], property_address="12 Larch Ln")
    record_payment(api, landlord["id"], lease["id"], period_month="2026-05",
                   due_date="2026-05-05T00:00:00Z", paid_date="2026-05-05T00:00:00Z")
    th = make_tenant_headers(tenant["id"])
    br = get_success_data(api.create_back_report_request(th, create_back_report_payload(lease["id"], ["2026-05"])))
    fee_inv = back_report_invoice_for(api, tenant["id"], br["id"])
    pay_invoice(api, tenant["id"], fee_inv["id"])  # fee invoice PAID, enrollment still PENDING_PAYMENT
    return {"tenant": tenant, "back_report": br}


def test_back_report_approve_blocked_when_enrollment_inactive(api):
    """PRD §3.6: "Approval requires that the tenant's enrolment be `ACTIVE`
    (otherwise `ERR_ENROLLMENT_INACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/backreport_approve_blocked_until_enrollment_active
    """
    ctx = _pending_enrollment_backreport(api, "ada@x.com")
    resp = api.decide_back_report_request(OFFICER, ctx["back_report"]["id"], {"decision": "APPROVED"})
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INACTIVE.value, 402)


def test_back_report_stays_pending_when_approve_blocked(api):
    """PRD §3.6: "on success the request moves from `PENDING` to `APPROVED`." —
    a decision blocked by `ERR_ENROLLMENT_INACTIVE` performs no transition, so the
    request is still `PENDING`.

    Design: Difficulty/cross_entity_state_dependency/backreport_approve_blocked_until_enrollment_active
    """
    ctx = _pending_enrollment_backreport(api, "ada2@x.com")
    validate_error(api.decide_back_report_request(OFFICER, ctx["back_report"]["id"], {"decision": "APPROVED"}),
                   ApiErrorId.ERR_ENROLLMENT_INACTIVE.value, 402)
    th = make_tenant_headers(ctx["tenant"]["id"])
    after = validate_success(api.get_back_report_request(th, ctx["back_report"]["id"]), 200)
    assert after["status"] == "PENDING"
