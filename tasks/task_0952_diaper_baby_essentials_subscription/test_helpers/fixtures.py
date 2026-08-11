"""Composite setup helpers.

Every fixture builds its state exclusively through PRD-declared endpoints —
the server is assumed to boot with an empty database and is never seeded
directly.  Setup calls use the lenient ``get_success_data`` validator so a
broken precondition surfaces as "Setup step failed" rather than as a
confusing assertion inside the test body.

Identity discipline: the registry owner, the gift purchaser and the
subscription account holder are three DISTINCT accounts in this domain.
Every ownership-gated call threads the real account id through the matching
per-instance header builder.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import BASE_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_child_payload,
    create_gift_order_payload,
    create_plan_payload,
    create_registry_item_payload,
    create_registry_payload,
    create_sku_payload,
    create_subscription_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
    make_anonymous_headers,
    make_gift_purchaser_headers,
    make_registry_owner_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
OPS2 = TEST_USERS["ops_admin_2_headers"]
SUPPORT = TEST_USERS["support_agent_headers"]
SUPPORT2 = TEST_USERS["support_agent_2_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ==========================================================================
# Tier 0 — primitives
# ==========================================================================
def set_clock(api, to_iso8601: str) -> str:
    """Move the logical clock and return the new current_utc it reports."""
    data = get_success_data(api.set_clock(to_iso8601, OPS))
    return data.get("current_utc")


def make_plan(api, **overrides) -> dict:
    return get_success_data(api.create_plan(create_plan_payload(**overrides), OPS))


def make_sku(api, **overrides) -> dict:
    return get_success_data(api.create_sku(create_sku_payload(**overrides), OPS))


def register_account(api, **overrides) -> dict:
    """Register a household in PENDING_VERIFICATION.

    Returns the created Account payload — it is the only moment the server
    hands out ``verification_token``.
    """
    return get_success_data(api.create_account(create_account_payload(**overrides), ANON))


def register_and_verify_account(api, **overrides) -> dict:
    """Register then verify a household; returns the verified Account read."""
    created = register_account(api, **overrides)
    get_success_data(
        api.verify_account(created["id"], created["verification_token"], ANON)
    )
    verified = get_success_data(
        api.get_account(created["id"], make_account_holder_headers(created["id"]))
    )
    # Preserve the one-time token and code from the creation response.
    verified["verification_token_at_creation"] = created["verification_token"]
    verified["referral_code"] = created.get("referral_code", verified.get("referral_code"))
    verified["loyalty_account_id"] = created.get(
        "loyalty_account_id", verified.get("loyalty_account_id")
    )
    return verified


def make_child(api, account, **overrides) -> dict:
    account_id = account["id"] if isinstance(account, dict) else account
    return get_success_data(
        api.create_child(
            create_child_payload(account_id, **overrides),
            make_account_holder_headers(account_id),
        )
    )


def make_subscription(api, account, plan, child, **overrides) -> dict:
    account_id = account["id"] if isinstance(account, dict) else account
    return get_success_data(
        api.create_subscription(
            create_subscription_payload(
                account_id,
                plan["id"] if isinstance(plan, dict) else plan,
                child["id"] if isinstance(child, dict) else child,
                **overrides,
            ),
            make_account_holder_headers(account_id),
        )
    )


def activate(api, account_id, subscription_id) -> dict:
    return get_success_data(
        api.activate_subscription(subscription_id, make_account_holder_headers(account_id))
    )


def issue_goodwill_credit(api, account_id, issued_cents, **overrides) -> dict:
    payload = {"account_id": account_id, "issued_cents": issued_cents}
    payload.update(overrides)
    return get_success_data(api.issue_credit(payload, SUPPORT))


# ==========================================================================
# Tier 1 — a live Pipeline-R household
# ==========================================================================
def setup_household(
    api,
    *,
    clock=BASE_CLOCK_UTC,
    plan_overrides=None,
    sku_overrides=None,
    account_overrides=None,
    child_overrides=None,
    subscription_overrides=None,
    with_sku=True,
    activate_subscription=True,
    email_prefix="household",
):
    """Clock + plan + (optional) SKU + verified account + child + subscription.

    Returns a dict with keys: ``plan``, ``sku``, ``account``, ``account_id``,
    ``headers`` (AccountHolder headers for that account), ``child``,
    ``subscription``, ``loyalty_account_id``.
    """
    set_clock(api, clock)
    plan = make_plan(api, **(plan_overrides or {}))
    sku = make_sku(api, **(sku_overrides or {})) if with_sku else None

    acct_payload = {"email": unique_email(email_prefix), "payment_method_on_file": True}
    acct_payload.update(account_overrides or {})
    account = register_and_verify_account(api, **acct_payload)
    headers = make_account_holder_headers(account["id"])

    child = make_child(api, account, **(child_overrides or {}))
    subscription = make_subscription(
        api, account, plan, child, **(subscription_overrides or {})
    )
    if activate_subscription:
        subscription = activate(api, account["id"], subscription["id"])

    return {
        "plan": plan,
        "sku": sku,
        "account": account,
        "account_id": account["id"],
        "headers": headers,
        "child": child,
        "subscription": subscription,
        "loyalty_account_id": account["loyalty_account_id"],
    }


def add_second_child_and_subscription(api, ctx, *, child_overrides=None,
                                      subscription_overrides=None):
    """A second child and its own ACTIVE subscription on the same household."""
    overrides = {"name": "Ken"}
    overrides.update(child_overrides or {})
    child = make_child(api, ctx["account"], **overrides)
    subscription = make_subscription(
        api, ctx["account"], ctx["plan"], child, **(subscription_overrides or {})
    )
    subscription = activate(api, ctx["account_id"], subscription["id"])
    return child, subscription


# ==========================================================================
# Tier 2 — cycle lifecycle shortcuts
# ==========================================================================
def generate_cycle(api, subscription_id) -> dict:
    return get_success_data(api.generate_cycle(subscription_id, OPS))


def allocate_cycle(api, cycle_id) -> dict:
    return get_success_data(api.allocate_cycle(cycle_id, OPS))


def lock_cycle(api, cycle_id) -> dict:
    return get_success_data(api.lock_cycle(cycle_id, OPS))


def charge_cycle(api, cycle_id, payload=None) -> dict:
    return get_success_data(api.charge_cycle(cycle_id, OPS, payload))


def dispatch_cycle(api, cycle_id, service_level="STANDARD") -> dict:
    return get_success_data(
        api.dispatch_cycle(cycle_id, OPS, {"service_level": service_level})
    )


def deliver_cycle(api, cycle_id) -> dict:
    return get_success_data(api.deliver_cycle(cycle_id, OPS))


def first_cycle_line(api, cycle_id) -> dict:
    data = get_success_data(api.list_cycle_lines(OPS, {"cycle_id": cycle_id}))
    assert data, f"Setup expected at least one cycle line on cycle {cycle_id}"
    return data[0]


def cycle_lines(api, cycle_id) -> list:
    return get_success_data(api.list_cycle_lines(OPS, {"cycle_id": cycle_id}))


def shipment_for_cycle(api, cycle_id) -> dict:
    data = get_success_data(api.list_shipments(OPS, {"cycle_id": cycle_id}))
    assert data, f"Setup expected a shipment for cycle {cycle_id}"
    return data[0]


def shipment_for_gift(api, gift_order_id) -> dict:
    data = get_success_data(api.list_shipments(OPS, {"gift_order_id": gift_order_id}))
    assert data, f"Setup expected a shipment for gift order {gift_order_id}"
    return data[0]


def setup_allocated_cycle(api, **kwargs):
    """A live household whose first cycle is ALLOCATED. Returns (ctx, cycle)."""
    ctx = setup_household(api, **kwargs)
    cycle = generate_cycle(api, ctx["subscription"]["id"])
    cycle = allocate_cycle(api, cycle["id"])
    return ctx, cycle


def setup_charged_cycle(api, *, lock_at=None, **kwargs):
    """Allocated cycle, optionally locked at ``lock_at``, then charged."""
    ctx, cycle = setup_allocated_cycle(api, **kwargs)
    if lock_at is not None:
        set_clock(api, lock_at)
        cycle = lock_cycle(api, cycle["id"])
    cycle = charge_cycle(api, cycle["id"])
    return ctx, cycle


def setup_dispatched_cycle(api, *, lock_at="2026-06-08T00:00:00Z",
                           service_level="STANDARD", **kwargs):
    """Allocated -> locked -> charged -> dispatched. Returns (ctx, cycle, shipment)."""
    ctx, cycle = setup_charged_cycle(api, lock_at=lock_at, **kwargs)
    cycle = dispatch_cycle(api, cycle["id"], service_level)
    shipment = shipment_for_cycle(api, cycle["id"])
    return ctx, cycle, shipment


def setup_delivered_cycle(api, *, lock_at="2026-06-08T00:00:00Z", **kwargs):
    """The full Pipeline-R chain through cycle delivery. Returns (ctx, cycle)."""
    ctx, cycle, _shipment = setup_dispatched_cycle(api, lock_at=lock_at, **kwargs)
    cycle = deliver_cycle(api, cycle["id"])
    return ctx, cycle


def setup_shipment_in_transit(api, *, service_level="STANDARD", **kwargs):
    """Dispatched cycle whose shipment has been picked and handed to the carrier."""
    ctx, cycle, shipment = setup_dispatched_cycle(
        api, service_level=service_level, **kwargs
    )
    get_success_data(api.pick_shipment(shipment["id"], OPS))
    shipment = get_success_data(api.transit_shipment(shipment["id"], OPS))
    return ctx, cycle, shipment


# ==========================================================================
# Tier 3 — accumulation / threshold targeting
# ==========================================================================
def setup_cycle_line_pending_by_allergen(api, *, sku_specs, allergen_tag="FRAGRANCE",
                                         severity="SEVERE", **kwargs):
    """Allocate onto the cheapest SKU, then flag an allergen that disqualifies it.

    ``sku_specs`` is an ordered list of ``create_sku_payload`` override dicts;
    they are created in the order given so creation order is a usable
    tie-break.  Returns ``(ctx, cycle, line, skus)``.
    """
    set_clock(api, kwargs.pop("clock", BASE_CLOCK_UTC))
    plan = make_plan(api, **(kwargs.pop("plan_overrides", None) or {}))
    skus = [make_sku(api, **spec) for spec in sku_specs]

    acct_payload = {"email": unique_email("subst"), "payment_method_on_file": True}
    acct_payload.update(kwargs.pop("account_overrides", None) or {})
    account = register_and_verify_account(api, **acct_payload)
    child = make_child(api, account, **(kwargs.pop("child_overrides", None) or {}))
    subscription = make_subscription(
        api, account, plan, child, **(kwargs.pop("subscription_overrides", None) or {})
    )
    subscription = activate(api, account["id"], subscription["id"])

    cycle = generate_cycle(api, subscription["id"])
    cycle = allocate_cycle(api, cycle["id"])
    line = first_cycle_line(api, cycle["id"])

    get_success_data(
        api.create_allergen_flag(
            child["id"],
            {"allergen_tag": allergen_tag, "severity": severity},
            make_account_holder_headers(account["id"]),
        )
    )
    line = get_success_data(api.get_cycle_line(line["id"], OPS))

    ctx = {
        "plan": plan,
        "skus": skus,
        "account": account,
        "account_id": account["id"],
        "headers": make_account_holder_headers(account["id"]),
        "child": child,
        "subscription": subscription,
        "loyalty_account_id": account["loyalty_account_id"],
    }
    return ctx, cycle, line, skus


def add_allergen_flag(api, ctx, allergen_tag, severity="SEVERE", note=None):
    payload = {"allergen_tag": allergen_tag, "severity": severity}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api.create_allergen_flag(ctx["child"]["id"], payload, ctx["headers"])
    )


def substitute_line(api, line_id) -> dict:
    return get_success_data(api.substitute_cycle_line(line_id, OPS))


# ==========================================================================
# Tier 4 — the registry and gift pipeline
# ==========================================================================
def setup_registry_parties(api, *, clock=BASE_CLOCK_UTC, sku_overrides=None,
                           owner_overrides=None, purchaser_overrides=None,
                           with_plan=False, plan_overrides=None):
    """Two DISTINCT verified accounts — a registry owner and a gift purchaser.

    Returns a dict with ``owner``, ``owner_id``, ``owner_headers`` (RegistryOwner
    role), ``owner_account_headers`` (AccountHolder role on the same account),
    ``purchaser``, ``purchaser_id``, ``purchaser_headers`` (GiftPurchaser role),
    ``child``, ``sku`` and optionally ``plan``.
    """
    set_clock(api, clock)
    plan = make_plan(api, **(plan_overrides or {})) if with_plan else None
    sku = make_sku(api, **(sku_overrides or {}))

    owner_payload = {"email": unique_email("owner"), "payment_method_on_file": True}
    owner_payload.update(owner_overrides or {})
    owner = register_and_verify_account(api, **owner_payload)

    purchaser_payload = {"email": unique_email("purchaser"), "payment_method_on_file": True}
    purchaser_payload.update(purchaser_overrides or {})
    purchaser = register_and_verify_account(api, **purchaser_payload)

    child = make_child(api, owner)

    return {
        "plan": plan,
        "sku": sku,
        "owner": owner,
        "owner_id": owner["id"],
        "owner_headers": make_registry_owner_headers(owner["id"]),
        "owner_account_headers": make_account_holder_headers(owner["id"]),
        "purchaser": purchaser,
        "purchaser_id": purchaser["id"],
        "purchaser_headers": make_gift_purchaser_headers(purchaser["id"]),
        "child": child,
    }


def make_registry(api, parties, **overrides) -> dict:
    return get_success_data(
        api.create_registry(
            create_registry_payload(
                parties["owner_id"], parties["child"]["id"], **overrides
            ),
            parties["owner_headers"],
        )
    )


def make_registry_item(api, parties, registry_id, sku_id=None, requested_quantity=2) -> dict:
    return get_success_data(
        api.create_registry_item(
            registry_id,
            create_registry_item_payload(
                sku_id or parties["sku"]["id"], requested_quantity
            ),
            parties["owner_headers"],
        )
    )


def setup_open_registry(api, *, requested_quantity=2, **kwargs):
    """Parties + a registry OPEN with one item. Returns (parties, registry, item)."""
    parties = setup_registry_parties(api, **kwargs)
    registry = make_registry(api, parties)
    item = make_registry_item(
        api, parties, registry["id"], requested_quantity=requested_quantity
    )
    registry = get_success_data(
        api.open_registry(registry["id"], parties["owner_headers"])
    )
    item = get_success_data(api.get_registry_item(item["id"], parties["owner_headers"]))
    return parties, registry, item


def reserve_gift(api, parties, item, quantity=1, **overrides) -> dict:
    """Reserve a gift using the item's CURRENT version, as OCC demands."""
    fresh = get_success_data(
        api.get_registry_item(item["id"], parties["purchaser_headers"])
    )
    return get_success_data(
        api.create_gift_order(
            create_gift_order_payload(
                fresh["id"], parties["purchaser_id"], quantity, fresh["version"],
                **overrides,
            ),
            parties["purchaser_headers"],
        )
    )


def pay_gift(api, parties, gift_order_id) -> dict:
    return get_success_data(
        api.pay_gift_order(gift_order_id, parties["purchaser_headers"])
    )


def setup_paid_gift(api, *, quantity=1, requested_quantity=2, **kwargs):
    """Open registry + one reserved and PAID gift. Returns (parties, registry, item, gift)."""
    parties, registry, item = setup_open_registry(
        api, requested_quantity=requested_quantity, **kwargs
    )
    gift = reserve_gift(api, parties, item, quantity)
    gift = pay_gift(api, parties, gift["id"])
    item = get_success_data(api.get_registry_item(item["id"], parties["owner_headers"]))
    return parties, registry, item, gift


def claim_gift(api, parties, gift_order_id, claim_mode="CREDIT", service_level=None) -> dict:
    payload = {"claim_mode": claim_mode}
    if service_level is not None:
        payload["service_level"] = service_level
    return get_success_data(
        api.claim_gift_order(gift_order_id, payload, parties["owner_headers"])
    )


def gift_credit_of(api, parties) -> dict:
    data = get_success_data(
        api.list_credits(
            parties["owner_account_headers"],
            {"account_id": parties["owner_id"], "credit_type": "GIFT"},
        )
    )
    assert data, "Setup expected a GIFT credit on the registry owner's account"
    return data[0]


# ==========================================================================
# Tier 5 — refunds and settlement
# ==========================================================================
def open_cycle_refund(api, account_id, cycle_id, reason="CANCEL") -> dict:
    return get_success_data(
        api.create_cycle_refund_request(
            cycle_id, reason, make_account_holder_headers(account_id)
        )
    )


def approve_refund(api, refund_id, headers=None) -> dict:
    return get_success_data(api.approve_refund(refund_id, headers or SUPPORT))


def settle_refund(api, refund_id, headers=None) -> dict:
    return get_success_data(api.settle_refund(refund_id, headers or OPS))


def refund_for_cycle(api, cycle_id) -> dict:
    data = get_success_data(api.list_refunds(OPS, {"cycle_id": cycle_id}))
    assert data, f"Setup expected a refund on cycle {cycle_id}"
    return data[0]


def setup_approved_cycle_refund(api, *, reason="CANCEL", **kwargs):
    """Charged cycle with a REQUESTED-then-APPROVED refund. Returns (ctx, cycle, refund)."""
    ctx, cycle = setup_charged_cycle(api, **kwargs)
    refund = open_cycle_refund(api, ctx["account_id"], cycle["id"], reason)
    refund = approve_refund(api, refund["id"])
    return ctx, cycle, refund


# ==========================================================================
# Read-back conveniences
# ==========================================================================
def read_cycle(api, cycle_id) -> dict:
    return get_success_data(api.get_cycle(cycle_id, OPS))


def read_subscription(api, subscription_id) -> dict:
    return get_success_data(api.get_subscription(subscription_id, OPS))


def read_account(api, account_id) -> dict:
    return get_success_data(
        api.get_account(account_id, make_account_holder_headers(account_id))
    )


def read_child(api, child_id, account_id) -> dict:
    return get_success_data(
        api.get_child(child_id, make_account_holder_headers(account_id))
    )


def read_credit(api, credit_id, account_id) -> dict:
    return get_success_data(
        api.get_credit(credit_id, make_account_holder_headers(account_id))
    )


def read_cycle_line(api, line_id) -> dict:
    return get_success_data(api.get_cycle_line(line_id, OPS))


def read_loyalty_account(api, loyalty_account_id) -> dict:
    return get_success_data(api.get_loyalty_account(loyalty_account_id, OPS))


def read_registry(api, registry_id, headers) -> dict:
    return get_success_data(api.get_registry(registry_id, headers))


def read_registry_item(api, item_id, headers) -> dict:
    return get_success_data(api.get_registry_item(item_id, headers))


def read_gift_order(api, gift_order_id, headers) -> dict:
    return get_success_data(api.get_gift_order(gift_order_id, headers))


def read_refund(api, refund_id) -> dict:
    return get_success_data(api.get_refund(refund_id, OPS))


def read_shipment(api, shipment_id) -> dict:
    return get_success_data(api.get_shipment(shipment_id, OPS))


def list_resize_events(api, subscription_id, **filters) -> list:
    params = {"subscription_id": subscription_id}
    params.update(filters)
    return get_success_data(api.list_resize_events(OPS, params))


def list_substitution_events(api, cycle_line_id) -> list:
    return get_success_data(
        api.list_substitution_events(OPS, {"cycle_line_id": cycle_line_id})
    )


def list_skip_records(api, **filters) -> list:
    return get_success_data(api.list_skip_records(OPS, filters))


def list_points_entries(api, loyalty_account_id, **filters) -> list:
    params = {"loyalty_account_id": loyalty_account_id}
    params.update(filters)
    return get_success_data(api.list_points_ledger_entries(OPS, params))


def list_credits_of(api, account_id, **filters) -> list:
    params = {"account_id": account_id}
    params.update(filters)
    return get_success_data(
        api.list_credits(make_account_holder_headers(account_id), params)
    )


def list_referrals(api, **filters) -> list:
    return get_success_data(api.list_referrals(OPS, filters))
