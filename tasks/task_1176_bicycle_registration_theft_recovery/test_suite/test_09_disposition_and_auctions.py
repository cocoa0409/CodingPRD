"""Disposition wait, auction scheduling and window rules, auction state guards
(PRD §3.1, §3.7)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    owner_headers,
    create_active_partner_org,
    partner_headers,
    create_intake,
    create_auction_for_intake,
    setup_unclaimed_intake,
    setup_open_auction,
    place_bid,
    create_auction_payload,
    create_recovery_intake_payload,
    create_partner_org_payload,
    create_flagged_report_scenario,
    scan_intake,
    get_auction_version,
    api_client,
    get_success_data,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestDispositionWait:
    def test_disposition_too_early_then_exact_day30(self, api):
        """PRD §3.7: "the current logical time must be at least thirty days after
        the intake's `created_at` (an earlier attempt fails with
        `ERR_DISPOSITION_TOO_EARLY`),"

        Design: Corner/errors/disposition_too_early_then_exact_day30
        """
        set_clock("2026-05-01T00:00:00Z")
        org = create_active_partner_org()
        intake = create_intake(
            org, serial_number_raw="DSP100", found_at="2026-04-30T00:00:00Z",
            appraised_value_cents=50000,
        )
        # Day 29: too early.
        set_clock("2026-05-30T00:00:00Z")
        resp = api.mark_unclaimed(intake["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_DISPOSITION_TOO_EARLY, expected_status=409)
        # Day 30 exactly: the wait is satisfied (inclusive bound).
        set_clock("2026-05-31T00:00:00Z")
        marked = validate_success(api.mark_unclaimed(intake["id"], REGISTRAR))
        assert marked["status"] == "UNCLAIMED", (
            f"at exactly thirty days the marking must succeed, got {marked['status']}"
        )

    def test_mark_unclaimed_blocked_by_active_match(self, api):
        """PRD §3.7: "no match candidate for the intake may remain in `PROPOSED` or
        `NOTIFIED` (otherwise `ERR_INTAKE_HAS_ACTIVE_MATCH`),"

        A PROPOSED match (below the notify threshold, never notified) still blocks
        disposition.

        Design: Corner/state_machines/mark_unclaimed_blocked_by_active_match
        """
        set_clock("2026-05-01T00:00:00Z")
        owner, bicycle, _report = create_flagged_report_scenario(
            owner_email="o1@x.com",
            bicycle_overrides={
                "serial_number": "NOM100", "manufacturer": "Trek", "model": "FX",
                "primary_color": "Black", "declared_value_cents": 60000,
            },
            report_overrides={"occurred_at": "2026-05-10T00:00:00Z"},
        )
        org = create_active_partner_org()
        # Unrelated serial/mfr/color: screening far below 7000 -> PROPOSED.
        intake = create_intake(
            org, serial_number_raw="ZZZ000", primary_color="Pink",
            found_at="2026-04-30T00:00:00Z", appraised_value_cents=30000,
            manufacturer="Huffy",
        )
        scan_intake(intake["id"], partner_headers(org))
        set_clock("2026-06-01T00:00:00Z")
        resp = api.mark_unclaimed(intake["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INTAKE_HAS_ACTIVE_MATCH, expected_status=409)


class TestPartnerPosture:
    def test_partner_pending_org_intake_rejected(self, api):
        """PRD §3.1: "Intaking a recovered bicycle, running a match scan,
        completing a return handoff, and manually flagging a duplicate pair all
        require the acting partner's organization to be `ACTIVE`; an attempt from
        a `PENDING`, `SUSPENDED`, or `REVOKED` organization is rejected with
        `ERR_PARTNER_ORG_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/errors/partner_pending_org_intake_rejected
        """
        org = get_success_data(
            api_client.create_partner_org(
                create_partner_org_payload(),
                ADMIN,
            )
        )  # org stays PENDING — never activated
        resp = api.create_recovery_intake(
            create_recovery_intake_payload(
                serial_number_raw="PND100", found_at="2026-04-30T00:00:00Z",
                appraised_value_cents=50000,
            ),
            partner_headers(org),
        )
        validate_error(resp, ApiErrorId.ERR_PARTNER_ORG_NOT_ACTIVE, expected_status=409)


class TestAuctionScheduling:
    def test_auction_read_exposes_computed_reserve_and_estimates(self, api):
        """PRD §3.7: "The `reserve_price_cents` is the larger of 1000 cents and
        twenty percent of the intake's `appraised_value_cents` rounded half-up."
        PRD §3.7: "with a reserve of 20000 cents and a scheduled end forty days
        after intake, the estimate projects a partner payout of 13275 cents."

        Design: Corner/endpoints/auction_read_exposes_computed_reserve_and_estimates
        """
        _org, intake = setup_unclaimed_intake(serial="CMP100", appraised_value_cents=100000)
        auction = create_auction_for_intake(
            intake, starts_at="2026-06-05T00:00:00Z", ends_at="2026-06-10T00:00:00Z"
        )
        read_back = validate_success(api.get_auction(auction["id"], REGISTRAR))
        assert read_back["reserve_price_cents"] == 20000, (
            f"reserve must be max(1000, 0.20*100000) == 20000, got "
            f"{read_back['reserve_price_cents']}"
        )
        assert read_back["estimated_storage_fee_cents"] == 5250, (
            f"35 chargeable days * 150 == 5250, got "
            f"{read_back['estimated_storage_fee_cents']}"
        )
        assert read_back["estimated_program_commission_cents"] == 1475
        assert read_back["estimated_partner_payout_cents"] == 13275, (
            f"estimate payout must be 13275, got "
            f"{read_back['estimated_partner_payout_cents']}"
        )
        assert (
            read_back["estimated_storage_fee_cents"]
            + read_back["estimated_program_commission_cents"]
            + read_back["estimated_partner_payout_cents"]
            == read_back["reserve_price_cents"]
        ), "estimate waterfall must conserve the reserve gross"

    def test_second_auction_same_intake_rejected(self, api):
        """PRD §3.7: "Exactly one non-`CANCELLED` auction may exist per intake —
        and this `ERR_AUCTION_ALREADY_EXISTS` check is deliberately evaluated
        before the intake's state check, so the constraint error surfaces even when
        a previous scheduling has already moved the intake on to
        `DISPOSITION_SCHEDULED`."

        Design: Corner/errors/second_auction_same_intake_rejected
        """
        _org, intake = setup_unclaimed_intake(serial="AEX100", appraised_value_cents=50000)
        create_auction_for_intake(intake)
        resp = api.create_auction(
            create_auction_payload(
                intake["id"],
                starts_at="2026-07-05T00:00:00Z",
                ends_at="2026-07-10T00:00:00Z",
            ),
            REGISTRAR,
        )
        validate_error(resp, ApiErrorId.ERR_AUCTION_ALREADY_EXISTS, expected_status=409)

    def test_auction_window_conflict_scoped_per_partner_org(self, api):
        """PRD §3.7: "the new auction's window, inflated by twelve hours on each
        side, must not overlap any other non-`CANCELLED` auction belonging to the
        same partner organization, or scheduling fails with
        `ERR_AUCTION_WINDOW_CONFLICT`."

        An identical window under a DIFFERENT partner organization is outside the
        rule's scope and schedules successfully.

        Design: Difficulty/resource_temporal_overlap/auction_window_buffer_inflated_overlap
        """
        org_a = create_active_partner_org(
            name="PD A", jurisdiction_code="A", contact_email="a@x.gov"
        )
        org_b = create_active_partner_org(
            name="PD B", jurisdiction_code="B", contact_email="b@x.gov"
        )
        set_clock("2026-05-01T00:00:00Z")
        intake_a = create_intake(org_a, serial_number_raw="BUF101", appraised_value_cents=50000)
        intake_b = create_intake(org_b, serial_number_raw="BUF102", appraised_value_cents=50000)
        set_clock("2026-06-01T00:00:00Z")
        get_success_data(api.mark_unclaimed(intake_a["id"], REGISTRAR))
        get_success_data(api.mark_unclaimed(intake_b["id"], REGISTRAR))
        create_auction_for_intake(
            intake_a, starts_at="2026-06-10T00:00:00Z", ends_at="2026-06-12T00:00:00Z"
        )
        # Same window, different partner org: no conflict.
        auction_b = validate_success(
            api.create_auction(
                create_auction_payload(
                    intake_b["id"],
                    starts_at="2026-06-10T00:00:00Z",
                    ends_at="2026-06-12T00:00:00Z",
                ),
                REGISTRAR,
            ),
            expected_status=201,
        )
        assert auction_b["status"] == "SCHEDULED"

    def test_storage_free_days_boundary_via_estimate(self, api):
        """PRD §3.7: "The first five days after intake creation are free:
        chargeable days are the whole 86400-second days elapsed between the
        intake's `created_at` and the cutoff, minus five, never below zero — so at
        exactly five days elapsed the chargeable count is zero. Each chargeable day
        costs 150 cents,"

        Design: Corner/calculations/storage_free_days_boundary_via_estimate
        """
        org_a = create_active_partner_org(
            name="PD A", jurisdiction_code="A", contact_email="a@x.gov"
        )
        org_b = create_active_partner_org(
            name="PD B", jurisdiction_code="B", contact_email="b@x.gov"
        )
        set_clock("2026-05-01T00:00:00Z")
        intake_a = create_intake(org_a, serial_number_raw="STG001", appraised_value_cents=100000)
        intake_b = create_intake(org_b, serial_number_raw="STG002", appraised_value_cents=100000)
        set_clock("2026-06-01T00:00:00Z")
        get_success_data(api.mark_unclaimed(intake_a["id"], REGISTRAR))
        get_success_data(api.mark_unclaimed(intake_b["id"], REGISTRAR))
        # ends_at exactly 5 days after intake creation: chargeable days == 0.
        auction_a = create_auction_for_intake(
            intake_a, starts_at="2026-05-02T00:00:00Z", ends_at="2026-05-06T00:00:00Z"
        )
        assert auction_a["estimated_storage_fee_cents"] == 0, (
            f"exactly five days elapsed must accrue zero, got "
            f"{auction_a['estimated_storage_fee_cents']}"
        )
        # ends_at 6 days after: the first chargeable day costs 150.
        auction_b = create_auction_for_intake(
            intake_b, starts_at="2026-05-02T00:00:00Z", ends_at="2026-05-07T00:00:00Z"
        )
        assert auction_b["estimated_storage_fee_cents"] == 150, (
            f"six days elapsed must accrue one chargeable day (150), got "
            f"{auction_b['estimated_storage_fee_cents']}"
        )


class TestAuctionStateGuards:
    def test_open_before_starts_rejected(self, api):
        """PRD §3.7: "Opening the bidding requires the auction to be `SCHEDULED`,
        the current logical time to have reached `starts_at` (otherwise
        `ERR_AUCTION_NOT_YET_OPEN`),"

        Design: Corner/errors/open_before_starts_rejected
        """
        _org, intake = setup_unclaimed_intake(serial="NYO100", appraised_value_cents=50000)
        auction = create_auction_for_intake(intake)
        set_clock("2026-06-01T00:00:00Z")  # before starts_at 2026-06-05
        resp = api.open_auction(auction["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_YET_OPEN, expected_status=409)

    def test_close_before_ends_rejected(self, api):
        """PRD §3.7: "Closing is a registrar action requiring the auction to be
        `OPEN` and the current logical time to be at or past `ends_at` (otherwise
        `ERR_AUCTION_NOT_CLOSABLE`)."

        Design: Corner/errors/close_before_ends_rejected
        """
        scenario = setup_open_auction(serial="CLS100", appraised_value_cents=50000)
        set_clock("2026-06-07T00:00:00Z")  # mid-window, before ends_at 2026-06-10
        resp = api.close_auction(scenario["auction"]["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_CLOSABLE, expected_status=409)

    def test_settle_from_open_rejected(self, api):
        """PRD §3.7: "Settlement, again registrar-run, requires `CLOSED` (otherwise
        `ERR_AUCTION_NOT_SETTLABLE`)."

        Design: Corner/errors/settle_from_open_rejected
        """
        scenario = setup_open_auction(serial="STL100", appraised_value_cents=50000)
        set_clock("2026-06-11T00:00:00Z")  # past ends_at, but never closed
        resp = api.settle_auction(scenario["auction"]["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_SETTLABLE, expected_status=409)

    def test_settled_auction_terminal_lockdown_open_rejected(self, api):
        """PRD §3.7: "`SETTLED`, `VOIDED`, and `CANCELLED` are terminal for the
        auction."
        PRD §3.7: "Cancelling from a terminal state fails with
        `ERR_AUCTION_NOT_SETTLABLE`."
        PRD §2.6: "the target entity sits in a state from which the invoked action
        is defined; failures yield the action-specific conflict error" — here
        `ERR_AUCTION_NOT_OPEN` and `ERR_AUCTION_NOT_SETTLABLE`.

        Design: Corner/state_machines/settled_auction_terminal_lockdown_open_rejected
        """
        _org, intake = setup_unclaimed_intake(serial="TLK100", appraised_value_cents=50000)
        auction = create_auction_for_intake(intake)
        validate_success(api.cancel_auction(auction["id"], REGISTRAR))
        resp_open = api.open_auction(auction["id"], REGISTRAR)
        validate_error(resp_open, ApiErrorId.ERR_AUCTION_NOT_OPEN, expected_status=409)
        resp_settle = api.settle_auction(auction["id"], REGISTRAR)
        validate_error(resp_settle, ApiErrorId.ERR_AUCTION_NOT_SETTLABLE, expected_status=409)
        # Cancellation returns the intake to the disposition queue.
        intake_after = validate_success(api.get_recovery_intake(intake["id"], REGISTRAR))
        assert intake_after["status"] == "UNCLAIMED", (
            f"cancel must return the intake to UNCLAIMED, got {intake_after['status']}"
        )

    def test_cancel_open_auction_with_bids_rejected(self, api):
        """PRD §3.7: "From `SCHEDULED` an auction may always be cancelled; from
        `OPEN` cancellation requires that zero bids exist (otherwise
        `ERR_AUCTION_HAS_BIDS`);"

        Design: Corner/errors/cancel_open_auction_with_bids_rejected
        """
        scenario = setup_open_auction(serial="CNB100", appraised_value_cents=100000)
        bidder = register_owner("o1@x.com", "O One")
        place_bid(
            scenario["auction"]["id"], bidder, 20000, scenario["auction_version"]
        )
        resp = api.cancel_auction(scenario["auction"]["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_AUCTION_HAS_BIDS, expected_status=409)
