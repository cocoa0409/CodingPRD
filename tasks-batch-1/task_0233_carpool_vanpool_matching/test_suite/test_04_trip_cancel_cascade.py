"""The trip-cancellation cascade and its subsidy-ledger reconciliation
(PRD §2.5, §3.5, §3.10).
"""
from test_helpers import (
    validate_success, get_success_data,
    make_driver_headers, make_rider_headers, make_program_admin_headers,
    setup_active_pool, create_trip,
)

PA = make_program_admin_headers()


def test_trip_cancel_cascades_to_reservations_refunds_and_reconciles_ledger(api):
    """PRD §3.5: "Cancelling from `SCHEDULED` cascades every `RESERVED` reservation
    to `CANCELLED`".
    PRD §3.5: "if the reservation's `payment_status` was `CHARGED`, the charged
    amount is refunded to the rider's wallet; ... and the trip's `seats_reserved` is
    recomputed as seats are released."
    PRD §3.10: "The program's derived `subsidy_consumed_cents` is exactly the signed
    sum of `amount_cents` across its entries".

    Two pay_now reservations on a SCHEDULED trip: cancelling refunds both wallets,
    releases all seats (seats_reserved 0), and — with no prior finalization DEBIT —
    leaves subsidy_consumed_cents at 0.

    Design: Difficulty/transitive_cascade/trip_cancel_cascade_depth4_subsidy_ledger
    """
    ctx = setup_active_pool(api=api, seed_rider_name="R1", seed_rider_wallet=50000)
    prog_id, drv_id, pool_id = ctx["program_id"], ctx["driver_id"], ctx["pool_id"]
    r1 = ctx["seed"]
    r2 = get_success_data(api.create_member(
        {"employer_program_id": prog_id, "full_name": "R2", "home_zone": "Z-N",
         "work_zone": "Z-DT", "wallet_balance_cents": 50000}, PA))
    trip = create_trip(pool_id, drv_id, api=api, distance_miles=10.0)

    res1 = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r1["id"],
         "expected_trip_version": trip["version"], "seat_count": 1, "pay_now": True},
        make_rider_headers(r1["id"])), expected_status=201)
    trip_v1 = get_success_data(api.get_trip(trip["id"], make_driver_headers(drv_id)))["version"]
    res2 = validate_success(api.create_reservation(
        {"trip_id": trip["id"], "rider_member_id": r2["id"],
         "expected_trip_version": trip_v1, "seat_count": 1, "pay_now": True},
        make_rider_headers(r2["id"])), expected_status=201)

    cancelled = validate_success(api.cancel_trip(trip["id"], make_driver_headers(drv_id)))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["seats_reserved"] == 0

    assert get_success_data(api.get_reservation(res1["id"], make_driver_headers(drv_id)))[
        "reservation_status"] == "CANCELLED"
    assert get_success_data(api.get_reservation(res2["id"], make_driver_headers(drv_id)))[
        "reservation_status"] == "CANCELLED"
    assert get_success_data(api.get_member(r1["id"], PA))["wallet_balance_cents"] == 50000
    assert get_success_data(api.get_member(r2["id"], PA))["wallet_balance_cents"] == 50000
    assert get_success_data(api.get_employer_program(prog_id, PA))["subsidy_consumed_cents"] == 0
