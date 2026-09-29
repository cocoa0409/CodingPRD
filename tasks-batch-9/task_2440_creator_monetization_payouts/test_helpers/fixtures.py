"""Composite setup helpers and pytest fixtures.

Every fixture is function scoped: the service is restarted against an empty
store before each test, so nothing may be cached across tests.

The helpers are layered:

* tier 1 builds a bare channel;
* tier 2 adds the catalogue and calendar rows a channel needs to earn;
* tier 3 walks the accrual to a statement;
* tier 4 walks the statement to a payout;
* tier 5 reaches the terminal money states and the supplemental funds.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import (
    FORM_W8BEN,
    FORM_W9,
    PRODUCT_TYPE_ADVERTISING,
    PRODUCT_TYPE_SUBSCRIPTIONS,
)
from .test_users import ADMIN, AUDITOR, FINANCE, REVIEWER, REVIEWER_ALT, make_creator_headers


# =============================================================== tier 1 ======
def new_creator(api, **overrides):
    """Register a channel and return it at its birth state."""
    return get_success_data(api.create_creator(f.creator_payload(**overrides), ADMIN))


def eligible_creator(api, **overrides):
    """Register a channel that passes both audience minimums and evaluate it."""
    creator = new_creator(api, **overrides)
    return get_success_data(api.evaluate_creator(creator["id"], FINANCE))


def eligible_creator_with_watch_time(api, watch_time_minutes_365d, **overrides):
    """An ELIGIBLE channel carrying an arbitrary trailing-year watch time.

    PRD 3.1: the evaluation reads the stored metrics, so a channel is first
    registered above both audience minimums and evaluated to `ELIGIBLE`; the
    watch time is then overwritten by administrative metrics ingestion, which
    "deliberately does not re-evaluate eligibility", leaving the channel
    `ELIGIBLE` at the requested watch time.
    """
    creator = eligible_creator(api, **overrides)
    return get_success_data(
        api.patch_creator_metrics(
            creator["id"],
            f.metrics_payload(watch_time_minutes_365d=watch_time_minutes_365d),
            ADMIN,
        )
    )


def refresh_creator(api, creator_id, headers=None):
    return get_success_data(api.get_creator(creator_id, headers or FINANCE))


def ledger_rows(api, creator_id, params=None, headers=None):
    response = api.list_ledger_entries(creator_id, headers or FINANCE, params)
    return get_success_data(response)


def ledger_meta(api, creator_id, params=None, headers=None):
    response = api.list_ledger_entries(creator_id, headers or FINANCE, params)
    assert 200 <= response.status_code < 300, response.text
    return response.json()["meta"]


# =============================================================== tier 2 ======
def tips_product(api, **overrides):
    """A tips product: not suitability sensitive, whole split, no minimum."""
    return get_success_data(api.create_product(f.product_payload(**overrides), ADMIN))


def ads_product(api, **overrides):
    """An advertising product, which is suitability sensitive."""
    defaults = {
        "product_type": PRODUCT_TYPE_ADVERTISING,
        "name": "Ads Standard",
        "creator_share_bps": 8000,
        "platform_fee_bps": 2000,
        "min_payable_cents": 0,
    }
    defaults.update(overrides)
    return get_success_data(api.create_product(f.product_payload(**defaults), ADMIN))


def subs_product(api, **overrides):
    defaults = {
        "product_type": PRODUCT_TYPE_SUBSCRIPTIONS,
        "name": "Subs Standard",
        "creator_share_bps": 7000,
        "platform_fee_bps": 3000,
        "min_payable_cents": 0,
    }
    defaults.update(overrides)
    return get_success_data(api.create_product(f.product_payload(**defaults), ADMIN))


def july_period(api, **overrides):
    return get_success_data(api.create_period(f.period_payload(**overrides), ADMIN))


def august_period(api, **overrides):
    defaults = {
        "label": "2026-08",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return get_success_data(api.create_period(f.period_payload(**defaults), ADMIN))


def content_item(api, creator_id, **overrides):
    payload = f.content_item_payload(creator_id, **overrides)
    return get_success_data(api.create_content_item(payload, ADMIN))


def verified_tax_profile(api, creator, form_type=FORM_W9, **overrides):
    """Take a channel's tax document all the way to verified."""
    payload = f.tax_profile_payload(
        creator["id"], creator["version"], form_type=form_type, **overrides
    )
    profile = get_success_data(api.create_tax_profile(payload, FINANCE))
    get_success_data(
        api.submit_tax_profile(profile["id"], make_creator_headers(creator["id"]))
    )
    return get_success_data(
        api.verify_tax_profile(profile["id"], f.verify_payload(), FINANCE)
    )


def payable_creator(api, country_code="US", **overrides):
    """An eligible channel whose tax documentation is verified."""
    creator = eligible_creator(api, country_code=country_code, **overrides)
    profile = verified_tax_profile(api, creator, country_code=country_code)
    return refresh_creator(api, creator["id"]), profile


def treaty_creator(api, country_code, treaty_rate_bps, tin_provided=True, **overrides):
    """An eligible channel on a non-resident form with a treaty claim."""
    creator = eligible_creator(api, country_code=country_code, **overrides)
    profile = verified_tax_profile(
        api,
        creator,
        form_type=FORM_W8BEN,
        country_code=country_code,
        tin_provided=tin_provided,
        treaty_claimed=True,
        treaty_rate_bps=treaty_rate_bps,
    )
    return refresh_creator(api, creator["id"]), profile


# =============================================================== tier 3 ======
def post_event(api, creator_id, product_id, **overrides):
    payload = f.revenue_event_payload(creator_id, product_id, **overrides)
    return get_success_data(api.create_revenue_event(payload, FINANCE))


def close(api, period_id):
    return get_success_data(api.close_period(period_id, FINANCE))


def statement_for(api, creator_id, period_id):
    """The single statement a period close produced for one channel."""
    rows = get_success_data(
        api.list_statements(FINANCE, {"creator_id": creator_id, "period_id": period_id})
    )
    assert rows, f"No statement was generated for creator {creator_id}"
    return rows[0]


def finalize(api, statement_id):
    return get_success_data(api.finalize_statement(statement_id, FINANCE))


def accrued_statement(api, gross_amount_cents=40000, country_code="US"):
    """Walk one channel from registration to a provisional statement."""
    creator, _profile = payable_creator(api, country_code=country_code)
    product = tips_product(api)
    period = july_period(api)
    event = post_event(
        api, creator["id"], product["id"], gross_amount_cents=gross_amount_cents
    )
    close(api, period["id"])
    statement = statement_for(api, creator["id"], period["id"])
    return {
        "creator": refresh_creator(api, creator["id"]),
        "product": product,
        "period": period,
        "event": event,
        "statement": statement,
    }


def finalized_statement(api, gross_amount_cents=40000, country_code="US"):
    ctx = accrued_statement(api, gross_amount_cents, country_code)
    ctx["statement"] = finalize(api, ctx["statement"]["id"])
    ctx["creator"] = refresh_creator(api, ctx["creator"]["id"])
    return ctx


# =============================================================== tier 4 ======
def pending_payout(api, gross_amount_cents=40000, country_code="US", **creator_kwargs):
    """A finalized statement attached to a freshly created payout."""
    ctx = finalized_statement(api, gross_amount_cents, country_code)
    ctx["payout"] = get_success_data(
        api.create_payout(f.payout_payload(ctx["creator"]["id"]), FINANCE)
    )
    ctx["creator"] = refresh_creator(api, ctx["creator"]["id"])
    return ctx


def processing_payout(api, gross_amount_cents=40000):
    ctx = pending_payout(api, gross_amount_cents)
    ctx["payout"] = get_success_data(api.submit_payout(ctx["payout"]["id"], FINANCE))
    return ctx


def settled_payout(api, outcome, gross_amount_cents=40000, **payload_kwargs):
    ctx = processing_payout(api, gross_amount_cents)
    ctx["payout"] = get_success_data(
        api.record_settlement(
            ctx["payout"]["id"], f.settlement_payload(outcome, **payload_kwargs), FINANCE
        )
    )
    ctx["creator"] = refresh_creator(api, ctx["creator"]["id"])
    return ctx


# =============================================================== tier 5 ======
def open_investigation(api, creator_id, **overrides):
    payload = f.investigation_payload(creator_id, **overrides)
    return get_success_data(api.create_investigation(payload, REVIEWER))


def allocated_fund(api, period_id, **overrides):
    fund = get_success_data(api.create_fund(f.fund_payload(period_id, **overrides), ADMIN))
    allocated = get_success_data(
        api.allocate_fund(fund["id"], f.allocate_payload(fund["version"]), FINANCE)
    )
    return allocated


def disbursed_fund(api, period_id, **overrides):
    fund = allocated_fund(api, period_id, **overrides)
    return get_success_data(api.disburse_fund(fund["id"], FINANCE))


def demonetizable_content(api, creator_id, product_id, **overrides):
    """A rated-by-default content item plus a linked accrued event."""
    item = content_item(api, creator_id, **overrides)
    event = post_event(
        api, creator_id, product_id, content_item_id=item["id"], gross_amount_cents=10000
    )
    return item, event


# ============================================================== fixtures =====
@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def finance_headers():
    return FINANCE


@pytest.fixture
def reviewer_headers():
    return REVIEWER


@pytest.fixture
def reviewer_alt_headers():
    return REVIEWER_ALT


@pytest.fixture
def auditor_headers():
    return AUDITOR


@pytest.fixture
def creator(api):
    """A channel at its birth state."""
    return new_creator(api)


@pytest.fixture
def eligible(api):
    """An evaluated, eligible channel."""
    return eligible_creator(api)


@pytest.fixture
def tips(api):
    return tips_product(api)


@pytest.fixture
def july(api):
    return july_period(api)


@pytest.fixture
def payable(api):
    """An eligible channel with verified tax documentation."""
    creator_row, profile = payable_creator(api)
    return {"creator": creator_row, "tax_profile": profile}


@pytest.fixture
def provisional(api):
    """A channel holding one provisional statement worth 20000 net."""
    return accrued_statement(api)


@pytest.fixture
def finalized(api):
    """A channel holding one finalized statement worth 20000 net."""
    return finalized_statement(api)


@pytest.fixture
def payout_ctx(api):
    """A channel holding one pending payout against a finalized statement."""
    return pending_payout(api)
