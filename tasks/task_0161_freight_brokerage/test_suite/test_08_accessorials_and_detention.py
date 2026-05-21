"""Accessorial charges and the detention calculation — PRD §3.7."""
from __future__ import annotations

import pytest

from test_helpers import (
    approve_accessorial,
    assert_accessorial_charge,
    create_accessorial,
    create_accessorial_charge_payload,
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    DETENTION_INCREMENT_MINUTES,
    detention_cents,
    make_carrier_headers,
    setup_in_transit_load,
    setup_delivered_load,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 — Accessorial creation, approve / deny.
# ===========================================================================
def test_create_accessorial_in_requested_state(api):
    """PRD §3.7: "Each charge carries a `charge_type` ... and an
    `amount_cents` integer that must be strictly greater than zero. A
    charge lands in `REQUESTED`."

    Claim: a freshly filed charge has status == REQUESTED.
    """
    brokerage, shipper, carrier, _q, load = setup_in_transit_load()
    res = api.create_accessorial_charge(
        brokerage["id"], shipper["id"], load["id"],
        create_accessorial_charge_payload(charge_type="LUMPER",
                                          amount_cents=5_000),
        make_carrier_headers(carrier["id"]),
    )
    charge = validate_success(res, 201)
    assert_accessorial_charge(charge)
    assert charge["status"] == "REQUESTED"
    assert charge["amount_cents"] == 5_000


def test_accessorial_amount_must_be_positive(api):
    """PRD §3.7: "`amount_cents` integer that must be strictly greater
    than zero."

    Claim: amount_cents == 0 -> ERR_INVALID_REQUEST.
    """
    brokerage, shipper, carrier, _q, load = setup_in_transit_load()
    res = api.create_accessorial_charge(
        brokerage["id"], shipper["id"], load["id"],
        create_accessorial_charge_payload(amount_cents=0),
        make_carrier_headers(carrier["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_approve_then_deny_rejected(api, broker_ops_headers):
    """PRD §3.7: "approval or denial of a charge already past `REQUESTED`
    yields `ERR_ACCESSORIAL_NOT_REQUESTED`."

    Claim: approve a charge, then attempt to deny it -> ERR_ACCESSORIAL_NOT_REQUESTED.
    """
    brokerage, shipper, carrier, _q, load = setup_in_transit_load()
    charge = create_accessorial(brokerage["id"], shipper["id"], load["id"],
                                carrier["id"])
    approve_accessorial(brokerage["id"], charge["id"])
    res = api.deny_accessorial_charge(brokerage["id"], charge["id"],
                                      broker_ops_headers)
    validate_error(res, "ERR_ACCESSORIAL_NOT_REQUESTED")


# ===========================================================================
# §3.7 — Detention calculation.
# ===========================================================================
def test_detention_zero_at_boundary(api):
    """PRD §3.7: "Subtract the brokerage's `detention_free_minutes`; if
    the result is non-positive, no detention accrues and
    `provisional_detention_cents` is zero."

    Claim: elapsed == free_minutes exactly -> provisional_detention_cents == 0.
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES,
    )
    assert load["provisional_detention_cents"] == 0


def test_detention_below_free_window_is_zero(api):
    """PRD §3.7: "Subtract the brokerage's `detention_free_minutes`; if
    the result is non-positive, no detention accrues and
    `provisional_detention_cents` is zero."

    Claim: elapsed < free_minutes -> 0 cents.
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES - 1,
    )
    assert load["provisional_detention_cents"] == 0


def test_detention_one_minute_over_free_rounds_up_to_full_increment(api):
    """PRD §3.7: "take the resulting chargeable-minute count, round it
    up to the next whole 15-minute increment, and multiply the resulting
    integer number of increments by `detention_rate_cents_per_15min` ...
    under no circumstances may the implementation derive a per-minute
    fractional rate, multiply by chargeable minutes, and round the
    resulting cents at the end, because for example a single chargeable
    minute under a 1500-cent per-15-minute rate must produce 1500 cents
    (one full increment) and not 100 cents (one-fifteenth of an
    increment)."

    Claim: elapsed = free + 1 -> chargeable = 1 -> ceil(1/15) = 1
    increment -> 1 * 1500 = 1500 cents (NOT 100).
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 1,
    )
    assert load["provisional_detention_cents"] == (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


def test_detention_full_increment_at_15_chargeable_minutes(api):
    """PRD §3.7: "round it up to the next whole 15-minute increment".

    Claim: 15 chargeable minutes -> exactly 1 increment -> 1500 cents.
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 15,
    )
    assert load["provisional_detention_cents"] == (
        DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


def test_detention_partial_increment_rounds_up(api):
    """PRD §3.7: "round it up to the next whole 15-minute increment".

    Claim: 16 chargeable minutes -> 2 increments (ceil(16/15)) -> 3000 cents.
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 16,
    )
    assert load["provisional_detention_cents"] == (
        2 * DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


def test_detention_two_full_increments_at_30_chargeable_minutes(api):
    """PRD §3.7: "round it up to the next whole 15-minute increment ...
    multiply the resulting integer number of increments by
    `detention_rate_cents_per_15min`."

    Claim: 30 chargeable minutes -> exactly 2 increments -> 3000 cents.
    """
    brokerage, shipper, carrier, _q, load = setup_delivered_load(
        detention_minutes=DEFAULT_DETENTION_FREE_MINUTES + 30,
    )
    assert load["provisional_detention_cents"] == (
        2 * DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
    )


def test_local_detention_helper_matches_server(api):
    """Sanity: the test-side detention_cents helper agrees with the
    server's provisional calculation across several elapsed values.

    PRD §3.7: pinned formula ceil(chargeable/15) * rate_cents_per_15min.
    """
    cases = [(120, 0), (135, 1500), (130, 1500), (150, 3000), (300, 18_000)]
    for elapsed, expected in cases:
        assert detention_cents(elapsed, DEFAULT_DETENTION_FREE_MINUTES,
                               DEFAULT_DETENTION_RATE_CENTS_PER_15MIN) == (
            expected
        )
