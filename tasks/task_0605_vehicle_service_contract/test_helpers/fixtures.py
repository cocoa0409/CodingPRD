"""Composite setup helpers for Vehicle Service Contract tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is reset before every test.

Helpers use get_success_data() (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_coverage_plan_payload,
    create_reinsurance_pool_payload,
    create_repair_facility_payload,
    create_contract_payload,
    create_claim_payload,
    create_claim_line_payload,
    create_cancellation_payload,
)

ADMIN = TEST_USERS["admin_underwriter_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Primitive creators
# ---------------------------------------------------------------------------

def create_pool(name="Pool"):
    resp = api_client.create_reinsurance_pool(create_reinsurance_pool_payload(name=name), ADMIN)
    return get_success_data(resp)


def create_plan(**overrides):
    resp = api_client.create_coverage_plan(create_coverage_plan_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_active_plan(**overrides):
    plan = create_plan(**overrides)
    resp = api_client.activate_coverage_plan(plan["id"], ADMIN)
    return get_success_data(resp)


def create_facility(**overrides):
    resp = api_client.create_repair_facility(create_repair_facility_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_contract(plan_id, pool_id, **overrides):
    resp = api_client.create_contract(create_contract_payload(plan_id, pool_id, **overrides), CONTRACT_ADMIN)
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(to_iso8601, CONTRACT_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: contract state progression + hierarchy
# ---------------------------------------------------------------------------

def setup_active_contract(plan_overrides=None, contract_overrides=None,
                          pool_name="Pool", with_facility=False, facility_overrides=None):
    """Active plan + open pool + ACTIVE contract. Optionally a facility.

    Returns dict(plan, pool, contract[, facility]).
    """
    plan_overrides = plan_overrides or {}
    contract_overrides = contract_overrides or {}
    pool = create_pool(pool_name)
    plan = create_active_plan(**plan_overrides)
    contract = create_contract(plan["id"], pool["id"], **contract_overrides)
    act = get_success_data(api_client.activate_contract(contract["id"], CONTRACT_ADMIN))
    result = {"plan": plan, "pool": pool, "contract": act}
    if with_facility:
        result["facility"] = create_facility(**(facility_overrides or {}))
    return result


def setup_pending_contract(plan_overrides=None, contract_overrides=None,
                           pool_name="Pool", with_facility=False, facility_overrides=None):
    """Active plan + open pool + PENDING contract (not activated)."""
    plan_overrides = plan_overrides or {}
    contract_overrides = contract_overrides or {}
    pool = create_pool(pool_name)
    plan = create_active_plan(**plan_overrides)
    contract = create_contract(plan["id"], pool["id"], **contract_overrides)
    result = {"plan": plan, "pool": pool, "contract": contract}
    if with_facility:
        result["facility"] = create_facility(**(facility_overrides or {}))
    return result


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_submitted_claim(claim_overrides=None, claim_lines=None,
                          plan_overrides=None, facility_overrides=None,
                          pool_name="Pool", contract_overrides=None):
    """Active contract + facility + a SUBMITTED claim with the given lines.

    claim_lines: list of payload-override dicts passed to create_claim_line.
    Returns dict(plan, pool, contract, facility, claim, lines).
    """
    base = setup_active_contract(
        plan_overrides=plan_overrides,
        contract_overrides=contract_overrides,
        pool_name=pool_name,
        with_facility=True,
        facility_overrides=facility_overrides,
    )
    claim = get_success_data(api_client.create_claim(
        create_claim_payload(base["contract"]["id"], base["facility"]["id"], **(claim_overrides or {})),
        ADJUSTER,
    ))
    lines = []
    for line_ov in (claim_lines or []):
        lines.append(get_success_data(api_client.create_claim_line(
            claim["id"], create_claim_line_payload(**line_ov), ADJUSTER,
        )))
    base["claim"] = claim
    base["lines"] = lines
    return base


def setup_under_review_claim(claim_overrides=None, claim_lines=None,
                             plan_overrides=None, facility_overrides=None,
                             pool_name="Pool", contract_overrides=None):
    """As setup_submitted_claim, then start-review -> UNDER_REVIEW."""
    base = setup_submitted_claim(
        claim_overrides=claim_overrides, claim_lines=claim_lines,
        plan_overrides=plan_overrides, facility_overrides=facility_overrides,
        pool_name=pool_name, contract_overrides=contract_overrides,
    )
    base["claim"] = get_success_data(api_client.start_review_claim(base["claim"]["id"], ADJUSTER))
    return base


def setup_authorized_claim(claim_overrides=None, claim_lines=None,
                           plan_overrides=None, facility_overrides=None,
                           pool_name="Pool", contract_overrides=None):
    """Claim taken through start-review -> approve -> authorize.

    Returns base dict additionally carrying 'authorization' and a fresh
    'contract_version' read after authorize (authorize does not bump the
    contract version, but reading is cheap and keeps disburse callers honest).
    """
    base = setup_under_review_claim(
        claim_overrides=claim_overrides, claim_lines=claim_lines,
        plan_overrides=plan_overrides, facility_overrides=facility_overrides,
        pool_name=pool_name, contract_overrides=contract_overrides,
    )
    get_success_data(api_client.approve_claim(base["claim"]["id"], ADJUSTER))
    auth = get_success_data(api_client.authorize_claim(base["claim"]["id"], ADJUSTER))
    base["authorization"] = auth
    base["claim"] = get_success_data(api_client.get_claim(base["claim"]["id"], ADJUSTER))
    contract = get_success_data(api_client.get_contract(base["contract"]["id"], ADJUSTER))
    base["contract"] = contract
    base["contract_version"] = contract["version"]
    return base


def setup_disbursed_claim(claim_overrides=None, claim_lines=None,
                          plan_overrides=None, facility_overrides=None,
                          pool_name="Pool", contract_overrides=None):
    """Claim taken all the way through disburse against a fresh contract version.

    Returns base dict with 'authorization' updated to DISBURSED.
    """
    base = setup_authorized_claim(
        claim_overrides=claim_overrides, claim_lines=claim_lines,
        plan_overrides=plan_overrides, facility_overrides=facility_overrides,
        pool_name=pool_name, contract_overrides=contract_overrides,
    )
    auth = get_success_data(api_client.disburse_repair_authorization(
        base["authorization"]["id"],
        {"expected_contract_version": base["contract_version"]},
        ADJUSTER,
    ))
    base["authorization"] = auth
    base["contract"] = get_success_data(api_client.get_contract(base["contract"]["id"], ADJUSTER))
    return base


# Standard line set: one covered LABOR 2.3h + one covered PART 13499.
# At posted 9500 vs cap 12000 -> effective 9500; 2.3*9500 = 21850; +13499 = 35349.
STANDARD_LINES = [
    {"line_type": "LABOR", "labor_hours": 2.3, "covered": True},
    {"line_type": "PART", "part_number": "TX-900", "requested_amount_cents": 13499, "covered": True},
]


def setup_disbursed_standard(pool_name="Pool", vin="VINSTD0001"):
    """Canonical disbursed claim: rental_days 4 (capped to 3 -> 15000),
    towing claimed (8000), adjudicated 35349, deductible 10000.
    total_payout = (35349 - 10000) + 15000 + 8000 = 48349.
    Facility IN_NETWORK + direct_pay_enrolled.
    """
    return setup_disbursed_claim(
        pool_name=pool_name,
        contract_overrides={"vin": vin},
        facility_overrides={"network_status": "IN_NETWORK", "direct_pay_enrolled": True},
        claim_overrides={"complaint": "transmission", "rental_days_claimed": 4, "towing_claimed": True},
        claim_lines=STANDARD_LINES,
    )


# ---------------------------------------------------------------------------
# Tier 5: cancellation lifecycle
# ---------------------------------------------------------------------------

def setup_requested_cancellation(reason="CUSTOMER_REQUEST", request_date="2026-01-20T00:00:00Z",
                                 clock=None, contract=None, pool_name="Pool",
                                 contract_overrides=None):
    """Active contract + a REQUESTED cancellation (optionally after setting clock).

    If `contract` is provided, reuse it; else build a fresh active contract.
    Returns dict(plan?, pool?, contract, cancellation).
    """
    if contract is None:
        base = setup_active_contract(pool_name=pool_name, contract_overrides=contract_overrides or {})
    else:
        base = {"contract": contract}
    if clock is not None:
        set_clock(clock)
    canc = get_success_data(api_client.create_cancellation(
        create_cancellation_payload(base["contract"]["id"], reason=reason, request_date=request_date),
        CONTRACT_ADMIN,
    ))
    base["cancellation"] = canc
    return base


def setup_approved_cancellation(reason="CUSTOMER_REQUEST", request_date="2026-01-20T00:00:00Z",
                                clock=None, pool_name="Pool", contract_overrides=None):
    """Active contract + cancellation taken REQUESTED -> APPROVED."""
    base = setup_requested_cancellation(
        reason=reason, request_date=request_date, clock=clock,
        pool_name=pool_name, contract_overrides=contract_overrides,
    )
    base["cancellation"] = get_success_data(
        api_client.approve_cancellation(base["cancellation"]["id"], CONTRACT_ADMIN)
    )
    return base
