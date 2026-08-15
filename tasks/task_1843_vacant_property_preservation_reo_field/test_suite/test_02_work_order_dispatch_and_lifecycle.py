"""Work order lifecycle: dispatch, capacity, field execution, QA review, OCC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_work_order_payload
from test_helpers.fixtures import (
    assign_work_order,
    complete_work_order,
    create_work_order,
    set_clock,
    setup_completed_order_with_invoice,
    setup_portfolio,
    start_work_order,
    submit_work_order,
    upload_minimum_photos,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_field_crew_headers,
    make_quality_reviewer_headers,
    make_servicer_headers,
)

ADMIN = TEST_USERS["vendor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
QA = TEST_USERS["quality_reviewer_headers"]


def _securing_order_in_progress(ctx, hash_prefix="sec"):
    """SECURING work order assigned, started, with the full minimum photo set."""
    wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                           order_type="SECURING", due_date="2026-08-20")
    assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
    start_work_order(wo["id"], ctx["crew_id"])
    upload_minimum_photos(wo["id"], "SECURING", ctx["crew_id"], hash_prefix=hash_prefix)
    return wo


class TestReworkCycle:
    def test_rework_cycle_counts_two_rejections(self, api):
        """PRD: "Rejection returns the order to the crew — `SUBMITTED → IN_PROGRESS`
        — with a mandatory `reason`; the order's `rework_count` increments by one and
        its `submitted_cost_cents` resets to null, so the rework loop from
        `IN_PROGRESS` through `SUBMITTED` and back is cyclic and may repeat."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000})
        wo = _securing_order_in_progress(ctx)
        submit_work_order(wo["id"], ctx["crew_id"], 4000)
        r1 = validate_success(api.reject_work_order(wo["id"], {"reason": "lock photo blurry"}, QA))
        assert r1["status"] == "IN_PROGRESS" and r1["rework_count"] == 1
        submit_work_order(wo["id"], ctx["crew_id"], 4500)
        r2 = validate_success(api.reject_work_order(
            wo["id"], {"reason": "missing serial close-up detail"}, QA))
        assert r2["status"] == "IN_PROGRESS", f"second rejection returns to IN_PROGRESS, got {r2['status']}"
        assert r2["rework_count"] == 2, f"two rejection loops counted, got {r2['rework_count']}"
        assert r2["submitted_cost_cents"] is None, "rejection resets submitted_cost_cents to null"

    def test_rework_cycle_final_submission_cost_approved(self, api):
        """PRD: "on success sets `approved_cost_cents`: the declared
        `submitted_cost_cents`, unless the order's `bid_id` links an `APPROVED` bid
        whose `amount_cents` is lower" and "the rework loop from `IN_PROGRESS`
        through `SUBMITTED` and back is cyclic and may repeat."

        Design: Difficulty/non_linear_state_machine/work_order_rework_cycle
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000})
        wo = _securing_order_in_progress(ctx)
        submit_work_order(wo["id"], ctx["crew_id"], 4000)
        api.reject_work_order(wo["id"], {"reason": "lock photo blurry"}, QA)
        submit_work_order(wo["id"], ctx["crew_id"], 4500)
        api.reject_work_order(wo["id"], {"reason": "missing serial close-up detail"}, QA)
        submit_work_order(wo["id"], ctx["crew_id"], 4800)
        final = validate_success(api.approve_work_order(wo["id"], QA))
        assert final["status"] == "APPROVED", f"third submission approved, got {final['status']}"
        assert final["approved_cost_cents"] == 4800, (
            f"approved cost is the latest resubmission 4800, got {final['approved_cost_cents']}")
        assert final["rework_count"] == 2


class TestPhotoCompletenessBoundary:
    def test_photo_minimum_exact_count_passes(self, api):
        """PRD: "`SECURING` requires two `BEFORE`, one `DURING`, two `AFTER`, and one
        `SERIAL_NUMBER`" and "Meeting a minimum exactly passes." and "While those
        counts are all met by unflagged photos, the order's computed
        `evidence_complete` reads true".

        Design: Difficulty/boundary_precision_check/photo_minimum_exact_count
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000})
        wo = _securing_order_in_progress(ctx, hash_prefix="exact")
        resp = api.submit_work_order(wo["id"], {"submitted_cost_cents": 1000},
                                     make_field_crew_headers(ctx["crew_id"]))
        submitted = validate_success(resp)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["evidence_complete"] is True, "exact minimum counts satisfy the gate"

    def test_photo_minimum_one_short_fails(self, api):
        """PRD: "Photographic completeness: the order type's minimum unflagged-photo
        counts must be met, or `ERR_PHOTO_INCOMPLETE`."

        Design: Difficulty/boundary_precision_check/photo_minimum_exact_count
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="SECURING", due_date="2026-08-08")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-03")
        start_work_order(wo["id"], ctx["crew_id"])
        # One short of the AFTER minimum: BEFORE 2, DURING 1, AFTER 1, SERIAL_NUMBER 1
        for category in ["BEFORE", "BEFORE", "DURING", "AFTER", "SERIAL_NUMBER"]:
            resp = api.create_photo_evidence(
                {"work_order_id": wo["id"], "category": category,
                 "taken_at": "2026-08-03T09:00:00Z",
                 "content_hash": f"short-{category}"},
                make_field_crew_headers(ctx["crew_id"]))
            validate_success(resp, expected_status=201)
        resp = api.submit_work_order(wo["id"], {"submitted_cost_cents": 1000},
                                     make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_PHOTO_INCOMPLETE)


class TestSubmitValidationPipeline:
    def test_second_submit_reports_state_error_not_fiscal(self, api):
        """PRD: "Every request passes through a fixed validation pipeline, and the
        order matters: a failure at an earlier stage masks every later stage, so the
        error a caller receives is always the earliest applicable one." PRD: state
        preconditions rank as stage 5 ("The target resource must be in a state that
        permits the requested transition; failures surface as `ERR_INVALID_STATE`")
        while "10. **Fiscal gates.** Over-cap submission without an approved bid,
        disposal authority limits, and line-less invoices fail with
        `ERR_BID_REQUIRED_OVER_CAP`, `ERR_DISPOSAL_AUTHORITY_LIMIT`, or
        `ERR_INVOICE_NO_LINES`".

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
        """
        ctx = setup_portfolio(item_code="GRASS_CUT", allowable_overrides={
            "requires_bid_over_cents": 2000})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="GRASS_CUT", due_date="2026-08-10")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "GRASS_CUT", ctx["crew_id"], hash_prefix="pipe")
        submit_work_order(wo["id"], ctx["crew_id"], 1500)
        resp = api.submit_work_order(wo["id"], {"submitted_cost_cents": 9000},
                                     make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_second_submit_leaves_submission_unchanged(self, api):
        """PRD: "Submission — `IN_PROGRESS → SUBMITTED` — is the crew's declaration
        of finished work" — a `SUBMITTED` order is not in the transition's from-state,
        so the failed second submit mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_fiscal
        """
        ctx = setup_portfolio(item_code="GRASS_CUT", allowable_overrides={
            "requires_bid_over_cents": 2000})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="GRASS_CUT", due_date="2026-08-10")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "GRASS_CUT", ctx["crew_id"], hash_prefix="pipe2")
        submit_work_order(wo["id"], ctx["crew_id"], 1500)
        api.submit_work_order(wo["id"], {"submitted_cost_cents": 9000},
                              make_field_crew_headers(ctx["crew_id"]))
        after = validate_success(api.get_work_order(wo["id"], ADMIN))
        assert after["status"] == "SUBMITTED", f"order stays SUBMITTED, got {after['status']}"
        assert after["submitted_cost_cents"] == 1500, (
            f"original declared cost preserved, got {after['submitted_cost_cents']}")

    def test_submit_negative_cost_returns_invalid_request(self, api):
        """PRD: "carries `submitted_cost_cents`, the crew-declared cost, which must
        be at least zero (`ERR_INVALID_REQUEST`)".

        Design: Corner/validations/submit_negative_cost_returns_invalid_request
        """
        ctx = setup_portfolio(item_code="GRASS_CUT")
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="GRASS_CUT", due_date="2026-08-08")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo["id"], ctx["crew_id"])
        upload_minimum_photos(wo["id"], "GRASS_CUT", ctx["crew_id"], hash_prefix="neg")
        resp = api.submit_work_order(wo["id"], {"submitted_cost_cents": -1},
                                     make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_submit_on_missing_work_order_returns_not_found(self, api):
        """PRD: "Every resource identifier referenced by the path or the body must
        exist, or the request fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/submit_on_missing_work_order_returns_not_found
        """
        resp = api.submit_work_order(NON_EXISTENT_UUID, {"submitted_cost_cents": 1000},
                                     make_field_crew_headers("some-crew"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_submit_over_bid_threshold_rejected(self, api):
        """PRD: "when `submitted_cost_cents` is strictly greater than the order's
        pinned `requires_bid_over_cents`, an `APPROVED` bid must be linked via the
        order's `bid_id`, or the submission is rejected with
        `ERR_BID_REQUIRED_OVER_CAP`; a submitted cost exactly equal to the threshold
        needs no bid."

        Design: Corner/errors/submit_over_bid_threshold_rejected
        """
        ctx = setup_portfolio(item_code="GRASS_CUT", allowable_overrides={
            "max_per_occurrence_cents": 5000, "aggregate_cap_cents_per_property_year": 100000,
            "requires_bid_over_cents": 2000})
        orders = []
        for i, (date, prefix) in enumerate([("2026-08-02", "thr-x"), ("2026-08-03", "thr-y")]):
            wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                                   order_type="GRASS_CUT", due_date="2026-08-08")
            assign_work_order(wo["id"], ctx["crew_id"], scheduled_date=date)
            start_work_order(wo["id"], ctx["crew_id"])
            upload_minimum_photos(wo["id"], "GRASS_CUT", ctx["crew_id"],
                                  date=date, hash_prefix=prefix)
            orders.append(wo)
        at_threshold = api.submit_work_order(orders[0]["id"], {"submitted_cost_cents": 2000},
                                             make_field_crew_headers(ctx["crew_id"]))
        assert validate_success(at_threshold)["status"] == "SUBMITTED", (
            "cost equal to the threshold needs no bid")
        over = api.submit_work_order(orders[1]["id"], {"submitted_cost_cents": 2001},
                                     make_field_crew_headers(ctx["crew_id"]))
        validate_error(over, ApiErrorId.ERR_BID_REQUIRED_OVER_CAP)


class TestDispatchAndExistence:
    def test_assign_with_missing_crew_returns_not_found(self, api):
        """PRD: "Every resource identifier referenced by the path or the body must
        exist, or the request fails with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/assign_with_missing_crew_returns_not_found
        """
        ctx = setup_portfolio(item_code="INSPECTION", allowable_overrides={
            "max_per_occurrence_cents": 5000, "max_occurrences_per_calendar_year": 30,
            "aggregate_cap_cents_per_property_year": 100000})
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="INSPECTION", due_date="2026-08-09")
        resp = api.assign_work_order(wo["id"], {"crew_id": NON_EXISTENT_UUID,
                                                "scheduled_date": "2026-08-03"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_start_by_other_crew_rejected(self, api):
        """PRD: "The starter's `X-User-ID` must equal the order's `assigned_crew_id`
        (`ERR_NOT_ASSIGNED_CREW`)".

        Design: Corner/errors/start_by_other_crew_rejected
        """
        ctx = setup_portfolio(item_code="INSPECTION", allowable_overrides={
            "max_per_occurrence_cents": 5000, "max_occurrences_per_calendar_year": 30,
            "aggregate_cap_cents_per_property_year": 100000})
        other_crew = validate_success(api.create_crew({"name": "Other", "crew_code": "CR-OTHER"}, ADMIN),
                                      expected_status=201)
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="INSPECTION", due_date="2026-08-09")
        assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-03")
        resp = api.start_work_order(wo["id"], make_field_crew_headers(other_crew["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_CREW)


class TestCrewDayCapacity:
    def _setup_two_of_two_assigned(self, api):
        ctx = setup_portfolio(item_code="INSPECTION",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 5000,
                                  "max_occurrences_per_calendar_year": 30,
                                  "aggregate_cap_cents_per_property_year": 100000},
                              crew_overrides={"daily_capacity_jobs": 2})
        orders = []
        for _ in range(3):
            wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                                   order_type="INSPECTION", due_date="2026-08-12")
            orders.append(wo)
        a1 = assign_work_order(orders[0]["id"], ctx["crew_id"], scheduled_date="2026-08-05")
        assign_work_order(orders[1]["id"], ctx["crew_id"], scheduled_date="2026-08-05")
        return ctx, orders, a1

    def test_crew_day_capacity_full_date_rejected(self, api):
        """PRD: "with `ERR_CREW_DAY_CAPACITY` when the target crew already has a count
        of work orders in `ASSIGNED` or `IN_PROGRESS` on that calendar date equal to
        or greater than its `daily_capacity_jobs`; the calendar date is the whole
        bucket — there is no per-slot geometry."

        Design: Difficulty/resource_temporal_overlap/crew_day_aggregate_capacity
        """
        ctx, orders, _a1 = self._setup_two_of_two_assigned(api)
        resp = api.assign_work_order(orders[2]["id"], {"crew_id": ctx["crew_id"],
                                                       "scheduled_date": "2026-08-05"}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CREW_DAY_CAPACITY)

    def test_crew_day_capacity_frees_on_move(self, api):
        """PRD: "Reassignment is the dispatch correction path: `ASSIGNED → ASSIGNED`
        with a new `crew_id` and `scheduled_date`. It repeats the capacity check
        against the new date" — after one order moves off the full date, the bucket
        has room again.

        Design: Difficulty/resource_temporal_overlap/crew_day_aggregate_capacity
        """
        ctx, orders, a1 = self._setup_two_of_two_assigned(api)
        api.assign_work_order(orders[2]["id"], {"crew_id": ctx["crew_id"],
                                                "scheduled_date": "2026-08-05"}, DISPATCHER)
        moved = validate_success(api.reassign_work_order(
            orders[0]["id"],
            {"crew_id": ctx["crew_id"], "scheduled_date": "2026-08-06",
             "expected_work_order_version": a1["version"]},
            DISPATCHER))
        assert moved["scheduled_date"] == "2026-08-06"
        resp = api.assign_work_order(orders[2]["id"], {"crew_id": ctx["crew_id"],
                                                       "scheduled_date": "2026-08-05"}, DISPATCHER)
        assert validate_success(resp)["status"] == "ASSIGNED", (
            "freed bucket admits the third order")

    def test_occ_reassign_stale_version_rejected(self, api):
        """PRD: "If the work order's current `version` no longer equals that value —
        because the order has been mutated since the dispatcher's last read — the
        reassignment is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_reassign_stale_version_rejected
        """
        ctx = setup_portfolio(item_code="INSPECTION",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 5000,
                                  "max_occurrences_per_calendar_year": 30,
                                  "aggregate_cap_cents_per_property_year": 100000})
        crew2 = validate_success(api.create_crew({"name": "Crew Two", "crew_code": "CR-TWO"}, ADMIN),
                                 expected_status=201)
        wo = create_work_order(ctx["property_id"], ctx["servicer_id"],
                               order_type="INSPECTION", due_date="2026-08-12")
        assigned = assign_work_order(wo["id"], ctx["crew_id"], scheduled_date="2026-08-03")
        observed_version = assigned["version"]
        first = validate_success(api.reassign_work_order(
            wo["id"], {"crew_id": crew2["id"], "scheduled_date": "2026-08-04",
                       "expected_work_order_version": observed_version}, DISPATCHER))
        assert first["version"] == observed_version + 1, "first reassign bumps the version"
        replay = api.reassign_work_order(
            wo["id"], {"crew_id": ctx["crew_id"], "scheduled_date": "2026-08-05",
                       "expected_work_order_version": observed_version}, DISPATCHER)
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)


class TestQualityReviewAndTerminalLockdown:
    def test_approve_with_flagged_photo_rejected(self, api):
        """PRD: "Approval — `SUBMITTED → APPROVED` — is blocked while any linked
        photo remains flagged and uncleared (`ERR_PHOTO_FLAGGED_OPEN`)" and
        "Clearing a flag is likewise a `QualityReviewer` action, but segregation of
        duties forbids self-clearance".

        Design: Corner/errors/approve_with_flagged_photo_rejected
        """
        ctx = setup_portfolio(item_code="LOCK_CHANGE", allowable_overrides={
            "max_per_occurrence_cents": 20000, "max_occurrences_per_calendar_year": 4,
            "aggregate_cap_cents_per_property_year": 80000})
        wo = _securing_order_in_progress(ctx, hash_prefix="flag")
        photos = validate_paginated(
            api.list_photo_evidence(ADMIN, params={"work_order_id": wo["id"]}))[0]
        after_photo = [p for p in photos if p["category"] == "AFTER"][0]
        submit_work_order(wo["id"], ctx["crew_id"], 4000)
        qa1 = make_quality_reviewer_headers("qa-1")
        qa2 = make_quality_reviewer_headers("qa-2")
        validate_success(api.flag_photo(after_photo["id"], {"reason": "blurry"}, qa1))
        blocked = api.approve_work_order(wo["id"], qa2)
        validate_error(blocked, ApiErrorId.ERR_PHOTO_FLAGGED_OPEN)
        validate_success(api.clear_photo_flag(after_photo["id"], qa2))
        approved = validate_success(api.approve_work_order(wo["id"], qa2))
        assert approved["status"] == "APPROVED", "approval succeeds once the flag is cleared"

    def test_work_order_cancel_from_completed_returns_invalid_state(self, api):
        """PRD: "A `Servicer` may cancel an order in `ISSUED`, `ASSIGNED`, or
        `IN_PROGRESS`" and "The target resource must be in a state that permits the
        requested transition; failures surface as `ERR_INVALID_STATE`".

        Design: Corner/state_machines/work_order_cancel_from_completed_returns_invalid_state
        """
        ctx = setup_completed_order_with_invoice(order_type="GRASS_CUT", add_line=False)
        resp = api.cancel_work_order(ctx["work_order_id"], {"reason": "too late"},
                                     make_servicer_headers(ctx["servicer_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWorkOrderListing:
    def test_work_orders_list_filter_and_pagination(self, api):
        """PRD: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`." and "The work order list endpoint filters by `property_id`".

        Design: Corner/endpoints/work_orders_list_filter_and_pagination
        """
        ctx = setup_portfolio(item_code="INSPECTION",
                              allowable_overrides={
                                  "max_per_occurrence_cents": 5000,
                                  "max_occurrences_per_calendar_year": 30,
                                  "aggregate_cap_cents_per_property_year": 100000})
        for day in ("2026-08-07", "2026-08-08", "2026-08-09"):
            create_work_order(ctx["property_id"], ctx["servicer_id"],
                              order_type="INSPECTION", due_date=day)
        page1, meta1 = validate_paginated(api.list_work_orders(
            ADMIN, params={"property_id": ctx["property_id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2, f"limit 2 returns 2 rows, got {len(page1)}"
        assert meta1["total_count"] == 3, f"total_count counts all matches, got {meta1['total_count']}"
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_work_orders(
            ADMIN, params={"property_id": ctx["property_id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1 and meta2["has_more"] is False
        for row in page1 + page2:
            assert row["property_id"] == ctx["property_id"], "filter constrains every returned row"
