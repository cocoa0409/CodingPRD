"""Pre-sale window boundary semantics: the half-open [open, close) partition and the
before-open rejection.

Difficulty (queue A) boundary instances and a corner (queue B) rejection instance.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_yearbook_payload,
    create_presale_order_payload,
    create_yearbook,
    set_clock,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


def test_presale_window_open_instant_inclusive_early(api):
    """PRD §3.5: "If the order time is at or after `presale_open_iso` but strictly
    before `presale_close_iso`, the `price_tier` is `EARLY`." PRD §3.5: "The per-copy
    base is 6500 cents in the `EARLY` tier".

    Design: Difficulty/boundary_precision_check/boundary_presale_window_open_inclusive
    """
    yb = create_yearbook()  # presale_open 2026-01-01T00:00:00Z
    set_clock("2026-01-01T00:00:00Z")  # exactly the open instant
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="On The Dot", quantity=1),
        SALESREP,
    )
    order = validate_success(res, 201)
    assert order["price_tier"] == "EARLY"
    assert order["total_price_cents"] == 6500


def test_presale_just_after_open_is_early(api):
    """PRD §3.5: "If the order time is at or after `presale_open_iso` but strictly
    before `presale_close_iso`, the `price_tier` is `EARLY`."

    Design: Difficulty/boundary_precision_check/boundary_presale_window_open_inclusive
    """
    yb = create_yearbook()  # presale_open 2026-01-01T00:00:00Z
    set_clock("2026-01-01T00:00:01Z")  # one second after the open instant -> still EARLY
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Just After", quantity=1),
        SALESREP,
    )
    order = validate_success(res, 201)
    assert order["price_tier"] == "EARLY"
    assert order["total_price_cents"] == 6500


def test_presale_window_close_instant_falls_to_standard(api):
    """PRD §3.5: "If the order time is at or after `presale_close_iso`, the `price_tier`
    is `STANDARD`. The per-copy base is 6500 cents in the `EARLY` tier and 8000 cents
    in the `STANDARD` tier."

    Design: Difficulty/resource_temporal_overlap/overlap_presale_window_early_standard_partition
    """
    yb = create_yearbook()  # presale_close 2026-03-01T00:00:00Z
    set_clock("2026-03-01T00:00:00Z")  # exactly close -> STANDARD (half-open boundary)
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="At Close", quantity=1),
        SALESREP,
    )
    order = validate_success(res, 201)
    assert order["price_tier"] == "STANDARD"
    assert order["total_price_cents"] == 8000


def test_presale_just_before_close_is_early(api):
    """PRD §3.5: "If the order time is at or after `presale_open_iso` but strictly
    before `presale_close_iso`, the `price_tier` is `EARLY`."

    Design: Difficulty/resource_temporal_overlap/overlap_presale_window_early_standard_partition
    """
    yb = create_yearbook()  # presale_close 2026-03-01T00:00:00Z
    set_clock("2026-02-28T23:59:59Z")  # strictly before close -> EARLY side of the partition
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Just Before Close", quantity=1),
        SALESREP,
    )
    order = validate_success(res, 201)
    assert order["price_tier"] == "EARLY"
    assert order["total_price_cents"] == 6500


def test_presale_before_open_returns_not_open(api):
    """PRD §3.5: "If that time is before the yearbook's `presale_open_iso`, the order
    is rejected outright with `ERR_PRESALE_NOT_OPEN` — the window has not opened."

    Design: Corner/validations/presale_before_open_returns_not_open
    """
    # presale_open in the future; clock left at the startup default 2026-01-01 (before open).
    yb = create_yearbook(presale_open_iso="2026-02-15T00:00:00Z")
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Too Early", quantity=1),
        SALESREP,
    )
    validate_error(res, "ERR_PRESALE_NOT_OPEN")
