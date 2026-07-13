"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the server database is empty at the start of each test.
Setup calls use get_success_data() (lenient) so misconfiguration surfaces as a
clear "Setup failed" rather than a confusing assertion error.

Identity threading: after a Publisher is created, every ownership-gated call
(titles, formats, assets, proofs, prices, distribution requests) uses
make_publisher_headers(publisher_id) with that publisher's actual id — never a
shared fallback header.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_publisher_headers
from .factories import (
    create_publisher_payload,
    create_title_payload,
    create_print_format_payload,
    create_ebook_format_payload,
    create_interior_asset_payload,
    create_cover_asset_payload,
    create_isbn_payload,
    create_channel_payload,
    create_price_payload,
    create_distribution_request_payload,
    create_sales_line_payload,
    create_statement_payload,
)
from .constants import IGS_CHANNEL

ADMIN = TEST_USERS["admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]

_isbn_seq = itertools.count(1)


def _next_isbn_13() -> str:
    """Generate a unique 13-digit ISBN string for pool inserts."""
    return f"978{next(_isbn_seq):010d}"


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(iso: str, api=api_client):
    return get_success_data(api.set_clock(iso, ADMIN))


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------
def create_publisher(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_publisher(create_publisher_payload(**overrides), ADMIN))


def create_amz_channel(api=api_client, **overrides) -> dict:
    return get_success_data(api.create_channel(create_channel_payload(**overrides), ADMIN))


def create_igs_channel(api=api_client, **overrides) -> dict:
    payload = dict(IGS_CHANNEL)
    payload.update(overrides)
    return get_success_data(api.create_channel(payload, ADMIN))


def create_title(api, publisher_id, **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.create_title(create_title_payload(publisher_id, **overrides), headers)
    )


def create_print_format(api, publisher_id, title_id, **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.create_format(title_id, create_print_format_payload(**overrides), headers)
    )


def create_ebook_format(api, publisher_id, title_id, **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.create_format(title_id, create_ebook_format_payload(**overrides), headers)
    )


def add_isbn(api, publisher_id, isbn_13=None) -> dict:
    if isbn_13 is None:
        isbn_13 = _next_isbn_13()
    return get_success_data(
        api.create_isbn(publisher_id, create_isbn_payload(isbn_13), ADMIN)
    )


def upload_interior(api, publisher_id, format_id, **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.create_asset(format_id, create_interior_asset_payload(**overrides), headers)
    )


def upload_cover(api, publisher_id, format_id, **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.create_asset(format_id, create_cover_asset_payload(**overrides), headers)
    )


def validate_asset(api, asset_id) -> dict:
    return get_success_data(api.validate_asset(asset_id, ADMIN))


def current_version(api, format_id) -> int:
    fmt = get_success_data(api.get_format(format_id, ADMIN))
    return fmt["version"]


def create_price(api, publisher_id, format_id, channel_id, list_price_cents=1500,
                 territory="US", effective_from="2026-01-01T00:00:00Z",
                 effective_to=None, expanded_reach=False) -> dict:
    """Create a ChannelPrice, reading the format's live version for the OCC guard.

    Used only for setup convenience; tests that intentionally exercise a stale
    expected_format_version call api.create_price() directly.
    """
    headers = make_publisher_headers(publisher_id)
    version = current_version(api, format_id)
    payload = create_price_payload(
        version, channel_id, list_price_cents,
        territory=territory, effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    if expanded_reach:
        payload["expanded_reach"] = True
    return get_success_data(api.create_price(format_id, payload, headers))


def assign_isbn(api, publisher_id, format_id, isbn_id) -> dict:
    headers = make_publisher_headers(publisher_id)
    return get_success_data(
        api.assign_isbn(format_id, {"isbn_id": isbn_id}, headers)
    )


def lock_format(api, publisher_id, format_id) -> dict:
    return get_success_data(api.lock_format(format_id, make_publisher_headers(publisher_id)))


def order_proof(api, publisher_id, format_id) -> dict:
    return get_success_data(api.create_proof(format_id, make_publisher_headers(publisher_id)))


def approve_proof(api, publisher_id, proof_id) -> dict:
    return get_success_data(api.approve_proof(proof_id, make_publisher_headers(publisher_id)))


def publish_format(api, publisher_id, format_id) -> dict:
    return get_success_data(api.publish_format(format_id, make_publisher_headers(publisher_id)))


def create_distribution_request(api, publisher_id, format_id, channel_id,
                                territory="US", **overrides) -> dict:
    headers = make_publisher_headers(publisher_id)
    payload = create_distribution_request_payload(channel_id, territory=territory, **overrides)
    return get_success_data(api.create_distribution_request(format_id, payload, headers))


def approve_distribution(api, dr_id) -> dict:
    return get_success_data(api.approve_distribution(dr_id, REVIEWER))


def create_statement(api, publisher_id, period_start, period_end) -> dict:
    return get_success_data(
        api.create_statement(publisher_id, create_statement_payload(period_start, period_end), ADMIN)
    )


def ingest_sale(api, format_id, channel_id, units, line_type, sale_date,
                territory="US") -> dict:
    payload = create_sales_line_payload(
        format_id, channel_id, units, line_type, sale_date, territory=territory
    )
    return get_success_data(api.create_sales_line(payload, ADMIN))


def issue_statement(api, statement_id) -> dict:
    return get_success_data(api.issue_statement(statement_id, ADMIN))


# --------------------------------------------------------------------------
# Composite scenarios
# --------------------------------------------------------------------------
def setup_publisher_with_print_format(api=api_client, page_count=200,
                                      interior_color="BW", trim_size="6x9") -> dict:
    """Publisher + title + DRAFT print format. Returns {publisher, title, format}."""
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"],
                              page_count=page_count, interior_color=interior_color,
                              trim_size=trim_size)
    return {"publisher": pub, "title": title, "format": fmt}


def setup_validated_interior(api=api_client, declared_page_count=200) -> dict:
    """Print format with one VALIDATED INTERIOR asset. Returns the scenario dict
    with an extra 'interior' key."""
    base = setup_publisher_with_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    interior = upload_interior(api, pub["id"], fmt["id"],
                               declared_page_count=declared_page_count)
    validate_asset(api, interior["id"])
    base["interior"] = interior
    return base


def setup_locked_print_format(api=api_client, assign_isbn_too=False) -> dict:
    """Print format with INTERIOR + COVER VALIDATED and status CONTENT_LOCKED.
    Optionally assigns a pool ISBN before locking. Returns the scenario dict
    with 'interior', 'cover', and (optionally) 'isbn'."""
    base = setup_publisher_with_print_format(api)
    pub, fmt = base["publisher"], base["format"]
    interior = upload_interior(api, pub["id"], fmt["id"])
    validate_asset(api, interior["id"])
    cover = upload_cover(api, pub["id"], fmt["id"])
    validate_asset(api, cover["id"])
    base["interior"] = interior
    base["cover"] = cover
    if assign_isbn_too:
        isbn = add_isbn(api, pub["id"])
        assign_isbn(api, pub["id"], fmt["id"], isbn["id"])
        base["isbn"] = isbn
    base["format"] = lock_format(api, pub["id"], fmt["id"])
    return base


def setup_ready_to_publish(api=api_client, channel=None,
                           with_distribution=False) -> dict:
    """Everything a format needs before publish: interior+cover validated, ISBN
    assigned, status CONTENT_LOCKED, an ACTIVE US price, and an APPROVED proof.
    Optionally files and APPROVES a distribution request while the format is still
    CONTENT_LOCKED (so the request waits in APPROVED). The format is NOT published.
    Returns the scenario dict with keys: channel, publisher, title, format, isbn,
    price, proof, and optionally dr.
    """
    if channel is None:
        channel = create_amz_channel(api)
    base = setup_locked_print_format(api, assign_isbn_too=True)
    pub, fmt = base["publisher"], base["format"]
    base["channel"] = channel
    base["price"] = create_price(api, pub["id"], fmt["id"], channel["id"])
    proof = order_proof(api, pub["id"], fmt["id"])
    base["proof"] = approve_proof(api, pub["id"], proof["id"])
    if with_distribution:
        dr = create_distribution_request(api, pub["id"], fmt["id"], channel["id"])
        base["dr"] = approve_distribution(api, dr["id"])
    return base


def setup_published_print_format(api=api_client, channel=None,
                                 with_distribution=False) -> dict:
    """Full lifecycle to a PUBLISHED print format, building on
    setup_ready_to_publish() and then publishing. When with_distribution is true
    the waiting APPROVED request cascades to LIVE at publish and the title to LIVE.
    """
    base = setup_ready_to_publish(api, channel=channel, with_distribution=with_distribution)
    base["format"] = publish_format(api, base["publisher"]["id"], base["format"]["id"])
    return base


def setup_priced_print_format_for_sales(api=api_client, list_price_cents=1500) -> dict:
    """Channel + publisher + title + print format with an ACTIVE open-ended US
    price (royalty 575 at list 1500). The base state for sales-line ingestion and
    statement scenarios. Returns {channel, publisher, title, format, price}."""
    channel = create_amz_channel(api)
    pub = create_publisher(api)
    title = create_title(api, pub["id"])
    fmt = create_print_format(api, pub["id"], title["id"])
    price = create_price(api, pub["id"], fmt["id"], channel["id"],
                         list_price_cents=list_price_cents)
    return {"channel": channel, "publisher": pub, "title": title,
            "format": fmt, "price": price}


def setup_two_period_ledger(api=api_client) -> dict:
    """Two consecutive statement periods for one publisher, with P1 ISSUED so its
    reserve has matured for P2 (still ACCRUING):

      P1 [2026-03-01, 2026-03-31]: one SALE of 4 units (gross 2300, reserve 345)
      P2 [2026-04-01, 2026-04-30]: one SALE of 2 units (gross 1150, reserve 173)

    Clock is advanced to 2026-05-01 and P1 is issued. Returns
    {channel, publisher, title, format, price, stmt1, stmt2, sale1, sale2}.
    """
    base = setup_priced_print_format_for_sales(api)
    pub, fmt, channel = base["publisher"], base["format"], base["channel"]
    stmt1 = create_statement(api, pub["id"], "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    sale1 = ingest_sale(api, fmt["id"], channel["id"], 4, "SALE", "2026-03-10T00:00:00Z")
    stmt2 = create_statement(api, pub["id"], "2026-04-01T00:00:00Z", "2026-04-30T00:00:00Z")
    sale2 = ingest_sale(api, fmt["id"], channel["id"], 2, "SALE", "2026-04-10T00:00:00Z")
    set_clock("2026-05-01T00:00:00Z", api)
    issue_statement(api, stmt1["id"])
    base.update({"stmt1": stmt1, "stmt2": stmt2, "sale1": sale1, "sale2": sale2})
    return base
