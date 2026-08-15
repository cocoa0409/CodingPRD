"""Callback verification: the $1M inclusive threshold, the strict four-hour
window, outcome recording, and the submit-time verification gate."""
from test_helpers import (
    ApiErrorId,
    assert_callback_verification,
    assert_wire,
    create_callback_pending_wire,
    create_wire,
    get_wire,
    list_wire_callbacks,
    parse_instant,
    record_callback,
    set_clock,
    setup_wire_room,
    submit_wire,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]


class TestCallbackThreshold:
    def test_callback_threshold_inclusive_at_exactly_one_million(self, api):
        """PRD §3.2: "A wire whose `amount_cents` is at least one million
        dollars — one hundred million cents, with the boundary inclusive so
        that exactly $1,000,000.00 requires a callback — has its computed
        `requires_callback` flag set true and enters `CALLBACK_PENDING` rather
        than `INITIATED`; its `callback_status` becomes `PENDING`, and the
        system opens a `CallbackVerification` case in `OPEN` status stamped
        with `opened_at` at creation and an `expires_at` exactly four hours
        later."
        PRD §3.2: "A wire below the threshold enters `INITIATED` with
        `callback_status` `NONE` and no case."

        Exactly 100000000 cents requires the callback; one cent below does
        not.

        Design: Difficulty/boundary_precision_check/callback_threshold_inclusive_at_exactly_one_million
        """
        room = setup_wire_room()

        wire_hi, case_hi = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=100000000)
        assert_wire(wire_hi)
        assert wire_hi["requires_callback"] is True
        assert wire_hi["status"] == "CALLBACK_PENDING"
        assert wire_hi["callback_status"] == "PENDING"
        assert_callback_verification(case_hi)
        assert case_hi["status"] == "OPEN"
        delta = parse_instant(case_hi["expires_at"]) - parse_instant(case_hi["opened_at"])
        assert delta.total_seconds() == 4 * 3600, (
            f"expires_at must be opened_at + 4h, got {delta}")

        wire_lo = create_wire(
            room["account"]["id"], room["beneficiary"]["id"], 99999999)
        assert wire_lo["requires_callback"] is False
        assert wire_lo["status"] == "INITIATED"
        assert wire_lo["callback_status"] == "NONE"
        cases_lo = list_wire_callbacks(wire_lo["id"])
        assert cases_lo == [], f"below-threshold wire must have no case, got {cases_lo}"

    def test_callback_required_above_threshold_and_window_is_four_hours(self, api):
        """PRD §3.2: "A wire whose `amount_cents` is at least one million
        dollars — one hundred million cents, with the boundary inclusive so
        that exactly $1,000,000.00 requires a callback — has its computed
        `requires_callback` flag set true and enters `CALLBACK_PENDING` rather
        than `INITIATED`"

        One cent above the threshold (100000001) also enters CALLBACK_PENDING
        with a single OPEN case whose expiry is four hours out.

        Design: Difficulty/boundary_precision_check/callback_threshold_inclusive_at_exactly_one_million
        """
        room = setup_wire_room()
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=100000001)
        assert wire["requires_callback"] is True
        assert wire["status"] == "CALLBACK_PENDING"
        assert case["status"] == "OPEN"
        delta = parse_instant(case["expires_at"]) - parse_instant(case["opened_at"])
        assert delta.total_seconds() == 4 * 3600


class TestCallbackOutcomes:
    def test_wire_above_threshold_initial_state_callback_pending(self, api):
        """PRD §3.2: "its `callback_status` becomes `PENDING`, and the system
        opens a `CallbackVerification` case in `OPEN` status stamped with
        `opened_at` at creation and an `expires_at` exactly four hours later."

        A wire of 200000000 cents starts CALLBACK_PENDING with an OPEN case
        whose deadline is exactly opened_at + 4h.

        Design: Corner/state_machines/wire_above_threshold_initial_state_callback_pending
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=200000000)
        assert wire["status"] == "CALLBACK_PENDING"
        assert wire["callback_status"] == "PENDING"
        assert wire["requires_callback"] is True
        assert case["status"] == "OPEN"
        delta = parse_instant(case["expires_at"]) - parse_instant(case["opened_at"])
        assert delta.total_seconds() == 4 * 3600

    def test_callback_denied_cancels_wire(self, api):
        """PRD §3.2: "A `DENIED` outcome resolves the case as `DENIED` and is
        fatal to the wire: the wire transitions to `CANCELLED`, its
        `callback_status` resets to `NONE`, and the denial is audit-logged."

        Design: Corner/state_machines/callback_denied_cancels_wire
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=150000000)

        resolved = record_callback(case["id"], outcome="DENIED")
        assert_callback_verification(resolved)
        assert resolved["status"] == "DENIED"

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "CANCELLED"
        assert wire_after["callback_status"] == "NONE"

    def test_callback_unreachable_then_confirmed_retry(self, api):
        """PRD §3.2: "An `UNREACHABLE` outcome is explicitly non-terminal: the
        case remains `OPEN` and retryable until the window lapses."
        PRD §3.2: "A `CONFIRMED` outcome resolves the case at `resolved_at`,
        moves it to `CONFIRMED`, and sets the wire's `callback_status` to
        `VERIFIED`."

        Design: Corner/endpoints/callback_unreachable_then_confirmed_retry
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=150000000)

        first = record_callback(case["id"], outcome="UNREACHABLE")
        assert first["status"] == "OPEN", "UNREACHABLE keeps the case OPEN"

        second = record_callback(case["id"], outcome="CONFIRMED")
        assert second["status"] == "CONFIRMED"
        assert second["resolved_at"] is not None

        wire_after = get_wire(wire["id"])
        assert wire_after["callback_status"] == "VERIFIED"


class TestSubmitCallbackGate:
    def test_submit_callback_pending_unverified_returns_error(self, api):
        """PRD §3.3: "The wire's `callback_status` must be `VERIFIED` — or
        `WAIVED`, as described next — otherwise the submission is rejected
        with `ERR_CALLBACK_NOT_VERIFIED`."

        With the business date OPEN the callback gate is the one that blocks;
        after a CONFIRMED recording the identical submit succeeds and stamps
        value_date.

        Design: Corner/validations/submit_callback_pending_unverified_returns_error
        """
        room = setup_wire_room(
            business_date="2026-09-22",
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=150000000)

        resp = api.submit_wire(wire["id"], {"business_date": "2026-09-22"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CALLBACK_NOT_VERIFIED)

        record_callback(case["id"], outcome="CONFIRMED")
        submitted = submit_wire(wire["id"], "2026-09-22")
        assert_wire(submitted)
        assert submitted["status"] == "PENDING_APPROVAL"
        assert submitted["value_date"] == "2026-09-22"
        assert submitted["callback_status"] == "VERIFIED"


class TestCallbackWindowDeadline:
    def test_callback_window_strict_deadline_semantics(self, api):
        """PRD §3.2: "Recording is only possible while the case is `OPEN`
        (else `ERR_INVALID_STATE`) and strictly before `expires_at` — at or
        after the deadline the attempt is rejected with
        `ERR_CALLBACK_WINDOW_EXPIRED`, because the case has in fact already
        auto-expired."

        One second inside the window records fine; exactly at the deadline
        instant the record is rejected and the case is already EXPIRED with
        the wire CANCELLED.

        Design: Difficulty/resource_temporal_overlap/callback_window_strict_deadline_semantics
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        account = room["account"]
        beneficiary = room["beneficiary"]

        # Case A opens at the startup clock 2026-08-01T00:00:00Z (expires 04:00:00Z).
        wire_a, case_a = create_callback_pending_wire(
            account["id"], beneficiary["id"], amount_cents=100000000)

        # Case B opens one second before A's deadline (expires 07:59:59Z).
        set_clock("2026-08-01T03:59:59Z")
        wire_b, case_b = create_callback_pending_wire(
            account["id"], beneficiary["id"], amount_cents=100000000)

        confirmed = record_callback(case_a["id"], outcome="CONFIRMED")
        assert confirmed["status"] == "CONFIRMED", (
            "one second inside the window must be a valid recording")

        set_clock("2026-08-01T07:59:59Z")
        resp = api.record_callback(
            case_b["id"],
            {
                "outcome": "CONFIRMED",
                "contact_name": "Treasurer B",
                "contact_phone": "+1-555-0101",
            },
            OPERATOR,
        )
        validate_error(resp, ApiErrorId.ERR_CALLBACK_WINDOW_EXPIRED)

        case_b_after = validate_success(api.get_callback(case_b["id"], OPERATOR), 200)
        assert case_b_after["status"] == "EXPIRED"
        wire_b_after = get_wire(wire_b["id"])
        assert wire_b_after["status"] == "CANCELLED"

    def test_callback_case_lazy_expiry_on_read(self, api):
        """PRD §3.2: "The four-hour window is strict: at or after
        `expires_at`, an `OPEN` case auto-expires under the lazy-expiry rule
        of §2.5, and expiry cancels the wire, resets its `callback_status` to
        `NONE`, and writes an audit entry."
        PRD §2.5: "whenever an expirable case — a callback verification case,
        a fraud hold, or a recall request — or its parent wire is accessed,
        the system first compares the current logical time against the case's
        deadline and, if the deadline has been reached, applies the
        auto-resolution transition before answering."

        No record attempt at all: once the clock reaches the deadline, a bare
        read observes the case EXPIRED and the wire CANCELLED.

        Design: Difficulty/resource_temporal_overlap/callback_window_strict_deadline_semantics
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=100000000)
        # Default clock 2026-08-01T00:00:00Z; the deadline is 04:00:00Z.
        set_clock("2026-08-01T04:00:00Z")

        case_after = validate_success(api.get_callback(case["id"], OPERATOR), 200)
        assert case_after["status"] == "EXPIRED"
        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "CANCELLED"
        assert wire_after["callback_status"] == "NONE"
