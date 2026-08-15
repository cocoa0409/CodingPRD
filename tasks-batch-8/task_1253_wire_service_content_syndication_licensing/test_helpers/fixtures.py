"""Composite setup helpers for the wire service test suite.

These encapsulate the multi-step API sequences needed to put the system into a
testable state (catalogue + subscriber + active subscription + entitlement +
published articles + recorded republications + invoices). All setup calls use
the lenient get_success_data() validator so a failed precondition surfaces as a
clear "Setup step failed" error.

Identity threading: republication events are recorded by SubscriberRep, whose
X-User-ID must equal the owning Subscriber's id — record_publication() always
builds per-instance headers via make_subscriberrep_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_WORK_CLOCK
from .factories import (
    create_article_payload,
    create_asset_payload,
    create_entitlement_payload,
    create_feed_payload,
    create_invoice_payload,
    create_package_payload,
    create_publication_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_tier_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_subscriberrep_headers

_ADMIN = TEST_USERS["platform_admin_headers"]
_SALES = TEST_USERS["salesops_headers"]
_EDITOR = TEST_USERS["editor_headers"]
_LEGAL = TEST_USERS["legal_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]
_BILLING = TEST_USERS["billing_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PlatformAdmin-only). Returns ClockCheckpoint."""
    return get_success_data(api_client.set_current_utc(set_clock_payload(to_iso8601), _ADMIN))


def create_package(**overrides) -> dict:
    return get_success_data(api_client.create_package(create_package_payload(**overrides), _ADMIN))


def create_tier(**overrides) -> dict:
    return get_success_data(api_client.create_tier(create_tier_payload(**overrides), _ADMIN))


def create_feed(**overrides) -> dict:
    return get_success_data(api_client.create_feed(create_feed_payload(**overrides), _ADMIN))


def create_subscriber(**overrides) -> dict:
    return get_success_data(
        api_client.create_subscriber(create_subscriber_payload(**overrides), _SALES)
    )


# ---------------------------------------------------------------------------
# Tier 1: state progression (subscription DRAFT -> ACTIVE with OCC threading)
# ---------------------------------------------------------------------------

def create_draft_subscription(subscriber_id: str, package_id: str,
                              start_at: str = DEFAULT_WORK_CLOCK) -> dict:
    return get_success_data(
        api_client.create_subscription(
            subscriber_id, create_subscription_payload(package_id, start_at=start_at), _SALES
        )
    )


def activate_subscription(subscription_id: str, subscriber_id: str) -> dict:
    """Activate a draft subscription, threading the OCC token correctly:
    re-reads the subscriber so expected_subscriber_version is always current
    (the subscriber's version advances on every mutation of the subscriber)."""
    fresh = get_success_data(api_client.get_subscriber(subscriber_id, _SALES))
    return get_success_data(
        api_client.activate_subscription(
            subscription_id, {"expected_subscriber_version": fresh["version"]}, _SALES
        )
    )


def grant_entitlement(subscription_id: str, feed_id: str) -> dict:
    return get_success_data(
        api_client.create_entitlement(
            subscription_id, create_entitlement_payload(feed_id), _SALES
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (catalogue + subscriber + subscription [+ feed/ent])
# ---------------------------------------------------------------------------

def setup_active_subscription(*, package=None, tier=None, subscriber=None,
                              package_overrides=None, tier_overrides=None,
                              subscriber_overrides=None,
                              start_at=DEFAULT_WORK_CLOCK,
                              clock_to=DEFAULT_WORK_CLOCK) -> dict:
    """Package + tier + subscriber + subscription walked to ACTIVE.

    Pass an existing package/tier/subscriber resource to skip creating that
    leg (e.g. boundary tests that pre-create several tiers). Returns a context
    dict with keys: package, tier, subscriber, subscription (post-activation).
    """
    if clock_to is not None:
        set_clock(clock_to)
    pkg = package or create_package(**(package_overrides or {}))
    tier_row = tier or create_tier(**(tier_overrides or {}))
    sub = subscriber or create_subscriber(**(subscriber_overrides or {}))
    draft = create_draft_subscription(sub["id"], pkg["id"], start_at=start_at)
    activated = activate_subscription(draft["id"], sub["id"])
    return {"package": pkg, "tier": tier_row, "subscriber": sub, "subscription": activated}


def setup_subscription_with_entitlement(*, feed=None, feed_overrides=None, **kwargs) -> dict:
    """Active subscription plus a feed plus a LIVE entitlement pairing them."""
    ctx = setup_active_subscription(**kwargs)
    feed_row = feed or create_feed(**(feed_overrides or {}))
    ent = grant_entitlement(ctx["subscription"]["id"], feed_row["id"])
    ctx["feed"] = feed_row
    ctx["entitlement"] = ent
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: editorial lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_published_article(feed_id: str, article_overrides=None,
                             asset_payloads=None) -> dict:
    """Create a draft article, optionally attach assets, then publish it.
    Assets must be attached before publish to count toward the member credit
    bonus. Returns the PUBLISHED article."""
    art = get_success_data(
        api_client.create_article(
            create_article_payload(feed_id=feed_id, **(article_overrides or {})), _EDITOR
        )
    )
    for ap in (asset_payloads or []):
        get_success_data(api_client.create_asset(art["id"], ap, _EDITOR))
    return get_success_data(api_client.publish_article(art["id"], _EDITOR))


def record_publication_response(subscription_id: str, article_id: str, subscriber_id: str):
    """Record a republication as the owning SubscriberRep. Returns the raw
    Response so callers can assert either success or a specific error."""
    return api_client.create_publication(
        create_publication_payload(subscription_id, article_id),
        make_subscriberrep_headers(subscriber_id),
    )


def record_publication(subscription_id: str, article_id: str, subscriber_id: str) -> dict:
    """Record a republication expected to succeed. Returns the Publication."""
    return get_success_data(
        record_publication_response(subscription_id, article_id, subscriber_id)
    )


def publish_contributing_article(feed_id: str, member_subscriber_id: str,
                                 body_word_count: int = 500,
                                 asset_payloads=None) -> dict:
    """Publish a member-contributed article, which computes member_credit_cents
    and credits the contributing subscriber's member_credit_balance_cents."""
    return create_published_article(
        feed_id,
        article_overrides={
            "body_word_count": body_word_count,
            "contributing_member_subscriber_id": member_subscriber_id,
        },
        asset_payloads=asset_payloads,
    )


# ---------------------------------------------------------------------------
# Tier 4: accumulation / quota targeting
# ---------------------------------------------------------------------------

def setup_subscription_with_publications(count: int, *, quota: int = 5,
                                         overage: int = 100,
                                         clock_to=DEFAULT_WORK_CLOCK,
                                         tier_overrides=None,
                                         **kwargs) -> dict:
    """Active subscription + LIVE entitlement + `count` distinct published
    articles, each republished once. The tier's monthly_republish_quota and
    overage_per_article_cents are controllable for quota-boundary tests.
    Returns the context dict with an extra "publications" list (in order)."""
    merged_tier = {"monthly_republish_quota": quota, "overage_per_article_cents": overage}
    merged_tier.update(tier_overrides or {})
    ctx = setup_subscription_with_entitlement(
        tier_overrides=merged_tier, clock_to=clock_to, **kwargs
    )
    pubs = []
    for _ in range(count):
        art = create_published_article(ctx["feed"]["id"])
        pubs.append(
            record_publication(
                ctx["subscription"]["id"], art["id"], ctx["subscriber"]["id"]
            )
        )
    ctx["publications"] = pubs
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: billing / invoice lifecycle
# ---------------------------------------------------------------------------

def create_draft_invoice(subscription_id: str, billing_month: str = "2026-05") -> dict:
    return get_success_data(
        api_client.create_invoice(
            subscription_id, create_invoice_payload(billing_month), _BILLING
        )
    )


def issue_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.issue_invoice(invoice_id, _BILLING))


def setup_issued_invoice(*, billing_month: str = "2026-05", **kwargs) -> dict:
    """Active subscription + draft invoice + issued invoice. Returns context
    with keys: package, tier, subscriber, subscription, invoice."""
    ctx = setup_active_subscription(**kwargs)
    draft = create_draft_invoice(ctx["subscription"]["id"], billing_month)
    ctx["invoice"] = issue_invoice(draft["id"])
    return ctx


def get_subscriber(subscriber_id: str) -> dict:
    return get_success_data(api_client.get_subscriber(subscriber_id, _SALES))


def get_subscription(subscription_id: str) -> dict:
    return get_success_data(api_client.get_subscription(subscription_id, _SALES))


def get_entitlement(entitlement_id: str) -> dict:
    return get_success_data(api_client.get_entitlement(entitlement_id, _SALES))


def get_article(article_id: str) -> dict:
    return get_success_data(api_client.get_article(article_id, _EDITOR))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, _BILLING))


def get_publication(publication_id: str) -> dict:
    return get_success_data(api_client.get_publication(publication_id, _AUDITOR))
