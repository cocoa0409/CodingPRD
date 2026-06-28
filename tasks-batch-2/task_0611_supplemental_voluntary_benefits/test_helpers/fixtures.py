"""Composite setup helpers.

These encapsulate the multi-step API sequences that most test claims need to
reach an interesting state. Each helper uses get_success_data() (lenient) so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion later.

The test harness restarts the server (empty DB) before every test, so every
helper builds its preconditions from scratch using only PRD-declared endpoints.

Identity threading: the Employee role is entity_backed; any ownership-gated
Employee call uses make_employee_headers(employee["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_employee_headers
from .constants import (
    PRODUCT_A_BASE_PREMIUM_CENTS,
    PRODUCT_A_ANNUAL_CAP_CENTS,
    PRODUCT_A_EOI_SURCHARGE_BPS,
    PRODUCT_A_PORTABILITY_LOADUP_BPS,
    GI_WINDOW_START,
    GI_WINDOW_END,
    BENEFIT_YEAR_START,
    IN_WINDOW_INSTANT,
    VALID_ROUTING_NUMBER,
)
from . import factories

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
_PAYROLL = TEST_USERS["payroll_headers"]
_SYSTEM = TEST_USERS["system_headers"]


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------
def set_clock(instant: str):
    """Advance the server logical clock to `instant`."""
    return get_success_data(api_client.set_clock(instant, _SYSTEM))


def create_employer(**overrides):
    payload = factories.create_employer_payload(**overrides)
    return get_success_data(api_client.create_employer(payload, _ADMIN))


def create_employee(employer_id, **overrides):
    payload = factories.create_employee_payload(employer_id, **overrides)
    return get_success_data(api_client.create_employee(payload, _ADMIN))


def create_product(employer_id, **overrides):
    payload = factories.create_plan_product_payload(employer_id, **overrides)
    return get_success_data(api_client.create_plan_product(payload, _ADMIN))


def add_schedule_item(product_id, **overrides):
    payload = factories.create_schedule_item_payload(product_id, **overrides)
    return get_success_data(api_client.create_schedule_item(payload, _ADMIN))


def open_product(product_id):
    return get_success_data(api_client.open_plan_product(product_id, _ADMIN))


def create_period(employer_id, **overrides):
    payload = factories.create_enrollment_period_payload(employer_id, **overrides)
    return get_success_data(api_client.create_enrollment_period(payload, _ADMIN))


def open_period(period_id):
    return get_success_data(api_client.open_enrollment_period(period_id, _ADMIN))


def create_verified_account(employee_id, **overrides):
    """Create a disbursement account and verify it. Returns the verified account."""
    payload = factories.create_disbursement_account_payload(employee_id, **overrides)
    acct = get_success_data(api_client.create_disbursement_account(payload, _ADMIN))
    return get_success_data(
        api_client.verify_disbursement_account(acct["id"], _ADMIN)
    )


def create_unverified_account(employee_id, **overrides):
    payload = factories.create_disbursement_account_payload(employee_id, **overrides)
    return get_success_data(api_client.create_disbursement_account(payload, _ADMIN))


# ---------------------------------------------------------------------------
# Tier 2: Product + period setup
# ---------------------------------------------------------------------------
def setup_open_product_and_period(
    employer=None,
    schedule_items=None,
    product_overrides=None,
    period_overrides=None,
    employer_overrides=None,
):
    """Active employer + an OPEN product (with schedule lines) + an OPEN period.

    schedule_items: list of dicts of schedule-item overrides; defaults to one
    FRACTURE line if None.
    Returns (employer, product, period, [schedule_items]).
    """
    if employer is None:
        employer = create_employer(**(employer_overrides or {}))
    product = create_product(employer["id"], **(product_overrides or {}))
    if schedule_items is None:
        schedule_items = [{}]
    created_items = [add_schedule_item(product["id"], **si) for si in schedule_items]
    open_product(product["id"])
    product = get_success_data(api_client.get_plan_product(product["id"], _ADMIN))
    period = create_period(employer["id"], **(period_overrides or {}))
    open_period(period["id"])
    period = get_success_data(api_client.get_enrollment_period(period["id"], _ADMIN))
    return employer, product, period, created_items


# ---------------------------------------------------------------------------
# Tier 1 / Tier 3: enrollment lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_pending_enrollment(
    employer=None,
    schedule_items=None,
    product_overrides=None,
    period_overrides=None,
    employer_overrides=None,
    enrolled_at=IN_WINDOW_INSTANT,
    enrollment_overrides=None,
    as_employee=False,
):
    """Build the full prerequisite chain and create a PENDING enrollment stamped at
    `enrolled_at`. Returns (employer, product, period, employee, enrollment, items).
    """
    employer, product, period, items = setup_open_product_and_period(
        employer=employer,
        schedule_items=schedule_items,
        product_overrides=product_overrides,
        period_overrides=period_overrides,
        employer_overrides=employer_overrides,
    )
    employee = create_employee(employer["id"])
    if enrolled_at is not None:
        set_clock(enrolled_at)
    payload = factories.create_enrollment_payload(
        employee["id"], product["id"], period["id"], **(enrollment_overrides or {})
    )
    headers = make_employee_headers(employee["id"]) if as_employee else _ADMIN
    enrollment = get_success_data(api_client.create_enrollment(payload, headers))
    return employer, product, period, employee, enrollment, items


def create_active_enrollment(**kwargs):
    """PENDING enrollment, then ACTIVE. Returns the same 6-tuple, enrollment ACTIVE."""
    employer, product, period, employee, enrollment, items = create_pending_enrollment(
        **kwargs
    )
    get_success_data(api_client.activate_enrollment(enrollment["id"], _ADMIN))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], _ADMIN))
    return employer, product, period, employee, enrollment, items


def post_deduction(enrollment_id, pay_period_index, outcome):
    payload = factories.create_payroll_deduction_payload(pay_period_index, outcome)
    return get_success_data(
        api_client.post_payroll_deduction(enrollment_id, payload, _PAYROLL)
    )


def create_funded_enrollment(**kwargs):
    """ACTIVE + one POSTED deduction (funding_status CURRENT).

    Returns (employer, product, period, employee, enrollment, items). The
    enrollment dict is refreshed after the POSTED deduction.
    """
    employer, product, period, employee, enrollment, items = create_active_enrollment(
        **kwargs
    )
    post_deduction(enrollment["id"], 0, "POSTED")
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], _ADMIN))
    return employer, product, period, employee, enrollment, items


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def file_claim(enrollment_id, account_id, event_code, event_date, headers=None):
    payload = factories.create_claim_payload(
        enrollment_id, account_id, event_code, event_date
    )
    return get_success_data(
        api_client.create_claim(payload, headers or _ADMIN)
    )


def file_and_review_claim(enrollment_id, account_id, event_code, event_date):
    """File a claim then move it to UNDER_REVIEW. Returns the claim (UNDER_REVIEW)."""
    claim = file_claim(enrollment_id, account_id, event_code, event_date)
    get_success_data(api_client.start_review_claim(claim["id"], _ADJUSTER))
    return get_success_data(api_client.get_claim(claim["id"], _ADJUSTER))


def file_review_approve_claim(enrollment_id, account_id, event_code, event_date):
    """File → start-review → approve. Returns the APPROVED claim."""
    claim = file_and_review_claim(enrollment_id, account_id, event_code, event_date)
    get_success_data(api_client.approve_claim(claim["id"], _ADJUSTER))
    return get_success_data(api_client.get_claim(claim["id"], _ADJUSTER))


def file_approve_disburse_claim(enrollment_id, account_id, event_code, event_date):
    """File → review → approve → disburse. Returns (claim PAID, disbursement)."""
    claim = file_review_approve_claim(
        enrollment_id, account_id, event_code, event_date
    )
    disbursement = get_success_data(api_client.disburse_claim(claim["id"], _ADJUSTER))
    claim = get_success_data(api_client.get_claim(claim["id"], _ADJUSTER))
    return claim, disbursement


# ---------------------------------------------------------------------------
# Tier 4: ledger / threshold targeting
# ---------------------------------------------------------------------------
def setup_funded_enrollment_with_account(
    schedule_items=None, product_overrides=None
):
    """Funded ACTIVE enrollment + a VERIFIED disbursement account.

    Returns (employer, product, period, employee, enrollment, account, items).
    """
    if schedule_items is None:
        schedule_items = [{}]
    employer, product, period, employee, enrollment, items = create_funded_enrollment(
        schedule_items=schedule_items, product_overrides=product_overrides
    )
    account = create_verified_account(employee["id"])
    return employer, product, period, employee, enrollment, account, items


def lapse_enrollment(enrollment_id, start_index=1):
    """Post 3 consecutive FAILED deductions to drive funding_status to LAPSED.

    Assumes the enrollment is ACTIVE. Returns the enrollment after lapsing.
    """
    for i in range(3):
        post_deduction(enrollment_id, start_index + i, "FAILED")
    return get_success_data(api_client.get_enrollment(enrollment_id, _ADMIN))


def terminate_enrollment(enrollment_id):
    get_success_data(api_client.terminate_enrollment(enrollment_id, _ADMIN))
    return get_success_data(api_client.get_enrollment(enrollment_id, _ADMIN))


# ---------------------------------------------------------------------------
# Tier 5: portability (terminal) setup
# ---------------------------------------------------------------------------
def setup_terminated_enrollment_for_port(product_overrides=None):
    """Active enrollment created by the Employee, then TERMINATED, ready to port.

    Returns (employer, product, period, employee, enrollment, current_version).
    The enrollment is created as the Employee (entity_backed) so subsequent
    ownership-gated port calls succeed.
    """
    employer, product, period, employee, enrollment, items = create_active_enrollment(
        product_overrides=product_overrides, as_employee=True
    )
    terminate_enrollment(enrollment["id"])
    emp_headers = make_employee_headers(employee["id"])
    enrollment = get_success_data(
        api_client.get_enrollment(enrollment["id"], emp_headers)
    )
    return employer, product, period, employee, enrollment, enrollment["version"]
