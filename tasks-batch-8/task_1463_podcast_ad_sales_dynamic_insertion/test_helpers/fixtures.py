"""Composite setup helpers — multi-step API call chains that build PRD state.

Every helper uses `get_success_data()` so setup failures surface as clear
"Setup failed" errors rather than assertion errors deep in the chain.
Ownership-gated calls thread entity-backed identity headers via
make_advertiser_headers / make_agency_headers / make_show_producer_headers.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK,
    DELIVERY_INSTANT,
    FLIGHT_END,
    FLIGHT_START,
    POST_WINDOW_CLOCK,
)
from .factories import (
    create_ad_copy_payload,
    create_advertiser_payload,
    create_agency_payload,
    create_attribution_event_payload,
    create_campaign_payload,
    create_downloads_payload,
    create_episode_payload,
    create_invoice_payload,
    create_line_item_payload,
    create_show_payload,
)
from .test_users import (
    TEST_USERS,
    make_advertiser_headers,
    make_agency_headers,
)

ADOPS = TEST_USERS["ad_ops_headers"]
FINANCE = TEST_USERS["finance_headers"]
INGESTION = TEST_USERS["ingestion_headers"]


# =====================================================================
# Tier 1: single-resource creators and transitions
# =====================================================================

def create_show(**overrides):
    return get_success_data(api_client.create_show(create_show_payload(**overrides), ADOPS))


def get_show(show_id):
    return get_success_data(api_client.get_show(show_id, ADOPS))


def transition_show(show_id, to_tier):
    return get_success_data(
        api_client.transition_show(show_id, {"to_tier": to_tier}, ADOPS)
    )


def create_episode(show_id, **overrides):
    return get_success_data(
        api_client.create_episode(create_episode_payload(show_id, **overrides), ADOPS)
    )


def get_episode(episode_id):
    return get_success_data(api_client.get_episode(episode_id, ADOPS))


def transition_episode(episode_id, action):
    return get_success_data(
        api_client.transition_episode(episode_id, {"action": action}, ADOPS)
    )


def set_clock(to_iso8601):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, ADOPS)
    )


def create_agency(**overrides):
    return get_success_data(
        api_client.create_agency(create_agency_payload(**overrides), ADOPS)
    )


def create_advertiser(**overrides):
    return get_success_data(
        api_client.create_advertiser(create_advertiser_payload(**overrides), ADOPS)
    )


def transition_advertiser(advertiser_id, action):
    return get_success_data(
        api_client.transition_advertiser(advertiser_id, {"action": action}, ADOPS)
    )


def create_campaign(advertiser_id, headers=None, **overrides):
    return get_success_data(
        api_client.create_campaign(
            create_campaign_payload(advertiser_id, **overrides), headers or ADOPS
        )
    )


def get_campaign(campaign_id):
    return get_success_data(api_client.get_campaign(campaign_id, ADOPS))


def transition_campaign(campaign_id, action):
    return get_success_data(
        api_client.transition_campaign(campaign_id, {"action": action}, ADOPS)
    )


def create_ad_copy(campaign_id, author_headers, **overrides):
    return get_success_data(
        api_client.create_ad_copy(
            create_ad_copy_payload(campaign_id, **overrides), author_headers
        )
    )


def submit_ad_copy(copy_id, author_headers):
    return get_success_data(api_client.submit_ad_copy(copy_id, author_headers))


def review_ad_copy(copy_id, action, reviewer_headers, note=None):
    payload = {"action": action}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.review_ad_copy(copy_id, payload, reviewer_headers))


def get_ad_copy(copy_id):
    return get_success_data(api_client.get_ad_copy(copy_id, ADOPS))


def create_line_item(campaign_id, ad_copy_id, **overrides):
    return get_success_data(
        api_client.create_line_item(
            create_line_item_payload(campaign_id, ad_copy_id, **overrides), ADOPS
        )
    )


def get_line_item(line_item_id):
    return get_success_data(api_client.get_line_item(line_item_id, ADOPS))


def transition_line_item(line_item_id, action):
    return get_success_data(
        api_client.transition_line_item(line_item_id, {"action": action}, ADOPS)
    )


def ingest_downloads(episode_id, listener_key_prefix, count,
                     occurred_at=DELIVERY_INSTANT, user_agent_class="HUMAN"):
    return get_success_data(
        api_client.create_downloads(
            create_downloads_payload(
                episode_id,
                listener_key_prefix=listener_key_prefix,
                count=count,
                occurred_at=occurred_at,
                user_agent_class=user_agent_class,
            ),
            INGESTION,
        )
    )


def ingest_attribution_event(campaign_id, kind, occurred_at, promo_code=None):
    payload = create_attribution_event_payload(
        campaign_id, kind=kind, occurred_at=occurred_at
    )
    if promo_code is not None:
        payload["promo_code"] = promo_code
    return get_success_data(api_client.create_attribution_event(payload, INGESTION))


def create_invoice(campaign_id):
    return get_success_data(
        api_client.create_invoice(create_invoice_payload(campaign_id), FINANCE)
    )


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, FINANCE))


def transition_invoice(invoice_id, action):
    return get_success_data(
        api_client.transition_invoice(invoice_id, {"action": action}, FINANCE)
    )


def list_make_goods_for_campaign(campaign_id):
    data, _meta = validate_paginated(
        api_client.list_make_goods(FINANCE, params={"campaign_id": campaign_id})
    )
    return data


def get_make_good(make_good_id):
    return get_success_data(api_client.get_make_good(make_good_id, FINANCE))


def transition_make_good(make_good_id, action, headers, extension_days=None):
    payload = {"action": action}
    if extension_days is not None:
        payload["extension_days"] = extension_days
    return get_success_data(
        api_client.transition_make_good(make_good_id, payload, headers)
    )


# =====================================================================
# Tier 2: entity hierarchy composites
# =====================================================================

def create_and_approve_copy(campaign_id, owner_headers, kind="PRODUCED_AUDIO",
                            show_id=None, reviewer_headers=None, script_text="spot"):
    """Create + submit + approve an ad copy.

    PRODUCED_AUDIO is reviewed by AdOps; HOST_READ_SCRIPT must be reviewed by
    the show's ShowProducer (pass reviewer_headers accordingly).
    """
    overrides = {"kind": kind, "script_text": script_text}
    if show_id is not None:
        overrides["show_id"] = show_id
    copy = create_ad_copy(campaign_id, owner_headers, **overrides)
    copy = submit_ad_copy(copy["id"], owner_headers)
    reviewer = reviewer_headers or ADOPS
    copy = review_ad_copy(copy["id"], "APPROVE", reviewer)
    return copy


def setup_selling_scenario(
    show_avg=10000,
    content_category="NEWS",
    with_episode=True,
    episode_publish_at="2026-08-05T00:00:00Z",
    episode_overrides=None,
    category="FINTECH",
    agency=None,
    advertiser_name="Adv",
    booked_impressions=1000,
    cpm_cents=1000,
    billing_model="ACTUAL_DELIVERY",
    flight_start=FLIGHT_START,
    flight_end=FLIGHT_END,
):
    """Show (+ episode) + advertiser (+ agency) + DRAFT campaign + APPROVED
    PRODUCED_AUDIO copy + campaign ACTIVATEd. Returns a context dict."""
    # Every scenario is built against the PRD §2.4 startup clock; a prior
    # composite in the same test may have advanced it (e.g. past a measurement
    # window), which would push a fresh episode's publish_at outside the
    # forecast horizon and starve the inventory pool.
    set_clock(DEFAULT_CLOCK)
    show = create_show(title=f"{advertiser_name} Show", content_category=content_category,
                       avg_downloads_30d=show_avg)
    episode = None
    if with_episode:
        episode = create_episode(
            show["id"], publish_at=episode_publish_at, **(episode_overrides or {})
        )
    adv_overrides = {"name": advertiser_name, "category": category}
    if agency is not None:
        adv_overrides["agency_id"] = agency["id"]
    advertiser = create_advertiser(**adv_overrides)
    owner_headers = (
        make_agency_headers(agency["id"])
        if agency is not None
        else make_advertiser_headers(advertiser["id"])
    )
    campaign = create_campaign(
        advertiser["id"],
        name=f"{advertiser_name} Campaign",
        flight_start=flight_start,
        flight_end=flight_end,
        booked_impressions=booked_impressions,
        cpm_cents=cpm_cents,
        billing_model=billing_model,
    )
    copy = create_and_approve_copy(campaign["id"], owner_headers)
    campaign = transition_campaign(campaign["id"], "ACTIVATE")
    return {
        "show": show,
        "episode": episode,
        "agency": agency,
        "advertiser": advertiser,
        "owner_headers": owner_headers,
        "campaign": campaign,
        "copy": copy,
    }


def add_line_item(ctx, target="show", position="MID_ROLL", reserved_impressions=1000,
                  priority=10, ad_copy=None, activate=True):
    """Create a line item in ctx's campaign against its show or episode."""
    target_key = {}
    if target == "show":
        target_key["show_id"] = ctx["show"]["id"]
    elif target == "episode":
        target_key["episode_id"] = ctx["episode"]["id"]
    else:
        raise ValueError(f"unknown target {target!r}")
    line_item = create_line_item(
        ctx["campaign"]["id"],
        (ad_copy or ctx["copy"])["id"],
        position=position,
        reserved_impressions=reserved_impressions,
        priority=priority,
        **target_key,
    )
    if activate:
        line_item = transition_line_item(line_item["id"], "ACTIVATE")
    return line_item


# =====================================================================
# Tier 3: full lifecycle shortcuts
# =====================================================================

def publish_episode(ctx):
    ctx["episode"] = transition_episode(ctx["episode"]["id"], "PUBLISH")
    return ctx["episode"]


def deliver_downloads(ctx, count, prefix="P", occurred_at=DELIVERY_INSTANT,
                      user_agent_class="HUMAN"):
    return ingest_downloads(
        ctx["episode"]["id"], prefix, count,
        occurred_at=occurred_at, user_agent_class=user_agent_class,
    )


def finalize_episode_measurement(ctx, clock=POST_WINDOW_CLOCK):
    set_clock(clock)
    ctx["episode"] = transition_episode(ctx["episode"]["id"], "FINALIZE_MEASUREMENT")
    return ctx["episode"]


def end_campaign(ctx):
    ctx["campaign"] = transition_campaign(ctx["campaign"]["id"], "END")
    return ctx["campaign"]


def invoice_campaign(ctx):
    """Create the invoice for an ENDED campaign and capture any make-good."""
    ctx["invoice"] = create_invoice(ctx["campaign"]["id"])
    make_goods = list_make_goods_for_campaign(ctx["campaign"]["id"])
    ctx["make_goods"] = make_goods
    ctx["make_good"] = make_goods[0] if make_goods else None
    return ctx["invoice"]


def setup_measured_delivery(
    booked_impressions=1000,
    cpm_cents=1000,
    billing_model="ACTUAL_DELIVERY",
    downloads=800,
    reserved_impressions=500,
    position="MID_ROLL",
    category="FINTECH",
    agency=None,
    end_campaign_too=True,
    create_invoice_too=False,
):
    """Full chain: ACTIVE campaign + ACTIVE run-of-show line item, episode
    PUBLISHED, `downloads` HUMAN downloads, clock past window close, episode
    MEASURED; optionally campaign ENDED and invoice created."""
    ctx = setup_selling_scenario(
        category=category,
        agency=agency,
        booked_impressions=booked_impressions,
        cpm_cents=cpm_cents,
        billing_model=billing_model,
        episode_publish_at=FLIGHT_START,
    )
    ctx["line_item"] = add_line_item(
        ctx, target="show", position=position, reserved_impressions=reserved_impressions
    )
    publish_episode(ctx)
    deliver_downloads(ctx, downloads)
    finalize_episode_measurement(ctx)
    if end_campaign_too:
        end_campaign(ctx)
    if create_invoice_too:
        invoice_campaign(ctx)
    return ctx
