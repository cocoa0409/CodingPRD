"""Compensating-action invariants and immediate-consistency reconciliation.

Covers cancellation conserving the bike pool count and the deposit money, plus the
immediate pool-decrement reflected right after a reservation.
"""
from test_helpers import (
    api_client,
    get_success_data,
    make_subscriber_headers,
    make_ops_admin_headers,
)
from test_helpers.fixtures import (
    set_clock, create_model, add_bikes, create_account, read_model_version, reserve,
)

OPS = make_ops_admin_headers()


# ===========================================================================
# Difficulty/compensating_invariant/cancel_reservation_conserves_bike_pool_count
# ===========================================================================
def test_cancel_restores_available_count_to_total(api):
    """PRD §3.3: "cancellation transitions lifecycle_status to CANCELLED, returns the bike
    from RESERVED to AVAILABLE and clears its current_rental_id, recomputes the model's
    available_count".

    Reserve one of 3 bikes then cancel: available_count returns to 3, equal to total_bikes.

    Design: Difficulty/compensating_invariant/cancel_reservation_conserves_bike_pool_count
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=3)
    add_bikes(model["id"], 3)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.cancel_rental(rental["id"], sub))
    model_after = get_success_data(api_client.get_bike_model(model["id"], sub))
    assert model_after["available_count"] == 3, "restored to total_bikes after cancel"


def test_cancel_conserves_total_bikes(api):
    """PRD §2.5: "total_bikes is the count of Bike rows whose model_id equals that model's
    id regardless of their status".

    Cancelling a reservation never destroys a unit: total_bikes stays at 3 (zero drift).

    Design: Difficulty/compensating_invariant/cancel_reservation_conserves_bike_pool_count
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=3)
    add_bikes(model["id"], 3)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.cancel_rental(rental["id"], sub))
    model_after = get_success_data(api_client.get_bike_model(model["id"], sub))
    assert model_after["total_bikes"] == 3, "pool conserved, zero drift"


# ===========================================================================
# Difficulty/compensating_invariant/cancel_reservation_conserves_deposit_money
# ===========================================================================
def test_cancel_refunds_full_deposit_to_wallet(api):
    """PRD §3.3: "sets billing_status to SETTLED and refunds the full deposit_cents to the
    account's wallet_credit_cents (a compensating refund since the reservation was never
    consumed)".

    Deposit 10000 held at reserve; after cancel the wallet holds exactly 10000.

    Design: Difficulty/compensating_invariant/cancel_reservation_conserves_deposit_money
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=10000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.cancel_rental(rental["id"], sub))
    account_after = get_success_data(api_client.get_account(account["id"], sub))
    assert account_after["wallet_credit_cents"] == 10000, (
        "full deposit refunded, equals deposit_cents"
    )


def test_cancel_settles_billing_status(api):
    """PRD §3.3: "sets billing_status to SETTLED and refunds the full deposit_cents to the
    account's wallet_credit_cents".

    After cancelling a RESERVED rental its billing_status becomes SETTLED (the deposit is
    released, money conserved).

    Design: Difficulty/compensating_invariant/cancel_reservation_conserves_deposit_money
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(deposit_cents=10000, fleet_size=2)
    add_bikes(model["id"], 1)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    rental = reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    get_success_data(api_client.cancel_rental(rental["id"], sub))
    rental_after = get_success_data(api_client.get_rental(rental["id"], sub))
    assert rental_after["billing_status"] == "SETTLED"


# ===========================================================================
# Corner/consistency_model/reserve_response_immediately_reflects_pool_decrement
# ===========================================================================
def test_reserve_immediately_decrements_available_count(api):
    """PRD §2.5: "both are recomputed on every reserve, release, retire, and buyout."
    PRD §3.3: "The reservation then recomputes the model's available_count".

    Right after a reserve, GET /bike-models/{id} shows available_count decremented from
    2 to 1 within the same request flow (no lag).

    Design: Corner/consistency_model/reserve_response_immediately_reflects_pool_decrement
    """
    set_clock("2026-06-01T00:00:00Z")
    model = create_model(fleet_size=2)
    add_bikes(model["id"], 2)
    account = create_account(rental_cap=1)
    mv = read_model_version(model["id"], account["id"])
    reserve(account["id"], model["id"], mv)
    sub = make_subscriber_headers(account["id"])
    model_after = get_success_data(api_client.get_bike_model(model["id"], sub))
    assert model_after["available_count"] == 1, "decremented from 2 immediately after reserve"
