"""Ops-day posture: the OPEN -> CUTOFF_PASSED -> CLOSED walk, end-of-day
reconciliation, and the submit-time cutoff gate's priority over the callback
gate."""
from test_helpers import (
    ApiErrorId,
    assert_business_date,
    create_business_date,
    create_callback_pending_wire,
    create_wire,
    get_wire,
    record_callback,
    setup_wire_room,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]


class TestBusinessDateLifecycle:
    def test_business_date_cutoff_then_close_happy_path(self, api):
        """PRD §2.5: "A **BusinessDate** record represents one operations day,
        identified by a unique `business_date` in ISO `YYYY-MM-DD` form, and
        walks a three-state posture machine: `OPEN`, then `CUTOFF_PASSED`,
        then `CLOSED`. Only an `OPEN` date may have its cutoff closed —
        attempting to close the cutoff on a date in any other posture is
        rejected with `ERR_CUTOFF_ALREADY_PASSED`."
        PRD §2.5: "Closing the day itself is the end-of-day reconciliation
        step: it requires the date to be in `CUTOFF_PASSED` and requires that
        no wire carry that `value_date` in any non-terminal processing status
        (`INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `APPROVED`,
        `RELEASING`, or `REPAIR`); either violation is rejected with
        `ERR_INVALID_STATE`."

        A wire-free date walks the full posture chain; replaying cutoff-close
        and day-close from the wrong posture are rejected.

        Design: Corner/state_machines/business_date_cutoff_then_close_happy_path
        """
        bd = create_business_date("2026-09-03")
        assert_business_date(bd)
        assert bd["status"] == "OPEN"

        cutoff = validate_success(api.close_cutoff(bd["id"], ADMIN), 200)
        assert cutoff["status"] == "CUTOFF_PASSED"

        resp_replay = api.close_cutoff(bd["id"], ADMIN)
        validate_error(resp_replay, ApiErrorId.ERR_CUTOFF_ALREADY_PASSED)

        closed = validate_success(api.close_day(bd["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"

        resp_close_again = api.close_day(bd["id"], ADMIN)
        validate_error(resp_close_again, ApiErrorId.ERR_INVALID_STATE)

    def test_close_day_blocked_by_nonterminal_wire(self, api):
        """PRD §2.5: "Closing the day itself is the end-of-day reconciliation
        step: it requires the date to be in `CUTOFF_PASSED` and requires that
        no wire carry that `value_date` in any non-terminal processing status
        (`INITIATED`, `CALLBACK_PENDING`, `PENDING_APPROVAL`, `APPROVED`,
        `RELEASING`, or `REPAIR`); either violation is rejected with
        `ERR_INVALID_STATE`."

        A PENDING_APPROVAL wire on the date blocks the close; cancelling the
        wire unblocks it.

        Design: Corner/state_machines/close_day_blocked_by_nonterminal_wire
        """
        room = setup_wire_room(business_date="2026-09-04")
        bd = room["business_date"]
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, purpose="eod probe")
        validate_success(api.submit_wire(
            wire["id"], {"business_date": "2026-09-04"}, OPERATOR), 200)
        validate_success(api.close_cutoff(bd["id"], ADMIN), 200)

        resp = api.close_day(bd["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        validate_success(api.cancel_wire(wire["id"], OPERATOR), 200)
        closed = validate_success(api.close_day(bd["id"], ADMIN), 200)
        assert closed["status"] == "CLOSED"


class TestSubmitCutoffPriority:
    def test_submit_cutoff_temporal_beats_callback_safety(self, api):
        """PRD §2.8: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the first failure
        determines the error returned. The order, from first to last, is:"
        PRD §2.8: "(8) the submit-time cutoff gate (`ERR_CUTOFF_PASSED`), (9)
        the optimistic-concurrency stale-view check (`ERR_STALE_VERSION`),
        (10) the generic state precondition on action endpoints
        (`ERR_INVALID_STATE`), (11) the callback-verification gate on submit
        (`ERR_CALLBACK_NOT_VERIFIED`)"

        A submit that violates both the cutoff rule (date CUTOFF_PASSED) and
        the callback rule (verification still PENDING) surfaces the cutoff
        error; nothing about the wire changes.

        Design: Difficulty/priority_pair_validation_conflict/submit_cutoff_temporal_beats_callback_safety
        """
        room = setup_wire_room()
        bd = create_business_date("2026-08-12")
        validate_success(api.close_cutoff(bd["id"], ADMIN), 200)

        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=100000000)
        assert wire["callback_status"] == "PENDING"
        assert case["status"] == "OPEN"

        resp = api.submit_wire(wire["id"], {"business_date": "2026-08-12"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "CALLBACK_PENDING", (
            "the rejected submit changes nothing")
        assert wire_after["reservation_active"] is False

    def test_submit_cutoff_fires_with_callback_satisfied(self, api):
        """PRD §2.5: "From the moment a date's cutoff passes, no wire may be
        submitted or released against that date; the rejection code is
        `ERR_CUTOFF_PASSED`."
        PRD §3.2: "A `CONFIRMED` outcome resolves the case at `resolved_at`,
        moves it to `CONFIRMED`, and sets the wire's `callback_status` to
        `VERIFIED`."

        The cutoff gate fires even when the callback obligation is fully
        satisfied: a VERIFIED wire submitted against a cutoff-passed date is
        still rejected with ERR_CUTOFF_PASSED.

        Design: Difficulty/priority_pair_validation_conflict/submit_cutoff_temporal_beats_callback_safety
        """
        room = setup_wire_room(
            account_overrides={"daily_outgoing_limit_cents": 500000000})
        bd_open = create_business_date("2026-08-12")
        wire, case = create_callback_pending_wire(
            room["account"]["id"], room["beneficiary"]["id"],
            amount_cents=150000000)
        record_callback(case["id"], outcome="CONFIRMED")
        verified = get_wire(wire["id"])
        assert verified["callback_status"] == "VERIFIED"

        validate_success(api.close_cutoff(bd_open["id"], ADMIN), 200)
        resp = api.submit_wire(wire["id"], {"business_date": "2026-08-12"}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "CALLBACK_PENDING"
