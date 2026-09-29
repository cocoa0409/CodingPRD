"""Composite setup helpers.

Every helper builds its preconditions from scratch through the PRD's own
endpoints, so each test starts from an empty service. Setup calls use the
lenient success reader so a broken precondition surfaces as a setup failure
rather than as a confusing assertion further down.

Store-scoped calls always thread the real Store id into X-User-ID through the
per-store header builders, because a StoreAssociate or StoreManager is
identified by the id of the store it acts for.
"""
from typing import Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import ANALYST_USER_ID, DEFAULT_CLOCK, MANAGER_USER_ID
from .factories import (
    create_change_order_payload,
    create_claim_payload,
    create_competitor_payload,
    create_index_report_payload,
    create_label_batch_payload,
    create_market_payload,
    create_match_payload,
    create_match_policy_payload,
    create_observation_payload,
    create_product_payload,
    create_repricing_rule_payload,
    create_store_payload,
)
from .test_users import (
    make_compliance_officer_headers,
    make_data_collector_headers,
    make_platform_admin_headers,
    make_pricing_analyst_headers,
    make_pricing_manager_headers,
    make_store_associate_headers,
    make_store_manager_headers,
)

ADMIN = make_platform_admin_headers()
ANALYST = make_pricing_analyst_headers(ANALYST_USER_ID)
MANAGER = make_pricing_manager_headers(MANAGER_USER_ID)
COMPLIANCE = make_compliance_officer_headers()
COLLECTOR = make_data_collector_headers()


# --------------------------------------------------------------- logical clock
def set_clock(current_utc: str = DEFAULT_CLOCK, headers: Optional[dict] = None) -> dict:
    """Move the service's logical current UTC instant."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, headers or ADMIN))


# ------------------------------------------------------------- reference data
def new_market(**overrides) -> dict:
    return get_success_data(api_client.create_market(create_market_payload(**overrides), ADMIN))


def new_product(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(market_id, **overrides), ADMIN)
    )


def new_store(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_store(create_store_payload(market_id, **overrides), ADMIN)
    )


def new_competitor(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_competitor(create_competitor_payload(market_id, **overrides), ADMIN)
    )


def read_market(market_id: str) -> dict:
    return get_success_data(api_client.get_market(market_id, MANAGER))


def read_product(product_id: str) -> dict:
    return get_success_data(api_client.get_product(product_id, ANALYST))


def read_store(store_id: str) -> dict:
    return get_success_data(api_client.get_store(store_id, MANAGER))


def read_match(link_id: str) -> dict:
    return get_success_data(api_client.get_match(link_id, ANALYST))


def read_competitor(competitor_id: str) -> dict:
    return get_success_data(api_client.get_competitor(competitor_id, ANALYST))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_change_order(order_id, MANAGER))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, MANAGER))


def read_policy(policy_id: str) -> dict:
    return get_success_data(api_client.get_match_policy(policy_id, MANAGER))


def read_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_label_batch(batch_id, MANAGER))


def read_report(report_id: str) -> dict:
    return get_success_data(api_client.get_index_report(report_id, ANALYST))


def product_version(product_id: str) -> int:
    return read_product(product_id)["version"]


def market_version(market_id: str) -> int:
    return read_market(market_id)["version"]


# -------------------------------------------------------------------- matching
def new_match(product_id: str, competitor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_match(create_match_payload(product_id, competitor_id, **overrides), ANALYST)
    )


def review_match(link_id: str, decision: str, note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.review_match(link_id, payload, MANAGER))


def revise_match(link_id: str, **fields) -> dict:
    return get_success_data(api_client.revise_match(link_id, dict(fields), ANALYST))


def confirm_match(link_id: str) -> dict:
    """Confirm a proposed match straight from PROPOSED."""
    return review_match(link_id, "CONFIRM")


def new_observation(link_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_observation(create_observation_payload(link_id, **overrides), COLLECTOR)
    )


def void_observation(observation_id: str, void_reason: str = "mis-scraped") -> dict:
    return get_success_data(
        api_client.void_observation(observation_id, {"void_reason": void_reason}, COLLECTOR)
    )


def suspend_competitor(competitor_id: str, reason: Optional[str] = None) -> dict:
    payload = {"to_status": "SUSPENDED"}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.patch_competitor_status(competitor_id, payload, COMPLIANCE))


def retire_competitor(competitor_id: str, reason: Optional[str] = None) -> dict:
    payload = {"to_status": "RETIRED"}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.patch_competitor_status(competitor_id, payload, COMPLIANCE))


# --------------------------------------------------------------- index reports
def new_index_report(market_id: str, **overrides) -> dict:
    """Create a report, reading the market's current version for the OCC field."""
    if "expected_market_version" not in overrides:
        overrides["expected_market_version"] = market_version(market_id)
    payload = create_index_report_payload(
        market_id, overrides.pop("expected_market_version"), **overrides
    )
    return get_success_data(api_client.create_index_report(payload, ANALYST))


def publish_index_report(report_id: str) -> dict:
    return get_success_data(api_client.publish_index_report(report_id, {}, MANAGER))


# ------------------------------------------------------------ repricing rules
def new_repricing_rule(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_repricing_rule(create_repricing_rule_payload(market_id, **overrides), MANAGER)
    )


# --------------------------------------------------------------- change orders
def new_change_order(product_id: str, **overrides) -> dict:
    """Create a change order, re-reading the product version unless one is given."""
    if "expected_product_version" not in overrides:
        overrides["expected_product_version"] = product_version(product_id)
    author = overrides.pop("headers", ANALYST)
    payload = create_change_order_payload(
        product_id, overrides.pop("expected_product_version"), **overrides
    )
    return get_success_data(api_client.create_change_order(payload, author))


def new_automated_order(product_id: str, **overrides) -> dict:
    """Create an AUTOMATED_RULE order, which must not carry a requested price."""
    overrides.setdefault("origin", "AUTOMATED_RULE")
    overrides.pop("requested_price_cents", None)
    version = overrides.pop("expected_product_version", None)
    if version is None:
        version = product_version(product_id)
    author = overrides.pop("headers", ANALYST)
    payload = create_change_order_payload(product_id, version, **overrides)
    payload.pop("requested_price_cents", None)
    return get_success_data(api_client.create_change_order(payload, author))


def submit_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.submit_change_order(order_id, {}, headers or ANALYST))


def decide_order(order_id: str, decision: str = "APPROVE", headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.decide_change_order(order_id, {"decision": decision}, headers or MANAGER)
    )


def execute_order(order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.execute_change_order(order_id, {}, headers or MANAGER))


def approve_order(order_id: str) -> dict:
    """Submit as the author, then approve as a different manager."""
    submit_order(order_id)
    return decide_order(order_id, "APPROVE")


# ---------------------------------------------------------- price match policy
def new_match_policy(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_match_policy(create_match_policy_payload(market_id, **overrides), MANAGER)
    )


# ------------------------------------------------------------------- claims
def new_claim(policy_id: str, product_id: str, competitor_id: str, store_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_store_associate_headers(store_id)
    payload = create_claim_payload(policy_id, product_id, competitor_id, store_id, **overrides)
    return get_success_data(api_client.create_claim(payload, headers))


def verify_claim(claim_id: str, store_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_store_manager_headers(store_id)
    return get_success_data(api_client.verify_claim(claim_id, dict(overrides), headers))


def decide_claim(claim_id: str, store_id: str, decision: str = "VERIFIED", **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_store_manager_headers(store_id)
    payload = {"decision": decision}
    payload.update(overrides)
    return get_success_data(api_client.decide_claim(claim_id, payload, headers))


def honor_claim(claim_id: str, store_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.honor_claim(claim_id, {}, headers or make_store_associate_headers(store_id))
    )


def reverse_claim(claim_id: str, store_id: str, reversal_reason: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.reverse_claim(
            claim_id, {"reversal_reason": reversal_reason}, headers or make_store_manager_headers(store_id)
        )
    )


# -------------------------------------------------------------- label batches
def new_label_batch(store_id: str, **overrides) -> dict:
    headers = overrides.pop("headers", None) or make_store_manager_headers(store_id)
    payload = create_label_batch_payload(store_id, **overrides)
    return get_success_data(api_client.create_label_batch(payload, headers))


def advance_label_batch(batch_id: str, store_id: str, to_status: str) -> dict:
    return get_success_data(
        api_client.advance_label_batch(
            batch_id, {"to_status": to_status}, make_store_manager_headers(store_id)
        )
    )


def cancel_label_batch(batch_id: str, store_id: str, cancel_reason: str = "printer jam") -> dict:
    return get_success_data(
        api_client.cancel_label_batch(
            batch_id, {"cancel_reason": cancel_reason}, make_store_manager_headers(store_id)
        )
    )


# =============================================================================
# Composite scenarios
# =============================================================================
def setup_market(clock: str = DEFAULT_CLOCK, **market_overrides) -> dict:
    """Pin the logical clock, then define one market."""
    set_clock(clock)
    return new_market(**market_overrides)


def setup_market_with_product(
    clock: str = DEFAULT_CLOCK,
    market_overrides: Optional[dict] = None,
    product_overrides: Optional[dict] = None,
) -> dict:
    """Clock + market + one catalog product. Returns {"market", "product"}."""
    market = setup_market(clock, **(market_overrides or {}))
    product = new_product(market["id"], **(product_overrides or {}))
    return {"market": market, "product": product}


def setup_market_product_store(
    clock: str = DEFAULT_CLOCK,
    market_overrides: Optional[dict] = None,
    product_overrides: Optional[dict] = None,
    store_overrides: Optional[dict] = None,
) -> dict:
    """Clock + market + product + store. Returns {"market", "product", "store"}."""
    scenario = setup_market_with_product(clock, market_overrides, product_overrides)
    scenario["store"] = new_store(scenario["market"]["id"], **(store_overrides or {}))
    return scenario


def setup_confirmed_match(
    clock: str = DEFAULT_CLOCK,
    market_overrides: Optional[dict] = None,
    product_overrides: Optional[dict] = None,
    competitor_overrides: Optional[dict] = None,
    match_overrides: Optional[dict] = None,
    observation_overrides: Optional[dict] = None,
    with_observation: bool = False,
) -> dict:
    """Market + product + ACTIVE competitor + a CONFIRMED match.

    When ``with_observation`` is set, one observation is posted before the
    confirmation so the match elects an effective competitor price.
    Returns {"market", "product", "competitor", "link", "observation"}.
    """
    scenario = setup_market_with_product(clock, market_overrides, product_overrides)
    competitor = new_competitor(scenario["market"]["id"], **(competitor_overrides or {}))
    link = new_match(scenario["product"]["id"], competitor["id"], **(match_overrides or {}))
    observation = None
    if with_observation:
        observation = new_observation(link["id"], **(observation_overrides or {}))
    link = confirm_match(link["id"])
    scenario.update(
        {"competitor": competitor, "link": link, "observation": observation}
    )
    return scenario


def setup_price_match_programme(
    clock: str = DEFAULT_CLOCK,
    market_overrides: Optional[dict] = None,
    product_overrides: Optional[dict] = None,
    store_overrides: Optional[dict] = None,
    competitor_overrides: Optional[dict] = None,
    match_overrides: Optional[dict] = None,
    policy_overrides: Optional[dict] = None,
    with_confirmed_match: bool = True,
) -> dict:
    """Everything a price-match claim needs: market, product, store, an eligible
    competitor with a CONFIRMED match, and one ACTIVE policy.

    Returns {"market", "product", "store", "competitor", "link", "policy"}.
    """
    competitor_defaults = {"price_match_eligible": True, "tier": "PRIMARY"}
    competitor_defaults.update(competitor_overrides or {})
    scenario = setup_market_product_store(
        clock, market_overrides, product_overrides, store_overrides
    )
    competitor = new_competitor(scenario["market"]["id"], **competitor_defaults)
    link = new_match(scenario["product"]["id"], competitor["id"], **(match_overrides or {}))
    if with_confirmed_match:
        link = confirm_match(link["id"])
    policy = new_match_policy(scenario["market"]["id"], **(policy_overrides or {}))
    scenario.update({"competitor": competitor, "link": link, "policy": policy})
    return scenario


def setup_submitted_claim(claim_overrides: Optional[dict] = None, **programme_kwargs) -> dict:
    """Price-match programme plus one filed claim in SUBMITTED."""
    scenario = setup_price_match_programme(**programme_kwargs)
    scenario["claim"] = new_claim(
        scenario["policy"]["id"],
        scenario["product"]["id"],
        scenario["competitor"]["id"],
        scenario["store"]["id"],
        **(claim_overrides or {}),
    )
    return scenario


def setup_verifying_claim(claim_overrides: Optional[dict] = None, **programme_kwargs) -> dict:
    """A filed claim moved on to VERIFYING."""
    scenario = setup_submitted_claim(claim_overrides, **programme_kwargs)
    scenario["claim"] = verify_claim(scenario["claim"]["id"], scenario["store"]["id"])
    return scenario


def setup_verified_claim(claim_overrides: Optional[dict] = None, **programme_kwargs) -> dict:
    """A filed claim carried through verification to VERIFIED."""
    scenario = setup_verifying_claim(claim_overrides, **programme_kwargs)
    scenario["claim"] = decide_claim(
        scenario["claim"]["id"], scenario["store"]["id"], "VERIFIED"
    )
    return scenario


def setup_honored_claim(claim_overrides: Optional[dict] = None, **programme_kwargs) -> dict:
    """A verified claim honoured at the register."""
    scenario = setup_verified_claim(claim_overrides, **programme_kwargs)
    scenario["claim"] = honor_claim(scenario["claim"]["id"], scenario["store"]["id"])
    return scenario


def setup_manual_order(
    order_overrides: Optional[dict] = None,
    stage: str = "DRAFT",
    **scenario_kwargs,
) -> dict:
    """Market + product (+ store when a signage store is wanted) + one MANUAL
    order carried to ``stage``: DRAFT, PENDING_APPROVAL, APPROVED or EXECUTED.

    Returns the scenario dict with an "order" key holding the latest read.
    """
    with_store = scenario_kwargs.pop("with_store", False)
    if with_store:
        scenario = setup_market_product_store(**scenario_kwargs)
    else:
        scenario = setup_market_with_product(**scenario_kwargs)
    overrides = dict(order_overrides or {})
    if with_store and "signage_store_id" not in overrides:
        overrides["signage_store_id"] = scenario["store"]["id"]
    order = new_change_order(scenario["product"]["id"], **overrides)
    if stage in ("PENDING_APPROVAL", "APPROVED", "EXECUTED"):
        order = submit_order(order["id"])
    if stage in ("APPROVED", "EXECUTED"):
        order = decide_order(order["id"], "APPROVE")
    if stage == "EXECUTED":
        order = execute_order(order["id"])
    scenario["order"] = order
    return scenario


def setup_store_with_batch(
    batch_overrides: Optional[dict] = None,
    **scenario_kwargs,
) -> dict:
    """Market + product + store + one SCHEDULED label print batch."""
    scenario = setup_market_product_store(**scenario_kwargs)
    scenario["batch"] = new_label_batch(scenario["store"]["id"], **(batch_overrides or {}))
    return scenario
