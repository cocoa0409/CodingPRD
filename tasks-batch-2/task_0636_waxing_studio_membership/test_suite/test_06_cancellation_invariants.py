"""Conservation invariants on timely cancellation: a timely credit cancel
restores the credit pool, and a timely deposit cancel returns the held cents to
the member's wallet."""
from test_helpers import (
    validate_success,
    setup_studio,
    set_clock,
    create_location,
    create_service_type,
    create_room,
    create_technician,
    create_member,
    create_and_activate_membership,
    book_reservation,
    get_member,
    get_membership,
    TEST_USERS,
    make_member_headers,
)

FRONT = TEST_USERS["front_desk_headers"]


def test_timely_credit_cancel_restores_credit_balance(api):
    """PRD 3.6: "A timely cancellation — one made at least 24 hours before
    `start_utc` — moves the settlement axis to `REFUNDED`: a credit booking
    writes a `REFUND` ledger entry restoring its `credits_held`".

    A PLUS membership with 8 credits books a CREDIT reservation (1 credit held,
    balance 7); a timely cancel writes a REFUND restoring the credit, returning
    credit_balance to its pre-booking value 8 — the credit pool is conserved.

    Design: Difficulty/compensating_invariant/timely_credit_cancel_conserves_credit_pool
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Conserve1"},
        service_overrides={"name": "Half", "duration_minutes": 30,
                           "list_price_cents": 3000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(
        member=member, location_id=studio["loc"]["id"], room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"], service_type_id=studio["svc"]["id"],
        start_utc="2026-06-25T10:00:00Z", payment_method="CREDIT",
        expected_room_version=studio["room"]["version"],
        membership_id=mbr["id"], expected_membership_version=mbr["version"],
    )
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "REFUNDED"
    assert get_membership(mbr["id"])["credit_balance"] == 8, \
        "credit pool must be conserved: balance returns to pre-booking 8"


def test_timely_credit_cancel_settlement_refunded(api):
    """PRD 3.6: "A timely cancellation — one made at least 24 hours before
    `start_utc` — moves the settlement axis to `REFUNDED`: a credit booking
    writes a `REFUND` ledger entry restoring its `credits_held`".

    A timely CREDIT cancel drives the booking axis to CANCELLED and the
    settlement axis to REFUNDED (the refund leg that conserves the credit pool),
    asserted on the reservation object directly.

    Design: Difficulty/compensating_invariant/timely_credit_cancel_conserves_credit_pool
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Conserve1b"},
        service_overrides={"name": "Half", "duration_minutes": 30,
                           "list_price_cents": 3000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(
        member=member, location_id=studio["loc"]["id"], room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"], service_type_id=studio["svc"]["id"],
        start_utc="2026-06-25T10:00:00Z", payment_method="CREDIT",
        expected_room_version=studio["room"]["version"],
        membership_id=mbr["id"], expected_membership_version=mbr["version"],
    )
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "REFUNDED"


def test_timely_deposit_cancel_returns_cents_to_wallet(api):
    """PRD 3.6: "A timely cancellation — one made at least 24 hours before
    `start_utc` — moves the settlement axis to `REFUNDED`: ... a deposit booking
    returns its `deposit_held_cents` to the member's `wallet_credit_cents`."

    A DEPOSIT booking holds 1000 cents; a timely cancel returns exactly 1000
    cents to the wallet (wallet 0 -> 1000) and releases the deposit — no cents
    created or destroyed.

    Design: Difficulty/compensating_invariant/timely_deposit_cancel_conserves_cents_pool
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Conserve2", deposit_required_cents=1000)
    svc = create_service_type(name="Toe", duration_minutes=15, list_price_cents=1000)
    room = create_room(loc["id"], label="Room CW")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Cowa")
    member = create_member(loc["id"])
    assert get_member(member["id"])["wallet_credit_cents"] == 0
    res = book_reservation(
        member=member, location_id=loc["id"], room_id=room["id"],
        technician_id=tech["id"], service_type_id=svc["id"],
        start_utc="2026-06-25T10:00:00Z", payment_method="DEPOSIT",
        expected_room_version=room["version"],
    )
    assert res["deposit_held_cents"] == 1000
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["settlement_status"] == "REFUNDED"
    assert get_member(member["id"])["wallet_credit_cents"] == 1000, \
        "wallet must gain exactly the released 1000 deposit cents"


def test_timely_deposit_cancel_with_custom_deposit_amount(api):
    """PRD 3.6: "a deposit booking returns its `deposit_held_cents` to the
    member's `wallet_credit_cents`."

    With a location deposit of 1500, a DEPOSIT booking holds 1500 and a timely
    cancel returns exactly 1500 to the wallet — the conservation holds at a
    different deposit amount.

    Design: Difficulty/compensating_invariant/timely_deposit_cancel_conserves_cents_pool
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Conserve2b", deposit_required_cents=1500)
    svc = create_service_type(name="Toe", duration_minutes=15, list_price_cents=1000)
    room = create_room(loc["id"], label="Room CW2")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="Cowa")
    member = create_member(loc["id"])
    res = book_reservation(
        member=member, location_id=loc["id"], room_id=room["id"],
        technician_id=tech["id"], service_type_id=svc["id"],
        start_utc="2026-06-25T10:00:00Z", payment_method="DEPOSIT",
        expected_room_version=room["version"],
    )
    assert res["deposit_held_cents"] == 1500
    cancelled = validate_success(
        api.cancel_reservation(res["id"], make_member_headers(member["id"])), 200)
    assert cancelled["settlement_status"] == "REFUNDED"
    assert get_member(member["id"])["wallet_credit_cents"] == 1500
