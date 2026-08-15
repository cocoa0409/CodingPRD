"""Composite setup helpers.

The test harness restarts the API server before every test, so each fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import INCOME_TIER_1, INCOME_TIER_2, INCOME_TIER_3
from .factories import (
    create_account_payload, create_charge_payload, create_application_payload,
    create_dpa_payload, create_payment_payload, create_certificate_payload,
    create_shutoff_order_payload, create_funding_source_payload,
    create_referral_payload,
)
from .test_users import TEST_USERS, make_csr_headers, make_specialist_headers

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
FIELDCREW = TEST_USERS["fieldcrew_headers"]


# ---------------------------------------------------------------------------
# Accounts & clock
# ---------------------------------------------------------------------------

def create_account(**overrides) -> dict:
    resp = api_client.create_account(create_account_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def get_account(account_id) -> dict:
    return get_success_data(api_client.get_account(account_id, CSR), 200)


def fresh_account_version(account_id) -> int:
    return get_account(account_id)["version"]


def charge_arrearage(account_id, amount_cents, effective_on="2026-08-01") -> dict:
    payload = create_charge_payload(charge_type="ARREARAGE", amount_cents=amount_cents,
                                    effective_on=effective_on)
    return get_success_data(api_client.post_charge(account_id, payload, ADMIN), 201)


def charge_current(account_id, amount_cents) -> dict:
    payload = create_charge_payload(charge_type="CURRENT", amount_cents=amount_cents)
    payload.pop("effective_on", None)
    return get_success_data(api_client.post_charge(account_id, payload, ADMIN), 201)


def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), 200)


def run_sweep(payload=None) -> dict:
    """Run the nightly ops pass; payload may carry observed_low_f / observed_heat_index_f."""
    return get_success_data(api_client.run_daily_sweep(payload or {}, ADMIN), 200)


# ---------------------------------------------------------------------------
# Applications & enrollments
# ---------------------------------------------------------------------------

def submit_application(account_id, submitter_user_id="csr_1", **income_overrides) -> dict:
    """Submit an application as a CustomerServiceRep with the given operator id."""
    income = dict(INCOME_TIER_1)
    income.update(income_overrides)
    payload = create_application_payload(
        account_id, fresh_account_version(account_id), **income)
    resp = api_client.create_application(payload, make_csr_headers(submitter_user_id))
    return get_success_data(resp, 201)


def begin_review(application_id, reviewer_user_id="es_1") -> dict:
    resp = api_client.begin_review(application_id, make_specialist_headers(reviewer_user_id))
    return get_success_data(resp, 200)


def verify_application(application_id, reviewer_user_id="es_1") -> dict:
    resp = api_client.verify_application(application_id, make_specialist_headers(reviewer_user_id))
    return get_success_data(resp, 200)


def create_verified_application(account_id, submitter_user_id="csr_1",
                                reviewer_user_id="es_1", **income_overrides) -> dict:
    """Submit + begin-review + verify. Returns the VERIFIED application."""
    app = submit_application(account_id, submitter_user_id=submitter_user_id,
                             **income_overrides)
    begin_review(app["id"], reviewer_user_id=reviewer_user_id)
    return verify_application(app["id"], reviewer_user_id=reviewer_user_id)


def get_enrollment_for_application(application_id) -> dict:
    """Locate the PENDING enrollment created by a verify (lineage filter)."""
    resp = api_client.list_enrollments(SPECIALIST, params={"application_id": application_id})
    rows = get_success_data(resp, 200)
    assert isinstance(rows, list) and len(rows) == 1, (
        f"expected exactly one enrollment for application {application_id}, got {rows}")
    return rows[0]


def create_active_enrollment(account_id, income=None, submitter_user_id="csr_1",
                             reviewer_user_id="es_1") -> tuple:
    """Verified application + activated enrollment. Returns (application, enrollment)."""
    income = income or INCOME_TIER_2
    app = create_verified_application(
        account_id, submitter_user_id=submitter_user_id,
        reviewer_user_id=reviewer_user_id, **income)
    enrollment = get_enrollment_for_application(app["id"])
    resp = api_client.activate_enrollment(enrollment["id"], make_csr_headers("csr_1"))
    enrollment = get_success_data(resp, 200)
    return app, enrollment


# ---------------------------------------------------------------------------
# Deferred payment agreements & payments
# ---------------------------------------------------------------------------

def create_dpa(account_id, installment_count=4) -> dict:
    """Create a DPA with a freshly read account version (OCC)."""
    payload = create_dpa_payload(account_id, fresh_account_version(account_id),
                                 installment_count=installment_count)
    return get_success_data(api_client.create_dpa(payload, CSR), 201)


def attempt_create_dpa(account_id, installment_count=4, expected_version=None, headers=None):
    """Raw-response variant for error-path tests; defaults to a fresh version so
    the OCC guard passes and the rule under test is what fires."""
    version = expected_version if expected_version is not None else fresh_account_version(account_id)
    payload = create_dpa_payload(account_id, version, installment_count=installment_count)
    return api_client.create_dpa(payload, headers or CSR)


def pay(account_id, amount_cents, tender_type="CASH", headers=None) -> dict:
    payload = create_payment_payload(account_id, amount_cents, tender_type=tender_type)
    return get_success_data(api_client.create_payment(payload, headers or CSR), 201)


def create_and_activate_dpa(account_id, installment_count=4, down_payment_cents=None) -> dict:
    """Create a DPA and complete its down payment so it stands ACTIVE."""
    dpa = create_dpa(account_id, installment_count=installment_count)
    required = dpa["down_payment_required_cents"]
    if required > 0:
        pay(account_id, down_payment_cents if down_payment_cents is not None else required)
    return get_success_data(api_client.get_dpa(dpa["id"], CSR), 200)


# ---------------------------------------------------------------------------
# Medical certificates & shutoff orders
# ---------------------------------------------------------------------------

def create_certificate(account_id, effective_from, condition_class="SERIOUS",
                       physician_name="Dr. Cert", physician_license_number="L-0") -> dict:
    payload = create_certificate_payload(
        account_id, effective_from, condition_class=condition_class,
        physician_name=physician_name, physician_license_number=physician_license_number)
    return get_success_data(api_client.create_certificate(payload, CSR), 201)


def create_shutoff_order(account_id, scheduled_date) -> dict:
    payload = create_shutoff_order_payload(account_id, scheduled_date)
    return get_success_data(api_client.create_shutoff_order(payload, ADMIN), 201)


def execute_shutoff_order(order_id) -> dict:
    return get_success_data(api_client.execute_shutoff_order(order_id, FIELDCREW), 200)


# ---------------------------------------------------------------------------
# Funding sources & allocations
# ---------------------------------------------------------------------------

def create_fund(**overrides) -> dict:
    return get_success_data(api_client.create_funding_source(
        create_funding_source_payload(**overrides), ADMIN), 201)


def allocate(account_id, amount_cents) -> list:
    """Successful allocation batch; returns the list of allocation rows."""
    resp = api_client.create_fund_allocations(
        {"account_id": account_id, "amount_cents": amount_cents}, ADMIN)
    return get_success_data(resp, 201)


def create_referral(account_id, agency_code="COMM_ACTION") -> dict:
    return get_success_data(api_client.create_referral(
        create_referral_payload(account_id, agency_code=agency_code), CSR), 201)


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_delinquent_account(arrearage_cents=120_000, charge_date="2026-08-01",
                             service_address="100 Delinquent Dr", **account_overrides) -> dict:
    """Account with an aged arrearage balance (no enrollment)."""
    account = create_account(service_address=service_address, **account_overrides)
    charge_arrearage(account["id"], arrearage_cents, effective_on=charge_date)
    return get_account(account["id"])


def setup_account_with_active_enrollment(income=None, arrearage_cents=None,
                                         service_address="200 Enrolled Ave",
                                         **account_overrides) -> tuple:
    """Account (+ optional arrearage charge) with an ACTIVE enrollment.
    Returns (account, application, enrollment)."""
    account = create_account(service_address=service_address, **account_overrides)
    if arrearage_cents is not None:
        charge_arrearage(account["id"], arrearage_cents)
    app, enrollment = create_active_enrollment(account["id"], income=income)
    return get_account(account["id"]), app, enrollment


def setup_disconnected_account(arrearage_cents=120_000, with_enrollment_income=None,
                               deposit_held_cents=0,
                               service_address="300 Cutoff Ct") -> tuple:
    """Account driven to DISCONNECTED: arrearage aged, manual order created at
    clock 2026-09-15 for 2026-09-30, executed at 2026-09-30.
    Returns (account, order)."""
    account = create_account(service_address=service_address,
                             deposit_held_cents=deposit_held_cents)
    charge_arrearage(account["id"], arrearage_cents)
    if with_enrollment_income is not None:
        create_active_enrollment(account["id"], income=with_enrollment_income)
    set_clock("2026-09-15T00:00:00Z")
    order = create_shutoff_order(account["id"], "2026-09-30")
    set_clock("2026-09-30T00:00:00Z")
    execute_shutoff_order(order["id"])
    return get_account(account["id"]), get_success_data(
        api_client.get_shutoff_order(order["id"], ADMIN), 200)
