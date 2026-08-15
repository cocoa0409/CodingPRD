"""Composite setup helpers for the Positive Pay test suite.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build preconditions from scratch using only
PRD-declared endpoints. Setup calls use get_success_data so failures surface as
clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_ach_rule_payload,
    create_enrollment_payload,
    create_enrollment_user_payload,
    create_account_payload,
    create_issue_file_payload,
    create_liability_case_payload,
    create_presented_item_payload,
    create_training_session_payload,
    make_check_row,
)
from .test_users import (
    TEST_USERS,
    make_bank_ops_headers,
    make_bank_treasury_manager_headers,
    make_customer_admin_headers,
    make_customer_manager_headers,
    make_customer_decision_maker_headers,
    make_customer_viewer_headers,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]

TRAINING_START = "2026-08-01T09:00:00Z"
TRAINING_END = "2026-08-01T10:00:00Z"

_ROLE_HEADER_BUILDERS = {
    "ADMIN": make_customer_admin_headers,
    "MANAGER": make_customer_manager_headers,
    "DECISION_MAKER": make_customer_decision_maker_headers,
    "VIEWER": make_customer_viewer_headers,
}


# ----------------------------------------------------------------------
# Tier 1: state progression primitives
# ----------------------------------------------------------------------

def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, BANK_OPS))


def create_enrollment(business_name="Test Co", tier="POSITIVE_PAY",
                      default_decision="PAY", **extra) -> dict:
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(business_name=business_name, tier=tier,
                                  default_decision=default_decision, **extra),
        BANK_MGR))


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, BANK_MGR))


def add_user(enrollment_id, display_name, user_role) -> dict:
    return get_success_data(api_client.create_enrollment_user(
        create_enrollment_user_payload(enrollment_id, display_name=display_name,
                                       user_role=user_role), BANK_MGR))


def create_account(enrollment_id, account_number="800001", **extra) -> dict:
    return get_success_data(api_client.create_account(
        create_account_payload(enrollment_id, account_number=account_number,
                               **extra), BANK_MGR))


def get_account(account_id) -> dict:
    return get_success_data(api_client.get_account(account_id, BANK_OPS))


def schedule_training(enrollment_id, trainer_id="tr-1", start=TRAINING_START,
                      end=TRAINING_END) -> dict:
    return get_success_data(api_client.create_training_session(
        create_training_session_payload(enrollment_id, trainer_id=trainer_id,
                                        scheduled_start=start, scheduled_end=end),
        BANK_OPS))


def complete_training(enrollment_id, attendee_user_id, trainer_id="tr-1",
                      start=TRAINING_START, end=TRAINING_END) -> dict:
    """Schedule + complete a training session; satisfies the activation gate."""
    sess = schedule_training(enrollment_id, trainer_id, start, end)
    return get_success_data(api_client.complete_training_session(
        sess["id"], [attendee_user_id], BANK_OPS))


def activate_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.activate_enrollment(enrollment_id, BANK_MGR))


# ----------------------------------------------------------------------
# Tier 2: enrollment bundle (enrollment + users + training + activation)
# ----------------------------------------------------------------------

def create_active_enrollment(business_name="Co", tier="POSITIVE_PAY",
                             default_decision="PAY", user_roles=("ADMIN",),
                             with_account=True, account_number="800001",
                             trainer_id="tr-1", training_start=TRAINING_START,
                             training_end=TRAINING_END,
                             payment_review_threshold_cents=None,
                             **enrollment_extra) -> dict:
    """Create an ACTIVE enrollment with users, one COMPLETED training session,
    and (optionally) one account. Returns a bundle:
      enrollment (post-activation body), account or None,
      users {role: EnrollmentUser}, headers {role: per-instance headers}.
    payment_review_threshold_cents is an account-level knob (PRD §3.2) and is
    forwarded to the account payload, never to the enrollment payload.
    """
    created = create_enrollment(business_name, tier, default_decision,
                                **enrollment_extra)
    users, headers = {}, {}
    for role in user_roles:
        user = add_user(created["id"], f"{role} user", role)
        users[role] = user
        headers[role] = _ROLE_HEADER_BUILDERS[role](user["id"])
    complete_training(created["id"], users[user_roles[0]]["id"],
                      trainer_id=trainer_id, start=training_start,
                      end=training_end)
    activated = activate_enrollment(created["id"])
    account_extra = (
        {"payment_review_threshold_cents": payment_review_threshold_cents}
        if payment_review_threshold_cents is not None else {})
    account = (create_account(created["id"], account_number, **account_extra)
               if with_account else None)
    return {"enrollment": activated, "account": account,
            "users": users, "headers": headers}


# ----------------------------------------------------------------------
# Tier 3: issue files, checks, presented items
# ----------------------------------------------------------------------

def upload_checks(enrollment_id, account_id, file_reference, rows,
                  uploader_headers) -> dict:
    return get_success_data(api_client.upload_issue_file(
        create_issue_file_payload(enrollment_id, account_id, file_reference,
                                  rows), uploader_headers))


def list_checks(params) -> list:
    return get_success_data(api_client.list_issued_checks(BANK_OPS, params=params))


def get_check_by_number(account_id, check_number) -> dict:
    checks = list_checks({"account_id": account_id,
                          "check_number": str(check_number)})
    assert checks, f"no issued check {check_number} on account {account_id}"
    return checks[0]


def present_item(account_id, check_number="1", amount_cents=100,
                 payee_name_raw="P", channel="TELLER", presented_at=None,
                 idempotency_key=None) -> dict:
    overrides = {"check_number": str(check_number), "amount_cents": amount_cents,
                 "payee_name_raw": payee_name_raw, "channel": channel}
    if presented_at is not None:
        overrides["presented_at"] = presented_at
    if idempotency_key is not None:
        overrides["idempotency_key"] = idempotency_key
    return get_success_data(api_client.ingest_presented_item(
        create_presented_item_payload(account_id, **overrides), BANK_OPS))


def get_presented_item(item_id) -> dict:
    return get_success_data(api_client.get_presented_item(item_id, BANK_OPS))


def get_exception(exception_id) -> dict:
    return get_success_data(api_client.get_exception(exception_id, BANK_OPS))


def decide(exception_id, decision, headers) -> dict:
    return get_success_data(api_client.decide_exception(
        exception_id, decision, headers))


def daily_sweep(enrollment_id=None) -> dict:
    payload = {"kind": "DAILY_SWEEP"}
    if enrollment_id is not None:
        payload["enrollment_id"] = enrollment_id
    return get_success_data(api_client.create_ops_run(payload, BANK_OPS))


def monthly_billing(enrollment_id, period) -> dict:
    return get_success_data(api_client.create_ops_run(
        {"kind": "MONTHLY_BILLING", "enrollment_id": enrollment_id,
         "period": period}, BANK_OPS))


def fee_statement(enrollment_id, period) -> dict:
    return get_success_data(api_client.get_fee_statement(enrollment_id, period,
                                                         BANK_MGR))


def find_fee_entry(exception_id=None, enrollment_id=None, fee_type=None) -> dict:
    params = {}
    if exception_id is not None:
        params["exception_id"] = exception_id
    if enrollment_id is not None:
        params["enrollment_id"] = enrollment_id
    if fee_type is not None:
        params["fee_type"] = fee_type
    entries = get_success_data(api_client.list_fee_entries(BANK_OPS, params=params))
    assert entries, f"no fee entry found for {params}"
    return entries[0]


# ----------------------------------------------------------------------
# Tier 4: domain composites
# ----------------------------------------------------------------------

def setup_open_exception(tier="REVERSE_POSITIVE_PAY", default_decision="PAY",
                         business_name="ExCo", account_number="900001",
                         check_number="1", amount_cents=100,
                         payee_name_raw="P", presented_at="2026-08-03T10:00:00Z",
                         user_roles=("ADMIN", "DECISION_MAKER"),
                         **enrollment_extra) -> dict:
    """ACTIVE enrollment + one ingested item held as an OPEN exception.
    Bundle gains: item, exception_id, exception."""
    bundle = create_active_enrollment(business_name, tier, default_decision,
                                      user_roles=user_roles,
                                      account_number=account_number,
                                      **enrollment_extra)
    item = present_item(bundle["account"]["id"], check_number, amount_cents,
                        payee_name_raw, presented_at=presented_at)
    assert item["status"] == "EXCEPTION_HELD", (
        f"setup expected EXCEPTION_HELD, got {item['status']} "
        f"({item.get('match_result')})")
    bundle["item"] = item
    bundle["exception_id"] = item["exception_id"]
    bundle["exception"] = get_exception(item["exception_id"])
    return bundle


def setup_reverse_tier_exceptions(n, default_decision="RETURN",
                                  business_name="RevCo", account_number="910001",
                                  clock="2026-08-05T09:00:00Z",
                                  user_roles=("ADMIN",),
                                  first_check_number=1) -> dict:
    """ACTIVE REVERSE-tier enrollment with n items ingested at `clock`, each
    becoming a REVERSE_REVIEW OPEN exception with a provisional EXCEPTION_FEE.
    Bundle gains: items, exception_ids."""
    bundle = create_active_enrollment(business_name, "REVERSE_POSITIVE_PAY",
                                      default_decision, user_roles=user_roles,
                                      account_number=account_number)
    set_clock(clock)
    items, exception_ids = [], []
    for i in range(n):
        item = present_item(bundle["account"]["id"],
                            str(first_check_number + i), 100, f"P{i + 1}")
        assert item["status"] == "EXCEPTION_HELD"
        items.append(item)
        exception_ids.append(item["exception_id"])
    bundle["items"] = items
    bundle["exception_ids"] = exception_ids
    return bundle


def setup_paid_item(amount_cents, payee="X CO", tier="POSITIVE_PAY",
                    business_name="PayCo", account_number="920001",
                    check_number="1", issue_date="2026-08-01",
                    presented_at=None, set_clock_to=None,
                    user_roles=("ADMIN", "DECISION_MAKER"),
                    **enrollment_extra) -> dict:
    """ACTIVE enrollment + one issued check + clean presentment -> PAID item.
    Bundle gains: check, item."""
    bundle = create_active_enrollment(business_name, tier, "PAY",
                                      user_roles=user_roles,
                                      account_number=account_number,
                                      **enrollment_extra)
    upload_checks(bundle["enrollment"]["id"], bundle["account"]["id"], "F-1",
                  [make_check_row(check_number, amount_cents, payee, issue_date)],
                  bundle["headers"]["ADMIN"])
    if set_clock_to is not None:
        set_clock(set_clock_to)
    item = present_item(bundle["account"]["id"], check_number, amount_cents,
                        payee, presented_at=presented_at)
    assert item["status"] == "PAID", (
        f"setup expected PAID, got {item['status']} ({item.get('match_result')})")
    bundle["check"] = get_check_by_number(bundle["account"]["id"], check_number)
    bundle["item"] = item
    return bundle


def setup_liability_case(amount_cents, claim_reason="FORGED_SIGNATURE",
                         business_name="CaseCo", account_number="930001",
                         **extra) -> dict:
    """PAID item + LiabilityCase in FILED status. Bundle gains: case."""
    bundle = setup_paid_item(amount_cents, business_name=business_name,
                             account_number=account_number, **extra)
    case = get_success_data(api_client.file_liability_case(
        create_liability_case_payload(bundle["item"]["id"],
                                      claim_reason=claim_reason),
        bundle["headers"]["DECISION_MAKER"]))
    assert case["status"] == "FILED"
    bundle["case"] = case
    return bundle


def setup_case_under_review(amount_cents, claim_reason="FORGED_SIGNATURE",
                            bank_ops_user_id="bank-ops-1",
                            business_name="CaseCo", account_number="930001",
                            **extra) -> dict:
    """PAID item + LiabilityCase moved FILED -> UNDER_REVIEW by BankOps."""
    bundle = setup_liability_case(amount_cents, claim_reason, business_name,
                                  account_number, **extra)
    case = get_success_data(api_client.start_case_review(
        bundle["case"]["id"], make_bank_ops_headers(bank_ops_user_id)))
    assert case["status"] == "UNDER_REVIEW"
    bundle["case"] = case
    return bundle


# ----------------------------------------------------------------------
# Tier 5: ACH rules
# ----------------------------------------------------------------------

def create_ach_rule(account_id, uploader_headers, rule_type="BLOCK",
                    originator_company_id="ORG1", sec_code="CCD",
                    max_amount_cents=None, effective_start_date="2026-08-01",
                    effective_end_date=None) -> dict:
    overrides = {"rule_type": rule_type,
                 "originator_company_id": originator_company_id,
                 "sec_code": sec_code,
                 "effective_start_date": effective_start_date}
    if max_amount_cents is not None:
        overrides["max_amount_cents"] = max_amount_cents
    if effective_end_date is not None:
        overrides["effective_end_date"] = effective_end_date
    return get_success_data(api_client.create_ach_rule(
        create_ach_rule_payload(account_id, **overrides), uploader_headers))
