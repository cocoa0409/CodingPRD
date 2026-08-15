"""Tooling pipeline: stage machine, bath booking (closed intervals + rinse
gap), the bounded retry loop, and the test-pressing stamper gate."""
from test_helpers import (
    ApiErrorId,
    advance_tooling,
    assert_test_pressing,
    assert_tooling_job,
    confirm_order,
    create_order,
    create_queued_order,
    create_release,
    drive_tooling_to_stamper_ready,
    make_customer_headers,
    produce_test_pressing,
    quote_order,
    review_test_pressing,
    setup_world,
    ship_test_pressing,
    start_tooling,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPERATOR


def _order_in_tooling(world, quantity_ordered=500):
    """CONFIRMED order moved to TOOLING; returns (order, round-1 ToolingJob)."""
    order = create_order(world["release"]["id"], quantity_ordered=quantity_ordered)
    order = quote_order(order)
    order = confirm_order(order, world["customer"]["id"])
    job = start_tooling(order["id"])
    return order, job


class TestToolingStageMachine:
    def test_tooling_advance_wrong_stage_rejected(self, api):
        """PRD §3.4: "An advance event that does not match the job's current
        stage is rejected with `ERR_TOOLING_JOB_INVALID_STATE`."

        Design: Corner/state_machines/tooling_advance_wrong_stage_rejected
        """
        world = setup_world(with_line=False)
        _order, job = _order_in_tooling(world)
        assert job["status"] == "QUEUED"

        r1 = api.advance_tooling_job(job["id"], {"event": "CUT_DONE"}, OPERATOR)
        validate_error(r1, ApiErrorId.ERR_TOOLING_JOB_INVALID_STATE)

        r2 = api.advance_tooling_job(job["id"], {"event": "PLATING_DONE"}, OPERATOR)
        validate_error(r2, ApiErrorId.ERR_TOOLING_JOB_INVALID_STATE)

        jobs = validate_success(
            api.list_order_tooling_jobs(_order["id"], OPERATOR), 200
        )
        assert jobs[0]["status"] == "QUEUED"
        assert jobs[0]["attempt_count"] == 0


class TestToolingRetryLoop:
    def test_tooling_retry_auto_requeue_and_booking_release(self, api):
        """PRD §3.4: "A `MARK_FAILED` advance from `CUTTING` or `PLATING` moves
        the job to `FAILED`, increments `attempt_count`, and records the
        operator's `defect_note`; a plating-stage failure additionally releases
        the bath booking, clearing `plating_bath_id`, `plating_start`, and
        `plating_end`. While `attempt_count` remains below 3 the job
        automatically requeues itself `FAILED` → `QUEUED` for another try; a
        third failure leaves the job resting in `FAILED`."

        Design: Difficulty/non_linear_state_machine/tooling_job_retry_loop
        """
        world = setup_world(with_line=False)
        _order, job = _order_in_tooling(world)
        bath_id = world["bath"]["id"]

        # Failure 1 from CUTTING: auto-requeue.
        advance_tooling(job["id"], "START_CUT")
        resp = api.advance_tooling_job(
            job["id"], {"event": "MARK_FAILED", "defect_note": "lacquer skip"},
            OPERATOR,
        )
        after1 = validate_success(resp, 200)
        assert after1["status"] == "QUEUED", (
            f"attempt_count 1 < 3 must auto-requeue to QUEUED, got {after1['status']}"
        )
        assert after1["attempt_count"] == 1

        # Failure 2 from PLATING: auto-requeue and release the bath booking.
        advance_tooling(job["id"], "START_CUT")
        advance_tooling(job["id"], "CUT_DONE")
        advance_tooling(job["id"], "START_PLATING", plating_bath_id=bath_id,
                        plating_start=2, plating_end=6)
        resp2 = api.advance_tooling_job(
            job["id"], {"event": "MARK_FAILED", "defect_note": "bath contamination"},
            OPERATOR,
        )
        after2 = validate_success(resp2, 200)
        assert after2["status"] == "QUEUED"
        assert after2["attempt_count"] == 2
        assert after2["plating_bath_id"] is None, (
            "a plating-stage failure must release the bath booking"
        )

    def test_tooling_third_failure_parks_failed(self, api):
        """PRD §3.4: "While `attempt_count` remains below 3 the job
        automatically requeues itself `FAILED` → `QUEUED` for another try; a
        third failure leaves the job resting in `FAILED`."

        Design: Difficulty/non_linear_state_machine/tooling_job_retry_loop
        """
        world = setup_world(with_line=False)
        _order, job = _order_in_tooling(world)

        for note in ("first", "second"):
            advance_tooling(job["id"], "START_CUT")
            advance_tooling(job["id"], "MARK_FAILED", defect_note=note)

        advance_tooling(job["id"], "START_CUT")
        resp = api.advance_tooling_job(
            job["id"], {"event": "MARK_FAILED", "defect_note": "third strike"},
            OPERATOR,
        )
        after3 = validate_success(resp, 200)
        assert_tooling_job(after3)
        assert after3["status"] == "FAILED", (
            f"the third failure must leave the job resting in FAILED, got {after3['status']}"
        )
        assert after3["attempt_count"] == 3


class TestBathBooking:
    def _two_jobs_awaiting_bath(self, world):
        order1, job1 = _order_in_tooling(world)
        advance_tooling(job1["id"], "START_CUT")
        advance_tooling(job1["id"], "CUT_DONE")
        # second order on a second release of the same customer
        rel2 = create_release(world["customer"]["id"], catalog_number="OV2-002",
                              title="TU2", weight_gram=140)
        order2 = create_order(rel2["id"], quantity_ordered=500)
        order2 = quote_order(order2)
        order2 = confirm_order(order2, world["customer"]["id"])
        job2 = start_tooling(order2["id"])
        advance_tooling(job2["id"], "START_CUT")
        advance_tooling(job2["id"], "CUT_DONE")
        return job1, job2

    def test_bath_touching_endpoint_conflicts(self, api):
        """PRD §3.4: "Bath bookings are closed intervals — both endpoints
        inclusive — and are checked against every other booking on the same
        bath held by a job currently in `PLATING`: if the new booking's start
        falls on or before an existing booking's end while the existing start
        falls on or before the new end, the booking is rejected with
        `ERR_BATH_TIME_CONFLICT`"
        PRD §3.4: "Touching endpoints count as conflicts here"

        Design: Difficulty/resource_temporal_overlap/bath_closed_interval_plus_rinse_gap
        """
        world = setup_world(with_line=False)
        bath_id = world["bath"]["id"]
        job1, job2 = self._two_jobs_awaiting_bath(world)

        plated1 = advance_tooling(job1["id"], "START_PLATING",
                                  plating_bath_id=bath_id,
                                  plating_start=2, plating_end=6)
        assert plated1["status"] == "PLATING"

        # [6,8] touches the closed end hour 6 of [2,6] -> conflict.
        resp = api.advance_tooling_job(
            job2["id"],
            {"event": "START_PLATING", "plating_bath_id": bath_id,
             "plating_start": 6, "plating_end": 8},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BATH_TIME_CONFLICT)

    def test_bath_rinse_gap_boundary(self, api):
        """PRD §3.4: "even without overlap, the new booking must begin no
        earlier than one rinse gap after each existing booking's end, or end no
        later than one rinse gap before each existing booking's start,
        otherwise it is rejected with `ERR_BATH_RINSE_GAP_VIOLATION`. Touching
        endpoints count as conflicts here, and the rinse gap is unconditional —
        it applies after every booking regardless of job type."

        Design: Difficulty/resource_temporal_overlap/bath_closed_interval_plus_rinse_gap
        """
        world = setup_world(with_line=False)  # bath rinse_gap_minutes = 2
        bath_id = world["bath"]["id"]
        job1, job2 = self._two_jobs_awaiting_bath(world)

        advance_tooling(job1["id"], "START_PLATING", plating_bath_id=bath_id,
                        plating_start=2, plating_end=6)

        # 1-hour gap after [2,6] is less than the rinse gap of 2 -> violation.
        resp = api.advance_tooling_job(
            job2["id"],
            {"event": "START_PLATING", "plating_bath_id": bath_id,
             "plating_start": 7, "plating_end": 9},
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_BATH_RINSE_GAP_VIOLATION)

        # Exactly one full rinse gap (8 >= 6 + 2) is allowed.
        plated2 = advance_tooling(job2["id"], "START_PLATING",
                                  plating_bath_id=bath_id,
                                  plating_start=8, plating_end=10)
        assert plated2["status"] == "PLATING", (
            "a booking separated by exactly the rinse gap must be accepted"
        )


class TestTestPressingGate:
    def test_test_pressing_blocked_until_stampers_ready(self, api):
        """PRD §3.4: "Creation requires the order to be in `TOOLING` with its
        latest tooling job in `STAMPER_READY` — otherwise
        `ERR_ORDER_INVALID_STATE` or `ERR_STAMPERS_NOT_READY` respectively"

        Design: Difficulty/cross_entity_state_dependency/test_pressing_gated_by_stamper_ready
        """
        world = setup_world(with_line=False)
        order, job = _order_in_tooling(world)
        advance_tooling(job["id"], "START_CUT")  # job now CUTTING, not ready

        resp = api.create_test_pressing(order["id"], {"quantity": 5}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STAMPERS_NOT_READY)

    def test_test_pressing_created_after_stamper_ready(self, api):
        """PRD §3.4: "With stampers ready, a `PressOperator` produces a test
        pressing of `quantity` between 1 and 20 copies."

        Design: Difficulty/cross_entity_state_dependency/test_pressing_gated_by_stamper_ready
        """
        world = setup_world(with_line=False)
        order, job = _order_in_tooling(world)
        drive_tooling_to_stamper_ready(job["id"], world["bath"]["id"])

        resp = api.create_test_pressing(order["id"], {"quantity": 5}, OPERATOR)
        tp = validate_success(resp, 201)
        assert_test_pressing(tp)
        assert tp["status"] == "PRODUCED"
        assert tp["press_order_id"] == order["id"]


class TestTestPressingReview:
    def test_test_pressing_double_review_rejected(self, api):
        """PRD §3.4: "reviewing a pressing not in `UNDER_REVIEW` is rejected
        with `ERR_TEST_PRESSING_INVALID_STATE`"

        Design: Corner/state_machines/test_pressing_double_review_rejected
        """
        world = setup_world(with_line=False)
        staged = create_queued_order(world, quantity_ordered=100)
        tp = staged["test_pressing"]
        assert tp["status"] == "APPROVED"

        resp = api.review_test_pressing(
            tp["id"], {"decision": "REQUEST_REVISION"},
            make_customer_headers(world["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEST_PRESSING_INVALID_STATE)

        order = validate_success(api.get_press_order(staged["order"]["id"], OPERATOR), 200)
        assert order["production_status"] == "QUEUED", (
            "a rejected re-review must not disturb the order"
        )
