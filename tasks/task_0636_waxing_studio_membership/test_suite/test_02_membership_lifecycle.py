"""Membership lifecycle: freeze/unfreeze credit park-and-restore cycle, and the
par-value cancellation conversion (including its multi-hop cascade)."""
from test_helpers import (
    validate_success,
    setup_studio,
    set_clock,
    create_location,
    create_member,
    create_and_activate_membership,
    book_reservation,
    get_member,
    get_membership,
    TEST_USERS,
    make_member_headers,
)

FRONT = TEST_USERS["front_desk_headers"]


def test_freeze_then_unfreeze_restores_credit_balance(api):
    """PRD 3.3: "Freezing ... parks the current balance by setting
    `frozen_cycle_credits` to the present `credit_balance`, and writes a
    `FREEZE_PARK` ledger entry whose `delta_credits` is the negative of that
    balance ... so the recomputed `credit_balance` is 0 while the pass is
    `FROZEN`."
    PRD 3.3: "Unfreezing returns a `FROZEN` membership to `ACTIVE` ... writing an
    `UNFREEZE_RESTORE` ledger entry whose `delta_credits` is the positive
    `frozen_cycle_credits`, resetting `frozen_cycle_credits` to 0, and
    recomputing the balance."

    A PLUS membership with 4 credits parks to 0 on freeze and restores to 4 on
    unfreeze — a true ACTIVE->FROZEN->ACTIVE loop.

    Design: Difficulty/non_linear_state_machine/membership_active_freeze_unfreeze_cycle
    """
    loc = create_location(name="Freezetown")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000)
    hdr = make_member_headers(member["id"])
    frozen = validate_success(api.freeze_membership(mbr["id"], {"freeze_days": 30}, hdr), 200)
    assert frozen["status"] == "FROZEN"
    assert frozen["credit_balance"] == 0, "balance must be parked to 0 while FROZEN"

    restored = validate_success(api.unfreeze_membership(mbr["id"], hdr), 200)
    assert restored["status"] == "ACTIVE"
    assert restored["credit_balance"] == 4, "unfreeze must restore the parked 4 credits"
    assert restored["frozen_cycle_credits"] == 0


def test_unfreeze_returns_membership_to_active_state(api):
    """PRD 3.3: "Unfreezing returns a `FROZEN` membership to `ACTIVE` ...
    clearing `freeze_until_utc`".

    After a freeze, an explicit unfreeze drives the status back to ACTIVE and
    zeroes the parked credits — the cyclic FROZEN->ACTIVE return leg.

    Design: Difficulty/non_linear_state_machine/membership_active_freeze_unfreeze_cycle
    """
    loc = create_location(name="Freezetown2")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000)
    hdr = make_member_headers(member["id"])
    validate_success(api.freeze_membership(mbr["id"], {"freeze_days": 30}, hdr), 200)
    restored = validate_success(api.unfreeze_membership(mbr["id"], hdr), 200)
    assert restored["status"] == "ACTIVE"
    assert restored["frozen_cycle_credits"] == 0


def test_cancel_converts_surviving_credits_to_wallet_at_par(api):
    """PRD 3.3: "the entire remaining `credit_balance` is forfeited to the
    member's `wallet_credit_cents` at the par rate of 100 cents per credit; this
    par-value conversion values every surviving credit at 100 cents regardless of
    where the membership sits in its cycle."
    PRD 3.3: "The membership's `credit_balance` is then recomputed to 0".

    A PLUS membership with 5 surviving credits converts to 500 wallet cents on
    cancel — the par-value forfeit, not the prorated-fee interpretation.

    Design: Difficulty/dual_variant_calc/membership_cancel_par_value_not_prorated
    """
    loc = create_location(name="Uptown")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=5, monthly_fee_cents=6000,
                                         max_rollover_credits=2)
    cancelled = validate_success(api.cancel_membership(mbr["id"], FRONT), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credit_balance"] == 0

    member_after = get_member(member["id"])
    assert member_after["wallet_credit_cents"] == 500, \
        f"Expected par-value wallet gain 500 (5*100), got {member_after['wallet_credit_cents']}"


def test_cancel_basic_membership_par_value_single_credit(api):
    """PRD 3.3: "the entire remaining `credit_balance` is forfeited to the
    member's `wallet_credit_cents` at the par rate of 100 cents per credit; this
    par-value conversion values every surviving credit at 100 cents regardless of
    where the membership sits in its cycle."

    A BASIC membership with 1 surviving credit converts to exactly 100 wallet
    cents on cancel (par rate confirmed at a different credit count).

    Design: Difficulty/dual_variant_calc/membership_cancel_par_value_not_prorated
    """
    loc = create_location(name="Uptown2")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="BASIC",
                                         monthly_credit_grant=1, monthly_fee_cents=4000)
    cancelled = validate_success(api.cancel_membership(mbr["id"], FRONT), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credit_balance"] == 0
    assert get_member(member["id"])["wallet_credit_cents"] == 100, \
        "1 surviving credit must convert to 100 wallet cents at par"


def test_cancel_with_open_credit_reservation_refunds_then_forfeits_at_par(api):
    """PRD 3.3: "Cancellation cascades: every `BOOKED` or `CHECKED_IN`
    reservation paid by credit on this membership is itself cancelled, releasing
    its held credits through a `REFUND` ledger entry that re-credits the balance.
    After those refunds land, the entire remaining `credit_balance` is forfeited
    to the member's `wallet_credit_cents` at the par rate of 100 cents per
    credit".

    A PLUS membership with 8 granted credits holds 1 against an open CREDIT
    reservation (balance 7). Cancelling the membership cancels that reservation
    (REFUND +1 -> balance 8) and then forfeits all 8 to the wallet at par = 800.

    Design: Difficulty/transitive_cascade/membership_cancel_depth3_cascade
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Cascadetown"},
        service_overrides={"name": "FullLeg", "duration_minutes": 45,
                           "list_price_cents": 6000, "credit_cost": 1},
    )
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=8, monthly_fee_cents=6000)
    res = book_reservation(
        member=member,
        location_id=studio["loc"]["id"],
        room_id=studio["room"]["id"],
        technician_id=studio["tech"]["id"],
        service_type_id=studio["svc"]["id"],
        start_utc="2026-06-25T10:00:00Z",
        payment_method="CREDIT",
        expected_room_version=studio["room"]["version"],
        membership_id=mbr["id"],
        expected_membership_version=mbr["version"],
    )
    cancelled = validate_success(api.cancel_membership(mbr["id"], FRONT), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credit_balance"] == 0

    res_after = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert res_after["booking_status"] == "CANCELLED"
    assert res_after["settlement_status"] == "REFUNDED"

    member_after = get_member(member["id"])
    assert member_after["wallet_credit_cents"] == 800, \
        f"Expected wallet 800 (8 surviving credits * 100 par), got {member_after['wallet_credit_cents']}"


def test_cancel_cascade_cancels_the_open_credit_reservation(api):
    """PRD 3.3: "Cancellation cascades: every `BOOKED` or `CHECKED_IN`
    reservation paid by credit on this membership is itself cancelled, releasing
    its held credits through a `REFUND` ledger entry that re-credits the
    balance."

    The depth-3 chain's first hop: cancelling the membership drives its open
    CREDIT reservation to CANCELLED with the settlement axis REFUNDED (the
    reservation is cascaded, not left BOOKED).

    Design: Difficulty/transitive_cascade/membership_cancel_depth3_cascade
    """
    studio = setup_studio(
        clock="2026-06-15T12:00:00Z",
        location_overrides={"name": "Cascadetown2"},
        service_overrides={"name": "FullLeg", "duration_minutes": 45,
                           "list_price_cents": 6000, "credit_cost": 1},
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
    validate_success(api.cancel_membership(mbr["id"], FRONT), 200)
    res_after = validate_success(api.get_reservation(res["id"], FRONT), 200)
    assert res_after["booking_status"] == "CANCELLED"
    assert res_after["settlement_status"] == "REFUNDED"
