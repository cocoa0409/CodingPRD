"""Auction consignment: nested reserve pricing, closed-interval listing
windows, the relist markdown cycle, sale reporting with per-line fee
rounding, and certification."""
from test_helpers import (
    ApiErrorId,
    certify_sale,
    consign,
    create_auction_house,
    create_borrower,
    create_loan,
    file_complaint,
    get_consignment,
    issue_cure_notice,
    list_consignment,
    list_sale_records,
    make_agent_headers,
    make_auctioneer_headers,
    make_borrower_headers,
    make_compliance_officer_headers,
    open_case,
    parse_instant,
    post_cost,
    report_sale,
    rm_headers,
    set_clock,
    setup_case_consign_pending,
    setup_case_in_auction,
    setup_case_sale_confirmed,
    validate_error,
    validate_success,
)


class TestReservePriceBranches:
    """Nested min/max reserve pricing: the FLOOR branch wins on case A, the
    GRADE branch wins on case B, with identical loans and costs."""

    def _setup_consign_pending(self, api, name, email, vin, trade_in):
        return setup_case_consign_pending(
            borrower_overrides={"full_name": name, "email": email},
            loan_overrides={"vin": vin},
            appraisal_overrides={"odometer": 65_000, "condition_grade": "GOOD",
                                 "trade_in_value_cents": trade_in,
                                 "auction_guide_low_cents": 900_000})

    def test_reserve_price_floor_branch_wins(self, api):
        """PRD §3.6: "The grade-adjusted appraisal is the case's
        `trade_in_value_cents` multiplied by the grade multiplier —
        eighty-five percent for `EXCELLENT`, seventy-five percent for `GOOD`,
        sixty percent for `FAIR`, forty-five percent for `POOR` — rounded half
        up. The floor value is one half of the payoff estimate, where the
        payoff estimate is the loan's `total_outstanding_cents` plus the case's
        recovery-costs total at consignment creation, rounded half up. The
        reserve price then stored in `reserve_price_cents` is the smaller of
        the grade-adjusted appraisal and the larger of the
        `auction_guide_low_cents` and the floor value."

        Design: Difficulty/combinatorial_formula/reserve_price_nested_min_max_grade_branch
        """
        ctx = self._setup_consign_pending(api, "RA", "ra@x.com",
                                          "VIN0000000000000A", 1_500_000)
        house = create_auction_house(name="AH")
        consignment = consign(ctx["case"]["id"], house["id"])
        # grade-adjusted 1,125,000; guide 900,000; floor rhu(0.5 x 2,111,500) = 1,055,750
        # -> min(1,125,000, max(900,000, 1,055,750)) = 1,055,750 (floor branch).
        assert consignment["reserve_price_cents"] == 1_055_750

    def test_reserve_price_grade_branch_wins(self, api):
        """PRD §3.6: "The reserve price then stored in `reserve_price_cents` is
        the smaller of the grade-adjusted appraisal and the larger of the
        `auction_guide_low_cents` and the floor value."
        PRD §3.6: "The grade-adjusted appraisal is the case's
        `trade_in_value_cents` multiplied by the grade multiplier —
        eighty-five percent for `EXCELLENT`, seventy-five percent for `GOOD`,
        sixty percent for `FAIR`, forty-five percent for `POOR` — rounded half
        up."

        Design: Difficulty/combinatorial_formula/reserve_price_nested_min_max_grade_branch
        """
        ctx = self._setup_consign_pending(api, "RB", "rb@x.com",
                                          "VIN0000000000000B", 1_000_000)
        house = create_auction_house(name="AH")
        consignment = consign(ctx["case"]["id"], house["id"])
        # grade-adjusted 750,000; floor 1,055,750 -> min(750,000, 1,055,750) = 750,000
        # (grade branch): identical loan and costs, different appraisal branch.
        assert consignment["reserve_price_cents"] == 750_000


class TestRelistCycle:
    def _setup_listed(self, api, name, email, vin):
        return setup_case_in_auction(
            borrower_overrides={"full_name": name, "email": email},
            loan_overrides={"vin": vin})

    def test_consigngent_relist_recomputes_reserve_with_markdown(self, api):
        """PRD §3.6: "Relisting an `UNSOLD` consignment repeats the same
        ownership, case-state, and window-overlap checks, but the reserve
        softens: before the transition commits, the consignment's
        `reserve_price_cents` is recomputed as the prior reserve multiplied by
        0.95 — a five-percent markdown — rounded half up, and stored; the
        `relist_count` increments by one, the consignment returns to `LISTED`,
        and the case re-enters `IN_AUCTION`."

        Design: Difficulty/non_linear_state_machine/consignment_relist_cycle_with_markdown
        """
        ctx = self._setup_listed(api, "RL", "rl@x.com", "VIN0000000000000D")
        consignment = ctx["consignment"]
        assert consignment["reserve_price_cents"] == 1_055_750

        unsold = validate_success(api.report_unsold(
            consignment["id"], make_auctioneer_headers(ctx["auction_house"]["id"])))
        assert unsold["status"] == "UNSOLD"

        resp = api.relist_consignment(
            consignment["id"],
            {"listing_start": "2026-06-01T00:00:00Z",
             "listing_end": "2026-06-03T00:00:00Z"},
            make_auctioneer_headers(ctx["auction_house"]["id"]))
        relisted = validate_success(resp)
        # round_half_up(1,055,750 x 0.95) = 1,002,963 (half up, not banker's).
        assert relisted["reserve_price_cents"] == 1_002_963
        assert relisted["relist_count"] == 1

    def test_consigngent_relist_completes_state_cycle(self, api):
        """PRD §3.6: "When a vehicle fails to sell, the house reports it: the
        consignment must be `LISTED`, and the report moves it to `UNSOLD` and
        the case back to `CONSIGNMENT_PENDING`."
        PRD §3.6: "the `relist_count` increments by one, the consignment
        returns to `LISTED`, and the case re-enters `IN_AUCTION`."

        Design: Difficulty/non_linear_state_machine/consignment_relist_cycle_with_markdown
        """
        ctx = self._setup_listed(api, "RL", "rl@x.com", "VIN0000000000000D")
        consignment = ctx["consignment"]
        validate_success(api.report_unsold(
            consignment["id"], make_auctioneer_headers(ctx["auction_house"]["id"])))
        case_mid = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_mid["status"] == "CONSIGNMENT_PENDING"

        relisted = validate_success(api.relist_consignment(
            consignment["id"],
            {"listing_start": "2026-06-01T00:00:00Z",
             "listing_end": "2026-06-03T00:00:00Z"},
            make_auctioneer_headers(ctx["auction_house"]["id"])))
        assert relisted["status"] == "LISTED"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "IN_AUCTION"


class TestBidAtReserveBoundary:
    """gross_sale_cents == reserve is accepted; one cent below is rejected."""

    def _setup_two_listed(self, api):
        ctx1 = setup_case_consign_pending(
            borrower_overrides={"full_name": "RA1", "email": "ra1@x.com"},
            loan_overrides={"vin": "VIN00000000000023"})
        ctx2 = setup_case_consign_pending(
            borrower_overrides={"full_name": "RB1", "email": "rb1@x.com"},
            loan_overrides={"vin": "VIN00000000000024"})
        house1 = create_auction_house(name="AH1")
        house2 = create_auction_house(name="AH2")
        consignment1 = consign(ctx1["case"]["id"], house1["id"])
        consignment2 = consign(ctx2["case"]["id"], house2["id"])
        list_consignment(consignment1["id"], house1["id"])
        list_consignment(consignment2["id"], house2["id"])
        set_clock("2026-06-05T00:00:00Z")
        return (ctx1, house1, consignment1), (ctx2, house2, consignment2)

    def test_bid_exactly_at_reserve_accepted(self, api):
        """PRD §3.6: "the bid must meet the reserve: a `gross_sale_cents` below
        the consignment's `reserve_price_cents` is rejected with
        `ERR_BID_BELOW_RESERVE` (HTTP 422), a fiscal check that fires only
        after the consignment's state guard has passed."
        PRD §3.6: "the `auction_fee_cents` is the gross multiplied by the
        house's `fee_bps` and divided by ten thousand, rounded half up; the
        `transport_fee_cents` is a snapshot of the house's flat fee; and the
        `net_proceeds_cents` is the gross minus the auction fee minus the
        transport fee, each fee line rounded to cents individually before the
        subtraction per §2.6."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_reserve
        """
        (ctx1, house1, consignment1), _ = self._setup_two_listed(api)
        assert consignment1["reserve_price_cents"] == 1_055_750
        resp = api.report_sale(
            consignment1["id"], {"gross_sale_cents": 1_055_750},
            make_auctioneer_headers(house1["id"]))
        sale = validate_success(resp, expected_status=201)
        # auction fee rhu(1,055,750 x 0.05) = 52,788; net = 1,055,750 - 52,788 - 15,000.
        assert sale["auction_fee_cents"] == 52_788
        assert sale["transport_fee_cents"] == 15_000
        assert sale["net_proceeds_cents"] == 987_962
        assert sale["status"] == "PENDING_CERTIFICATION"

    def test_bid_one_cent_below_reserve_rejected(self, api):
        """PRD §3.6: "the bid must meet the reserve: a `gross_sale_cents` below
        the consignment's `reserve_price_cents` is rejected with
        `ERR_BID_BELOW_RESERVE` (HTTP 422), a fiscal check that fires only
        after the consignment's state guard has passed."
        PRD §3.6: "At most one non-`VOID` sale record may exist per
        consignment."

        Design: Difficulty/boundary_precision_check/bid_exactly_at_reserve
        """
        _, (ctx2, house2, consignment2) = self._setup_two_listed(api)
        resp = api.report_sale(
            consignment2["id"], {"gross_sale_cents": 1_055_749},
            make_auctioneer_headers(house2["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_RESERVE)
        assert list_sale_records(consignment2["id"]) == [], (
            "a rejected report creates no sale record")


class TestClosedIntervalListingWindows:
    """Auction-house lane calendar uses CLOSED intervals: touching windows
    collide; only a strict gap succeeds."""

    def _setup_two_drafts_same_house(self, api):
        ctx1 = setup_case_consign_pending(
            borrower_overrides={"full_name": "G1", "email": "g1@x.com"},
            loan_overrides={"vin": "VIN00000000000034"})
        ctx2 = setup_case_consign_pending(
            borrower_overrides={"full_name": "G2", "email": "g2@x.com"},
            loan_overrides={"vin": "VIN00000000000035"})
        house = create_auction_house(name="LaneHouse")
        consignment1 = consign(ctx1["case"]["id"], house["id"])
        consignment2 = consign(ctx2["case"]["id"], house["id"])
        list_consignment(consignment1["id"], house["id"],
                         listing_start="2026-05-28T00:00:00Z",
                         listing_end="2026-05-30T00:00:00Z")
        return house, ctx2, consignment2

    def test_auction_listing_touching_windows_rejected(self, api):
        """PRD §3.6: "the new closed window must not touch or overlap any other
        `LISTED` consignment window at the same auction house
        (`ERR_AUCTION_WINDOW_OVERLAP`, HTTP 409; note the contrast with field
        windows: closed-interval adjacency counts as a conflict here)."

        Design: Difficulty/resource_temporal_overlap/auction_listing_closed_interval_gap_required
        """
        house, ctx2, consignment2 = self._setup_two_drafts_same_house(api)
        # [05-30, 06-01] touches the LISTED [05-28, 05-30] at 05-30: collision.
        resp = api.list_consignment(
            consignment2["id"],
            {"listing_start": "2026-05-30T00:00:00Z",
             "listing_end": "2026-06-01T00:00:00Z"},
            make_auctioneer_headers(house["id"]))
        validate_error(resp, ApiErrorId.ERR_AUCTION_WINDOW_OVERLAP)
        assert get_consignment(consignment2["id"])["status"] == "DRAFT"

    def test_auction_listing_strict_gap_accepted(self, api):
        """PRD §3.6: "A successful listing moves the consignment from `DRAFT`
        to `LISTED` and the case from `CONSIGNMENT_PENDING` to `IN_AUCTION`."
        PRD §3.6: "the new closed window must not touch or overlap any other
        `LISTED` consignment window at the same auction house
        (`ERR_AUCTION_WINDOW_OVERLAP`, HTTP 409..."

        Design: Difficulty/resource_temporal_overlap/auction_listing_closed_interval_gap_required
        """
        house, ctx2, consignment2 = self._setup_two_drafts_same_house(api)
        # Strict gap: start 05-31 > prior end 05-30.
        listed = validate_success(api.list_consignment(
            consignment2["id"],
            {"listing_start": "2026-05-31T00:00:00Z",
             "listing_end": "2026-06-02T00:00:00Z"},
            make_auctioneer_headers(house["id"])))
        assert listed["status"] == "LISTED"
        case_after = validate_success(api.get_recovery_case(ctx2["case"]["id"], rm_headers()))
        assert case_after["status"] == "IN_AUCTION"


class TestSaleReportingAndCertification:
    def test_sale_fee_lines_and_net_proceeds(self, api):
        """PRD §3.6: "the `auction_fee_cents` is the gross multiplied by the
        house's `fee_bps` and divided by ten thousand, rounded half up; the
        `transport_fee_cents` is a snapshot of the house's flat fee; and the
        `net_proceeds_cents` is the gross minus the auction fee minus the
        transport fee, each fee line rounded to cents individually before the
        subtraction per §2.6."
        PRD §3.6: "A valid report creates the `SaleRecord` in
        `PENDING_CERTIFICATION` — the consignment itself stays `LISTED` until
        certification"

        Design: Corner/calculations/sale_fee_lines_and_net_proceeds
        """
        ctx = setup_case_in_auction(
            borrower_overrides={"full_name": "SF2", "email": "sf2@x.com"},
            loan_overrides={"vin": "VIN00000000000056"})
        set_clock("2026-06-05T00:00:00Z")
        resp = api.report_sale(
            ctx["consignment"]["id"], {"gross_sale_cents": 1_200_000},
            make_auctioneer_headers(ctx["auction_house"]["id"]))
        sale = validate_success(resp, expected_status=201)
        assert sale["auction_fee_cents"] == 60_000      # rhu(1,200,000 x 500 / 10,000)
        assert sale["transport_fee_cents"] == 15_000    # house's flat fee snapshot
        assert sale["net_proceeds_cents"] == 1_125_000  # 1,200,000 - 60,000 - 15,000
        assert sale["status"] == "PENDING_CERTIFICATION"
        assert get_consignment(ctx["consignment"]["id"])["status"] == "LISTED"

    def test_double_list_rejected_invalid_consignment_state(self, api):
        """PRD §3.6: "Listing requires the consignment in `DRAFT`
        (`ERR_INVALID_CONSIGNMENT_STATE`), the caller to own the consignment
        via `auction_house_id` (`ERR_FORBIDDEN_OWNERSHIP`), the case in
        `CONSIGNMENT_PENDING` (`ERR_INVALID_CASE_STATE`)"

        Design: Corner/state_machines/double_list_rejected_invalid_consignment_state
        """
        ctx = setup_case_in_auction(
            borrower_overrides={"full_name": "DL", "email": "dl@x.com"},
            loan_overrides={"vin": "VIN00000000000081"})
        consignment = ctx["consignment"]
        assert consignment["status"] == "LISTED"
        resp = api.list_consignment(
            consignment["id"],
            {"listing_start": "2026-06-01T00:00:00Z",
             "listing_end": "2026-06-03T00:00:00Z"},
            make_auctioneer_headers(ctx["auction_house"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_CONSIGNMENT_STATE)
        after = get_consignment(consignment["id"])
        assert after["status"] == "LISTED"
        assert parse_instant(after["listing_start"]) == parse_instant("2026-05-28T00:00:00Z"), (
            "the existing window is not overwritten by a rejected list")

    def test_double_certify_rejected_invalid_sale_state(self, api):
        """PRD §3.6: "A `ComplianceOfficer` certifies a record standing in
        `PENDING_CERTIFICATION` (`ERR_INVALID_SALE_STATE` otherwise), on a case
        standing in `IN_AUCTION` (`ERR_INVALID_CASE_STATE`)"
        PRD §3.6: "Certification moves the record to `CERTIFIED`, the
        consignment to `SOLD`, and the case from `IN_AUCTION` to
        `SALE_CONFIRMED`, stamping the case's `sold_at` with the current
        logical time"

        Design: Corner/state_machines/double_certify_rejected_invalid_sale_state
        """
        ctx = setup_case_sale_confirmed(
            borrower_overrides={"full_name": "DC3", "email": "dc3@x.com"},
            loan_overrides={"vin": "VIN00000000000082"})
        sale = ctx["sale"]
        assert sale["status"] == "CERTIFIED"
        resp = api.certify_sale(sale["id"], make_compliance_officer_headers("co_2"))
        validate_error(resp, ApiErrorId.ERR_INVALID_SALE_STATE)
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["status"] == "SALE_CONFIRMED"
        assert parse_instant(case_after["sold_at"]) == parse_instant("2026-06-05T00:00:00Z")


class TestCertifyRequiresCaseInAuction:
    """Cross-entity gate: certification reads the CASE state through
    SaleRecord -> Consignment -> RecoveryCase."""

    def _setup_frozen_pending_sale(self, api):
        ctx = setup_case_in_auction(
            borrower_overrides={"full_name": "XC", "email": "xc@x.com"},
            loan_overrides={"vin": "VIN00000000000026"})
        set_clock("2026-06-05T00:00:00Z")
        sale = report_sale(ctx["consignment"]["id"], ctx["auction_house"]["id"], 1_200_000)
        complaint = file_complaint(ctx["case"]["id"], ctx["borrower"]["id"],
                                   category="NOTICE_DEFECT",
                                   description="cure notice misstated")
        return ctx, sale, complaint

    def test_certify_blocked_when_case_frozen_in_complaint_review(self, api):
        """PRD §3.6: "A `ComplianceOfficer` certifies a record standing in
        `PENDING_CERTIFICATION` (`ERR_INVALID_SALE_STATE` otherwise), on a case
        standing in `IN_AUCTION` (`ERR_INVALID_CASE_STATE`)"
        PRD §3.8: "Filing freezes the case: the case's status at that instant
        is captured verbatim into `pre_complaint_state`, the case moves to
        `COMPLAINT_REVIEW`, and if any consignment of the case is currently
        `LISTED`, that consignment is withdrawn to `WITHDRAWN` in the same
        atomic act."

        Design: Difficulty/cross_entity_state_dependency/certify_requires_case_in_auction
        """
        ctx, sale, _ = self._setup_frozen_pending_sale(api)
        case_frozen = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_frozen["status"] == "COMPLAINT_REVIEW"

        resp = api.certify_sale(sale["id"], make_compliance_officer_headers("co_1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)
        records = [r for r in list_sale_records(ctx["consignment"]["id"]) if r["id"] == sale["id"]]
        assert records[0]["status"] == "PENDING_CERTIFICATION", "rejected certify mutates nothing"

    def test_complaint_freeze_withdraws_listed_consignment(self, api):
        """PRD §3.8: "Filing freezes the case: the case's status at that
        instant is captured verbatim into `pre_complaint_state`, the case moves
        to `COMPLAINT_REVIEW`, and if any consignment of the case is currently
        `LISTED`, that consignment is withdrawn to `WITHDRAWN` in the same
        atomic act."

        Design: Difficulty/cross_entity_state_dependency/certify_requires_case_in_auction
        """
        ctx, sale, _ = self._setup_frozen_pending_sale(api)
        consignment_after = get_consignment(ctx["consignment"]["id"])
        assert consignment_after["status"] == "WITHDRAWN"
        case_after = validate_success(api.get_recovery_case(ctx["case"]["id"], rm_headers()))
        assert case_after["pre_complaint_state"] == "IN_AUCTION"
