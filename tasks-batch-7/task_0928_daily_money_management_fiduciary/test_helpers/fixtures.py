"""Composite setup helpers.

Nothing is ever seeded server-side: every fixture builds its preconditions
from scratch through the declared endpoints, because the harness restarts the
server with an empty database before every single test.

The workhorse is :func:`setup_billpay_world`, which establishes a deliberately
**un-gated** world - a bond in force over the clock date, an ACTIVE client, an
ACTIVE instrument spanning the clock date, an account whose fraud posture is
NORMAL, and no reconciliation period at all - so that each test perturbs
exactly one thing and reaches the rung it is aiming at rather than a gate.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_BUDGET_MONTH, BASE_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    account_adjustment_payload,
    approval_decision_payload,
    benefit_application_status_payload,
    budget_override_payload,
    capacity_determination_payload,
    client_status_payload,
    clock_payload,
    consent_payload,
    coordination_disposition_payload,
    create_account_payload,
    create_authorization_payload,
    create_benefit_application_payload,
    create_budget_category_payload,
    create_client_payload,
    create_coordination_request_payload,
    create_dispute_payload,
    create_family_recipient_payload,
    create_family_report_payload,
    create_fraud_alert_payload,
    create_payee_payload,
    create_payment_payload,
    create_reconciliation_period_payload,
    create_surety_bond_payload,
    fraud_alert_disposition_payload,
    fraud_posture_payload,
    import_statement_line_payload,
    period_status_payload,
    record_decision_payload,
    resolve_dispute_payload,
    settlement_event_payload,
    statement_line_disposition_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_family_recipient_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["fiduciary_manager_headers"]
MANAGER_ALT = TEST_USERS["fiduciary_manager_alt_headers"]
SPECIALIST = TEST_USERS["bill_pay_specialist_headers"]
SPECIALIST_ALT = TEST_USERS["bill_pay_specialist_alt_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
COMPLIANCE_ALT = TEST_USERS["compliance_officer_alt_headers"]


# ===========================================================================
# Tier 1 - primitives
# ===========================================================================


def set_clock(to_iso8601: str = BASE_CLOCK_UTC) -> Dict[str, Any]:
    """Move the logical clock. Performs no sweep of its own."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def run_checkpoint() -> Dict[str, Any]:
    return get_success_data(api_client.run_checkpoint(ADMIN))


def register_bond(**overrides) -> Dict[str, Any]:
    """Register a surety bond. Defaults cover the whole of 2026 with ample
    coverage, so the bond gate passes for every clock instant the suite uses."""
    return get_success_data(
        api_client.create_surety_bond(create_surety_bond_payload(**overrides), ADMIN)
    )


def create_client(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_client(create_client_payload(**overrides), MANAGER)
    )


def record_capacity(client_id: str, determination: str = "RETAINS_CAPACITY", **overrides):
    return get_success_data(
        api_client.record_capacity_determination(
            client_id,
            capacity_determination_payload(determination=determination, **overrides),
            MANAGER,
        )
    )


def change_client_status(client_id: str, to_status: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_client_status(
            client_id, client_status_payload(to_status, **overrides), MANAGER
        )
    )


def create_active_client(
    determination: str = "RETAINS_CAPACITY", **overrides
) -> Dict[str, Any]:
    """Intake -> capacity determination -> ACTIVE."""
    client = create_client(**overrides)
    record_capacity(client["id"], determination=determination)
    return change_client_status(client["id"], "ACTIVE")


def draft_authorization(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_authorization(
            create_authorization_payload(client_id, **overrides), MANAGER
        )
    )


def execute_authorization(authorization_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_authorization_status(
            authorization_id, {"to_status": "ACTIVE"}, MANAGER
        )
    )


def revoke_authorization(authorization_id: str, revocation_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_authorization_status(
            authorization_id,
            {"to_status": "REVOKED", "revocation_reason": revocation_reason},
            MANAGER,
        )
    )


def create_active_authorization(client_id: str, **overrides) -> Dict[str, Any]:
    """Draft an instrument and execute it in one step."""
    authorization = draft_authorization(client_id, **overrides)
    return execute_authorization(authorization["id"])


def create_account(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_account(create_account_payload(client_id, **overrides), MANAGER)
    )


def post_adjustment(
    account_id: str,
    adjustment_type: str,
    amount_cents: int,
    value_date: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.post_account_adjustment(
            account_id,
            account_adjustment_payload(
                adjustment_type, amount_cents, value_date, **overrides
            ),
            headers or SPECIALIST,
        )
    )


def set_fraud_posture(account_id: str, to_posture: str, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_fraud_posture(
            account_id, fraud_posture_payload(to_posture, reason), COMPLIANCE
        )
    )


def create_payee(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_payee(create_payee_payload(client_id, **overrides), SPECIALIST)
    )


def block_payee(payee_id: str, blocked_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.block_payee(payee_id, {"blocked_reason": blocked_reason}, COMPLIANCE)
    )


def create_budget_category(client_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_budget_category(
            create_budget_category_payload(client_id, **overrides), MANAGER
        )
    )


def grant_override(budget_category_id: str, added_cents: int, reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.grant_budget_override(
            budget_category_id, budget_override_payload(added_cents, reason), MANAGER
        )
    )


def open_period(account_id: str, period_month: str = BASE_BUDGET_MONTH) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_reconciliation_period(
            create_reconciliation_period_payload(account_id, period_month), SPECIALIST
        )
    )


def change_period_status(period_id: str, to_status: str, headers=None) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_period_status(
            period_id, period_status_payload(to_status), headers or MANAGER
        )
    )


def close_period(account_id: str = None, period_id: str = None) -> Dict[str, Any]:
    """Walk an OPEN period through IN_REVIEW into CLOSED (or LOCKED, when the
    period has already been reopened once)."""
    assert period_id is not None, "close_period requires a period_id"
    change_period_status(period_id, "IN_REVIEW", SPECIALIST)
    return change_period_status(period_id, "CLOSED", MANAGER)


def open_and_close_period(
    account_id: str, period_month: str = BASE_BUDGET_MONTH
) -> Dict[str, Any]:
    period = open_period(account_id, period_month)
    return close_period(period_id=period["id"])


# --- reads used as setup ---------------------------------------------------


def account_version(account_id: str) -> int:
    """Re-read the account's live version for the payment OCC token."""
    return get_success_data(api_client.get_account(account_id, MANAGER))["version"]


def read_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_account(account_id, MANAGER))


def read_payment(payment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_payment(payment_id, MANAGER))


def read_budget_category(budget_category_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_budget_category(budget_category_id, MANAGER))


def read_bond(bond_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_surety_bond(bond_id, MANAGER))


def read_payee(payee_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_payee(payee_id, MANAGER))


def read_period(period_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_reconciliation_period(period_id, MANAGER))


def read_authorization(authorization_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_authorization(authorization_id, MANAGER))


def read_client(client_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_client(client_id, MANAGER))


def read_fraud_alert(alert_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_fraud_alert(alert_id, MANAGER))


def read_dispute(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_dispute(dispute_id, MANAGER))


def read_benefit_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_benefit_application(application_id, MANAGER))


def read_family_recipient(recipient_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_family_recipient(recipient_id, MANAGER))


def recipient_version(recipient_id: str) -> int:
    return read_family_recipient(recipient_id)["version"]


def read_family_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_family_report(report_id, MANAGER))


def read_coordination_request(request_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_coordination_request(request_id, MANAGER))


def read_statement_line(statement_line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_statement_line(statement_line_id, MANAGER))


def period_version(period_id: str) -> int:
    return read_period(period_id)["version"]


def list_ledger_entries(account_id: Optional[str] = None, **filters) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    if account_id is not None:
        params["account_id"] = account_id
    params.update(filters)
    response = api_client.list_ledger_entries(MANAGER, params=params)
    return get_success_data(response)


def list_payments(**filters) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    params.update(filters)
    response = api_client.list_payments(MANAGER, params=params)
    return get_success_data(response)


# ===========================================================================
# Tier 2 - the clean, un-gated bill-pay world
# ===========================================================================


def setup_billpay_world(
    clock_iso: str = BASE_CLOCK_UTC,
    with_bond: bool = True,
    bond_overrides: Optional[Dict[str, Any]] = None,
    capacity: str = "RETAINS_CAPACITY",
    client_overrides: Optional[Dict[str, Any]] = None,
    scope_tier: str = "FULL_AGENCY",
    authorization_overrides: Optional[Dict[str, Any]] = None,
    opening_balance_cents: int = TEST_DEFAULTS["OPENING_BALANCE_CENTS"],
    account_overrides: Optional[Dict[str, Any]] = None,
    payee_type: str = "RECURRING_BILLER",
    payee_overrides: Optional[Dict[str, Any]] = None,
    budget_month: str = BASE_BUDGET_MONTH,
    allocation_cents: int = TEST_DEFAULTS["ALLOCATION_CENTS"],
    budget_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a world in which every write gate passes.

    - the logical clock sits at ``clock_iso``;
    - a surety bond is IN_FORCE across the clock date (bond gate passes);
    - the client is ACTIVE with a capacity finding on file;
    - one instrument is ACTIVE and spans the clock date (authorization gate
      passes) at ``scope_tier``;
    - the account's fraud posture is NORMAL (fraud-freeze gate passes);
    - **no reconciliation period exists**, so the reconciliation-freeze gate
      passes for want of a receiving period.

    A test that wants a gate to fire perturbs exactly one of those.
    """
    set_clock(clock_iso)

    bond = None
    if with_bond:
        bond = register_bond(**(bond_overrides or {}))

    client = create_active_client(determination=capacity, **(client_overrides or {}))
    authorization = create_active_authorization(
        client["id"], scope_tier=scope_tier, **(authorization_overrides or {})
    )
    account = create_account(
        client["id"],
        opening_balance_cents=opening_balance_cents,
        **(account_overrides or {}),
    )
    payee = create_payee(client["id"], payee_type=payee_type, **(payee_overrides or {}))
    budget_category = create_budget_category(
        client["id"],
        budget_month=budget_month,
        allocation_cents=allocation_cents,
        **(budget_overrides or {}),
    )
    return {
        "bond": bond,
        "client": client,
        "authorization": authorization,
        "account": account,
        "payee": payee,
        "budget_category": budget_category,
    }


def add_payee(world: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Register a second payee for the world's client."""
    defaults = {"payee_name": "Northside Gas", "remittance_reference": "NG-31"}
    defaults.update(overrides)
    return create_payee(world["client"]["id"], **defaults)


# ===========================================================================
# Tier 3 - payment lifecycle shortcuts
# ===========================================================================


def schedule_payment(
    world: Dict[str, Any],
    amount_cents: int = TEST_DEFAULTS["PAYMENT_AMOUNT_CENTS"],
    channel: str = "ACH",
    payee: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    **extra,
) -> Dict[str, Any]:
    """Schedule one payment, re-reading the account's live OCC token first."""
    payload = create_payment_payload(
        world["account"]["id"],
        (payee or world["payee"])["id"],
        world["authorization"]["id"],
        world["budget_category"]["id"],
        amount_cents,
        account_version(world["account"]["id"]),
        channel=channel,
        **extra,
    )
    return get_success_data(api_client.create_payment(payload, headers or SPECIALIST))


def payment_request(
    world: Dict[str, Any],
    amount_cents: int = TEST_DEFAULTS["PAYMENT_AMOUNT_CENTS"],
    channel: str = "ACH",
    payee: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_account_version: Optional[int] = None,
    **extra,
):
    """Issue a payment create and hand back the raw response, for tests that
    expect a refusal."""
    payload = create_payment_payload(
        world["account"]["id"],
        (payee or world["payee"])["id"],
        world["authorization"]["id"],
        world["budget_category"]["id"],
        amount_cents,
        (
            expected_account_version
            if expected_account_version is not None
            else account_version(world["account"]["id"])
        ),
        channel=channel,
        **extra,
    )
    return api_client.create_payment(payload, headers or SPECIALIST)


def approve_payment(payment_id: str, headers: Optional[Dict[str, str]] = None, **overrides):
    """Second control APPROVE. Defaults to the compliance officer, who is a
    different natural person from the preparing specialist."""
    return get_success_data(
        api_client.decide_payment_approval(
            payment_id,
            approval_decision_payload("APPROVE", **overrides),
            headers or COMPLIANCE,
        )
    )


def reject_payment(payment_id: str, headers: Optional[Dict[str, str]] = None, **overrides):
    return get_success_data(
        api_client.decide_payment_approval(
            payment_id,
            approval_decision_payload("REJECT", **overrides),
            headers or COMPLIANCE,
        )
    )


def release_payment(payment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.release_payment(payment_id, SPECIALIST))


def settle_payment(payment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_settlement_event(
            payment_id, settlement_event_payload("SETTLE"), SPECIALIST
        )
    )


def return_payment(payment_id: str, return_reason: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_settlement_event(
            payment_id,
            settlement_event_payload("RETURN", return_reason=return_reason),
            SPECIALIST,
        )
    )


def cancel_payment(payment_id: str, reason: str = "No longer required.", headers=None):
    return get_success_data(
        api_client.cancel_payment(payment_id, {"reason": reason}, headers or SPECIALIST)
    )


def schedule_and_release(world: Dict[str, Any], amount_cents: int = 80000, **kwargs):
    """Schedule a payment below the dual-control threshold and release it, so
    the settlement axis reads IN_FLIGHT."""
    payment = schedule_payment(world, amount_cents=amount_cents, **kwargs)
    return release_payment(payment["id"])


def schedule_release_and_settle(world: Dict[str, Any], amount_cents: int = 80000, **kwargs):
    """Schedule, release and settle a payment, leaving it SETTLED with two
    ledger entries on the account."""
    payment = schedule_payment(world, amount_cents=amount_cents, **kwargs)
    release_payment(payment["id"])
    return settle_payment(payment["id"])


# ===========================================================================
# Tier 4 - fraud, dispute and reconciliation composites
# ===========================================================================


def raise_fraud_alert(
    account_id: str,
    payment_id: str,
    reason_code: str = "UNRECOGNIZED_PAYEE",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_fraud_alert(
            create_fraud_alert_payload(account_id, payment_id, reason_code, **overrides),
            headers or COMPLIANCE,
        )
    )


def dispose_fraud_alert(alert_id: str, action: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispose_fraud_alert(
            alert_id, fraud_alert_disposition_payload(action, **overrides), COMPLIANCE
        )
    )


def acknowledge_fraud_alert(alert_id: str, **overrides) -> Dict[str, Any]:
    return dispose_fraud_alert(alert_id, "ACKNOWLEDGE", **overrides)


def confirm_fraud_alert(alert_id: str, **overrides) -> Dict[str, Any]:
    return dispose_fraud_alert(alert_id, "CONFIRM_FRAUD", **overrides)


def file_dispute(
    payment_id: str,
    disputed_amount_cents: int,
    reason_code: str = "UNAUTHORIZED",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_dispute(
            create_dispute_payload(payment_id, disputed_amount_cents, reason_code),
            headers or COMPLIANCE,
        )
    )


def apply_provisional_credit(dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.apply_provisional_credit(dispute_id, COMPLIANCE))


def resolve_dispute(dispute_id: str, outcome: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.resolve_dispute(
            dispute_id, resolve_dispute_payload(outcome, **overrides), COMPLIANCE
        )
    )


def import_statement_line(
    period_id: str, external_ref: str, amount_cents: int, line_date: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.import_statement_line(
            period_id,
            import_statement_line_payload(external_ref, amount_cents, line_date, **overrides),
            SPECIALIST,
        )
    )


def dispose_statement_line(
    statement_line_id: str,
    action: str,
    expected_period_version: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispose_statement_line(
            statement_line_id,
            statement_line_disposition_payload(
                action, expected_period_version, **overrides
            ),
            headers or SPECIALIST,
        )
    )


def setup_period_with_deposit_and_line(
    line_amount_cents: int = 100000,
    deposit_amount_cents: int = 250000,
    value_date: str = "2026-06-01",
    line_date: str = "2026-06-01",
    external_ref: str = "BK-0001",
) -> Dict[str, Any]:
    """An ACTIVE client with an account, an OPEN 2026-06 period holding one
    DEPOSIT ledger entry, and one imported statement line awaiting disposition.

    No surety bond is needed - no disbursement happens here - but one is
    registered anyway so the adjustment endpoint's bond gate passes.
    """
    set_clock(BASE_CLOCK_UTC)
    register_bond()
    client = create_active_client()
    account = create_account(client["id"])
    period = open_period(account["id"], BASE_BUDGET_MONTH)
    post_adjustment(
        account["id"], "DEPOSIT", deposit_amount_cents, value_date, memo="Pension deposit."
    )
    entries = list_ledger_entries(account["id"])
    line = import_statement_line(
        period["id"],
        external_ref,
        line_amount_cents,
        line_date,
        line_description="Unidentified credit",
    )
    return {
        "client": client,
        "account": account,
        "period": period,
        "ledger_entries": entries,
        "statement_line": line,
    }


# ===========================================================================
# Tier 5 - benefits, family reporting and care-team coordination
# ===========================================================================


def draft_benefit_application(
    client_id: str, authorization_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_benefit_application(
            create_benefit_application_payload(client_id, authorization_id, **overrides),
            MANAGER,
        )
    )


def submit_benefit_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_benefit_application_status(
            application_id, benefit_application_status_payload("SUBMIT"), MANAGER
        )
    )


def appeal_benefit_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.change_benefit_application_status(
            application_id, benefit_application_status_payload("APPEAL"), MANAGER
        )
    )


def record_benefit_decision(
    application_id: str, outcome: str, decision_date: str, account_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_benefit_decision(
            application_id,
            record_decision_payload(outcome, decision_date, account_id, **overrides),
            MANAGER,
        )
    )


def setup_submitted_application(
    program: str = "MEDICAID",
    asserted_monthly_income_cents: int = 120000,
    resource_items: Optional[List[Dict[str, Any]]] = None,
    clock_iso: str = BASE_CLOCK_UTC,
    opening_balance_cents: int = TEST_DEFAULTS["OPENING_BALANCE_CENTS"],
) -> Dict[str, Any]:
    """ACTIVE client + ACTIVE FULL_AGENCY instrument + account + a SUBMITTED
    benefit application."""
    set_clock(clock_iso)
    client = create_active_client()
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    account = create_account(client["id"], opening_balance_cents=opening_balance_cents)
    application = draft_benefit_application(
        client["id"],
        authorization["id"],
        program=program,
        asserted_monthly_income_cents=asserted_monthly_income_cents,
        resource_items=resource_items,
    )
    application = submit_benefit_application(application["id"])
    return {
        "client": client,
        "authorization": authorization,
        "account": account,
        "application": application,
    }


def enrol_family_recipient(
    client_id: str, authorization_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_family_recipient(
            create_family_recipient_payload(client_id, authorization_id, **overrides),
            MANAGER,
        )
    )


def record_consent(
    recipient_id: str,
    permitted_categories: List[str],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.record_consent(
            recipient_id, consent_payload(permitted_categories), headers or MANAGER
        )
    )


def generate_family_report(
    recipient_id: str,
    report_month: str,
    expected_recipient_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    version = (
        expected_recipient_version
        if expected_recipient_version is not None
        else recipient_version(recipient_id)
    )
    return get_success_data(
        api_client.create_family_report(
            create_family_report_payload(recipient_id, report_month, version, **overrides),
            headers or make_family_recipient_headers(recipient_id),
        )
    )


def setup_consented_recipient(
    permitted_categories: Optional[List[str]] = None,
    clock_iso: str = BASE_CLOCK_UTC,
    opening_balance_cents: int = TEST_DEFAULTS["OPENING_BALANCE_CENTS"],
    with_account: bool = True,
    consent_as_client: bool = True,
) -> Dict[str, Any]:
    """ACTIVE client with RETAINS_CAPACITY, ACTIVE FULL_AGENCY instrument, one
    account, and one FamilyRecipient whose subscription is ACTIVE.

    Consent is recorded by the ``Client`` themselves, whose ``X-User-ID`` is
    that client's own row id - a different identity from every operator in
    this suite and from the recipient's own identity.
    """
    set_clock(clock_iso)
    client = create_active_client()
    authorization = create_active_authorization(client["id"], scope_tier="FULL_AGENCY")
    account = (
        create_account(client["id"], opening_balance_cents=opening_balance_cents)
        if with_account
        else None
    )
    recipient = enrol_family_recipient(client["id"], authorization["id"])
    categories = (
        permitted_categories if permitted_categories is not None else ["BILL_PAY", "BALANCES"]
    )
    recipient = record_consent(
        recipient["id"],
        categories,
        headers=make_client_headers(client["id"]) if consent_as_client else MANAGER,
    )
    return {
        "client": client,
        "authorization": authorization,
        "account": account,
        "recipient": recipient,
    }


def open_coordination_request(
    client_id: str,
    assigned_member_user_id: str,
    tier: str = "ROUTINE",
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_coordination_request(
            create_coordination_request_payload(
                client_id, assigned_member_user_id, tier=tier, **overrides
            ),
            headers or MANAGER,
        )
    )


def dispose_coordination_request(
    request_id: str, action: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api_client.dispose_coordination_request(
            request_id, coordination_disposition_payload(action, **overrides), headers or MANAGER
        )
    )
