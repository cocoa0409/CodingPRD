"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors, not confusing assertion failures.

Identity threading: the Policyholder role is entity-backed, so paying an
invoice (the only ownership-gated call here) always uses
make_policyholder_headers(policyholder_id) with the real id, never the shared
constant.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_policyholder_payload,
    create_policy_payload,
    create_premium_invoice_payload,
    create_rate_filing_payload,
    create_trigger_certification_payload,
    create_provider_payload,
    create_care_plan_payload,
    create_claim_payload,
    create_claim_line_payload,
    adjudicate_payload,
)
from .test_users import TEST_USERS, make_policyholder_headers

UW = TEST_USERS["underwriter_headers"]
CE = TEST_USERS["claims_examiner_headers"]
CA = TEST_USERS["care_assessor_headers"]
REG = TEST_USERS["regulator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Atomic building blocks
# ---------------------------------------------------------------------------
def create_policyholder(**overrides) -> dict:
    res = api_client.create_policyholder(create_policyholder_payload(**overrides), UW)
    return get_success_data(res)


def create_policy(policyholder_id: str, **overrides) -> dict:
    """APPLIED / PENDING policy."""
    res = api_client.create_policy(create_policy_payload(policyholder_id, **overrides), UW)
    return get_success_data(res)


def create_issued_policy(policyholder_id=None, **policy_overrides) -> dict:
    """Create + issue a policy -> coverage IN_FORCE, premium PENDING. Returns the policy."""
    if policyholder_id is None:
        policyholder_id = create_policyholder()["id"]
    policy = create_policy(policyholder_id, **policy_overrides)
    issued = get_success_data(api_client.issue_policy(policy["id"], UW))
    return issued


def create_eligible_provider(**overrides) -> dict:
    """Create + certify a provider -> ELIGIBLE."""
    provider = get_success_data(api_client.create_provider(create_provider_payload(**overrides), CA))
    return get_success_data(api_client.certify_provider(provider["id"], CA))


def add_premium_invoice(policy_id: str, period_index: int, **overrides) -> dict:
    res = api_client.create_premium_invoice(
        policy_id, create_premium_invoice_payload(period_index, **overrides), UW)
    return get_success_data(res)


def pay_invoice(invoice_id: str, policyholder_id: str) -> dict:
    """Pay an invoice as the owning policyholder (ownership-gated -> entity-backed headers)."""
    res = api_client.pay_premium_invoice(invoice_id, make_policyholder_headers(policyholder_id))
    return get_success_data(res)


def record_trigger_certification(policy_id: str, **overrides) -> dict:
    res = api_client.create_trigger_certification(
        policy_id, create_trigger_certification_payload(**overrides), CA)
    return get_success_data(res)


def author_and_activate_care_plan(policy_id: str, provider_id: str, **overrides) -> dict:
    plan = get_success_data(api_client.create_care_plan(
        create_care_plan_payload(policy_id, provider_id, **overrides), CA))
    return get_success_data(api_client.activate_care_plan(plan["id"], CA))


def current_policy_version(policy_id: str, headers=CE) -> int:
    return get_success_data(api_client.get_policy(policy_id, headers))["version"]


# ---------------------------------------------------------------------------
# Tier 2: Premium-current, benefits-triggered, plan-active policy
# ---------------------------------------------------------------------------
def setup_active_claimable_policy(policyholder_overrides=None, policy_overrides=None,
                                  provider_overrides=None, care_setting="NURSING_HOME",
                                  base_premium_cents=12000, cert_overrides=None):
    """Full preamble to a policy that can open & adjudicate claims:

    register policyholder -> eligible provider -> issued policy (IN_FORCE) ->
    period-0 premium invoice -> pay (PAID_CURRENT) -> CERTIFIED trigger
    (benefits_triggered) -> active care plan on the eligible provider.

    Returns a dict with: ph_id, prov_id, pol_id, cp_id, inv0_id, and the
    issued policy version observed after activation (via get).
    """
    policyholder_overrides = policyholder_overrides or {}
    policy_overrides = policy_overrides or {}
    provider_overrides = provider_overrides or {}
    cert_overrides = cert_overrides or {}

    ph = create_policyholder(**policyholder_overrides)
    provider = create_eligible_provider(**provider_overrides)
    policy = create_issued_policy(ph["id"], **policy_overrides)
    inv0 = add_premium_invoice(policy["id"], 0, base_premium_cents=base_premium_cents)
    pay_invoice(inv0["id"], ph["id"])
    record_trigger_certification(policy["id"], **cert_overrides)
    plan = author_and_activate_care_plan(policy["id"], provider["id"], care_setting=care_setting)

    return {
        "ph_id": ph["id"],
        "prov_id": provider["id"],
        "pol_id": policy["id"],
        "cp_id": plan["id"],
        "inv0_id": inv0["id"],
    }


# ---------------------------------------------------------------------------
# Tier 3: Claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_claim(policy_id: str, care_plan_id: str, service_month="2026-03", headers=CE) -> dict:
    """Open a claim using the live policy version. Returns the created claim."""
    version = current_policy_version(policy_id, headers)
    res = api_client.create_claim(
        create_claim_payload(policy_id, care_plan_id, version, service_month=service_month), headers)
    return get_success_data(res)


def add_lines(claim_id: str, lines, headers=CE):
    """lines: iterable of (service_date, billed_charge_cents[, is_qualifying_day])."""
    created = []
    for spec in lines:
        if len(spec) == 3:
            service_date, charge, qualifying = spec
            payload = create_claim_line_payload(service_date, charge, is_qualifying_day=qualifying)
        else:
            service_date, charge = spec
            payload = create_claim_line_payload(service_date, charge)
        created.append(get_success_data(api_client.add_claim_line(claim_id, payload, headers)))
    return created


def setup_claim_under_review(lines=None, service_month="2026-03",
                             policy_overrides=None, policyholder_overrides=None,
                             provider_overrides=None, base_premium_cents=12000,
                             cert_overrides=None):
    """Reach a claim in UNDER_REVIEW with the given service-day lines attached.

    lines: list of (service_date, billed_charge_cents[, is_qualifying_day]) tuples.
    Returns dict with ph_id, prov_id, pol_id, cp_id, claim_id, inv0_id.
    """
    ctx = setup_active_claimable_policy(
        policyholder_overrides=policyholder_overrides,
        policy_overrides=policy_overrides,
        provider_overrides=provider_overrides,
        base_premium_cents=base_premium_cents,
        cert_overrides=cert_overrides,
    )
    claim = open_claim(ctx["pol_id"], ctx["cp_id"], service_month=service_month)
    if lines:
        add_lines(claim["id"], lines)
    get_success_data(api_client.start_review(claim["id"], CE))
    ctx["claim_id"] = claim["id"]
    return ctx


def approve_claim(policy_id: str, claim_id: str, headers=CE) -> dict:
    """Approve a claim using the live policy version. Returns the approved claim."""
    version = current_policy_version(policy_id, headers)
    res = api_client.approve_claim(claim_id, adjudicate_payload_version(version), headers)
    return get_success_data(res)


def deny_claim(policy_id: str, claim_id: str, headers=CE) -> dict:
    version = current_policy_version(policy_id, headers)
    res = api_client.deny_claim(claim_id, {"expected_policy_version": version}, headers)
    return get_success_data(res)


def adjudicate_payload_version(version: int) -> dict:
    return {"expected_policy_version": version}


# ---------------------------------------------------------------------------
# Tier 4: Rate filing shortcuts
# ---------------------------------------------------------------------------
def setup_issued_policy_with_filing(requested_increase_pct=40, effective_period_index=1,
                                    policy_overrides=None):
    """Issued (IN_FORCE) policy + one FILED rate filing.

    Returns dict with ph_id, pol_id, fil_id.
    """
    policy_overrides = policy_overrides or {}
    ph = create_policyholder()
    policy = create_issued_policy(ph["id"], **policy_overrides)
    filing = get_success_data(api_client.create_rate_filing(
        create_rate_filing_payload(
            policy["id"],
            requested_increase_pct=requested_increase_pct,
            effective_period_index=effective_period_index),
        UW))
    return {"ph_id": ph["id"], "pol_id": policy["id"], "fil_id": filing["id"]}


def adjudicate_filing(policy_id: str, filing_id: str, granted_pct: int, headers=REG) -> dict:
    """Adjudicate using the live policy version. Returns the filing."""
    version = get_success_data(api_client.get_policy(policy_id, REG))["version"]
    res = api_client.adjudicate_rate_filing(
        filing_id, adjudicate_payload(granted_pct, version), headers)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 5: Reverse-reachability readers (these endpoints return arrays)
# ---------------------------------------------------------------------------
def read_benefit_pool(policy_id: str, headers=CE) -> dict:
    """GET /policies/{id}/benefit-pool returns the single BenefitPool row."""
    data, _ = validate_paginated(api_client.get_benefit_pool(policy_id, headers))
    assert len(data) == 1, f"expected exactly one benefit-pool row, got {len(data)}"
    return data[0]


def read_partnership_disregard(policy_id: str, headers=REG):
    """GET /policies/{id}/partnership-disregard returns the disregard rows (0 or 1)."""
    data, meta = validate_paginated(api_client.get_partnership_disregard(policy_id, headers))
    return data, meta


def read_policy_ledger(policy_id: str, headers=CE):
    data, meta = validate_paginated(api_client.list_policy_ledger_entries(policy_id, headers))
    return data, meta
