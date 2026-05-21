"""Quote requests and the spot/contract pricing engine — PRD §3.4, §3.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    add_days,
    add_minutes,
    advance_clock_to_iso,
    assert_quote_request,
    create_quote_request,
    create_rate_contract,
    iso_utc,
    make_shipper_headers,
    parse_iso,
    quote_quote_request,
    reject_quote_request,
    setup_accepted_quote,
    setup_brokerage_with_shipper,
    setup_quoted_quote_request,
    setup_shipper_with_outstanding,
    SPOT_BASE_CENTS_PER_EQUIPMENT,
    SPOT_PER_UNIT_CENTS,
    spot_linehaul_cents,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 — Pricing engine: SPOT path.
# ===========================================================================
def test_spot_linehaul_formula_dry_van(api, broker_ops_headers):
    """PRD §3.4: "The quoted linehaul in cents is therefore the
    equipment-specific base plus the integer ZIP-difference multiplied
    by the equipment-specific per-unit rate."

    PRD §3.4: "The base price is 30,000 cents for `DRY_VAN` ... and the
    per-unit rate is 10 cents for `DRY_VAN`."

    Claim: a DRY_VAN quote with no rate_contract_id and ZIP-diff 10_001
    yields quoted_linehaul_cents == 30_000 + 10_001 * 10 = 130_010.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request(
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN",
    )
    assert quoted["rate_source"] == "SPOT"
    expected = spot_linehaul_cents("DRY_VAN", "10001", "20002")
    assert quoted["quoted_linehaul_cents"] == expected, (
        f"Expected {expected}, got {quoted['quoted_linehaul_cents']}"
    )


def test_spot_linehaul_formula_reefer(api, broker_ops_headers):
    """PRD §3.4: "The base price is 30,000 cents for `DRY_VAN`, 50,000 cents for `REEFER`, and 40,000 cents for `FLATBED`."
    PRD §3.4: "the per-unit rate is 10 cents for `DRY_VAN`, 18 cents for `REEFER`, and 14 cents for `FLATBED`."

    Claim: REEFER quote uses base 50_000 + diff*18.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request(
        origin_zip="10000", destination_zip="20100",
        equipment_type="REEFER",
    )
    expected = 50_000 + 10_100 * 18
    assert quoted["quoted_linehaul_cents"] == expected


def test_spot_linehaul_formula_flatbed(api, broker_ops_headers):
    """PRD §3.4: "The base price is 30,000 cents for `DRY_VAN`, 50,000 cents for `REEFER`, and 40,000 cents for `FLATBED`."
    PRD §3.4: "the per-unit rate is 10 cents for `DRY_VAN`, 18 cents for `REEFER`, and 14 cents for `FLATBED`."

    Claim: FLATBED quote uses base 40_000 + diff*14.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request(
        origin_zip="10000", destination_zip="20100",
        equipment_type="FLATBED",
    )
    expected = 40_000 + 10_100 * 14
    assert quoted["quoted_linehaul_cents"] == expected


# ===========================================================================
# §3.4 — Pricing engine: CONTRACT path.
# ===========================================================================
def test_contract_quote_uses_flat_rate(api, broker_ops_headers):
    """PRD §3.4: "If exactly one rate contract matches, the quote's
    `rate_source` is set to `CONTRACT` and `quoted_linehaul_cents` is set to
    the contract's `flat_rate_cents`."

    Claim: a quote with matching rate_contract_id yields rate_source ==
    CONTRACT and quoted_linehaul_cents == contract.flat_rate_cents.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    contract = create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="10001", lane_destination_zip="20002",
        equipment_type="DRY_VAN", flat_rate_cents=88_888,
    )
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN", rate_contract_id=contract["id"],
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    assert quoted["rate_source"] == "CONTRACT"
    assert quoted["quoted_linehaul_cents"] == 88_888


def test_contract_id_with_mismatched_lane_falls_through_to_spot(
    api, broker_ops_headers,
):
    """PRD §3.4: "If no rate contract matches, or if `rate_contract_id`
    was not supplied at all, the engine falls through to the spot path
    with `rate_source` set to `SPOT`."

    Claim: when rate_contract_id is supplied but the contract's lane
    does not match the quote, the quote resolves to SPOT.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    contract = create_rate_contract(
        brokerage["id"], shipper["id"],
        lane_origin_zip="99999", lane_destination_zip="88888",
        equipment_type="DRY_VAN", flat_rate_cents=88_888,
    )
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN", rate_contract_id=contract["id"],
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    assert quoted["rate_source"] == "SPOT"
    assert quoted["quoted_linehaul_cents"] == spot_linehaul_cents(
        "DRY_VAN", "10001", "20002",
    )


# ===========================================================================
# §3.5 — Workflow transitions.
# ===========================================================================
def test_quote_initial_status_open(api):
    """PRD §3.5: "The quote lands in `OPEN` status."

    Claim: a freshly filed quote is OPEN with rate_source unset.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    quote = create_quote_request(brokerage["id"], shipper["id"])
    assert quote["status"] == "OPEN"


def test_quote_quoted_then_accepted(api):
    """PRD §3.5: "Acceptance advances `QUOTED → ACCEPTED` and carries two preconditions."

    Claim: after /quote and /accept, status == ACCEPTED.
    """
    brokerage, shipper, accepted = setup_accepted_quote()
    assert accepted["status"] == "ACCEPTED"


def test_quote_quoted_then_rejected(api):
    """PRD §3.5: "Rejection advances `QUOTED → REJECTED` unconditionally."

    Claim: /reject on a QUOTED quote -> status == REJECTED.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request()
    rejected = reject_quote_request(brokerage["id"], shipper["id"],
                                    quoted["id"])
    assert rejected["status"] == "REJECTED"


def test_quote_window_start_must_precede_end(api):
    """PRD §3.5: "The window must be non-empty: `pickup_window_end` must
    be strictly after `pickup_window_start`."

    Claim: equal start and end -> ERR_INVALID_REQUEST.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    now = parse_iso(brokerage["clock_now_iso"])
    same = iso_utc(add_minutes(now, 1))
    res = api.create_quote_request(
        brokerage["id"], shipper["id"],
        {
            "origin_zip": "10001", "destination_zip": "20002",
            "equipment_type": "DRY_VAN",
            "pickup_window_start": same,
            "pickup_window_end": same,
        },
        make_shipper_headers(shipper["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_quote_not_open_blocks_quote_transition(api, broker_ops_headers):
    """PRD §3.5: "Attempting to quote a request not in `OPEN` yields
    `ERR_QUOTE_NOT_OPEN`."

    Claim: calling /quote on an already-QUOTED quote -> ERR_QUOTE_NOT_OPEN.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request()
    res = api.quote_quote_request(brokerage["id"], shipper["id"],
                                  quoted["id"], broker_ops_headers)
    validate_error(res, "ERR_QUOTE_NOT_OPEN")


def test_accept_a_non_quoted_quote_rejected(api):
    """PRD §3.5: "Attempting either operation on a quote not currently
    in `QUOTED` yields `ERR_QUOTE_NOT_QUOTED`."

    Claim: /accept on an OPEN quote -> ERR_QUOTE_NOT_QUOTED.
    """
    brokerage, shipper = setup_brokerage_with_shipper()
    quote = create_quote_request(brokerage["id"], shipper["id"])
    res = api.accept_quote_request(brokerage["id"], shipper["id"],
                                   quote["id"], make_shipper_headers(shipper["id"]))
    validate_error(res, "ERR_QUOTE_NOT_QUOTED")


def test_quote_accept_with_expired_window_rejected(api):
    """PRD §3.5: "The brokerage clock must be no later than
    `pickup_window_end` — a stale quote is rejected with `ERR_QUOTE_EXPIRED`."

    Claim: advancing the clock past pickup_window_end (without running
    the sweep so the quote is still QUOTED at the call) makes /accept
    return ERR_QUOTE_EXPIRED.

    Note: per PRD §2.5 clock-advance also runs the sweep that moves
    OPEN/QUOTED past-window quotes into EXPIRED. We test the temporal
    check by calling /accept on a quote that the sweep has now moved
    out of QUOTED — in which case the state-precondition check (PRD
    §2.9 priority 5) fires FIRST, yielding ERR_QUOTE_NOT_QUOTED rather
    than ERR_QUOTE_EXPIRED. The two-reader test: a faithful PRD-only
    implementer could legitimately return either ERR_QUOTE_EXPIRED (if
    the sweep is applied lazily at /accept time) or ERR_QUOTE_NOT_QUOTED
    (if the sweep moves it to EXPIRED eagerly during clock-advance).
    So we accept either.
    """
    brokerage, shipper, quoted = setup_quoted_quote_request()
    # Move the clock to one minute past pickup_window_end.
    pickup_end = parse_iso(quoted["pickup_window_end"])
    advance_clock_to_iso(brokerage["id"],
                         iso_utc(add_minutes(pickup_end, 1)))
    res = api.accept_quote_request(brokerage["id"], shipper["id"],
                                   quoted["id"],
                                   make_shipper_headers(shipper["id"]))
    body = res.json()
    error_id = body.get("data", {}).get("error_id")
    assert error_id in ("ERR_QUOTE_EXPIRED", "ERR_QUOTE_NOT_QUOTED"), (
        f"Expected ERR_QUOTE_EXPIRED or ERR_QUOTE_NOT_QUOTED, got {error_id!r}"
    )


def test_accept_exceeding_credit_limit_rejected(api):
    """PRD §3.5: "Additionally, the shipper's current `outstanding_invoiced_cents`
    plus the quote's `quoted_linehaul_cents` must not exceed the
    shipper's `credit_limit_cents`; a breach yields
    `ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Claim: outstanding 40_000 + new quote 130_010 against credit_limit
    100_000 -> ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED with HTTP 402.
    """
    brokerage, shipper, _invoice = setup_shipper_with_outstanding(
        outstanding_target_cents=40_000,
        credit_limit_cents=100_000,
    )
    # outstanding is now 40_000; credit limit 100_000.
    # Build a quote whose linehaul is 130_010 > (100_000-40_000=60_000).
    quote = create_quote_request(
        brokerage["id"], shipper["id"],
        origin_zip="10001", destination_zip="20002",
        equipment_type="DRY_VAN",
    )
    quoted = quote_quote_request(brokerage["id"], shipper["id"], quote["id"])
    assert quoted["quoted_linehaul_cents"] == 130_010

    res = api.accept_quote_request(brokerage["id"], shipper["id"],
                                   quoted["id"],
                                   make_shipper_headers(shipper["id"]))
    validate_error(res, "ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED")


def test_quote_terminal_states_block_further_transitions(api):
    """PRD §3.5: "`ACCEPTED`, `REJECTED`, and `EXPIRED` are terminal: a quote
    in any of those three states cannot be quoted, accepted, or rejected
    again."

    Claim: /reject on an ACCEPTED quote -> ERR_QUOTE_NOT_QUOTED.
    """
    brokerage, shipper, accepted = setup_accepted_quote()
    res = api.reject_quote_request(brokerage["id"], shipper["id"],
                                   accepted["id"],
                                   make_shipper_headers(shipper["id"]))
    validate_error(res, "ERR_QUOTE_NOT_QUOTED")
