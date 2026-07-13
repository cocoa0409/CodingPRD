"""Refunds (full vs prorated), exchange branch, and revenue/ wallet conservation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_passenger_headers,
    sum_allocations,
)
from test_helpers import fixtures as fx


# ==========================================================================
# dual_variant_calc / refund_full_vs_prorated_diverge_ticket_domain
# ==========================================================================

def test_refund_full_variant_on_unactivated_single(api):
    """PRD 3.7: "For a purchased, unactivated ticket the full variant applies: the refund
    is the ticket's purchase price minus a flat refund fee of 200 cents, floored at zero,
    ignoring dates."
    PRD 3.7: "When the destination is `WALLET`, the refund amount is added to the
    passenger's wallet balance and the passenger's `version` advances; when it is
    `ORIGINAL`, no wallet change occurs."

    Design: Difficulty/dual_variant_calc/refund_full_vs_prorated_diverge_ticket_domain
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")  # price 1300
    rr = fx.request_refund(api, tkt["id"], pax["id"], refund_destination="WALLET")
    approved = fx.approve_refund(api, rr["id"])
    assert approved["refund_amount_cents"] == 1100
    assert approved["status"] == "APPROVED"
    ticket = fx.get_ticket(api, tkt["id"])
    assert ticket["status"] == "REFUNDED"
    assert ticket["refund_amount_cents"] == 1100
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 1100


def test_refund_prorated_variant_on_activated_monthly(api):
    """PRD 3.7: "For an activated monthly ticket the prorated variant applies: let the
    total days be the number of days in the calendar month of activation; let the used days
    be the whole number of days elapsed from the start of the activation day to the current
    clock instant, counted inclusively (that is, the floor of the elapsed days plus one);
    let the remaining days be the total days minus the used days, floored at zero; compute
    a gross refund equal to the purchase price multiplied by remaining days and divided by
    total days, floored to whole cents; and take the refund as that gross minus the
    200-cent fee, floored at zero."

    Design: Difficulty/dual_variant_calc/refund_full_vs_prorated_diverge_ticket_domain
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api, ticket_type="MONTHLY", base_fare_cents=3100,
                                peak_surcharge_cents=0)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")  # price 3100 (<= 5000 cap)
    fx.activate_ticket(api, tkt["id"], pax["id"])  # activated_at = 2026-03-01
    fx.set_clock(api, "2026-03-11T00:00:00Z")  # used_days = 11, remaining = 20, total = 31
    rr = fx.request_refund(api, tkt["id"], pax["id"], refund_destination="WALLET")
    assert rr["refund_amount_cents"] == 1800  # floor(3100*20/31)=2000, -200
    approved = fx.approve_refund(api, rr["id"])
    assert approved["status"] == "APPROVED"
    ticket = fx.get_ticket(api, tkt["id"])
    assert ticket["status"] == "REFUNDED"
    assert ticket["refund_amount_cents"] == 1800


# ==========================================================================
# non_linear_state_machine / ticket_branches_purchased_to_exchanged
# ==========================================================================

def test_exchange_mints_new_ticket_and_credits_downgrade(api):
    """PRD 3.4: "A brand-new ticket is created in `PURCHASED`, priced by the same
    purchase-price calculation and given its own revenue allocations."
    PRD 3.4: "When the old ticket's purchase price exceeded the new ticket's purchase price,
    the positive difference is added to the passenger's wallet balance and the passenger's
    `version` advances."

    Design: Difficulty/non_linear_state_machine/ticket_branches_purchased_to_exchanged
    """
    fx.set_clock(api)
    fp_hi = fx.create_fare_product(api, origin_zone=1, destination_zone=3,
                                   base_fare_cents=1000, peak_surcharge_cents=300)
    fp_lo = fx.create_fare_product(api, origin_zone=1, destination_zone=2,
                                   base_fare_cents=700, peak_surcharge_cents=200)
    pax = fx.create_passenger(api)
    old = fx.purchase_ticket(api, pax["id"], fp_hi["id"], "PEAK")  # 1300
    new = validate_success(
        api.exchange_ticket(
            old["id"],
            {"new_fare_product_id": fp_lo["id"], "travel_period": "OFF_PEAK"},
            make_passenger_headers(pax["id"]),
        ),
        201,
    )
    assert new["status"] == "PURCHASED"
    assert new["purchase_price_cents"] == 700
    assert fx.get_ticket(api, old["id"])["status"] == "EXCHANGED"
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 600


def test_exchange_zeroes_old_allocations_and_allocates_new_ticket(api):
    """PRD 3.4: "The old ticket moves to the terminal `EXCHANGED` state and its revenue
    allocations are zeroed to a sum of zero. A brand-new ticket is created in `PURCHASED`,
    priced by the same purchase-price calculation and given its own revenue allocations."

    Design: Difficulty/non_linear_state_machine/ticket_branches_purchased_to_exchanged
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp_hi = fx.create_fare_product(api, origin_zone=1, destination_zone=3,
                                   base_fare_cents=1000, peak_surcharge_cents=300)
    fp_lo = fx.create_fare_product(api, origin_zone=1, destination_zone=2,
                                   base_fare_cents=700, peak_surcharge_cents=200)
    pax = fx.create_passenger(api)
    old = fx.purchase_ticket(api, pax["id"], fp_hi["id"], "PEAK")
    new = validate_success(
        api.exchange_ticket(
            old["id"],
            {"new_fare_product_id": fp_lo["id"], "travel_period": "OFF_PEAK"},
            make_passenger_headers(pax["id"]),
        ),
        201,
    )
    assert sum_allocations(fx.get_ticket(api, old["id"])) == 0
    assert sum_allocations(new) == 700


# ==========================================================================
# compensating_invariant / refund_conserves_agency_revenue_to_zero
# ==========================================================================

def test_refund_zeroes_agency_revenue_and_credits_wallet(api):
    """PRD 3.7: "Approval drives the ticket into the terminal `REFUNDED` state, writes the
    computed amount onto the ticket's `refund_amount_cents`, zeroes every entry of the
    ticket's `revenue_allocations` so their sum becomes zero, and advances the ticket's
    `version`."
    PRD 3.7: "When the destination is `WALLET`, the refund amount is added to the
    passenger's wallet balance and the passenger's `version` advances; when it is
    `ORIGINAL`, no wallet change occurs."

    Design: Difficulty/compensating_invariant/refund_conserves_agency_revenue_to_zero
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")  # 1300, allocations sum 1300
    assert sum_allocations(tkt) == 1300
    rr = fx.request_refund(api, tkt["id"], pax["id"], refund_destination="WALLET")
    fx.approve_refund(api, rr["id"])
    ticket = fx.get_ticket(api, tkt["id"])
    assert ticket["status"] == "REFUNDED"
    assert sum_allocations(ticket) == 0
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 1100


def test_refund_original_tender_zeroes_revenue_without_wallet_change(api):
    """PRD 3.7: "zeroes every entry of the ticket's `revenue_allocations` so their sum
    becomes zero"
    PRD 3.7: "when it is `ORIGINAL`, no wallet change occurs."

    Design: Difficulty/compensating_invariant/refund_conserves_agency_revenue_to_zero
    """
    fx.set_clock(api)
    fx.create_agencies_abc(api)
    fp = fx.create_fare_product(api, base_fare_cents=1000, peak_surcharge_cents=300)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    rr = fx.request_refund(api, tkt["id"], pax["id"], refund_destination="ORIGINAL")
    fx.approve_refund(api, rr["id"])
    ticket = fx.get_ticket(api, tkt["id"])
    assert ticket["status"] == "REFUNDED"
    assert sum_allocations(ticket) == 0
    assert fx.get_passenger(api, pax["id"])["wallet_credit_cents"] == 0


# ==========================================================================
# Corner: refund guards and idempotency
# ==========================================================================

def test_refund_on_validated_ticket_returns_not_refundable(api):
    """PRD 3.7: "A refund may be requested only while the ticket is `PURCHASED` or
    `ACTIVATED`, and an activated ticket is refundable only when it is a monthly pass; a
    ticket that is terminal, or an activated single-journey ticket, is not refundable and
    the request fails with `ERR_TICKET_NOT_REFUNDABLE`."

    Design: Corner/validations/refund_on_validated_ticket_returns_not_refundable
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.activate_ticket(api, tkt["id"], pax["id"])
    validate_success(api.validate_ticket(tkt["id"], make_passenger_headers(pax["id"])), 200)
    resp = api.create_refund_request(
        {"ticket_id": tkt["id"], "reason": "x", "refund_destination": "WALLET"},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_NOT_REFUNDABLE.value)


def test_refund_after_window_returns_window_elapsed(api):
    """PRD 3.7: "The request must also fall within 60 days of the ticket's creation, or it
    fails with `ERR_REFUND_WINDOW_ELAPSED`."

    Design: Corner/validations/refund_after_window_returns_window_elapsed
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.set_clock(api, "2026-06-01T00:00:00Z")  # > 60 days after purchase
    resp = api.create_refund_request(
        {"ticket_id": tkt["id"], "reason": "late", "refund_destination": "ORIGINAL"},
        make_passenger_headers(pax["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_ELAPSED.value)


def test_refund_approve_twice_second_returns_invalid_refund_state(api):
    """PRD 3.7: "Approval is permitted only while the request is `REQUESTED` and the ticket
    is still `PURCHASED` or `ACTIVATED`; a decision on a request that is not `REQUESTED`
    fails with `ERR_INVALID_REFUND_STATE`."

    Design: Corner/state_machines/refund_approve_twice_second_returns_invalid_refund_state
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    rr = fx.request_refund(api, tkt["id"], pax["id"], refund_destination="WALLET")
    fx.approve_refund(api, rr["id"])
    resp = api.approve_refund(rr["id"], fx.ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REFUND_STATE.value)
