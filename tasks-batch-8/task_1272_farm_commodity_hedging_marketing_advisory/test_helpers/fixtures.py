"""Composite setup helpers.

Each helper builds multi-entity preconditions from scratch using only
PRD-declared endpoints (the harness restarts the server before every test, so
no state is ever carried over). Setup calls use the lenient get_success_data
validator so failures surface as clear "Setup failed" errors.

The Grower role is entity-backed: every grower call threads the owning
operation's id through make_grower_headers(operation_id).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_operation_payload,
    create_baseline_payload,
    create_policy_payload,
    create_plan_payload,
    create_price_target_payload,
    create_market_tick_payload,
    create_recommendation_payload,
    create_margin_account_payload,
    create_buyer_payload,
    create_contract_payload,
    create_ticket_payload,
    create_storage_lot_payload,
    create_agreement_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_grower_headers,
)


ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
ADMIN = TEST_USERS["admin_headers"]


def grower_headers_for(operation_id: str) -> dict:
    """Entity-backed Grower headers for the owning operation."""
    return make_grower_headers(operation_id)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_operation(**overrides) -> dict:
    """Create a GrowerOperation. Returns the created operation (with version)."""
    resp = api_client.create_operation(create_operation_payload(**overrides), ADVISOR)
    return get_success_data(resp)


def create_baseline_for(operation: dict, **overrides) -> dict:
    """Create a ProductionBaseline for an operation, OCC-guarded on the
    operation's current version. Returns the baseline."""
    op = get_success_data(api_client.get_operation(operation["id"], ADVISOR))
    payload = create_baseline_payload(op["id"], op["version"], **overrides)
    resp = api_client.create_baseline(payload, ADVISOR)
    return get_success_data(resp)


def certify_baseline(baseline: dict, operation_id: str) -> dict:
    """Grower attestation: PROVISIONAL -> CERTIFIED."""
    resp = api_client.certify_baseline(baseline["id"], make_grower_headers(operation_id))
    return get_success_data(resp)


def create_certified_baseline(operation: dict, **overrides) -> dict:
    """Baseline created and certified."""
    baseline = create_baseline_for(operation, **overrides)
    return certify_baseline(baseline, operation["id"])


def create_agreement_for(operation_id: str, **overrides) -> dict:
    resp = api_client.create_agreement(create_agreement_payload(operation_id, **overrides), ADVISOR)
    return get_success_data(resp)


def activate_agreement(agreement: dict, operation_id: str, submitter_headers=None) -> dict:
    """Walk an agreement DRAFT -> PENDING_SIGNATURE -> ACTIVE with the full
    disclosure workflow (deliver, acknowledge, sign)."""
    submitter = submitter_headers or ADVISOR
    get_success_data(api_client.submit_agreement(agreement["id"], submitter))
    get_success_data(api_client.deliver_disclosure(agreement["id"], ADVISOR))
    get_success_data(api_client.acknowledge_disclosure(agreement["id"], make_grower_headers(operation_id)))
    resp = api_client.sign_agreement(agreement["id"], make_grower_headers(operation_id))
    return get_success_data(resp)


def create_active_agreement(operation_id: str, **overrides) -> dict:
    """Agreement created and walked to ACTIVE with a current acknowledgment."""
    agreement = create_agreement_for(operation_id, **overrides)
    return activate_agreement(agreement, operation_id)


def create_approved_buyer(**overrides) -> dict:
    """Buyer registered and approved by compliance."""
    buyer = get_success_data(api_client.create_buyer(create_buyer_payload(**overrides), ADVISOR))
    return get_success_data(api_client.approve_buyer(buyer["id"], COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy — operation + baseline + agreement + plan
# ---------------------------------------------------------------------------

def create_plan_for(operation: dict, baseline: dict, **overrides) -> dict:
    """Create a DRAFT MarketingPlan."""
    payload = create_plan_payload(operation["id"], baseline["id"], **overrides)
    return get_success_data(api_client.create_plan(payload, ADVISOR))


def create_active_plan(operation: dict, baseline: dict, **overrides) -> dict:
    """Create a plan and activate it (agreement + baseline gates assumed met)."""
    plan = create_plan_for(operation, baseline, **overrides)
    return get_success_data(api_client.activate_plan(plan["id"], ADVISOR))


def setup_operation_with_active_plan(
    name="Test Farm",
    risk_profile="BALANCED",
    yield_method="APH",
    planted_acres=100,
    aph_yield_bushels=200.0,
    trend_yield_bushels=205.0,
    max_priced_pct=1.00,
    agreement_overrides=None,
    primary_commodity="CORN",
    crop_year=2026,
) -> dict:
    """Full activation chain: operation -> certified baseline -> ACTIVE
    agreement (acknowledged disclosure) -> ACTIVE marketing plan.

    Returns a dict with operation, baseline, agreement, plan."""
    operation = create_operation(
        name=name,
        primary_commodity=primary_commodity,
        crop_year=crop_year,
        risk_profile=risk_profile,
        yield_method=yield_method,
    )
    baseline = create_certified_baseline(
        operation,
        planted_acres=planted_acres,
        aph_yield_bushels=aph_yield_bushels,
        trend_yield_bushels=trend_yield_bushels,
    )
    agreement = create_active_agreement(operation["id"], **(agreement_overrides or {}))
    plan = create_active_plan(operation, baseline, max_priced_pct=max_priced_pct)
    return {
        "operation": operation,
        "baseline": baseline,
        "agreement": agreement,
        "plan": plan,
    }


def setup_active_plan_with_buyer(**kwargs) -> dict:
    """setup_operation_with_active_plan plus one APPROVED buyer."""
    ctx = setup_operation_with_active_plan(**kwargs)
    ctx["buyer"] = create_approved_buyer()
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — contracts, recommendations, positions
# ---------------------------------------------------------------------------

def create_flat_contract(ctx: dict, **overrides) -> dict:
    """FLAT_PRICE contract against the context's operation/plan/buyer."""
    payload = create_contract_payload(
        ctx["operation"]["id"], ctx["plan"]["id"], ctx["buyer"]["id"], **overrides
    )
    return get_success_data(api_client.create_contract(payload, ADVISOR))


def create_confirmed_delivery(ctx: dict, contract: dict, **overrides) -> dict:
    """Record + confirm a delivery ticket against a contract."""
    ticket = get_success_data(
        api_client.create_ticket(
            create_ticket_payload(contract["id"], **overrides),
            make_grower_headers(ctx["operation"]["id"]),
        )
    )
    return get_success_data(api_client.confirm_ticket(ticket["id"], ADVISOR))


def create_accepted_recommendation(plan: dict, operation_id: str, **overrides) -> dict:
    """Advisor-authored recommendation accepted by the grower (ACCEPTED)."""
    rec = get_success_data(
        api_client.create_recommendation(create_recommendation_payload(plan["id"], **overrides), ADVISOR)
    )
    return get_success_data(
        api_client.accept_recommendation(rec["id"], make_grower_headers(operation_id))
    )


def create_open_position(ctx: dict, **rec_overrides) -> dict:
    """Recommendation -> accept -> execute; returns the OPEN BrokeragePosition.

    Requires a margin account in ctx["account"] and a SETTLEMENT tick already
    recorded for the recommendation's contract month."""
    rec = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], **rec_overrides)
    return get_success_data(api_client.execute_recommendation(rec["id"], ADVISOR))


def setup_margin_account(ctx: dict, initial_funding=20000, **overrides) -> dict:
    """Open the operation's margin account."""
    account = get_success_data(
        api_client.create_margin_account(
            create_margin_account_payload(
                ctx["operation"]["id"], initial_funding=initial_funding, **overrides
            ),
            ADVISOR,
        )
    )
    ctx["account"] = account
    return account


def record_settlement_tick(price, price_date, contract_month="2026-12", commodity="CORN") -> dict:
    """Record a SETTLEMENT market tick (PlatformAdmin)."""
    return get_success_data(
        api_client.create_market_tick(
            create_market_tick_payload(
                price=price, price_date=price_date, contract_month=contract_month, commodity=commodity
            ),
            ADMIN,
        )
    )


def record_quote_tick(price, price_date, contract_month="2026-12", commodity="CORN") -> dict:
    """Record a QUOTE market tick (PlatformAdmin)."""
    return get_success_data(
        api_client.create_market_tick(
            create_market_tick_payload(
                price=price,
                price_date=price_date,
                contract_month=contract_month,
                commodity=commodity,
                kind="QUOTE",
            ),
            ADMIN,
        )
    )


def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PlatformAdmin)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


# ---------------------------------------------------------------------------
# Tier 4: margin-call targeting — drive an account into CALL_OUTSTANDING
# ---------------------------------------------------------------------------

def setup_account_in_margin_call(
    initial_funding=20000,
    position_bushels=50000,
    entry_price=4.50,
    adverse_price=4.70,
) -> dict:
    """BALANCED operation (expected 200000, cap 160000) with an ACTIVE plan, a
    funded margin account, and one OPEN FUTURES_SHORT position entered at
    `entry_price`; an adverse SETTLEMENT tick at `adverse_price` then drives
    margin_equity below maintenance and the account into CALL_OUTSTANDING.

    Returns ctx with operation/plan/account/position keys."""
    ctx = setup_operation_with_active_plan(
        risk_profile="BALANCED", planted_acres=1000, max_priced_pct=0.80
    )
    setup_margin_account(ctx, initial_funding=initial_funding)
    record_settlement_tick(entry_price, "2026-06-01")
    ctx["position"] = create_open_position(ctx, bushels=position_bushels)
    record_settlement_tick(adverse_price, "2026-07-01")
    return ctx
