"""Box-office entitlement and fiscal-precondition validations.

Advance access, comp allowance, credit honesty, member email uniqueness and the
two money rules that guard opening and confirming an engagement.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_member,
    booking_payload,
    catalogue_title,
    enrol_member,
    lodge_donation,
    make_member_headers,
    member_payload,
    open_engagement,
    read_booking,
    read_member,
    read_showtime,
    register_distributor,
    register_venue,
    setup_screening_on_sale,
    ticket_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PROGRAMMER = TEST_USERS["programmer_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
EXECUTIVE_DIRECTOR = TEST_USERS["executive_director_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def _orders(api, **params):
    rows, _meta = validate_paginated(api.list_ticket_orders(BOX_OFFICE, params=params))
    return rows


class TestSalesWindowEntitlement:

    def test_ticket_order_walkup_before_public_onsale_is_refused(self, api):
        """PRD §3.8: "When a screening's `public_sale_opens_at` is later than the
        logical clock, public sales have not opened, and the order is admitted
        only if the buyer's own advance window has: that is, only if the clock has
        reached `public_sale_opens_at` moved earlier by the buyer's
        `advance_access_hours`."

        PRD §3.8: "Anonymous walk-ups and members at `PROSPECT` have a zero-hour
        window and are therefore refused outright before public sales open. A
        buyer whose window has not yet opened is refused with
        `ERR_ADVANCE_ACCESS_NOT_OPEN`."

        Design: Corner/validations/walkup_before_public_onsale_is_refused
        """
        # Sales are deliberately ON_SALE with every seat free, so neither the
        # sales-closed rung nor the capacity rung can be the one that answers.
        world = setup_screening_on_sale(
            "2026-08-14T12:00:00Z",
            showtime_overrides={"public_sale_opens_at": "2026-08-10T00:00:00Z"},
        )
        showtime_id = world["showtime"]["id"]
        assert world["showtime"]["sale_status"] == "ON_SALE", (
            f"Expected ON_SALE, got {world['showtime']['sale_status']}"
        )

        # No member_id at all, so the buyer's advance window is zero hours wide
        # while public sales are still nine days away.
        response = api.create_ticket_order(
            ticket_order_payload(
                showtime_id, 2, purchaser_email="early@example.com"
            ),
            ANONYMOUS,
        )

        validate_error(response, ApiErrorId.ERR_ADVANCE_ACCESS_NOT_OPEN.value)

        showtime = read_showtime(showtime_id)
        assert showtime["sale_status"] == "ON_SALE", (
            f"Expected the window still ON_SALE, got {showtime['sale_status']}"
        )
        assert showtime["seats_available"] == 8, (
            f"Expected seats_available 8, got {showtime['seats_available']}"
        )
        assert showtime["seats_sold"] == 0, (
            f"Expected seats_sold 0, got {showtime['seats_sold']}"
        )
        assert showtime["gross_cents"] == 0, (
            f"Expected gross_cents 0, got {showtime['gross_cents']}"
        )
        assert _orders(api, showtime_id=showtime_id) == [], (
            "A refused order must leave no ticket order behind"
        )

    def test_ticket_order_comp_seats_refused_for_a_basic_tier_member(self, api):
        """PRD §3.8: "Comps are only for the upper tiers: `comp_quantity` must be
        zero unless the order carries a `member_id` whose `effective_tier` is
        `SUPPORTER` or `DONOR_CIRCLE`, and it must never exceed either the order's
        own `quantity` or the member's `comp_tickets_remaining`; a violation of
        any of those is refused with `ERR_COMP_ALLOWANCE_EXCEEDED`, and an
        anonymous or walk-up order may never carry comps at all."

        PRD §3.7: "`comp_tickets_granted` is 0 for both `PROSPECT` and `BASIC`, 2
        for `SUPPORTER` and 6 for `DONOR_CIRCLE`, being the comp allowance for the
        current membership term."

        Design: Corner/validations/comp_seats_refused_for_a_basic_tier_member
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]

        member = enrol_member(full_name="Bo Lin", email="bo@example.com")
        # 6000 cents is exactly the BASIC threshold, so the member is ACTIVE and
        # entitled to a discount but to no comps whatsoever.
        member = lodge_donation(member["id"], 6000, "2026-03-01T10:00:00Z")
        assert member["effective_tier"] == "BASIC", (
            f"Expected effective_tier BASIC, got {member['effective_tier']}"
        )
        assert member["comp_tickets_remaining"] == 0, (
            "Expected comp_tickets_remaining 0, got "
            f"{member['comp_tickets_remaining']}"
        )

        response = api.create_ticket_order(
            ticket_order_payload(
                showtime_id,
                2,
                purchaser_email="bo@example.com",
                member_id=member["id"],
                comp_quantity=1,
            ),
            # A Member acts under their own membership id, so the ownership rung
            # is satisfied and the comp entitlement rung is what answers.
            make_member_headers(member["id"]),
        )

        validate_error(response, ApiErrorId.ERR_COMP_ALLOWANCE_EXCEEDED.value)

        after = read_member(member["id"])
        assert_member(after)
        assert after["status"] == "ACTIVE", (
            f"Expected ACTIVE, got {after['status']}"
        )
        assert after["effective_tier"] == "BASIC", (
            f"Expected BASIC, got {after['effective_tier']}"
        )
        assert after["comp_tickets_granted"] == 0, (
            f"Expected comp_tickets_granted 0, got {after['comp_tickets_granted']}"
        )
        assert after["comp_tickets_remaining"] == 0, (
            f"Expected comp_tickets_remaining 0, got {after['comp_tickets_remaining']}"
        )
        assert _orders(api, member_id=member["id"]) == [], (
            "A refused order must leave no ticket order behind"
        )
        showtime = read_showtime(showtime_id)
        assert showtime["seats_sold"] == 0, (
            f"Expected seats_sold 0, got {showtime['seats_sold']}"
        )
        assert showtime["seats_available"] == 8, (
            f"Expected seats_available 8, got {showtime['seats_available']}"
        )

    def test_ticket_order_credit_redemption_without_a_member_is_refused(self, api):
        """PRD §3.8: "Credit redemption must be honest: `apply_credit` is only
        accepted together with a `member_id`, and only when that member actually
        holds credit at request time; an `apply_credit` without a member, or
        against a `credit_balance_cents` of zero, is refused with
        `ERR_CREDIT_BALANCE_INSUFFICIENT`."

        Design: Corner/validations/credit_redemption_without_a_member_is_refused
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]

        # Public sales are open at the startup clock, so the advance-access rung
        # is satisfied and only the credit-honesty rung can answer.
        response = api.create_ticket_order(
            ticket_order_payload(
                showtime_id, 1, purchaser_email="walkup@example.com", apply_credit=True
            ),
            ANONYMOUS,
        )

        validate_error(response, ApiErrorId.ERR_CREDIT_BALANCE_INSUFFICIENT.value)

        assert _orders(api, showtime_id=showtime_id) == [], (
            "The flag must not be quietly ignored and the order silently taken"
        )
        showtime = read_showtime(showtime_id)
        assert showtime["seats_sold"] == 0, (
            f"Expected seats_sold 0, got {showtime['seats_sold']}"
        )
        assert showtime["seats_available"] == 8, (
            f"Expected seats_available 8, got {showtime['seats_available']}"
        )


class TestMembershipEnrolment:

    def test_member_second_enrolment_with_the_same_email_is_refused(self, api):
        """PRD §3.7: "The email must not already be held by a member whose status
        is `PENDING` or `ACTIVE`, otherwise the request is refused with
        `ERR_MEMBER_EMAIL_TAKEN`."

        PRD §3.7: "A new record starts in `PENDING` with an empty `donations`
        list, a null `expires_at`, `rolling_donation_cents` and
        `fiscal_ytd_donation_cents` at 0, `rolling_tier`, `fiscal_tier` and
        `effective_tier` all at `PROSPECT`, `discount_pct` at 0.00,
        `advance_access_hours` at 0, `comp_tickets_granted` and
        `comp_tickets_remaining` at 0, and `credit_balance_cents` at 0."

        Design: Corner/validations/second_member_with_the_same_email_is_refused
        """
        first = enrol_member(
            full_name="Ada Wells", email="ada@example.com", join_date="2026-07-01"
        )
        assert first["status"] == "PENDING", (
            f"Expected PENDING, got {first['status']} — a never-activated holder "
            "still blocks the address"
        )

        response = api.create_member(
            member_payload(
                full_name="Ada W. Wells",
                email="ada@example.com",
                join_date="2026-08-01",
            ),
            EXECUTIVE_DIRECTOR,
        )

        validate_error(response, ApiErrorId.ERR_MEMBER_EMAIL_TAKEN.value)

        held = read_member(first["id"])
        assert held["status"] == "PENDING", (
            f"Expected PENDING, got {held['status']}"
        )
        assert held["full_name"] == "Ada Wells", (
            f"Expected full_name 'Ada Wells', got {held['full_name']!r} — the "
            "refused create must not overwrite the holder"
        )
        assert held["join_date"] == "2026-07-01", (
            f"Expected join_date 2026-07-01, got {held['join_date']}"
        )
        assert held["version"] == 1, (
            f"Expected version 1, got {held['version']}"
        )

        # A free address is still accepted, so the refusal was about the clash.
        second = validate_success(
            api.create_member(
                member_payload(full_name="Bo Lin", email="bo@example.com"),
                BOX_OFFICE,
            ),
            expected_status=201,
        )
        assert second["email"] == "bo@example.com", (
            f"Expected bo@example.com, got {second['email']}"
        )


class TestEngagementMoneyGuards:

    def test_booking_without_a_guarantee_is_refused_when_the_distributor_demands_one(
        self, api
    ):
        """PRD §3.1: "That flag is a hard fiscal constraint rather than
        documentation: when a distributor demands an advance guarantee, every
        engagement opened against them and every negotiation round lodged on such
        an engagement must carry a guarantee amount strictly greater than zero,
        and a zero guarantee is refused with `ERR_GUARANTEE_REQUIRED`."

        Design: Corner/validations/booking_without_a_guarantee_is_refused_when_the_distributor_demands_one
        """
        venue = register_venue()
        demanding = register_distributor(
            name="Gauntlet Pictures",
            contact_email="deals@gauntlet.example",
            default_terms_variant="PERCENTAGE_FLOOR",
            default_min_run_days=5,
            default_distributor_share_pct=0.40,
            requires_advance_guarantee=True,
        )
        title = catalogue_title(demanding["id"])

        # Everything else in the payload is legal; only guarantee_cents is zero.
        response = api.create_booking(
            booking_payload(
                title["id"],
                demanding["id"],
                venue["id"],
                terms_variant="PERCENTAGE_FLOOR",
                house_nut_cents=12500,
                distributor_share_pct=0.40,
                guarantee_cents=0,
                min_run_days=5,
            ),
            PROGRAMMER,
        )

        validate_error(response, ApiErrorId.ERR_GUARANTEE_REQUIRED.value)

        assert api.get_distributor(demanding["id"], PROGRAMMER).status_code == 200
        rows, _meta = validate_paginated(
            api.list_bookings(PROGRAMMER, params={"distributor_id": demanding["id"]})
        )
        assert rows == [], (
            "No engagement — and therefore no opening negotiation round — may be "
            f"minted by a refused create, got {rows}"
        )

        # The identical payload with a strictly positive guarantee is accepted.
        accepted = validate_success(
            api.create_booking(
                booking_payload(
                    title["id"],
                    demanding["id"],
                    venue["id"],
                    terms_variant="PERCENTAGE_FLOOR",
                    house_nut_cents=12500,
                    distributor_share_pct=0.40,
                    guarantee_cents=1,
                    min_run_days=5,
                ),
                PROGRAMMER,
            ),
            expected_status=201,
        )
        assert accepted["guarantee_cents"] == 1, (
            f"Expected guarantee_cents 1, got {accepted['guarantee_cents']}"
        )

    def test_booking_house_nut_above_the_venue_cap_is_refused_at_confirm(self, api):
        """PRD §3.2: "And the round's `proposed_house_nut_cents` must not exceed
        the auditorium's `base_house_nut_weekly_cents`, otherwise the confirmation
        is refused with `ERR_HOUSE_NUT_ABOVE_CAP`."

        PRD §3.1: "And `base_house_nut_weekly_cents` defaults to 480000 — four
        thousand eight hundred dollars a week — and is the board-approved ceiling
        on the weekly house nut: no engagement may ever be confirmed at a house
        nut above it."

        Design: Corner/validations/house_nut_above_the_venue_cap_is_refused_at_confirm
        """
        venue = register_venue()
        assert venue["base_house_nut_weekly_cents"] == 200000, (
            "Expected the board cap at 200000, got "
            f"{venue['base_house_nut_weekly_cents']}"
        )
        distributor = register_distributor()
        title = catalogue_title(distributor["id"])

        # Opening the engagement at an ambitious 250000 is deliberately allowed:
        # the negotiation log has to be able to hold an ask that will be refused.
        booking = open_engagement(
            title["id"], distributor["id"], venue["id"], house_nut_cents=250000
        )
        assert booking["status"] == "OFFERED", (
            f"Expected OFFERED, got {booking['status']}"
        )

        response = api.confirm_booking(booking["id"], EXECUTIVE_DIRECTOR)

        validate_error(response, ApiErrorId.ERR_HOUSE_NUT_ABOVE_CAP.value)

        after = read_booking(booking["id"])
        assert after["status"] == "OFFERED", (
            f"Expected the engagement still OFFERED, got {after['status']}"
        )
        assert after["confirmed_by_user_id"] is None, (
            "Expected confirmed_by_user_id null, got "
            f"{after['confirmed_by_user_id']!r}"
        )
        offers, _meta = validate_paginated(
            api.list_booking_offers(booking["id"], PROGRAMMER)
        )
        assert len(offers) == 1, (
            f"Expected exactly the one opening round, got {len(offers)}"
        )
        assert offers[0]["round_index"] == 1, (
            f"Expected round_index 1, got {offers[0]['round_index']}"
        )
        assert offers[0]["proposed_house_nut_cents"] == 250000, (
            "Expected the ask recorded at 250000, got "
            f"{offers[0]['proposed_house_nut_cents']}"
        )
        assert offers[0]["outcome"] == "PENDING", (
            f"Expected outcome PENDING, got {offers[0]['outcome']}"
        )
        reread_venue = validate_success(api.get_venue(venue["id"], PROGRAMMER))
        assert reread_venue["base_house_nut_weekly_cents"] == 200000, (
            "The board cap must not be raised to accommodate an offer, got "
            f"{reread_venue['base_house_nut_weekly_cents']}"
        )
