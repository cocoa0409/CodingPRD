"""Refund-vs-credit elections, the parallel booking status axes, the inclusive
election window, and the pinned process-due batch order."""
from test_helpers import (
    api_client, validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, add_passenger, add_flight, add_event, add_booking,
    event_to_assessing, cancel_flight_under_event,
    setup_disrupted_booking, setup_committed_case,
    get_booking, issue_voucher, elect, process_election,
    cost_summary, comm_logs,
    create_refund_election_payload,
)

AGENT = TEST_USERS["agent_headers"]
FIN = TEST_USERS["finance_headers"]
DUTY = TEST_USERS["duty_manager_headers"]
ADMIN = TEST_USERS["ops_admin_headers"]


class TestBookingParallelStatusAxes:
    """The travel axis (booking_status) and the money axis (compensation_status)
    evolve independently on one row."""

    def _setup(self):
        return setup_committed_case(
            event_code="MECH-6", event_state="RECOVERY",
            passenger_overrides={"full_name": "Tim T", "contact_email": "tim@x.com"},
            flight_overrides={"flight_number": "OC800",
                              "sched_dep_utc": "2026-08-10T10:00:00Z",
                              "sched_arr_utc": "2026-08-10T12:00:00Z",
                              "distance_km": 3200},
            booking_overrides={"fare_cents": 50000},
            extra_flights=[{"flight_number": "OC900",
                            "sched_dep_utc": "2026-08-10T14:00:00Z",
                            "sched_arr_utc": "2026-08-10T16:00:00Z",
                            "distance_km": 3200}])

    def test_rebooked_booking_keeps_eligible_pending_money_axis(self, api):
        """PRD §3.7: "Every booking carries two independent axes on one row. The
        travel axis, `booking_status`, tracks fulfillment: `ACTIVE`,
        `DISRUPTED`, `REBOOKED`, and the terminals `CANCELLED` and `COMPLETED`.
        The money axis, `compensation_status`, tracks regulatory entitlement:
        `NONE`, `ELIGIBLE_PENDING`, `ELECTED_REFUND`, `ELECTED_CREDIT`, and the
        terminal `SETTLED`. Neither axis gates the other".

        Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes
        """
        ctx = self._setup()
        booking = get_booking(ctx["booking"]["id"])
        assert booking["booking_status"] == "REBOOKED"
        assert booking["compensation_status"] == "ELIGIBLE_PENDING", (
            "committing the case does not advance the money axis")

    def test_money_axis_settles_while_travel_axis_stays_rebooked(self, api):
        """PRD §3.7: "Election creates a `RefundElection` in `PENDING` with
        `election_source` `USER` and three snapshots taken at creation:
        `refund_amount_cents`, `credit_amount_cents`, and
        `compensation_amount_cents`. The booking's money axis advances to
        `ELECTED_REFUND` or `ELECTED_CREDIT` accordingly."
        PRD §3.7: "Processing moves the election to `PROCESSED` and the
        booking's money axis to `SETTLED`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes
        """
        ctx = self._setup()
        booking_id = ctx["booking"]["id"]
        election = elect(booking_id, "REFUND")
        assert election["election_status"] == "PENDING"
        assert election["election_source"] == "USER"
        mid = get_booking(booking_id)
        assert mid["booking_status"] == "REBOOKED"
        assert mid["compensation_status"] == "ELECTED_REFUND"

        process_election(election["id"])
        final = get_booking(booking_id)
        assert final["booking_status"] == "REBOOKED", (
            "processing the election does not touch the travel axis")
        assert final["compensation_status"] == "SETTLED"


def test_election_deadline_is_inclusive(api):
    """PRD §3.7: "Both doors stamp `eligible_at` and set the `election_deadline`
    to exactly 72 hours after it, inclusive."
    PRD §3.7: "the current time must be at or before the `election_deadline` —
    the deadline is inclusive — otherwise `ERR_ELECTION_WINDOW_CLOSED`
    (HTTP 422)."

    Design: Corner/validations/election_window_inclusive_deadline
    """
    set_clock("2026-08-10T00:00:00Z")
    p1 = add_passenger(full_name="Mia M", contact_email="mia@x.com")
    p2 = add_passenger(full_name="Noa N", contact_email="noa@x.com")
    flight = add_flight(flight_number="OC54",
                        sched_dep_utc="2026-08-10T09:00:00Z",
                        sched_arr_utc="2026-08-10T10:00:00Z")
    event = add_event(event_code="MECH-C14", cost_cap_cents=1_000_000)
    event_to_assessing(event["id"])
    b1 = add_booking(p1["id"], flight["id"])
    b2 = add_booking(p2["id"], flight["id"])
    # eligible_at stamped at 2026-08-10T00:00:00Z -> deadline 2026-08-13T00:00:00Z.
    cancel_flight_under_event(flight["id"], event["id"],
                              expected_version=flight["version"])

    set_clock("2026-08-13T00:00:00Z")
    res_ok = api_client.create_refund_election(
        b1["id"], create_refund_election_payload("REFUND"), AGENT)
    validate_success(res_ok, 201)

    set_clock("2026-08-13T00:00:01Z")
    res_late = api_client.create_refund_election(
        b2["id"], create_refund_election_payload("REFUND"), AGENT)
    validate_error(res_late, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED)


class TestCommsBatchEvaluationOrder:
    """One booking, ELIGIBLE_PENDING past its deadline, with one expired
    TRANSPORT voucher and one queued CANCELLATION notice."""

    def _setup(self):
        ctx = setup_disrupted_booking(
            clock="2026-08-10T00:00:00Z", event_code="MECH-5",
            cost_cap_cents=500000, event_state="RECOVERY",
            passenger_overrides={"full_name": "Sue S", "contact_email": "sue@x.com"},
            flight_overrides={"flight_number": "OC700",
                              "sched_dep_utc": "2026-08-10T08:00:00Z",
                              "sched_arr_utc": "2026-08-10T09:00:00Z",
                              "distance_km": 2000},
            booking_overrides={"fare_cents": 30000})
        voucher = issue_voucher(ctx["booking"]["id"], "TRANSPORT")
        assert voucher["valid_through"] == "2026-08-12"
        # Election deadline 2026-08-13T00:00:00Z and the voucher validity date
        # 2026-08-12 both pass before the batch runs.
        set_clock("2026-08-13T00:00:01Z")
        return ctx

    def test_batch_counts_follow_the_pinned_step_order(self, api):
        """PRD §3.8: "Step two expires `ISSUED` vouchers whose `valid_through`
        is before the current date, posting the compensating `REVERSAL` entries.
        Step three defaults overdue elections, as §3.7 describes:
        `ELIGIBLE_PENDING` bookings past their deadline receive a processed
        system-default credit election, the cost entries, and an
        `ELECTION_DEFAULT` message due now. Step four sends every `QUEUED`
        message whose `due_at` is at or before the current time — including the
        `ELECTION_DEFAULT` rows just queued — stamping `sent_at` and moving them
        to `SENT`. Step five emits cadence reminders: any booking still
        `DISRUPTED` whose most recent sent or queued message is older than
        thirty minutes gets a `REMINDER` queued and sent within this same batch,
        except that bookings defaulted in step three are excluded because their
        `ELECTION_DEFAULT` already satisfies the cadence."
        PRD §3.8: "The batch reports its work as counts: `expired_options`,
        `expired_vouchers`, `defaulted_elections`, `sent_count`, and
        `reminders_sent`."

        Design: Difficulty/combinatorial_formula/comms_batch_evaluation_order
        """
        ctx = self._setup()
        result = validate_success(api_client.process_due(ADMIN))
        assert result["expired_options"] == 0
        assert result["expired_vouchers"] == 1
        assert result["defaulted_elections"] == 1
        assert result["sent_count"] == 2, (
            "the queued CANCELLATION plus the freshly queued ELECTION_DEFAULT")
        assert result["reminders_sent"] == 0, (
            "the defaulted booking is excluded from cadence reminders")

    def test_defaulted_booking_settles_with_system_credit(self, api):
        """PRD §3.7: "When the process-due batch finds an `ELIGIBLE_PENDING`
        booking whose `election_deadline` has passed, it creates a
        `RefundElection` with `election` `CREDIT` and `election_source`
        `SYSTEM_DEFAULT`, already `PROCESSED`, posts the corresponding `CREDIT`
        and `COMPENSATION` cost entries, queues an `ELECTION_DEFAULT`
        communication due immediately, and the booking's money axis advances
        straight to `SETTLED`."
        PRD §2.9: "The committed-cost view, `accrual_total_cents`, is the sum of
        `amount_cents` over the event's `ACCRUAL` entries plus the sum over its
        `REVERSAL` entries; because every reversal recorded in this system
        targets an accrual, voiding or expiring a voucher reduces the accrual
        view only. The actual-cash view, `settled_total_cents`, is the sum over
        `SETTLEMENT` entries (plus any reversals targeting settlements, which do
        not occur in practice), so voids never move the settled view."

        Design: Difficulty/combinatorial_formula/comms_batch_evaluation_order
        """
        ctx = self._setup()
        validate_success(api_client.process_due(ADMIN))

        booking = get_booking(ctx["booking"]["id"])
        assert booking["compensation_status"] == "SETTLED"

        elections = validate_success(api_client.list_refund_elections(
            FIN, params={"booking_id": ctx["booking"]["id"]}))
        assert len(elections) == 1
        election = elections[0]
        assert election["election"] == "CREDIT"
        assert election["election_source"] == "SYSTEM_DEFAULT"
        assert election["election_status"] == "PROCESSED"
        # fare 30000, nothing FLOWN -> refund 30000; credit = 33000;
        # 2000 km tier -> compensation 40000.
        assert election["credit_amount_cents"] == 33000
        assert election["compensation_amount_cents"] == 40000

        summary = cost_summary(ctx["event"]["id"])
        # 5000 voucher ACCRUAL - 5000 REVERSAL + 33000 CREDIT + 40000 COMPENSATION.
        assert summary["accrual_total_cents"] == 73000
        assert summary["settled_total_cents"] == 40000

        logs = comm_logs({"booking_id": ctx["booking"]["id"]})
        templates = {l["template"]: l["log_status"] for l in logs}
        assert templates.get("ELECTION_DEFAULT") == "SENT"
        assert templates.get("CANCELLATION") == "SENT"
        assert "REMINDER" not in templates, (
            "a booking defaulted in step three never receives a REMINDER in the same batch")
