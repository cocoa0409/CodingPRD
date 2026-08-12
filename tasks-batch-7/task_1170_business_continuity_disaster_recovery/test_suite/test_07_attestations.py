"""Attestation readiness computation and the sign gate (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_process,
    create_attestation,
    create_contact,
    create_gap,
    make_attestation_signer_headers,
    make_risk_committee_headers,
    set_clock,
    setup_attestation_scenario,
    validate_error,
    validate_success,
)

READINESS_ORDER_QUOTE = (
    "Readiness is a strict top-to-bottom computation over the attestation's "
    "process, and the evaluation order is pinned because the gap counts feed "
    "the points, the points feed the subtotal, and the multiplier keys on a "
    "gap count."
)


class TestReadinessPinnedEvaluationOrder:
    def test_readiness_pinned_order_yields_seventy(self, api):
        """PRD §3.9: "Readiness is a strict top-to-bottom computation over the attestation's process, and the evaluation order is pinned because the gap counts feed the points, the points feed the subtotal, and the multiplier keys on a gap count."
        PRD §3.9: "Fifth, the capability leg contributes the capability base minus ten points per overdue gap, floored at zero."
        PRD §3.9: "Eighth, the open count is the number of the process's gaps in `OPEN` or `IN_PROGRESS` that are not overdue. Ninth, the multiplier is 0.8 when that open count is greater than zero, and 1.0 when it is zero."

        40 (plan) + max(0, 25 - 2*10) (capability) + 25 (recent MET exercise) = 70;
        the multiplier stays 1.0 because the two overdue gaps are not in open_count.

        Design: Difficulty/combinatorial_formula/attestation_readiness_pinned_evaluation_order
        """
        ctx = setup_attestation_scenario(
            process_name="TradeSettle",
            overdue_gap_severities=("MEDIUM", "LOW"))
        attestation = create_attestation(ctx["process"]["id"], ctx["signer"]["id"])
        assert attestation["readiness_score"] == 70, (
            f"40 + max(0,25-20) + 25 with multiplier 1.0 must be 70, "
            f"got {attestation['readiness_score']}"
        )

    def test_sign_at_pinned_order_score_captures_snapshot(self, api):
        """PRD §3.9: "the `readiness_score` at signing time must be at least 70, or the signing is rejected with `ERR_READINESS_BELOW_THRESHOLD` (HTTP 422)."
        PRD §3.9: "A successful signing records the acting contact in `signed_by_contact_id`, increments `version`, and captures the `snapshot_payload`: an immutable JSON record of the readiness inputs at the signing instant — the approved plan's identity and version, the capability states, the open-gap counts, and the exercise recency."

        The pinned-order score of exactly 70 clears the >= 70 gate; signing records
        the snapshot.

        Design: Difficulty/combinatorial_formula/attestation_readiness_pinned_evaluation_order
        """
        ctx = setup_attestation_scenario(
            process_name="TradeSettle",
            overdue_gap_severities=("MEDIUM", "LOW"))
        attestation = create_attestation(ctx["process"]["id"], ctx["signer"]["id"])
        signed = validate_success(
            api_client.sign_attestation(
                attestation["id"], {"signer_declaration": True},
                make_attestation_signer_headers(ctx["signer"]["id"])))
        assert signed["status"] == "SIGNED"
        assert signed["signed_by_contact_id"] == ctx["signer"]["id"]
        assert signed.get("snapshot_payload"), (
            "signing must capture the immutable snapshot_payload"
        )


class TestSignGateBoundary:
    def test_sign_gate_passes_at_exactly_seventy(self, api):
        """PRD §3.9: "the `readiness_score` at signing time must be at least 70, or the signing is rejected with `ERR_READINESS_BELOW_THRESHOLD` (HTTP 422)."
        PRD §2.7: "All comparison boundaries in scoring and target checks are inclusive: a measured value exactly equal to its target passes."

        A readiness of exactly 70 (40 + max(0,25-20) + 25) signs.

        Design: Difficulty/boundary_precision_check/attestation_sign_gate_exactly_seventy
        """
        ctx = setup_attestation_scenario(
            process_name="Treasury",
            overdue_gap_severities=("MEDIUM", "LOW"))
        attestation = create_attestation(ctx["process"]["id"], ctx["signer"]["id"])
        assert attestation["readiness_score"] == 70
        signed = validate_success(
            api_client.sign_attestation(
                attestation["id"], {"signer_declaration": True},
                make_attestation_signer_headers(ctx["signer"]["id"])))
        assert signed["status"] == "SIGNED", "the boundary value 70 passes the gate"

    def test_sign_gate_rejects_sixty_five(self, api):
        """PRD §3.9: "the `readiness_score` at signing time must be at least 70, or the signing is rejected with `ERR_READINESS_BELOW_THRESHOLD` (HTTP 422)."

        With three overdue gaps the capability leg floors at 0: 40 + 0 + 25 = 65,
        which the gate rejects.

        Design: Difficulty/boundary_precision_check/attestation_sign_gate_exactly_seventy
        """
        ctx = setup_attestation_scenario(
            process_name="Treasury2",
            overdue_gap_severities=("MEDIUM", "LOW", "LOW"))
        attestation = create_attestation(ctx["process"]["id"], ctx["signer"]["id"],
                                         attestation_type="CUSTOMER")
        assert attestation["readiness_score"] == 65, (
            f"40 + 0 + 25 must be 65, got {attestation['readiness_score']}"
        )
        rejected = api_client.sign_attestation(
            attestation["id"], {"signer_declaration": True},
            make_attestation_signer_headers(ctx["signer"]["id"]))
        validate_error(rejected, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD)


class TestReadinessReconciliation:
    def test_readiness_derived_field_reconciliation(self, api):
        """PRD §3.9: "While the attestation remains in `DRAFT`, every detail read recomputes the score against the live program state, so the draft always reflects current readiness."

        One overdue OPEN gap: 40 + max(0, 25-10) + 25 = 80 at creation; closing the
        gap reconciles the next read to 40 + 25 + 25 = 90.

        Design: Corner/cross_cutting_layers/readiness_derived_field_reconciliation
        """
        ctx = setup_attestation_scenario(
            process_name="RecProc", overdue_gap_severities=("MEDIUM",))
        signer_headers = make_attestation_signer_headers(ctx["signer"]["id"])
        attestation = create_attestation(ctx["process"]["id"], ctx["signer"]["id"])
        assert attestation["readiness_score"] == 80, (
            f"40 + max(0,25-10) + 25 must be 80, got {attestation['readiness_score']}"
        )
        gap = ctx["gaps"][0]
        validate_success(
            api_client.close_gap(gap["id"],
                                 make_risk_committee_headers(ctx["committee"]["id"])))
        reread = validate_success(api_client.get_attestation(attestation["id"],
                                                             signer_headers))
        assert reread["readiness_score"] == 90, (
            f"the DRAFT read must reconcile to 90 after the gap closes, "
            f"got {reread['readiness_score']}"
        )


class TestSignDeclarationFlag:
    def test_attestation_sign_requires_declaration_flag(self, api):
        """PRD §3.9: "The `AttestationSigner` signs with `signer_declaration` set to true — an absent or false declaration fails with `ERR_INVALID_REQUEST` — and the readiness gate must clear: the `readiness_score` at signing time must be at least 70, or the signing is rejected with `ERR_READINESS_BELOW_THRESHOLD` (HTTP 422)."

        signer_declaration false is a request-shape failure; the draft stays DRAFT.

        Design: Corner/validations/attestation_sign_requires_declaration_flag
        """
        signer = create_contact("Signer Sue", "Signer")
        process = create_active_process(signer["id"], name="DeclProc",
                                        criticality_tier="TIER_3")
        attestation = create_attestation(process["id"], signer["id"],
                                         attestation_type="CUSTOMER")
        signer_headers = make_attestation_signer_headers(signer["id"])
        rejected = api_client.sign_attestation(
            attestation["id"], {"signer_declaration": False}, signer_headers)
        validate_error(rejected, ApiErrorId.ERR_INVALID_REQUEST)
        reread = validate_success(api_client.get_attestation(attestation["id"],
                                                             signer_headers))
        assert reread["status"] == "DRAFT"
