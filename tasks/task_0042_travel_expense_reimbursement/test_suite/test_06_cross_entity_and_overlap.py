"""Cross-entity state dependencies and resource temporal overlaps.

Queue A (Difficulty) — rules cross_entity_state_dependency and resource_temporal_overlap.
"""
from test_helpers import (
    validate_error,
    validate_success,
    get_success_data,
    ApiErrorId,
    setup_base_env,
    create_pending_trip,
    create_approved_trip,
    create_report,
    add_mileage_line,
    add_flight_line,
    add_lodging_line,
    issue_card,
)


class TestReportSubmitRequiresTripApproved:
    def test_submit_blocked_when_trip_pending_oop(self, api):
        """PRD §3.8: "The report's trip must already be APPROVED, or the submission is
        rejected with ERR_TRIP_NOT_APPROVED."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_trip_approved
        """
        env = setup_base_env(lodging_cap_cents=20000, mie_cents=8000)
        # 4 nights baseline 224000; budget 300000 -> OOP -> stays PENDING_OOP_APPROVAL.
        trip = create_pending_trip(env, budget_total_cents=300000,
                                   start_date="2026-06-01", end_date="2026-06-05")
        submitted = get_success_data(api.submit_trip_request(trip["id"], env["traveler_headers"]))
        assert submitted["status"] == "PENDING_OOP_APPROVAL"
        report = create_report(env, trip, title="Early Rpt")
        add_mileage_line(env, report, miles=100)
        resp = api.submit_expense_report(report["id"], env["traveler_headers"])
        validate_error(resp, ApiErrorId.ERR_TRIP_NOT_APPROVED.value)

    def test_submit_allowed_when_trip_approved(self, api):
        """PRD §3.8: "The report's trip must already be APPROVED, or the submission is
        rejected with ERR_TRIP_NOT_APPROVED."
        PRD §3.8: "A valid submission moves the report from DRAFT to SUBMITTED and
        recomputes meal_reimbursable_cents and total_reimbursable_cents."

        Design: Difficulty/cross_entity_state_dependency/report_submit_requires_trip_approved
        """
        env = setup_base_env()
        # in-policy trip auto-approves to APPROVED.
        trip = create_approved_trip(env, budget_total_cents=100000)
        assert trip["status"] == "APPROVED"
        report = create_report(env, trip, title="Ready Rpt")
        add_mileage_line(env, report, miles=100)
        data = get_success_data(api.submit_expense_report(report["id"], env["traveler_headers"]))
        assert data["status"] == "SUBMITTED", "report submits once its trip is APPROVED"


class TestLineChargeRequiresCardActive:
    def test_charge_to_frozen_card_rejected(self, api):
        """PRD §3.4: "A line may only be charged to a card that is ACTIVE, otherwise
        the charge is refused with ERR_CARD_NOT_ACTIVE"
        PRD §3.3: "Freezing moves a card from ACTIVE to FROZEN; while frozen, any
        attempt to charge a new expense line to the card is refused with
        ERR_CARD_NOT_ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/line_charge_requires_card_active
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        card = issue_card(env, trip, load_limit_cents=100000)
        get_success_data(api.freeze_virtual_card(card["id"], env["admin_headers"]))
        report = create_report(env, trip, title="Frozen Card Rpt")
        resp = api.create_expense_line(
            {
                "report_id": report["id"], "line_type": "FLIGHT",
                "claimed_amount_cents": 30000, "virtual_card_id": card["id"],
                "cabin_class": "ECONOMY", "scheduled_hours": 4, "advance_days": 20,
            },
            env["traveler_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)

    def test_charge_allowed_after_unfreeze(self, api):
        """PRD §3.3: "Unfreezing returns it from FROZEN to ACTIVE."
        PRD §3.4: "A line may only be charged to a card that is ACTIVE, otherwise the
        charge is refused with ERR_CARD_NOT_ACTIVE"
        PRD §3.4: "When a line names a virtual card, charging it creates a provisional
        hold on that card: the line's settlement_status becomes PENDING and its
        reimbursable amount is reflected in the card's authorized_holds_cents."

        Design: Difficulty/cross_entity_state_dependency/line_charge_requires_card_active
        """
        env = setup_base_env()
        trip = create_approved_trip(env, budget_total_cents=100000)
        card = issue_card(env, trip, load_limit_cents=100000)
        get_success_data(api.freeze_virtual_card(card["id"], env["admin_headers"]))
        get_success_data(api.unfreeze_virtual_card(card["id"], env["admin_headers"]))
        report = create_report(env, trip, title="Unfrozen Card Rpt")
        # Card is ACTIVE again -> the charge succeeds and creates a PENDING hold.
        line = validate_success(
            api.create_expense_line(
                {
                    "report_id": report["id"], "line_type": "FLIGHT",
                    "claimed_amount_cents": 30000, "virtual_card_id": card["id"],
                    "cabin_class": "ECONOMY", "scheduled_hours": 4, "advance_days": 20,
                },
                env["traveler_headers"],
            ),
            expected_status=201,
        )
        assert line["settlement_status"] == "PENDING", "charge to ACTIVE card opens a hold"


class TestTripDateOverlap:
    def test_touching_endpoint_collides(self, api):
        """PRD §3.2: "a new trip whose date range overlaps any existing trip of the
        same traveler in PENDING, PENDING_OOP_APPROVAL, AUTO_APPROVED, or APPROVED is
        rejected with ERR_TRIP_DATE_OVERLAP. Overlap is evaluated on the closed
        interval from start_date through end_date inclusive on both ends, so two trips
        that merely touch at an endpoint — one ending on the very day another begins —
        are treated as overlapping and collide."

        Design: Difficulty/resource_temporal_overlap/trip_dates_closed_interval_overlap
        """
        env = setup_base_env()
        create_pending_trip(env, budget_total_cents=100000,
                            start_date="2026-06-01", end_date="2026-06-05")
        # Second trip starts on first trip's end_date -> closed-interval touch -> collide.
        resp = api.create_trip_request(
            {
                "traveler_id": env["traveler"]["id"], "destination_state": "CA",
                "start_date": "2026-06-05", "end_date": "2026-06-08",
                "budget_total_cents": 100000,
            },
            env["traveler_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_TRIP_DATE_OVERLAP.value)

    def test_non_overlapping_trip_allowed(self, api):
        """PRD §3.2: "a new trip whose date range overlaps any existing trip of the same
        traveler in PENDING, PENDING_OOP_APPROVAL, AUTO_APPROVED, or APPROVED is rejected
        with ERR_TRIP_DATE_OVERLAP. Overlap is evaluated on the closed interval from
        start_date through end_date inclusive on both ends, so two trips that merely
        touch at an endpoint — one ending on the very day another begins — are treated
        as overlapping and collide."

        Design: Difficulty/resource_temporal_overlap/trip_dates_closed_interval_overlap
        """
        env = setup_base_env()
        create_pending_trip(env, budget_total_cents=100000,
                            start_date="2026-06-01", end_date="2026-06-05")
        # A second trip strictly after the first (starts the day after end) does not collide.
        resp = api.create_trip_request(
            {
                "traveler_id": env["traveler"]["id"], "destination_state": "CA",
                "start_date": "2026-06-06", "end_date": "2026-06-08",
                "budget_total_cents": 100000,
            },
            env["traveler_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING", "a non-overlapping trip is created successfully"


class TestLodgingOverlapHalfOpen:
    def test_adjacent_lodging_allowed_genuine_overlap_rejected(self, api):
        """PRD §3.4: "Lodging lines additionally may not overlap one another within
        the same report: their stays are compared on the half-open interval from
        check_in_date up to but not including check_out_date, so two stays where one's
        check_out_date equals the next one's check_in_date are adjacent and permitted,
        while any genuine overlap is rejected with ERR_LODGING_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/lodging_nights_half_open_adjacent_allowed
        """
        env = setup_base_env(lodging_cap_cents=20000)
        trip = create_approved_trip(env, budget_total_cents=100000,
                                    start_date="2026-06-01", end_date="2026-06-05")
        report = create_report(env, trip, title="Lodging Rpt")
        add_lodging_line(env, report, claimed_amount_cents=30000,
                         check_in_date="2026-06-01", check_out_date="2026-06-03")
        # Adjacent stay (check_in == prior check_out) is permitted.
        resp_adj = api.create_expense_line(
            {
                "report_id": report["id"], "line_type": "LODGING",
                "claimed_amount_cents": 20000,
                "check_in_date": "2026-06-03", "check_out_date": "2026-06-05",
            },
            env["traveler_headers"],
        )
        adj = validate_success(resp_adj, expected_status=201)
        assert adj["reimbursable_amount_cents"] == 20000, "adjacent 1-night stay caps at 20000"
        # Genuine overlap (2026-06-02..2026-06-04 overlaps the first stay) is rejected.
        resp_ovl = api.create_expense_line(
            {
                "report_id": report["id"], "line_type": "LODGING",
                "claimed_amount_cents": 20000,
                "check_in_date": "2026-06-02", "check_out_date": "2026-06-04",
            },
            env["traveler_headers"],
        )
        validate_error(resp_ovl, ApiErrorId.ERR_LODGING_OVERLAP.value)

    def test_separated_lodging_stays_allowed(self, api):
        """PRD §3.4: "their stays are compared on the half-open interval from
        check_in_date up to but not including check_out_date, so two stays where one's
        check_out_date equals the next one's check_in_date are adjacent and permitted,
        while any genuine overlap is rejected with ERR_LODGING_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/lodging_nights_half_open_adjacent_allowed
        """
        env = setup_base_env(lodging_cap_cents=20000)
        trip = create_approved_trip(env, budget_total_cents=100000,
                                    start_date="2026-06-01", end_date="2026-06-08")
        report = create_report(env, trip, title="Lodging Sep Rpt")
        add_lodging_line(env, report, claimed_amount_cents=20000,
                         check_in_date="2026-06-01", check_out_date="2026-06-02")
        # A stay with a clear gap (06-04..06-05) does not overlap the first (06-01..06-02).
        resp = api.create_expense_line(
            {
                "report_id": report["id"], "line_type": "LODGING",
                "claimed_amount_cents": 20000,
                "check_in_date": "2026-06-04", "check_out_date": "2026-06-05",
            },
            env["traveler_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["reimbursable_amount_cents"] == 20000, "non-overlapping 1-night stay is allowed"
