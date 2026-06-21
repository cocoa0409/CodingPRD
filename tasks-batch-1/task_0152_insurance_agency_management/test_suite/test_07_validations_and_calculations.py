"""Breadth tests for calculation variants and business-rule validations.

Queue B (Corner) translations for the `calculations` and `validations` sections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    TEST_USERS,
    ApiErrorId,
    make_producer_headers,
    setup_compliant_writer,
    setup_active_policy,
    setup_active_policy_no_split,
    create_quoted_policy,
    add_writing_split,
    bind_policy,
    activate_policy,
    create_producer,
    create_active_carrier,
    create_product,
    create_account,
    open_trust_account_with_balance,
    open_statement,
    get_statement,
    finalize_statement,
    set_clock,
    factories,
)

ADMIN = lambda: TEST_USERS["agency_admin_headers"]
MANAGER = lambda: TEST_USERS["account_manager_headers"]
TRUST = lambda: TEST_USERS["trust_accountant_headers"]


# ===========================================================================
# calculations
# ===========================================================================
def test_renewal_rate_lower_than_new_business(api):
    """PRD §3.5: "if the `term_kind` is `RENEWAL`, the base rate is instead the product's
    `renewal_commission_pct` when not null, and otherwise the carrier's
    `default_renewal_commission_pct` (renewal rates are normally the lower of the two)."

    Design: Corner/calculations/renewal_rate_lower_than_new_business
    """
    set_clock("2026-02-01T00:00:00Z")
    ctx = setup_compliant_writer(
        carrier_overrides={
            "default_new_business_commission_pct": 0.20,
            "default_renewal_commission_pct": 0.10,
        },
        product_overrides={"cancellation_basis": "PRO_RATA"},
    )
    producer = ctx["producer"]
    # A prior new-business policy to renew from.
    prior = create_quoted_policy(
        ctx,
        annual_premium_cents=1_200_000,
        effective_date="2025-02-01T00:00:00Z", expiration_date="2026-02-01T00:00:00Z",
    )
    # The renewal-term policy.
    renewal = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                ctx["account"]["id"], ctx["product"]["id"], producer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-02-01T00:00:00Z", expiration_date="2027-02-01T00:00:00Z",
                renewed_from_policy_id=prior["id"],
            ),
            make_producer_headers(producer["id"]),
        )
    )
    assert renewal["term_kind"] == "RENEWAL", renewal
    _, v = add_writing_split(ctx, renewal, split_pct=1.0, role="WRITING")
    bound = bind_policy(ctx, renewal["id"], v)
    activate_policy(renewal["id"], bound["version"])
    stmt = open_statement(producer["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    data = get_statement(stmt["id"])
    # Renewal rate 0.10 * 1_200_000 = 120000, * 1.10 tier = 132000, * 1.0 split.
    assert data["gross_commission_cents"] == 132000, data


def test_tier1_low_premium_no_multiplier(api):
    """PRD §3.5: "when the annual premium is below one thousand dollars (that is, below 100,000
    cents) the multiplier is 1.00".

    Design: Corner/calculations/tier1_low_premium_no_multiplier
    """
    set_clock("2026-02-01T00:00:00Z")
    ctx = setup_compliant_writer(
        product_overrides={"new_business_commission_pct": 0.20, "cancellation_basis": "PRO_RATA"}
    )
    s = setup_active_policy(
        ctx=ctx,
        policy_overrides={
            "annual_premium_cents": 99999,
            "effective_date": "2026-02-01T00:00:00Z",
            "expiration_date": "2027-02-01T00:00:00Z",
        },
    )
    stmt = open_statement(ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    data = get_statement(stmt["id"])
    # round(round(99999*0.20)*1.00) = round(20000*1.00) = 20000.
    assert data["gross_commission_cents"] == 20000, data


# ===========================================================================
# validations
# ===========================================================================
def test_bind_missing_license_returns_license_not_active(api):
    """PRD §3.4: "The writing producer must hold a license whose computed status is `ACTIVE`
    matching both the policy's `state_code` and the product's `line_of_business`; absent such a
    license the bind is rejected with `ERR_LICENSE_NOT_ACTIVE` (HTTP 422)."

    Design: Corner/validations/bind_missing_license_returns_license_not_active
    """
    set_clock("2026-06-01T00:00:00Z")
    carrier = create_active_carrier()
    product = create_product(carrier["id"], line_of_business="AUTO")
    producer = create_producer()  # NO license.
    account = create_account(producer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], producer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(producer["id"]),
        )
    )
    resp = api.bind_policy(
        policy["id"], {"expected_policy_version": policy["version"]},
        make_producer_headers(producer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value)


def test_bind_no_appointment_returns_not_appointed(api):
    """PRD §3.4: "an appointment with status `ACTIVE` must exist for the combination of that
    writing producer, the product's carrier, and the policy's `state_code`; absent it, the
    bind is rejected with `ERR_NOT_APPOINTED` (HTTP 422)."

    Design: Corner/validations/bind_no_appointment_returns_not_appointed
    """
    set_clock("2026-06-01T00:00:00Z")
    carrier = create_active_carrier()
    product = create_product(carrier["id"], line_of_business="AUTO")
    producer = create_producer()
    # ACTIVE license but NO ACTIVE appointment.
    get_success_data(
        api.create_license(
            factories.create_license_payload(
                producer["id"], state_code="CA", line_of_business="AUTO",
                effective_date="2025-01-01T00:00:00Z", expiration_date="2030-01-01T00:00:00Z",
            ),
            ADMIN(),
        )
    )
    account = create_account(producer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], producer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(producer["id"]),
        )
    )
    resp = api.bind_policy(
        policy["id"], {"expected_policy_version": policy["version"]},
        make_producer_headers(producer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_APPOINTED.value)


def test_inactive_producer_split_rejected(api):
    """PRD §3.5: "A split may not target a producer whose status is `INACTIVE`; such an attempt
    is rejected with `ERR_PRODUCER_INACTIVE` (HTTP 422)."

    Design: Corner/validations/inactive_producer_split_rejected
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    writer = create_producer(full_name="Writer PI")
    inactive = create_producer(full_name="Inactive PI", default_split_pct=0.5)
    get_success_data(
        api.deactivate_producer(inactive["id"], {"expected_producer_version": inactive["version"]}, ADMIN())
    )
    account = create_account(writer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], writer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(writer["id"]),
        )
    )
    resp = api.create_commission_split(
        factories.create_commission_split_payload(
            policy["id"], inactive["id"], policy["version"], split_pct=0.5, role="SERVICING"
        ),
        make_producer_headers(writer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCER_INACTIVE.value)


def test_split_over_allocation_rejected(api):
    """PRD §3.5: "Adding a split whose inclusion would push the sum of `WRITING` plus
    `SERVICING` percentages above 1.0 is rejected with `ERR_SPLIT_OVER_ALLOCATED` (HTTP 422)."

    Design: Corner/validations/split_over_allocation_rejected
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    writer = create_producer(full_name="Writer OA", default_split_pct=0.7)
    servicer = create_producer(full_name="Servicer OA", default_split_pct=0.4)
    account = create_account(writer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], writer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(writer["id"]),
        )
    )
    get_success_data(
        api.create_commission_split(
            factories.create_commission_split_payload(
                policy["id"], writer["id"], policy["version"], split_pct=0.7, role="WRITING"
            ),
            make_producer_headers(writer["id"]),
        )
    )
    policy2 = get_success_data(api.get_policy(policy["id"], make_producer_headers(writer["id"])))
    resp = api.create_commission_split(
        factories.create_commission_split_payload(
            policy["id"], servicer["id"], policy2["version"], split_pct=0.4, role="SERVICING"
        ),
        make_producer_headers(writer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPLIT_OVER_ALLOCATED.value)


def test_override_split_exempt_from_cap(api):
    """PRD §3.5: "The `WRITING` and `SERVICING` shares on a policy together represent the full
    agency commission and so their `split_pct` values may sum to at most 1.0; an `OVERRIDE`
    split is paid on top and is excluded from that cap."

    Design: Corner/validations/override_split_exempt_from_cap
    """
    carrier = create_active_carrier()
    product = create_product(carrier["id"])
    writer = create_producer(full_name="Writer OV", default_split_pct=1.0)
    manager = create_producer(full_name="Manager OV", default_split_pct=0.1)
    account = create_account(writer["id"])
    policy = get_success_data(
        api.create_policy(
            factories.create_policy_payload(
                account["id"], product["id"], writer["id"],
                annual_premium_cents=1_200_000,
                effective_date="2026-01-01T00:00:00Z", expiration_date="2027-01-01T00:00:00Z",
            ),
            make_producer_headers(writer["id"]),
        )
    )
    get_success_data(
        api.create_commission_split(
            factories.create_commission_split_payload(
                policy["id"], writer["id"], policy["version"], split_pct=1.0, role="WRITING"
            ),
            make_producer_headers(writer["id"]),
        )
    )
    policy2 = get_success_data(api.get_policy(policy["id"], make_producer_headers(writer["id"])))
    resp = api.create_commission_split(
        factories.create_commission_split_payload(
            policy["id"], manager["id"], policy2["version"], split_pct=0.1, role="OVERRIDE"
        ),
        make_producer_headers(writer["id"]),
    )
    data = validate_success(resp, 201)
    assert data["role"] == "OVERRIDE", data


def test_cancel_out_of_term_rejected(api):
    """PRD §3.6: "The `cancellation_date` must fall within the policy's term — at or after
    `effective_date` and strictly before `expiration_date`; a date outside that half-open
    window is rejected with `ERR_CANCEL_OUT_OF_TERM` (HTTP 422)."

    Design: Corner/validations/cancel_out_of_term_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    open_trust_account_with_balance(5_000_000, state_code="CA")
    s = setup_active_policy_no_split(
        policy_overrides={
            "annual_premium_cents": 1_200_000,
            "effective_date": "2026-01-01T00:00:00Z",
            "expiration_date": "2027-01-01T00:00:00Z",
        }
    )
    policy = s["policy"]
    resp = api.cancel_policy(
        policy["id"],
        {
            "expected_policy_version": policy["version"],
            "cancellation_date": "2025-06-01T00:00:00Z",  # before effective_date.
            "cancellation_reason": "INSURED_REQUEST",
        },
        MANAGER(),
    )
    validate_error(resp, ApiErrorId.ERR_CANCEL_OUT_OF_TERM.value)


def test_finalize_before_period_end_rejected(api):
    """PRD §3.10: "Finalization is permitted only once the period has ended — the statement's
    `period_end` must be at or before the current moment, otherwise it is rejected with
    `ERR_VALIDATION_PERIOD_NOT_ENDED` (HTTP 422)".

    Design: Corner/validations/finalize_before_period_end_rejected
    """
    set_clock("2026-02-15T00:00:00Z")
    producer = create_producer()
    stmt = open_statement(producer["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    resp = api.finalize_statement(
        stmt["id"], {"expected_commissionstatement_version": stmt["version"]}, TRUST()
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PERIOD_NOT_ENDED.value)


def test_pay_below_minimum_balance_rejected(api):
    """PRD §3.10: "the disbursement may not drop the balance below the account's
    `minimum_balance_cents` floor, and an attempt that would breach it is rejected with
    `ERR_TRUST_MINIMUM_BREACH` (HTTP 422)."

    Design: Corner/validations/pay_below_minimum_balance_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    trust = open_trust_account_with_balance(1_000_000, state_code="CA", minimum_balance_cents=500000)
    ctx = setup_compliant_writer(product_overrides={"cancellation_basis": "PRO_RATA"})
    s = setup_active_policy(
        ctx=ctx,
        policy_overrides={
            "annual_premium_cents": 4_000_000,
            "effective_date": "2026-02-01T00:00:00Z",
            "expiration_date": "2027-02-01T00:00:00Z",
        },
    )
    stmt = open_statement(ctx["producer"]["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    finalized = finalize_statement(stmt["id"], stmt["version"])
    # net = round(round(4_000_000*0.15)*1.10) = round(600000*1.10) = 660000.
    assert finalized["net_payable_cents"] == 660000, finalized
    resp = api.pay_statement(
        stmt["id"],
        {"expected_commissionstatement_version": finalized["version"], "trust_account_id": trust["id"]},
        TRUST(),
    )
    validate_error(resp, ApiErrorId.ERR_TRUST_MINIMUM_BREACH.value)
