"""Calculation corners: rollover cap settlement, UNLIMITED-tier bookability,
the no-membership zero-discount retail path, and intro-free completion charging."""
from test_helpers import (
    validate_success,
    setup_studio,
    set_clock,
    create_location,
    create_member,
    create_service_type,
    create_product,
    create_room,
    create_technician,
    create_and_activate_membership,
    book_reservation,
    book_and_complete_walk_in,
    attach_retail_sale,
    get_member,
    TEST_USERS,
    make_member_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_rollover_cap_forfeits_excess_on_renew(api):
    """PRD 3.3: "First, the pre-renewal balance is captured ... Second, the
    surviving carryover is the smaller of that pre-renewal balance and the
    membership's `max_rollover_credits`. Third, the forfeited amount is the
    pre-renewal balance minus the surviving carryover ... Fourth, the new grant
    is 0 for an `UNLIMITED` tier and otherwise the membership's
    `monthly_credit_grant` ... Fifth, the resulting balance is the surviving
    carryover plus the grant."

    Pre-balance 4, max_rollover 2, grant 4: capped_carryover=2, forfeit=2,
    new_balance=2+4=6, and cycle_index advances to 1.

    Design: Corner/calculations/rollover_cap_forfeit_on_renew
    """
    loc = create_location(name="Roll")
    member = create_member(loc["id"])
    set_clock("2026-06-15T12:00:00Z")
    mbr = create_and_activate_membership(member["id"], tier="PLUS",
                                         monthly_credit_grant=4, monthly_fee_cents=6000,
                                         max_rollover_credits=2)
    data = validate_success(api.renew_membership(mbr["id"], {"payment_outcome": "SUCCEEDED"}, FRONT), 200)
    assert data["credit_balance"] == 6, f"expected new balance 6, got {data['credit_balance']}"
    assert data["cycle_index"] == 1
    assert data["status"] == "ACTIVE"


def test_unlimited_tier_books_with_zero_balance(api):
    """PRD 3.4: "For an `UNLIMITED` tier the effective balance is treated as
    unbounded, so a credit booking always has enough".
    PRD 3.3: "the grant is honored for `BASIC` and `PLUS` and ignored for
    `UNLIMITED`".

    An ACTIVE UNLIMITED membership (credit_balance 0, grant ignored) books a
    CREDIT reservation successfully and the balance stays 0.

    Design: Corner/calculations/unlimited_tier_books_without_credit_balance
    """
    studio = setup_studio(clock="2026-06-15T12:00:00Z", location_overrides={"name": "Unl"},
                          service_overrides={"name": "QU", "duration_minutes": 30,
                                             "list_price_cents": 3000, "credit_cost": 1})
    member = studio["member"]
    mbr = create_and_activate_membership(member["id"], tier="UNLIMITED",
                                         monthly_credit_grant=0, monthly_fee_cents=9000)
    res = book_reservation(member=member, location_id=studio["loc"]["id"],
                           room_id=studio["room"]["id"], technician_id=studio["tech"]["id"],
                           service_type_id=studio["svc"]["id"], start_utc="2026-06-16T10:00:00Z",
                           payment_method="CREDIT", expected_room_version=studio["room"]["version"],
                           membership_id=mbr["id"], expected_membership_version=mbr["version"],
                           booked_by="frontdesk")
    assert res["booking_status"] == "BOOKED"
    assert res["settlement_status"] == "CREDIT_HELD"
    after = validate_success(api.get_membership(mbr["id"], make_member_headers(member["id"])), 200)
    assert after["credit_balance"] == 0


def test_retail_no_active_membership_zero_discount(api):
    """PRD 3.7: "The member discount applies only when the buyer holds a
    membership whose `status` is `ACTIVE` at confirm time; if the buyer has no
    active membership, the `member_discount_pct` is treated as zero and the
    `discount_cents` is zero."

    A buyer with no membership: discount_cents==0 and net_cents==gross_cents
    (1299*2 = 2598).

    Design: Corner/calculations/retail_net_no_membership_zero_discount
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Nm")
    svc = create_service_type(name="QN", duration_minutes=30, list_price_cents=2000)
    product = create_product(name="Serum", unit_price_cents=1299, member_discount_pct=0.10,
                             stock_qty=100)
    room = create_room(loc["id"], label="RN")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TN")
    member = create_member(loc["id"])
    studio = {"loc": loc, "svc": svc, "room": room, "tech": tech, "member": member}
    res = book_and_complete_walk_in(studio, start_utc="2026-06-16T10:00:00Z",
                                    checkin_clock="2026-06-16T09:45:00Z")
    sale = attach_retail_sale(member, res["id"], product["id"], quantity=2)
    confirmed = validate_success(api.confirm_retail_sale(
        sale["id"], {"expected_product_version": product["version"]}, FRONT), 200)
    assert confirmed["gross_cents"] == 2598
    assert confirmed["discount_cents"] == 0
    assert confirmed["net_cents"] == 2598


def test_intro_free_completion_charges_zero_and_marks_intro(api):
    """PRD 3.6: "For an `INTRO_FREE` visit the final charge is 0 and the member's
    `intro_used` flag is set true as a cross-entity effect".

    An INTRO_FREE reservation on an intro-eligible service completes with
    charged_amount_cents==0, settlement PAID, and the member's intro_used flips to
    true.

    Design: Corner/calculations/intro_free_completion_marks_intro_used
    """
    set_clock("2026-06-15T12:00:00Z")
    loc = create_location(name="Intro")
    svc = create_service_type(name="Brow Intro", duration_minutes=15, list_price_cents=2100,
                              intro_eligible=True)
    room = create_room(loc["id"], label="RInt")
    tech = create_technician(loc["id"], certified_service_ids=[svc["id"]], full_name="TInt")
    member = create_member(loc["id"])
    res = book_reservation(member=member, location_id=loc["id"], room_id=room["id"],
                           technician_id=tech["id"], service_type_id=svc["id"],
                           start_utc="2026-06-16T10:00:00Z", payment_method="INTRO_FREE",
                           expected_room_version=room["version"], booked_by="frontdesk")
    set_clock("2026-06-16T09:45:00Z")
    api.check_in_reservation(res["id"], FRONT)
    completed = validate_success(api.complete_reservation(res["id"], FRONT), 200)
    assert completed["charged_amount_cents"] == 0
    assert completed["settlement_status"] == "PAID"
    assert get_member(member["id"])["intro_used"] is True
