"""Booking state machine: initial state, terminal lockdown, time-window gates,
and cross-entity gates on training and completion (PRD §3.3, §3.6–§3.8)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    TEST_USERS, create_usage_log_payload,
    make_researcher_headers,
    setup_canonical_stack, create_booking_request, create_approved_booking,
    approve_booking, run_session_to_completed, set_clock, get_booking,
    get_grant, find_entries, enroll_and_certify,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestBookingInitialState:
    def test_booking_initial_state_and_cancel_free(self, api):
        """PRD §3.6: "A successful creation lands in `REQUESTED`." PRD §3.7:
        "Cancelling a `REQUESTED` booking is always free: `penalty_cents`
        becomes zero." and "Whenever `penalty_cents` exceeds zero, a `PENALTY`
        `RechargeEntry` — with `amount_cents` equal to the penalty,
        `subsidy_offset_cents` zero, and `net_amount_cents` equal to the
        penalty — posts into the currently `OPEN` `RechargeBatch` (none open
        means `ERR_BATCH_NOT_OPEN`), debiting the grant or, for external users,
        accruing to their invoice."

        Design: Corner/state_machines/booking_initial_state_and_cancel_free
        """
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        assert b1["status"] == "REQUESTED"
        # A REQUESTED booking never participates in the grant's encumbrance sum
        # (PRD §2.10 counts only APPROVED / IN_PROGRESS bookings).
        grant = get_grant(stack["g1"]["id"])
        assert grant["budget_encumbered_cents"] == 0

        cancelled = validate_success(
            api.cancel_booking(b1["id"], make_researcher_headers(stack["u1"]["id"])),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["penalty_cents"] == 0, "cancelling REQUESTED is free"
        assert find_entries(booking_id=b1["id"]) == [], (
            "penalty 0 must not post any recharge entry"
        )


class TestTerminalAndTimeWindowGates:
    def test_booking_terminal_completed_lockdown(self, api):
        """PRD §3.7: "`COMPLETED`, `CANCELLED`, `NO_SHOW`, `PREEMPTED`, and
        `REJECTED` are all terminal." PRD §2.9: "State-machine legality
        (`ERR_INVALID_STATE`): the target resource's current state must permit
        the requested transition".

        Design: Corner/state_machines/booking_terminal_completed_lockdown
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        assert completed["status"] == "COMPLETED"
        res = api.cancel_booking(completed["id"], STAFF)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        after = get_booking(completed["id"])
        assert after["status"] == "COMPLETED"
        assert after["encumbered_cents"] == 0, (
            "completion already released the encumbrance (PRD §3.7)"
        )

    def test_booking_no_show_before_start(self, api):
        """PRD §3.7: "Marking a no-show is permitted only once the current
        logical time has passed `start_at`". PRD §2.9: "This rule also covers
        time-window misuse on booking cancel and no-show: cancelling an
        `APPROVED` booking is permitted only strictly before `start_at`, and
        marking a no-show is permitted only after `start_at` has passed;
        violations surface as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/booking_no_show_before_start
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        set_clock("2026-09-01T08:59:00Z")  # one minute before start_at
        res = api.no_show_booking(b1["id"], STAFF)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        after = get_booking(b1["id"])
        assert after["status"] == "APPROVED"
        assert after["encumbered_cents"] == 18000, (
            "a rejected no-show must not release the 18000-cent encumbrance"
        )

    def test_booking_check_in_early_window_boundary(self, api):
        """PRD §3.7: "Check-in advances an `APPROVED` booking to `IN_PROGRESS`
        and is allowed from fifteen minutes before `start_at` through
        `end_at`; outside that window the attempt fails `ERR_INVALID_STATE`."

        Design: Corner/state_machines/booking_check_in_early_window_boundary
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)  # 2026-09-01 09:00-10:30
        set_clock("2026-09-01T08:44:00Z")  # start - 16 min
        early = api.check_in_booking(b1["id"], STAFF)
        validate_error(early, "ERR_INVALID_STATE", expected_status=409)
        set_clock("2026-09-01T08:45:00Z")  # start - 15 min exactly
        checked_in = validate_success(api.check_in_booking(b1["id"], STAFF), 200)
        assert checked_in["status"] == "IN_PROGRESS", (
            "start minus exactly fifteen minutes is inside the check-in window"
        )


class TestUsageLogGatedByBookingCompletion:
    def test_usage_log_create_rejected_while_booking_approved(self, api):
        """PRD §3.8: "the booking must be `COMPLETED`
        (`ERR_BOOKING_NOT_COMPLETED`)".

        Design: Difficulty/cross_entity_state_dependency/usage_log_gated_by_booking_completion
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)  # APPROVED, never checked in
        res = api.create_usage_log(
            create_usage_log_payload(
                b1["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
            ),
            STAFF,
        )
        validate_error(res, "ERR_BOOKING_NOT_COMPLETED")

    def test_usage_log_create_succeeds_after_completion(self, api):
        """PRD §3.8: "The log's `instrument_id` and `user_id` are denormalized
        from the booking, and the creator's operator id is recorded as
        `logged_by`." and "New logs start `DRAFT`."

        Design: Difficulty/cross_entity_state_dependency/usage_log_gated_by_booking_completion
        """
        stack = setup_canonical_stack()
        b1 = create_approved_booking(stack)
        completed = run_session_to_completed(
            b1, "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
        )
        log = validate_success(
            api.create_usage_log(
                create_usage_log_payload(
                    completed["id"], "2026-09-01T09:00:00Z", "2026-09-01T10:30:00Z"
                ),
                STAFF,
            ),
            201,
        )
        assert log["status"] == "DRAFT"
        assert log["logged_by"] == "staff-1"
        assert log["instrument_id"] == stack["i1"]["id"]
        assert log["user_id"] == stack["u1"]["id"]


class TestBookingApprovalGatedByTrainingState:
    def test_approve_fails_after_training_revoked(self, api):
        """PRD §3.3: "Revocation from `ENROLLED`, `CERTIFIED`, or `EXPIRED` is
        terminal (`REVOKED`) and blocks all future booking creation and
        approval for that (user, instrument) pair until a brand-new record is
        created and certified." PRD §3.3: "At booking creation and again at
        booking approval, when the instrument requires training the user must
        hold a record whose effective status is `CERTIFIED`; absence of one is
        rejected with `ERR_TRAINING_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/booking_approval_gated_by_training_state
        """
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        validate_success(api.revoke_training_record(stack["t1"]["id"], STAFF), 200)
        res = api.approve_booking(b1["id"], STAFF)
        validate_error(res, "ERR_TRAINING_REQUIRED", expected_status=422)
        assert get_booking(b1["id"])["status"] == "REQUESTED"

    def test_approve_succeeds_after_fresh_certification(self, api):
        """PRD §3.3: "At most one record with status `ENROLLED`, `CERTIFIED`,
        or `EXPIRED` may exist per (user, instrument) pair; `REVOKED` records
        do not block a fresh enrollment." PRD §3.6: "The provisional estimate —
        `estimated_charge_cents` — is the scheduled minutes (the whole-minute
        difference between `end_at` and `start_at`) multiplied by the pinned
        hourly rate divided by sixty, rounded half-up to whole cents; this
        provisional variant applies no billing-increment ceiling, no
        minimum-charge floor, and no consumables."

        Design: Difficulty/cross_entity_state_dependency/booking_approval_gated_by_training_state
        """
        stack = setup_canonical_stack()
        b1 = create_booking_request(stack)
        validate_success(api.revoke_training_record(stack["t1"]["id"], STAFF), 200)
        validate_error(api.approve_booking(b1["id"], STAFF), "ERR_TRAINING_REQUIRED")
        # A REVOKED record does not block a fresh enrollment for the pair.
        t2 = enroll_and_certify(stack["u1"]["id"], stack["i1"]["id"])
        assert t2["status"] == "CERTIFIED"
        approved = validate_success(api.approve_booking(b1["id"], STAFF), 200)
        assert approved["status"] == "APPROVED"
        assert approved["estimated_charge_cents"] == 18000, (
            "90 scheduled minutes x 12000 cents/hour / 60 = 18000"
        )
