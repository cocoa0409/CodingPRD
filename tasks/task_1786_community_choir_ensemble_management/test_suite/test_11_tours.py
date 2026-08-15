"""Tours: provisional/final cost shares, registration gates, refunds, waitlist."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    confirm_registration,
    create_open_season_with_section,
    create_registration_payload,
    create_tour,
    enroll_member,
    issue_invoice,
    make_member_headers,
    open_tour_registration,
    register_member_for_tour,
    set_clock,
    setup_tour_open_with_active_members,
    validate_error,
    validate_success,
)


class TestTourCostShareVariants:
    def test_tour_cost_share_provisional_vs_final(self, api,
                                                  president_headers,
                                                  treasurer_headers):
        """PRD §3.8: "Opening computes `provisional_share_cents`: the total
        cost divided by `min_seats`, rounded half up to integer cents."
        PRD §3.8: "At lock, `final_share_cents` is computed as the total cost
        divided by `confirmed_count`, rounded half up to integer cents — the
        provisional and final shares diverge whenever the confirmed roster
        differs from `min_seats` — and each `CONFIRMED` registration settles:
        its `share_charge_cents` is set to `final_share_cents`, its
        `refund_cents` to `deposit_paid_cents` minus `final_share_cents`, and
        the treasury is debited each refund, returning the difference to the
        member."

        Design: Difficulty/dual_variant_calc/tour_cost_share_provisional_vs_final
        """
        season, _section, members, tour = (
            setup_tour_open_with_active_members(
                num_members=2, seat_count=2, min_seats=1, cost=10000))
        # Provisional denominator is min_seats: 10000 / 1.
        assert tour["provisional_share_cents"] == 10000
        assert tour["final_share_cents"] is None

        r1 = register_member_for_tour(tour["id"], members[0]["id"])
        r2 = register_member_for_tour(tour["id"], members[1]["id"])
        c1 = confirm_registration(r1["id"])
        c2 = confirm_registration(r2["id"])
        # Deposit equals the provisional share at confirm time.
        assert c1["deposit_paid_cents"] == 10000
        assert c2["deposit_paid_cents"] == 10000

        locked = validate_success(api.transition_tour(
            tour["id"], "LOCK_ROSTER", president_headers))
        assert locked["status"] == "ROSTER_LOCKED"
        # Final denominator is confirmed_count: 10000 / 2.
        assert locked["final_share_cents"] == 5000
        assert locked["provisional_share_cents"] == 10000

        reg = validate_success(api.get_registration(r1["id"],
                                                    treasurer_headers))
        assert reg["share_charge_cents"] == 5000
        assert reg["refund_cents"] == 5000

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # 2*18000 dues + 2*10000 deposits - 2*5000 lock refunds.
        assert season_data["treasury_balance_cents"] == 46000

    def test_tour_cost_share_variants_agree_at_min_seats(
            self, api, president_headers, treasurer_headers):
        """PRD §3.8: "the provisional and final shares diverge whenever the
        confirmed roster differs from `min_seats`" — when the confirmed roster
        equals `min_seats`, the final share equals the provisional share and no
        refund is due.

        Design: Difficulty/dual_variant_calc/tour_cost_share_provisional_vs_final
        """
        season, _section, members, tour = (
            setup_tour_open_with_active_members(
                num_members=2, seat_count=2, min_seats=2, cost=10000))
        assert tour["provisional_share_cents"] == 5000  # 10000 / 2

        r1 = register_member_for_tour(tour["id"], members[0]["id"])
        r2 = register_member_for_tour(tour["id"], members[1]["id"])
        confirm_registration(r1["id"])
        confirm_registration(r2["id"])

        locked = validate_success(api.transition_tour(
            tour["id"], "LOCK_ROSTER", president_headers))
        assert locked["final_share_cents"] == 5000, \
            "confirmed_count == min_seats: denominators agree"
        reg = validate_success(api.get_registration(r1["id"],
                                                    treasurer_headers))
        assert reg["share_charge_cents"] == 5000
        assert reg["refund_cents"] == 0


class TestTourRegistrationGates:
    def test_registration_on_planning_tour_rejected(self, api):
        """PRD §3.8: "Registration requires the tour to be
        `REGISTRATION_OPEN`, else `ERR_TOUR_NOT_OPEN`"

        Design: Corner/validations/registration_on_planning_tour_rejected
        """
        season, section = create_open_season_with_section()
        member = activate_member(season["id"], section["id"])
        tour = create_tour(season["id"])  # stays PLANNING

        resp = api.create_registration(
            create_registration_payload(tour["id"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_TOUR_NOT_OPEN)

    def test_duplicate_registration_rejected(self, api):
        """PRD §3.8: "forbids a second non-terminal registration on the same
        tour — a member already `REGISTERED`, `CONFIRMED`, or `WAITLISTED` is
        rejected with `ERR_ALREADY_REGISTERED`."

        Design: Corner/validations/duplicate_registration_rejected
        """
        _season, _section, members, tour = (
            setup_tour_open_with_active_members(num_members=1))
        first = register_member_for_tour(tour["id"], members[0]["id"])
        assert first["status"] == "REGISTERED"

        resp = api.create_registration(
            create_registration_payload(tour["id"]),
            make_member_headers(members[0]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_REGISTERED)

    def test_dues_not_current_blocks_registration(self, api):
        """PRD §3.8: "requires the member's `dues_balance_cents` to be zero and
        the member to be `performance_eligible`, else `ERR_DUES_NOT_CURRENT`"

        Design: Corner/validations/dues_not_current_blocks_registration
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        issue_invoice(member["id"])  # unpaid: balance 18000
        tour = create_tour(season["id"], transport_lodging_cost_cents=5000)
        open_tour_registration(tour["id"])

        resp = api.create_registration(
            create_registration_payload(tour["id"]),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_DUES_NOT_CURRENT)


class TestTourTransitions:
    def test_tour_open_registration_with_past_departure_rejected(
            self, api, president_headers):
        """PRD §3.8: "Opening registration — `PLANNING` to `REGISTRATION_OPEN`
        — requires `departure_at` to lie in the future, else
        `ERR_TOUR_IN_PAST`"

        Design: Corner/state_machines/tour_open_registration_with_past_departure_rejected
        """
        season = create_open_season_with_section()[0]
        # Departure 2026-07-01 is before the startup clock (2026-08-01).
        tour = create_tour(season["id"],
                           departure_at="2026-07-01T00:00:00Z",
                           return_at="2026-07-05T00:00:00Z",
                           transport_lodging_cost_cents=5000)
        resp = api.transition_tour(tour["id"], "OPEN_REGISTRATION",
                                   president_headers)
        validate_error(resp, ApiErrorId.ERR_TOUR_IN_PAST)

    def test_tour_lock_below_min_seats_rejected(self, api, president_headers):
        """PRD §3.8: "Locking the roster — `REGISTRATION_OPEN` to
        `ROSTER_LOCKED` — requires `confirmed_count` to be at least
        `min_seats`, else `ERR_BELOW_MIN_SEATS`."

        Design: Corner/state_machines/tour_lock_below_min_seats_rejected
        """
        _season, _section, members, tour = (
            setup_tour_open_with_active_members(
                num_members=1, seat_count=3, min_seats=2, cost=10000))
        r1 = register_member_for_tour(tour["id"], members[0]["id"])
        confirm_registration(r1["id"])  # confirmed_count 1 < min_seats 2

        resp = api.transition_tour(tour["id"], "LOCK_ROSTER",
                                   president_headers)
        validate_error(resp, ApiErrorId.ERR_BELOW_MIN_SEATS)

        tour_data = validate_success(api.get_tour(tour["id"],
                                                  president_headers))
        assert tour_data["status"] == "REGISTRATION_OPEN"


class TestTourRefundSchedule:
    def test_registration_cancel_exactly_sixty_days_full_refund(
            self, api, treasurer_headers):
        """PRD §3.8: "Cancelling a `CONFIRMED` one refunds by schedule: the
        number of whole days between now and the tour's `departure_at`
        determines the percentage — sixty days or more returns the full
        deposit, thirty to fifty-nine days returns half, and fewer than thirty
        days returns nothing — and `refund_cents` is the deposit multiplied by
        that percentage, rounded half up to integer cents. The boundaries are
        exact: exactly sixty days before departure yields 100 percent, exactly
        thirty days yields 50 percent, and twenty-nine days yields nothing."

        Design: Corner/state_machines/registration_cancel_exactly_sixty_days_full_refund
        """
        season, _section, members, tour = (
            setup_tour_open_with_active_members(
                num_members=1, seat_count=2, min_seats=1, cost=5000))
        r1 = register_member_for_tour(tour["id"], members[0]["id"])
        confirmed = confirm_registration(r1["id"])
        assert confirmed["deposit_paid_cents"] == 5000

        # Exactly 60 days before the 2026-12-01 departure: full refund.
        set_clock("2026-10-02T00:00:00Z")
        cancelled = validate_success(api.cancel_registration(
            r1["id"], make_member_headers(members[0]["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["refund_cents"] == 5000, \
            "the 60-day boundary is inclusive at 100 percent"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # 18000 dues + 5000 deposit - 5000 refund.
        assert season_data["treasury_balance_cents"] == 18000


class TestTourWaitlistPromotion:
    def test_tour_waitlist_promotion_on_cancel(self, api, treasurer_headers):
        """PRD §3.8: "If a seat is free the registration opens as `REGISTERED`,
        otherwise as `WAITLISTED`."
        PRD §3.8: "Promotion itself is deterministic: the oldest `WAITLISTED`
        registration by `created_at` ascending moves to `REGISTERED` whenever a
        freed seat exists while the tour is `REGISTRATION_OPEN`, a sweep also
        run at each checkpoint."

        Design: Corner/state_machines/tour_waitlist_promotion_on_cancel
        """
        _season, _section, members, tour = (
            setup_tour_open_with_active_members(
                num_members=2, seat_count=1, min_seats=1, cost=5000))
        r1 = register_member_for_tour(tour["id"], members[0]["id"])
        r2 = register_member_for_tour(tour["id"], members[1]["id"])
        assert r1["status"] == "REGISTERED"
        assert r2["status"] == "WAITLISTED", "the single seat is taken"

        cancelled = validate_success(api.cancel_registration(
            r1["id"], make_member_headers(members[0]["id"])))
        assert cancelled["status"] == "CANCELLED"

        promoted = validate_success(api.get_registration(r2["id"],
                                                         treasurer_headers))
        assert promoted["status"] == "REGISTERED", \
            "freed seat promotes the oldest waitlisted registration"
