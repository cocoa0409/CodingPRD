"""Department queue: skip branch, sequence monotonicity, priority selector,
empty-queue rejection, and the referral-ledger no-drift invariant (PRD §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    call_next_payload,
    create_accommodation_flag_for,
    get_appointment,
    get_referral,
    get_success_data,
    list_appointment_tickets,
    setup_arrived_visit,
    setup_in_room_visit,
    setup_ready_visit,
    validate_error,
    validate_success,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
FD = TEST_USERS["front_desk_headers"]


class TestSkipBranch:
    def _in_room_visit(self, api, provider_code="DRF"):
        return setup_in_room_visit(
            scheduled_start="2026-08-10T09:05:00Z",
            provider_code=provider_code,
            copay_cents=3500,
            coinsurance_pct=0,
            allowed_amount_cents=5000,
            payment_amounts=[875],
            checkin_clock="2026-08-10T09:04:00Z",
        )

    def test_called_ticket_skip_moves_ticket_to_skipped(self, api):
        """PRD §3.6: "When a called patient cannot be roomed, a
        `FrontDeskAgent` skips the ticket, moving it `CALLED` → `SKIPPED`, and
        the appointment drops back from `IN_ROOM` to `ARRIVED` for
        re-rooming."

        Design: Difficulty/non_linear_state_machine/queue_ticket_called_skipped_branch
        """
        ctx = self._in_room_visit(api)
        assert ctx["ticket"]["state"] == "CALLED"
        skipped = validate_success(api.skip_ticket(ctx["ticket"]["id"], FD), 200)
        assert skipped["state"] == "SKIPPED"

    def test_skip_returns_appointment_to_arrived(self, api):
        """PRD §3.6: "When a called patient cannot be roomed, a
        `FrontDeskAgent` skips the ticket, moving it `CALLED` → `SKIPPED`, and
        the appointment drops back from `IN_ROOM` to `ARRIVED` for
        re-rooming."

        Design: Difficulty/non_linear_state_machine/queue_ticket_called_skipped_branch
        """
        ctx = self._in_room_visit(api)
        assert get_appointment(ctx["appointment"]["id"])["status"] == "IN_ROOM"
        validate_success(api.skip_ticket(ctx["ticket"]["id"], FD), 200)
        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["status"] == "ARRIVED"


class TestReferralLedgerInvariant:
    def _arrived_hmo_visit_with_referral(self, api):
        ctx = setup_arrived_visit(
            plan_type="HMO",
            department_code="CARD",
            procedure_code="99213",
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRS",
            with_referral=True,
            referral_npi="NPI777",
            referral_visits_authorized=2,
            referral_valid_from="2026-08-01",
            referral_valid_until="2026-09-30",
            allowed_amount_cents=0,
        )
        return ctx

    def test_skip_does_not_release_consumed_visit(self, api):
        """PRD §3.6: "Two consumptions ride along with arrival: the matched
        referral's `visits_consumed` increments by one, which may tip it into
        `EXHAUSTED` per §3.3, and the authorization covering the visit moves
        `APPROVED` → `CONSUMED`."
        PRD §3.6: "When a called patient cannot be roomed, a `FrontDeskAgent`
        skips the ticket, moving it `CALLED` → `SKIPPED`, and the appointment
        drops back from `IN_ROOM` to `ARRIVED` for re-rooming."

        Design: Difficulty/compensating_invariant/referral_consume_then_release_preserves_visits_consumed
        """
        ctx = self._arrived_hmo_visit_with_referral(api)
        ticket = get_success_data(
            api.call_next(call_next_payload("CARD", "2026-08-10"), FD)
        )
        validate_success(api.skip_ticket(ticket["id"], FD), 200)

        referral = get_referral(ctx["referral"]["id"])
        # The skip compensation must not drift the utilization ledger.
        assert referral["visits_consumed"] == 1
        assert referral["status"] == "OPEN"

    def test_skip_keeps_appointment_arrived_for_re_rooming(self, api):
        """PRD §3.6: "the appointment drops back from `IN_ROOM` to `ARRIVED`
        for re-rooming."
        PRD §3.3: "A new referral starts with `visits_consumed` at zero and
        status `OPEN`"

        Design: Difficulty/compensating_invariant/referral_consume_then_release_preserves_visits_consumed
        """
        ctx = self._arrived_hmo_visit_with_referral(api)
        ticket = get_success_data(
            api.call_next(call_next_payload("CARD", "2026-08-10"), FD)
        )
        validate_success(api.skip_ticket(ticket["id"], FD), 200)

        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["status"] == "ARRIVED"
        referral = get_referral(ctx["referral"]["id"])
        assert referral["visits_consumed"] == 1


class TestQueueSequence:
    def test_sequence_monotonic_after_skip(self, api):
        """PRD §3.6: "Its `sequence_number` is one more than the count of
        tickets already issued for that department and date in any state, so
        numbers are monotonic within the day and never reused, even after
        tickets are skipped or removed."

        Design: Corner/calculations/queue_sequence_monotonic_after_skip
        """
        ctx1 = setup_in_room_visit(
            department_code="DERM",
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRQ1",
            allowed_amount_cents=0,
            checkin_clock="2026-08-10T08:45:00Z",
        )
        assert ctx1["ticket"]["sequence_number"] == 1
        validate_success(api.skip_ticket(ctx1["ticket"]["id"], FD), 200)

        ctx2 = setup_arrived_visit(
            patient_over={
                "first_name": "Seq", "last_name": "Two",
                "date_of_birth": "1999-09-09", "sex_at_birth": "F",
                "primary_phone": "+15551300004",
            },
            department_code="DERM",
            scheduled_start="2026-08-10T09:15:00Z",
            provider_code="DRQ2",
            allowed_amount_cents=0,
        )
        tickets = list_appointment_tickets(ctx2["appointment"]["id"])
        assert len(tickets) == 1
        assert tickets[0]["sequence_number"] == 2


class TestQueuePrioritySelector:
    def test_accommodation_beats_earlier_standard(self, api):
        """PRD §3.6: "The ticket's `priority` is derived at issuance: `STAT`
        when the check-in payload carried `stat_flag` as true; otherwise
        `ACCOMMODATION` when the patient has any accommodation flag with
        `active` set to true; otherwise `STANDARD` — `STAT` outranks all, and
        `ACCOMMODATION` outranks `STANDARD`."
        PRD §3.6: "selects among that day's `WAITING` tickets for the
        department by priority rank — `STAT` first, then `ACCOMMODATION`, then
        `STANDARD` — breaking ties by ascending `sequence_number`; the first
        ticket in that order is called."

        Design: Corner/calculations/queue_priority_accommodation_beats_standard
        """
        # STANDARD patient arrives first (sequence 1).
        ctx_std = setup_arrived_visit(
            patient_over={
                "first_name": "Std", "last_name": "Ard",
                "date_of_birth": "1991-01-11", "sex_at_birth": "M",
                "primary_phone": "+15551300005",
            },
            department_code="GI",
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRG1",
            allowed_amount_cents=0,
            checkin_clock="2026-08-10T08:40:00Z",
        )
        # ACCOMMODATION patient arrives second (sequence 2).
        ctx_acc = setup_arrived_visit(
            patient_over={
                "first_name": "Acc", "last_name": "Omm",
                "date_of_birth": "1992-02-12", "sex_at_birth": "F",
                "primary_phone": "+15551300006",
            },
            department_code="GI",
            scheduled_start="2026-08-10T09:10:00Z",
            provider_code="DRG2",
            allowed_amount_cents=0,
            flag_over={"flag_type": "MOBILITY", "note": "wheelchair"},
        )

        called = validate_success(
            api.call_next(call_next_payload("GI", "2026-08-10"), FD), 200
        )
        assert called["priority"] == "ACCOMMODATION"
        assert called["appointment_id"] == ctx_acc["appointment"]["id"]
        assert called["appointment_id"] != ctx_std["appointment"]["id"]


class TestEmptyQueue:
    def test_call_next_empty_queue_rejected(self, api):
        """PRD §3.6: "Calling next against an empty queue — no `WAITING`
        ticket exists for the department and date — is rejected with
        `ERR_QUEUE_EMPTY` (HTTP 404)."

        Design: Corner/errors/err_queue_empty_on_call_next
        """
        res = api.call_next(call_next_payload("ONC", "2026-08-10"), FD)
        validate_error(res, ApiErrorId.ERR_QUEUE_EMPTY)
