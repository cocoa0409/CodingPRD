"""Suspension cascade chains, completion follow-up cascade, and cross-entity state gating.

Depth coverage for the license->visit->prescription (and ->claim) suspension cascade,
the complete->follow-up cascade, and two cross-entity dependencies (visit transition
gated on physician status; claim reversal gated on visit void).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_physician_headers,
    board_headers,
    officer_headers,
    set_clock,
    setup_requested_visit,
    setup_approved_visit,
    setup_visit_with_active_controlled_rx,
    complete_visit,
)


class TestSuspensionCascadeDepth:
    """License suspend -> Visit VOIDED -> Prescription VOIDED (-> Claim REVERSED on insurance)."""

    def test_suspend_voids_cleared_visit(self, api):
        """PRD §3.4: "Every `Visit` currently in `COMPLIANCE_CLEARED` whose clearing
        `ComplianceCheck` has a `matched_license_id` equal to the suspended license
        transitions from `COMPLIANCE_CLEARED` to `VOIDED`, because its compliance clearance
        no longer rests on a valid license."

        Design: Difficulty/transitive_cascade/suspension_cascade_license_visit_prescription_depth3
        """
        ctx = setup_visit_with_active_controlled_rx(insured=False, dea_schedule="IV", drug_name="Lorazepam")
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        visit_after = validate_success(api.get_visit(ctx["visit"]["id"], phys_headers), 200)
        assert visit_after["status"] == "VOIDED", f"expected VOIDED, got {visit_after['status']}"
        lic_after = validate_success(api.get_state_license(ctx["license"]["id"], board_headers()), 200)
        assert lic_after["status"] == "SUSPENDED", f"expected SUSPENDED, got {lic_after['status']}"

    def test_voided_visit_voids_its_active_prescription(self, api):
        """PRD §3.4: "As part of a visit's transition to `VOIDED`, every `Prescription` on
        that visit (matched by `visit_id`) whose `status` is `ACTIVE` transitions from
        `ACTIVE` to `VOIDED`."

        Design: Difficulty/transitive_cascade/suspension_cascade_license_visit_prescription_depth3
        """
        ctx = setup_visit_with_active_controlled_rx(insured=False, dea_schedule="IV", drug_name="Lorazepam")
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        rx_after = validate_success(api.get_prescription(ctx["prescription"]["id"], phys_headers), 200)
        assert rx_after["status"] == "VOIDED", f"expected prescription VOIDED, got {rx_after['status']}"


class TestCompleteFollowUpCascade:
    """Completing a visit creates a FollowUp due 30 days after completion."""

    def test_complete_creates_open_follow_up(self, api):
        """PRD §3.8: "As a cascade of completion, the platform creates a `FollowUp`
        recording the just-completed visit through its `source_visit_id`, with `status`
        `OPEN`, a null `linked_visit_id`, and a computed `due_at`."

        Design: Difficulty/transitive_cascade/complete_cascade_visit_followup_depth2
        """
        ctx = setup_approved_visit(clock="2026-03-01T12:00:00.000Z", insured=False,
                                   visit_overrides={"scheduled_at": "2026-03-02T10:00:00.000Z"})
        completed = complete_visit(ctx["visit"]["id"], ctx["physician"]["id"])
        assert completed["status"] == "COMPLETED", f"expected COMPLETED, got {completed['status']}"
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        data, meta = validate_paginated(api.list_visit_follow_ups(ctx["visit"]["id"], phys_headers))
        assert meta["total_count"] == 1, f"expected one FollowUp, got {meta['total_count']}"
        assert data[0]["status"] == "OPEN", f"expected OPEN, got {data[0]['status']}"

    def test_follow_up_due_at_is_completion_plus_thirty_days(self, api):
        """PRD §3.8: "The `due_at` is the visit's completion time (its `updated_at` at the
        instant it reached `COMPLETED`) plus a follow-up interval of thirty days."

        Design: Difficulty/transitive_cascade/complete_cascade_visit_followup_depth2
        """
        # Clock held at 2026-03-01T12:00:00Z through completion -> completion time is that instant.
        ctx = setup_approved_visit(clock="2026-03-01T12:00:00.000Z", insured=False,
                                   visit_overrides={"scheduled_at": "2026-03-02T10:00:00.000Z"})
        complete_visit(ctx["visit"]["id"], ctx["physician"]["id"])
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        data, _ = validate_paginated(api.list_visit_follow_ups(ctx["visit"]["id"], phys_headers))
        assert data[0]["due_at"] == "2026-03-31T12:00:00.000Z", (
            f"due_at expected 2026-03-31T12:00:00.000Z (completion + 30d), got {data[0]['due_at']}"
        )


class TestCrossEntityStateDependency:
    """Visit transition gated on Physician status; Claim reversal gated on Visit void."""

    def test_run_compliance_blocked_when_physician_deactivated(self, api):
        """PRD §3.3: "This is permitted only when the visit is `REQUESTED` and the
        physician's own `status` is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/run_compliance_requires_physician_active
        """
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        validate_success(api.deactivate_physician(physician["id"], board_headers()), 200)
        phys_headers = make_physician_headers(physician["id"])
        res = api.run_compliance(visit["id"], phys_headers)
        validate_error(res, "ERR_INVALID_STATE")
        visit_after = validate_success(api.get_visit(visit["id"], phys_headers), 200)
        assert visit_after["status"] == "REQUESTED", (
            f"visit should not transition, got {visit_after['status']}"
        )

    def test_run_compliance_clears_when_physician_active(self, api):
        """PRD §3.3: "This is permitted only when the visit is `REQUESTED` and the
        physician's own `status` is `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/run_compliance_requires_physician_active
        """
        # Positive control on the same rule: an ACTIVE physician's identical visit clears.
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        phys_headers = make_physician_headers(physician["id"])
        cleared = validate_success(api.run_compliance(visit["id"], phys_headers), 200)
        assert cleared["status"] == "COMPLIANCE_CLEARED", (
            f"active physician's visit should clear, got {cleared['status']}"
        )

    def test_claim_reverses_only_as_consequence_of_visit_void(self, api):
        """PRD §3.4: "When the visit being voided is an `APPROVED_INSURANCE` visit, every
        `Claim` on that visit (matched by `visit_id`) whose `status` is `SUBMITTED` or
        `ADJUDICATED` transitions to `REVERSED`."
        PRD §3.4: "an `APPROVED_INSURANCE` visit governed by it likewise transitions to
        `VOIDED`."

        Design: Difficulty/cross_entity_state_dependency/claim_reversal_depends_on_visit_voided
        """
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = ctx["claim"]
        # Adjudicate so the claim is ADJUDICATED before suspend.
        api.adjudicate_claim(claim["id"], officer_headers())
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        visit_after = validate_success(api.get_visit(ctx["visit"]["id"], phys_headers), 200)
        assert visit_after["status"] == "VOIDED", f"expected visit VOIDED, got {visit_after['status']}"
        claim_after = validate_success(api.get_claim(claim["id"], officer_headers()), 200)
        assert claim_after["status"] == "REVERSED", f"expected claim REVERSED, got {claim_after['status']}"

    def test_submitted_claim_reverses_on_visit_void_without_adjudication(self, api):
        """PRD §3.4: "When the visit being voided is an `APPROVED_INSURANCE` visit, every
        `Claim` on that visit (matched by `visit_id`) whose `status` is `SUBMITTED` or
        `ADJUDICATED` transitions to `REVERSED`."

        Design: Difficulty/cross_entity_state_dependency/claim_reversal_depends_on_visit_voided
        """
        # Claim left SUBMITTED (never adjudicated); suspension cascade still reverses it
        # because the rule covers both SUBMITTED and ADJUDICATED.
        ctx = setup_approved_visit(
            insured=True,
            payer_overrides={"telehealth_parity": True, "copay_cents": 2500,
                             "covered_state_codes": ["CA"], "allowed_amount_cents": 8000},
            visit_overrides={"list_fee_cents": 10000},
        )
        claim = ctx["claim"]
        assert claim["status"] == "SUBMITTED", f"claim should start SUBMITTED, got {claim['status']}"
        api.suspend_state_license(ctx["license"]["id"], {"suspension_reason": "board action"}, board_headers())
        claim_after = validate_success(api.get_claim(claim["id"], officer_headers()), 200)
        assert claim_after["status"] == "REVERSED", (
            f"SUBMITTED claim should reverse on visit void, got {claim_after['status']}"
        )
