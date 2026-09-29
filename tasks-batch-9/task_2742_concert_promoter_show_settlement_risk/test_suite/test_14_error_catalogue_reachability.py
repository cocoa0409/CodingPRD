"""Reachability of the declared error catalogue.

Every error id the contract declares is driven here through the declared
surface, so no id sits in the catalogue without a request that provokes it.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    factories,
    get_success_data,
    make_artist_rep_headers,
    make_headers_with_empty_role,
    make_headers_with_empty_user_id,
    make_headers_with_no_identity,
    make_headers_without_role,
    make_headers_without_user_id,
    make_talent_buyer_headers,
    make_tour_accountant_headers,
    make_unknown_role_headers,
    validate_error,
)
from test_helpers import api_errors as E

# Every show booked here is a RENTAL date, which the contract requires to carry
# a positive flat fee.
RENTAL_FEE_CENTS = 50_000

# The eleven single-resource reads, each paired with the not-found id that
# guards its path variable. A TourAccountant is authorised on all eleven.
NOT_FOUND_PROBES = [
    ("get_market", E.ERR_MARKET_NOT_FOUND),
    ("get_artist", E.ERR_ARTIST_NOT_FOUND),
    ("get_venue", E.ERR_VENUE_NOT_FOUND),
    ("get_show", E.ERR_SHOW_NOT_FOUND),
    ("get_offer", E.ERR_OFFER_NOT_FOUND),
    ("get_budget_line", E.ERR_BUDGET_LINE_NOT_FOUND),
    ("get_vendor_invoice", E.ERR_VENDOR_INVOICE_NOT_FOUND),
    ("get_ticket_tier", E.ERR_TICKET_TIER_NOT_FOUND),
    ("get_ticket_hold", E.ERR_TICKET_HOLD_NOT_FOUND),
    ("get_settlement", E.ERR_SETTLEMENT_NOT_FOUND),
    ("get_cancellation_event", E.ERR_CANCELLATION_EVENT_NOT_FOUND),
]


class TestIdentityAndAuthorisationErrorsAreReachable:
    @pytest.mark.parametrize(
        "headers",
        [
            make_headers_with_no_identity(),
            make_headers_without_user_id(),
            make_headers_without_role(),
            make_headers_with_empty_user_id(),
            make_headers_with_empty_role(),
        ],
    )
    def test_err_unauthenticated_on_a_missing_or_empty_identity_header(
        self, api, headers
    ):
        """From PRD §2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This check precedes everything else, including request-body parsing and resource lookup."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        response = api.get_show(NON_EXISTENT_UUID, headers)

        validate_error(response, E.ERR_UNAUTHENTICATED)

    def test_err_unauthenticated_precedes_request_body_parsing(self, api):
        """From PRD §2.1: "This check precedes everything else, including request-body parsing and resource lookup."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        response = api.create_market({}, make_headers_with_no_identity())

        validate_error(response, E.ERR_UNAUTHENTICATED)

    @pytest.mark.parametrize(
        "headers",
        [make_unknown_role_headers(role="Producer"), make_talent_buyer_headers()],
    )
    def test_err_role_forbidden_for_an_unknown_or_unauthorised_role(self, api, headers):
        """From PRD §2.1: "If `X-User-Role` holds any other string, or holds one of the five but that role is not listed as authorised for the endpoint being called, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        response = api.create_market(factories.market_payload(), headers)

        validate_error(response, E.ERR_ROLE_FORBIDDEN)

    def test_err_not_resource_owner_when_another_act_accepts_the_offer(
        self, api, build
    ):
        """From PRD §2.1: "When an entity-backed role acts on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        stranger = build.artist(name="Someone Else", tier="CLUB", withholding_pct=0)
        offer = build.submitted_offer(ctx["show"]["id"], guarantee_cents=100_000)

        response = api.accept_offer(
            offer["id"], make_artist_rep_headers(stranger["id"])
        )

        validate_error(response, E.ERR_NOT_RESOURCE_OWNER)
        assert build.read_offer(offer["id"])["status"] == "SUBMITTED"

    def test_err_segregation_of_duties_when_the_verifier_also_approves(
        self, api, build
    ):
        """From PRD §3.6: "Approval — available to a `TourAccountant` or a `RiskOfficer` — moves it `VERIFIED → APPROVED` and records `approved_by_user_id`, and requires an acting `X-User-ID` different from the recorded `verified_by_user_id`"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.budget_line(ctx["show"]["id"], budgeted_cents=60_000)
        invoice = get_success_data(
            api.create_vendor_invoice(
                factories.vendor_invoice_payload(
                    ctx["show"]["id"], line["id"], amount_cents=60_000
                ),
                build.accountant,
            )
        )
        get_success_data(api.verify_vendor_invoice(invoice["id"], build.accountant))

        response = api.approve_vendor_invoice(invoice["id"], build.accountant)

        validate_error(response, E.ERR_SEGREGATION_OF_DUTIES)
        assert build.read_invoice(invoice["id"])["status"] == "VERIFIED"

    def test_err_variance_approval_authority_on_a_risk_officer_line(self, api, build):
        """From PRD §3.6: "a `RiskOfficer` may decide any line, while a `TourAccountant` may decide only lines whose `required_approver_role` is `NONE` or `TOUR_ACCOUNTANT` and is refused on a `RISK_OFFICER` line with `ERR_VARIANCE_APPROVAL_AUTHORITY` (HTTP 403)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.line_with_actual(
            ctx["show"]["id"], budgeted_cents=200_000, actual_cents=260_000
        )
        assert line["variance_status"] == "PENDING_APPROVAL"
        assert line["required_approver_role"] == "RISK_OFFICER"

        response = api.decide_variance(
            line["id"],
            build.accountant,
            decision="APPROVE",
            approved_cap_cents=260_000,
            variance_justification="the change order was signed on site",
        )

        validate_error(response, E.ERR_VARIANCE_APPROVAL_AUTHORITY)
        assert build.read_budget_line(line["id"])["variance_status"] == "PENDING_APPROVAL"

    def test_err_invalid_request_for_a_missing_field_or_an_undeclared_enum_member(
        self, api, build
    ):
        """From PRD §2.9: "Request-body well-formedness — `ERR_INVALID_REQUEST`. Every required field must be present, every enum-valued field must hold a declared member"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        missing_field = api.create_market(
            {"region_code": "PNW", "guarantee_exposure_limit_cents": 1_000_000},
            build.risk,
        )
        undeclared_enum = api.create_artist(
            factories.artist_payload(tier="STADIUM"), build.buyer
        )

        validate_error(missing_field, E.ERR_INVALID_REQUEST)
        validate_error(undeclared_enum, E.ERR_INVALID_REQUEST)

    @pytest.mark.parametrize("getter, error_id", NOT_FOUND_PROBES)
    def test_each_of_the_eleven_not_found_ids_is_reachable(
        self, api, getter, error_id
    ):
        """From PRD §2.11: "Every path variable is resolved left to right, and the first unresolvable segment determines the error." — and "All eleven are HTTP 404."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        response = getattr(api, getter)(
            NON_EXISTENT_UUID, make_tour_accountant_headers()
        )

        validate_error(response, error_id)


class TestBookingAndNegotiationErrorsAreReachable:
    def test_err_stale_show_version_on_a_mismatched_offer_create(self, api, build):
        """From PRD §2.7: "If the supplied value does not equal the show's current `version`, the create is rejected with `ERR_STALE_SHOW_VERSION` (HTTP 412)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        stale = ctx["show"]["version"] + 1

        response = api.create_offer(
            factories.offer_payload(ctx["show"]["id"], stale, guarantee_cents=100_000),
            build.buyer,
        )

        validate_error(response, E.ERR_STALE_SHOW_VERSION)

    def test_err_invalid_show_window_when_load_in_follows_the_event(self, api, build):
        """From PRD §3.1: "First, window coherence: `load_in_at` must be strictly earlier than `event_at`, `event_at` must be strictly earlier than `load_out_at`, and `announce_at` must be no later than `event_at`; otherwise `ERR_INVALID_SHOW_WINDOW`."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.world()

        response = api.create_show(
            factories.show_payload(
                ctx["artist"]["id"],
                ctx["venue"]["id"],
                event_at="2026-10-10T02:00:00.000Z",
                load_in_at="2026-10-10T06:00:00.000Z",
                load_out_at="2026-10-10T08:00:00.000Z",
                announce_at="2026-08-15T15:00:00.000Z",
                rental_fee_cents=RENTAL_FEE_CENTS,
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_INVALID_SHOW_WINDOW)

    def test_err_event_date_in_past_for_a_coherent_but_expired_window(self, api, build):
        """From PRD §3.1: "Second, `event_at` must be strictly after the current logical clock — booking into the past yields `ERR_EVENT_DATE_IN_PAST`."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.world()

        response = api.create_show(
            factories.show_payload(
                ctx["artist"]["id"],
                ctx["venue"]["id"],
                event_at="2026-07-02T02:00:00.000Z",
                load_in_at="2026-07-01T14:00:00.000Z",
                load_out_at="2026-07-02T08:00:00.000Z",
                announce_at="2026-06-01T15:00:00.000Z",
                rental_fee_cents=RENTAL_FEE_CENTS,
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_EVENT_DATE_IN_PAST)

    def test_err_venue_window_conflict_for_an_overlapping_occupancy(self, api, build):
        """From PRD §3.1: "Third, venue occupancy: the new show's half-open interval from `load_in_at` up to but not including `load_out_at` must not overlap the interval of any other show at the same venue whose `show_status` is anything other than `CANCELLED` or `RESCHEDULED`; an overlap yields `ERR_VENUE_WINDOW_CONFLICT`."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        second_act = build.artist(name="Support Act", tier="CLUB", withholding_pct=0)

        response = api.create_show(
            factories.show_payload(
                second_act["id"],
                ctx["venue"]["id"],
                event_at="2026-10-10T04:00:00.000Z",
                load_in_at="2026-10-09T20:00:00.000Z",
                load_out_at="2026-10-10T10:00:00.000Z",
                announce_at="2026-08-15T15:00:00.000Z",
                rental_fee_cents=RENTAL_FEE_CENTS,
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_VENUE_WINDOW_CONFLICT)

    def test_err_artist_routing_conflict_inside_the_thirty_six_hour_buffer(
        self, api, build
    ):
        """From PRD §3.3: "the absolute difference between that show's `event_at` and this show's `event_at` must be at least 36 hours — a day and a half of rest and travel. A gap of exactly 36 hours is permitted; anything shorter yields `ERR_ARTIST_ROUTING_CONFLICT` (HTTP 409)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        other_room = build.venue(
            ctx["market"]["id"], name="The Second Room", gross_capacity=500
        )
        next_night = build.show(
            ctx["artist"]["id"],
            other_room["id"],
            event_at="2026-10-11T02:00:00.000Z",
            load_in_at="2026-10-10T14:00:00.000Z",
            load_out_at="2026-10-11T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            rental_fee_cents=RENTAL_FEE_CENTS,
        )
        offer = build.submitted_offer(next_night["id"], guarantee_cents=100_000)

        response = api.accept_offer(
            offer["id"], build.artist_rep(ctx["artist"]["id"])
        )

        validate_error(response, E.ERR_ARTIST_ROUTING_CONFLICT)
        assert build.read_show(next_night["id"])["show_status"] == "PLANNED"

    def test_err_deal_terms_incoherent_when_the_deposit_exceeds_the_guarantee(
        self, api, build
    ):
        """From PRD §3.2: "In every structure `deposit_cents` may not exceed `guarantee_cents`, and `expense_cap_cents`, when supplied, must be greater than 0. Any of these violations yields `ERR_DEAL_TERMS_INCOHERENT` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})

        response = api.create_offer(
            factories.offer_payload(
                ctx["show"]["id"],
                ctx["show"]["version"],
                guarantee_cents=100_000,
                deposit_cents=200_000,
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_DEAL_TERMS_INCOHERENT)

    def test_err_negotiation_rounds_exhausted_on_the_fourth_round(self, api, build):
        """From PRD §3.2: "Negotiation is capped at three rounds: neither a counter nor a re-submission may proceed once `round_index` has reached 3, and an attempt to go a fourth round is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        rep = build.artist_rep(ctx["artist"]["id"])
        offer = build.submitted_offer(ctx["show"]["id"], guarantee_cents=100_000)
        get_success_data(
            api.counter_offer(
                offer["id"],
                rep,
                counter_guarantee_cents=120_000,
                counter_note="the act needs more to carry the crew",
            )
        )
        get_success_data(
            api.submit_offer(offer["id"], build.buyer, guarantee_cents=110_000)
        )
        get_success_data(
            api.counter_offer(
                offer["id"],
                rep,
                counter_guarantee_cents=130_000,
                counter_note="still short of the routing floor",
            )
        )
        third_round = get_success_data(
            api.submit_offer(offer["id"], build.buyer, guarantee_cents=125_000)
        )
        assert third_round["round_index"] == 3

        response = api.counter_offer(
            offer["id"],
            rep,
            counter_guarantee_cents=140_000,
            counter_note="one last ask",
        )

        validate_error(response, E.ERR_NEGOTIATION_ROUNDS_EXHAUSTED)

    def test_err_offer_expired_at_exactly_the_deadline(self, api, build):
        """From PRD §3.2: "a counter or an acceptance attempted at or after the offer's `expires_at` is rejected with `ERR_OFFER_EXPIRED` (HTTP 409); the current logical clock must be strictly earlier than `expires_at`"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        offer = build.submitted_offer(ctx["show"]["id"], guarantee_cents=100_000)
        build.set_clock(offer["expires_at"])

        response = api.accept_offer(
            offer["id"], build.artist_rep(ctx["artist"]["id"])
        )

        validate_error(response, E.ERR_OFFER_EXPIRED)

    def test_err_announce_date_not_reached_before_the_announce_instant(
        self, api, build
    ):
        """From PRD §3.4: "First, the current logical clock must have reached the show's `announce_at`; an earlier attempt yields `ERR_ANNOUNCE_DATE_NOT_REACHED` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={
                "rental_fee_cents": RENTAL_FEE_CENTS,
                "announce_at": "2026-09-15T15:00:00.000Z",
            },
        )
        build.tier(ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=100)

        response = api.put_show_on_sale(ctx["show"]["id"], build.buyer)

        validate_error(response, E.ERR_ANNOUNCE_DATE_NOT_REACHED)

    def test_err_no_ticket_tiers_when_the_house_has_no_inventory(self, api, build):
        """From PRD §3.4: "Second, the show must have at least one ticket tier; an empty tier set yields `ERR_NO_TICKET_TIERS` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        build.set_clock("2026-08-15T15:00:00.000Z")

        response = api.put_show_on_sale(ctx["show"]["id"], build.buyer)

        validate_error(response, E.ERR_NO_TICKET_TIERS)

    def test_err_venue_capacity_exceeded_by_one_seat(self, api, build):
        """From PRD §3.4: "the sum of `allocation_qty` across the show's tiers, counting the tier being created, may not exceed the venue's `gross_capacity`, or the create is rejected with `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(
            gross_capacity=100, show={"rental_fee_cents": RENTAL_FEE_CENTS}
        )

        response = api.create_ticket_tier(
            factories.ticket_tier_payload(
                ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=101
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_VENUE_CAPACITY_EXCEEDED)

    def test_err_duplicate_tier_name_within_one_show(self, api, build):
        """From PRD §3.4: "`tier_name` must be unique among that show's tiers, or the create is rejected with `ERR_DUPLICATE_TIER_NAME` (HTTP 409)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(
            gross_capacity=500, show={"rental_fee_cents": RENTAL_FEE_CENTS}
        )
        build.tier(ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=100)

        response = api.create_ticket_tier(
            factories.ticket_tier_payload(
                ctx["show"]["id"], tier_name="GA", price_cents=6_000, allocation_qty=50
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_DUPLICATE_TIER_NAME)

    def test_err_insufficient_tier_inventory_when_the_block_exceeds_availability(
        self, api, build
    ):
        """From PRD §3.4: "`qty` must not exceed the tier's `available_qty`, or the request is rejected with `ERR_INSUFFICIENT_TIER_INVENTORY` (HTTP 422)"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.on_sale_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 10}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )

        response = api.record_sales(ctx["tiers"][0]["id"], build.buyer, qty=11)

        validate_error(response, E.ERR_INSUFFICIENT_TIER_INVENTORY)

    def test_err_comp_allowance_exceeded_past_three_percent_of_the_house(
        self, api, build
    ):
        """From PRD §3.5: "The show's comp allowance in whole tickets is 3 percent of that total allocation, rounded half up. The show's current `comp_tickets_issued` plus the requested quantity must not exceed that allowance, or the request is rejected with `ERR_COMP_ALLOWANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.on_sale_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )

        response = api.create_ticket_hold(
            factories.ticket_hold_payload(
                ctx["tiers"][0]["id"], kind="COMP", qty=4, holder="the label's radio guests"
            ),
            build.buyer,
        )

        validate_error(response, E.ERR_COMP_ALLOWANCE_EXCEEDED)

    def test_err_invalid_state_when_resuming_a_show_that_never_sold(self, api, build):
        """From PRD §2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})

        response = api.resume_sales(ctx["show"]["id"], build.buyer)

        validate_error(response, E.ERR_INVALID_STATE)

    def test_err_already_terminal_when_withdrawing_an_accepted_offer(self, api, build):
        """From PRD §2.9: "Terminality — `ERR_ALREADY_TERMINAL` when the target already sits in one of its own terminal states."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )

        response = api.withdraw_offer(
            ctx["offer"]["id"], "the buyer changed his mind", build.buyer
        )

        validate_error(response, E.ERR_ALREADY_TERMINAL)

    def test_err_market_exposure_exceeded_by_a_single_cent(self, api, build):
        """From PRD §3.3: "the market's current `committed_guarantee_cents` plus this offer's `guarantee_cents` must not exceed the applicable ceiling, and equality with the ceiling passes" — "Exceeding it yields `ERR_MARKET_EXPOSURE_EXCEEDED` (HTTP 402)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(
            guarantee_exposure_limit_cents=1_000_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        offer = build.submitted_offer(ctx["show"]["id"], guarantee_cents=1_000_001)

        response = api.accept_offer(
            offer["id"], build.artist_rep(ctx["artist"]["id"])
        )

        validate_error(response, E.ERR_MARKET_EXPOSURE_EXCEEDED)
        assert build.read_market(ctx["market"]["id"])["committed_guarantee_cents"] == 0

    def test_err_market_posture_frozen_after_the_ceiling_is_fully_committed(
        self, api, build
    ):
        """From PRD §3.3: "if the market's `risk_posture` is `FROZEN`, the acceptance is rejected with `ERR_MARKET_POSTURE_FROZEN` (HTTP 409)"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_exposure_limit_cents=1_000_000,
            guarantee_cents=1_000_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        assert build.read_market(ctx["market"]["id"])["risk_posture"] == "FROZEN"
        second_act = build.artist(name="December Act", tier="CLUB", withholding_pct=0)
        december = build.show(
            second_act["id"],
            ctx["venue"]["id"],
            event_at="2026-12-09T02:00:00.000Z",
            load_in_at="2026-12-08T14:00:00.000Z",
            load_out_at="2026-12-09T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            rental_fee_cents=RENTAL_FEE_CENTS,
        )
        offer = build.submitted_offer(december["id"], guarantee_cents=1_000)

        response = api.accept_offer(offer["id"], build.artist_rep(second_act["id"]))

        validate_error(response, E.ERR_MARKET_POSTURE_FROZEN)

    def test_err_exposure_override_invalid_above_twice_the_market_limit(
        self, api, build
    ):
        """From PRD §3.3: "The override may not exceed twice the market's own `guarantee_exposure_limit_cents`, and the justification may not be empty; either violation yields `ERR_EXPOSURE_OVERRIDE_INVALID` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.planned_show(
            guarantee_exposure_limit_cents=1_000_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )

        response = api.grant_exposure_override(
            ctx["show"]["id"],
            build.risk,
            exposure_override_limit_cents=3_000_000,
            exposure_override_justification="a marquee routing worth the breach",
        )

        validate_error(response, E.ERR_EXPOSURE_OVERRIDE_INVALID)
        assert build.read_show(ctx["show"]["id"])["exposure_override_limit_cents"] is None


class TestLedgerSettlementAndCancellationErrorsAreReachable:
    def test_err_budget_line_show_mismatch_across_two_dates(self, api, build):
        """From PRD §3.6: "the `BudgetLine` named by `budget_line_id` must belong to the same show as the `show_id` on the invoice, or the create is rejected with `ERR_BUDGET_LINE_SHOW_MISMATCH` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.budget_line(ctx["show"]["id"], budgeted_cents=60_000)
        second_act = build.artist(name="December Act", tier="CLUB", withholding_pct=0)
        other_date = build.show(
            second_act["id"],
            ctx["venue"]["id"],
            event_at="2026-12-09T02:00:00.000Z",
            load_in_at="2026-12-08T14:00:00.000Z",
            load_out_at="2026-12-09T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            rental_fee_cents=RENTAL_FEE_CENTS,
        )

        response = api.create_vendor_invoice(
            factories.vendor_invoice_payload(
                other_date["id"], line["id"], amount_cents=60_000
            ),
            build.accountant,
        )

        validate_error(response, E.ERR_BUDGET_LINE_SHOW_MISMATCH)

    def test_err_variance_cap_invalid_on_both_incoherent_cap_shapes(self, api, build):
        """From PRD §3.6: "on `APPROVE`, `approved_cap_cents` must be present and at least the line's `budgeted_cents`; on `REJECT`, `approved_cap_cents` must be absent; either violation yields `ERR_VARIANCE_CAP_INVALID` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.confirmed_show(
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.line_with_actual(
            ctx["show"]["id"], budgeted_cents=200_000, actual_cents=260_000
        )

        rejection_with_a_cap = api.decide_variance(
            line["id"],
            build.risk,
            decision="REJECT",
            approved_cap_cents=260_000,
            variance_justification="the overage was never authorised",
        )
        approval_below_budget = api.decide_variance(
            line["id"],
            build.risk,
            decision="APPROVE",
            approved_cap_cents=150_000,
            variance_justification="only part of the overage is defensible",
        )

        validate_error(rejection_with_a_cap, E.ERR_VARIANCE_CAP_INVALID)
        validate_error(approval_below_budget, E.ERR_VARIANCE_CAP_INVALID)
        assert build.read_budget_line(line["id"])["variance_status"] == "PENDING_APPROVAL"

    def test_err_show_not_yet_occurred_before_the_event_instant(self, api, build):
        """From PRD §3.7: "the current logical clock must have reached the show's `event_at` — an earlier attempt yields `ERR_SHOW_NOT_YET_OCCURRED` (HTTP 422)"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.on_sale_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )

        response = api.perform_show(ctx["show"]["id"], build.accountant)

        validate_error(response, E.ERR_SHOW_NOT_YET_OCCURRED)

    def test_err_settlement_already_open_on_a_second_book(self, api, build):
        """From PRD §3.7: "A show may have at most one settlement that is not yet `PAID`; attempting to open a second while one is outstanding yields `ERR_SETTLEMENT_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.performed_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        build.settlement(ctx["show"]["id"])

        response = api.create_settlement(
            factories.settlement_payload(ctx["show"]["id"]), build.accountant
        )

        validate_error(response, E.ERR_SETTLEMENT_ALREADY_OPEN)

    def test_err_unresolved_invoices_while_paper_is_still_submitted(self, api, build):
        """From PRD §3.7: "no vendor invoice on the show may still be `SUBMITTED`, `VERIFIED` or `DISPUTED` — every invoice must have reached `APPROVED` or `REJECTED` before the books close — or the call is rejected with `ERR_UNRESOLVED_INVOICES` (HTTP 409)"

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.performed_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.budget_line(ctx["show"]["id"], budgeted_cents=60_000)
        invoice = get_success_data(
            api.create_vendor_invoice(
                factories.vendor_invoice_payload(
                    ctx["show"]["id"], line["id"], amount_cents=60_000
                ),
                build.accountant,
            )
        )
        book = build.settlement(ctx["show"]["id"])

        response = api.calculate_settlement(book["id"], build.accountant)

        validate_error(response, E.ERR_UNRESOLVED_INVOICES)
        assert build.read_invoice(invoice["id"])["status"] == "SUBMITTED"

    def test_err_unresolved_variance_while_a_line_is_pending_approval(self, api, build):
        """From PRD §3.7: "no budget line on the show may be `PENDING_APPROVAL`, or the call is rejected with `ERR_UNRESOLVED_VARIANCE` (HTTP 409)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.performed_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        line = build.line_with_actual(
            ctx["show"]["id"], budgeted_cents=200_000, actual_cents=260_000
        )
        assert line["variance_status"] == "PENDING_APPROVAL"
        book = build.settlement(ctx["show"]["id"])

        response = api.calculate_settlement(book["id"], build.accountant)

        validate_error(response, E.ERR_UNRESOLVED_VARIANCE)

    def test_err_cash_payment_limit_above_ten_thousand_dollars(self, api, build):
        """From PRD §3.8: "Cash is capped: when `payment_method` is `CASH`, the settlement's `payment_due_cents` may not exceed 1,000,000 cents — ten thousand dollars — or the payment is rejected with `ERR_CASH_PAYMENT_LIMIT` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.performed_show(
            gross_capacity=500,
            guarantee_cents=2_000_000,
            deposit_cents=0,
            expense_cap_cents=2_000_000,
            withholding_pct=0,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        build.budget_line(ctx["show"]["id"], category="PRODUCTION", budgeted_cents=50_000)
        signed = build.signed_settlement(ctx["show"]["id"], ctx["artist"]["id"])
        assert signed["payment_due_cents"] == 2_000_000

        response = api.pay_settlement(
            signed["id"],
            build.accountant_two,
            payment_method="CASH",
            payment_reference="counted out of the box office drawer",
        )

        validate_error(response, E.ERR_CASH_PAYMENT_LIMIT, expected_status=422)
        assert build.read_settlement(signed["id"])["status"] == "ARTIST_SIGNED"

    def test_err_replacement_show_invalid_without_a_back_reference(self, api, build):
        """From PRD §3.9: "the show it names must carry a `rescheduled_from_show_id` equal to the event's own `show_id`, must itself be in `show_status` `PLANNED`, and must not be the original show; any violation yields `ERR_REPLACEMENT_SHOW_INVALID` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.on_sale_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        event = build.cancellation_event(
            ctx["show"]["id"],
            kind="POSTPONED",
            reason="the act lost its voice and the date moves to December",
        )
        unrelated = build.show(
            ctx["artist"]["id"],
            ctx["venue"]["id"],
            event_at="2026-12-09T02:00:00.000Z",
            load_in_at="2026-12-08T14:00:00.000Z",
            load_out_at="2026-12-09T08:00:00.000Z",
            announce_at="2026-08-15T15:00:00.000Z",
            rental_fee_cents=RENTAL_FEE_CENTS,
        )
        assert unrelated["rescheduled_from_show_id"] is None

        response = api.reschedule_cancellation_event(
            event["id"], build.buyer, replacement_show_id=unrelated["id"]
        )

        validate_error(response, E.ERR_REPLACEMENT_SHOW_INVALID)
        assert build.read_event(event["id"])["status"] == "OPENED"

    def test_err_claim_window_closed_more_than_thirty_days_after_the_event(
        self, api, build
    ):
        """From PRD §3.9: "the current logical clock must be within 30 days of the event's `occurred_at`, inclusive of the final instant, or the filing is rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422)."

        Design: Corner/errors/every_catalog_error_id_is_reachable_and_none_is_decorative
        """
        ctx = build.on_sale_show(
            gross_capacity=500,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        build.sell(ctx["tiers"][0]["id"], 20)
        event = build.refunds_processed_event(ctx["show"]["id"], kind="CANCELLED")
        build.set_clock("2026-09-16T15:00:00.000Z")

        response = api.file_claim(
            event["id"],
            build.risk,
            claim_amount_cents=1_000_000,
            claim_documentation_ref="PKT-2026-0918",
        )

        validate_error(response, E.ERR_CLAIM_WINDOW_CLOSED)
        assert build.read_event(event["id"])["status"] == "REFUNDS_PROCESSED"
