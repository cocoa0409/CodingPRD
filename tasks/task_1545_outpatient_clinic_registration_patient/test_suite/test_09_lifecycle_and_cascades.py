"""Terminal-state lockdown, visit completion side effects, policy-termination
cascade, and the day-close no-show sweep (PRD §3.2, §3.4, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_patient_payload,
    create_prechecked_visit,
    get_appointment,
    get_success_data,
    list_appointment_estimates,
    list_appointment_tickets,
    schedule_appointment,
    set_clock,
    setup_completed_visit,
    validate_error,
    validate_success,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
FD = TEST_USERS["front_desk_headers"]
SUP = TEST_USERS["access_supervisor_headers"]


class TestPolicyTerminationCascade:
    def _prechecked_visit_with_estimate(self, api):
        ctx = create_prechecked_visit(
            deductible_remaining_cents=30000,
            copay_cents=0,
            coinsurance_pct=20,
            scheduled_start="2026-08-20T09:00:00Z",
            provider_code="DRG",
        )
        estimate_res = api.create_copay_estimate(
            ctx["appointment"]["id"],
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 100000},
            FC,
        )
        ctx["estimate"] = validate_success(estimate_res, 201)
        return ctx

    def test_termination_supersedes_estimate_and_zeroes_responsibility(self, api):
        """PRD §3.2: "Termination cascades: every appointment of the policy's
        patient in `SCHEDULED` or `PRE_CHECKED` that relies on a `PROVISIONAL`
        estimate built from this policy has that estimate moved to
        `SUPERSEDED`, the appointment's cached responsibility re-derived, and
        its clearance recomputed."
        PRD §3.5: "the appointment's cached
        `estimated_patient_responsibility_cents` is then re-derived from the
        newest `PROVISIONAL` estimate, falling back to zero when none remains,
        and clearance is recomputed."

        Design: Difficulty/transitive_cascade/policy_terminate_estimate_supersede_gate_recompute
        """
        ctx = self._prechecked_visit_with_estimate(api)
        assert ctx["estimate"]["estimated_patient_responsibility_cents"] == 44000

        terminated = validate_success(
            api.terminate_policy(ctx["policy"]["id"], {"effective_end": "2026-08-01"}, REG),
            200,
        )
        assert terminated["status"] == "TERMINATED"

        estimates = list_appointment_estimates(ctx["appointment"]["id"])
        assert len(estimates) == 1
        assert estimates[0]["status"] == "SUPERSEDED"

        appt = get_appointment(ctx["appointment"]["id"])
        assert appt["estimated_patient_responsibility_cents"] == 0

    def test_termination_relaxes_gate_from_clear_with_payment_to_clear(self, api):
        """PRD §3.5: "Finally the gate resolves: when demographics,
        authorization, and referral are not all satisfied, `registration_gate`
        is `BLOCKED`; otherwise, when a current estimate exists whose
        `deposit_required_cents` is above zero and `amount_collected_cents` has
        not yet reached it, the gate is `CLEAR_WITH_PAYMENT`; otherwise the
        gate is `CLEAR`."
        PRD §3.2: "Termination cascades: every appointment of the policy's
        patient in `SCHEDULED` or `PRE_CHECKED` that relies on a `PROVISIONAL`
        estimate built from this policy has that estimate moved to
        `SUPERSEDED`, the appointment's cached responsibility re-derived, and
        its clearance recomputed."

        Design: Difficulty/transitive_cascade/policy_terminate_estimate_supersede_gate_recompute
        """
        ctx = self._prechecked_visit_with_estimate(api)
        # Deposit 11000 > collected 0 -> gate is CLEAR_WITH_PAYMENT.
        assert get_appointment(ctx["appointment"]["id"])["registration_gate"] == (
            "CLEAR_WITH_PAYMENT"
        )

        validate_success(
            api.terminate_policy(ctx["policy"]["id"], {"effective_end": "2026-08-01"}, REG),
            200,
        )
        # With no non-SUPERSEDED estimate left, the deposit branch no longer
        # applies and the gate resolves CLEAR.
        assert get_appointment(ctx["appointment"]["id"])["registration_gate"] == "CLEAR"


class TestTerminalStates:
    def test_completed_appointment_rejects_cancel(self, api):
        """PRD §3.4: "Cancellation is available to a `Registrar` from any
        pre-arrival state — `SCHEDULED`, `PRE_CHECKED`, or `READY` — and lands
        the appointment in the terminal `CANCELLED` status, with an optional
        `reason` recorded."
        PRD §3.7: "`COMPLETED`, `CANCELLED`, and `NO_SHOW` are the terminal
        states of the appointment lifecycle."
        PRD §2.10: "then admissibility of the requested state transition — an
        action attempted against a resource in a state that does not permit it
        is rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/terminal_completed_rejects_cancel
        """
        ctx = setup_completed_visit(
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRS2",
            allowed_amount_cents=0,
            checkin_clock="2026-08-10T08:50:00Z",
        )
        assert ctx["appointment"]["status"] == "COMPLETED"
        res = api.cancel_appointment(ctx["appointment"]["id"], {}, REG)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_serves_ticket_and_finalizes_estimate(self, api):
        """PRD §3.6: "Finishing the visit is a `FrontDeskAgent` act from
        `IN_ROOM` to the terminal `COMPLETED` status: the ticket moves `CALLED`
        → `SERVED`, and the visit's latest `PROVISIONAL` estimate moves to
        `FINAL` as described in §3.5."

        Design: Corner/state_machines/complete_sets_estimate_final_and_ticket_served
        """
        ctx = setup_completed_visit(
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRS3",
            copay_cents=2000,
            coinsurance_pct=0,
            allowed_amount_cents=5000,
            payment_amounts=[500],
            checkin_clock="2026-08-10T08:50:00Z",
        )
        assert ctx["appointment"]["status"] == "COMPLETED"

        tickets = list_appointment_tickets(ctx["appointment"]["id"])
        assert len(tickets) == 1
        assert tickets[0]["state"] == "SERVED"

        estimates = list_appointment_estimates(ctx["appointment"]["id"])
        assert len(estimates) == 1
        assert estimates[0]["status"] == "FINAL"


class TestDayClose:
    def test_close_day_marks_no_shows(self, api):
        """PRD §3.7: "It marks every appointment of the department still in
        `SCHEDULED`, `PRE_CHECKED`, or `READY` whose grace moment has passed as
        `NO_SHOW`, and removes every `WAITING` ticket of that date from the
        queue, moving each to `REMOVED`. The sweep reports back the number of
        visits marked as `no_show_count` and the number of tickets expired out
        of the queue as `expired_ticket_count`."

        Design: Corner/endpoints/close_day_marks_no_shows_and_removes_tickets
        """
        set_clock("2026-08-10T08:00:00Z")
        patient = get_success_data(
            api.create_patient(
                create_patient_payload(
                    first_name="No",
                    last_name="Show",
                    date_of_birth="1993-04-04",
                    sex_at_birth="F",
                    primary_phone="+15551600001",
                ),
                REG,
            )
        )
        appt = schedule_appointment(
            patient["id"],
            department_code="PULM",
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRNS",
        )
        # Advance logical time to the next day: the grace moment has passed
        # under any plausible reading of the configured grace period.
        set_clock("2026-08-11T00:00:00Z")

        summary = validate_success(
            api.close_day("PULM", {"queue_date": "2026-08-10"}, SUP), 200
        )
        assert summary["no_show_count"] == 1

        appt_after = validate_success(api.get_appointment(appt["id"], REG), 200)
        assert appt_after["status"] == "NO_SHOW"
