"""Composite setup helpers for the LIHEAP API.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the test harness restarts the server against an empty database before
every test). Helpers use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertions.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_funding_pool_payload,
    create_household_payload,
    create_application_payload,
    create_income_document_payload,
    create_vendor_payload,
    create_utility_account_payload,
    create_pledge_payload,
    create_payment_payload,
    create_crisis_benefit_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_vendoragent_headers,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["programadmin_headers"]


def _data(resp):
    return get_success_data(resp)


# --- Atomic building blocks ------------------------------------------------
def new_funding_pool(api, **overrides):
    """Create an OPEN funding pool. Returns the pool dict (with version)."""
    return _data(api.create_funding_pool(create_funding_pool_payload(**overrides), PA))


def new_enrolled_vendor(api, **overrides):
    """Create a vendor and enroll it. Returns the ENROLLED vendor dict."""
    vendor = _data(api.create_vendor(create_vendor_payload(**overrides), PA))
    return _data(api.enroll_vendor(vendor["id"], PA))


def new_pending_vendor(api, **overrides):
    """Create a vendor and leave it PENDING (unenrolled)."""
    return _data(api.create_vendor(create_vendor_payload(**overrides), PA))


def new_household(api, **overrides):
    return _data(api.create_household(create_household_payload(**overrides), CW))


def new_utility_account(api, household_id, vendor_id, **overrides):
    payload = create_utility_account_payload(household_id, vendor_id, **overrides)
    return _data(api.create_utility_account(payload, CW))


def new_draft_application(api, household_id, **overrides):
    payload = create_application_payload(household_id, **overrides)
    return _data(api.create_application(payload, CW))


def submit_app(api, application_id, household_id):
    """Submit an application as its owning Applicant. Returns the SUBMITTED app."""
    return _data(api.submit_application(application_id, make_applicant_headers(household_id)))


def add_verified_income(api, application_id, reported_income_cents, verified_income_cents=None):
    """Upload one income document and verify it. Returns the VERIFIED document."""
    if verified_income_cents is None:
        verified_income_cents = reported_income_cents
    doc = _data(api.create_income_document(
        create_income_document_payload(application_id, reported_income_cents=reported_income_cents), CW))
    return _data(api.verify_income_document(
        doc["id"], {"outcome": "VERIFIED", "verified_income_cents": verified_income_cents}, CW))


def pool_version(api, pool_id):
    """Read the current version of a pool (Caseworker may GET pools)."""
    return _data(api.get_funding_pool(pool_id, CW))["version"]


# --- Tier 3: Full-lifecycle shortcuts --------------------------------------
def setup_submitted_application(api, pool_overrides=None, household_overrides=None,
                                income_cents=1_700_000):
    """OPEN HEATING pool + household + a SUBMITTED (not yet approved) application.

    Returns a context dict: pool, pool_id, household, household_id,
    application, application_id.
    """
    pool = new_funding_pool(api, **(pool_overrides or {}))
    household = new_household(api, **(household_overrides or {"annual_income_cents": income_cents}))
    application = new_draft_application(api, household["id"])
    application = submit_app(api, application["id"], household["id"])
    return {
        "pool": pool, "pool_id": pool["id"],
        "household": household, "household_id": household["id"],
        "application": application, "application_id": application["id"],
    }


def setup_approved_application(api, pool_overrides=None, vendor_overrides=None,
                               household_overrides=None, account_overrides=None,
                               reported_income_cents=1_700_000, verified_income_cents=None):
    """Full chain to an APPROVED application ready to be pledged against.

    Builds: OPEN HEATING pool + ENROLLED vendor + household + utility account +
    application submitted, income verified, application approved.

    Returns a context dict with pool/vendor/household/account/application (+ *_id)
    and pool_version (the pool's current version after approval).
    """
    pool = new_funding_pool(api, **(pool_overrides or {}))
    vendor = new_enrolled_vendor(api, **(vendor_overrides or {}))
    household = new_household(api, **(household_overrides or {"annual_income_cents": reported_income_cents}))
    account = new_utility_account(api, household["id"], vendor["id"], **(account_overrides or {}))
    application = new_draft_application(api, household["id"])
    submit_app(api, application["id"], household["id"])
    add_verified_income(api, application["id"], reported_income_cents, verified_income_cents)
    application = _data(api.approve_application(application["id"], CW))
    return {
        "pool": pool, "pool_id": pool["id"],
        "vendor": vendor, "vendor_id": vendor["id"],
        "household": household, "household_id": household["id"],
        "account": account, "account_id": account["id"],
        "application": application, "application_id": application["id"],
        "pool_version": pool_version(api, pool["id"]),
    }


def add_utility_account(api, ctx, **overrides):
    """Add a second utility account to an existing context (same household+vendor)."""
    return new_utility_account(api, ctx["household_id"], ctx["vendor_id"], **overrides)


def create_pledge_on(api, ctx, account_id=None, **pledge_overrides):
    """Create a pledge against the context's pool/vendor, refreshing pool_version.

    Uses the current pool version for the OCC guard unless expected_pool_version
    is supplied in pledge_overrides. Returns the created Pledge dict.
    """
    account_id = account_id or ctx["account_id"]
    expected = pledge_overrides.pop("expected_pool_version", None)
    if expected is None:
        expected = pool_version(api, ctx["pool_id"])
    payload = create_pledge_payload(
        ctx["vendor_id"], ctx["pool_id"], account_id, expected,
        application_id=ctx["application_id"], **pledge_overrides)
    resp = api.create_pledge(payload, CW)
    ctx["pool_version"] = pool_version(api, ctx["pool_id"])
    return resp


def create_initiated_payment(api, pledge_id, amount_cents):
    return _data(api.create_payment(create_payment_payload(pledge_id, amount_cents=amount_cents), CW))


def remit(api, payment_id, vendor_id):
    """Remit a payment as the owning VendorAgent. Returns the REMITTED payment."""
    return _data(api.remit_payment(payment_id, make_vendoragent_headers(vendor_id)))


# --- Crisis setups ---------------------------------------------------------
def setup_open_crisis(api, crisis_type="NO_HEAT", pool_overrides=None,
                      account_overrides=None, household_overrides=None):
    """OPEN CRISIS pool + ENROLLED vendor + household + account + one OPEN crisis.

    Returns a context dict: pool, pool_id, vendor, vendor_id, household,
    household_id, account, account_id, crisis, crisis_id.
    """
    cpool_defaults = {"program_component": "CRISIS"}
    cpool_defaults.update(pool_overrides or {})
    pool = new_funding_pool(api, **cpool_defaults)
    vendor = new_enrolled_vendor(api)
    household = new_household(api, **(household_overrides or {}))
    account = new_utility_account(api, household["id"], vendor["id"], **(account_overrides or {}))
    crisis = _data(api.create_crisis_benefit(
        create_crisis_benefit_payload(household["id"], account["id"], pool["id"],
                                       crisis_type=crisis_type), CW))
    return {
        "pool": pool, "pool_id": pool["id"],
        "vendor": vendor, "vendor_id": vendor["id"],
        "household": household, "household_id": household["id"],
        "account": account, "account_id": account["id"],
        "crisis": crisis, "crisis_id": crisis["id"],
    }
