"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty database) before
every individual test. All setup calls use get_success_data() so a broken
precondition surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_account_holder_headers
from .factories import (
    create_account_payload, create_subscription_payload, create_credit_adjustment_payload,
    create_contact_payload, create_card_payload, create_gift_item_payload,
    create_artist_payload, create_order_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STUDIO = TEST_USERS["studio_operator_headers"]


def holder(account_id: str) -> dict:
    """Ownership-correct AccountHolder headers for the given account."""
    return make_account_holder_headers(account_id)


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def set_clock(iso: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


def run_scheduler() -> dict:
    return get_success_data(api_client.run_scheduler(ADMIN))


def new_account() -> dict:
    return get_success_data(api_client.create_account(create_account_payload(), ADMIN))


def new_subscription(account_id: str, tier: str) -> dict:
    return get_success_data(
        api_client.create_subscription(account_id, create_subscription_payload(tier), ADMIN)
    )


def grant_credits(account_id: str, delta: int, reason: str = "MANUAL_ADJUST") -> dict:
    return get_success_data(
        api_client.create_credit_adjustment(
            account_id, create_credit_adjustment_payload(delta, reason), ADMIN
        )
    )


def new_contact(account_id: str, region: str = "CA", verified: bool = False, **overrides) -> dict:
    contact = get_success_data(
        api_client.create_contact(create_contact_payload(account_id, region=region, **overrides), holder(account_id))
    )
    if verified:
        contact = verify_contact(contact["id"], "VERIFIED")
    return contact


def verify_contact(contact_id: str, result: str = "VERIFIED") -> dict:
    return get_success_data(api_client.verify_address(contact_id, {"result": result}, STUDIO))


def new_card(**kwargs) -> dict:
    return get_success_data(api_client.create_card(create_card_payload(**kwargs), ADMIN))


def retire_card(card_id: str) -> dict:
    return get_success_data(api_client.retire_card(card_id, ADMIN))


def new_gift_item(**kwargs) -> dict:
    return get_success_data(api_client.create_gift_item(create_gift_item_payload(**kwargs), ADMIN))


def retire_gift_item(gift_item_id: str) -> dict:
    return get_success_data(api_client.retire_gift_item(gift_item_id, ADMIN))


def new_artist(daily_capacity: int = 5, region_code: str = "CA") -> dict:
    return get_success_data(
        api_client.create_artist(create_artist_payload(daily_capacity=daily_capacity, region_code=region_code), ADMIN)
    )


def account_version(account_id: str) -> int:
    return get_success_data(api_client.get_account(account_id, ADMIN))["version"]


def account_balance(account_id: str) -> int:
    return get_success_data(api_client.get_account(account_id, ADMIN))["card_credit_balance"]


def new_order(account_id: str, contact_id: str, card_id: str, **kwargs) -> dict:
    payload = create_order_payload(account_id, contact_id, card_id, **kwargs)
    return get_success_data(api_client.create_order(payload, holder(account_id)))


def submit(account_id: str, order_id: str) -> dict:
    version = account_version(account_id)
    return get_success_data(
        api_client.submit_order(order_id, {"expected_account_version": version}, holder(account_id))
    )


def pending_proof(account_id: str, order_id: str) -> dict:
    proofs = get_success_data(api_client.list_order_proofs(order_id, holder(account_id)))
    assert proofs, "expected a live proof for the submitted order"
    return proofs[0]


def approve(account_id: str, proof_id: str) -> dict:
    return get_success_data(api_client.approve_proof(proof_id, holder(account_id)))


def schedule(order_id: str) -> dict:
    return get_success_data(api_client.schedule_order(order_id, STUDIO))


def reserve_artist(order_id: str, artist_id: str,
                   window_start: str = "2026-04-01T09:00:00Z",
                   window_end: str = "2026-04-01T11:00:00Z") -> dict:
    return get_success_data(
        api_client.assign_artist(
            order_id, {"artist_id": artist_id, "window_start": window_start, "window_end": window_end}, STUDIO
        )
    )


def produce(order_id: str) -> dict:
    return get_success_data(api_client.produce_order(order_id, STUDIO))


def mail(order_id: str, carrier: str = "USPS") -> dict:
    return get_success_data(api_client.mail_order(order_id, {"carrier": carrier}, STUDIO))


def order_shipment(account_id: str, order_id: str) -> dict:
    ships = get_success_data(api_client.get_order_shipment(order_id, holder(account_id)))
    assert ships, "expected a shipment for the mailed order"
    return ships[0]


# --------------------------------------------------------------------------
# Composite pipeline
# --------------------------------------------------------------------------
_STAGES = [
    "draft", "submitted", "approved", "scheduled", "assigned",
    "produced", "mailed", "in_transit", "delivered",
]


def build_pipeline(
    stage: str = "submitted",
    *,
    tier: str = "PRO",
    extra_credits: int = 0,
    region: str = "CA",
    verify: bool = True,
    card_kwargs: dict = None,
    gift_kwargs: dict = None,
    gift_quantity: int = 0,
    scheduled_send_at: str = "2026-04-01T00:00:00Z",
    produce_clock: str = "2026-04-01T00:00:00Z",
    carrier: str = "USPS",
    need_artist: bool = True,
    window_start: str = "2026-04-01T09:00:00Z",
    window_end: str = "2026-04-01T11:00:00Z",
) -> dict:
    """Drive an order through the fulfillment pipeline up to ``stage``.

    Returns a context dict with the built entities and their ids. Stages, in
    order: draft, submitted, approved, scheduled, assigned, produced, mailed,
    in_transit, delivered.
    """
    assert stage in _STAGES, f"unknown stage {stage!r}"
    ctx: dict = {}

    account = new_account()
    account_id = account["id"]
    ctx["account"] = account
    ctx["account_id"] = account_id

    if tier is not None:
        ctx["subscription"] = new_subscription(account_id, tier)
    if extra_credits:
        grant_credits(account_id, extra_credits)

    contact = new_contact(account_id, region=region, verified=verify)
    ctx["contact"] = contact
    ctx["contact_id"] = contact["id"]

    card = new_card(**(card_kwargs or {}))
    ctx["card"] = card
    ctx["card_id"] = card["id"]

    order_kwargs = {"scheduled_send_at": scheduled_send_at}
    if gift_kwargs is not None:
        gift = new_gift_item(**gift_kwargs)
        ctx["gift"] = gift
        ctx["gift_id"] = gift["id"]
        order_kwargs["gift_item_id"] = gift["id"]
        order_kwargs["gift_quantity"] = gift_quantity

    order = new_order(account_id, contact["id"], card["id"], **order_kwargs)
    ctx["order"] = order
    ctx["order_id"] = order["id"]
    if stage == "draft":
        return ctx

    submit(account_id, order["id"])
    proof = pending_proof(account_id, order["id"])
    ctx["proof"] = proof
    ctx["proof_id"] = proof["id"]
    if stage == "submitted":
        return ctx

    approve(account_id, proof["id"])
    if stage == "approved":
        return ctx

    schedule(order["id"])
    if stage == "scheduled":
        return ctx

    if need_artist:
        artist = new_artist()
        ctx["artist"] = artist
        ctx["artist_id"] = artist["id"]
        assignment = reserve_artist(order["id"], artist["id"], window_start, window_end)
        ctx["assignment"] = assignment
        ctx["assignment_id"] = assignment["id"]
    if stage == "assigned":
        return ctx

    set_clock(produce_clock)
    produce(order["id"])
    if stage == "produced":
        return ctx

    mail(order["id"], carrier)
    shipment = order_shipment(account_id, order["id"])
    ctx["shipment"] = shipment
    ctx["shipment_id"] = shipment["id"]
    if stage == "mailed":
        return ctx

    get_success_data(api_client.advance_shipment(shipment["id"], {"to_status": "IN_TRANSIT"}, STUDIO))
    if stage == "in_transit":
        return ctx

    get_success_data(api_client.advance_shipment(shipment["id"], {"to_status": "DELIVERED"}, STUDIO))
    return ctx
