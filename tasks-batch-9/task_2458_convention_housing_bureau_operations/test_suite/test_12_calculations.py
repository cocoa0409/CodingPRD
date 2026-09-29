"""Derived figures: the posture aggregation, occupancy input filtering, vendor risk
constants, the dispute tolerance band, the top attrition tier, the reduction
waterfall, pickup chronology and pace, the buffered overlap, and no-show billing."""

from test_helpers import (
    COMPLIANCE,
    COORDINATOR,
    approve_reduction,
    book_reservation,
    cancel_reservation,
    create_reservation_payload,
    exercise_reduction,
    file_reduction,
    import_attendee,
    make_attendee_headers,
    read_block,
    record_incident,
    record_rogue_vendor,
    register_event,
    report_no_show,
    set_clock,
    setup_block_at_cutoff,
    setup_closed_block,
    setup_housing_program,
    setup_issued_invoice,
    setup_open_block,
    setup_pickup_history,
    validate_error,
    validate_paginated,
    validate_success,
)

FULL_WINDOW_STAY = {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18"}

ONE_FOUR_NIGHT_STAY = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
]

FOUR_AND_TWO_NIGHTS = [
    {"check_in_date": "2026-09-14", "check_out_date": "2026-09-18", "occupants": 1},
    {"check_in_date": "2026-09-15", "check_out_date": "2026-09-17", "occupants": 1},
]

# 100000 pre-tax cents reported against a 131400-cent bureau ledger.
NEAR_MISS_PICKUP = [
    {
        "as_of_date": "2026-08-19",
        "reported_rooms_picked_up": 2,
        "reported_room_nights": 5,
        "reported_gross_revenue_cents": 100000,
    }
]

FIRST_PICKUP_REPORT = {
    "as_of_date": "2026-08-05",
    "reported_rooms_picked_up": 3,
    "reported_room_nights": 6,
    "reported_gross_revenue_cents": 131400,
}


class TestPostureRestrictedOnFullInventory:
    def test_committing_the_only_room_moves_the_posture_from_open_to_restricted(
        self, api
    ):
        """PRD §2.11: "The **available room count** is the sum of `available_rooms`
        over every sub-block whose `approval_status` is `APPROVED` and whose parent
        block is in the open group."
        PRD §2.11: "Otherwise, if the open group is non-empty and the available room
        count is exactly zero, the posture is `RESTRICTED`."
        PRD §3.3: "`inventory_status` is the enum `FULL` when `available_rooms` is
        exactly zero and `OPEN` otherwise."

        Design: Corner/calculations/event_posture_becomes_restricted_when_approved_inventory_is_full
        """
        ctx = setup_open_block(
            general_rooms=1, contracted_rooms_per_night=1, num_attendees=1
        )
        before = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert before["housing_posture"] == "OPEN"

        book_reservation(ctx["sub_block"]["id"], ctx["attendees"][0], **FULL_WINDOW_STAY)

        after = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert after["housing_posture"] == "RESTRICTED", (
            "the block is still OPEN, so a full allotment is RESTRICTED and not "
            f"CLOSED, got {after['housing_posture']}"
        )

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["available_rooms"] == 0
        assert sub_block["inventory_status"] == "FULL"
        assert read_block(ctx["block"]["id"])["status"] == "OPEN"


class TestOccupancyInputSetFiltering:
    def test_a_cancelled_stay_frees_its_night_for_an_overlapping_booking(self, api):
        """PRD §3.3: "the server counts the reservations of that sub-block whose
        `reservation_status` is `CONFIRMED` and whose stay covers that night"
        PRD §3.3: "Only `CONFIRMED` reservations occupy inventory: `WAITLISTED`,
        `CANCELLED` and `NO_SHOW` rows count for nothing."
        PRD §3.4: "for every night the candidate stay would occupy, the count of
        `CONFIRMED` reservations already covering that night, plus one for the
        candidate, must be less than or equal to the sub-block's `allotted_rooms`."

        Design: Corner/calculations/sub_block_occupancy_counts_only_confirmed_reservations
        """
        ctx = setup_open_block(
            general_rooms=1, contracted_rooms_per_night=1, num_attendees=2
        )
        first, second = ctx["attendees"]

        held = book_reservation(ctx["sub_block"]["id"], first, **FULL_WINDOW_STAY)
        cancelled = cancel_reservation(held["id"], first["id"])
        assert cancelled["reservation_status"] == "CANCELLED"

        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                second["id"],
                check_in_date="2026-09-15",
                check_out_date="2026-09-17",
            ),
            make_attendee_headers(second["id"]),
        )
        replacement = validate_success(response, 201)
        assert replacement["reservation_status"] == "CONFIRMED"

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1, (
            "the cancelled row must drop out of the occupancy input set, got "
            f"{sub_block['committed_rooms']}"
        )
        assert sub_block["available_rooms"] == 0

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 2


class TestRiskScoreConstants:
    def test_one_single_channel_incident_scores_fifty_and_does_not_escalate(self, api):
        """PRD §3.8: "The vendor starts in `status` `REPORTED` with
        `warning_issued_count` at 0, and with its `risk_score` and
        `verified_incident_count` derived immediately — which, with no incidents on
        file, puts the score at the base value of 10."
        PRD §3.8: "The score starts from a base of 10, adds 25 for each counted
        incident, adds 15 for each distinct `contact_channel` appearing among the
        counted incidents, and adds a further 20 if any counted incident has
        `solicited_payment` true — that bonus is awarded once, not per incident."
        PRD §3.8: "A single verified incident on one channel with no payment
        solicitation scores 50 and does not escalate; the same incident with
        `solicited_payment` true scores 70 and does."
        PRD §3.8: "Each incident begins in `status` `RECORDED` with
        `warning_issued_at` and `warning_severity` both null"

        Design: Corner/calculations/risk_score_constants_leave_single_incident_vendor_below_review
        """
        event = register_event()
        guest = import_attendee(event["id"])

        vendor = record_rogue_vendor(event["id"])
        assert vendor["risk_score"] == 10
        assert vendor["status"] == "REPORTED"

        incident = record_incident(
            vendor["id"],
            guest["id"],
            contact_channel="EMAIL",
            occurred_at="2026-07-20T10:00:00Z",
            verified=True,
            solicited_payment=False,
        )
        assert incident["status"] == "RECORDED"
        assert incident["warning_severity"] is None

        after = validate_success(api.get_rogue_vendor(vendor["id"], COMPLIANCE))
        assert after["risk_score"] == 50, (
            f"base 10 plus 25 for the incident plus 15 for its channel, got "
            f"{after['risk_score']}"
        )
        assert after["status"] == "REPORTED"
        assert after["verified_incident_count"] == 1

        attendee = validate_success(api.get_attendee(guest["id"], COORDINATOR))
        assert attendee["warning_count"] == 0


class TestVarianceToleranceBand:
    def test_a_variance_inside_the_five_thousand_cent_floor_cannot_be_disputed(
        self, api
    ):
        """PRD §3.9: "The tolerance is the greater of a floor of 5,000 cents — fifty
        dollars — and one percent of `bureau_confirmed_commission_cents` rounded half
        up to whole cents."
        PRD §3.9: "The owning `HotelManager` may dispute only from `ISSUED` or
        `PARTIALLY_PAID`, with any other status rejected as `ERR_INVOICE_NOT_PAYABLE`,
        and only when the absolute value of `variance_cents` is **strictly greater**
        than that tolerance; a variance inside the band, and equally a
        `variance_cents` that is null because the block never filed a pickup report,
        is rejected with `ERR_VARIANCE_WITHIN_TOLERANCE`."
        PRD §3.9: "`variance_cents` is the signed difference
        `bureau_confirmed_commission_cents` minus `hotel_reported_commission_cents`,
        and is null when no pickup report exists."

        Design: Corner/calculations/variance_below_tolerance_floor_blocks_dispute
        """
        ctx = setup_issued_invoice(
            stays=FOUR_AND_TWO_NIGHTS,
            basis="BUREAU_CONFIRMED",
            pickup_reports=NEAR_MISS_PICKUP,
            general_rooms=6,
        )
        invoice = ctx["invoice"]
        assert invoice["commission_due_cents"] == 15768
        assert invoice["hotel_reported_commission_cents"] == 12000
        assert invoice["variance_cents"] == 3768
        assert invoice["billable_room_nights"] == 6
        assert invoice["rebate_due_cents"] == 4200

        response = api.dispute_commission_invoice(invoice["id"], ctx["hotel_headers"])
        validate_error(response, "ERR_VARIANCE_WITHIN_TOLERANCE", 422)

        after = validate_success(
            api.get_commission_invoice(invoice["id"], COORDINATOR)
        )
        assert after["status"] == "ISSUED"
        assert after["version"] == invoice["version"]


class TestAttritionTopTier:
    def test_a_block_that_picked_up_nothing_pays_the_ninety_percent_tier(self, api):
        """PRD §3.9: "Closure freezes the attrition exposure:
        `attrition_liability_cents` is set to the post-reduction attrition penalty
        exposure defined in §3.7, computed against the block as it finally stands."
        PRD §3.7: "The **protected room nights** are the adjusted contracted room
        nights multiplied by the allowed pickup ratio of 80 percent, rounded half up
        to a whole number of room nights."
        PRD §3.7: "The **penalty rate** is selected by tier from the shortfall ratio:
        50 percent when the ratio is less than or equal to 0.10; otherwise 70 percent
        when the ratio is less than or equal to 0.25; otherwise 90 percent."
        PRD §3.7: "The **penalty** is the shortfall room nights multiplied by the
        block's `negotiated_nightly_rate_cents` multiplied by the penalty rate,
        rounded half up to whole cents once, at this final step."
        PRD §3.9: "Any sub-block whose `allotted_rooms` became 0 through this sweep
        moves `APPROVED → RELEASED`."

        Design: Corner/calculations/attrition_tier_three_applies_ninety_percent_to_full_shortfall
        """
        ctx = setup_closed_block(
            [], general_rooms=1, contracted_rooms_per_night=1
        )

        # Adjusted 4 room nights, actual 0, protected 3, shortfall 3, ratio 0.75.
        assert ctx["block"]["status"] == "CLOSED"
        assert ctx["block"]["attrition_liability_cents"] == 59130, (
            "3 shortfall nights at 21900 cents and the 90 percent tier is 59130, "
            f"got {ctx['block']['attrition_liability_cents']}"
        )
        assert ctx["block"]["attrition_liability_cents"] != 45990
        assert ctx["block"]["released_rooms_per_night"] == 1

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["approval_status"] == "RELEASED"
        assert sub_block["allotted_rooms"] == 0


class TestReductionWaterfallOrder:
    def test_the_waterfall_drains_unassigned_first_then_the_general_carve(self, api):
        """PRD §3.7: "The block's `unassigned_rooms_per_night` absorbs first: the
        smaller of the outstanding rooms and the unassigned pool is taken out of
        `unassigned_rooms_per_night` and recorded on the reduction as
        `rooms_absorbed_from_unassigned`."
        PRD §3.7: "Those eligible sub-blocks are visited in a fixed segment order,
        `GENERAL` first, then `EXHIBITOR`, then `STAFF`, then `VIP` last, and within
        one segment in ascending `carve_seq` order; each sub-block visited gives up
        the smaller of the outstanding rooms and its own `allotted_rooms`, and the
        walk stops the moment nothing is outstanding."
        PRD §3.7: "The block's `contracted_rooms_per_night` falls by
        `requested_reduction_rooms`, its `contracted_room_nights` is re-derived from
        the new figure and the event's `night_count`, and the block's `version` is
        bumped."
        PRD §3.7: "The total drawn from sub-blocks is recorded as
        `rooms_absorbed_from_sub_blocks`, which is `requested_reduction_rooms` minus
        `rooms_absorbed_from_unassigned`."
        PRD §3.7: "The block's `attrition_liability_cents` is set to the
        post-reduction attrition penalty exposure, and the reduction's
        `penalty_avoided_cents` is set to the pre-reduction exposure minus the
        post-reduction exposure."
        PRD §3.7: "The **pre-reduction** variant exists only to fill
        `penalty_avoided_cents`: it adds this reduction's `requested_reduction_rooms`
        back into `contracted_rooms_per_night` for the purpose of steps one, three,
        four and six, while keeping the **same post-cascade actual room nights** from
        step two, so that a tier change between the two runs surfaces as avoided
        penalty."

        Design: Corner/calculations/reduction_waterfall_drains_unassigned_then_lowest_segment_rank
        """
        ctx = setup_housing_program(
            contracted_rooms_per_night=10,
            carves=[
                {"segment": "GENERAL", "allotted_rooms": 4},
                {
                    "segment": "VIP",
                    "allotted_rooms": 2,
                    "eligibility_code": "VIP-2026",
                    "approve": True,
                },
            ],
            open_portal=True,
            block_overrides={"reduction_rights_pct": 0.50},
        )
        general, vip = ctx["sub_blocks"]
        assert ctx["block"]["unassigned_rooms_per_night"] == 4

        # Cap is floor(10 * 0.50) == 5, so a 5-room strike is the whole entitlement.
        reduction = file_reduction(ctx["block"]["id"], 5, effective_date="2026-08-14")
        approve_reduction(reduction["id"])
        exercised = exercise_reduction(reduction["id"])

        assert exercised["status"] == "EXERCISED"
        assert exercised["rooms_absorbed_from_unassigned"] == 4
        assert exercised["rooms_absorbed_from_sub_blocks"] == 1

        block = read_block(ctx["block"]["id"])
        assert block["unassigned_rooms_per_night"] == 0
        assert block["contracted_rooms_per_night"] == 5
        assert block["contracted_room_nights"] == 20

        general_after = validate_success(api.get_sub_block(general["id"], COORDINATOR))
        vip_after = validate_success(api.get_sub_block(vip["id"], COORDINATOR))
        assert general_after["allotted_rooms"] == 3, (
            "the single sub-block room comes from GENERAL, got "
            f"{general_after['allotted_rooms']}"
        )
        assert vip_after["allotted_rooms"] == 2, "VIP inventory is protected last"

        # Post-reduction: adjusted 20, protected 16, shortfall 16, ratio 0.80.
        assert block["attrition_liability_cents"] == 315360
        # Pre-reduction the same 0.90 tier applies to 32 shortfall nights: 630720.
        assert exercised["penalty_avoided_cents"] == 315360


class TestPickupChronology:
    def test_an_earlier_or_equal_as_of_date_is_refused(self, api):
        """PRD §3.6: "Their sequence is strictly increasing: an `as_of_date` that is
        not strictly later than the latest existing report's `as_of_date` for that
        block is rejected with `ERR_PICKUP_REPORT_OUT_OF_ORDER`."
        PRD §3.6: "History is readable in `as_of_date` ascending order."

        Design: Corner/calculations/pickup_report_with_earlier_as_of_date_rejected
        """
        ctx = setup_pickup_history([FIRST_PICKUP_REPORT])
        first_report = ctx["pickup_reports"][0]

        earlier = api.create_pickup_report(
            ctx["block"]["id"],
            {
                "as_of_date": "2026-08-03",
                "reported_rooms_picked_up": 2,
                "reported_room_nights": 4,
                "reported_gross_revenue_cents": 87600,
            },
            ctx["hotel_headers"],
        )
        validate_error(earlier, "ERR_PICKUP_REPORT_OUT_OF_ORDER", 422)

        same_day = api.create_pickup_report(
            ctx["block"]["id"],
            {
                "as_of_date": "2026-08-05",
                "reported_rooms_picked_up": 4,
                "reported_room_nights": 8,
                "reported_gross_revenue_cents": 175200,
            },
            ctx["hotel_headers"],
        )
        validate_error(same_day, "ERR_PICKUP_REPORT_OUT_OF_ORDER", 422)

        rows, meta = validate_paginated(
            api.list_pickup_reports(ctx["block"]["id"], COORDINATOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == first_report["id"]
        assert rows[0]["reported_room_nights"] == 6


class TestPaceWithASingleReport:
    def test_one_report_flattens_both_projections_onto_the_latest_figure(self, api):
        """PRD §3.6: "When fewer than two reports exist, no extrapolation is
        possible: both projections equal the latest `reported_room_nights` and
        `pace_variance_room_nights` is 0"
        PRD §3.6: "`days_remaining_to_cutoff` is the number of whole days from the
        last report's `as_of_date` to the block's `cutoff_date`."
        PRD §3.6: "Separately, `pace_target_room_nights` is the block's
        `contracted_room_nights` multiplied by the pace target ratio of 80 percent,
        rounded half up to whole room nights. The boolean `on_pace` is true exactly
        when `forward_looking_projection_room_nights` is greater than or equal to
        `pace_target_room_nights` — the contractual projection decides it, never the
        run rate."

        Design: Corner/calculations/pickup_pace_with_single_report_flattens_both_projections
        """
        ctx = setup_pickup_history([FIRST_PICKUP_REPORT], contracted_rooms_per_night=10)
        assert ctx["block"]["contracted_room_nights"] == 40

        pace = validate_success(
            api.get_pickup_pace(ctx["block"]["id"], ctx["organizer_headers"])
        )

        assert pace["hotel_block_id"] == ctx["block"]["id"]
        assert pace["report_count"] == 1
        assert pace["latest_reported_room_nights"] == 6
        assert pace["days_remaining_to_cutoff"] == 16
        assert pace["forward_looking_projection_room_nights"] == 6
        assert pace["chronological_run_rate_projection_room_nights"] == 6
        assert pace["pace_variance_room_nights"] == 0
        assert pace["pace_target_room_nights"] == 32
        assert pace["on_pace"] is False


class TestOverlapAdmitsAWideGap:
    def test_a_stay_starting_one_day_past_the_high_bound_is_admitted(self, api):
        """PRD §3.4: "Each of that attendee's other reservations whose
        `reservation_status` is `CONFIRMED` or `WAITLISTED` is inflated by a one-day
        shoulder buffer at each end, producing a low bound one day before its
        `check_in_date` and a high bound one day after its `check_out_date`, and both
        bounds are treated as **inclusive**."
        PRD §3.4: "The candidate stay is accepted against that existing stay only
        when the candidate's `check_out_date` falls strictly before the low bound, or
        the candidate's `check_in_date` falls strictly after the high bound; in every
        other case the two collide and the booking is rejected with
        `ERR_ATTENDEE_STAY_OVERLAP`."
        PRD §3.4: "`check_out_date` must be no later than one day after the event's
        `event_end_date`"

        Design: Corner/calculations/stay_overlap_admits_gap_wider_than_shoulder_buffer
        """
        ctx = setup_open_block(
            general_rooms=1, contracted_rooms_per_night=1, num_attendees=1
        )
        guest = ctx["attendees"][0]
        book_reservation(ctx["sub_block"]["id"], guest, "2026-09-14", "2026-09-16")

        response = api.create_reservation(
            create_reservation_payload(
                ctx["sub_block"]["id"],
                guest["id"],
                check_in_date="2026-09-18",
                check_out_date="2026-09-19",
            ),
            make_attendee_headers(guest["id"]),
        )
        second = validate_success(response, 201)

        assert second["reservation_status"] == "CONFIRMED"
        assert second["room_nights"] == 1
        assert second["total_room_charge_cents"] == 25130

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 1

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 3


class TestNoShowBilling:
    def test_a_no_show_bills_one_night_not_the_whole_stay(self, api):
        """PRD §3.5: "On success the guest is billed for exactly one night:
        `no_show_billed_cents` is the taxed nightly amount —
        `quoted_nightly_rate_cents` multiplied by one plus `room_tax_pct_snapshot`,
        rounded half up to whole cents — multiplied by the single billed no-show
        night."
        PRD §3.5: "The guest's `no_show_strikes` rises by one, the sub-block's
        occupancy is recomputed because a `NO_SHOW` row leaves the committed set, and
        the event's `total_confirmed_room_nights` is recomputed."
        PRD §3.5: "The `HotelManager` that owns the block moves a reservation
        `CONFIRMED → NO_SHOW`, and four conditions must hold: the reservation is in
        `CONFIRMED`, the parent block's `status` is exactly `CUTOFF_PASSED`, the
        block's `hotel_id` equals the acting `X-User-ID`, and the logical clock has
        reached the reservation's `check_in_date` at midnight UTC."

        Design: Corner/calculations/no_show_bills_exactly_one_night_at_snapshotted_rate
        """
        ctx = setup_block_at_cutoff(ONE_FOUR_NIGHT_STAY, general_rooms=6)
        reservation = ctx["reservations"][0]
        assert reservation["total_room_charge_cents"] == 100520

        set_clock("2026-09-14T12:00:00Z")
        no_show = report_no_show(reservation["id"], ctx["hotel"]["id"])

        assert no_show["reservation_status"] == "NO_SHOW"
        assert no_show["no_show_billed_cents"] == 25130, (
            "one taxed night of 25130 cents is billed, never the 100520 stay, got "
            f"{no_show['no_show_billed_cents']}"
        )
        assert no_show["total_room_charge_cents"] == 100520

        attendee = validate_success(
            api.get_attendee(ctx["attendees"][0]["id"], COORDINATOR)
        )
        assert attendee["no_show_strikes"] == 1

        event = validate_success(api.get_event(ctx["event"]["id"], COORDINATOR))
        assert event["total_confirmed_room_nights"] == 0

        sub_block = validate_success(
            api.get_sub_block(ctx["sub_block"]["id"], COORDINATOR)
        )
        assert sub_block["committed_rooms"] == 0
