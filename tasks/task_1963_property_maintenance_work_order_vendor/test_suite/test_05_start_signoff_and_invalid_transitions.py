"""Start/sign-off rules and invalid state transitions on the work order."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_instant_equals,
    create_work_order,
    dispatch_in_house,
    get_work_order,
    make_resident_headers,
    make_technician_headers,
    set_clock,
    setup_assigned_work_order,
    setup_completed_work_order,
    setup_in_progress_work_order,
    setup_property_resident_technician,
    start_as_technician,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestStart:
    def test_start_sets_started_at_from_logical_clock(self, api):
        """PRD §3.4: "Starting moves the work order from `ASSIGNED` to `IN_PROGRESS` and stamps `started_at` with the current logical clock."
        PRD §2.4: "On server boot the logical clock starts at the fixed default `2026-08-01T00:00:00Z`; it does not read wall-clock time and must not fall back to it."
        PRD §2.5: "`version` (integer): starts at 1 on creation and increments by exactly one on every mutation of the resource."

        Design: Corner/state_machines/start_sets_started_at_from_clock
        """
        bundle = setup_assigned_work_order("Start Property", unit_number="209")
        data = start_as_technician(
            bundle["work_order"]["id"], bundle["technician"]["id"]
        )
        assert data["status"] == "IN_PROGRESS"
        assert_instant_equals(data["started_at"], "2026-08-01T00:00:00Z", "started_at")
        # create = 1, dispatch = 2, start = 3.
        assert data["version"] == 3

    def test_resident_consent_not_confirmed_rejected(self, api):
        """PRD §3.4: "If the dispatch was authorized by `RESIDENT_CONSENT`, the start payload must carry `resident_consent_confirmed` set to true, or the start is rejected with `ERR_ENTRY_RULE_VIOLATION`."

        Design: Corner/validations/resident_consent_not_confirmed_rejected
        """
        bundle = setup_assigned_work_order("Consent Property", unit_number="405")
        wo = bundle["work_order"]
        resp = api.start_work_order(
            wo["id"],
            {"resident_consent_confirmed": False},
            make_technician_headers(bundle["technician"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_RULE_VIOLATION)
        assert get_work_order(wo["id"])["status"] == "ASSIGNED"

    def test_notice_posted_start_timing_window(self, api):
        """PRD §3.4: "If the dispatch was authorized by `NOTICE_POSTED`, the current logical clock at start time must have reached at least `notice_posted_at` plus the property's `entry_notice_min_hours`; starting earlier is likewise `ERR_ENTRY_RULE_VIOLATION`."

        Design: Corner/validations/notice_posted_start_timing_window
        """
        bundle = setup_property_resident_technician("NoticeStart Property", unit_number="406")
        wo = create_work_order(
            bundle["property"]["id"], bundle["resident"]["id"],
            category="PLUMBING", priority="ROUTINE", description="Inspection",
        )
        # 48h lead satisfies the dispatch-time rule (notice 08-01T10:00Z, start 08-03T10:00Z).
        dispatch_in_house(
            wo["id"], bundle["technician"]["id"],
            scheduled_start_at="2026-08-03T10:00:00Z",
            scheduled_end_at="2026-08-03T12:00:00Z",
            entry_authorization="NOTICE_POSTED",
            notice_posted_at="2026-08-01T10:00:00Z",
        )
        # 23h elapsed since the notice: too early to start.
        set_clock("2026-08-02T09:00:00Z")
        resp = api.start_work_order(
            wo["id"], {}, make_technician_headers(bundle["technician"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ENTRY_RULE_VIOLATION)
        assert get_work_order(wo["id"])["status"] == "ASSIGNED"

        # Exactly 24h elapsed: "at least" is satisfied, start succeeds.
        set_clock("2026-08-02T10:00:00Z")
        resp2 = api.start_work_order(
            wo["id"], {}, make_technician_headers(bundle["technician"]["id"])
        )
        data = validate_success(resp2, 200)
        assert data["status"] == "IN_PROGRESS"


class TestInvalidTransitions:
    def test_dispatch_from_in_progress_rejected(self, api):
        """PRD §3.3: "Dispatch is the Dispatcher's core act and moves the work order from `TRIAGED` — or from `REOPENED` on a recall — to `ASSIGNED`."
        PRD §3.5: "Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/dispatch_from_in_progress_rejected
        """
        bundle = setup_in_progress_work_order("InvDisp Property", unit_number="205")
        wo = bundle["work_order"]
        resp = api.dispatch_work_order(
            wo["id"],
            {
                "assignment_type": "IN_HOUSE",
                "technician_id": bundle["technician"]["id"],
                "scheduled_start_at": "2026-08-01T14:00:00Z",
                "scheduled_end_at": "2026-08-01T16:00:00Z",
                "entry_authorization": "RESIDENT_CONSENT",
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_work_order(wo["id"])
        assert after["status"] == "IN_PROGRESS"
        assert_instant_equals(
            after["scheduled_start_at"], "2026-08-01T10:00:00Z", "scheduled_start_at"
        )

    def test_signoff_before_start_rejected(self, api):
        """PRD §3.4: "Resident sign-off is a self-transition: while the work order is `IN_PROGRESS`, the reporting resident — and only the reporting resident, matching `X-User-ID` against the work order's `resident_id` — records approval, which sets `resident_signoff` to true and leaves the status at `IN_PROGRESS`."
        PRD §3.5: "Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/signoff_before_start_rejected
        """
        bundle = setup_assigned_work_order("So Property", unit_number="208")
        wo = bundle["work_order"]
        resp = api.sign_off_work_order(
            wo["id"], {}, make_resident_headers(bundle["resident"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(wo["id"])["resident_signoff"] is False

    def test_cancel_from_in_progress_rejected(self, api):
        """PRD §3.5: "Cancellation is available only before work starts — from `TRIAGED`, from `ASSIGNED`, or from `REOPENED` — and moves the work order to the terminal `CANCELLED` status."
        PRD §3.5: "Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/cancel_from_in_progress_rejected
        """
        bundle = setup_in_progress_work_order("CancelInv Property", unit_number="207")
        wo = bundle["work_order"]
        resp = api.cancel_work_order(wo["id"], {}, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(wo["id"])["status"] == "IN_PROGRESS"

    def test_reopen_of_closed_work_order_rejected(self, api):
        """PRD §3.5: "Closure is the manager's quiet end-state: a PropertyManager closes a `COMPLETED` work order, stamping `closed_at` with the current logical clock and moving the status to `CLOSED`, a terminal state."
        PRD §3.5: "Attempting any transition from a status that does not allow it — reopening an `IN_PROGRESS` order, closing a `TRIAGED` one, cancelling a `COMPLETED` one, and so on — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/closed_work_order_reopen_rejected
        """
        bundle = setup_completed_work_order(property_name="Closed Property",
                                            unit_number="206")
        wo = bundle["work_order"]
        closed = validate_success(api.close_work_order(wo["id"], {}, MANAGER), 200)
        assert closed["status"] == "CLOSED"
        resp = api.reopen_work_order(
            wo["id"], {}, make_resident_headers(bundle["resident"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_work_order(wo["id"])["status"] == "CLOSED"
