"""The checkout settlement waterfall (deposit -> loyalty -> gift -> charge), the
depth-4 cascade it drives across appointment/technician/client/gift-card, and the
simpler single-input settlement results."""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_base, make_station, make_menu_item, make_add_on, make_technician,
    make_client, make_gift_card, book_appointment, attach_add_on, confirm,
    check_in, start_service, checkout, drive_to_in_service,
    inject_client_state, inject_appointment_deposit, set_clock,
)

MANAGER = TEST_USERS["salon_manager_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: combinatorial three-input waterfall
# ---------------------------------------------------------------------------
def test_checkout_waterfall_charges_after_deposit_loyalty_gift(api):
    """PRD §3.10: "the deposit credit is `deposit_paid_cents` (0 if none was held),
    and the amount remaining after the deposit is the gross minus that credit,
    floored at 0."
    PRD §3.10: "the requested loyalty value in cents is `loyalty_points_redeemed`
    multiplied by the per-point value of 10 cents, and the loyalty actually applied
    is the smaller of that requested value and the amount remaining after the
    deposit."
    PRD §3.10: "the gift draw is the smaller of the card's `balance_cents` and the
    amount remaining after loyalty (0 if no card was supplied)".

    Design: Difficulty/combinatorial_formula/checkout_waterfall_three_input_nonlinear
    """
    set_clock("2026-05-01T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    addon = make_add_on(price_cents=1500, extra_minutes=0)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    gc = make_gift_card(initial_balance_cents=3000, purchaser_client_id=client["id"])
    inject_client_state(client["id"], loyalty_points_balance=60)

    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-05-01T13:00:00Z")
    attach_add_on(appt["id"], addon["id"], appt["version"])
    inject_appointment_deposit(appt["id"], 2000)
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirm(appt["id"])
    check_in(appt["id"])
    started = start_service(appt["id"], tech["id"])

    completed = checkout(appt["id"], started["version"],
                         loyalty_points_redeemed=50, gift_card_id=gc["id"])
    # gross 6000 - deposit 2000 = 4000; - loyalty 500 = 3500; - gift 3000 = 500.
    assert completed["total_charged_cents"] == 500


def test_checkout_waterfall_depletes_gift_and_consumes_loyalty(api):
    """PRD §3.10: "The client's `loyalty_points_balance` is reduced by the points
    consumed and the gift card's `balance_cents` is reduced by the gift draw."
    PRD §3.10: "If the gift-card draw brought the card's `balance_cents` to exactly
    0, the card's `status` transitions from `ACTIVE` to `DEPLETED`".

    Design: Difficulty/combinatorial_formula/checkout_waterfall_three_input_nonlinear
    """
    set_clock("2026-05-01T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=0, requires_sterile_station=False)
    addon = make_add_on(price_cents=1500, extra_minutes=0)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    gc = make_gift_card(initial_balance_cents=3000, purchaser_client_id=client["id"])
    inject_client_state(client["id"], loyalty_points_balance=60)

    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-05-01T13:00:00Z")
    attach_add_on(appt["id"], addon["id"], appt["version"])
    inject_appointment_deposit(appt["id"], 2000)
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirm(appt["id"])
    check_in(appt["id"])
    started = start_service(appt["id"], tech["id"])
    checkout(appt["id"], started["version"], loyalty_points_redeemed=50,
             gift_card_id=gc["id"])

    client_after = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert client_after["loyalty_points_balance"] == 10   # 60 - 50 consumed + 0 award
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 0
    assert gc_after["status"] == "DEPLETED"


# ---------------------------------------------------------------------------
# Difficulty: depth-4 checkout cascade
# ---------------------------------------------------------------------------
def test_checkout_cascade_settles_charge_and_accrues_commission(api):
    """PRD §3.10: "It then computes `technician_earning_cents` (Section 3.11) and
    adds it to the assigned technician's `accrued_earnings_cents`."
    PRD §3.10: "the gift draw is the smaller of the card's `balance_cents` and the
    amount remaining after loyalty (0 if no card was supplied)".

    Design: Difficulty/transitive_cascade/checkout_cascade_depth4_settlement_commission_loyalty_giftdeplete
    """
    set_clock("2026-03-20T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=10, requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)

    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-20T13:00:00Z")
    completed = checkout(started["id"], started["version"], gift_card_id=gc["id"])
    # gross 4500, gift covers all -> charge 0; commission earning round_half_up(4500*0.6)=2700.
    assert completed["total_charged_cents"] == 0

    tech_after = validate_success(api.get_technician(tech["id"], MANAGER))
    assert tech_after["accrued_earnings_cents"] == 2700


def test_checkout_cascade_awards_loyalty_and_depletes_gift(api):
    """PRD §3.10: "It awards the service's `loyalty_points_award` to the client's
    `loyalty_points_balance`."
    PRD §3.10: "If the gift-card draw brought the card's `balance_cents` to exactly
    0, the card's `status` transitions from `ACTIVE` to `DEPLETED` (a system-driven
    cascade hop) and the card's `version` increments."

    Design: Difficulty/transitive_cascade/checkout_cascade_depth4_settlement_commission_loyalty_giftdeplete
    """
    set_clock("2026-03-20T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=45,
                          loyalty_points_award=10, requires_sterile_station=False)
    tech = make_technician(station["id"], pay_model="COMMISSION", commission_pct=0.40)
    client = make_client()
    gc = make_gift_card(initial_balance_cents=4500)

    started = drive_to_in_service(client["id"], tech["id"], station["id"], menu["id"],
                                  origin="APPOINTMENT", start_at="2026-03-20T13:00:00Z")
    checkout(started["id"], started["version"], gift_card_id=gc["id"])

    client_after = validate_success(api.get_client(client["id"], FRONT_DESK))
    assert client_after["loyalty_points_balance"] == 10   # awarded, none redeemed
    gc_after = validate_success(api.get_gift_card(gc["id"], FRONT_DESK))
    assert gc_after["balance_cents"] == 0
    assert gc_after["status"] == "DEPLETED"


# ---------------------------------------------------------------------------
# Corner: simpler settlement results + immediate consistency
# ---------------------------------------------------------------------------
def test_checkout_no_extras_charges_full_subtotal(api):
    """PRD §3.10: "Begin with the gross equal to the snapshotted `subtotal_cents`."
    PRD §3.10: "Fourth, the remainder is the client's charge: `total_charged_cents`
    equals the amount remaining after the gift draw."

    Design: Corner/calculations/checkout_no_extras_charges_full_subtotal
    """
    set_clock("2026-07-10T12:00:00Z")
    base = setup_base(base_price_cents=4500, duration_minutes=30)
    started = drive_to_in_service(base["client"]["id"], base["technician"]["id"],
                                  base["station"]["id"], base["menu"]["id"],
                                  origin="WALK_IN")
    completed = checkout(started["id"], started["version"])
    assert completed["total_charged_cents"] == 4500


def test_deposit_only_checkout_charges_remainder(api):
    """PRD §3.10: "First, apply the deposit already held: the deposit credit is
    `deposit_paid_cents` (0 if none was held), and the amount remaining after the
    deposit is the gross minus that credit, floored at 0."

    Design: Corner/calculations/deposit_only_checkout_charges_remainder
    """
    set_clock("2026-07-11T12:00:00Z")
    station = make_station(requires_autoclave=False)
    menu = make_menu_item(base_price_cents=4500, duration_minutes=30,
                          requires_sterile_station=False)
    tech = make_technician(station["id"])
    client = make_client()
    inject_client_state(client["id"], active_no_show_strikes=2,
                        last_no_show_at="2026-07-10T00:00:00Z")
    appt = book_appointment(client["id"], tech["id"], station["id"], menu["id"],
                            origin="APPOINTMENT", start_at="2026-07-11T13:00:00Z")
    validate_success(api.pay_deposit(appt["id"], FRONT_DESK))
    confirm(appt["id"])
    check_in(appt["id"])
    started = start_service(appt["id"], tech["id"])

    completed = checkout(started["id"], started["version"])
    assert completed["deposit_paid_cents"] == 2000
    assert completed["total_charged_cents"] == 2500   # 4500 - 2000


def test_checkout_response_reflects_all_changes_immediately(api):
    """PRD §3.10: "A `FrontDesk` operator or `SalonManager` checks out an
    `IN_SERVICE` appointment, advancing `booking_status` from `IN_SERVICE` to
    `COMPLETED` while settling payment."
    PRD §3.10: "It sets `payment_status` to `SETTLED`."

    Design: Corner/consistency_model/checkout_response_reflects_all_changes_immediately
    """
    set_clock("2026-07-24T12:00:00Z")
    base = setup_base(base_price_cents=3000, duration_minutes=30)
    started = drive_to_in_service(base["client"]["id"], base["technician"]["id"],
                                  base["station"]["id"], base["menu"]["id"],
                                  origin="WALK_IN")
    completed = checkout(started["id"], started["version"])
    assert completed["booking_status"] == "COMPLETED"
    assert completed["payment_status"] == "SETTLED"
    assert completed["total_charged_cents"] == 3000
