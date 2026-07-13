"""Composite setup helpers.

Every helper takes the api client as its first argument, builds its
preconditions from scratch using only PRD-declared endpoints, and uses the
lenient get_success_data() validator so setup failures surface clearly.

Identity threading: Author operations use make_author_headers(author["id"]) and
Narrator operations use make_narrator_headers(narrator["id"]) so ownership
checks resolve against real records.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    admin_headers,
    qc_headers,
    make_author_headers,
    make_narrator_headers,
)
from . import factories as f


# ─── Primitives ───────────────────────────────────────

def onboard_author(api, **overrides) -> dict:
    return get_success_data(api.create_author(f.create_author_payload(**overrides), admin_headers()))


def onboard_narrator(api, **overrides) -> dict:
    return get_success_data(api.create_narrator(f.create_narrator_payload(**overrides), admin_headers()))


def new_title(api, author_id, **overrides) -> dict:
    return get_success_data(api.create_title(f.create_title_payload(**overrides), make_author_headers(author_id)))


def open_title(api, title_id, author_id) -> dict:
    return get_success_data(api.open_title(title_id, make_author_headers(author_id)))


def submit_audition(api, title_id, narrator_id, **overrides) -> dict:
    return get_success_data(
        api.create_audition(f.create_audition_payload(title_id, **overrides), make_narrator_headers(narrator_id))
    )


def accept_audition(api, audition_id, author_id) -> dict:
    return get_success_data(
        api.decide_audition(audition_id, {"decision": "ACCEPT"}, make_author_headers(author_id))
    )


def _contract_payload(title_id, narrator_id, expected_title_version, deal_type,
                      royalty_share_pct, per_hour_rate_cents):
    payload = {
        "title_id": title_id,
        "narrator_id": narrator_id,
        "deal_type": deal_type,
        "expected_title_version": expected_title_version,
    }
    if deal_type == "ROYALTY_SHARE":
        payload["royalty_share_pct"] = royalty_share_pct
    else:
        payload["per_hour_rate_cents"] = per_hour_rate_cents
    return payload


def offer_contract(api, title_id, narrator_id, author_id, expected_title_version,
                   deal_type="ROYALTY_SHARE", royalty_share_pct=0.30,
                   per_hour_rate_cents=None) -> dict:
    payload = _contract_payload(
        title_id, narrator_id, expected_title_version, deal_type,
        royalty_share_pct, per_hour_rate_cents,
    )
    return get_success_data(api.create_contract(payload, make_author_headers(author_id)))


def accept_contract(api, contract_id, narrator_id) -> dict:
    return get_success_data(
        api.respond_contract(contract_id, {"decision": "ACCEPT"}, make_narrator_headers(narrator_id))
    )


def submit_full_milestone(api, contract_id, narrator_id, finished_hours=6.0, **overrides) -> dict:
    payload = f.create_milestone_payload(contract_id, "FULL", finished_hours=finished_hours, **overrides)
    return get_success_data(api.create_milestone(payload, make_narrator_headers(narrator_id)))


def qc_pass(api, milestone_id) -> dict:
    return get_success_data(api.create_qc_review(milestone_id, {"outcome": "PASS"}, qc_headers()))


def qc_fail(api, milestone_id, notes="Revision required") -> dict:
    return get_success_data(
        api.create_qc_review(milestone_id, {"outcome": "FAIL", "notes": notes}, qc_headers())
    )


def publish(api, title_id) -> dict:
    return get_success_data(api.publish_title(title_id, admin_headers()))


def new_channel(api, retailer_cut_pct=0.40, supported_territories=None, name="Test Channel") -> dict:
    payload = f.create_channel_payload(
        name=name,
        supported_territories=supported_territories or ["US"],
        retailer_cut_pct=retailer_cut_pct,
    )
    return get_success_data(api.create_channel(payload, admin_headers()))


def new_listing(api, title_id, channel_id, **overrides) -> dict:
    return get_success_data(
        api.create_listing(f.create_listing_payload(title_id, channel_id, **overrides), admin_headers())
    )


def add_sales_event(api, listing_id, units_sold, unit_price_cents, occurred_at, **overrides) -> dict:
    payload = f.create_sales_event_payload(listing_id, units_sold, unit_price_cents, occurred_at, **overrides)
    return get_success_data(api.create_sales_event(payload, admin_headers()))


def create_statement(api, title_id, period_start, period_end) -> dict:
    return get_success_data(
        api.create_statement(f.create_statement_payload(title_id, period_start, period_end), admin_headers())
    )


def finalize_statement(api, statement_id) -> dict:
    return get_success_data(api.finalize_statement(statement_id, admin_headers()))


def pay_statement(api, statement_id) -> dict:
    return get_success_data(api.pay_statement(statement_id, admin_headers()))


# ─── Tier 1/2: State-progression composites ───────────

def setup_accepted_audition(api, *, exclusivity="NON_EXCLUSIVE", territory="WORLD",
                            list_price_cents=2000, hourly_rate_cents=20000):
    """Onboard author+narrator, create+open a title, submit+accept one audition.

    Title ends OPEN_FOR_AUDITION with an ACCEPTED audition; casting can proceed.
    Returns ctx with: author, narrator, title, audition, title_version (post-open).
    """
    author = onboard_author(api)
    narrator = onboard_narrator(api, hourly_rate_cents=hourly_rate_cents)
    title = new_title(
        api, author["id"], exclusivity=exclusivity, territory=territory,
        list_price_cents=list_price_cents,
    )
    opened = open_title(api, title["id"], author["id"])
    audition = submit_audition(api, title["id"], narrator["id"])
    accept_audition(api, audition["id"], author["id"])
    return {
        "author": author,
        "narrator": narrator,
        "title": title,
        "audition": audition,
        "title_version": opened["version"],
    }


def setup_offered_contract(api, *, deal_type="ROYALTY_SHARE", royalty_share_pct=0.30,
                           per_hour_rate_cents=None, **audition_kwargs):
    """setup_accepted_audition + one OFFERED contract. Title ends CASTING.

    Returns ctx adding: contract.
    """
    ctx = setup_accepted_audition(api, **audition_kwargs)
    contract = offer_contract(
        api, ctx["title"]["id"], ctx["narrator"]["id"], ctx["author"]["id"],
        ctx["title_version"], deal_type=deal_type, royalty_share_pct=royalty_share_pct,
        per_hour_rate_cents=per_hour_rate_cents,
    )
    ctx["contract"] = contract
    return ctx


def setup_accepted_contract(api, *, deal_type="ROYALTY_SHARE", royalty_share_pct=0.30,
                            per_hour_rate_cents=None, **audition_kwargs):
    """setup_offered_contract + narrator ACCEPT. Title ends IN_PRODUCTION.

    Returns ctx (author, narrator, title, audition, contract).
    """
    ctx = setup_offered_contract(
        api, deal_type=deal_type, royalty_share_pct=royalty_share_pct,
        per_hour_rate_cents=per_hour_rate_cents, **audition_kwargs
    )
    ctx["contract"] = accept_contract(api, ctx["contract"]["id"], ctx["narrator"]["id"])
    return ctx


def setup_submitted_full_milestone(api, *, finished_hours=6.0, **contract_kwargs):
    """setup_accepted_contract + one SUBMITTED FULL milestone. Title ends IN_QC.

    Returns ctx adding: milestone.
    """
    ctx = setup_accepted_contract(api, **contract_kwargs)
    ctx["milestone"] = submit_full_milestone(
        api, ctx["contract"]["id"], ctx["narrator"]["id"], finished_hours=finished_hours
    )
    return ctx


def setup_published_title(api, *, finished_hours=6.0, **contract_kwargs):
    """Full chain through PUBLISHED: FULL milestone PASS then publish.

    Returns ctx adding: milestone (APPROVED). Title ends PUBLISHED.
    """
    ctx = setup_submitted_full_milestone(api, finished_hours=finished_hours, **contract_kwargs)
    qc_pass(api, ctx["milestone"]["id"])
    publish(api, ctx["title"]["id"])
    ctx["milestone"] = get_success_data(
        api.get_milestone(ctx["milestone"]["id"], admin_headers())
    )
    return ctx


def setup_published_with_listing(api, *, retailer_cut_pct=0.40, supported_territories=None,
                                 listing_territory="US", effective_from="2026-03-01",
                                 effective_until="2026-12-31", finished_hours=6.0,
                                 **contract_kwargs):
    """setup_published_title + one channel + one ACTIVE listing.

    Returns ctx adding: channel, listing.
    """
    ctx = setup_published_title(api, finished_hours=finished_hours, **contract_kwargs)
    ctx["channel"] = new_channel(
        api, retailer_cut_pct=retailer_cut_pct,
        supported_territories=supported_territories or ["US"],
    )
    ctx["listing"] = new_listing(
        api, ctx["title"]["id"], ctx["channel"]["id"], territory=listing_territory,
        effective_from=effective_from, effective_until=effective_until,
    )
    return ctx


def setup_provisional_statement(api, *, sales, period_start="2026-03-01T00:00:00Z",
                                period_end="2026-03-31T23:59:59Z",
                                retailer_cut_pct=0.40, exclusivity="NON_EXCLUSIVE",
                                deal_type="ROYALTY_SHARE", royalty_share_pct=0.30,
                                per_hour_rate_cents=None, finished_hours=6.0,
                                listing_territory="US"):
    """Full chain + N sales events + one PROVISIONAL RoyaltyStatement.

    `sales` is a list of dicts, each with units_sold, unit_price_cents, occurred_at
    and optional units_returned. Returns ctx adding: sales_events (list), statement.
    """
    ctx = setup_published_with_listing(
        api, retailer_cut_pct=retailer_cut_pct, exclusivity=exclusivity,
        deal_type=deal_type, royalty_share_pct=royalty_share_pct,
        per_hour_rate_cents=per_hour_rate_cents, finished_hours=finished_hours,
        listing_territory=listing_territory,
    )
    ctx["sales_events"] = [
        add_sales_event(api, ctx["listing"]["id"], **sale) for sale in sales
    ]
    ctx["statement"] = create_statement(api, ctx["title"]["id"], period_start, period_end)
    return ctx
