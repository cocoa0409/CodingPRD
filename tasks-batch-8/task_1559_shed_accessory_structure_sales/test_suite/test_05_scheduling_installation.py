"""Scheduling, deposit gate, crew whole-day occupancy, and installation state gates
(PRD §3.5)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    setup_book, create_draft_order, submit_site_check, file_report,
    get_order, get_only_application, approve_application,
    record_order_payment, drive_order_to_ready, drive_order_to_scheduled,
    create_schedule_payload,
    DEPOSIT_10X12_WINDOW, DEPOSIT_8X8,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
CREW = TEST_USERS["install_crew_headers"]


def _ready_cash_order(api, options=None, width=10, depth=12):
    """10x12 [WINDOW] CASH order in READY_TO_SCHEDULE under the reference rule book."""
    jur, model, cust = setup_book()
    order = create_draft_order(
        cust["id"], model["id"], jur["id"], width_ft=width, depth_ft=depth,
        options=options or [],
    )
    drive_order_to_ready(order)
    return get_order(order["id"])


class TestDepositExactBoundary:
    def test_exact_deposit_allows_schedule(self, api):
        """PRD §3.5: "a `CASH` order may not be scheduled until `collected_cents` reaches
        at least twenty percent of `quoted_total_cents`, rounded half-up to whole cents —
        the boundary is inclusive, and a shortfall is rejected with
        `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."
        PRD §3.5: "A successful booking records the date and crew on the order, moves it
        from `READY_TO_SCHEDULE` to `SCHEDULED`, and increments its `version`."

        Design: Difficulty/boundary_precision_check/deposit_exact_boundary_allows_schedule
        """
        order = _ready_cash_order(api, options=["WINDOW"])  # quoted 601490
        record_order_payment(order["id"], DEPOSIT_10X12_WINDOW, "dep-exact")  # 120298
        res = api.schedule_order(
            order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
        )
        scheduled = validate_success(res, 200)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["scheduled_date"] == "2026-08-10"
        assert scheduled["crew_id"] == "crew-1"

    def test_one_cent_above_boundary_also_schedules(self, api):
        """PRD §3.5: "a `CASH` order may not be scheduled until `collected_cents` reaches
        at least twenty percent of `quoted_total_cents`, rounded half-up to whole cents —
        the boundary is inclusive, and a shortfall is rejected with
        `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/deposit_exact_boundary_allows_schedule
        """
        order = _ready_cash_order(api, options=["WINDOW"])
        record_order_payment(order["id"], DEPOSIT_10X12_WINDOW + 1, "dep-plus")  # 120299
        res = api.schedule_order(
            order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
        )
        assert validate_success(res, 200)["status"] == "SCHEDULED"


def test_deposit_one_cent_short_rejected(api):
    """PRD §3.5: "Then the money: a `CASH` order may not be scheduled until
    `collected_cents` reaches at least twenty percent of `quoted_total_cents`, rounded
    half-up to whole cents — the boundary is inclusive, and a shortfall is rejected with
    `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402)."

    Design: Corner/validations/deposit_insufficient_rejected
    """
    order = _ready_cash_order(api, options=["WINDOW"])
    record_order_payment(order["id"], DEPOSIT_10X12_WINDOW - 1, "dep-short")  # 120297
    res = api.schedule_order(
        order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
    )
    validate_error(res, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT, expected_status=402)
    assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"


def test_schedule_date_in_past_rejected(api):
    """PRD §3.5: "Then the calendar: a `scheduled_date` before the current logical date
    is rejected with `ERR_DATE_IN_PAST`."
    PRD §2.6: "The server maintains a logical clock whose startup value is exactly
    `2026-08-01T00:00:00Z`"

    Design: Corner/validations/schedule_date_in_past_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    drive_order_to_ready(order)  # 8x8 = 64 < 120: NOT_REQUIRED auto-advance
    record_order_payment(order["id"], DEPOSIT_8X8, "dep-1")
    res = api.schedule_order(
        order["id"], create_schedule_payload("2026-07-01", "crew-1"), SALES
    )
    validate_error(res, ApiErrorId.ERR_DATE_IN_PAST, expected_status=422)
    assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"


class TestScheduleGatedByPermitApproval:
    def _permit_review_with_deposit(self, api):
        jur, model, cust = setup_book()
        order = create_draft_order(
            cust["id"], model["id"], jur["id"], options=["WINDOW"]
        )
        asm = submit_site_check(order["id"])
        file_report(asm["id"])
        record_order_payment(order["id"], DEPOSIT_10X12_WINDOW, "dep-1")
        app = get_only_application(order["id"])
        assert app["status"] == "SUBMITTED"
        return order, app

    def test_schedule_blocked_while_submitted(self, api):
        """PRD §3.5: "From `READY_TO_SCHEDULE`, a `SalesRep` books the build with a
        `scheduled_date` and a `crew_id`."
        PRD §2.8: "**State preconditions** — the target resource must be in a state that
        allows the requested transition (`ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/order_schedule_gated_by_permit_approval
        """
        order, _ = self._permit_review_with_deposit(api)
        res = api.schedule_order(
            order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_order(order["id"])["status"] == "PERMIT_REVIEW"

    def test_approve_unblocks_schedule(self, api):
        """PRD §3.4: "Approval sets `decided_at` from the logical clock and advances the
        order from `PERMIT_REVIEW` to `READY_TO_SCHEDULE`."
        PRD §3.5: "A successful booking records the date and crew on the order, moves it
        from `READY_TO_SCHEDULE` to `SCHEDULED`, and increments its `version`."

        Design: Difficulty/cross_entity_state_dependency/order_schedule_gated_by_permit_approval
        """
        order, app = self._permit_review_with_deposit(api)
        res = api.schedule_order(
            order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        approve_application(app["id"])
        assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"

        scheduled = validate_success(
            api.schedule_order(
                order["id"], create_schedule_payload("2026-08-10", "crew-1"), SALES
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED"


class TestCrewWholeDayOccupancy:
    def _two_ready_orders(self, api):
        jur, model, cust = setup_book()
        o1 = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        drive_order_to_ready(o1)
        record_order_payment(o1["id"], DEPOSIT_10X12_WINDOW, "dep-o1")
        o2 = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
        asm2 = submit_site_check(o2["id"], window_start_hour=14)
        file_report(asm2["id"])
        approve_application(get_only_application(o2["id"])["id"])
        record_order_payment(o2["id"], DEPOSIT_10X12_WINDOW, "dep-o2")
        return o1, o2

    def test_same_day_second_booking_conflicts(self, api):
        """PRD §3.5: "Crew occupancy comes first: if the crew is already committed on
        that calendar date — by another order in `SCHEDULED` or `IN_PROGRESS`, or by a
        service visit in `SCHEDULED` — the booking is rejected with
        `ERR_CREW_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_wholeday_occupancy_conflict
        """
        o1, o2 = self._two_ready_orders(api)
        first = validate_success(
            api.schedule_order(o1["id"], create_schedule_payload("2026-08-10", "crew-9"), SALES),
            200,
        )
        assert first["status"] == "SCHEDULED"
        res = api.schedule_order(
            o2["id"], create_schedule_payload("2026-08-10", "crew-9"), SALES
        )
        validate_error(res, ApiErrorId.ERR_CREW_DATE_CONFLICT, expected_status=409)
        assert get_order(o2["id"])["status"] == "READY_TO_SCHEDULE"

    def test_adjacent_day_booking_succeeds(self, api):
        """PRD §3.5: "Crew occupancy comes first: if the crew is already committed on
        that calendar date — by another order in `SCHEDULED` or `IN_PROGRESS`, or by a
        service visit in `SCHEDULED` — the booking is rejected with
        `ERR_CREW_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crew_wholeday_occupancy_conflict
        """
        o1, o2 = self._two_ready_orders(api)
        validate_success(
            api.schedule_order(o1["id"], create_schedule_payload("2026-08-10", "crew-9"), SALES),
            200,
        )
        res = api.schedule_order(
            o2["id"], create_schedule_payload("2026-08-10", "crew-9"), SALES
        )
        validate_error(res, ApiErrorId.ERR_CREW_DATE_CONFLICT)
        # The adjacent calendar date is free: whole-day occupancy is per date.
        second = validate_success(
            api.schedule_order(o2["id"], create_schedule_payload("2026-08-11", "crew-9"), SALES),
            200,
        )
        assert second["status"] == "SCHEDULED"
        assert second["scheduled_date"] == "2026-08-11"


def test_start_from_ready_rejected(api):
    """PRD §3.5: "Starting moves the order from `SCHEDULED` to `IN_PROGRESS` and
    increments its `version`."
    PRD §2.8: "**State preconditions** — the target resource must be in a state that allows
    the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/order_start_from_ready_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], width_ft=8, depth_ft=8)
    drive_order_to_ready(order)  # NOT_REQUIRED auto-advance; no schedule call made
    res = api.start_order(order["id"], CREW)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_order(order["id"])["status"] == "READY_TO_SCHEDULE"


def test_cancel_from_in_progress_rejected(api):
    """PRD §3.6: "cancelling an order that is `IN_PROGRESS`, `COMPLETED`, or `CLOSED` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_from_in_progress_rejected
    """
    jur, model, cust = setup_book()
    order = create_draft_order(cust["id"], model["id"], jur["id"], options=["WINDOW"])
    scheduled = drive_order_to_scheduled(order, deposit_cents=DEPOSIT_10X12_WINDOW)
    get_success_data(api.start_order(scheduled["id"], CREW))
    res = api.cancel_order(order["id"], {"reason": "too late"}, SALES)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_order(order["id"])
    assert after["status"] == "IN_PROGRESS"
    assert after["refunded_cents"] == 0, "no compensation fired on a rejected cancel"
