"""Audit scoring variants, decision gates, and the continuing audit chain."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    application_audits,
    assert_certificate,
    assert_instant_equal,
    audit_certificate,
    certificate_listing,
    close_nc,
    decide_audit,
    get_audit,
    make_decision_maker,
    make_decision_maker_headers,
    make_nonconformity,
    setup_granted_chain,
    setup_reported_chain,
    setup_started_chain,
    start_second_audit,
    submit_report,
    validate_error,
)

ADMIN = TEST_USERS["scheme_admin_headers"]


def _build_chain_with_ncs(api, grades):
    """Started chain + one finding per grade. Returns (chain, ncs)."""
    chain = setup_started_chain()
    ncs = [
        make_nonconformity(chain.audit["id"], chain.auditor["id"], grade=grade,
                           clause_ref=f"SQF 2.4.{i + 1}",
                           description=f"{grade.lower()} finding {i + 1}")
        for i, grade in enumerate(grades)
    ]
    return chain, ncs


class TestDualVariantScore:
    def test_reported_score_full_weights_at_submit(self, api):
        """PRD §2.9: "Every nonconformity deducts from a base of 100 according
        to its `grade`: a `CRITICAL` finding weighs 25 points, a `MAJOR`
        finding weighs 10 points, and a `MINOR` finding weighs 3 points. The
        reported variant, frozen at report submission, deducts the full weight
        of every finding on the audit regardless of closure status."

        Design: Difficulty/dual_variant_calc/audit_score_reported_vs_resolved_divergence
        """
        chain, _ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "MAJOR", "MINOR"])
        reported = submit_report(chain.audit["id"], chain.auditor["id"],
                                 actual_days=2)
        # 100 - (25 + 25 + 10 + 3), full weights on identical NC data.
        assert reported["reported_score"] == 37

    def test_resolved_score_halved_weights_at_decision(self, api):
        """PRD §2.9: "The resolved variant, computed at the certification
        decision, deducts the full weight of every finding not yet `CLOSED`
        but only half weight — rounded down, so `CRITICAL` contributes 12,
        `MAJOR` contributes 5, and `MINOR` contributes 1 — for each `CLOSED`
        finding."
        PRD §3.6: "A rendered decision moves the audit from `REPORT_SUBMITTED`
        to `DECIDED`, computes and stores the `resolved_score`, stamps
        `decision_outcome`, `decision_maker_id`, and `decided_at`"

        Design: Difficulty/dual_variant_calc/audit_score_reported_vs_resolved_divergence
        """
        chain, ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "MAJOR", "MINOR"])
        submit_report(chain.audit["id"], chain.auditor["id"],
                      actual_days=2)
        for nc in ncs:
            close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        decided = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        # 100 - (12 + 12 + 5 + 1): floor-halved weights once CLOSED.
        assert decided["resolved_score"] == 70
        assert decided["decision_outcome"] == "GRANT"
        assert decided["status"] == "DECIDED"
        fresh = get_audit(chain.audit["id"])
        assert fresh["reported_score"] == 37
        assert fresh["resolved_score"] == 70
        assert fresh["reported_score"] != fresh["resolved_score"]


class TestClosureHalvingAndPassGate:
    def test_three_critical_reported_score(self, api):
        """PRD §2.9: "a `CRITICAL` finding weighs 25 points" and "The reported
        variant, frozen at report submission, deducts the full weight of every
        finding on the audit regardless of closure status."

        Design: Difficulty/combinatorial_formula/audit_score_weighted_deductions_with_closure_halving
        """
        chain, _ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "CRITICAL"])
        reported = submit_report(chain.audit["id"], chain.auditor["id"],
                                 actual_days=2)
        # 100 - 3 x 25.
        assert reported["reported_score"] == 25

    def test_three_critical_grant_blocked_then_deny_resolved(self, api):
        """PRD §3.6: "the resolved score per §2.9 must be at least the
        scheme's `pass_score`, boundary inclusive (`ERR_SCORE_BELOW_PASS`,
        422)."
        PRD §2.9: "The resolved variant, computed at the certification
        decision, deducts the full weight of every finding not yet `CLOSED`
        but only half weight — rounded down, so `CRITICAL` contributes 12"

        Design: Difficulty/combinatorial_formula/audit_score_weighted_deductions_with_closure_halving
        """
        chain, ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "CRITICAL"])
        submit_report(chain.audit["id"], chain.auditor["id"], actual_days=2)
        for nc in ncs:
            close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        # All three CLOSED: resolved would be 100 - 3 x 12 = 64 < pass 70.
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"},
                                make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_PASS, 422)
        assert get_audit(chain.audit["id"])["status"] == "REPORT_SUBMITTED"
        denied = decide_audit(chain.audit["id"], chain.dm["id"], "DENY")
        assert denied["resolved_score"] == 64
        assert denied["decision_outcome"] == "DENY"
        assert denied["status"] == "DECIDED"


class TestPassBoundary:
    def test_resolved_exactly_at_pass_grants(self, api):
        """PRD §2.9: "Granting additionally requires the resolved score to be
        at least the scheme's `pass_score`, with the boundary inclusive: a
        resolved score exactly equal to `pass_score` passes."

        Design: Difficulty/boundary_precision_check/resolved_score_exactly_at_pass_threshold_grants
        """
        chain, ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "MAJOR", "MINOR"])
        submit_report(chain.audit["id"], chain.auditor["id"], actual_days=2)
        for nc in ncs:
            close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        decided = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        # 100 - 12 - 12 - 5 - 1 == 70, exactly the scheme's pass_score.
        assert decided["resolved_score"] == 70
        assert decided["status"] == "DECIDED"
        assert decided["decision_outcome"] == "GRANT"

    def test_resolved_exactly_at_pass_issues_certificate(self, api):
        """PRD §2.9: "a resolved score exactly equal to `pass_score` passes."
        PRD §3.6: "A `GRANT` on an `INITIAL` audit issues the certificate: its
        `valid_from` is the decision's `decided_at` ... it starts `ACTIVE`"

        Design: Difficulty/boundary_precision_check/resolved_score_exactly_at_pass_threshold_grants
        """
        chain, ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "MAJOR", "MINOR"])
        submit_report(chain.audit["id"], chain.auditor["id"], actual_days=2)
        for nc in ncs:
            close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        certs = audit_certificate(chain.audit["id"])
        assert len(certs) == 1
        assert_certificate(certs[0])
        assert certs[0]["status"] == "ACTIVE"

    def test_grant_with_resolved_score_69_rejected(self, api):
        """PRD §3.6: "the resolved score per §2.9 must be at least the
        scheme's `pass_score`, boundary inclusive (`ERR_SCORE_BELOW_PASS`,
        422)."

        Design: Corner/validations/grant_with_resolved_score_69_rejected
        """
        # 2 CRITICAL + 1 MAJOR + 2 MINOR, all CLOSED:
        # resolved = 100 - 12 - 12 - 5 - 1 - 1 = 69 < 70.
        chain, ncs = _build_chain_with_ncs(
            api, ["CRITICAL", "CRITICAL", "MAJOR", "MINOR", "MINOR"])
        submit_report(chain.audit["id"], chain.auditor["id"], actual_days=2)
        for nc in ncs:
            close_nc(nc["id"], chain.client["id"], chain.auditor["id"])
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"},
                                make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_SCORE_BELOW_PASS, 422)
        assert get_audit(chain.audit["id"])["status"] == "REPORT_SUBMITTED"
        # A failed GRANT renders no decision and issues no certificate.
        assert audit_certificate(chain.audit["id"]) == []


class TestClosureGate:
    def test_grant_with_open_minor_nc_rejected(self, api):
        """PRD §3.6: "a `GRANT` carries two further gates: every
        nonconformity raised on the audit must be `CLOSED`
        (`ERR_OPEN_NCS_REMAIN`, 422)"

        Design: Corner/validations/grant_with_open_minor_nc_rejected
        """
        chain = setup_started_chain()
        make_nonconformity(chain.audit["id"], chain.auditor["id"],
                           grade="MINOR", clause_ref="SQF 2.6.1",
                           description="open minor")
        submit_report(chain.audit["id"], chain.auditor["id"], actual_days=1)
        # The resolved score would be 97 (>= 70), but the closure gate is
        # independent of the score gate.
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"},
                                make_decision_maker_headers(chain.dm["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_NCS_REMAIN, 422)
        assert get_audit(chain.audit["id"])["status"] == "REPORT_SUBMITTED"


class TestDecisionIndependence:
    def test_decision_by_linked_auditor_rejected(self, api):
        """PRD §2.7: "if the acting decision maker's `linked_auditor_id` is
        non-null and equals the audit's `auditor_id`, the decision is rejected
        with `ERR_DECISION_NOT_INDEPENDENT` (403)."

        Design: Corner/validations/decision_by_linked_auditor_rejected
        """
        chain = setup_reported_chain()
        linked = make_decision_maker(name="Self Reviewer",
                                     linked_auditor_id=chain.auditor["id"])
        resp = api.decide_audit(chain.audit["id"], {"outcome": "GRANT"},
                                make_decision_maker_headers(linked["id"]))
        validate_error(resp, ApiErrorId.ERR_DECISION_NOT_INDEPENDENT, 403)
        # An unlinked decision maker renders the decision successfully.
        decided = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        assert decided["decision_maker_id"] == chain.dm["id"]
        assert decided["status"] == "DECIDED"


class TestIssuanceAndChainProjection:
    def test_certificate_number_minted_on_issuance(self, api):
        """PRD §3.6: "it receives the next `certificate_number` in the global
        issuance sequence formatted as CERT-NNNNNN with a zero-padded
        six-digit number"
        PRD §3.6: "its `valid_from` is the decision's `decided_at`, its
        `valid_to` is `cert_validity_days` days later"

        Design: Corner/entities/certificate_number_minted_on_issuance
        """
        chain = setup_granted_chain()
        cert = chain.certificate
        # The first certificate issued in a fresh system.
        assert cert["certificate_number"] == "CERT-000001"
        # GRANT decided at the current logical time 2026-08-15T09:00:00Z;
        # cert_validity_days 1095.
        assert_instant_equal(cert["valid_from"], "2026-08-15T09:00:00Z")
        assert_instant_equal(cert["valid_to"], "2029-08-14T09:00:00Z")

    def test_certificate_visible_immediately_after_decision(self, api):
        """PRD §3.6: "A `GRANT` on an `INITIAL` audit issues the certificate
        ... publishes the DirectoryListing in `LISTED` status with `listed_at`
        equal to `decided_at`, and schedules the next audit in the chain."
        PRD §3.6: "The certificate an audit issued remains readable through
        the audit, as an array of zero or one entries."

        Design: Corner/consistency_model/certificate_visible_immediately_after_decision
        """
        chain = setup_reported_chain()  # zero findings
        decided = decide_audit(chain.audit["id"], chain.dm["id"], "GRANT")
        assert decided["status"] == "DECIDED"
        assert decided["resolved_score"] == 100
        assert decided["decision_outcome"] == "GRANT"
        # The whole cascade is visible in the very next reads.
        certs = audit_certificate(chain.audit["id"])
        assert len(certs) == 1
        assert certs[0]["status"] == "ACTIVE"
        listing = certificate_listing(certs[0]["id"])
        assert listing["status"] == "LISTED"
        audits = application_audits(chain.app["id"])
        assert len(audits) == 2  # the SURVEILLANCE successor exists

    def test_next_audit_window_gap_max_rule(self, api):
        """PRD §3.6: "Its `window_start` is the later of two instants:
        fourteen days after `decided_at`, or the decided audit's `window_end`
        plus the scheme's `min_audit_gap_days`. Its `window_end` extends
        `unannounced_min_window_days` beyond the start for an `UNANNOUNCED`
        audit and `announced_max_window_days` beyond the start otherwise."

        Design: Corner/calculations/next_audit_window_gap_max_rule
        """
        chain = setup_granted_chain()
        audits = application_audits(chain.app["id"])
        assert len(audits) == 2
        audit2 = audits[1]
        # Seq1 window ended 2026-09-14T00:00:00Z; + min_audit_gap_days 30 wins
        # over decided_at (2026-08-15T09:00:00Z) + 14d == 2026-08-29T09:00:00Z.
        assert audit2["audit_type"] == "SURVEILLANCE"  # 2 % 3 != 0
        assert_instant_equal(audit2["window_start"], "2026-10-14T00:00:00Z")
        assert_instant_equal(audit2["window_end"], "2026-11-13T00:00:00Z")

    def test_third_cycle_audit_auto_unannounced(self, api):
        """PRD §3.6: "Its `audit_type` is `UNANNOUNCED` when the new sequence
        number is an exact multiple of the scheme's `unannounced_every_n`, and
        `SURVEILLANCE` otherwise."
        PRD §3.6: "Its `window_end` extends `unannounced_min_window_days`
        beyond the start for an `UNANNOUNCED` audit"

        Design: Corner/calculations/third_cycle_audit_auto_unannounced
        """
        chain = setup_granted_chain()  # unannounced_every_n 3
        start_second_audit(chain)
        chain.audit2 = submit_report(chain.audit2["id"], chain.auditor["id"])
        chain.audit2 = decide_audit(chain.audit2["id"], chain.dm["id"], "GRANT")
        audits = application_audits(chain.app["id"])
        assert len(audits) == 3
        audit2, audit3 = audits[1], audits[2]
        assert audit2["audit_type"] == "SURVEILLANCE"  # 2 % 3 != 0
        assert audit3["sequence_number"] == 3
        assert audit3["audit_type"] == "UNANNOUNCED"  # 3 % 3 == 0
        # Seq2 ended 2026-11-13T00:00:00Z; + gap 30d -> 2026-12-13 start;
        # unannounced length is unannounced_min_window_days 60.
        assert_instant_equal(audit3["window_start"], "2026-12-13T00:00:00Z")
        assert_instant_equal(audit3["window_end"], "2027-02-11T00:00:00Z")
