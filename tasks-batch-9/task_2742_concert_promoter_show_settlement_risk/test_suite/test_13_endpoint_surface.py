"""Endpoint-surface behaviour: create-plus-action writes, guarded actions,
cross-reference links and state-conditional actions.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_common_fields,
    assert_list_response,
    assert_no_pagination_meta,
    assert_tier_inventory_conserved,
    assert_timestamp_equals,
    assert_unchanged,
    assert_version_bumped_by,
    expected_adjusted_gross,
    factories,
    get_success_data,
    make_risk_officer_headers,
    make_talent_buyer_headers,
    make_tour_accountant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers.constants import DEFAULT_CLOCK

# A RENTAL show must carry a positive rental fee, so every show built here
# names one explicitly.
RENTAL_FEE_CENTS = 50_000


class TestWriteSurfaceIsCreatePlusActionOnly:
    def test_creating_a_venue_echoes_its_stored_fields_at_version_one(self, api, build):
        """From PRD §2.4: "`version` starts at 1 when the resource is created and increases by exactly 1 on each mutation of that resource", and §2.4 also states "Every persisted resource carries an `id` that is a server-minted UUID."

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        market = build.market(
            name="Crud Market",
            region_code="CR",
            guarantee_exposure_limit_cents=5_000_000,
        )
        response = api.create_venue(
            factories.venue_payload(
                market["id"],
                name="Crud Amphitheatre",
                gross_capacity=4_200,
                facility_fee_cents_per_ticket=275,
                ticket_tax_pct=6.50,
            ),
            make_talent_buyer_headers(),
        )
        venue = validate_success(response, 201)

        assert_common_fields(venue, expected_version=1)
        assert venue["market_id"] == market["id"]
        assert venue["name"] == "Crud Amphitheatre"
        assert venue["gross_capacity"] == 4_200
        assert venue["facility_fee_cents_per_ticket"] == 275
        assert float(venue["ticket_tax_pct"]) == pytest.approx(6.50, abs=0.01)
        assert_timestamp_equals(venue["created_at"], DEFAULT_CLOCK)
        assert_timestamp_equals(venue["updated_at"], DEFAULT_CLOCK)
        assert_no_pagination_meta(response.json())

    def test_reading_a_venue_never_bumps_its_version_or_updated_at(self, api, build):
        """From PRD: "Reads never trigger recomputation of persisted values, with one deliberate exception noted in §3.3." (PRD §2.10)

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        market = build.market(guarantee_exposure_limit_cents=5_000_000)
        created = build.venue(
            market["id"],
            name="Crud Amphitheatre",
            gross_capacity=4_200,
            facility_fee_cents_per_ticket=275,
            ticket_tax_pct=6.50,
        )

        first = validate_success(api.get_venue(created["id"], make_tour_accountant_headers()))
        second = validate_success(api.get_venue(created["id"], make_tour_accountant_headers()))

        assert first["name"] == "Crud Amphitheatre"
        assert first["gross_capacity"] == 4_200
        assert first["facility_fee_cents_per_ticket"] == 275
        assert first["market_id"] == market["id"]
        assert first["version"] == 1
        assert_timestamp_equals(first["updated_at"], created["updated_at"])
        assert_unchanged(second, first, ["version", "updated_at", "created_at"])

    def test_posting_an_identical_venue_body_twice_creates_two_rows(self, api, build):
        """From PRD: "Every persisted resource carries an `id` that is a server-minted UUID. Identifiers carry no type prefix and are never supplied by the client" (PRD §2.4)

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        market = build.market(guarantee_exposure_limit_cents=5_000_000)
        payload = factories.venue_payload(
            market["id"],
            name="Crud Amphitheatre",
            gross_capacity=4_200,
            facility_fee_cents_per_ticket=275,
            ticket_tax_pct=6.50,
        )
        headers = make_talent_buyer_headers()

        first = validate_success(api.create_venue(payload, headers), 201)
        second = validate_success(api.create_venue(payload, headers), 201)

        assert second["id"] != first["id"]
        assert first["version"] == 1
        assert second["version"] == 1

    def test_the_venue_list_pages_through_two_rows_one_at_a_time(self, api, build):
        """From PRD: "`total_count` (the number of records matching the filters before pagination), and `has_more` (true when records remain beyond the current page)" (PRD §2.3)

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        market = build.market(guarantee_exposure_limit_cents=5_000_000)
        first = build.venue(market["id"], name="Crud Amphitheatre", gross_capacity=4_200)
        second = build.venue(market["id"], name="Crud Amphitheatre", gross_capacity=4_200)

        page_one_response = api.list_venues(
            make_talent_buyer_headers(), market_id=market["id"], limit=1, offset=0
        )
        assert_list_response(page_one_response.json())
        page_one, meta_one = validate_paginated(page_one_response)
        page_two, meta_two = validate_paginated(
            api.list_venues(
                make_talent_buyer_headers(), market_id=market["id"], limit=1, offset=1
            )
        )

        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0
        assert len(page_one) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 1
        assert len(page_two) == 1
        assert {page_one[0]["id"], page_two[0]["id"]} == {first["id"], second["id"]}

    def test_the_artist_list_narrows_by_tier(self, api, build):
        """From PRD: "Artists can be listed and narrowed by `tier`." (PRD §3.1)

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        theatre_act = build.artist(
            name="Crud Act Theatre",
            agency="Crd Talent",
            tier="THEATER",
            historical_sellthrough_pct=64.00,
            withholding_pct=0,
        )
        arena_act = build.artist(
            name="Crud Act Arena",
            agency="Crd Talent",
            tier="ARENA",
            historical_sellthrough_pct=82.00,
            withholding_pct=15.00,
        )

        rows, meta = validate_paginated(
            api.list_artists(make_tour_accountant_headers(), tier="THEATER")
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [theatre_act["id"]]
        read_arena = validate_success(api.get_artist(arena_act["id"], make_tour_accountant_headers()))
        assert read_arena["tier"] == "ARENA"
        assert float(read_arena["withholding_pct"]) == pytest.approx(15.00, abs=0.01)

    def test_reading_an_unknown_venue_id_returns_the_venue_not_found_error(self, api):
        """From PRD: "Every path variable is resolved left to right, and the first unresolvable segment determines the error." (PRD §2.11, which maps `venue_id` to `ERR_VENUE_NOT_FOUND` and states "All eleven are HTTP 404.")

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        response = api.get_venue(NON_EXISTENT_UUID, make_talent_buyer_headers())

        validate_error(response, E.ERR_VENUE_NOT_FOUND)

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    @pytest.mark.parametrize(
        "resource",
        ["market", "artist", "venue", "show", "offer"],
    )
    def test_no_update_or_delete_verb_exists_on_any_resource_path(
        self, api, build, method, resource
    ):
        """From PRD: "The table below is the complete surface of the API." (PRD §4, whose sixty-one rows declare only GET and POST)

        Design: Corner/endpoints/the_write_surface_is_create_plus_action_only_with_no_update_or_delete_verb
        """
        ctx = build.planned_show(
            guarantee_exposure_limit_cents=5_000_000,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        offer = build.offer(ctx["show"]["id"], guarantee_cents=100_000)
        paths = {
            "market": f"/markets/{ctx['market']['id']}",
            "artist": f"/artists/{ctx['artist']['id']}",
            "venue": f"/venues/{ctx['venue']['id']}",
            "show": f"/shows/{ctx['show']['id']}",
            "offer": f"/offers/{offer['id']}",
        }

        response = api.raw(method, paths[resource], make_talent_buyer_headers(), payload={})

        assert response.status_code in (404, 405), (
            f"{method} {paths[resource]} answered {response.status_code}; "
            "the declared surface carries no update or delete verb"
        )


def _performed_rental_show(api, build):
    """A 500-seat rental date: 50 seats sold at 5000, one 50000 production line."""
    ctx = build.on_sale_show(
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        withholding_pct=0,
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
        show={"rental_fee_cents": RENTAL_FEE_CENTS},
    )
    build.sell(ctx["tiers"][0]["id"], 50)
    ctx["line"] = build.line_with_actual(
        ctx["show"]["id"],
        budgeted_cents=50_000,
        actual_cents=50_000,
        category="PRODUCTION",
        is_artist_deductible=True,
    )
    build.set_clock("2026-10-10T06:00:00.000Z")
    get_success_data(api.perform_show(ctx["show"]["id"], build.accountant))
    ctx["show"] = build.read_show(ctx["show"]["id"])
    return ctx


def _confirmed_show_plus_a_second_planned_show(build):
    """One CONFIRMED date carrying a 100000 guarantee, one PLANNED date with open paper."""
    ctx = build.confirmed_show(
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        withholding_pct=0,
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        show={"rental_fee_cents": RENTAL_FEE_CENTS},
    )
    ctx["second_artist"] = build.artist(
        name="Act Two", agency="Act Talent", tier="CLUB", withholding_pct=0
    )
    ctx["second_show"] = build.show(
        ctx["second_artist"]["id"],
        ctx["venue"]["id"],
        event_at="2026-12-09T02:00:00.000Z",
        load_in_at="2026-12-08T14:00:00.000Z",
        load_out_at="2026-12-09T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    ctx["second_offer"] = build.submitted_offer(
        ctx["second_show"]["id"], guarantee_cents=200_000
    )
    return ctx


class TestActionEndpointsMoveTheRowOrRefuse:
    def test_withdraw_moves_a_submitted_offer_to_withdrawn_and_bumps_its_version(
        self, api, build
    ):
        """From PRD §3.2: "The promoter may withdraw it from `DRAFT`, `SUBMITTED` or `COUNTERED`, supplying a `reason`, which moves it to `WITHDRAWN`."

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _confirmed_show_plus_a_second_planned_show(build)
        submitted = ctx["second_offer"]

        withdrawn = validate_success(
            api.withdraw_offer(
                submitted["id"],
                "Artist took a competing offer in the market",
                build.buyer,
            )
        )

        assert submitted["status"] == "SUBMITTED"
        assert withdrawn["status"] == "WITHDRAWN"
        assert_version_bumped_by(withdrawn, submitted, 1)

    def test_withdrawing_an_unaccepted_offer_touches_no_exposure(self, api, build):
        """From PRD §3.3: "`PLANNED` shows contribute nothing, because no guarantee is committed until an offer is accepted"

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _confirmed_show_plus_a_second_planned_show(build)
        before = build.read_market(ctx["market"]["id"])

        get_success_data(
            api.withdraw_offer(
                ctx["second_offer"]["id"],
                "Artist took a competing offer in the market",
                build.buyer,
            )
        )

        after = build.read_market(ctx["market"]["id"])
        assert before["committed_guarantee_cents"] == 100_000
        assert after["committed_guarantee_cents"] == 100_000
        assert after["risk_posture"] == "OPEN"
        planned = build.read_show(ctx["second_show"]["id"])
        assert planned["show_status"] == "PLANNED"
        assert planned["committed_guarantee_cents"] == 0

    def test_an_accepted_offer_can_no_longer_be_withdrawn(self, api, build):
        """From PRD §2.9: "Terminality — `ERR_ALREADY_TERMINAL` when the target already sits in one of its own terminal states." PRD §3.2 names the offer's terminal set: "`ACCEPTED`, `WITHDRAWN`, `SUPERSEDED` and `EXPIRED` are all terminal"

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _confirmed_show_plus_a_second_planned_show(build)
        accepted = ctx["offer"]

        response = api.withdraw_offer(accepted["id"], "Buyer regret", build.buyer)

        validate_error(response, E.ERR_ALREADY_TERMINAL)
        assert build.read_offer(accepted["id"])["status"] == "ACCEPTED"

    def test_calculating_the_settlement_freezes_the_rental_waterfall(self, api, build):
        """From PRD §3.7: "Under `RENTAL`, `venue_expense_reimbursement_cents` is 0 — the promoter bears every expense — so `promoter_borne_expense_cents` equals `total_settlement_expense_cents`, and `venue_share_cents` is the show's flat `rental_fee_cents`, paid regardless of outcome."

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)

        book = build.calculated_settlement(ctx["show"]["id"])

        waterfall = expected_adjusted_gross(250_000, 0, 50, 0)
        assert book["status"] == "CALCULATED"
        assert book["adjusted_gross_cents"] == waterfall["adjusted_gross_cents"] == 243_750
        assert book["allowed_expense_cents"] == 50_000
        assert book["payment_due_cents"] == 100_000
        assert book["promoter_borne_expense_cents"] == 50_000
        assert book["venue_share_cents"] == RENTAL_FEE_CENTS
        assert book["promoter_net_cents"] == 243_750 - 100_000 - 50_000 - RENTAL_FEE_CENTS

    def test_the_calculating_accountant_may_not_reopen_the_settlement(self, api, build):
        """From PRD §2.8: "Reopening a settlement requires an `X-User-ID` different from the settlement's `calculated_by_user_id`."

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)
        book = build.calculated_settlement(ctx["show"]["id"])

        response = api.reopen_settlement(
            book["id"],
            make_risk_officer_headers(book["calculated_by_user_id"]),
            reopen_reason="Recheck the production ledger",
        )

        validate_error(response, E.ERR_SEGREGATION_OF_DUTIES)
        unchanged = build.read_settlement(book["id"])
        assert unchanged["status"] == "CALCULATED"
        assert unchanged["reopen_count"] == 0

    def test_reopen_from_calculated_moves_the_row_and_counts_one(self, api, build):
        """From PRD §3.8: "A `RiskOfficer` may reopen a settlement that is `CALCULATED` or `ARTIST_SIGNED`, moving it to `REOPENED` with a required `reopen_reason`."

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)
        book = build.calculated_settlement(ctx["show"]["id"])

        reopened = validate_success(
            api.reopen_settlement(
                book["id"], build.risk, reopen_reason="Recheck the production ledger"
            )
        )

        assert book["reopen_count"] == 0
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 1
        assert reopened["reopen_reason"] == "Recheck the production ledger"

    def test_reopening_a_reopened_settlement_is_refused_and_the_count_holds(
        self, api, build
    ):
        """From PRD §2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition"

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)
        book = build.calculated_settlement(ctx["show"]["id"])
        get_success_data(
            api.reopen_settlement(
                book["id"], build.risk, reopen_reason="Recheck the production ledger"
            )
        )

        response = api.reopen_settlement(book["id"], build.risk, reopen_reason="Again")

        validate_error(response, E.ERR_INVALID_STATE)
        assert build.read_settlement(book["id"])["reopen_count"] == 1

    def test_reopen_from_artist_signed_voids_the_signature_and_accumulates_the_count(
        self, api, build
    ):
        """From PRD §3.8: "Reopening increases `reopen_count` by 1, records the `reopen_reason`, and clears `signed_by_user_id` to null" — and "`reopen_count` is a running total and is never reset"

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)
        book = build.calculated_settlement(ctx["show"]["id"])
        get_success_data(
            api.reopen_settlement(
                book["id"], build.risk, reopen_reason="Recheck the production ledger"
            )
        )
        recalculated = get_success_data(
            api.calculate_settlement(book["id"], build.accountant)
        )
        signed = get_success_data(
            api.respond_to_settlement(
                book["id"], build.artist_rep(ctx["artist"]["id"]), response="SIGN"
            )
        )

        reopened = validate_success(
            api.reopen_settlement(
                book["id"],
                build.risk,
                reopen_reason="Artist disputes the backline charge after signing",
            )
        )

        assert recalculated["status"] == "CALCULATED"
        assert signed["status"] == "ARTIST_SIGNED"
        assert signed["signed_by_user_id"] == ctx["artist"]["id"]
        assert reopened["status"] == "REOPENED"
        assert reopened["reopen_count"] == 2
        assert reopened["signed_by_user_id"] is None

    def test_neither_reopen_moves_the_show_out_of_performed(self, api, build):
        """From PRD §3.8: "**Hop one:** the show's `show_status` moves `PERFORMED → SETTLED`." — only the payment hop moves it, and no payment was made here.

        Design: Corner/endpoints/action_endpoints_move_the_row_and_refuse_when_their_precondition_fails
        """
        ctx = _performed_rental_show(api, build)
        book = build.calculated_settlement(ctx["show"]["id"])
        get_success_data(
            api.reopen_settlement(
                book["id"], build.risk, reopen_reason="Recheck the production ledger"
            )
        )

        assert build.read_show(ctx["show"]["id"])["show_status"] == "PERFORMED"


def _postponed_show_and_its_replacement(api, build):
    """A 100-seat on-sale date with 50 paid tickets, postponed, plus a PLANNED replacement."""
    ctx = build.on_sale_show(
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        withholding_pct=0,
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
        show={"rental_fee_cents": RENTAL_FEE_CENTS},
    )
    build.sell(ctx["tiers"][0]["id"], 50)
    ctx["event"] = build.cancellation_event(
        ctx["show"]["id"],
        kind="POSTPONED",
        reason="the act lost its voice and the date moves to December",
    )
    ctx["replacement"] = build.show(
        ctx["artist"]["id"],
        ctx["venue"]["id"],
        event_at="2026-12-09T02:00:00.000Z",
        load_in_at="2026-12-08T14:00:00.000Z",
        load_out_at="2026-12-09T08:00:00.000Z",
        announce_at="2026-08-15T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
        rescheduled_from_show_id=ctx["show"]["id"],
    )
    return ctx


class TestCrossReferenceLinksAreReadableFromEitherSide:
    def test_an_invoice_names_both_its_show_and_its_budget_line(self, api, build):
        """From PRD §3.6: "Invoices may be listed and narrowed by `show_id`, by `budget_line_id` and by `status`."

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = build.confirmed_show(
            guarantee_exposure_limit_cents=5_000_000,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            withholding_pct=0,
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        show_id = ctx["show"]["id"]
        staging = build.budget_line(show_id, category="PRODUCTION", budgeted_cents=60_000)
        catering = build.budget_line(show_id, category="HOSPITALITY", budgeted_cents=40_000)
        staging_invoice = build.approved_invoice(show_id, staging["id"], 60_000)
        catering_invoice = build.approved_invoice(show_id, catering["id"], 40_000)

        by_show, show_meta = validate_paginated(
            api.list_vendor_invoices(build.accountant, show_id=show_id)
        )
        by_line, line_meta = validate_paginated(
            api.list_vendor_invoices(build.accountant, budget_line_id=staging["id"])
        )

        assert staging_invoice["show_id"] == show_id
        assert staging_invoice["budget_line_id"] == staging["id"]
        assert show_meta["total_count"] == 2
        assert {row["id"] for row in by_show} == {
            staging_invoice["id"],
            catering_invoice["id"],
        }
        assert line_meta["total_count"] == 1
        assert by_line[0]["id"] == staging_invoice["id"]

    def test_a_postponement_opens_an_event_with_no_replacement_yet(self, api, build):
        """From PRD §3.9: "The event is created in status `OPENED` with `occurred_at` stamped from the current logical clock"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = build.on_sale_show(
            guarantee_exposure_limit_cents=5_000_000,
            gross_capacity=500,
            facility_fee_cents_per_ticket=0,
            ticket_tax_pct=0,
            withholding_pct=0,
            guarantee_cents=100_000,
            deposit_cents=0,
            expense_cap_cents=100_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 100}],
            show={"rental_fee_cents": RENTAL_FEE_CENTS},
        )
        build.sell(ctx["tiers"][0]["id"], 50)
        build.set_clock("2026-09-01T12:00:00.000Z")

        event = build.cancellation_event(
            ctx["show"]["id"],
            kind="POSTPONED",
            reason="the act lost its voice and the date moves to December",
        )

        assert_common_fields(event, expected_version=1)
        assert event["status"] == "OPENED"
        assert event["kind"] == "POSTPONED"
        assert event["show_id"] == ctx["show"]["id"]
        assert event["replacement_show_id"] is None
        assert_timestamp_equals(event["occurred_at"], "2026-09-01T12:00:00.000Z")

    def test_postponement_carries_the_face_value_refund_liability_onto_both_rows(
        self, api, build
    ):
        """From PRD §3.9: "The show's `refund_liability_cents` becomes its `gross_sold_cents` plus its `transferred_in_gross_cents`"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)

        original = build.read_show(ctx["show"]["id"])
        assert original["show_status"] == "POSTPONED"
        assert original["sales_status"] == "CLOSED"
        assert original["gross_sold_cents"] == 250_000
        assert original["paid_tickets_sold"] == 50
        assert original["refund_liability_cents"] == 250_000
        assert ctx["event"]["refund_liability_cents"] == 250_000

    def test_postponement_releases_the_committed_guarantee(self, api, build):
        """From PRD §3.9: "the market's `committed_guarantee_cents` decreases by exactly the show's `committed_guarantee_cents`"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)

        market = build.read_market(ctx["market"]["id"])
        assert market["committed_guarantee_cents"] == 0
        assert market["risk_posture"] == "OPEN"

    def test_the_replacement_row_points_back_at_the_original_before_any_transfer(
        self, api, build
    ):
        """From PRD §3.9: "the show it names must carry a `rescheduled_from_show_id` equal to the event's own `show_id`, must itself be in `show_status` `PLANNED`, and must not be the original show"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)

        replacement = ctx["replacement"]
        assert replacement["rescheduled_from_show_id"] == ctx["show"]["id"]
        assert replacement["show_status"] == "PLANNED"
        assert replacement["transferred_in_gross_cents"] == 0
        assert replacement["transferred_in_paid_tickets"] == 0

    def test_rescheduling_moves_the_money_onto_the_replacement_date(self, api, build):
        """From PRD §3.9: "the replacement show's `transferred_in_gross_cents` increases by the original's `gross_sold_cents` and its `transferred_in_paid_tickets` increases by the original's `paid_tickets_sold`"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)

        rescheduled = validate_success(
            api.reschedule_cancellation_event(
                ctx["event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement"]["id"],
            )
        )

        assert rescheduled["status"] == "RESCHEDULED"
        assert rescheduled["replacement_show_id"] == ctx["replacement"]["id"]
        assert_version_bumped_by(rescheduled, ctx["event"], 1)
        replacement = build.read_show(ctx["replacement"]["id"])
        assert replacement["transferred_in_gross_cents"] == 250_000
        assert replacement["transferred_in_paid_tickets"] == 50
        assert replacement["gross_sold_cents"] == 0
        assert replacement["paid_tickets_sold"] == 0
        assert replacement["show_status"] == "PLANNED"

    def test_rescheduling_clears_the_refund_liability_and_leaves_exposure_alone(
        self, api, build
    ):
        """From PRD §3.9: "Both the original show's `refund_liability_cents` and the event's `refund_liability_cents` are set to 0." — and "The market's `committed_guarantee_cents` is **unchanged** by this call"

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)
        before = build.read_market(ctx["market"]["id"])

        rescheduled = validate_success(
            api.reschedule_cancellation_event(
                ctx["event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement"]["id"],
            )
        )

        original = build.read_show(ctx["show"]["id"])
        assert original["show_status"] == "RESCHEDULED"
        assert original["refund_liability_cents"] == 0
        assert rescheduled["refund_liability_cents"] == 0
        after = build.read_market(ctx["market"]["id"])
        assert before["committed_guarantee_cents"] == 0
        assert after["committed_guarantee_cents"] == 0

    def test_the_link_is_queryable_from_the_show_side_and_the_event_side(
        self, api, build
    ):
        """From PRD §3.9: "Cancellation events may be listed and narrowed by `show_id`, by `replacement_show_id`, by `kind` and by `status`."

        Design: Corner/endpoints/cross_reference_links_require_both_rows_and_are_readable_from_either_side
        """
        ctx = _postponed_show_and_its_replacement(api, build)
        get_success_data(
            api.reschedule_cancellation_event(
                ctx["event"]["id"],
                build.buyer,
                replacement_show_id=ctx["replacement"]["id"],
            )
        )

        shows, show_meta = validate_paginated(
            api.list_shows(build.buyer, rescheduled_from_show_id=ctx["show"]["id"])
        )
        events, event_meta = validate_paginated(
            api.list_cancellation_events(
                build.buyer, replacement_show_id=ctx["replacement"]["id"]
            )
        )

        assert show_meta["total_count"] == 1
        assert shows[0]["id"] == ctx["replacement"]["id"]
        assert event_meta["total_count"] == 1
        assert events[0]["id"] == ctx["event"]["id"]
        assert events[0]["show_id"] == ctx["show"]["id"]


def _selling_show_with_two_holds(api, build):
    """A 300-seat tier on sale carrying a 5-seat artist hold and a 2-seat promoter hold."""
    ctx = build.on_sale_show(
        guarantee_exposure_limit_cents=5_000_000,
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
        withholding_pct=0,
        guarantee_cents=100_000,
        deposit_cents=0,
        expense_cap_cents=100_000,
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 300}],
        show={"rental_fee_cents": RENTAL_FEE_CENTS},
    )
    tier_id = ctx["tiers"][0]["id"]
    ctx["artist_hold"] = build.hold(
        tier_id, kind="ARTIST_HOLD", qty=5, holder="the act's own guest list"
    )
    ctx["promoter_hold"] = build.hold(
        tier_id, kind="PROMOTER_HOLD", qty=2, holder="the local radio partner"
    )
    return ctx


class TestSalesPauseAndCompConversionRequireTheNamedStates:
    def test_a_selling_show_cannot_be_resumed(self, api, build):
        """From PRD §3.4: "Resuming, available to a `TalentBuyer`, moves `sales_status` `PAUSED → SELLING` provided `show_status` is `ON_SALE`, and cascades every `PAUSED` tier back to `ON_SALE`." PRD §2.9 rules the refusal: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition"

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        assert ctx["show"]["sales_status"] == "SELLING"

        response = api.resume_sales(ctx["show"]["id"], build.buyer)

        validate_error(response, E.ERR_INVALID_STATE)
        assert build.read_show(ctx["show"]["id"])["sales_status"] == "SELLING"

    def test_pausing_moves_only_the_ticketing_dimension_and_cascades_the_tier(
        self, api, build
    ):
        """From PRD §3.4: "Pausing — available to a `TalentBuyer` or a `RiskOfficer`, and requiring a `reason` — moves `sales_status` `SELLING → PAUSED` and cascades every tier in `ON_SALE` to `PAUSED`, while leaving `show_status` completely untouched at `ON_SALE`."

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        before = build.read_show(ctx["show"]["id"])

        paused = validate_success(
            api.pause_sales(
                ctx["show"]["id"],
                "a severe weather advisory covers the metro area",
                build.risk,
            )
        )

        assert paused["sales_status"] == "PAUSED"
        assert paused["show_status"] == "ON_SALE"
        assert_version_bumped_by(paused, before, 1)
        assert build.read_tier(ctx["tiers"][0]["id"])["status"] == "PAUSED"

    def test_pausing_an_already_paused_show_is_refused(self, api, build):
        """From PRD §3.4: "Pausing — available to a `TalentBuyer` or a `RiskOfficer`, and requiring a `reason` — moves `sales_status` `SELLING → PAUSED`"

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        get_success_data(
            api.pause_sales(
                ctx["show"]["id"],
                "a severe weather advisory covers the metro area",
                build.buyer,
            )
        )

        response = api.pause_sales(ctx["show"]["id"], "still snowing", build.buyer)

        validate_error(response, E.ERR_INVALID_STATE)
        still_paused = build.read_show(ctx["show"]["id"])
        assert still_paused["sales_status"] == "PAUSED"
        assert still_paused["show_status"] == "ON_SALE"

    def test_resuming_a_paused_show_restores_the_show_and_its_tier(self, api, build):
        """From PRD §3.4: "Resuming, available to a `TalentBuyer`, moves `sales_status` `PAUSED → SELLING` provided `show_status` is `ON_SALE`, and cascades every `PAUSED` tier back to `ON_SALE`."

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        get_success_data(
            api.pause_sales(
                ctx["show"]["id"],
                "a severe weather advisory covers the metro area",
                build.buyer,
            )
        )

        resumed = validate_success(api.resume_sales(ctx["show"]["id"], build.buyer))

        assert resumed["sales_status"] == "SELLING"
        assert resumed["show_status"] == "ON_SALE"
        assert build.read_tier(ctx["tiers"][0]["id"])["status"] == "ON_SALE"

    def test_a_show_still_in_pre_sale_cannot_be_paused(self, api, build):
        """From PRD §3.4: "A newly booked show starts in `show_status` `PLANNED` and `sales_status` `PRE_SALE`, commits no guarantee, and contributes nothing to its market's exposure." Pausing is declared only for `SELLING → PAUSED`.

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = build.planned_show(show={"rental_fee_cents": RENTAL_FEE_CENTS})
        booked = ctx["show"]
        assert booked["show_status"] == "PLANNED"
        assert booked["sales_status"] == "PRE_SALE"

        response = api.pause_sales(
            booked["id"], "the routing is still being negotiated", build.buyer
        )

        validate_error(response, E.ERR_INVALID_STATE)
        assert_unchanged(
            build.read_show(booked["id"]),
            booked,
            ["show_status", "sales_status", "version"],
        )

    def test_conversion_flips_the_kind_and_records_the_acting_buyer(self, api, build):
        """From PRD §3.5: "On success the hold's `kind` becomes `COMP` and its status moves `HELD → CONVERTED`, `released_by_user_id` records the acting `X-User-ID`"

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        held = ctx["artist_hold"]

        converted = validate_success(
            api.convert_hold_to_comp(held["id"], build.buyer)
        )

        assert held["kind"] == "ARTIST_HOLD"
        assert held["status"] == "HELD"
        assert held["released_by_user_id"] is None
        assert converted["kind"] == "COMP"
        assert converted["status"] == "CONVERTED"
        assert converted["qty"] == 5
        assert converted["released_by_user_id"] == build.buyer["X-User-ID"]
        assert_version_bumped_by(converted, held, 1)

    def test_conversion_moves_seats_from_held_to_comp_and_leaves_available_alone(
        self, api, build
    ):
        """From PRD §3.5: "the tier's `held_qty` decreases by the hold's `qty` while its `comp_qty` increases by the same amount, and the tier's `available_qty` is **unchanged**" — and "The show's `comp_tickets_issued` increases by that quantity and its `held_tickets` decreases by it."

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        before_tier = build.read_tier(ctx["tiers"][0]["id"])
        assert before_tier["held_qty"] == 7
        assert before_tier["comp_qty"] == 0
        assert before_tier["available_qty"] == 293
        assert_tier_inventory_conserved(before_tier)

        get_success_data(api.convert_hold_to_comp(ctx["artist_hold"]["id"], build.buyer))
        get_success_data(
            api.convert_hold_to_comp(ctx["promoter_hold"]["id"], build.buyer)
        )

        tier = build.read_tier(ctx["tiers"][0]["id"])
        assert tier["comp_qty"] == 7
        assert tier["held_qty"] == 0
        assert tier["available_qty"] == 293
        assert tier["sold_qty"] == 0
        assert tier["allocation_qty"] == 300
        assert_tier_inventory_conserved(tier)
        show = build.read_show(ctx["show"]["id"])
        assert show["comp_tickets_issued"] == 7
        assert show["held_tickets"] == 0

    @pytest.mark.parametrize(
        "action", ["convert_hold_to_comp", "release_ticket_hold"]
    )
    def test_a_converted_hold_accepts_no_further_movement(self, api, build, action):
        """From PRD §3.5: "`RELEASED`, `CONVERTED` and `EXPIRED` are all terminal for a hold." PRD §2.9 rules the refusal: "Terminality — `ERR_ALREADY_TERMINAL` when the target already sits in one of its own terminal states."

        Design: Corner/endpoints/sales_pause_and_comp_conversion_are_allowed_only_from_the_states_that_name_them
        """
        ctx = _selling_show_with_two_holds(api, build)
        converted = get_success_data(
            api.convert_hold_to_comp(ctx["artist_hold"]["id"], build.buyer)
        )

        response = getattr(api, action)(converted["id"], build.buyer)

        validate_error(response, E.ERR_ALREADY_TERMINAL)
        after = build.read_hold(converted["id"])
        assert after["status"] == "CONVERTED"
        assert after["kind"] == "COMP"
        assert build.read_tier(ctx["tiers"][0]["id"])["comp_qty"] == 5
