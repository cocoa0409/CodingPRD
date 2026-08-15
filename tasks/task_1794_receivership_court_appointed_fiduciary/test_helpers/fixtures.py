"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API
(each test runs against a freshly restarted server). Lenient get_success_data
is used internally so setup failures surface as clear "Setup failed" errors.

All roles use opaque identities (PRD §2.1), so the shared header constants
are safe for every call — no ownership threading is needed.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_asset_payload,
    create_authorization_request_payload,
    create_case_payload,
    create_claim_payload,
    create_distribution_plan_payload,
    create_engagement_payload,
    create_fee_application_payload,
    create_status_report_payload,
)
from .test_users import TEST_USERS

COURT = TEST_USERS["court_headers"]
RECEIVER = TEST_USERS["receiver_headers"]
CREDITOR = TEST_USERS["creditor_headers"]
SYSADMIN = TEST_USERS["system_admin_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, SYSADMIN))


# ---------------------------------------------------------------------------
# Cases / assets / claims — the estate base
# ---------------------------------------------------------------------------

def create_case(**overrides) -> dict:
    return get_success_data(api_client.create_case(create_case_payload(**overrides), COURT))


def get_case(case_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, RECEIVER))


def create_asset(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_asset(create_asset_payload(case_id, **overrides), RECEIVER)
    )


def liquidate_asset(asset_id: str, liquidation_value_cents: int,
                    authorization_id: Optional[str] = None) -> dict:
    payload = {"liquidation_value_cents": liquidation_value_cents}
    if authorization_id is not None:
        payload["authorization_id"] = authorization_id
    return get_success_data(api_client.liquidate_asset(asset_id, payload, RECEIVER))


def abandon_asset(asset_id: str, authorization_id: Optional[str] = None) -> dict:
    payload = {}
    if authorization_id is not None:
        payload["authorization_id"] = authorization_id
    return get_success_data(api_client.abandon_asset(asset_id, payload, RECEIVER))


def create_claim(case_id: str, as_creditor: bool = True, **overrides) -> dict:
    headers = CREDITOR if as_creditor else RECEIVER
    return get_success_data(
        api_client.create_claim(create_claim_payload(case_id, **overrides), headers)
    )


def determine_claim(claim_id: str, determination: str,
                    allowed_amount_cents: Optional[int] = None) -> dict:
    payload = {"determination": determination}
    if allowed_amount_cents is not None:
        payload["allowed_amount_cents"] = allowed_amount_cents
    return get_success_data(api_client.determine_claim(claim_id, payload, RECEIVER))


def allow_claim(claim_id: str, allowed_amount_cents: int) -> dict:
    return determine_claim(claim_id, "ALLOWED", allowed_amount_cents)


def disallow_claim(claim_id: str) -> dict:
    return determine_claim(claim_id, "DISALLOWED")


def reconsider_claim(claim_id: str) -> dict:
    return get_success_data(api_client.reconsider_claim(claim_id, COURT))


# ---------------------------------------------------------------------------
# Engagements / fee applications
# ---------------------------------------------------------------------------

def create_engagement(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_engagement(
            create_engagement_payload(case_id, **overrides), RECEIVER,
        )
    )


def decide_engagement(engagement_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_engagement(engagement_id, {"decision": decision}, COURT)
    )


def create_approved_engagement(case_id: str, **overrides) -> dict:
    eng = create_engagement(case_id, **overrides)
    return decide_engagement(eng["id"], "APPROVE")


def create_fee_application(engagement_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fee_application(
            create_fee_application_payload(engagement_id, **overrides), RECEIVER,
        )
    )


def decide_fee_application(application_id: str, decision: str,
                           approved_amount_cents: Optional[int] = None) -> dict:
    payload = {"decision": decision}
    if approved_amount_cents is not None:
        payload["approved_amount_cents"] = approved_amount_cents
    return get_success_data(
        api_client.decide_fee_application(application_id, payload, COURT)
    )


def pay_fee_application(application_id: str, expected_case_version: int) -> dict:
    return get_success_data(
        api_client.pay_fee_application(
            application_id, {"expected_case_version": expected_case_version}, RECEIVER,
        )
    )


# ---------------------------------------------------------------------------
# Authorization requests
# ---------------------------------------------------------------------------

def create_authorization_request(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_authorization_request(
            create_authorization_request_payload(case_id, **overrides), RECEIVER,
        )
    )


def decide_authorization_request(request_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_authorization_request(
            request_id, {"decision": decision}, COURT,
        )
    )


# ---------------------------------------------------------------------------
# Status reports
# ---------------------------------------------------------------------------

def create_status_report(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_status_report(
            create_status_report_payload(case_id, **overrides), RECEIVER,
        )
    )


def decide_status_report(report_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_status_report(report_id, {"decision": decision}, COURT)
    )


# ---------------------------------------------------------------------------
# Distribution plans / payments
# ---------------------------------------------------------------------------

def create_distribution_plan(case_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_distribution_plan(
            create_distribution_plan_payload(case_id, **overrides), RECEIVER,
        )
    )


def decide_distribution_plan(plan_id: str, decision: str) -> dict:
    return get_success_data(
        api_client.decide_distribution_plan(plan_id, {"decision": decision}, COURT)
    )


def amend_distribution_plan(plan_id: str, reserve_cents: Optional[int] = None) -> dict:
    payload = {}
    if reserve_cents is not None:
        payload["reserve_cents"] = reserve_cents
    return get_success_data(api_client.amend_distribution_plan(plan_id, payload, RECEIVER))


def list_plan_payments(plan_id: str, params: Optional[dict] = None) -> list:
    data, _meta = validate_paginated(api_client.list_plan_payments(plan_id, RECEIVER, params))
    return data


def list_claim_payments(claim_id: str, params: Optional[dict] = None) -> list:
    data, _meta = validate_paginated(api_client.list_claim_payments(claim_id, RECEIVER, params))
    return data


def pay_distribution_payment(payment_id: str, expected_case_version: int) -> dict:
    return get_success_data(
        api_client.pay_distribution_payment(
            payment_id, {"expected_case_version": expected_case_version}, RECEIVER,
        )
    )


def void_distribution_payment(payment_id: str) -> dict:
    return get_success_data(api_client.void_distribution_payment(payment_id, COURT))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_case_with_cash(cash_cents: int, **case_overrides) -> tuple:
    """Case ACTIVE + one liquidated CASH asset so cash_on_hand_cents == cash_cents.
    Returns (case, asset)."""
    case = create_case(**case_overrides)
    asset = create_asset(case["id"], asset_class="CASH",
                         estimated_value_cents=cash_cents)
    liquidate_asset(asset["id"], cash_cents)
    return get_case(case["id"]), asset


def setup_estate_with_allowed_claims(cash_cents: int, claims_spec: list,
                                     plan_reserve: Optional[int] = None,
                                     approve_plan: bool = False,
                                     **case_overrides) -> dict:
    """Full estate: case + liquidated cash asset + claims filed & determined.

    claims_spec: list of dicts passed as create_claim overrides; each must
    carry ``allow`` (allowed amount) or ``disallow=True`` to determine.

    Returns {"case", "asset", "claims", "plan"} (plan only when requested).
    """
    case, asset = setup_case_with_cash(cash_cents, **case_overrides)
    claims = []
    for spec in claims_spec:
        spec = dict(spec)
        allow = spec.pop("allow", None)
        disallow = spec.pop("disallow", False)
        claim = create_claim(case["id"], **spec)
        if disallow:
            claim = disallow_claim(claim["id"])
        elif allow is not None:
            claim = allow_claim(claim["id"], allow)
        claims.append(claim)
    out = {"case": get_case(case["id"]), "asset": asset, "claims": claims}
    if plan_reserve is not None:
        plan = create_distribution_plan(case["id"], reserve_cents=plan_reserve)
        if approve_plan:
            plan = decide_distribution_plan(plan["id"], "APPROVE")
        out["plan"] = plan
        out["case"] = get_case(case["id"])
    return out
