"""Composite setup helpers for the magazine publishing test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database and the startup clock). Setup steps use the
lenient get_success_data() validator so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP_DEFAULT, FAR_FUTURE_UTC
from .factories import (
    create_publication_payload,
    create_issue_payload,
    create_subscriber_payload,
    create_subscription_payload,
    create_controlled_subscription_payload,
    create_renewal_series_payload,
    create_mailing_batch_payload,
    create_back_issue_order_payload,
    create_circulation_audit_payload,
)
from .test_users import TEST_USERS

# Role-header shortcuts (all roles have opaque identity per PRD §2.1).
PD = TEST_USERS["publishing_director_headers"]
PM = TEST_USERS["production_manager_headers"]
CM = TEST_USERS["circulation_manager_headers"]
FM = TEST_USERS["fulfillment_manager_headers"]
PCO = TEST_USERS["postal_compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601=CLOCK_STARTUP_DEFAULT):
    """Move the server's logical clock (PublishingDirector only, PRD §2.4)."""
    return get_success_data(api_client.set_current_utc({"to_iso8601": to_iso8601}, PD))


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and state progression
# ---------------------------------------------------------------------------
def create_publication(**overrides) -> dict:
    return get_success_data(api_client.create_publication(create_publication_payload(**overrides), PD))


def create_issue(publication_id, **overrides) -> dict:
    return get_success_data(api_client.create_issue(publication_id, create_issue_payload(**overrides), PM))


def create_subscriber(**overrides) -> dict:
    return get_success_data(api_client.create_subscriber(create_subscriber_payload(**overrides), CM))


def create_subscription(publication_id, subscriber_id, start_issue_id, **overrides) -> dict:
    """Create a PAID subscription (PENDING_START) with the given overrides."""
    payload = create_subscription_payload(start_issue_id, **overrides)
    return get_success_data(api_client.create_subscription(publication_id, subscriber_id, payload, CM))


def create_controlled_subscription(publication_id, subscriber_id, start_issue_id, **overrides) -> dict:
    """Create a CONTROLLED subscription (price 0, payment NONE; PENDING_START)."""
    payload = create_controlled_subscription_payload(start_issue_id, **overrides)
    return get_success_data(api_client.create_subscription(publication_id, subscriber_id, payload, CM))


def activate_subscription(publication_id, subscription_id) -> dict:
    return get_success_data(api_client.activate_subscription(publication_id, subscription_id, CM))


def create_active_subscription(publication_id, subscriber_id, start_issue_id, **overrides) -> dict:
    sub = create_subscription(publication_id, subscriber_id, start_issue_id, **overrides)
    return activate_subscription(publication_id, sub["id"])


def create_active_controlled_subscription(publication_id, subscriber_id, start_issue_id, **overrides) -> dict:
    sub = create_controlled_subscription(publication_id, subscriber_id, start_issue_id, **overrides)
    return activate_subscription(publication_id, sub["id"])


def create_default_renewal_series(publication_id, offsets=(-90, -60, -30),
                                  pricing=(999, 1099, 1199), is_default=True) -> dict:
    payload = create_renewal_series_payload(
        effort_offsets_days=list(offsets), effort_pricing_cents=list(pricing), is_default=is_default
    )
    return get_success_data(api_client.create_renewal_series(publication_id, payload, CM))


def fire_next_renewal_event(publication_id, subscription_id) -> dict:
    return get_success_data(api_client.fire_next_renewal_event(publication_id, subscription_id, CM))


def get_subscription(publication_id, subscription_id) -> dict:
    return get_success_data(api_client.get_subscription(publication_id, subscription_id, CM))


def get_issue(publication_id, issue_id) -> dict:
    return get_success_data(api_client.get_issue(publication_id, issue_id, PM))


def get_mailing_batch(publication_id, issue_id, batch_id) -> dict:
    return get_success_data(api_client.get_mailing_batch(publication_id, issue_id, batch_id, FM))


def get_first_term(publication_id, subscription_id) -> dict:
    """Return the subscription's first (index-1) SubscriptionTerm."""
    terms = get_success_data(api_client.list_subscription_terms(publication_id, subscription_id, CM))
    assert isinstance(terms, list) and len(terms) >= 1, (
        f"Setup failed: expected at least one SubscriptionTerm, got {terms!r}"
    )
    return terms[0]


def list_term_revenue_entries(publication_id, subscription_id, term_id) -> list:
    """All DeferredRevenueEntries for a term. A 12-issue PRO_RATA_ISSUE term
    posts 12 RECOGNITION entries (PRD §3.5), which exceeds the default
    pagination limit of 10 (PRD §2.3), so the read must request a full page."""
    entries = get_success_data(
        api_client.list_term_revenue_entries(
            publication_id, subscription_id, term_id, CM, params={"limit": 100}
        )
    )
    assert isinstance(entries, list), f"Setup failed: expected entry list, got {entries!r}"
    return entries


# ---------------------------------------------------------------------------
# Tier 2: Issue pipeline drivers
# ---------------------------------------------------------------------------
def close_editorial(publication_id, issue_id) -> dict:
    return get_success_data(api_client.close_editorial(publication_id, issue_id, PM))


def close_ads_with_occ(publication_id, issue_id) -> dict:
    """Close advertising, threading the Issue's current version through the
    concurrency-guarded write (PRD §2.9)."""
    issue = get_issue(publication_id, issue_id)
    return get_success_data(
        api_client.close_ads(publication_id, issue_id, {"expected_issue_version": issue["version"]}, PM)
    )


def drive_issue_to_ad_closed(publication_id, issue_id) -> dict:
    close_editorial(publication_id, issue_id)
    return close_ads_with_occ(publication_id, issue_id)


def drive_issue_to_at_printer(publication_id, issue_id) -> dict:
    drive_issue_to_ad_closed(publication_id, issue_id)
    return get_success_data(api_client.ship_to_printer(publication_id, issue_id, PM))


# ---------------------------------------------------------------------------
# Tier 3: MailingBatch pipeline drivers
# ---------------------------------------------------------------------------
def create_batch(publication_id, issue_id, **overrides) -> dict:
    payload = create_mailing_batch_payload(**overrides)
    return get_success_data(api_client.create_mailing_batch(publication_id, issue_id, payload, FM))


def generate_labels_with_occ(publication_id, issue_id, batch_id) -> dict:
    """Generate labels, threading the batch's current version through the
    concurrency-guarded write (PRD §2.9). Returns the LABELS_GENERATED batch."""
    batch = get_mailing_batch(publication_id, issue_id, batch_id)
    return get_success_data(
        api_client.generate_labels(
            publication_id, issue_id, batch_id, {"expected_batch_version": batch["version"]}, FM
        )
    )


def verify_postal(publication_id, issue_id, batch_id) -> dict:
    return get_success_data(api_client.verify_postal(publication_id, issue_id, batch_id, PCO))


def drive_batch_to_confirmed(publication_id, issue_id, batch_id) -> dict:
    generate_labels_with_occ(publication_id, issue_id, batch_id)
    verify_postal(publication_id, issue_id, batch_id)
    get_success_data(api_client.tender_batch(publication_id, issue_id, batch_id, FM))
    return get_success_data(api_client.confirm_batch(publication_id, issue_id, batch_id, PCO))


def drive_issue_to_mailed(publication_id, issue_id, batch_overrides=None) -> dict:
    """Full pipeline PLANNING -> MAILED with one freshly created batch.
    Returns the MAILED Issue."""
    drive_issue_to_at_printer(publication_id, issue_id)
    batch = create_batch(publication_id, issue_id, **(batch_overrides or {}))
    drive_batch_to_confirmed(publication_id, issue_id, batch["id"])
    return get_success_data(api_client.mark_mailed(publication_id, issue_id, FM))


def drive_issue_to_finalized(publication_id, issue_id, batch_overrides=None) -> dict:
    """Full pipeline PLANNING -> FINALIZED. Returns the FINALIZED Issue."""
    drive_issue_to_mailed(publication_id, issue_id, batch_overrides=batch_overrides)
    return get_success_data(api_client.finalize_issue(publication_id, issue_id, PM))


def mail_sequential_issues(publication_id, count, start_issue_number=None) -> list:
    """Create `count` issues and drive each one through the full pipeline to
    MAILED (serving every qualifying subscription each time). Returns the
    created Issue payloads."""
    mailed = []
    for _ in range(count):
        overrides = {}
        if start_issue_number is not None:
            overrides["issue_number"] = start_issue_number
            start_issue_number += 1
        issue = create_issue(publication_id, **overrides)
        drive_issue_to_mailed(publication_id, issue["id"])
        mailed.append(issue)
    return mailed


# ---------------------------------------------------------------------------
# Tier 4: composite scenario builders
# ---------------------------------------------------------------------------
def setup_publication_with_subscriptions(
    num_paid=1,
    num_controlled=0,
    circulation_model="PAID",
    term_issues=12,
    price_paid_cents=1200,
    issue_overrides=None,
    publication_overrides=None,
    clock=CLOCK_STARTUP_DEFAULT,
) -> dict:
    """Publication + one issue + N PAID and M CONTROLLED ACTIVE subscriptions
    whose start issue is that issue. Returns a context dict."""
    set_clock(clock)
    pub_overrides = {"circulation_model": circulation_model}
    pub_overrides.update(publication_overrides or {})
    pub = create_publication(**pub_overrides)
    issue = create_issue(pub["id"], **(issue_overrides or {}))
    paid_subs = []
    for _ in range(num_paid):
        subscriber = create_subscriber()
        paid_subs.append(
            create_active_subscription(
                pub["id"], subscriber["id"], issue["id"],
                term_issues=term_issues, price_paid_cents=price_paid_cents,
                qualification_tier="PAID", payment_method="CARD",
            )
        )
    controlled_subs = []
    for _ in range(num_controlled):
        subscriber = create_subscriber()
        controlled_subs.append(
            create_active_controlled_subscription(
                pub["id"], subscriber["id"], issue["id"], term_issues=term_issues,
            )
        )
    return {
        "publication": pub,
        "issue": issue,
        "paid_subscriptions": paid_subs,
        "controlled_subscriptions": controlled_subs,
    }


def setup_batch_with_labels_generated(
    num_paid=1,
    num_controlled=0,
    circulation_model="PAID",
    postal_class="FIRST_CLASS",
    entry_point="ORIGIN",
    is_controlled_copy_included=False,
    batch_label="DOMESTIC",
    issue_overrides=None,
    clock=CLOCK_STARTUP_DEFAULT,
) -> dict:
    """Publication + issue driven to AT_PRINTER + one batch in
    LABELS_GENERATED covering the ACTIVE subscriptions."""
    ctx = setup_publication_with_subscriptions(
        num_paid=num_paid,
        num_controlled=num_controlled,
        circulation_model=circulation_model,
        issue_overrides=issue_overrides,
        clock=clock,
    )
    pub_id = ctx["publication"]["id"]
    issue_id = ctx["issue"]["id"]
    drive_issue_to_at_printer(pub_id, issue_id)
    batch = create_batch(
        pub_id, issue_id,
        batch_label=batch_label, postal_class=postal_class, entry_point=entry_point,
        is_controlled_copy_included=is_controlled_copy_included,
    )
    ctx["batch"] = generate_labels_with_occ(pub_id, issue_id, batch["id"])
    return ctx


def setup_subscription_in_grace(price_paid_cents=1200, clock=CLOCK_STARTUP_DEFAULT) -> dict:
    """ACTIVE subscription on a 1-issue term whose single issue is then mailed,
    so issues_remaining reaches zero and the subscription enters GRACE
    (PRD §3.5). Returns a context dict."""
    set_clock(clock)
    pub = create_publication()
    issue = create_issue(pub["id"])
    subscriber = create_subscriber()
    subscription = create_active_subscription(
        pub["id"], subscriber["id"], issue["id"],
        term_issues=1, price_paid_cents=price_paid_cents,
        qualification_tier="PAID", payment_method="CARD",
    )
    mailed_issue = drive_issue_to_mailed(pub["id"], issue["id"])
    subscription = get_subscription(pub["id"], subscription["id"])
    assert subscription["status"] == "GRACE", (
        f"Setup failed: expected GRACE after the only term issue mailed, "
        f"got {subscription['status']}"
    )
    return {
        "publication": pub,
        "issue": mailed_issue,
        "subscriber": subscriber,
        "subscription": subscription,
    }


def setup_active_subscription_with_pending_renewal_event(
    series_offsets=(-30, -7),
    series_pricing=(999, 1199),
    term_issues=12,
    price_paid_cents=1200,
) -> dict:
    """ACTIVE subscription carrying exactly one PENDING RenewalEvent.

    The clock is moved far beyond the term horizon BEFORE the subscription
    exists, so no clock-driven automatic effort can have fired on it; the
    subsequent manual fire-next deterministically creates effort number 1.
    """
    set_clock(CLOCK_STARTUP_DEFAULT)
    pub = create_publication()
    issue = create_issue(pub["id"])
    series = create_default_renewal_series(
        pub["id"], offsets=series_offsets, pricing=series_pricing, is_default=True
    )
    set_clock(FAR_FUTURE_UTC)
    subscriber = create_subscriber()
    subscription = create_active_subscription(
        pub["id"], subscriber["id"], issue["id"],
        term_issues=term_issues, price_paid_cents=price_paid_cents,
        qualification_tier="PAID", payment_method="CARD",
    )
    event = fire_next_renewal_event(pub["id"], subscription["id"])
    return {
        "publication": pub,
        "issue": issue,
        "renewal_series": series,
        "subscriber": subscriber,
        "subscription": subscription,
        "renewal_event": event,
    }


def setup_publication_with_pending_renewal_events(num_subs=2) -> dict:
    """Publication with a default renewal series and `num_subs` ACTIVE
    subscriptions, each carrying one PENDING RenewalEvent (see
    setup_active_subscription_with_pending_renewal_event for clock ordering)."""
    set_clock(CLOCK_STARTUP_DEFAULT)
    pub = create_publication()
    issue = create_issue(pub["id"])
    create_default_renewal_series(pub["id"])
    set_clock(FAR_FUTURE_UTC)
    subscriptions = []
    events = []
    for _ in range(num_subs):
        subscriber = create_subscriber()
        sub = create_active_subscription(pub["id"], subscriber["id"], issue["id"])
        subscriptions.append(sub)
        events.append(fire_next_renewal_event(pub["id"], sub["id"]))
    return {
        "publication": pub,
        "issue": issue,
        "subscriptions": subscriptions,
        "renewal_events": events,
    }


def setup_gift_subscription_with_entitlement(
    gift_price_paid_cents=1200,
    donor_price_paid_cents=2400,
    term_issues=12,
) -> dict:
    """Donor (ACTIVE PAID subscription) + recipient gift subscription, one
    PENDING RenewalEvent on the gift subscription, and one issue mailed so the
    gift subscription holds a FULL DigitalEntitlement (PRD §3.5)."""
    set_clock(CLOCK_STARTUP_DEFAULT)
    pub = create_publication()
    issue = create_issue(pub["id"])
    create_default_renewal_series(pub["id"], offsets=(-30,), pricing=(999,))
    set_clock(FAR_FUTURE_UTC)
    donor_subscriber = create_subscriber()
    donor_subscription = create_active_subscription(
        pub["id"], donor_subscriber["id"], issue["id"],
        term_issues=term_issues, price_paid_cents=donor_price_paid_cents,
        qualification_tier="PAID", payment_method="CARD",
    )
    recipient_subscriber = create_subscriber()
    gift = create_subscription(
        pub["id"], recipient_subscriber["id"], issue["id"],
        term_issues=term_issues, price_paid_cents=gift_price_paid_cents,
        qualification_tier="PAID", payment_method="CARD",
        is_gift=True, donor_subscriber_id=donor_subscriber["id"],
    )
    gift = activate_subscription(pub["id"], gift["id"])
    event = fire_next_renewal_event(pub["id"], gift["id"])
    mailed_issue = drive_issue_to_mailed(pub["id"], issue["id"])
    return {
        "publication": pub,
        "issue": mailed_issue,
        "donor_subscriber": donor_subscriber,
        "donor_subscription": donor_subscription,
        "recipient_subscriber": recipient_subscriber,
        "gift_subscription": get_subscription(pub["id"], gift["id"]),
        "renewal_event": event,
    }
