"""Customer profile, risk score, and adverse-event escalation cascade.

PRD §3.2 declares the customer_risk_score formula:
  base from declarative fields × (1 + 0.25 × adverse_event_count).
PRD §3.6 declares the adverse-event escalate cascade:
  AdverseEvent.OPEN → ESCALATED ⇒ Customer.adverse_event_count++ ⇒
  Customer.risk_score recompute.

The cascade depth is two: escalate updates count, count recomputation
yields a new score.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ATTENDING_PHYSICIAN_ID,
    AE_MULTIPLIER_STEP,
    ALLERGY_WEIGHT,
    ApiErrorId,
    NURSE_ID,
    PREGNANCY_WEIGHT,
    TEST_USERS,
    api_client,
    approve_plan_via_attending,
    assert_customer,
    countersign_plan,
    create_customer,
    create_customer_payload,
    create_kyc_verified_customer,
    dob_for_age,
    escalate_adverse_event,
    file_adverse_event,
    file_adverse_event_payload,
    get_customer,
    iso_utc,
    make_customer_headers,
    setup_approved_plan_simple,
    setup_scheduled_appointment,
    sign_consent,
    submit_plan,
    utcnow,
    validate_error,
    validate_success,
)


# ===========================================================================
# Risk score — declarative variant (Rule 1 instance 2 / "base")
# ===========================================================================
class TestRiskScoreDeclarative:

    def test_risk_score_with_no_factors_is_zero(self, api):
        """PRD §3.2: "The risk-score calculation begins from a base
        of 0."

        Claim: clean health declaration, no allergies, no AE history
        → risk_score == 0.0.
        """
        customer = create_customer(age_years=30)
        assert_customer(customer)
        assert customer["risk_score"] == 0 or customer["risk_score"] == 0.0

    def test_risk_score_sums_declarative_weights(self, api):
        """PRD §3.2: "Pregnancy adds 30 to the base ... Each entry in
        allergies adds 5 to the base ... After the base is
        accumulated, an adverse-event multiplier is applied: the
        multiplier equals 1.0 plus 0.25 multiplied by the customer's
        adverse_event_count."

        Claim: pregnant + 2 allergies → 30 + 2×5 = 40.0 (no AE means
        multiplier 1.0).
        """
        customer = create_customer(
            age_years=30,
            health_declaration={
                "is_pregnant": True,
                "has_uncontrolled_hypertension": False,
                "has_active_infection": False,
                "has_bleeding_disorder": False,
            },
            allergies=["LIDOCAINE", "PENICILLIN"],
        )
        assert customer["risk_score"] == pytest.approx(40.0, abs=0.01)
        assert customer["adverse_event_count"] == 0


# ===========================================================================
# Risk score — ae_amplified variant
# ===========================================================================
# difficulty: dual_variant_calc/customer_risk_base_vs_ae_amplified_on_customer
class TestRiskScoreAEAmplified:
    """PRD §3.2: "Two variants of this computation exist: when
    adverse_event_count is exactly 0 the multiplier is 1.0 and the
    score depends purely on the declarative fields; when
    adverse_event_count is at least 1 the multiplier amplifies the
    same declarative inputs to a different final score."
    """

    def _build_pregnant_two_allergy_customer(self) -> dict:
        return create_customer(
            age_years=30,
            health_declaration={
                "is_pregnant": True,
                "has_uncontrolled_hypertension": False,
                "has_active_infection": False,
                "has_bleeding_disorder": False,
            },
            allergies=["LIDOCAINE", "PENICILLIN"],
        )

    def test_risk_score_base_variant_no_amplification(self, api):
        """PRD §3.2: "when adverse_event_count is exactly 0 the
        multiplier is 1.0 and the score depends purely on the
        declarative fields."

        Claim: with pregnancy (30) + 2 allergies (2×5) and no AE, the
        risk_score is exactly the unamplified base, 40.0.

        # difficulty: dual_variant_calc/customer_risk_base_vs_ae_amplified_on_customer
        """
        customer = self._build_pregnant_two_allergy_customer()
        assert customer["adverse_event_count"] == 0
        assert customer["risk_score"] == pytest.approx(40.0, abs=0.01)

    def test_risk_score_amplified_after_severe_ae_escalation(self, api):
        """PRD §3.6: "A SEVERE event always escalates: when created
        with severity of SEVERE (whether manually filed or auto-from-
        feedback) it is moved from OPEN to ESCALATED."
        PRD §3.6: "The escalate action — performed by the attending
        physician or by a senior physician — sets escalated_at to the
        server time, increments the customer's adverse_event_count,
        recomputes the customer's risk_score (with the new
        multiplier), and writes an audit entry of action AE_ESCALATED."

        Claim: filing a SEVERE adverse event auto-escalates →
        adverse_event_count becomes 1 → risk_score = 40 × 1.25 = 50.0.

        # difficulty: dual_variant_calc/customer_risk_base_vs_ae_amplified_on_customer
        """
        bundle = setup_scheduled_appointment()
        # Override the customer's declarative fields to reach base 40.
        # The simplest path: create a separate customer here, but the
        # appointment must reference that customer. We instead PATCH
        # the existing customer to set the declarative profile.
        cust_id = bundle["customer"]["id"]
        patch_resp = api.patch_customer(
            cust_id,
            {
                "health_declaration": {
                    "is_pregnant": True,
                    "has_uncontrolled_hypertension": False,
                    "has_active_infection": False,
                    "has_bleeding_disorder": False,
                },
                "allergies": ["LIDOCAINE", "PENICILLIN"],
            },
            make_customer_headers(cust_id),
        )
        # Tolerate either Customer-as-actor or Consultant-as-actor: if
        # the implementation rejects Customer-PATCH of these specific
        # fields, fall back to Consultant role.
        if patch_resp.status_code >= 400:
            patch_resp = api.patch_customer(
                cust_id,
                {
                    "health_declaration": {
                        "is_pregnant": True,
                        "has_uncontrolled_hypertension": False,
                        "has_active_infection": False,
                        "has_bleeding_disorder": False,
                    },
                    "allergies": ["LIDOCAINE", "PENICILLIN"],
                },
                TEST_USERS["consultant_headers"],
            )
        validate_success(patch_resp, 200)

        # Confirm base score.
        customer_pre = get_customer(cust_id)
        assert customer_pre["risk_score"] == pytest.approx(40.0, abs=0.01)
        assert customer_pre["adverse_event_count"] == 0

        # File a SEVERE adverse event on the scheduled appointment.
        # PRD §3.6 says SEVERE always escalates on creation.
        ae = file_adverse_event(
            appointment_id=bundle["appointment"]["id"],
            severity="SEVERE",
            description="Test cascade",
            actor_doctor_id=bundle["attending_doctor_id"],
        )
        assert ae["severity"] == "SEVERE"
        # PRD §3.6: SEVERE auto-escalates so status reaches ESCALATED.
        assert ae["status"] == "ESCALATED", (
            f"PRD §3.6: SEVERE event auto-escalates; got status "
            f"{ae['status']!r}"
        )

        customer_post = get_customer(cust_id)
        assert customer_post["adverse_event_count"] == 1, (
            f"adverse_event_count must increment after SEVERE AE "
            f"escalation, got {customer_post['adverse_event_count']}"
        )
        assert customer_post["risk_score"] == pytest.approx(50.0, abs=0.05), (
            f"PRD §3.2 amplified multiplier 1.25 × base 40 = 50.0; "
            f"got {customer_post['risk_score']}"
        )


# ===========================================================================
# Adverse-event escalation cascade — depth 2 (Rule 4 instance 2)
# ===========================================================================
class TestAdverseEventEscalateCascade:
    """PRD §3.6 cascade: AE.OPEN → ESCALATED triggers
    Customer.adverse_event_count++, which triggers Customer.risk_score
    recompute. Depth 2.
    """

    def test_escalate_moderate_ae_increments_count_and_score(self, api):
        """PRD §3.6: "The escalate action — performed by the attending
        physician or by a senior physician — sets escalated_at to the
        server time, increments the customer's adverse_event_count,
        recomputes the customer's risk_score (with the new
        multiplier), and writes an audit entry of action AE_ESCALATED."

        Claim: a MODERATE AE in OPEN can be escalated; after escalate,
        AdverseEvent.status == 'ESCALATED', Customer.adverse_event_count
        == 1, and Customer.risk_score reflects the new multiplier on
        the same declarative inputs.

        # difficulty: transitive_cascade/adverse_event_escalation_cascade_depth_2
        """
        bundle = setup_scheduled_appointment()
        cust_id = bundle["customer"]["id"]
        # Set declarative profile to base 40.
        patch_resp = api.patch_customer(
            cust_id,
            {
                "health_declaration": {
                    "is_pregnant": True,
                    "has_uncontrolled_hypertension": False,
                    "has_active_infection": False,
                    "has_bleeding_disorder": False,
                },
                "allergies": ["LIDOCAINE", "PENICILLIN"],
            },
            make_customer_headers(cust_id),
        )
        if patch_resp.status_code >= 400:
            patch_resp = api.patch_customer(
                cust_id,
                {
                    "health_declaration": {
                        "is_pregnant": True,
                        "has_uncontrolled_hypertension": False,
                        "has_active_infection": False,
                        "has_bleeding_disorder": False,
                    },
                    "allergies": ["LIDOCAINE", "PENICILLIN"],
                },
                TEST_USERS["consultant_headers"],
            )
        validate_success(patch_resp, 200)

        # File a MODERATE AE (stays OPEN).
        ae = file_adverse_event(
            appointment_id=bundle["appointment"]["id"],
            severity="MODERATE",
            description="Cascade depth 2 setup",
            actor_doctor_id=bundle["attending_doctor_id"],
        )
        assert ae["status"] == "OPEN"

        # Customer score still base (no escalation yet).
        pre = get_customer(cust_id)
        assert pre["adverse_event_count"] == 0
        assert pre["risk_score"] == pytest.approx(40.0, abs=0.01)

        # Escalate explicitly (link 1 of the cascade).
        escalated = escalate_adverse_event(
            ae["id"], actor_doctor_id=bundle["attending_doctor_id"],
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["escalated_at"] is not None, (
            "PRD §3.6: escalate must set escalated_at"
        )

        # Verify links 2 + 3 of the cascade (count++ and score recompute).
        post = get_customer(cust_id)
        assert post["adverse_event_count"] == 1, (
            "PRD §3.6: escalate increments Customer.adverse_event_count"
        )
        assert post["risk_score"] == pytest.approx(50.0, abs=0.05), (
            f"PRD §3.6 + §3.2: escalate triggers risk recompute; "
            f"expected 50.0, got {post['risk_score']}"
        )


# ===========================================================================
# Customer underage gate (PRD §3.3)
# ===========================================================================
class TestCustomerAgeGate:

    def test_underage_customer_submit_rejected(self, api):
        """PRD §3.3: "that the customer's age at submission time is at
        least 18 (ERR_CUSTOMER_UNDERAGE, HTTP 422)."

        Claim: customer aged 17 → plan submit yields
        ERR_CUSTOMER_UNDERAGE.
        """
        # The simplest path: build a draft plan whose customer is 17.
        from test_helpers import setup_draft_plan
        ctx = setup_draft_plan(customer_overrides={"age_years": 17})
        res = api.submit_plan(
            ctx["plan"]["id"], TEST_USERS["consultant_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CUSTOMER_UNDERAGE.value)
