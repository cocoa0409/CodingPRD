"""Disruption event lifecycle: the RECOVERY->ASSESSING loop, invalid-from
rejections, voucher gating on RECOVERY, and the close child-gate."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_disruption_event,
    add_event, add_flight, add_passenger, add_booking,
    event_to_assessing, event_to_recovery,
    setup_disrupted_booking, issue_voucher,
    get_event,
)

DUTY = TEST_USERS["duty_manager_headers"]
AGENT = TEST_USERS["agent_headers"]


class TestEventRecoveryReopenCycle:
    def test_reopen_loops_recovery_back_to_assessing(self, api):
        """PRD §3.2: "If new information arrives during recovery, reopening
        cycles the event from `RECOVERY` back to `ASSESSING`, and while an
        event sits in `ASSESSING` voucher issuance is blocked."
        PRD §3.2: "The event lifecycle is a decision staircase owned by the
        `DutyManager`, and each step increments the event's `version`."

        Design: Difficulty/non_linear_state_machine/disruption_event_recovery_reopen_cycle
        """
        event = add_event(event_code="CYC-1", classification="ATC",
                          cost_cap_cents=100000)
        assert event["event_status"] == "OPEN"
        event_to_assessing(event["id"])
        event_to_recovery(event["id"])
        reopened = validate_success(api_client.reopen_event(event["id"], DUTY))
        assert reopened["event_status"] == "ASSESSING", (
            f"RECOVERY -> reopen must loop back to ASSESSING, got {reopened['event_status']}")
        assert reopened["version"] == 4, (
            f"create(1) + assess + declare-recovery + reopen = 4, got {reopened['version']}")

    def test_full_cycle_closes_from_second_recovery(self, api):
        """PRD §3.2: "From `RECOVERY`, the event may be closed into the terminal
        `CLOSED` state" and "The event lifecycle is a decision staircase owned by
        the `DutyManager`, and each step increments the event's `version`."

        Design: Difficulty/non_linear_state_machine/disruption_event_recovery_reopen_cycle
        """
        event = add_event(event_code="CYC-1b", classification="ATC",
                          cost_cap_cents=100000)
        event_to_assessing(event["id"])
        event_to_recovery(event["id"])
        validate_success(api_client.reopen_event(event["id"], DUTY))
        event_to_recovery(event["id"])
        closed = validate_success(api_client.close_event(event["id"], DUTY))
        assert closed["event_status"] == "CLOSED"
        assert closed["version"] == 6, (
            f"five lifecycle steps after creation -> version 6, got {closed['version']}")


def test_event_lifecycle_actions_rejected_from_wrong_state(api):
    """PRD §3.2: "The event is born `OPEN`." and "Any lifecycle action
    attempted from the wrong state — assessing an event that is not `OPEN`,
    declaring recovery outside `ASSESSING`, reopening or closing outside
    `RECOVERY` — is rejected with `ERR_EVENT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/event_invalid_from_transitions
    """
    event = add_event(event_code="WX-C3", classification="WEATHER",
                      cost_cap_cents=1000)
    assert event["event_status"] == "OPEN"

    res_close = api_client.close_event(event["id"], DUTY)
    validate_error(res_close, ApiErrorId.ERR_EVENT_INVALID_STATE)

    event_to_assessing(event["id"])
    res_again = api_client.assess_event(event["id"], DUTY)
    validate_error(res_again, ApiErrorId.ERR_EVENT_INVALID_STATE)


class TestVoucherIssuanceRequiresEventRecovery:
    def _setup(self):
        return setup_disrupted_booking(event_code="MECH-17", event_state="ASSESSING")

    def test_voucher_issue_blocked_while_event_assessing(self, api):
        """PRD §3.6: "First, the booking's event must be in `RECOVERY` — an
        event that is `OPEN`, `ASSESSING`, or `CLOSED` rejects issuance with
        `ERR_EVENT_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/voucher_requires_event_recovery
        """
        ctx = self._setup()
        assert ctx["booking"]["id"]
        booking = get_booking_for(ctx)
        assert booking["booking_status"] == "DISRUPTED"
        res = api_client.issue_voucher(
            ctx["booking"]["id"], {"voucher_type": "TRANSPORT"}, AGENT)
        validate_error(res, ApiErrorId.ERR_EVENT_INVALID_STATE)

    def test_voucher_issue_succeeds_after_declare_recovery(self, api):
        """PRD §3.6: "A `TRANSPORT` voucher requires only that the booking be
        `DISRUPTED` — no committed case is needed — and carries a flat
        `face_value_cents` of five thousand cents, valid through two days after
        its issue date."
        PRD §3.2: "declaring recovery moves it to `RECOVERY`, which is the state
        that enables voucher issuance and signals that reaccommodation offers
        are being worked."

        Design: Difficulty/cross_entity_state_dependency/voucher_requires_event_recovery
        """
        ctx = self._setup()
        res = api_client.issue_voucher(
            ctx["booking"]["id"], {"voucher_type": "TRANSPORT"}, AGENT)
        validate_error(res, ApiErrorId.ERR_EVENT_INVALID_STATE)
        event_to_recovery(ctx["event"]["id"])
        voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
        assert voucher["face_value_cents"] == 5000
        assert voucher["voucher_status"] == "ISSUED"


def get_booking_for(ctx):
    from test_helpers import get_booking
    return get_booking(ctx["booking"]["id"])


class TestEventCloseChildGate:
    def _setup_weather_disruption(self):
        return setup_disrupted_booking(
            event_code="WX-1", classification="WEATHER",
            cost_cap_cents=100000, event_state="RECOVERY")

    def test_close_blocked_while_case_open(self, api):
        """PRD §3.2: "closing is rejected with `ERR_EVENT_CLOSE_BLOCKED`
        (HTTP 409) if any reaccommodation case belonging to the event is still
        `QUEUED`, `OFFERED`, or `ESCALATED`, if any voucher of the event is
        still `ISSUED`, if any booking with a case on the event is still
        `ELIGIBLE_PENDING` on its compensation axis, or if any refund election
        belonging to a booking of the event is still `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/event_close_requires_cases_terminal
        """
        ctx = self._setup_weather_disruption()
        assert ctx["case"]["case_status"] == "QUEUED"
        res = api_client.close_event(ctx["event"]["id"], DUTY)
        validate_error(res, ApiErrorId.ERR_EVENT_CLOSE_BLOCKED)

    def test_close_succeeds_after_booking_cancel_voids_case(self, api):
        """PRD §3.4: "Cancellation moves every non-`FLOWN` segment to
        `CANCELLED` and releases those seats, decreasing each affected cabin's
        `seats_sold` by `party_size`; any open case becomes `VOIDED` and its
        `PROPOSED` options become `EXPIRED`."
        PRD §3.7: "Bookings disrupted under uncontrollable `WEATHER` or `ATC`
        events receive no compensation: the amount is zero and the money axis
        stays `NONE`."

        Design: Difficulty/cross_entity_state_dependency/event_close_requires_cases_terminal
        """
        ctx = self._setup_weather_disruption()
        res = api_client.close_event(ctx["event"]["id"], DUTY)
        validate_error(res, ApiErrorId.ERR_EVENT_CLOSE_BLOCKED)

        validate_success(api_client.cancel_booking(ctx["booking"]["id"], AGENT))
        case_after = get_case_via_api(ctx["case"]["id"])
        assert case_after["case_status"] == "VOIDED"

        closed = validate_success(api_client.close_event(ctx["event"]["id"], DUTY))
        assert closed["event_status"] == "CLOSED"
        booking = get_booking_for(ctx)
        assert booking["compensation_status"] == "NONE", (
            "uncontrollable WEATHER event grants no eligibility, even after cancel")


def get_case_via_api(case_id):
    from test_helpers import get_case
    return get_case(case_id)
