"""Clearance gate derivation, mark-ready guardrail ordering, and cross-entity
state dependencies (PRD §2.10, §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_authorization_for,
    create_prechecked_visit,
    create_patient_payload,
    create_policy_for,
    create_registered_patient,
    get_appointment,
    get_success_data,
    post_eligibility_check,
    schedule_appointment,
    setup_procedure_visit_with_auth_and_payment,
    validate_error,
    validate_success,
    complete_registration_payload,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
SUP = TEST_USERS["access_supervisor_headers"]


class TestClearanceEvaluationOrder:
    def test_gate_clear_when_auth_and_deposit_satisfied(self, api):
        """PRD §3.5: "Finally the gate resolves: when demographics,
        authorization, and referral are not all satisfied, `registration_gate`
        is `BLOCKED`; otherwise, when a current estimate exists whose
        `deposit_required_cents` is above zero and `amount_collected_cents` has
        not yet reached it, the gate is `CLEAR_WITH_PAYMENT`; otherwise the
        gate is `CLEAR`."
        PRD §3.5: "Second, `auth_satisfied` is true when no authorization is
        needed, or when an authorization exists for this appointment in
        `APPROVED` status whose `valid_until` falls on or after the appointment
        date."

        Design: Difficulty/combinatorial_formula/clearance_status_evaluation_order_is_pinned
        """
        ctx = setup_procedure_visit_with_auth_and_payment()
        estimate = ctx["estimate"]
        # PAYER_VERIFIED: ded = min(100000, 0) = 0; coinsurance = 20% of
        # 100000 = 20000; capped at 500000 -> 20000.
        assert estimate["estimated_patient_responsibility_cents"] == 20000
        appt = ctx["appointment"]
        assert appt["amount_collected_cents"] == 10000
        assert appt["auth_satisfied"] is True
        assert appt["registration_gate"] == "CLEAR"

    def test_authorization_void_blocks_gate_despite_payment(self, api):
        """PRD §3.3: "An `AccessSupervisor` may void an `APPROVED`
        authorization — `APPROVED` → `VOIDED` — which likewise recomputes the
        owning appointment's clearance."
        PRD §3.5: "when demographics, authorization, and referral are not all
        satisfied, `registration_gate` is `BLOCKED`"

        Design: Difficulty/combinatorial_formula/clearance_status_evaluation_order_is_pinned
        """
        ctx = setup_procedure_visit_with_auth_and_payment()
        assert ctx["appointment"]["registration_gate"] == "CLEAR"

        validate_success(api.void_authorization(ctx["authorization"]["id"], SUP), 200)

        appt = get_appointment(ctx["appointment"]["id"])
        # Deposit remains fully collected, yet the missing authorization
        # dominates: the gate is BLOCKED.
        assert appt["amount_collected_cents"] == 10000
        assert appt["auth_satisfied"] is False
        assert appt["registration_gate"] == "BLOCKED"


class TestMarkReadyGuardrailOrder:
    def test_mark_ready_from_scheduled_returns_invalid_state(self, api):
        """PRD §2.10: "Authentication of the operator headers comes first, then
        role authorization, then existence of every referenced resource, then
        admissibility of the requested state transition — an action attempted
        against a resource in a state that does not permit it is rejected with
        `ERR_INVALID_STATE` (HTTP 409) — and only then the endpoint's business
        rules."
        PRD §3.5: "A `FinancialCounselor` moves a `PRE_CHECKED` visit to
        `READY` only when the gate allows it"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referral_business_safety
        """
        patient = create_registered_patient(
            first_name="Pri",
            last_name="One",
            date_of_birth="1981-01-15",
            sex_at_birth="F",
            primary_phone="+15556000001",
        )
        create_policy_for(patient["id"], plan_type="HMO", payer_id="PAYERH", member_id="MP1")
        appt = schedule_appointment(
            patient["id"],
            department_code="CARD",
            scheduled_start="2026-08-18T09:00:00Z",
            provider_code="DRI",
        )
        # Appointment is SCHEDULED (pre-check never performed) AND the HMO
        # referral is missing; the state check fires first.
        res = api.mark_ready(appt["id"], FC)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_mark_ready_from_cancelled_returns_invalid_state(self, api):
        """PRD §2.10: "then admissibility of the requested state transition —
        an action attempted against a resource in a state that does not permit
        it is rejected with `ERR_INVALID_STATE` (HTTP 409) — and only then the
        endpoint's business rules."
        PRD §3.4: "Cancellation is available to a `Registrar` from any
        pre-arrival state — `SCHEDULED`, `PRE_CHECKED`, or `READY` — and lands
        the appointment in the terminal `CANCELLED` status, with an optional
        `reason` recorded."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_referral_business_safety
        """
        patient = create_registered_patient(
            first_name="Pri",
            last_name="OneB",
            date_of_birth="1981-01-16",
            sex_at_birth="F",
            primary_phone="+15556000011",
        )
        create_policy_for(patient["id"], plan_type="HMO", payer_id="PAYERH", member_id="MP1B")
        appt = schedule_appointment(
            patient["id"],
            department_code="CARD",
            scheduled_start="2026-08-18T10:00:00Z",
            provider_code="DRIB",
        )
        validate_success(api.cancel_appointment(appt["id"], {}, REG), 200)
        # CANCELLED appointment with a missing HMO referral: the state check
        # still fires before the referral business rule.
        res = api.mark_ready(appt["id"], FC)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_auth_requirement_beats_deposit_shortfall(self, api):
        """PRD §3.5: "The guardrails fire in a pinned order. The referral
        requirement is evaluated first, so an `HMO` or `EPO` visit without a
        matched referral is rejected with `ERR_REFERRAL_REQUIRED` even when
        money is also outstanding. Next comes the authorization requirement,
        rejecting with `ERR_AUTH_REQUIRED` when a `PROCEDURE` or `IMAGING`
        visit — or one the payer flagged through `auth_required` — lacks a
        current `APPROVED` authorization. Only then does the collection
        requirement fire, rejecting with `ERR_DEPOSIT_SHORTFALL` (HTTP 402)
        while collected funds remain below the deposit target."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_auth_beats_fiscal_deposit
        """
        ctx = create_prechecked_visit(
            visit_type="PROCEDURE",
            department_code="SURG",
            procedure_code="47562",
            duration_minutes=60,
            scheduled_start="2026-08-19T09:00:00Z",
            provider_code="DRJ",
            copay_cents=0,
            coinsurance_pct=20,
            auth_required=True,
            deductible_remaining_cents=30000,
        )
        appointment_id = ctx["appointment"]["id"]
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 100000},
            FC,
        )
        estimate = validate_success(estimate_res, 201)
        assert estimate["deposit_required_cents"] == 11000
        # Auth missing AND deposit unpaid: ERR_AUTH_REQUIRED wins.
        res = api.mark_ready(appointment_id, FC)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_deposit_shortfall_fires_once_auth_satisfied(self, api):
        """PRD §3.5: "Next comes the authorization requirement, rejecting with
        `ERR_AUTH_REQUIRED` when a `PROCEDURE` or `IMAGING` visit — or one the
        payer flagged through `auth_required` — lacks a current `APPROVED`
        authorization. Only then does the collection requirement fire,
        rejecting with `ERR_DEPOSIT_SHORTFALL` (HTTP 402) while collected funds
        remain below the deposit target."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_auth_beats_fiscal_deposit
        """
        ctx = create_prechecked_visit(
            visit_type="PROCEDURE",
            department_code="SURG",
            procedure_code="47562",
            duration_minutes=60,
            scheduled_start="2026-08-19T09:00:00Z",
            provider_code="DRJ2",
            copay_cents=0,
            coinsurance_pct=20,
            auth_required=True,
            deductible_remaining_cents=30000,
        )
        appointment_id = ctx["appointment"]["id"]
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 100000},
            FC,
        )
        estimate = validate_success(estimate_res, 201)
        assert estimate["deposit_required_cents"] == 11000
        create_authorization_for(
            ctx["patient"]["id"], appointment_id, valid_until="2026-09-30"
        )
        # With the authorization in place, the unpaid deposit surfaces.
        res = api.mark_ready(appointment_id, FC)
        validate_error(res, ApiErrorId.ERR_DEPOSIT_SHORTFALL)


class TestCrossEntityStateDependency:
    def test_precheck_rejected_while_patient_pre_registered(self, api):
        """PRD §3.4: "Pre-check requires the patient to be `REGISTERED` and a
        usable verification on file: an eligibility check for this appointment
        whose `result` is `VERIFIED` or `VERIFIED_WITH_AUTH` and whose
        `checked_at` falls within thirty days of the current date."
        PRD §2.10: "then admissibility of the requested state transition — an
        action attempted against a resource in a state that does not permit it
        is rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Difficulty/cross_entity_state_dependency/precheck_requires_patient_registered
        """
        ctx = create_prechecked_visit(
            register_patient=False,
            run_pre_check=False,
            scheduled_start="2026-08-25T09:00:00Z",
            provider_code="DRN",
            copay_cents=3500,
        )
        assert ctx["patient"]["status"] == "PRE_REGISTERED"
        assert ctx["check"]["result"] == "VERIFIED"
        res = api.pre_check(ctx["appointment"]["id"], REG)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_precheck_succeeds_after_registration_completes(self, api):
        """PRD §3.4: "Once coverage is verified, a `Registrar` advances the
        visit `SCHEDULED` → `PRE_CHECKED`."
        PRD §3.4: "Pre-check requires the patient to be `REGISTERED` and a
        usable verification on file"

        Design: Difficulty/cross_entity_state_dependency/precheck_requires_patient_registered
        """
        ctx = create_prechecked_visit(
            register_patient=False,
            run_pre_check=False,
            scheduled_start="2026-08-25T09:00:00Z",
            provider_code="DRN2",
            copay_cents=3500,
        )
        get_success_data(
            api.complete_registration(
                ctx["patient"]["id"], complete_registration_payload(), REG
            )
        )
        updated = validate_success(api.pre_check(ctx["appointment"]["id"], REG), 200)
        assert updated["status"] == "PRE_CHECKED"

    def test_mark_ready_rejected_without_authorization(self, api):
        """PRD §3.5: "Next comes the authorization requirement, rejecting with
        `ERR_AUTH_REQUIRED` when a `PROCEDURE` or `IMAGING` visit — or one the
        payer flagged through `auth_required` — lacks a current `APPROVED`
        authorization."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_authorization_approved
        """
        ctx = create_prechecked_visit(
            visit_type="PROCEDURE",
            department_code="SURG",
            procedure_code="47562",
            duration_minutes=60,
            scheduled_start="2026-08-26T09:00:00Z",
            provider_code="DRO",
            auth_required=True,
        )
        appointment_id = ctx["appointment"]["id"]
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 0},
            FC,
        )
        validate_success(estimate_res, 201)
        res = api.mark_ready(appointment_id, FC)
        validate_error(res, ApiErrorId.ERR_AUTH_REQUIRED)

    def test_mark_ready_succeeds_once_authorization_recorded(self, api):
        """PRD §3.3: "it enters `APPROVED` immediately, and its arrival
        recomputes the appointment's clearance, which may flip `auth_satisfied`
        to true."
        PRD §3.5: "A `FinancialCounselor` moves a `PRE_CHECKED` visit to
        `READY` only when the gate allows it: either `registration_gate` is
        `CLEAR`, or it is `CLEAR_WITH_PAYMENT` and `amount_collected_cents` has
        reached the `deposit_required_cents` of the latest non-`SUPERSEDED`
        estimate."

        Design: Difficulty/cross_entity_state_dependency/mark_ready_requires_authorization_approved
        """
        ctx = create_prechecked_visit(
            visit_type="PROCEDURE",
            department_code="SURG",
            procedure_code="47562",
            duration_minutes=60,
            scheduled_start="2026-08-26T09:00:00Z",
            provider_code="DRO2",
            auth_required=True,
        )
        appointment_id = ctx["appointment"]["id"]
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 0},
            FC,
        )
        validate_success(estimate_res, 201)
        create_authorization_for(
            ctx["patient"]["id"], appointment_id, valid_until="2026-09-30"
        )
        ready = validate_success(api.mark_ready(appointment_id, FC), 200)
        assert ready["status"] == "READY"
        assert ready["auth_satisfied"] is True


class TestReferralRequirement:
    def test_referral_required_on_hmo_mark_ready(self, api):
        """PRD §3.3: "When the primary policy's `plan_type` is `HMO` or `EPO`
        and no referral is matched to the visit, marking it ready is rejected
        with `ERR_REFERRAL_REQUIRED` (HTTP 422)."

        Design: Corner/errors/err_referral_required_on_mark_ready
        """
        ctx = create_prechecked_visit(
            plan_type="HMO",
            department_code="CARD",
            scheduled_start="2026-09-12T09:00:00Z",
            provider_code="DRRR",
        )
        appointment_id = ctx["appointment"]["id"]
        estimate_res = api.create_copay_estimate(
            appointment_id,
            {"policy_id": ctx["policy"]["id"], "allowed_amount_cents": 0},
            FC,
        )
        validate_success(estimate_res, 201)
        res = api.mark_ready(appointment_id, FC)
        validate_error(res, ApiErrorId.ERR_REFERRAL_REQUIRED)
