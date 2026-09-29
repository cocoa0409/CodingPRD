"""The rolling and lifetime scores, and the material-finding cascade."""

from test_helpers import (
    AUDITOR,
    BREEDER,
    OFFICER,
    OFFICER_THREE,
    OFFICER_TWO,
    ApiErrorId,
    add_line_item,
    advance_clock,
    draft_report,
    finalize_engagement_payload,
    licensed_quota,
    opened_audit_engagement,
    royalty_chain_with_accepted_report,
    validate_error,
    validate_success,
)


class TestRollingWindowVersusLifetime:
    """One late report, two scores, and what the clock does to each."""

    def _late_accepted_report(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=20000,
            variety_overrides={
                "denomination": "Cascade Crimson",
                "species": "Malus domestica",
                "breeder_code": "CC",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Riverbend Propagation",
        )
        report = draft_report(
            api, chain,
            period_code="2026M08",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-15T00:00:00Z",
            due_at="2026-08-20T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 5000)
        advance_clock(api, "2026-08-25T00:00:00Z")
        chain["report"] = validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        chain["report_id"] = report["id"]
        chain["report"] = validate_success(
            api.accept_royalty_report(report["id"], OFFICER_TWO)
        )
        return chain

    def test_an_accepted_late_report_costs_both_scores_six_points(self, api):
        """Submitting five days after the deadline stamps the report late, and
        acceptance materializes the six-point event that both scores read.

        PRD 2.11: "A royalty report that was submitted late and has been accepted contributes **6 points**, attributed to the instant the report was submitted."

        Design: Difficulty/dual_variant_calc/propagator_compliance_rolling_window_versus_lifetime_divergence
        """
        chain = self._late_accepted_report(api)
        assert chain["report"]["is_late"] is True

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 94
        assert propagator["lifetime_compliance_score"] == 94

    def test_the_rolling_score_recovers_once_the_event_ages_out(self, api):
        """Advancing the clock to 2026-12-25 puts the 2026-08-25 event outside the
        120-day window, so the rolling score returns to the baseline of 100.

        PRD 2.11: "`compliance_score` is 100 minus the sum of the points of the in-window events, clamped into 0 through 100."

        Design: Difficulty/dual_variant_calc/propagator_compliance_rolling_window_versus_lifetime_divergence
        """
        chain = self._late_accepted_report(api)

        advance_clock(api, "2026-12-25T00:00:00Z")

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 100

    def test_the_lifetime_score_ignores_age_and_never_rises(self, api):
        """The lifetime score keeps counting the same event after the window has
        slid past it, so it stays at 94 while the rolling score recovers, and the
        agreement is left alone throughout.

        PRD 2.11: "`lifetime_compliance_score` is 100 minus the sum of the points of **all** derived events, clamped the same way; because it ignores age, it never rises when the clock advances and is monotonically non-increasing for a fixed set of source rows."

        Design: Difficulty/dual_variant_calc/propagator_compliance_rolling_window_versus_lifetime_divergence
        """
        chain = self._late_accepted_report(api)

        advance_clock(api, "2026-12-25T00:00:00Z")

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["lifetime_compliance_score"] == 94
        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "ACTIVE"


class TestMaterialAuditFindingCascade:
    """Finalizing with a MATERIAL finding runs four cascade levels."""

    def _engagement_over_an_overrun_report(self, api):
        chain = royalty_chain_with_accepted_report(
            api,
            quality_tier="TIER_A",
            allocated_units=20000,
            requested_units=12000,
            reported_units=9800,
            variety_overrides={
                "denomination": "Cinder Rose",
                "species": "Rosa hybrida",
                "breeder_code": "CR",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Stonebridge Growers",
        )
        chain["engagement"] = opened_audit_engagement(api, chain)
        return chain

    def test_the_finding_disputes_the_report_and_zeroes_the_payable(self, api):
        """The engagement reaches FINDINGS_ISSUED, the still-unsettled report is
        driven to DISPUTED with its booked amount zeroed, and that un-booking
        empties the propagator's payable balance.

        PRD 3.9: "Independently of severity within the findings branch, when the audited report is still `ACCEPTED` and still `UNSETTLED` it moves to `DISPUTED` with `booked_amount_cents` set to 0, and that un-booking in turn causes the propagator's `royalty_payable_cents` to be re-derived; a report already `SETTLED` or `REVERSED` is left alone, though the engagement still reaches `FINDINGS_ISSUED` and the penalty still lands."

        Design: Difficulty/transitive_cascade/material_audit_finding_disputes_report_then_zeroes_payable_then_suspends_agreement_then_freezes_quota
        """
        chain = self._engagement_over_an_overrun_report(api)
        before_report = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert before_report["review_status"] == "ACCEPTED"
        assert before_report["booked_amount_cents"] == 458850
        before_propagator = validate_success(
            api.get_propagator(chain["propagator_id"], OFFICER)
        )
        assert before_propagator["royalty_payable_cents"] == 458850
        assert before_propagator["compliance_score"] == 85

        finalized = validate_success(
            api.finalize_audit_engagement(
                chain["engagement"]["id"],
                finalize_engagement_payload("MATERIAL", underreported_units=2200),
                AUDITOR,
            )
        )
        assert finalized["status"] == "FINDINGS_ISSUED"

        report = validate_success(api.get_royalty_report(chain["report_id"], BREEDER))
        assert report["review_status"] == "DISPUTED"
        assert report["booked_amount_cents"] == 0
        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_payable_cents"] == 0
        assert propagator["royalty_settled_cents"] == 0

    def test_the_finding_suspends_the_agreement_and_freezes_its_quota(self, api):
        """A MATERIAL finding suspends outright, recording AUDIT_FINDING rather
        than the compliance reason, and the suspension freezes the agreement's
        active quota.

        PRD 3.9: "A `MATERIAL` finding suspends the agreement outright, moving it `ACTIVE → SUSPENDED` with `suspension_reason` `AUDIT_FINDING`, regardless of what the recomputed score is."

        Design: Difficulty/transitive_cascade/material_audit_finding_disputes_report_then_zeroes_payable_then_suspends_agreement_then_freezes_quota
        """
        chain = self._engagement_over_an_overrun_report(api)
        before_agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert before_agreement["status"] == "ACTIVE"
        before_quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert before_quota["status"] == "ACTIVE"

        validate_success(
            api.finalize_audit_engagement(
                chain["engagement"]["id"],
                finalize_engagement_payload("MATERIAL", underreported_units=2200),
                AUDITOR,
            )
        )

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["suspension_reason"] == "AUDIT_FINDING"
        quota = validate_success(api.get_production_quota(chain["quota_id"], OFFICER))
        assert quota["status"] == "FROZEN"

    def test_the_unresolved_material_finding_blocks_reinstatement(self, api):
        """The finding both re-scores the propagator, replacing the overrun
        penalty with the 25-point material one, and raises the count that bars
        reinstatement even though the score is well above 70.

        PRD 3.5: "The propagator's `material_audit_finding_count` must be exactly 0, and any outstanding material finding is rejected with `ERR_MATERIAL_FINDING_UNRESOLVED` (HTTP 422) — a propagator carrying an unresolved material finding cannot be reinstated even when its rolling score has fully recovered."

        Design: Difficulty/transitive_cascade/material_audit_finding_disputes_report_then_zeroes_payable_then_suspends_agreement_then_freezes_quota
        """
        chain = self._engagement_over_an_overrun_report(api)

        validate_success(
            api.finalize_audit_engagement(
                chain["engagement"]["id"],
                finalize_engagement_payload("MATERIAL", underreported_units=2200),
                AUDITOR,
            )
        )

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["material_audit_finding_count"] == 1
        assert propagator["compliance_score"] == 75
        assert propagator["lifetime_compliance_score"] == 75

        validate_error(
            api.reinstate_agreement(chain["agreement_id"], OFFICER),
            ApiErrorId.ERR_MATERIAL_FINDING_UNRESOLVED.value,
            422,
        )


class TestReinstatementReportsTheScoreGateFirst:
    """A settled late report plus a material finding violates both gates at once."""

    def _propagator_failing_both_gates(self, api):
        chain = licensed_quota(
            api,
            quality_tier="TIER_B",
            territory_class="DOMESTIC",
            allocated_units=20000,
            season_code="2026S1",
            basis="PER_PLANT",
            variety_overrides={
                "denomination": "Inglewood Bramble",
                "species": "Rubus idaeus",
                "breeder_code": "IG",
                "base_royalty_cents_per_plant": 35,
                "base_royalty_cents_per_acre": 1200,
            },
            territory_codes=["US-WA"],
            propagator_name="Inglewood Nursery",
        )
        report = draft_report(
            api, chain, period_code="2026Q3",
            period_start="2026-08-01T00:00:00Z",
            period_end="2026-08-05T00:00:00Z",
            due_at="2026-08-10T00:00:00Z",
        )
        add_line_item(api, chain, report["id"], 100)
        advance_clock(api, "2026-08-15T00:00:00Z")
        validate_success(
            api.submit_royalty_report(report["id"], chain["propagator_headers"])
        )
        chain["report_id"] = report["id"]
        chain["accepted"] = validate_success(
            api.accept_royalty_report(report["id"], OFFICER_TWO)
        )
        chain["settled"] = validate_success(
            api.settle_royalty_report(report["id"], OFFICER_THREE)
        )
        chain["engagement"] = opened_audit_engagement(api, chain)
        chain["finalized"] = validate_success(
            api.finalize_audit_engagement(
                chain["engagement"]["id"],
                finalize_engagement_payload("MATERIAL", underreported_units=50),
                AUDITOR,
            )
        )
        return chain

    def test_a_settled_report_is_never_disputed_by_the_finding(self, api):
        """The money has already moved, so the findings limb that un-books a report
        leaves this one alone while the engagement still issues its findings.

        PRD 3.9: "Independently of severity within the findings branch, when the audited report is still `ACCEPTED` and still `UNSETTLED` it moves to `DISPUTED` with `booked_amount_cents` set to 0, and that un-booking in turn causes the propagator's `royalty_payable_cents` to be re-derived; a report already `SETTLED` or `REVERSED` is left alone, though the engagement still reaches `FINDINGS_ISSUED` and the penalty still lands."

        Design: Corner/validations/reinstate_blocked_by_both_gates_returns_the_compliance_error_first
        """
        chain = self._propagator_failing_both_gates(api)
        assert chain["accepted"]["late_fee_cents"] == 70
        assert chain["accepted"]["booked_amount_cents"] == 3570
        assert chain["finalized"]["status"] == "FINDINGS_ISSUED"

        report = validate_success(api.get_royalty_report(chain["report_id"], OFFICER))
        assert report["review_status"] == "ACCEPTED"
        assert report["settlement_status"] == "SETTLED"
        assert report["booked_amount_cents"] == 3570

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["royalty_settled_cents"] == 3570
        assert propagator["royalty_payable_cents"] == 0

    def test_the_two_surviving_penalties_add_up_and_the_audit_reason_wins(self, api):
        """The late filing keeps costing six points because the report was never
        disputed, and the material finding adds twenty-five, so the score is 69 and
        the suspension is labelled with the audit reason rather than the breach.

        PRD 3.5: "The precedence between the last two is pinned. When a `MATERIAL` finding also drops the rolling score below 70, `suspension_reason` ends up as `AUDIT_FINDING`: the audit reason is applied first, and the compliance recomputation that follows finds the agreement already `SUSPENDED` and leaves `suspension_reason` exactly as it is."

        Design: Corner/validations/reinstate_blocked_by_both_gates_returns_the_compliance_error_first
        """
        chain = self._propagator_failing_both_gates(api)

        propagator = validate_success(api.get_propagator(chain["propagator_id"], OFFICER))
        assert propagator["compliance_score"] == 69
        assert propagator["lifetime_compliance_score"] == 69
        assert propagator["material_audit_finding_count"] == 1

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["suspension_reason"] == "AUDIT_FINDING"
        assert validate_success(api.get_production_quota(chain["quota_id"], OFFICER))[
            "status"
        ] == "FROZEN"

    def test_both_gates_are_violated_and_the_score_gate_is_reported(self, api):
        """Reinstatement has two independent eligibility gates and this propagator
        fails both, so the answer names the score rather than the outstanding
        material finding, and nothing is reinstated.

        PRD 3.5: "Of the two coded checks the compliance-score gate is evaluated first, so a propagator failing both is told about its score."

        Design: Corner/validations/reinstate_blocked_by_both_gates_returns_the_compliance_error_first
        """
        chain = self._propagator_failing_both_gates(api)

        validate_error(
            api.reinstate_agreement(chain["agreement_id"], OFFICER),
            ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW.value,
            422,
        )

        agreement = validate_success(
            api.get_propagator_agreement(chain["agreement_id"], OFFICER)
        )
        assert agreement["status"] == "SUSPENDED"
        assert agreement["reinstatement_count"] == 0
