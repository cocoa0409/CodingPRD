"""Cross-cutting behavior: error envelope, authentication/authorization,
customer ownership, application OCC, sweep idempotency, and referral lifecycle."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, NO_AUTH_HEADERS,
    create_account, charge_arrearage, submit_application,
    fresh_account_version, create_application_payload, create_referral,
    set_clock, run_sweep, get_account,
    TEST_USERS, make_customer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CSR = TEST_USERS["csr_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
FIELDCREW = TEST_USERS["fieldcrew_headers"]


def test_error_response_envelope_shape(api):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/error_response_envelope_shape
    """
    resp = api.get_account(NON_EXISTENT_UUID, ADMIN)
    body = resp.json()
    assert body.get("response_type") == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"]
    error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert error_data["message"].strip(), "message must explain the error"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring their operational
    capacity."
    PRD §2.1: "A request missing either header, or presenting a role outside this
    declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    account = create_account(service_address="70 Auth Ave")
    resp = api.get_account(account["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_customer_cannot_read_other_account(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
    acting CustomerAccount; ownership checks on any account-scoped resource compare
    the resource's account reference — the `account_id` path parameter or the
    `account_id` supplied in the request body — to `X-User-ID`, and a mismatch is
    rejected with `ERR_ACCOUNT_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_read_other_account
    """
    account = create_account(service_address="72 Owner Only")
    resp = api.get_account(
        account["id"], make_customer_headers("22222222-2222-2222-2222-222222222222"))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_OWNERSHIP_MISMATCH)


def test_fieldcrew_cannot_create_funding_source(api):
    """PRD §2.1: "A request whose role is not among the roles permitted for the
    targeted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /assistance/funding-sources is authorized for ProgramAdmin only.

    Design: Corner/rbac/fieldcrew_cannot_create_funding_source
    """
    resp = api.create_funding_source(
        {"name": "X", "funder_type": "STATE_GRANT", "fiscal_year": 2026,
         "appropriated_cents": 1_000, "priority_rank": 1,
         "eligible_tiers": ["TIER_1"]}, FIELDCREW)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_specialist_cannot_post_charges(api):
    """PRD §2.1: "A request whose role is not among the roles permitted for the
    targeted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: POST /assistance/accounts/{account_id}/charges is authorized for
    ProgramAdmin only.

    Design: Corner/rbac/specialist_cannot_post_charges
    """
    account = create_account(service_address="73 Charge Deny")
    resp = api.post_charge(
        account["id"], {"charge_type": "ARREARAGE", "amount_cents": 5_000}, SPECIALIST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_occ_application_create_stale_version_rejected(api):
    """PRD §2.7: "Two creation operations mutate a CustomerAccount as a side effect
    and therefore demand optimistic concurrency protection against a stale view of
    that account: submitting an assistance application, and creating a deferred
    payment agreement."
    PRD §2.7: "If the account's current `version` has advanced beyond that observed
    value — because another writer posted a charge, filed a newer application,
    created a DPA, or otherwise mutated the account in the meantime — the create is
    rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), so a client never
    silently supersedes work it never saw."

    Design: Corner/cross_cutting_layers/occ_application_create_stale_version_rejected
    """
    account = create_account(service_address="81 Occ Oaks")
    observed = fresh_account_version(account["id"])
    first = api.create_application(
        create_application_payload(account["id"], observed,
                                   household_size=1, gross_annual_income_cents=500_000,
                                   current_month_income_cents=40_000), CSR)
    app1 = validate_success(first, 201)
    stale = api.create_application(
        create_application_payload(account["id"], observed,
                                   household_size=2, gross_annual_income_cents=600_000,
                                   current_month_income_cents=50_000), CSR)
    validate_error(stale, ApiErrorId.ERR_STALE_ACCOUNT_VERSION)
    stayed = validate_success(api.get_application(app1["id"], CSR), 200)
    assert stayed["status"] == "SUBMITTED", (
        "the rejected create must not withdraw the application it never saw")


def test_sweep_idempotent_no_change_no_version_bump(api):
    """PRD §2.9: "Conversely, a reconciliation pass that changes nothing bumps
    nothing: during the nightly sweep, an account's `version` advances only where
    a field value actually changed."
    PRD §3.9: "The sweep responds with its tallies — `certificates_expired`,
    `enrollments_lapsed`, `dpas_defaulted`, `dpas_broken`, `referrals_expired`,
    `orders_created`, `orders_blocked`, `orders_unblocked`, and `orders_cancelled`".

    Design: Corner/cross_cutting_layers/sweep_idempotent_no_change_no_version_bump
    """
    account = create_account(service_address="83 Idle Inn")
    charge_arrearage(account["id"], 120_000)
    set_clock("2026-08-15T00:00:00Z")  # age 14 days -> CURRENT, nothing actionable
    v_pre = get_account(account["id"])["version"]
    counter_keys = ("certificates_expired", "enrollments_lapsed", "dpas_defaulted",
                    "dpas_broken", "referrals_expired", "orders_created",
                    "orders_blocked", "orders_unblocked", "orders_cancelled")
    for _ in range(2):
        sweep = run_sweep()
        for key in counter_keys:
            assert sweep[key] == 0, f"{key} must be 0 on an idle pass"
    v_post = get_account(account["id"])["version"]
    assert v_post == v_pre, "a sweep that changes nothing must not bump version"


def test_referral_expires_after_60_days_boundary(api):
    """PRD §3.9: "Referrals left hanging expire: the daily sweep moves an
    `INITIATED` referral to `EXPIRED` once the clock date runs more than 60 days
    past its `initiated_on`."

    Design: Corner/state_machines/referral_expires_after_60_days_boundary
    """
    account = create_account(service_address="11 Referral Rd")
    referral = create_referral(account["id"], agency_code="COMM_ACTION")

    set_clock("2026-09-30T00:00:00Z")  # exactly initiated_on + 60 days
    sweep = run_sweep()
    assert sweep["referrals_expired"] == 0
    alive = validate_success(api.get_referral(referral["id"], CSR), 200)
    assert alive["status"] == "INITIATED", "strictly-more-than-60 rule"

    set_clock("2026-10-01T00:00:00Z")  # 61 days past
    sweep = run_sweep()
    assert sweep["referrals_expired"] == 1
    expired = validate_success(api.get_referral(referral["id"], CSR), 200)
    assert expired["status"] == "EXPIRED"


def test_duplicate_referral_same_agency_rejected(api):
    """PRD §3.9: "One open referral per agency per account is the limit — a second
    `INITIATED` referral with the same account and `agency_code` is refused with
    `ERR_DUPLICATE_REFERRAL` (HTTP 422)."

    Design: Corner/validations/duplicate_referral_same_agency_rejected
    """
    account = create_account(service_address="36 Dup Dr")
    create_referral(account["id"], agency_code="COMM_ACTION")
    dup = api.create_referral(
        {"account_id": account["id"], "agency_code": "COMM_ACTION"}, CSR)
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_REFERRAL)
    other = api.create_referral(
        {"account_id": account["id"], "agency_code": "SALVATION_ARMY"}, CSR)
    data = validate_success(other, 201)
    assert data["status"] == "INITIATED"
