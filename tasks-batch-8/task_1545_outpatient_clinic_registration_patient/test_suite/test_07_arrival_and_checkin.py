"""Arrival & check-in: late-arrival cutoff, pre-check revert cycle, referral
consumption, and check-in state admissibility (PRD §3.4, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_prechecked_visit,
    get_referral,
    list_appointment_tickets,
    set_clock,
    setup_ready_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
FD = TEST_USERS["front_desk_headers"]


class TestLateArrivalCutoff:
    def _ready_pair(self, api):
        """Two identical READY ESTABLISHED visits at 2026-08-10T09:00 with a
        zero deposit, so the gate is CLEAR for both."""
        ctx1 = setup_ready_visit(
            patient_over={
                "first_name": "Bnd", "last_name": "One",
                "date_of_birth": "1990-10-10", "sex_at_birth": "F",
                "primary_phone": "+15557000001",
            },
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRK",
            allowed_amount_cents=0,
        )
        ctx2 = setup_ready_visit(
            patient_over={
                "first_name": "Bnd", "last_name": "Two",
                "date_of_birth": "1991-11-11", "sex_at_birth": "M",
                "primary_phone": "+15557000002",
            },
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRL",
            allowed_amount_cents=0,
        )
        return ctx1, ctx2

    def test_checkin_exactly_at_thirty_minutes_allowed(self, api):
        """PRD §3.6: "Then the late-arrival rule applies: check-in is rejected
        with `ERR_TOO_LATE_FOR_CHECKIN` (HTTP 422) once the current time passes
        thirty minutes after `scheduled_start`, while an arrival exactly thirty
        minutes late is still accepted."
        PRD §3.6: "A successful check-in records `late_minutes` on the
        appointment — the minutes between `scheduled_start` and the actual
        check-in, negative when the patient arrived early."

        Design: Difficulty/boundary_precision_check/late_arrival_cutoff_exactly_30_minutes_allowed
        """
        ctx1, _ = self._ready_pair(api)
        set_clock("2026-08-10T09:30:00Z")
        arrived = validate_success(
            api.check_in(ctx1["appointment"]["id"], {}, FD), 200
        )
        assert arrived["status"] == "ARRIVED"
        assert arrived["late_minutes"] == 30

    def test_checkin_one_minute_past_cutoff_rejected(self, api):
        """PRD §3.6: "Then the late-arrival rule applies: check-in is rejected
        with `ERR_TOO_LATE_FOR_CHECKIN` (HTTP 422) once the current time passes
        thirty minutes after `scheduled_start`, while an arrival exactly thirty
        minutes late is still accepted."

        Design: Difficulty/boundary_precision_check/late_arrival_cutoff_exactly_30_minutes_allowed
        """
        _, ctx2 = self._ready_pair(api)
        set_clock("2026-08-10T09:31:00Z")
        res = api.check_in(ctx2["appointment"]["id"], {}, FD)
        validate_error(res, ApiErrorId.ERR_TOO_LATE_FOR_CHECKIN)


class TestPrecheckRevertCycle:
    def test_revert_precheck_returns_to_scheduled(self, api):
        """PRD §3.4: "When plans change, the same role reverts the visit
        `PRE_CHECKED` → `SCHEDULED`, again recomputing clearance."

        Design: Difficulty/non_linear_state_machine/appointment_precheck_revert_cycle
        """
        ctx = create_prechecked_visit(
            scheduled_start="2026-08-15T09:00:00Z",
            provider_code="DRE",
            copay_cents=3500,
        )
        assert ctx["appointment"]["status"] == "PRE_CHECKED"
        reverted = validate_success(
            api.revert_precheck(ctx["appointment"]["id"], REG), 200
        )
        assert reverted["status"] == "SCHEDULED"

    def test_precheck_again_after_revert(self, api):
        """PRD §3.4: "Once coverage is verified, a `Registrar` advances the
        visit `SCHEDULED` → `PRE_CHECKED`."
        PRD §3.4: "When plans change, the same role reverts the visit
        `PRE_CHECKED` → `SCHEDULED`, again recomputing clearance."

        Design: Difficulty/non_linear_state_machine/appointment_precheck_revert_cycle
        """
        ctx = create_prechecked_visit(
            scheduled_start="2026-08-15T09:00:00Z",
            provider_code="DRE2",
            copay_cents=3500,
        )
        validate_success(api.revert_precheck(ctx["appointment"]["id"], REG), 200)
        rechecked = validate_success(api.pre_check(ctx["appointment"]["id"], REG), 200)
        assert rechecked["status"] == "PRE_CHECKED"


class TestCheckInReferralConsumption:
    def _hmo_ready_visit_with_referral(self, api):
        ctx = setup_ready_visit(
            plan_type="HMO",
            department_code="CARD",
            procedure_code="99213",
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRH",
            with_referral=True,
            referral_npi="NPI999",
            referral_visits_authorized=1,
            referral_valid_from="2026-08-01",
            referral_valid_until="2026-09-30",
            allowed_amount_cents=0,
        )
        return ctx

    def test_checkin_consumes_referral_visit(self, api):
        """PRD §3.6: "Two consumptions ride along with arrival: the matched
        referral's `visits_consumed` increments by one, which may tip it into
        `EXHAUSTED` per §3.3, and the authorization covering the visit moves
        `APPROVED` → `CONSUMED`."
        PRD §3.6: "On arrival day a `FrontDeskAgent` checks the patient in,
        moving the visit `READY` → `ARRIVED`"

        Design: Difficulty/transitive_cascade/checkin_referral_consume_then_exhaust
        """
        ctx = self._hmo_ready_visit_with_referral(api)
        assert ctx["appointment"]["referral_id"] == ctx["referral"]["id"]

        arrived = validate_success(
            api.check_in(ctx["appointment"]["id"], {}, FD), 200
        )
        assert arrived["status"] == "ARRIVED"

        referral = get_referral(ctx["referral"]["id"])
        assert referral["visits_consumed"] == 1

    def test_checkin_exhausts_single_visit_referral(self, api):
        """PRD §3.3: "When a check-in increments `visits_consumed` so that it
        reaches `visits_authorized`, the referral moves `OPEN` → `EXHAUSTED`
        and future matching sweeps skip it."

        Design: Difficulty/transitive_cascade/checkin_referral_consume_then_exhaust
        """
        ctx = self._hmo_ready_visit_with_referral(api)
        validate_success(api.check_in(ctx["appointment"]["id"], {}, FD), 200)
        referral = get_referral(ctx["referral"]["id"])
        assert referral["visits_consumed"] == 1
        assert referral["status"] == "EXHAUSTED"


class TestCheckInStateAdmissibility:
    def test_checkin_before_ready_rejected_and_no_ticket(self, api):
        """PRD §3.6: "On arrival day a `FrontDeskAgent` checks the patient in,
        moving the visit `READY` → `ARRIVED`"
        PRD §2.10: "then admissibility of the requested state transition — an
        action attempted against a resource in a state that does not permit it
        is rejected with `ERR_INVALID_STATE` (HTTP 409)"
        PRD §3.6: "an appointment's tickets are listed under the appointment."

        Design: Corner/state_machines/checkin_before_ready_returns_invalid_state
        """
        ctx = create_prechecked_visit(
            scheduled_start="2026-08-10T09:00:00Z",
            provider_code="DRS1",
            copay_cents=0,
            coinsurance_pct=0,
        )
        assert ctx["appointment"]["status"] == "PRE_CHECKED"
        res = api.check_in(ctx["appointment"]["id"], {}, FD)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        tickets_res = api.list_appointment_tickets(ctx["appointment"]["id"], FD)
        tickets, meta = validate_paginated(tickets_res)
        assert tickets == []
        assert meta["total_count"] == 0
