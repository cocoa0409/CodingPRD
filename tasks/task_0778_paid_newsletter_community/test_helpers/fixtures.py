"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Fixtures use get_success_data() (lenient) so setup failures surface clearly.

Identity threading: Member is entity_backed, so ownership-gated member calls
always pass make_member_headers(member["id"]). Creator ownership is keyed on the
X-User-ID recorded as creator_user_id, so a publication and all its children are
driven by the same make_creator_headers(creator_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import TEST_USERS, make_creator_headers, make_member_headers
from .constants import DEFAULT_CLOCK_UTC

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------

def set_clock(api, iso: str):
    """Set the server logical clock (PlatformAdmin)."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


def reset_clock(api):
    """Reset the logical clock to its startup default."""
    return set_clock(api, DEFAULT_CLOCK_UTC)


def new_publication(api, creator_id="creator_1", name="Pub", **overrides) -> dict:
    payload = {"name": name}
    payload.update(overrides)
    return get_success_data(api.create_publication(payload, make_creator_headers(creator_id)))


def new_tier(api, pub_id, tier_rank, monthly_price_cents, trial_days=0,
             name=None, creator_id="creator_1") -> dict:
    payload = {
        "name": name or f"Tier{tier_rank}",
        "tier_rank": tier_rank,
        "monthly_price_cents": monthly_price_cents,
        "trial_days": trial_days,
    }
    return get_success_data(api.create_tier(pub_id, payload, make_creator_headers(creator_id)))


def new_member(api, pub_id, email="m@x.com", display_name="M") -> dict:
    """Create a PENDING member (self-signup)."""
    return get_success_data(
        api.create_member(pub_id, {"email": email, "display_name": display_name}, ANON)
    )


def new_verified_member(api, pub_id, email="m@x.com", display_name="M") -> dict:
    """Create a member and verify it -> VERIFIED."""
    member = new_member(api, pub_id, email, display_name)
    get_success_data(
        api.verify_member(member["id"], {"verification_token": member["verification_token"]}, ANON)
    )
    return member


def new_post(api, pub_id, creator_id="creator_1", publish=True, **overrides) -> dict:
    payload = {
        "title": "T",
        "body": "B",
        "content_type": "POST",
        "min_tier_rank": 0,
    }
    payload.update(overrides)
    post = get_success_data(api.create_post(pub_id, payload, make_creator_headers(creator_id)))
    if publish:
        post = get_success_data(api.publish_post(post["id"], make_creator_headers(creator_id)))
    return post


def new_event(api, pub_id, creator_id="creator_1", **overrides) -> dict:
    payload = {
        "title": "E",
        "starts_at": "2026-04-01T10:00:00Z",
        "ends_at": "2026-04-01T11:00:00Z",
        "registration_closes_at": "2026-03-31T00:00:00Z",
        "capacity": 1,
        "min_tier_rank": 0,
        "allow_waitlist": True,
    }
    payload.update(overrides)
    return get_success_data(api.create_event(pub_id, payload, make_creator_headers(creator_id)))


# --------------------------------------------------------------------------
# Invoice helpers
# --------------------------------------------------------------------------

def list_invoices_for(api, sub_id) -> list:
    resp = api.list_invoices(ADMIN, params={"subscription_id": sub_id})
    return get_success_data(resp)


def initial_invoice_id(api, sub_id) -> str:
    invoices = list_invoices_for(api, sub_id)
    return invoices[0]["id"]


def find_invoice_by_reason(api, sub_id, reason: str) -> dict:
    for inv in list_invoices_for(api, sub_id):
        if inv["reason"] == reason:
            return inv
    raise AssertionError(f"Setup failed: no {reason} invoice for subscription {sub_id}")


def simulate_payment(api, invoice_id, outcome) -> dict:
    return get_success_data(
        api.simulate_payment({"invoice_id": invoice_id, "outcome": outcome}, ADMIN)
    )


# --------------------------------------------------------------------------
# Subscription builders
# --------------------------------------------------------------------------

def subscribe(api, member_id, tier_id) -> dict:
    """Create a raw subscription as the member (ownership-gated)."""
    return get_success_data(
        api.create_subscription(member_id, {"tier_id": tier_id}, make_member_headers(member_id))
    )


def new_free_subscriber(api, pub_id, free_tier_id, email="m@x.com", display_name="M") -> dict:
    """Verified member + ACTIVE free subscription (rank 0). Returns
    {member, subscription}."""
    member = new_verified_member(api, pub_id, email, display_name)
    sub = subscribe(api, member["id"], free_tier_id)
    return {"member": member, "subscription": sub}


def new_paid_subscriber(api, pub_id, tier_id, email="m@x.com", display_name="M") -> dict:
    """Verified member + paid subscription whose INITIAL invoice is PAID, so the
    subscription is ACTIVE. Returns {member, subscription, initial_invoice}."""
    member = new_verified_member(api, pub_id, email, display_name)
    sub = subscribe(api, member["id"], tier_id)
    inv_id = initial_invoice_id(api, sub["id"])
    invoice = simulate_payment(api, inv_id, "SUCCEEDED")
    sub = get_success_data(api.get_subscription(sub["id"], make_member_headers(member["id"])))
    return {"member": member, "subscription": sub, "initial_invoice": invoice}


def new_trialing_paid_subscriber(api, pub_id, tier_id, email="m@x.com", display_name="M") -> dict:
    """Verified member + paid subscription still TRIALING with an OPEN INITIAL
    invoice (unpaid). Returns {member, subscription, initial_invoice_id}."""
    member = new_verified_member(api, pub_id, email, display_name)
    sub = subscribe(api, member["id"], tier_id)
    inv_id = initial_invoice_id(api, sub["id"])
    return {"member": member, "subscription": sub, "initial_invoice_id": inv_id}


def sub_version(api, sub_id, member_id) -> int:
    sub = get_success_data(api.get_subscription(sub_id, make_member_headers(member_id)))
    return sub["version"]


def pub_version(api, pub_id, creator_id="creator_1") -> int:
    pub = get_success_data(api.get_publication(pub_id, make_creator_headers(creator_id)))
    return pub["version"]


def get_pub(api, pub_id, creator_id="creator_1") -> dict:
    return get_success_data(api.get_publication(pub_id, make_creator_headers(creator_id)))


# --------------------------------------------------------------------------
# Registration builders
# --------------------------------------------------------------------------

def register(api, event_id, member_id) -> dict:
    return get_success_data(
        api.create_registration(event_id, {}, make_member_headers(member_id))
    )


def find_event(api, pub_id, event_id, creator_id="creator_1") -> dict:
    """Read one event's current computed counters via the publication's event list."""
    events = get_success_data(api.list_events(pub_id, make_creator_headers(creator_id)))
    for e in events:
        if e["id"] == event_id:
            return e
    raise AssertionError(f"Setup failed: event {event_id} not found under {pub_id}")


# --------------------------------------------------------------------------
# High-level composite scenarios
# --------------------------------------------------------------------------

def setup_publication_with_pro_balance(api, price=2500, fee_bps=1000,
                                       creator_id="creator_1") -> dict:
    """Publication with one ACTIVE PRO subscriber whose initial invoice is PAID,
    so payout_balance_cents == creator_net of that invoice.

    Returns {pub_id, pro_tier, member, subscription, initial_invoice}.
    """
    pub = new_publication(api, creator_id=creator_id, platform_fee_bps=fee_bps)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=price,
                   trial_days=0, name="Pro", creator_id=creator_id)
    sub_bundle = new_paid_subscriber(api, pub["id"], pro["id"])
    return {
        "pub_id": pub["id"],
        "pro_tier": pro,
        "member": sub_bundle["member"],
        "subscription": sub_bundle["subscription"],
        "initial_invoice": sub_bundle["initial_invoice"],
    }


def setup_canceled_pro_subscription(api, creator_id="creator_1") -> dict:
    """Publication + PRO tier + member with an ACTIVE-then-CANCELED subscription,
    still inside the win-back window. Clock reset to the default first.

    Returns {pub_id, pro_tier, member, subscription}.
    """
    reset_clock(api)
    bundle = setup_publication_with_pro_balance(api, creator_id=creator_id)
    member = bundle["member"]
    sub = bundle["subscription"]
    canceled = get_success_data(
        api.cancel_subscription(sub["id"], {}, make_member_headers(member["id"]))
    )
    bundle["subscription"] = canceled
    return bundle


def setup_free_member_with_published_post(api, min_tier_rank=0, creator_id="creator_1") -> dict:
    """Publication + FREE tier + verified member with ACTIVE free subscription +
    one PUBLISHED post. Returns {pub_id, free_tier, member, subscription, post}.
    """
    pub = new_publication(api, creator_id=creator_id)
    free = new_tier(api, pub["id"], tier_rank=0, monthly_price_cents=0,
                    trial_days=0, name="Free", creator_id=creator_id)
    sub_bundle = new_free_subscriber(api, pub["id"], free["id"])
    post = new_post(api, pub["id"], creator_id=creator_id, publish=True,
                    min_tier_rank=min_tier_rank)
    return {
        "pub_id": pub["id"],
        "free_tier": free,
        "member": sub_bundle["member"],
        "subscription": sub_bundle["subscription"],
        "post": post,
    }


def setup_pending_comment(api, creator_id="creator_1") -> dict:
    """Free member with ACTIVE subscription posts a PENDING comment on a published
    post. Returns {pub_id, member, post, comment}.
    """
    base = setup_free_member_with_published_post(api, min_tier_rank=0, creator_id=creator_id)
    member = base["member"]
    comment = get_success_data(
        api.create_comment(base["post"]["id"], {"body": "nice"}, make_member_headers(member["id"]))
    )
    base["comment"] = comment
    return base


def setup_publication_with_two_free_members_sent(api, creator_id="creator_1") -> dict:
    """Publication + FREE tier + two VERIFIED members each with an ACTIVE free
    subscription + one NEWSLETTER post SENT to both (sent_count 2).

    Returns {pub_id, free_tier, member_a, member_b, sent_post}.
    """
    pub = new_publication(api, creator_id=creator_id)
    free = new_tier(api, pub["id"], tier_rank=0, monthly_price_cents=0,
                    trial_days=0, name="Free", creator_id=creator_id)
    a = new_free_subscriber(api, pub["id"], free["id"], email="a@x.com", display_name="A")
    b = new_free_subscriber(api, pub["id"], free["id"], email="b@x.com", display_name="B")
    post = get_success_data(api.create_post(
        pub["id"],
        {"title": "News", "body": "Body", "content_type": "NEWSLETTER", "min_tier_rank": 0},
        make_creator_headers(creator_id),
    ))
    sent = get_success_data(api.send_post(post["id"], make_creator_headers(creator_id)))
    return {
        "pub_id": pub["id"],
        "free_tier": free,
        "member_a": a["member"],
        "member_b": b["member"],
        "sent_post": sent,
    }


def setup_two_pro_members_for_event(api, event_overrides=None, creator_id="creator_1") -> dict:
    """Publication + PRO tier + one Event + two ACTIVE PRO members A and B (not
    yet registered). Clock reset to the default first.

    Returns {pub_id, pro_tier, event, member_a, member_b, sub_a, sub_b}.
    """
    reset_clock(api)
    pub = new_publication(api, creator_id=creator_id)
    pro = new_tier(api, pub["id"], tier_rank=2, monthly_price_cents=2500,
                   trial_days=0, name="Pro", creator_id=creator_id)
    event = new_event(api, pub["id"], creator_id=creator_id, **(event_overrides or {}))
    a = new_paid_subscriber(api, pub["id"], pro["id"], email="a@x.com", display_name="A")
    b = new_paid_subscriber(api, pub["id"], pro["id"], email="b@x.com", display_name="B")
    return {
        "pub_id": pub["id"],
        "pro_tier": pro,
        "event": event,
        "member_a": a["member"],
        "member_b": b["member"],
        "sub_a": a["subscription"],
        "sub_b": b["subscription"],
    }
