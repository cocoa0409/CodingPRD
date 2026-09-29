"""The two risk-score variants and the investigation fork."""

from test_helpers import (
    api_client,
    assert_instant_equals,
    create_product,
    get_incident_data,
    get_product_data,
    resolve_investigation_payload,
    set_clock,
    setup_frozen_product,
    setup_incident_under_investigation,
    setup_open_capa,
    validate_success,
    verify_corrective_action,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["safety_director_headers"]


class TestRiskVariantDivergenceAfterVerification:
    def _one_mitigated_and_one_untouched_incident(self):
        """Two in-set incidents worth 36.00 and 6.00 points, only the heavier of
        which is covered by a `VERIFIED` corrective action."""
        product = create_product()
        covered, action = setup_open_capa(product["id"])
        # HOSPITALIZATION weight 12 times RAIL_FRACTURE weight 3.0.
        assert float(covered["incident_points"]) == 36.00
        uncovered = setup_incident_under_investigation(
            product["id"], incident_type="SLIP_FALL", injury_severity="MINOR"
        )
        # MINOR weight 4 times SLIP_FALL weight 1.5.
        assert float(uncovered["incident_points"]) == 6.00
        verify_corrective_action(action["id"])
        return product, covered, uncovered

    def test_gross_variant_ignores_the_verified_corrective_action(self):
        """PRD §3.8: "`risk_score_gross` is the un-discounted exposure used for
        the liability dossier and regulatory disclosure: every incident in the set
        contributes its full `incident_points` regardless of corrective-action
        state."

        Design: Difficulty/dual_variant_calc/risk_score_gross_versus_mitigated_after_capa_verified
        """
        product, covered, _ = self._one_mitigated_and_one_untouched_incident()

        reread = get_product_data(product["id"])

        assert float(reread["risk_score_gross"]) == 42.00
        assert get_incident_data(covered["id"])["status"] == "CLOSED", (
            "the covered incident closed, yet still contributes in full"
        )

    def test_mitigated_variant_discounts_only_the_covered_incident(self):
        """PRD §3.8: "`risk_score_mitigated` is the figure the resume-ship gate
        reads: an incident that has at least one corrective action in `VERIFIED`
        contributes only one quarter of its `incident_points`, while every other
        in-set incident contributes its full points; a corrective action in
        `SUPERSEDED` never grants that credit."
        PRD §3.8: "For identical incident data the mitigated variant is therefore
        strictly lower than the gross one once any corrective action has been
        verified."

        Design: Difficulty/dual_variant_calc/risk_score_gross_versus_mitigated_after_capa_verified
        """
        product, _, _ = self._one_mitigated_and_one_untouched_incident()

        reread = get_product_data(product["id"])

        # A quarter of 36.00 plus the whole 6.00 of the uncovered incident.
        assert float(reread["risk_score_mitigated"]) == 15.00
        assert float(reread["risk_score_mitigated"]) < float(
            reread["risk_score_gross"]
        )
        assert (
            float(reread["risk_score_gross"]) - float(reread["risk_score_mitigated"])
        ) == 27.00

    def test_retention_stays_null_on_a_model_whose_design_was_never_frozen(self):
        """PRD §2.10: "If the design-freeze candidate is null, both
        `dhf_retention_until` and `retention_anchor_source` are null."
        PRD §2.10: "Both are null until the design is frozen, and both are
        recomputed on design freeze, on lot release, when a field incident closes
        through corrective-action verification, and on recall announcement."

        Design: Difficulty/dual_variant_calc/risk_score_gross_versus_mitigated_after_capa_verified
        """
        product, _, _ = self._one_mitigated_and_one_untouched_incident()

        reread = get_product_data(product["id"])

        assert reread["design_status"] == "DRAFT"
        assert reread["design_frozen_at"] is None
        assert reread["dhf_retention_until"] is None
        assert reread["retention_anchor_source"] is None


class TestInvestigationForkDivergesOnFinding:
    def _two_incidents_under_investigation(self):
        """A heavy 30.00-point incident that stays put, plus a light 6.00-point
        incident whose resolution is the branch under test."""
        product = create_product()
        heavy = setup_incident_under_investigation(
            product["id"],
            incident_type="RUNG_SEPARATION",
            injury_severity="HOSPITALIZATION",
        )
        light = setup_incident_under_investigation(
            product["id"], incident_type="SLIP_FALL", injury_severity="MINOR"
        )
        assert float(heavy["incident_points"]) == 30.00
        assert float(light["incident_points"]) == 6.00
        product = get_product_data(product["id"])
        assert float(product["risk_score_gross"]) == 36.00
        assert float(product["risk_score_mitigated"]) == 36.00
        return product, heavy, light

    def test_not_substantiated_branch_closes_the_incident_and_drops_it_from_both_sets(
        self,
    ):
        """PRD §3.8: "On the `NOT_SUBSTANTIATED` branch, `status` moves
        `UNDER_INVESTIGATION` → `NOT_SUBSTANTIATED`, `finding` is set to
        `NOT_SUBSTANTIATED`, `closed_at` is stamped with the logical clock,
        `requires_capa` stays false, `root_cause_code` stays null, and both risk
        scores are recomputed **with this incident removed from both input
        sets**."

        Design: Difficulty/non_linear_state_machine/field_incident_fork_diverges_on_finding
        """
        product, _, light = self._two_incidents_under_investigation()

        resolved = validate_success(
            api_client.resolve_investigation(
                light["id"],
                resolve_investigation_payload("NOT_SUBSTANTIATED", None),
                DIRECTOR,
            )
        )

        assert resolved["status"] == "NOT_SUBSTANTIATED"
        assert resolved["finding"] == "NOT_SUBSTANTIATED"
        assert_instant_equals(
            resolved["closed_at"], "2026-08-01T00:00:00Z", "closed_at"
        )
        assert resolved["requires_capa"] is False
        assert resolved["root_cause_code"] is None

        reread = get_product_data(product["id"])
        assert float(reread["risk_score_gross"]) == 30.00
        assert float(reread["risk_score_mitigated"]) == 30.00

    def test_root_cause_branch_keeps_the_incident_open_and_at_full_weight(self):
        """PRD §3.8: "On the `ROOT_CAUSE_IDENTIFIED` branch, `status` moves
        `UNDER_INVESTIGATION` → `ROOT_CAUSE_IDENTIFIED`, `finding` is set to
        `ROOT_CAUSE_IDENTIFIED`, the supplied `root_cause_code` is stored,
        `requires_capa` is set to true, and `closed_at` stays null."
        PRD §3.8: "On this branch the risk scores are **not** recomputed: the
        incident stays in both input sets at full weight."

        Design: Difficulty/non_linear_state_machine/field_incident_fork_diverges_on_finding
        """
        product, _, light = self._two_incidents_under_investigation()

        resolved = validate_success(
            api_client.resolve_investigation(
                light["id"],
                resolve_investigation_payload(
                    "ROOT_CAUSE_IDENTIFIED", "RIVET_SHEAR_MARGIN"
                ),
                DIRECTOR,
            )
        )

        assert resolved["status"] == "ROOT_CAUSE_IDENTIFIED"
        assert resolved["finding"] == "ROOT_CAUSE_IDENTIFIED"
        assert resolved["root_cause_code"] == "RIVET_SHEAR_MARGIN"
        assert resolved["requires_capa"] is True
        assert resolved["closed_at"] is None

        reread = get_product_data(product["id"])
        assert float(reread["risk_score_gross"]) == 36.00
        assert float(reread["risk_score_mitigated"]) == 36.00

    def test_a_not_substantiated_incident_never_anchors_design_history_retention(self):
        """PRD §3.8: "Because the retention computation of §2.10 only reads
        incidents whose `status` is `CLOSED`, a `NOT_SUBSTANTIATED` incident never
        anchors design-history retention despite carrying a `closed_at`."
        PRD §2.10: "The **incident-closure candidate** is the latest `closed_at`
        across the product's field incidents whose `status` is `CLOSED` and whose
        `closed_at` is set; incidents in any other status, including
        `NOT_SUBSTANTIATED`, never contribute."

        Design: Difficulty/non_linear_state_machine/field_incident_fork_diverges_on_finding
        """
        ctx = setup_frozen_product()
        frozen = ctx["product"]
        assert_instant_equals(
            frozen["dhf_retention_until"],
            "2033-08-01T00:00:00Z",
            "dhf_retention_until",
        )
        assert frozen["retention_anchor_source"] == "DESIGN_FREEZE"

        set_clock("2026-09-10T00:00:00Z")
        incident = setup_incident_under_investigation(frozen["id"])
        resolved = validate_success(
            api_client.resolve_investigation(
                incident["id"],
                resolve_investigation_payload("NOT_SUBSTANTIATED", None),
                DIRECTOR,
            )
        )
        assert_instant_equals(
            resolved["closed_at"], "2026-09-10T00:00:00Z", "closed_at"
        )

        reread = get_product_data(frozen["id"])
        assert_instant_equals(
            reread["dhf_retention_until"],
            "2033-08-01T00:00:00Z",
            "dhf_retention_until",
        )
        assert reread["retention_anchor_source"] == "DESIGN_FREEZE", (
            "the later NOT_SUBSTANTIATED closure is not a retention candidate"
        )
