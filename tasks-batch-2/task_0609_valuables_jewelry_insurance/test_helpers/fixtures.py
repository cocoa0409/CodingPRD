"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures. Every helper builds
its preconditions from scratch — the server database is empty before each test.

Identity threading: Policyholder and RepairShop are entity-backed roles, so any
ownership-gated call uses make_policyholder_headers(policyholder["id"]) /
make_repair_shop_headers(shop["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_policyholder_payload,
    create_risk_zone_payload,
    create_repair_shop_payload,
    create_appraisal_payload,
    create_policy_payload,
    create_scheduled_item_payload,
    create_endorsement_payload,
    create_claim_payload,
    create_payment_payload,
)
from .constants import DEFAULT_CLOCK_ISO, GENEROUS_PAYMENT_CENTS
from .test_users import (
    TEST_USERS,
    make_policyholder_headers,
    make_repair_shop_headers,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]
_AP = TEST_USERS["appraiser_headers"]


# ─── Tier 0: Atomic catalog helpers ───────────────────────────────────────

def set_clock(iso=DEFAULT_CLOCK_ISO, headers=None):
    """Set the logical clock. Returns the (null) data payload."""
    return get_success_data(api_client.set_clock(iso, headers or _UW))


def create_policyholder(email="holder@example.com", residence_zip="10001", **overrides):
    res = api_client.create_policyholder(
        create_policyholder_payload(email=email, residence_zip=residence_zip, **overrides),
        _UW,
    )
    return get_success_data(res)


def create_risk_zone(zip_prefix="100", rate_per_thousand_cents=300, **overrides):
    res = api_client.create_risk_zone(
        create_risk_zone_payload(
            zip_prefix=zip_prefix, rate_per_thousand_cents=rate_per_thousand_cents, **overrides
        ),
        _UW,
    )
    return get_success_data(res)


def create_repair_shop(name="Test Jeweler", service_zip="10005", in_network=True, **overrides):
    res = api_client.create_repair_shop(
        create_repair_shop_payload(
            name=name, service_zip=service_zip, in_network=in_network, **overrides
        ),
        _UW,
    )
    return get_success_data(res)


def create_appraisal(policyholder_id, appraised_value_cents=3000000, **overrides):
    res = api_client.create_appraisal(
        create_appraisal_payload(
            policyholder_id, appraised_value_cents=appraised_value_cents, **overrides
        ),
        _AP,
    )
    return get_success_data(res)


def create_policy(policyholder_id, **overrides):
    res = api_client.create_policy(create_policy_payload(policyholder_id, **overrides), _UW)
    return get_success_data(res)


def create_scheduled_item(policy_id, **overrides):
    res = api_client.create_scheduled_item(
        policy_id, create_scheduled_item_payload(**overrides), _UW
    )
    return get_success_data(res)


# ─── Tier 1: Policy state progression ─────────────────────────────────────

def setup_quoted_policy_with_item(
    item_overrides=None, policy_overrides=None, zone_overrides=None,
    create_zone=True, clock=DEFAULT_CLOCK_ISO,
):
    """Clock set + (optional) risk zone + policyholder + QUOTED policy + one PENDING item.

    Returns dict: {policyholder, policy, item}.
    """
    if clock is not None:
        set_clock(clock)
    if create_zone:
        create_risk_zone(**(zone_overrides or {}))
    ph = create_policyholder()
    policy = create_policy(ph["id"], **(policy_overrides or {}))
    item = create_scheduled_item(policy["id"], **(item_overrides or {}))
    return {"policyholder": ph, "policy": policy, "item": item}


def bind_policy(policy_id):
    res = api_client.bind_policy(policy_id, _UW)
    return get_success_data(res)


def setup_bound_policy_with_item(**kwargs):
    """QUOTED policy with one item, then bind -> BOUND. Returns dict with bound policy."""
    ctx = setup_quoted_policy_with_item(**kwargs)
    ctx["policy"] = bind_policy(ctx["policy"]["id"])
    return ctx


def pay_premium(policy_id, policyholder_id, amount_cents=GENEROUS_PAYMENT_CENTS):
    """Pay premium as the owning policyholder (ownership-gated)."""
    res = api_client.create_payment(
        policy_id,
        create_payment_payload(amount_cents),
        make_policyholder_headers(policyholder_id),
    )
    return get_success_data(res)


def setup_active_policy_with_item(payment_cents=GENEROUS_PAYMENT_CENTS, **kwargs):
    """QUOTED -> BOUND -> pay -> ACTIVE. Returns dict {policyholder, policy, item, payment}.

    The returned policy is re-read so coverage_status/billing_status reflect ACTIVE/PAID.
    """
    ctx = setup_bound_policy_with_item(**kwargs)
    payment = pay_premium(ctx["policy"]["id"], ctx["policyholder"]["id"], payment_cents)
    ctx["payment"] = payment
    ctx["policy"] = get_success_data(api_client.get_policy(ctx["policy"]["id"], _UW))
    return ctx


# ─── Tier 2: Claims ───────────────────────────────────────────────────────

def file_claim(policy_id, scheduled_item_id, **overrides):
    """File an FNOL claim as ClaimsAdjuster (a permitted filer)."""
    res = api_client.create_claim(
        policy_id, create_claim_payload(scheduled_item_id, **overrides), _CA
    )
    return get_success_data(res)


def setup_claim_under_review(claim_overrides=None, **kwargs):
    """ACTIVE policy + item; file claim and start_review -> UNDER_REVIEW (item SUSPENDED).

    Returns dict {policyholder, policy, item, claim} where claim is the post-review state.
    """
    ctx = setup_active_policy_with_item(**kwargs)
    claim = file_claim(ctx["policy"]["id"], ctx["item"]["id"], **(claim_overrides or {}))
    ctx["claim"] = get_success_data(
        api_client.start_review_claim(ctx["policy"]["id"], claim["id"], _CA)
    )
    return ctx


def approve_claim(policy_id, claim_id, expected_claim_version):
    res = api_client.approve_claim(
        policy_id, claim_id, {"expected_claim_version": expected_claim_version}, _CA
    )
    return get_success_data(res)


def setup_approved_claim(claim_overrides=None, **kwargs):
    """ACTIVE policy + claim driven through start_review -> approve (UNDER_REVIEW version
    used for OCC). Returns dict {policyholder, policy, item, claim}."""
    ctx = setup_claim_under_review(claim_overrides=claim_overrides, **kwargs)
    claim_v = ctx["claim"]["version"]
    ctx["claim"] = approve_claim(ctx["policy"]["id"], ctx["claim"]["id"], claim_v)
    return ctx


# ─── Tier 3: Repair-order lifecycle (partial-damage path) ─────────────────

def setup_repair_order_assigned(shop_in_network=True, claimed_amount_cents=300000, **kwargs):
    """ACTIVE policy + APPROVED PARTIAL_DAMAGE claim + an in-network RepairShop +
    an assigned RepairOrder (ASSIGNED). Returns dict {policyholder, policy, item, claim,
    shop, repair_order}.
    """
    shop = create_repair_shop(in_network=shop_in_network)
    claim_overrides = {
        "peril": "ACCIDENTAL_DAMAGE",
        "loss_type": "PARTIAL_DAMAGE",
        "claimed_amount_cents": claimed_amount_cents,
    }
    ctx = setup_approved_claim(claim_overrides=claim_overrides, **kwargs)
    ctx["shop"] = shop
    res = api_client.assign_repair_order(
        ctx["policy"]["id"], ctx["claim"]["id"], {"repair_shop_id": shop["id"]}, _CA
    )
    ctx["repair_order"] = get_success_data(res)
    return ctx


def accept_repair_order(policy_id, claim_id, shop_id):
    res = api_client.accept_repair_order(
        policy_id, claim_id, make_repair_shop_headers(shop_id)
    )
    return get_success_data(res)


def setup_repair_order_in_progress(**kwargs):
    """As setup_repair_order_assigned, then the assigned shop accepts -> IN_PROGRESS."""
    ctx = setup_repair_order_assigned(**kwargs)
    ctx["repair_order"] = accept_repair_order(
        ctx["policy"]["id"], ctx["claim"]["id"], ctx["shop"]["id"]
    )
    return ctx


# ─── Tier 4: Premium-targeted dual/compound policies ──────────────────────

def setup_active_inflation_policy(
    inflation_guard_mode, inflation_guard_pct, valuation_basis="AGREED_VALUE",
    scheduled_value_cents=1000000, clock=DEFAULT_CLOCK_ISO, zone_rate=300,
    create_zone=True, email="ifl@example.com",
):
    """An ACTIVE+PAID policy carrying one RING under a given inflation guard, ready for
    clock-advance revaluation. Returns dict {policyholder, policy, item}.
    """
    if clock is not None:
        set_clock(clock)
    if create_zone:
        create_risk_zone(rate_per_thousand_cents=zone_rate)
    ph = create_policyholder(email=email)
    policy = create_policy(
        ph["id"],
        valuation_basis=valuation_basis,
        inflation_guard_mode=inflation_guard_mode,
        inflation_guard_pct=inflation_guard_pct,
    )
    item = create_scheduled_item(
        policy["id"], scheduled_value_cents=scheduled_value_cents
    )
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])
    policy = get_success_data(api_client.get_policy(policy["id"], _UW))
    return {"policyholder": ph, "policy": policy, "item": item}


# ─── Tier 5: Endorsement drafting ─────────────────────────────────────────

def draft_endorsement(policy_id, endorsement_type, **overrides):
    res = api_client.create_endorsement(
        policy_id, create_endorsement_payload(endorsement_type, **overrides), _UW
    )
    return get_success_data(res)


def live_policy_version(policy_id):
    """Re-read the policy and return its current version (for OCC apply calls)."""
    return get_success_data(api_client.get_policy(policy_id, _UW))["version"]
