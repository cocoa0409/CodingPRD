"""Investigations: the cyclic tracer send-and-answer loop with its three
dispatch cap, message sequencing, and the respond precondition."""
from test_helpers import (
    ApiErrorId,
    assert_investigation,
    assert_tracer_message,
    create_executed_wire,
    create_investigation,
    dispatch_tracer,
    respond_investigation,
    setup_wire_room,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
INVESTIGATOR = TEST_USERS["wire_investigator_headers"]


class TestTracerLoopCap:
    def test_investigation_tracer_answer_loop_with_cap(self, api):
        """PRD §3.10: "From `OPEN`, dispatching an outbound tracer — supplying
        the message `body` — requires `tracer_count` to be below
        `max_tracers`, with a fourth dispatch rejected as
        `ERR_TRACER_LIMIT_EXCEEDED`."
        PRD §3.10: "Each dispatch creates a `TracerMessage` with `direction`
        `OUTBOUND`, assigns it a `sequence_no` equal to the count of existing
        tracer messages for the investigation plus one (so numbering starts at
        one), increments `tracer_count`, and moves the investigation to
        `AWAITING_RESPONSE`."
        PRD §3.10: "registering the counterparty's reply — again supplying a
        `body` — creates an `INBOUND` tracer message with the next
        `sequence_no`, does **not** consume any of the tracer budget, and
        returns the investigation to `OPEN`"

        Three dispatches succeed (with interleaved replies cycling the
        investigation back to OPEN); the fourth dispatch is rejected and the
        count holds at three.

        Design: Difficulty/non_linear_state_machine/investigation_tracer_answer_loop_with_cap
        """
        room = setup_wire_room(business_date="2026-08-07")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-07",
            750000, method="CHIPS", purpose="loop probe")
        investigation = create_investigation(
            wire["id"], type="TRACER", note="beneficiary claims non-receipt")
        assert_investigation(investigation)
        assert investigation["status"] == "OPEN"
        assert investigation["tracer_count"] == 0

        t1 = dispatch_tracer(investigation["id"], body="tracer 1")
        assert_tracer_message(t1)
        assert t1["direction"] == "OUTBOUND"
        assert t1["sequence_no"] == 1
        respond_investigation(investigation["id"], body="reply 1")

        t2 = dispatch_tracer(investigation["id"], body="tracer 2")
        assert t2["sequence_no"] == 3, (
            f"sequence counts every message on the investigation, got "
            f"{t2['sequence_no']}")
        respond_investigation(investigation["id"], body="reply 2")

        t3 = dispatch_tracer(investigation["id"], body="tracer 3")
        assert t3["sequence_no"] == 5, (
            f"the third dispatch is the fifth message overall, got "
            f"{t3['sequence_no']}")
        respond_investigation(investigation["id"], body="reply 3")

        resp = api.dispatch_tracer(
            investigation["id"], {"body": "tracer 4"}, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_TRACER_LIMIT_EXCEEDED)

        after = validate_success(
            api.get_investigation(investigation["id"], INVESTIGATOR), 200)
        assert_investigation(after)
        assert after["tracer_count"] == 3
        assert after["status"] == "OPEN", (
            "each reply returned the loop to OPEN and the cap held")

    def test_tracer_thread_sequences_and_budget(self, api):
        """PRD §3.10: "Each dispatch creates a `TracerMessage` with
        `direction` `OUTBOUND`, assigns it a `sequence_no` equal to the count
        of existing tracer messages for the investigation plus one (so
        numbering starts at one), increments `tracer_count`, and moves the
        investigation to `AWAITING_RESPONSE`. From `AWAITING_RESPONSE`,
        registering the counterparty's reply — again supplying a `body` —
        creates an `INBOUND` tracer message with the next `sequence_no`, does
        **not** consume any of the tracer budget, and returns the
        investigation to `OPEN`, where another dispatch becomes possible."
        PRD §3.10: "An investigation's tracer thread is listable in
        `sequence_no` ascending order."

        Outbound and inbound messages share one ascending sequence while only
        outbound dispatches consume the tracer budget.

        Design: Difficulty/non_linear_state_machine/investigation_tracer_answer_loop_with_cap
        """
        room = setup_wire_room(business_date="2026-08-07")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-07",
            750000, method="CHIPS", purpose="sequence probe")
        investigation = create_investigation(
            wire["id"], type="NON_RECEIPT", note="where is the money")

        dispatch_tracer(investigation["id"], body="tracer 1")
        reply1 = respond_investigation(investigation["id"], body="reply 1")
        assert reply1["direction"] == "INBOUND"
        assert reply1["sequence_no"] == 2

        mid = validate_success(
            api.get_investigation(investigation["id"], INVESTIGATOR), 200)
        assert mid["status"] == "OPEN"
        assert mid["tracer_count"] == 1, (
            f"the INBOUND reply consumed no budget, got {mid['tracer_count']}")

        t2 = dispatch_tracer(investigation["id"], body="tracer 2")
        assert t2["sequence_no"] == 3
        awaiting = validate_success(
            api.get_investigation(investigation["id"], INVESTIGATOR), 200)
        assert awaiting["status"] == "AWAITING_RESPONSE"
        assert awaiting["tracer_count"] == 2

        thread = validate_success(
            api.list_tracers(investigation["id"], INVESTIGATOR), 200)
        assert [m["sequence_no"] for m in thread] == [1, 2, 3]
        assert [m["direction"] for m in thread] == [
            "OUTBOUND", "INBOUND", "OUTBOUND"]


class TestRespondPrecondition:
    def test_investigation_respond_out_of_order_rejected(self, api):
        """PRD §3.10: "From `AWAITING_RESPONSE`, registering the
        counterparty's reply — again supplying a `body` — creates an `INBOUND`
        tracer message with the next `sequence_no`"
        PRD §3.10: "acting from any other state is `ERR_INVALID_STATE`."

        A respond on a freshly OPEN investigation (no tracer dispatched) is
        rejected.

        Design: Corner/state_machines/investigation_respond_out_of_order_rejected
        """
        room = setup_wire_room(business_date="2026-09-08")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-08",
            100000, purpose="inv probe")
        investigation = create_investigation(
            wire["id"], type="NON_RECEIPT", note="beneficiary claims non-receipt")
        assert investigation["status"] == "OPEN"

        resp = api.respond_investigation(
            investigation["id"], {"body": "premature reply"}, INVESTIGATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
