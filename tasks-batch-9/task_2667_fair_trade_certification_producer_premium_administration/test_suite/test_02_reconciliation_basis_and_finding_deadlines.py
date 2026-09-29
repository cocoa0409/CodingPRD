"""Reconciling declared volumes against a counterparty, and dating a fresh finding."""

from test_helpers import (
    AUDITOR,
    AUDITOR_1_ID,
    OFFICER,
    assert_instant,
    assert_pct,
    assert_score,
    assert_volume,
    expected_variance_pct,
    factories as f,
    validate_success,
)


def _two_window_trade_history(api):
    """Two monthly windows, each holding one settled 12000 kg lot and one disputed 1000 kg lot."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    august_settled = f.record_trade(
        api, chain, 12000, declared_unit_price_cents_per_kg=400, contract_date="2026-08-05"
    )
    f.verify_trade(api, august_settled["id"], "VERIFIED")
    f.settle_trade(api, august_settled["id"])
    august_disputed = f.record_trade(
        api, chain, 1000, declared_unit_price_cents_per_kg=400, contract_date="2026-08-06"
    )
    f.verify_trade(api, august_disputed["id"], "DISPUTED")
    september_settled = f.record_trade(
        api, chain, 12000, declared_unit_price_cents_per_kg=400, contract_date="2026-09-05"
    )
    f.verify_trade(api, september_settled["id"], "VERIFIED")
    f.settle_trade(api, september_settled["id"])
    september_disputed = f.record_trade(
        api, chain, 1000, declared_unit_price_cents_per_kg=400, contract_date="2026-09-06"
    )
    f.verify_trade(api, september_disputed["id"], "DISPUTED")

    chain["august_report_id"] = f.file_volume_report(
        api, chain["producer_id"], chain["brand_id"], "2026-08-01", "2026-09-01", 12240
    )["id"]
    chain["september_report_id"] = f.file_volume_report(
        api, chain["producer_id"], chain["brand_id"], "2026-09-01", "2026-10-01", 12240
    )["id"]
    return chain


class TestReconciliationBasisVariants:
    """The basis named on the reconcile request selects which counterparty total is compared."""

    def test_seller_basis_counts_only_settled_verified_volume_and_matches(self, api, clock):
        """Under SELLER_BASIS the August window counts only the 12000 kg verified and settled
        lot, so a 12240 kg declaration lands at 2.00 percent and is MATCHED.

        Design: Difficulty/dual_variant_calc/volume_report_seller_basis_matches_while_buyer_basis_flags_variance
        """
        chain = _two_window_trade_history(api)

        reconciled = validate_success(
            api.reconcile_volume_report(
                chain["august_report_id"], f.reconcile_payload("SELLER_BASIS"), OFFICER
            ),
            200,
        )

        assert reconciled["basis"] == "SELLER_BASIS"
        assert_volume(reconciled["counterparty_volume_kg"], 12000, "counterparty_volume_kg")
        assert_pct(reconciled["variance_pct"], "2.00", "variance_pct")
        assert_pct(
            reconciled["variance_pct"], expected_variance_pct(12240, 12000), "variance_pct"
        )
        assert reconciled["reconciliation_status"] == "MATCHED"

    def test_buyer_basis_also_counts_the_disputed_lot_and_flags_the_variance(self, api, clock):
        """Under BUYER_BASIS the September window also counts the 1000 kg disputed lot, so the
        same 12240 kg declaration lands at -5.85 percent and is VARIANCE_FLAGGED.

        Design: Difficulty/dual_variant_calc/volume_report_seller_basis_matches_while_buyer_basis_flags_variance
        """
        chain = _two_window_trade_history(api)

        reconciled = validate_success(
            api.reconcile_volume_report(
                chain["september_report_id"], f.reconcile_payload("BUYER_BASIS"), OFFICER
            ),
            200,
        )

        assert reconciled["basis"] == "BUYER_BASIS"
        assert_volume(reconciled["counterparty_volume_kg"], 13000, "counterparty_volume_kg")
        assert_pct(reconciled["variance_pct"], "-5.85", "variance_pct")
        assert_pct(
            reconciled["variance_pct"], expected_variance_pct(12240, 13000), "variance_pct"
        )
        assert reconciled["reconciliation_status"] == "VARIANCE_FLAGGED"

    def test_only_the_flagging_basis_suspends_the_holder_and_its_node(self, api, clock):
        """The MATCHED reconciliation leaves the producer CERTIFIED, while the flagged one
        suspends it for VOLUME_VARIANCE and cascades SUSPENDED onto its node.

        Design: Difficulty/dual_variant_calc/volume_report_seller_basis_matches_while_buyer_basis_flags_variance
        """
        chain = _two_window_trade_history(api)

        validate_success(
            api.reconcile_volume_report(
                chain["august_report_id"], f.reconcile_payload("SELLER_BASIS"), OFFICER
            ),
            200,
        )
        after_match = f.read_holder(api, chain["producer_id"])
        assert after_match["certificate_status"] == "CERTIFIED"

        validate_success(
            api.reconcile_volume_report(
                chain["september_report_id"], f.reconcile_payload("BUYER_BASIS"), OFFICER
            ),
            200,
        )

        holder = f.read_holder(api, chain["producer_id"])
        assert holder["certificate_status"] == "SUSPENDED"
        assert holder["suspension_reason"] == "VOLUME_VARIANCE"
        assert f.read_node(api, chain["seller_node_id"])["status"] == "SUSPENDED"


class TestFindingDeadlineFromPreInsertScore:
    """A finding is dated from the score the holder held before that finding was inserted."""

    def test_two_findings_raised_at_one_instant_carry_different_deadlines(self, api, clock):
        """The first critical finding is dated from a score of 100 with fourteen grace days, the
        second from the already reduced score of 60 with none.

        Design: Difficulty/combinatorial_formula/nonconformity_deadline_derived_from_pre_insert_compliance_score_mode_c
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(
            api, producer["holder_id"], "2026-08-01", "2026-08-05",
            auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
        )

        first = f.raise_finding(
            api, audit["id"], "CRITICAL", "FT-4.2.1",
            "Premium payment records missing for two harvests",
        )
        second = f.raise_finding(
            api, audit["id"], "CRITICAL", "FT-3.1.4",
            "Committee minutes absent for the whole fiscal year",
        )

        assert_score(first["compliance_score_at_raise"], 100, "compliance_score_at_raise")
        assert_instant(first["deadline_at"], "2026-08-11T00:00:00Z", "deadline_at")
        assert first["escalation_grace_days"] == 14, (
            f"expected 14 grace days, got {first['escalation_grace_days']}"
        )
        assert_score(second["compliance_score_at_raise"], 60, "compliance_score_at_raise")
        assert_instant(second["deadline_at"], "2026-08-04T00:00:00Z", "deadline_at")
        assert second["escalation_grace_days"] == 0, (
            f"expected 0 grace days, got {second['escalation_grace_days']}"
        )

    def test_holder_and_audit_aggregates_settle_after_both_findings(self, api, clock):
        """Both critical findings leave the holder scoring 20 with two open criticals, and the
        audit counting two findings at REPORT_PENDING.

        Design: Difficulty/combinatorial_formula/nonconformity_deadline_derived_from_pre_insert_compliance_score_mode_c
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(
            api, producer["holder_id"], "2026-08-01", "2026-08-05",
            auditor_user_id=AUDITOR_1_ID, audit_type="SURVEILLANCE",
        )

        f.raise_finding(
            api, audit["id"], "CRITICAL", "FT-4.2.1",
            "Premium payment records missing for two harvests",
        )
        f.raise_finding(
            api, audit["id"], "CRITICAL", "FT-3.1.4",
            "Committee minutes absent for the whole fiscal year",
        )

        holder = f.read_holder(api, producer["holder_id"])
        assert_score(holder["compliance_score"], 20)
        assert holder["open_critical_count"] == 2, (
            f"expected 2 open criticals, got {holder['open_critical_count']}"
        )
        reread = f.read_audit(api, audit["id"], AUDITOR)
        assert reread["nonconformity_count"] == 2
        assert reread["open_nonconformity_count"] == 2
        assert reread["status"] == "REPORT_PENDING"
