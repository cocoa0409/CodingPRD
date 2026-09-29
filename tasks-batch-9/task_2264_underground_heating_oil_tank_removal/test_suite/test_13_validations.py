"""Gates that let a request through once the condition they guard is satisfied."""
import pytest

from test_helpers import fixtures as fx, parse_instant, validate_success
from test_helpers.factories import work_order_payload
from test_helpers.test_users import COMPLIANCE_OFFICER, PROJECT_COORDINATOR


class TestClaimSubmissionGates:
    #: New Jersey gross costs of 200,000 cents stay inside the first cap tier.
    CLAIMED_CENTS = 200000
    SUBMISSION_INSTANT = "2026-08-06T13:00:00Z"

    def test_submission_succeeds_when_the_project_is_clear_and_the_amount_is_positive(
        self, api
    ):
        """PRD §3.9: "Submission from `DRAFT` requires the project to be in `ASSESSED`, `REMEDIATION_ACTIVE`, `CLEARED` or `CLOSED_NFA`, requires `eligible_amount_cents` to be strictly greater than zero — a zero-value claim is refused with `ERR_CLAIM_NOT_ELIGIBLE` — and, when the project's `contamination_disclosure_required` latch is true, requires that a `CONTAMINATION_FINDINGS` disclosure on the project already stand at `ACKNOWLEDGED`; a missing acknowledgement is refused with `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."
        PRD §3.9: "A claim is submitted by a `ComplianceOfficer` from `DRAFT` or from `INFO_REQUESTED`, transitioning to `SUBMITTED` with `submitted_at` stamped from the logical clock."
        PRD §3.9: "Under `PRELIMINARY_ESTIMATE`, the cap is applied to the gross figure first and the deductible is then subtracted from the already-capped figure: take the capped figure less `deductible_cents`, floor that difference at zero, and subtract `admin_fee_cents`."

        Design: Corner/validations/claim_submit_passes_when_every_gate_is_satisfied
        """
        ctx = fx.project_cleared()
        assert ctx["project"]["contamination_disclosure_required"] is False, (
            "a clean round never latches the disclosure requirement, so the "
            "acknowledgement gate does not apply"
        )

        claim = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.CLAIMED_CENTS
        )
        assert claim["admin_fee_cents"] == 7000, (
            "three and a half percent of the 200,000-cent capped figure is 7000, got "
            f"{claim['admin_fee_cents']}"
        )
        assert claim["eligible_amount_cents"] == 143000, (
            "200,000 capped, less the 50,000 New Jersey deductible, less the 7000 fee "
            f"is 143,000, got {claim['eligible_amount_cents']}"
        )

        submitted = validate_success(
            api.submit_trust_fund_claim(claim["id"], COMPLIANCE_OFFICER), 200
        )
        assert submitted["status"] == "SUBMITTED", (
            f"every gate is satisfied, so the claim advances, got {submitted['status']}"
        )
        assert parse_instant(submitted["submitted_at"]) == parse_instant(
            self.SUBMISSION_INSTANT
        ), (
            "the submission instant comes from the logical clock, got "
            f"{submitted['submitted_at']}"
        )
        assert submitted["eligible_amount_cents"] == 143000, (
            "submission does not disturb the eligibility breakdown, got "
            f"{submitted['eligible_amount_cents']}"
        )


class TestWorkOrderMethodDivergenceGate:
    OVERRIDE_REASON = "municipal engineer requires the slab to stay intact"

    def test_a_justified_divergence_from_the_recommendation_is_accepted(self, api):
        """PRD §3.4: "First, when the requested `method` differs from the project's `recommended_method`, the scheduler is overriding a computed regulatory recommendation and must justify it: `method_override_reason` is required in that case, and its absence is refused with `ERR_METHOD_OVERRIDE_REASON_REQUIRED`."
        PRD §3.1: "`recommended_method` is then `ABANDONMENT_IN_PLACE` when `method_score` is at least 55.00, and `REMOVAL` otherwise. Both fields are read-only outputs of the survey; the method actually executed is captured separately, as `decommission_method`, when the crew begins work."
        PRD §3.4: "A work order is created with `field_status` at `SCHEDULED` and `billing_status` at `UNBILLED`."

        Design: Corner/validations/work_order_with_override_reason_passes_the_method_divergence_gate
        """
        ctx = fx.project_at_surveyed()
        crew = fx.create_crew(crew_name="Crew Override OK")

        assert ctx["project"]["recommended_method"] == "REMOVAL", (
            "a score of 36.00 falls short of the 55.00 abandonment threshold, got "
            f"{ctx['project']['recommended_method']}"
        )
        assert ctx["project"]["method_score"] == pytest.approx(36.00, abs=0.01), (
            f"the survey under test must score 36.00, got {ctx['project']['method_score']}"
        )

        booked = validate_success(
            api.create_work_order(
                work_order_payload(
                    ctx["project"]["id"],
                    crew["id"],
                    method="ABANDONMENT_IN_PLACE",
                    method_override_reason=self.OVERRIDE_REASON,
                ),
                PROJECT_COORDINATOR,
            ),
            201,
        )
        assert booked["method"] == "ABANDONMENT_IN_PLACE", (
            f"the overriding method is what gets booked, got {booked['method']}"
        )
        assert booked["field_status"] == "SCHEDULED", (
            f"the booking opens in SCHEDULED, got {booked['field_status']}"
        )
        assert booked["method_override_reason"] == self.OVERRIDE_REASON, (
            f"the justification is stored, got {booked['method_override_reason']}"
        )

        stored = fx.read_work_order(booked["id"])
        assert stored["billing_status"] == "UNBILLED", (
            f"the billing dimension opens in UNBILLED, got {stored['billing_status']}"
        )
        assert fx.read_project(ctx["project"]["id"])["decommission_method"] is None, (
            "the executed method is frozen only when the crew begins work"
        )
