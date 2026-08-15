"""Sale scheduling guards, venue occupancy, postponements, and conduct gating."""
from test_helpers import (
    AUCT,
    CM,
    ApiErrorId,
    assert_instant_equals,
    assert_postponement,
    create_postponement_payload,
    file_affidavit,
    file_stay,
    get_case,
    postpone_sale,
    record_nots,
    record_publication,
    release_stay,
    schedule_sale,
    set_clock,
    setup_case_at_publication_complete,
    setup_case_at_sale_scheduled,
    setup_case_with_nod,
    add_bidding_instruction,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVenueHalfOpenOccupancy:
    def _two_publication_complete_cases(self, api):
        ctx_a = setup_case_at_publication_complete("BEN-O1A",
                                                   loan_reference="LN-O1A")
        ctx_b = setup_case_at_publication_complete("BEN-O1B",
                                                   loan_reference="LN-O1B")
        sale_a = schedule_sale(ctx_a["nots"]["id"], venue_name="VEN-O1",
                               scheduled_sale_start_at="2026-11-23T10:00:00Z")
        return ctx_a, ctx_b, sale_a

    def test_overlapping_start_rejected(self, api):
        """PRD §3.8: "A sale occupies its venue for a half-open interval of sixty minutes beginning at its start — the start instant itself is occupied, the instant exactly sixty minutes later is not — and a schedule attempt conflicts, surfacing `ERR_AUCTION_SCHEDULE_CONFLICT` (HTTP 409), whenever another sale with the same `venue_name` in `SCHEDULED` or `CONDUCTED` status has an occupancy interval intersecting the requested one; two sales where one ends exactly as the other begins do not conflict."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_window_overlap
        """
        _ctx_a, ctx_b, _sale_a = self._two_publication_complete_cases(api)
        resp = api.schedule_sale(
            ctx_b["nots"]["id"],
            {"venue_name": "VEN-O1",
             "scheduled_sale_start_at": "2026-11-23T10:30:00Z"},
            CM,
        )
        # 10:30 falls inside the first sale's [10:00, 11:00) occupancy.
        validate_error(resp, ApiErrorId.ERR_AUCTION_SCHEDULE_CONFLICT, 409)

    def test_adjacent_start_accepted(self, api):
        """PRD §3.8: "A sale occupies its venue for a half-open interval of sixty minutes beginning at its start — the start instant itself is occupied, the instant exactly sixty minutes later is not — and a schedule attempt conflicts, surfacing `ERR_AUCTION_SCHEDULE_CONFLICT` (HTTP 409), whenever another sale with the same `venue_name` in `SCHEDULED` or `CONDUCTED` status has an occupancy interval intersecting the requested one; two sales where one ends exactly as the other begins do not conflict."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_window_overlap
        """
        _ctx_a, ctx_b, sale_a = self._two_publication_complete_cases(api)
        sale_b = validate_success(
            api.schedule_sale(
                ctx_b["nots"]["id"],
                {"venue_name": "VEN-O1",
                 "scheduled_sale_start_at": "2026-11-23T11:00:00Z"},
                CM,
            ),
            201,
        )
        assert sale_b["status"] == "SCHEDULED", (
            "starting exactly as the other sale ends is adjacency, not overlap"
        )
        first = validate_success(api.get_auction_sale(sale_a["id"], AUCT), 200)
        assert first["status"] == "SCHEDULED"
        assert_instant_equals(
            first["scheduled_sale_start_at"], "2026-11-23T10:00:00",
            label="first sale start",
        )


class TestPostponementSelfLoop:
    def _scheduled_sale(self, api):
        ctx = setup_case_at_sale_scheduled("BEN-C2", venue_name="VEN-C2",
                                           loan_reference="LN-C2")
        return ctx

    def test_postponement_keeps_sale_scheduled_and_moves_start(self, api):
        """PRD §3.8: "On success the system creates an immutable `Postponement` recording the `auction_sale_id`, the `prior_sale_start_at` captured before the move, the `new_sale_start_at`, the `reason`, and the `announced_via`; the sale's `scheduled_sale_start_at` is updated; the notice's `postponement_count` increments by one; and the sale's `version` increments."

        Design: Difficulty/non_linear_state_machine/auction_postponement_self_loop_cycle
        """
        ctx = self._scheduled_sale(api)
        sale_id = ctx["sale"]["id"]
        postpone_sale(sale_id, "2026-11-25T10:00:00Z")
        postpone_sale(sale_id, "2026-11-30T10:00:00Z",
                      reason="BENEFICIARY_REQUEST", announced_via="AT_SALE")
        sale = validate_success(api.get_auction_sale(sale_id, AUCT), 200)
        assert sale["status"] == "SCHEDULED", (
            f"the self-loop never escapes SCHEDULED, got {sale['status']}"
        )
        assert_instant_equals(
            sale["scheduled_sale_start_at"], "2026-11-30T10:00:00",
            label="sale start after second postponement",
        )

    def test_postponement_increments_count_and_sale_version(self, api):
        """PRD §3.8: "On success the system creates an immutable `Postponement` recording the `auction_sale_id`, the `prior_sale_start_at` captured before the move, the `new_sale_start_at`, the `reason`, and the `announced_via`; the sale's `scheduled_sale_start_at` is updated; the notice's `postponement_count` increments by one; and the sale's `version` increments."
        PRD §2.4: "The `version` is an integer that starts at its initial value on creation and increments by one on every mutation of the resource, including mutations driven by cascades — when a case's `lifecycle_status` advances, when a computed field such as `undistributed_surplus_cents` is recomputed, or when a parent's counters are updated by a child event, the affected resource's `updated_at` refreshes and its `version` increments."

        Design: Difficulty/non_linear_state_machine/auction_postponement_self_loop_cycle
        """
        ctx = self._scheduled_sale(api)
        sale_id = ctx["sale"]["id"]
        v0 = ctx["sale"]["version"]
        postpone_sale(sale_id, "2026-11-25T10:00:00Z")
        postpone_sale(sale_id, "2026-11-30T10:00:00Z")
        sale = validate_success(api.get_auction_sale(sale_id, AUCT), 200)
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 2
        assert sale["version"] == v0 + 2, (
            f"one version bump per postponement: {v0} -> {sale['version']}"
        )


class TestPostponementCountCap:
    def _sale_with_two_postponements(self, api):
        ctx = setup_case_at_sale_scheduled("BEN-B2", venue_name="VEN-B2",
                                           loan_reference="LN-B2")
        sale_id = ctx["sale"]["id"]
        postpone_sale(sale_id, "2026-11-25T10:00:00Z")
        postpone_sale(sale_id, "2026-11-30T10:00:00Z")
        return ctx

    def test_third_postponement_allowed(self, api):
        """PRD §3.8: "the parent notice's `postponement_count` must still be below three — the third postponement is allowed and the fourth is rejected with `ERR_POSTPONEMENT_LIMIT` (HTTP 422);"

        Design: Difficulty/boundary_precision_check/postponement_third_allowed_fourth_rejected
        """
        ctx = self._sale_with_two_postponements(api)
        post3 = postpone_sale(ctx["sale"]["id"], "2026-12-05T10:00:00Z")
        assert_postponement(post3)
        assert_instant_equals(
            post3["new_sale_start_at"], "2026-12-05T10:00:00",
            label="third postponement new start",
        )
        rows, meta = validate_paginated(
            api.list_postponements(ctx["sale"]["id"], AUCT)
        )
        assert meta["total_count"] == 3
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 3

    def test_fourth_postponement_rejected(self, api):
        """PRD §3.8: "the parent notice's `postponement_count` must still be below three — the third postponement is allowed and the fourth is rejected with `ERR_POSTPONEMENT_LIMIT` (HTTP 422);"

        Design: Difficulty/boundary_precision_check/postponement_third_allowed_fourth_rejected
        """
        ctx = self._sale_with_two_postponements(api)
        sale_id = ctx["sale"]["id"]
        postpone_sale(sale_id, "2026-12-05T10:00:00Z")
        v4 = validate_success(api.get_auction_sale(sale_id, AUCT), 200)["version"]
        resp = api.create_postponement(
            sale_id,
            create_postponement_payload("2026-12-10T10:00:00Z", v4),
            AUCT,
        )
        validate_error(resp, ApiErrorId.ERR_POSTPONEMENT_LIMIT, 422)
        _rows, meta = validate_paginated(api.list_postponements(sale_id, AUCT))
        assert meta["total_count"] == 3, "the rejection creates no fourth row"
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 3
        assert nots["status"] == "SALE_SCHEDULED"


class TestStayOverflowCascade:
    def _sale_at_postponement_cap(self, api):
        ctx = setup_case_at_sale_scheduled("BEN-X1", venue_name="VEN-X1",
                                           loan_reference="LN-X1")
        sale_id = ctx["sale"]["id"]
        postpone_sale(sale_id, "2026-11-25T10:00:00Z", reason="MUTUAL_AGREEMENT")
        postpone_sale(sale_id, "2026-11-30T10:00:00Z", reason="MUTUAL_AGREEMENT")
        postpone_sale(sale_id, "2026-12-05T10:00:00Z", reason="MUTUAL_AGREEMENT")
        set_clock("2026-12-04T10:00:00Z")
        return ctx

    def test_stay_filing_overflow_voids_sale_and_notice(self, api):
        """PRD §3.7: "When the notice's `postponement_count` has already reached three, no further postponement is possible; the forced fourth postponement instead voids the machinery — the `SCHEDULED` sale becomes `VOIDED`, the notice of trustee's sale becomes `VOIDED`, and the case rewinds from `SALE_SCHEDULED` to `NOD_RECORDED`, requiring the trustee to re-notice the sale from scratch."

        Design: Difficulty/transitive_cascade/stay_filing_postponement_overflow_cascade
        """
        ctx = self._sale_at_postponement_cap(api)
        stay = file_stay(
            ctx["case"]["id"], stay_type="BANKRUPTCY_CHAPTER_13",
            court_case_number="BK-26-0001", filed_at="2026-12-04T09:00:00Z",
        )
        assert stay["status"] == "ACTIVE"
        sale = validate_success(api.get_auction_sale(ctx["sale"]["id"], AUCT), 200)
        assert sale["status"] == "VOIDED", (
            f"the forced fourth postponement voids the sale, got {sale['status']}"
        )
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["status"] == "VOIDED"

    def test_stay_filing_overflow_rewinds_case_and_keeps_count(self, api):
        """PRD §3.7: "When the notice's `postponement_count` has already reached three, no further postponement is possible; the forced fourth postponement instead voids the machinery — the `SCHEDULED` sale becomes `VOIDED`, the notice of trustee's sale becomes `VOIDED`, and the case rewinds from `SALE_SCHEDULED` to `NOD_RECORDED`, requiring the trustee to re-notice the sale from scratch."
        PRD §2.10: "The posture is `BANKRUPTCY_STAY` whenever any `ACTIVE` stay of a bankruptcy type exists on the case; otherwise `LITIGATION_HOLD` whenever any `ACTIVE` litigation-hold stay exists; otherwise `CLEAR`."

        Design: Difficulty/transitive_cascade/stay_filing_postponement_overflow_cascade
        """
        ctx = self._sale_at_postponement_cap(api)
        file_stay(
            ctx["case"]["id"], stay_type="BANKRUPTCY_CHAPTER_13",
            court_case_number="BK-26-0001", filed_at="2026-12-04T09:00:00Z",
        )
        case = get_case(ctx["case"]["id"])
        assert case["hold_status"] == "BANKRUPTCY_STAY"
        assert case["lifecycle_status"] == "NOD_RECORDED", (
            f"hop 4: the notice void rewinds the case, got {case['lifecycle_status']}"
        )
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 3, "no fourth postponement is created"
        _rows, meta = validate_paginated(
            api.list_postponements(ctx["sale"]["id"], AUCT)
        )
        assert meta["total_count"] == 3


class TestScheduleSaleGates:
    def test_schedule_sale_too_soon_after_first_publication_rejected(self, api):
        """PRD §3.8: "then the scheduled start must be at least twenty days after the notice's `first_publication_date` and at least fourteen days after the notice's `recording_date` — starts on either boundary day are acceptable, and a violation is rejected with `ERR_SALE_DATE_TOO_SOON` (HTTP 422); and the venue must be free."

        Design: Corner/validations/schedule_sale_too_soon_after_first_publication_rejected
        """
        ctx = setup_case_at_publication_complete("BEN-VL1",
                                                 loan_reference="LN-VL1")
        # First publication 2026-11-02 + 20 days == 2026-11-22; 2026-11-20 is too soon.
        resp = api.schedule_sale(
            ctx["nots"]["id"],
            {"venue_name": "VEN-VL1",
             "scheduled_sale_start_at": "2026-11-20T10:00:00Z"},
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_SALE_DATE_TOO_SOON, 422)
        _rows, meta = validate_paginated(
            api.list_auction_sales(
                CM, params={"foreclosure_case_id": ctx["case"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "no sale may be created by the rejection"

    def test_schedule_sale_before_publication_complete_rejected(self, api):
        """PRD §3.8: "then the notice must have completed its publication cycle — scheduling against a notice that has not reached `PUBLICATION_COMPLETE` is rejected with `ERR_PUBLICATION_INCOMPLETE` (HTTP 422);"

        Design: Corner/errors/schedule_sale_before_publication_complete_rejected
        """
        # A notice with three runs but only two affidavits filed.
        ctx = setup_case_with_nod("BEN-ER10", loan_reference="LN-ER10")
        nots = record_nots(ctx["case"]["id"])
        p1 = record_publication(nots["id"], "2026-11-02")
        p2 = record_publication(nots["id"], "2026-11-09")
        record_publication(nots["id"], "2026-11-16")
        file_affidavit(p1["id"])
        file_affidavit(p2["id"])
        resp = api.schedule_sale(
            nots["id"],
            {"venue_name": "VEN-ER10",
             "scheduled_sale_start_at": "2026-11-23T10:00:00Z"},
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_PUBLICATION_INCOMPLETE, 422)

    def test_schedule_sale_rejected_under_active_stay(self, api):
        """PRD §2.10: "A case that is not `CLEAR` may not advance along its sale-side lifecycle. Five operations are gated this way and are rejected with `ERR_ACTIVE_STAY` (HTTP 409) while the case is under hold: recording a notice of default, recording a notice of trustee's sale, scheduling an auction, conducting an auction, and closing an auction."

        Design: Difficulty/cross_entity_state_dependency/schedule_sale_blocked_by_active_litigation_stay
        """
        ctx = setup_case_at_publication_complete("BEN-D1", loan_reference="LN-D1")
        file_stay(ctx["case"]["id"], stay_type="LITIGATION_HOLD",
                  court_case_number="CV-26-0002",
                  filed_at="2026-11-15T09:00:00Z")
        resp = api.schedule_sale(
            ctx["nots"]["id"],
            {"venue_name": "VEN-D1",
             "scheduled_sale_start_at": "2026-11-23T10:00:00Z"},
            CM,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_STAY, 409)

    def test_schedule_sale_succeeds_after_stay_release(self, api):
        """PRD §3.7: "On release the stay becomes `RELEASED`, `released_at` is stamped, the supplied reference is recorded, the case's `hold_status` is recomputed — returning to `CLEAR` when the released stay was the last `ACTIVE` one — and the case's `version` increments."
        PRD §2.10: "A case that is not `CLEAR` may not advance along its sale-side lifecycle. Five operations are gated this way and are rejected with `ERR_ACTIVE_STAY` (HTTP 409) while the case is under hold: recording a notice of default, recording a notice of trustee's sale, scheduling an auction, conducting an auction, and closing an auction."

        Design: Difficulty/cross_entity_state_dependency/schedule_sale_blocked_by_active_litigation_stay
        """
        ctx = setup_case_at_publication_complete("BEN-D1", loan_reference="LN-D1")
        stay = file_stay(ctx["case"]["id"], stay_type="LITIGATION_HOLD",
                         court_case_number="CV-26-0002",
                         filed_at="2026-11-15T09:00:00Z")
        validate_error(
            api.schedule_sale(
                ctx["nots"]["id"],
                {"venue_name": "VEN-D1",
                 "scheduled_sale_start_at": "2026-11-23T10:00:00Z"},
                CM,
            ),
            ApiErrorId.ERR_ACTIVE_STAY,
            409,
        )
        release_stay(stay["id"])
        assert get_case(ctx["case"]["id"])["hold_status"] == "CLEAR"
        sale = validate_success(
            api.schedule_sale(
                ctx["nots"]["id"],
                {"venue_name": "VEN-D1",
                 "scheduled_sale_start_at": "2026-11-23T10:00:00Z"},
                CM,
            ),
            201,
        )
        assert sale["status"] == "SCHEDULED"
        assert get_case(ctx["case"]["id"])["lifecycle_status"] == "SALE_SCHEDULED"


class TestPostponementWindowAndLedgerShape:
    def test_postponement_window_31_days_rejected(self, api):
        """PRD §3.8: "and the new start must be strictly later than the currently scheduled start and no more than thirty days after it, with a start exactly thirty days out permitted — otherwise `ERR_POSTPONEMENT_WINDOW` (HTTP 422)."

        Design: Corner/validations/postponement_window_31_days_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-VL2", venue_name="VEN-VL2",
                                           loan_reference="LN-VL2")
        sale = ctx["sale"]
        resp = api.create_postponement(
            sale["id"],
            create_postponement_payload("2026-12-24T10:00:00Z", sale["version"]),
            AUCT,
        )
        validate_error(resp, ApiErrorId.ERR_POSTPONEMENT_WINDOW, 422)
        after = validate_success(api.get_auction_sale(sale["id"], AUCT), 200)
        assert_instant_equals(
            after["scheduled_sale_start_at"], "2026-11-23T10:00:00",
            label="sale start after rejection",
        )
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 0

    def test_postponement_immutable_no_common_fields(self, api):
        """PRD §2.4: "Two resources are deliberate exceptions to this rule because they are immutable ledger entries: a `Postponement` and a `Bid` are never modified after creation. Each carries only `id` and `created_at`; both `updated_at` and `version` are absent on these two resources."
        PRD §3.8: "On success the system creates an immutable `Postponement` recording the `auction_sale_id`, the `prior_sale_start_at` captured before the move, the `new_sale_start_at`, the `reason`, and the `announced_via`; the sale's `scheduled_sale_start_at` is updated; the notice's `postponement_count` increments by one; and the sale's `version` increments."

        Design: Corner/entities/postponement_immutable_no_common_fields
        """
        ctx = setup_case_at_sale_scheduled("BEN-T6", venue_name="VEN-T6",
                                           loan_reference="LN-T6")
        post = postpone_sale(ctx["sale"]["id"], "2026-11-25T10:00:00Z")
        assert_postponement(post)
        assert_instant_equals(
            post["prior_sale_start_at"], "2026-11-23T10:00:00",
            label="prior_sale_start_at",
        )
        assert_instant_equals(
            post["new_sale_start_at"], "2026-11-25T10:00:00",
            label="new_sale_start_at",
        )

    def test_postponement_stale_sale_version_rejected(self, api):
        """PRD §2.7: "Postponing an auction sale requires `expected_auction_sale_version` to match the sale's current `version`. Successive postponements are legitimate, so the only sound rejection basis is the staleness of the client's view of the sale; a mismatch is rejected with `ERR_STALE_SALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/postponement_stale_sale_version_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-L3", venue_name="VEN-L3",
                                           loan_reference="LN-L3")
        sale = ctx["sale"]
        sv0 = sale["version"]
        validate_success(
            api.create_postponement(
                sale["id"],
                create_postponement_payload(
                    "2026-11-25T10:00:00Z", sv0, reason="BENEFICIARY_REQUEST"
                ),
                AUCT,
            ),
            201,
        )
        resp = api.create_postponement(
            sale["id"],
            create_postponement_payload("2026-11-27T10:00:00Z", sv0),
            AUCT,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SALE_VERSION, 412)
        after = validate_success(api.get_auction_sale(sale["id"], AUCT), 200)
        assert_instant_equals(
            after["scheduled_sale_start_at"], "2026-11-25T10:00:00",
            label="sale start after stale rejection",
        )
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["postponement_count"] == 1


class TestConductGates:
    def test_conduct_on_wrong_date_rejected(self, api):
        """PRD §3.8: "Conducting requires the sale to be `SCHEDULED` (`ERR_INVALID_SALE_STATE`), the case to be in `SALE_SCHEDULED` with `hold_status` of `CLEAR` (`ERR_ACTIVE_STAY`), an `ACTIVE` bidding instruction to exist on the case (without one the sale cannot be cried and the attempt is rejected with `ERR_NO_ACTIVE_BIDDING_INSTRUCTION`, HTTP 422), and the current clock UTC date to equal the calendar date of the sale's `scheduled_sale_start_at` — an attempt on any other day is rejected with `ERR_SALE_NOT_TODAY` (HTTP 422)."

        Design: Corner/errors/conduct_on_wrong_date_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-ER7", venue_name="VEN-ER7",
                                           loan_reference="LN-ER7")
        add_bidding_instruction(ctx["case"]["id"], ctx["beneficiary"]["id"])
        set_clock("2026-11-22T10:30:00Z")
        resp = api.conduct_sale(ctx["sale"]["id"], AUCT)
        validate_error(resp, ApiErrorId.ERR_SALE_NOT_TODAY, 422)
        sale = validate_success(api.get_auction_sale(ctx["sale"]["id"], AUCT), 200)
        assert sale["status"] == "SCHEDULED"

    def test_conduct_without_instruction_rejected(self, api):
        """PRD §3.8: "Conducting requires the sale to be `SCHEDULED` (`ERR_INVALID_SALE_STATE`), the case to be in `SALE_SCHEDULED` with `hold_status` of `CLEAR` (`ERR_ACTIVE_STAY`), an `ACTIVE` bidding instruction to exist on the case (without one the sale cannot be cried and the attempt is rejected with `ERR_NO_ACTIVE_BIDDING_INSTRUCTION`, HTTP 422), and the current clock UTC date to equal the calendar date of the sale's `scheduled_sale_start_at` — an attempt on any other day is rejected with `ERR_SALE_NOT_TODAY` (HTTP 422)."

        Design: Corner/errors/conduct_without_instruction_rejected
        """
        ctx = setup_case_at_sale_scheduled("BEN-ER9", venue_name="VEN-ER9",
                                           loan_reference="LN-ER9")
        set_clock("2026-11-23T10:30:00Z")
        resp = api.conduct_sale(ctx["sale"]["id"], AUCT)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_BIDDING_INSTRUCTION, 422)
        sale = validate_success(api.get_auction_sale(ctx["sale"]["id"], AUCT), 200)
        assert sale["status"] == "SCHEDULED"
        assert sale["opening_bid_cents"] is None, (
            "the opening-bid snapshot is taken only at a successful conduct"
        )
