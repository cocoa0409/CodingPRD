"""Complaints and recall campaigns: complaint intake defaults, escalation
gating, recall-scope cascades onto batches, vacuous recovery percentages, and
termination compensation (PRD §2.7, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, create_complaint_payload, create_recall_campaign_payload,
    create_approved_nutrient_profile, create_ingredient, create_draft_formula,
    create_released_batch_scenario, create_recall_campaign, create_recall_scope,
    create_investigating_complaint,
)


def _minimal_formula(users, code):
    """A DRAFT formula sufficient as a complaint FK target."""
    profile = create_approved_nutrient_profile(users, profile_code="INF-0-6M")
    ing_a = create_ingredient(users, f"{code}-A", "Ingredient A",
                              "DAIRY_BASE", "HIGH_RISK", "REFRIGERATED")
    ing_b = create_ingredient(users, f"{code}-B", "Ingredient B",
                              "CARBOHYDRATE", "LOW_RISK", "AMBIENT")
    return create_draft_formula(users, code, f"{code} Product",
                                profile["id"], ing_a["id"], ing_b["id"])


class TestComplaintIntake:
    def test_new_complaint_is_received_and_not_adverse(self, api, users):
        """PRD §3.6: "New complaints begin in `RECEIVED`." and "The server
        assigns a `complaint_ref` in the format `C-{YYYYMMDD}-{seq}` and
        computes the boolean `is_adverse_event`: true whenever
        `complaint_type` is `ADVERSE_EVENT` or `ILLNESS`, or `severity` is
        `CRITICAL`, and false otherwise." A LOW QUALITY_DEFECT complaint is
        not an adverse event.

        Design: Corner/state_machines/complaint_initial_state_received
        """
        formula = _minimal_formula(users, "IF-CI-1")
        res = api.create_complaint(
            create_complaint_payload(product_formula_id=formula["id"]),
            users["ch"]["headers"])
        data = validate_success(res, 201)
        assert data["status"] == "RECEIVED"
        assert data["is_adverse_event"] is False


class TestComplaintEscalation:
    def test_escalation_rejected_when_not_warranted(self, api, users):
        """PRD §3.6: escalation "is gated by the escalation rule: the complaint
        must either have `is_adverse_event` true or `severity` equal to `HIGH`
        or `CRITICAL`; otherwise the escalation is rejected with
        `ERR_ESCALATION_NOT_WARRANTED` (HTTP 422)." A LOW QUALITY_DEFECT
        complaint meets neither branch.

        Design: Corner/errors/err_escalation_not_warranted
        """
        formula = _minimal_formula(users, "IF-ESC-1")
        complaint = create_investigating_complaint(
            users, formula["id"], complaint_type="QUALITY_DEFECT",
            severity="LOW", description="Minor packaging scuff")
        assert complaint["status"] == "INVESTIGATING"
        res = api.escalate_complaint(
            complaint["id"],
            {"escalation_reason": "Attempting unwarranted escalation"},
            users["ch"]["headers"])
        validate_error(res, ApiErrorId.ERR_ESCALATION_NOT_WARRANTED)


class TestRecallScopeCascade:
    def test_scope_creation_cascades_batch_to_recalled(self, api, users):
        """PRD §2.7: "Adding a `RecallScope` entry to a campaign transitions
        the referenced `ProductionBatch` from `RELEASED` to `RECALLED`."
        PRD §3.6: "New scope entries start in `PENDING`".

        Design: Difficulty/transitive_cascade/recall_scope_cascades_batch_to_recalled_and_flags_allocations
        """
        scenario = create_released_batch_scenario(users, batch_size_kg=200.000,
                                                  actual_yield_kg=195.000)
        batch = scenario["batch"]
        assert batch["status"] == "RELEASED"
        campaign = create_recall_campaign(
            users, reason="PATHOGEN_CONTAMINATION", recall_class="CLASS_I",
            scope_description="Potential Salmonella contamination in batch")
        scope = create_recall_scope(users, campaign["id"], batch["id"],
                                    quantity_shipped_kg=195.000)
        assert scope["status"] == "PENDING"
        batch_after = validate_success(api.get_production_batch(
            batch["id"], users["qm"]["headers"]))
        assert batch_after["status"] == "RECALLED", (
            f"Batch must cascade RELEASED -> RECALLED, got {batch_after['status']}")

    def test_scope_created_with_zero_recovered_and_batch_link(self, api, users):
        """PRD §3.6: "New scope entries start in `PENDING` with
        `quantity_recovered_kg` zero and `recovery_pct` computed as described
        below" — "otherwise it is `quantity_recovered_kg` divided by
        `quantity_shipped_kg`, multiplied by 100, rounded half-up to 2 decimal
        places." With nothing yet recovered of 195.000 kg shipped,
        recovery_pct is 0.00.

        Design: Difficulty/transitive_cascade/recall_scope_cascades_batch_to_recalled_and_flags_allocations
        """
        scenario = create_released_batch_scenario(users, batch_size_kg=200.000,
                                                  actual_yield_kg=195.000)
        campaign = create_recall_campaign(
            users, reason="PATHOGEN_CONTAMINATION", recall_class="CLASS_I")
        scope = create_recall_scope(users, campaign["id"],
                                    scenario["batch"]["id"],
                                    quantity_shipped_kg=195.000)
        assert scope["batch_id"] == scenario["batch"]["id"]
        assert scope["quantity_recovered_kg"] == 0
        assert scope["recovery_pct"] == 0.00


class TestVacuousRecoveryPercentage:
    def test_zero_shipped_quantity_yields_100_recovery(self, api, users):
        """PRD §3.6: "when `quantity_shipped_kg` is zero, `recovery_pct` is
        100.00 by vacuous completion".

        Design: Difficulty/boundary_precision_check/recovery_pct_zero_shipped_quantity
        """
        scenario = create_released_batch_scenario(users, batch_size_kg=50.000,
                                                  actual_yield_kg=48.000)
        campaign = create_recall_campaign(users)
        scope = create_recall_scope(users, campaign["id"],
                                    scenario["batch"]["id"],
                                    quantity_shipped_kg=0.000)
        assert scope["recovery_pct"] == 100.00, (
            f"Vacuous recovery must be 100.00, got {scope['recovery_pct']}")

    def test_zero_shipped_scope_still_recalls_batch(self, api, users):
        """PRD §2.7: "Adding a `RecallScope` entry to a campaign transitions
        the referenced `ProductionBatch` from `RELEASED` to `RECALLED`." The
        cascade does not depend on the shipped quantity.

        Design: Difficulty/boundary_precision_check/recovery_pct_zero_shipped_quantity
        """
        scenario = create_released_batch_scenario(users, batch_size_kg=50.000,
                                                  actual_yield_kg=48.000)
        campaign = create_recall_campaign(users)
        create_recall_scope(users, campaign["id"], scenario["batch"]["id"],
                            quantity_shipped_kg=0.000)
        batch_after = validate_success(api.get_production_batch(
            scenario["batch"]["id"], users["qm"]["headers"]))
        assert batch_after["status"] == "RECALLED"


class TestRecallTermination:
    def _recalled_scenario(self, users):
        scenario = create_released_batch_scenario(users, batch_size_kg=50.000,
                                                  actual_yield_kg=48.000)
        campaign = create_recall_campaign(users)
        scope = create_recall_scope(users, campaign["id"],
                                    scenario["batch"]["id"],
                                    quantity_shipped_kg=48.000)
        return scenario, campaign, scope

    def test_terminate_restores_batch_to_released(self, api, users):
        """PRD §3.6: "termination cascades every scope entry to `VERIFIED`
        regardless of prior state and restores every in-scope batch from
        `RECALLED` back to `RELEASED`." (Also PRD §2.7: "Terminating a
        campaign reverses that cascade: every batch in scope is restored from
        `RECALLED` to `RELEASED`.")

        Design: Difficulty/compensating_invariant/recall_terminate_restores_batch_to_released
        """
        scenario, campaign, _scope = self._recalled_scenario(users)
        recalled = validate_success(api.get_production_batch(
            scenario["batch"]["id"], users["qm"]["headers"]))
        assert recalled["status"] == "RECALLED"
        terminated = validate_success(api.terminate_recall_campaign(
            campaign["id"],
            {"termination_reason": "False alarm — lab error confirmed"},
            users["qm"]["headers"]))
        assert terminated["status"] == "TERMINATED"
        restored = validate_success(api.get_production_batch(
            scenario["batch"]["id"], users["qm"]["headers"]))
        assert restored["status"] == "RELEASED", (
            f"Batch must be restored to RELEASED, got {restored['status']}")

    def test_terminate_marks_scope_entries_verified(self, api, users):
        """PRD §3.6: "termination cascades every scope entry to `VERIFIED`
        regardless of prior state".

        Design: Difficulty/compensating_invariant/recall_terminate_restores_batch_to_released
        """
        _scenario, campaign, scope = self._recalled_scenario(users)
        validate_success(api.terminate_recall_campaign(
            campaign["id"], {"termination_reason": "Recall stood down"},
            users["qm"]["headers"]))
        scope_after = validate_success(api.get_recall_scope(
            scope["id"], users["qm"]["headers"]))
        assert scope_after["status"] == "VERIFIED", (
            f"Scope must be VERIFIED after termination, got {scope_after['status']}")


class TestRecallNotificationGate:
    def test_notify_rejected_when_no_scope_entries(self, api, users):
        """PRD §3.6: "It is refused with `ERR_RECALL_SCOPE_EMPTY` (HTTP 422)
        if the campaign has no scope entries".

        Design: Corner/errors/err_recall_scope_empty
        """
        campaign = validate_success(api.create_recall_campaign(
            create_recall_campaign_payload(scope_description="Empty scope test"),
            users["qm"]["headers"]), 201)
        res = api.notify_recall_campaign(campaign["id"], users["ra1"]["headers"])
        validate_error(res, ApiErrorId.ERR_RECALL_SCOPE_EMPTY)
