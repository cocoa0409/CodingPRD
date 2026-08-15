"""Composite setup helpers.

The pricing workflow behind most PRD rules is long: a rate sheet only becomes
EFFECTIVE after draft -> submit -> approve -> schedule -> four channel
deployments -> four on-time disclosures -> clock advance -> activate. These
helpers encapsulate that plumbing so tests can focus on assertions. Every
helper builds its preconditions from scratch against a fresh server and uses
the lenient `get_success_data` validator so setup failures surface clearly.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_bundle_payload,
    create_enrollment_payload,
    create_funding_curve_payload,
    create_migration_batch_payload,
    create_product_payload,
    create_promo_payload,
    create_rate_sheet_payload,
    create_repricing_cycle_payload,
    create_scan_payload,
    single_tier,
)
from .test_users import TEST_USERS, make_banker_headers

ANALYST = TEST_USERS["analyst_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
TREASURY = TEST_USERS["treasury_headers"]
BANKER = TEST_USERS["banker_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
CHANNEL = TEST_USERS["channel_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(date: str):
    """Advance the logical clock to `date` (YYYY-MM-DD) at 00:00:00Z."""
    resp = api_client.set_clock({"to_iso8601": f"{date}T00:00:00Z"}, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Products / funding curves / scans
# ---------------------------------------------------------------------------

def create_product(**overrides) -> dict:
    resp = api_client.create_deposit_product(create_product_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_funding_curve(**overrides) -> dict:
    resp = api_client.create_funding_curve(create_funding_curve_payload(**overrides), TREASURY)
    return get_success_data(resp)


def create_scan(**overrides) -> dict:
    resp = api_client.create_competitor_rate_scan(create_scan_payload(**overrides), ANALYST)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Rate sheet lifecycle
# ---------------------------------------------------------------------------

def create_draft_sheet(product_id: str, **overrides) -> dict:
    resp = api_client.create_rate_sheet(create_rate_sheet_payload(product_id, **overrides), ANALYST)
    return get_success_data(resp)


def submit_sheet(sheet_id: str) -> dict:
    return get_success_data(api_client.submit_rate_sheet(sheet_id, ANALYST))


def review_sheet(sheet_id: str, decision: str, reason: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.review_decision_rate_sheet(sheet_id, payload, COMMITTEE))


def schedule_sheet(sheet_id: str) -> dict:
    return get_success_data(api_client.schedule_rate_sheet(sheet_id, ANALYST))


def list_sheet_deployments(sheet_id: str) -> List[dict]:
    data = get_success_data(api_client.list_rate_deployments(CHANNEL, params={"sheet_id": sheet_id}))
    assert isinstance(data, list)
    return data


def list_sheet_notices(sheet_id: str) -> List[dict]:
    data = get_success_data(api_client.list_disclosure_notices(COMPLIANCE, params={"sheet_id": sheet_id}))
    assert isinstance(data, list)
    return data


def list_account_notices(account_id: str) -> List[dict]:
    data = get_success_data(api_client.list_disclosure_notices(COMPLIANCE, params={"account_id": account_id}))
    assert isinstance(data, list)
    return data


def deploy_all(sheet_id: str) -> List[dict]:
    """DEPLOY every deployment row of a sheet; returns the deployment rows."""
    deployments = list_sheet_deployments(sheet_id)
    for row in deployments:
        get_success_data(api_client.execute_rate_deployment(row["id"], {"action": "DEPLOY"}, CHANNEL))
    return deployments


def send_all_notices(sheet_id: str) -> List[dict]:
    """SEND every sheet-level PRE_CHANGE notice; returns the notice rows."""
    notices = list_sheet_notices(sheet_id)
    for row in notices:
        get_success_data(api_client.resolve_disclosure_notice(row["id"], {"action": "SEND"}, COMPLIANCE))
    return notices


def waive_all_notices(sheet_id: str, reason: str = "regulatory waiver") -> List[dict]:
    notices = list_sheet_notices(sheet_id)
    for row in notices:
        get_success_data(api_client.resolve_disclosure_notice(
            row["id"], {"action": "WAIVE", "reason": reason}, COMPLIANCE))
    return notices


def promote_sheet_to_scheduled(sheet_id: str) -> dict:
    """submit -> APPROVE -> schedule. Returns the SCHEDULED sheet."""
    submit_sheet(sheet_id)
    review_sheet(sheet_id, "APPROVE")
    return schedule_sheet(sheet_id)


def create_effective_sheet(product_id: Optional[str] = None,
                           market_code: str = "US-WEST",
                           effective_date: str = "2026-08-15",
                           tiers: Optional[list] = None,
                           activate_date: Optional[str] = None,
                           product_overrides: Optional[dict] = None,
                           sheet_overrides: Optional[dict] = None) -> Dict:
    """Full pipeline to EFFECTIVE: (product) -> DRAFT -> submit -> APPROVE ->
    schedule -> all 4 deployments DEPLOYED -> all 4 PRE_CHANGE notices SENT
    on time (sent before the clock reaches required_by_date) -> clock advance
    -> activate. Returns {"product": ..., "sheet": <EFFECTIVE sheet>}.
    """
    if product_id is None:
        product_id = create_product(**(product_overrides or {}))["id"]
    sheet_kwargs = dict(sheet_overrides or {})
    sheet_kwargs.setdefault("market_code", market_code)
    sheet_kwargs.setdefault("effective_date", effective_date)
    if tiers is not None:
        sheet_kwargs["tiers"] = tiers
    sheet = create_draft_sheet(product_id, **sheet_kwargs)
    promote_sheet_to_scheduled(sheet["id"])
    deploy_all(sheet["id"])
    send_all_notices(sheet["id"])
    set_clock(activate_date or effective_date)
    sheet = get_success_data(api_client.activate_rate_sheet(sheet["id"], ANALYST))
    return {"product_id": product_id, "sheet": sheet}


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def open_account(product_id: str, market_code: str = "US-WEST",
                 opening_balance_cents: int = 1_000_000,
                 customer_ref: str = "CUST-1", channel: str = "ONLINE",
                 headers=None) -> dict:
    payload = create_account_payload(
        product_id,
        market_code=market_code,
        opening_balance_cents=opening_balance_cents,
        customer_ref=customer_ref,
        channel=channel,
    )
    return get_success_data(api_client.create_deposit_account(payload, headers or BANKER))


def patch_balance(account_id: str, expected_account_version: int, balance_cents: int) -> dict:
    payload = {"expected_account_version": expected_account_version,
               "balance_cents": balance_cents}
    return get_success_data(api_client.patch_deposit_account(account_id, payload, BANKER))


def account_action(account_id: str, action: str, promo_offer_id: Optional[str] = None,
                   headers=None) -> dict:
    payload = {"action": action}
    if promo_offer_id is not None:
        payload["promo_offer_id"] = promo_offer_id
    return get_success_data(api_client.deposit_account_action(account_id, payload, headers or BANKER))


# ---------------------------------------------------------------------------
# Promotional offers
# ---------------------------------------------------------------------------

def create_promo(product_id: str, publish: bool = True, **overrides) -> dict:
    resp = api_client.create_promotional_offer(create_promo_payload(product_id, **overrides), ANALYST)
    offer = get_success_data(resp)
    if publish:
        offer = get_success_data(api_client.publish_promotional_offer(offer["id"], ANALYST))
    return offer


def enroll_promo(account_id: str, promo_offer_id: str, headers=None) -> dict:
    return account_action(account_id, "ENROLL_PROMO", promo_offer_id=promo_offer_id,
                          headers=headers)


# ---------------------------------------------------------------------------
# Exception pricing requests
# ---------------------------------------------------------------------------

def create_exception(account_id: str, sheet_id: str, requested_rate_bp: int,
                     term_days: int = 60, justification_doc_ref: Optional[str] = None,
                     submitter_user_id: str = "banker-1") -> dict:
    payload = {
        "account_id": account_id,
        "sheet_id": sheet_id,
        "requested_rate_bp": requested_rate_bp,
        "term_days": term_days,
    }
    if justification_doc_ref is not None:
        payload["justification_doc_ref"] = justification_doc_ref
    resp = api_client.create_exception_pricing_request(
        payload, make_banker_headers(submitter_user_id))
    return get_success_data(resp)


def decide_exception(request_id: str, decision: str, role: str = "BranchBanker",
                     user_id: str = "banker-2") -> dict:
    from .test_users import make_committee_headers
    headers = (make_committee_headers(user_id) if role == "PricingCommittee"
               else make_banker_headers(user_id))
    return get_success_data(api_client.decide_exception_pricing_request(
        request_id, {"decision": decision}, headers))


# ---------------------------------------------------------------------------
# Bundles and enrollments
# ---------------------------------------------------------------------------

def create_bundle(**overrides) -> dict:
    return get_success_data(api_client.create_relationship_bundle(create_bundle_payload(**overrides), ADMIN))


def create_enrollment(bundle_id: str, customer_ref: str) -> dict:
    return get_success_data(api_client.create_bundle_enrollment(
        create_enrollment_payload(bundle_id, customer_ref), ADMIN))


# ---------------------------------------------------------------------------
# Migration batches
# ---------------------------------------------------------------------------

def create_migration_batch(source_sheet_id: str, target_sheet_id: str) -> dict:
    return get_success_data(api_client.create_migration_batch(
        create_migration_batch_payload(source_sheet_id, target_sheet_id), ADMIN))


def execute_migration(batch_id: str, action: str = "EXECUTE") -> dict:
    return get_success_data(api_client.execute_migration_batch(batch_id, {"action": action}, ADMIN))


# ---------------------------------------------------------------------------
# Repricing cycles
# ---------------------------------------------------------------------------

def create_cycle(product_id: str, market_code: str = "US-WEST", cadence_days: int = 30) -> dict:
    return get_success_data(api_client.create_repricing_cycle(
        create_repricing_cycle_payload(product_id, market_code=market_code, cadence_days=cadence_days),
        ANALYST))


def find_cycle(product_id: str, market_code: str) -> dict:
    data = get_success_data(api_client.list_repricing_cycles(
        ANALYST, params={"product_id": product_id, "market_code": market_code}))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one cycle for ({product_id}, {market_code}), got {len(data)}")
    return data[0]


# ---------------------------------------------------------------------------
# Composite: second sheet superseding an incumbent
# ---------------------------------------------------------------------------

def supersede_sheet(product_id: str, market_code: str, old_sheet: dict,
                    new_effective_date: str, new_tiers: list,
                    activate_date: Optional[str] = None, **sheet_overrides) -> dict:
    """Create and fully activate a successor sheet for the same pair, which
    supersedes `old_sheet` at activation. Returns the EFFECTIVE new sheet."""
    return create_effective_sheet(
        product_id=product_id, market_code=market_code,
        effective_date=new_effective_date, tiers=new_tiers,
        activate_date=activate_date or new_effective_date,
        **sheet_overrides)["sheet"]
