"""Two places where the API computes the same quantity two ways and keeps both:
the pickup-pace projections on a block, and the two commission bases on an
invoice."""

from test_helpers import (
    make_event_organizer_headers,
    setup_issued_invoice,
    setup_pickup_history,
    validate_success,
)

# Three cumulative reports whose whole-window pace (2.0 room nights per day)
# is deliberately slower than the pace of the most recent pair (3.0).
ACCELERATING_REPORTS = [
    {
        "as_of_date": "2026-08-05",
        "reported_rooms_picked_up": 3,
        "reported_room_nights": 6,
        "reported_gross_revenue_cents": 131400,
    },
    {
        "as_of_date": "2026-08-11",
        "reported_rooms_picked_up": 5,
        "reported_room_nights": 12,
        "reported_gross_revenue_cents": 262800,
    },
    {
        "as_of_date": "2026-08-17",
        "reported_rooms_picked_up": 8,
        "reported_room_nights": 30,
        "reported_gross_revenue_cents": 657000,
    },
]

# The same geometry pushed across the pace target: the whole-window pace
# projects 31 room nights while the latest pair projects 35.
LATE_SURGE_REPORTS = [
    {
        "as_of_date": "2026-08-01",
        "reported_rooms_picked_up": 1,
        "reported_room_nights": 1,
        "reported_gross_revenue_cents": 21900,
    },
    {
        "as_of_date": "2026-08-13",
        "reported_rooms_picked_up": 4,
        "reported_room_nights": 15,
        "reported_gross_revenue_cents": 328500,
    },
    {
        "as_of_date": "2026-08-17",
        "reported_rooms_picked_up": 7,
        "reported_room_nights": 25,
        "reported_gross_revenue_cents": 547500,
    },
]

# Two stays worth six room nights: 4 nights and 2 nights at 21900 cents.
TWO_STAYS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 2},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 1},
]

# The hotel attributes only five of those six room nights to the block.
UNDER_REPORTED_PICKUP = [
    {
        "as_of_date": "2026-08-19",
        "reported_rooms_picked_up": 2,
        "reported_room_nights": 5,
        "reported_gross_revenue_cents": 109500,
    },
]


class TestPickupPaceProjections:
    """The two projection geometries over one report history."""

    def test_two_projections_diverge_on_the_same_three_reports(self, api):
        """PRD §3.6: "The **forward-looking projection** measures average pace
        across the whole observed window: the difference in
        `reported_room_nights` between the last and the first report, divided by
        the number of whole days between their `as_of_date` values, gives an
        average daily pace; that pace multiplied by `days_remaining_to_cutoff`
        is added to the last report's `reported_room_nights`, and the sum is
        rounded half up to a whole number of room nights to give
        `forward_looking_projection_room_nights`."
        PRD §3.6: "The **chronological run rate** measures only the most recent
        consecutive pair: the difference in `reported_room_nights` between the
        last and the second-to-last report, divided by the number of whole days
        between their `as_of_date` values, gives the latest daily rate; that
        rate multiplied by `days_remaining_to_cutoff` is added to the last
        report's `reported_room_nights`, and the sum is rounded half up to give
        `chronological_run_rate_projection_room_nights`."
        PRD §3.6: "`pace_variance_room_nights` is the chronological run-rate
        projection minus the forward-looking projection, and it is the number
        the bureau argues about."

        Design: Difficulty/dual_variant_calc/pickup_pace_two_projection_variants_diverge_on_hotel_block
        """
        ctx = setup_pickup_history(ACCELERATING_REPORTS, contracted_rooms_per_night=10)

        pace = validate_success(
            api.get_pickup_pace(
                ctx["block"]["id"], make_event_organizer_headers(ctx["event"]["id"])
            )
        )

        assert pace["report_count"] == 3
        assert pace["latest_reported_room_nights"] == 30
        assert pace["days_remaining_to_cutoff"] == 4
        assert pace["forward_looking_projection_room_nights"] == 38, (
            "whole-window pace of 2.0 room nights per day over 4 remaining days "
            f"projects 38, got {pace['forward_looking_projection_room_nights']}"
        )
        assert pace["chronological_run_rate_projection_room_nights"] == 42, (
            "latest-pair rate of 3.0 room nights per day projects 42, got "
            f"{pace['chronological_run_rate_projection_room_nights']}"
        )
        assert pace["pace_variance_room_nights"] == 4
        assert pace["hotel_block_id"] == ctx["block"]["id"]

    def test_on_pace_follows_the_contractual_projection_not_the_run_rate(self, api):
        """PRD §3.6: "Separately, `pace_target_room_nights` is the block's
        `contracted_room_nights` multiplied by the pace target ratio of 80
        percent, rounded half up to whole room nights."
        PRD §3.6: "The boolean `on_pace` is true exactly when
        `forward_looking_projection_room_nights` is greater than or equal to
        `pace_target_room_nights` — the contractual projection decides it, never
        the run rate."

        Design: Difficulty/dual_variant_calc/pickup_pace_two_projection_variants_diverge_on_hotel_block
        """
        ctx = setup_pickup_history(LATE_SURGE_REPORTS, contracted_rooms_per_night=10)
        organizer = make_event_organizer_headers(ctx["event"]["id"])

        pace = validate_success(api.get_pickup_pace(ctx["block"]["id"], organizer))

        assert pace["pace_target_room_nights"] == 32, (
            "40 contracted room nights at the 80 percent target rounds to 32, got "
            f"{pace['pace_target_room_nights']}"
        )
        assert pace["forward_looking_projection_room_nights"] == 31
        assert pace["chronological_run_rate_projection_room_nights"] == 35
        assert pace["pace_variance_room_nights"] == 4
        # The run rate clears the 32 target and the forward projection does not,
        # so only the contractual figure can be deciding on_pace.
        assert pace["on_pace"] is False


class TestCommissionBasisVariants:
    """One invoice, both commission sides, and the basis that selects the bill."""

    def test_hotel_reported_basis_bills_the_pickup_report_and_shows_variance(self, api):
        """PRD §3.9: "`bureau_confirmed_commission_cents` is that pre-tax
        revenue multiplied by the block's `commission_pct`, rounded half up to
        whole cents **once for the side** — never per reservation."
        PRD §3.9: "On `HOTEL_REPORTED`, `commission_due_cents` takes
        `hotel_reported_commission_cents` and `billable_room_nights` takes the
        latest report's `reported_room_nights` — so unattributed rooms silently
        disappear from the bill and surface only as variance."
        PRD §3.9: "`variance_cents` is the signed difference
        `bureau_confirmed_commission_cents` minus
        `hotel_reported_commission_cents`, and is null when no pickup report
        exists."

        Design: Difficulty/dual_variant_calc/commission_two_basis_variants_diverge_on_invoice
        """
        ctx = setup_issued_invoice(
            stays=TWO_STAYS,
            basis="HOTEL_REPORTED",
            pickup_reports=UNDER_REPORTED_PICKUP,
            general_rooms=6,
        )
        invoice = ctx["invoice"]

        assert invoice["bureau_confirmed_commission_cents"] == 15768, (
            "131400 pre-tax cents at 0.12 rounds to 15768, got "
            f"{invoice['bureau_confirmed_commission_cents']}"
        )
        assert invoice["hotel_reported_commission_cents"] == 13140
        assert invoice["commission_due_cents"] == 13140
        assert invoice["billable_room_nights"] == 5
        assert invoice["rebate_due_cents"] == 3500
        assert invoice["variance_cents"] == 2628
        assert invoice["outstanding_cents"] == 13140
        assert invoice["status"] == "ISSUED"

    def test_bureau_confirmed_basis_bills_the_reservation_ledger_instead(self, api):
        """PRD §3.9: "Both sides are always computed, whichever basis is chosen,
        because the reconciliation is the point."
        PRD §3.9: "On `BUREAU_CONFIRMED`, `commission_due_cents` takes
        `bureau_confirmed_commission_cents` and `billable_room_nights` takes the
        bureau room-night total — so rooms the hotel failed to attribute to the
        block are still billed."
        PRD §3.9: "`rebate_due_cents`, the money owed to the organizer, is the
        block's `rebate_per_room_night_cents` multiplied by
        `billable_room_nights`."

        Design: Difficulty/dual_variant_calc/commission_two_basis_variants_diverge_on_invoice
        """
        ctx = setup_issued_invoice(
            stays=TWO_STAYS,
            basis="BUREAU_CONFIRMED",
            pickup_reports=UNDER_REPORTED_PICKUP,
            general_rooms=6,
        )
        invoice = ctx["invoice"]

        assert invoice["basis"] == "BUREAU_CONFIRMED"
        assert invoice["bureau_confirmed_commission_cents"] == 15768
        assert invoice["hotel_reported_commission_cents"] == 13140
        assert invoice["commission_due_cents"] == 15768, (
            "the bureau basis bills its own ledger, got "
            f"{invoice['commission_due_cents']}"
        )
        assert invoice["billable_room_nights"] == 6
        assert invoice["rebate_due_cents"] == 4200
        assert invoice["variance_cents"] == 2628
        assert invoice["outstanding_cents"] == 15768
