"""Brokerage creation, server clock, and quote-expiry sweep — PRD §2.5, §3.1."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_minutes,
    advance_clock_to_iso,
    assert_brokerage,
    create_brokerage,
    create_brokerage_payload,
    create_quote_request,
    create_shipper,
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    get_brokerage,
    iso_utc,
    parse_iso,
    quote_quote_request,
    setup_brokerage_with_shipper,
    sweep_expire_quotes,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.1 — brokerage creation defaults and required fields.
# ===========================================================================
def test_create_brokerage_with_defaults(api, platform_admin_headers):
    """PRD §3.1: "Two optional fields tune the brokerage-wide detention
    pricing: `detention_free_minutes`, defaulting to 120, ... and
    `detention_rate_cents_per_15min`, defaulting to 1500."

    Claim: omitting the two optional fields yields defaults 120 / 1500.
    """
    payload = {
        "name": "Defaults Co",
        "mc_number": "MC999999",
        "factoring_reserve_pct": 5.00,
    }
    res = api.create_brokerage(payload, platform_admin_headers)
    brokerage = validate_success(res, 201)
    assert_brokerage(brokerage)
    assert brokerage["detention_free_minutes"] == DEFAULT_DETENTION_FREE_MINUTES
    assert brokerage["detention_rate_cents_per_15min"] == (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


def test_brokerage_clock_initialized(api, platform_admin_headers):
    """PRD §3.1: "At creation the brokerage's `clock_now_iso` is initialised
    to the current real-world time, after which it advances only by
    explicit administrative action."

    Claim: a freshly created brokerage carries a clock_now_iso ISO-8601
    timestamp.
    """
    res = api.create_brokerage(create_brokerage_payload(),
                               platform_admin_headers)
    brokerage = validate_success(res, 201)
    assert_brokerage(brokerage)
    # clock_now_iso parses as an ISO 8601 instant.
    parse_iso(brokerage["clock_now_iso"])


def test_create_brokerage_missing_required_field(api, platform_admin_headers):
    """PRD §3.1: a PlatformAdmin "creates a brokerage by supplying its
    name, its mc_number, and its factoring_reserve_pct."

    Claim: omitting `name` -> ERR_INVALID_REQUEST.
    """
    payload = create_brokerage_payload()
    del payload["name"]
    res = api.create_brokerage(payload, platform_admin_headers)
    validate_error(res, "ERR_INVALID_REQUEST")


# ===========================================================================
# §2.5 / §3.1 — clock advancement and quote-expiry sweep.
# ===========================================================================
def test_clock_advances_forward(api, platform_admin_headers):
    """PRD §2.5: "The clock advances only via the platform-admin
    clock-advance capability, which takes a `to_iso` request body field
    carrying the new ISO 8601 timestamp the clock is to be set to."

    Claim: clock_advance with a later timestamp updates clock_now_iso.
    """
    brokerage = create_brokerage()
    new_clock = iso_utc(add_days(parse_iso(brokerage["clock_now_iso"]), 7))
    res = api.clock_advance(brokerage["id"], {"to_iso": new_clock},
                            platform_admin_headers)
    updated = validate_success(res, 200)
    assert updated["clock_now_iso"] == new_clock


def test_clock_advance_triggers_expiry_sweep(api, broker_ops_headers,
                                             platform_admin_headers):
    """PRD §2.5: "Advancing the clock also runs a quote-expiry sweep
    that transitions every `QuoteRequest` in `OPEN` or `QUOTED` whose
    `pickup_window_end` is now earlier than `clock_now_iso` into the `EXPIRED`
    terminal state."

    Claim: a QUOTED quote whose pickup_window_end is in the past after
    clock-advance ends up in EXPIRED.
    """
    brokerage, shipper, quoted = pytest_setup_quoted_quote_request_short()

    # Build a quote whose pickup_window_end is just 1 hour in the future,
    # then move the clock 1 day past it.
    now = parse_iso(brokerage["clock_now_iso"])
    pickup_end = iso_utc(add_minutes(now, 60))
    new_quote = create_quote_request(
        brokerage["id"], shipper["id"],
        pickup_window_start=iso_utc(add_minutes(now, 30)),
        pickup_window_end=pickup_end,
    )
    new_quoted = quote_quote_request(brokerage["id"], shipper["id"],
                                     new_quote["id"])
    assert new_quoted["status"] == "QUOTED"

    # Now advance clock past pickup_window_end.
    advance_clock_to_iso(
        brokerage["id"],
        iso_utc(add_days(now, 2)),
    )

    after = api.get_quote_request(brokerage["id"], shipper["id"],
                                  new_quoted["id"], broker_ops_headers)
    body = after.json()
    assert body["data"]["status"] == "EXPIRED"


def test_manual_sweep_expires_quotes_without_moving_clock(
    api, broker_ops_headers, platform_admin_headers,
):
    """PRD §2.5: "An equivalent sweep capability is exposed as a
    standalone administrative operation so that tests can trigger expiry
    without moving the clock — it processes the same expiry rule on
    whatever the clock currently reads."

    Claim: a /sweep/expire-quotes call moves OPEN/QUOTED quotes past
    pickup_window_end into EXPIRED.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    now = parse_iso(brokerage["clock_now_iso"])
    # Build an OPEN quote whose pickup_window_end is in the past so the
    # sweep catches it.
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        pickup_window_start=iso_utc(add_minutes(now, -120)),
        pickup_window_end=iso_utc(add_minutes(now, -60)),
    )
    assert quote["status"] == "OPEN"

    sweep_expire_quotes(brokerage["id"])

    after = api.get_quote_request(brokerage["id"], shipper["id"],
                                  quote["id"], broker_ops_headers)
    body = after.json()
    assert body["data"]["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Small in-file helper to avoid pulling extra imports.
# ---------------------------------------------------------------------------
def pytest_setup_quoted_quote_request_short():
    brokerage, shipper = setup_brokerage_with_shipper()
    quote = create_quote_request(brokerage["id"], shipper["id"])
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    return brokerage, shipper, quoted
