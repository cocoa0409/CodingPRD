"""Treasury aggregation, late-fee accrual, and cross-entity cascades."""
from test_helpers import (
    ApiErrorId,
    activate_member,
    advance_posture,
    confirm_booking,
    contract_in_state,
    create_booking,
    create_concert,
    create_contract,
    create_open_season_with_section,
    create_piece,
    create_score,
    create_tour,
    create_venue,
    checkout_score,
    enroll_member,
    issue_invoice,
    make_president_headers,
    make_treasurer_headers,
    offer_contract,
    open_tour_registration,
    register_member_for_tour,
    run_checkpoint,
    set_clock,
    setup_rehearsing_season_with_active_member,
    validate_error,
    validate_success,
)


class TestTreasuryAggregation:
    def test_treasury_aggregation_mixed_sources(self, api, treasurer_headers):
        """PRD §2.10: "The balance is defined, scoped to a single season, as:
        the sum of `amount_cents` over dues payments in `POSTED` status, ...
        plus the sum of `amount_cents` over pledges in `FULFILLED` status, ...
        minus the `quoted_fee_cents` of guest contracts in `PAID` status, ..."
        PRD §3.9: "computes the donor's `recognition_tier`: `GOLD` for a
        pledge of at least 50000 cents"

        Design: Corner/calculations/treasury_aggregation_mixed_sources
        """
        season, section = create_open_season_with_section()
        member = activate_member(season["id"], section["id"])  # +18000 dues

        committee = validate_success(api.create_committee(
            {"season_id": season["id"], "name": "Gala",
             "chair_member_id": member["id"],
             "fundraising_goal_cents": 200000},
            make_president_headers("pres-1")), 201)
        validate_success(api.transition_committee(
            committee["id"], "ACTIVATE", make_president_headers("pres-1")))
        pledge = validate_success(api.create_pledge(
            {"committee_id": committee["id"], "donor_name": "Big Donor",
             "amount_cents": 100000},
            make_treasurer_headers("treas-1")), 201)
        fulfilled = validate_success(api.fulfill_pledge(
            pledge["id"], make_treasurer_headers("treas-2")))
        assert fulfilled["recognition_tier"] == "GOLD", \
            "100000 >= 50000: the GOLD boundary"

        contract_in_state(
            season["id"], "PAID", rate_cents=30000,
            approver_headers=make_president_headers("pres-1"),
            payer_headers=make_treasurer_headers("treas-1"))  # -30000

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # 18000 dues + 100000 fulfilled pledge - 30000 contract payment.
        assert season_data["treasury_balance_cents"] == 88000
        committee_data = validate_success(api.get_committee(
            committee["id"], treasurer_headers))
        assert committee_data["raised_cents"] == 100000


class TestLateFeeAccrual:
    def test_late_fee_accrual_capped_and_enrolled_not_suspended(
            self, api, treasurer_headers, director_headers):
        """PRD §3.4: "the late fee accrues: the number of full weeks overdue is
        the count of whole seven-day periods between `dues_due_date` and now,
        never below zero — exactly seven days overdue counts as one full week —
        and `late_fee_cents` is the lesser of the season's `late_fee_cap_cents`
        and the weeks overdue multiplied by `late_fee_weekly_cents`. An invoice
        moving to `OVERDUE` suspends an `ACTIVE` or `PROBATION` member."

        Design: Corner/calculations/late_fee_accrual_capped_and_enrolled_not_suspended
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])  # 18000, ISSUED, unpaid

        # 2026-09-01 -> 2026-10-15 is 44 days = 6 full weeks: 6*500 = 3000,
        # capped at late_fee_cap_cents 2000.
        set_clock("2026-10-15T00:00:00Z")
        run_checkpoint(season["id"])

        data = validate_success(api.get_invoice(invoice["id"],
                                                treasurer_headers))
        assert data["status"] == "OVERDUE"
        assert data["late_fee_cents"] == 2000, "raw 3000 hits the 2000 cap"
        assert data["balance_cents"] == 20000, "18000 dues + 2000 late fee"

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["status"] == "ENROLLED", \
            "the suspension sweep covers only ACTIVE or PROBATION members"


class TestConcertCancelCascade:
    def test_concert_cancel_depth3_cascade(self, api, director_headers,
                                           treasurer_headers):
        """PRD §3.6: "Cancelling a concert runs the concert-cancel cascade,
        available from `PLANNING`, `VENUE_BOOKED`, `PROGRAM_LOCKED`, or
        `READY`. The cascade releases the concert's booking: a booking in
        `REQUESTED` or `CONFIRMED` moves to `RELEASED`, and where a deposit was
        actually posted — a `CONFIRMED` booking — `deposit_cents` is refunded
        to the season treasury. It then voids every non-`VOID` program piece,
        and each voided piece cancels its linked guest contract when that
        contract stands in `OFFERED`, `COUNTERED`, `ACCEPTED`, or `APPROVED`;
        a contract cancelled after acceptance posts its cancellation fee as a
        treasury debit, as §3.7 specifies."
        PRD §3.7: "Cancelling from `ACCEPTED` or `APPROVED` posts a
        `cancellation_fee_cents` of twenty percent of `quoted_fee_cents`,
        rounded half up to integer cents, debited from the treasury"

        Design: Difficulty/transitive_cascade/concert_cancel_depth3_cascade
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())  # treasury 18000
        venue = create_venue()
        concert = create_concert(season["id"], "Winter Gala", 80)
        booking = create_booking(concert["id"], venue["id"],
                                 deposit_cents=10000)
        confirm_booking(booking["id"])  # treasury 8000; concert VENUE_BOOKED

        contract = create_contract(
            season["id"],
            service_lines=[{"kind": "CONCERT", "units": 1,
                            "rate_cents": 30000}],
            concert_id=concert["id"])
        offer_contract(contract["id"])
        validate_success(api.accept_contract(contract["id"], director_headers))

        piece = create_piece(concert["id"], "Suite", 3600, 1,
                             guest_contract_id=contract["id"])
        validate_success(api.confirm_piece(piece["id"], director_headers))

        cancelled = validate_success(api.transition_concert(
            concert["id"], "CANCEL", director_headers))
        assert cancelled["status"] == "CANCELLED"

        booking_data = validate_success(api.get_booking(booking["id"],
                                                        treasurer_headers))
        assert booking_data["status"] == "RELEASED"
        piece_data = validate_success(api.get_piece(piece["id"],
                                                    director_headers))
        assert piece_data["status"] == "VOID"
        contract_data = validate_success(api.get_contract(contract["id"],
                                                          director_headers))
        assert contract_data["status"] == "CANCELLED"
        # round_half_up(0.20 * 30000) = 6000
        assert contract_data["cancellation_fee_cents"] == 6000

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # 18000 dues - 10000 deposit + 10000 deposit refund - 6000 fee.
        assert season_data["treasury_balance_cents"] == 12000

    def test_concert_cancel_from_planning_releases_unconfirmed_booking(
            self, api, director_headers, treasurer_headers):
        """PRD §3.6: "The cascade releases the concert's booking: a booking in
        `REQUESTED` or `CONFIRMED` moves to `RELEASED`, and where a deposit was
        actually posted — a `CONFIRMED` booking — `deposit_cents` is refunded
        to the season treasury."
        PRD §3.7: "Cancelling a contract in `DRAFT`, `OFFERED`, or `COUNTERED`
        — whether by the director directly or by the concert cascade — costs
        nothing: no cancellation fee exists before acceptance."

        Design: Difficulty/transitive_cascade/concert_cancel_depth3_cascade
        """
        season, _section, _member = (
            setup_rehearsing_season_with_active_member())  # treasury 18000
        venue = create_venue()
        concert = create_concert(season["id"])
        booking = create_booking(concert["id"], venue["id"])  # REQUESTED
        contract = create_contract(
            season["id"],
            service_lines=[{"kind": "CONCERT", "units": 1,
                            "rate_cents": 30000}],
            concert_id=concert["id"])
        offer_contract(contract["id"])  # OFFERED
        piece = create_piece(concert["id"], "Suite", 3600, 1,
                             guest_contract_id=contract["id"])  # DRAFT

        cancelled = validate_success(api.transition_concert(
            concert["id"], "CANCEL", director_headers))
        assert cancelled["status"] == "CANCELLED"

        booking_data = validate_success(api.get_booking(booking["id"],
                                                        treasurer_headers))
        assert booking_data["status"] == "RELEASED", \
            "the cascade releases even a REQUESTED booking"
        piece_data = validate_success(api.get_piece(piece["id"],
                                                    director_headers))
        assert piece_data["status"] == "VOID"
        contract_data = validate_success(api.get_contract(contract["id"],
                                                          director_headers))
        assert contract_data["status"] == "CANCELLED"
        assert contract_data["cancellation_fee_cents"] == 0, \
            "no cancellation fee exists before acceptance"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        # No deposit was ever posted, and no fee: treasury unchanged.
        assert season_data["treasury_balance_cents"] == 18000


class TestMemberDropCascade:
    def test_member_drop_depth2_cascade(self, api, director_headers,
                                        librarian_headers):
        """PRD §3.3: "Both run the same member-drop cascade: any score checkout
        still `CHECKED_OUT` or `OVERDUE` is marked `LOST` with the charges
        described in §3.5 posted to the member's ledger"
        PRD §3.5: "Marking a copy lost moves the checkout to `LOST`, sets
        `charge_cents` to the score's `replacement_cost_cents` and posts it to
        `ledger_balance_cents` — together with the accrued fine when the
        checkout was `OVERDUE` — and increments `copies_lost`."

        Design: Difficulty/transitive_cascade/member_drop_depth2_cascade
        """
        season, section = create_open_season_with_section()
        member = activate_member(season["id"], section["id"])
        score = create_score(copy_count=2, replacement_cost_cents=7000)
        checkout = checkout_score(score["id"], member["id"],
                                  "2026-08-10T00:00:00Z")

        dropped = validate_success(api.set_member_status(
            member["id"], "DROP", director_headers))
        assert dropped["status"] == "DROPPED"

        checkout_data = validate_success(api.get_checkout(checkout["id"],
                                                          librarian_headers))
        assert checkout_data["status"] == "LOST"
        assert checkout_data["charge_cents"] == 7000

        member_data = validate_success(api.get_member(member["id"],
                                                      director_headers))
        assert member_data["ledger_balance_cents"] == 7000

        score_data = validate_success(api.get_score(score["id"],
                                                    librarian_headers))
        assert score_data["copies_lost"] == 1
        assert score_data["copies_available"] == 1, \
            "2 copies minus 0 open checkouts minus 1 lost"

    def test_member_drop_cancels_registrations_and_recomputes_section(
            self, api, director_headers, treasurer_headers):
        """PRD §3.3: "the member's non-terminal tour registrations are
        cancelled and the freed seats trigger waitlist promotion; and the
        section's `active_count` is recomputed."

        Design: Difficulty/transitive_cascade/member_drop_depth2_cascade
        """
        season, section = create_open_season_with_section(target_max=4)
        m1 = activate_member(season["id"], section["id"], "A One",
                             "a1@x.org", "2026-08-02T10:00:00Z")
        m2 = activate_member(season["id"], section["id"], "A Two",
                             "a2@x.org", "2026-08-02T11:00:00Z")
        tour = create_tour(season["id"], seat_count=1, min_seats=1,
                           transport_lodging_cost_cents=5000)
        open_tour_registration(tour["id"])
        r1 = register_member_for_tour(tour["id"], m1["id"])
        r2 = register_member_for_tour(tour["id"], m2["id"])
        assert r1["status"] == "REGISTERED"
        assert r2["status"] == "WAITLISTED"

        validate_success(api.set_member_status(m1["id"], "DROP",
                                               director_headers))

        r1_data = validate_success(api.get_registration(r1["id"],
                                                        treasurer_headers))
        assert r1_data["status"] == "CANCELLED", \
            "drop cascade cancels the member's non-terminal registrations"
        r2_data = validate_success(api.get_registration(r2["id"],
                                                        treasurer_headers))
        assert r2_data["status"] == "REGISTERED", \
            "the freed seat triggers waitlist promotion"

        section_data = validate_success(api.get_section(section["id"],
                                                        director_headers))
        assert section_data["active_count"] == 1, \
            "DROPPED members no longer count toward the section"


class TestTreasuryDebitGuard:
    def test_booking_confirm_with_empty_treasury_rejected(
            self, api, treasurer_headers):
        """PRD §3.6: "Confirming a booking is the Treasurer's job and requires
        the treasury to cover the deposit, else `ERR_INSUFFICIENT_TREASURY`"
        PRD §2.10: "Any operation that would debit more than the season's
        current `treasury_balance_cents` — confirming a booking deposit, paying
        a contract, posting a cancellation fee, refunding a payment, pledge, or
        registration — is rejected with `ERR_INSUFFICIENT_TREASURY`."

        Design: Corner/validations/booking_confirm_with_empty_treasury_rejected
        """
        season, section = create_open_season_with_section()
        member = enroll_member(season["id"], section["id"])
        invoice = issue_invoice(member["id"])
        # Activate the member via a full scholarship waiver so the treasury
        # stays at exactly zero.
        grant = validate_success(api.create_grant(
            {"member_id": member["id"], "requested_cents": 18000},
            treasurer_headers), 201)
        validate_success(api.decide_grant(
            grant["id"], {"decision": "APPROVE"}, treasurer_headers))
        applied = validate_success(api.apply_grant(
            grant["id"], {"invoice_id": invoice["id"]}, treasurer_headers))
        assert applied["status"] == "APPLIED"

        season_data = validate_success(api.get_season(season["id"],
                                                      treasurer_headers))
        assert season_data["treasury_balance_cents"] == 0

        advance_posture(season["id"], "REHEARSING")
        venue = create_venue()
        concert = create_concert(season["id"])
        booking = create_booking(concert["id"], venue["id"],
                                 deposit_cents=50000)

        resp = api.confirm_booking(booking["id"], treasurer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_TREASURY)

        booking_data = validate_success(api.get_booking(booking["id"],
                                                        treasurer_headers))
        assert booking_data["status"] == "REQUESTED", \
            "rejected confirm leaves the booking REQUESTED"
