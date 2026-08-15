"""Release gating: the verdict ladder (blocking findings, obligations,
warning thresholds), the EMBEDDED/audit strict mode, cross-entity
preconditions on creation, and the CISO bypass."""
import pytest

from test_helpers import (
    ApiErrorId,
    SPEC_MIT,
    TEST_USERS,
    assert_release_gate,
    bypass_gate_payload,
    create_gate,
    create_product,
    create_scan,
    evaluate_gate,
    finding_for_vulnerability,
    fulfill_all_obligation_tickets,
    generate_notice,
    get_bom,
    get_product,
    list_boms,
    manifest_component_spec,
    process_scan,
    register_vulnerability,
    setup_blocked_product,
    setup_gate_ready,
    setup_product_with_completed_scan,
    validate_error,
    validate_success,
)

RELEASE_MGR = TEST_USERS["release_manager_headers"]
CISO = TEST_USERS["ciso_headers"]
SECURITY = TEST_USERS["security_headers"]


def _warning_specs(n):
    """n distinct permissive packages, each a finding target."""
    return [manifest_component_spec(
        package_url=f"pkg:npm/warn-{i}@1.0.0", declared_license_spdx="MIT")
        for i in range(n)]


def _register_high_vulns(product_id, count, cve_prefix):
    """Register `count` HIGH vulnerabilities, one per warn-N package, and
    return their findings (one finding per shipped entry, PRD §3.5)."""
    findings = []
    for i in range(count):
        vuln = register_vulnerability(
            cve_id=f"CVE-2026-{cve_prefix}{i:02d}", severity="HIGH",
            cvss_score=7.0,
            affected_package_url=f"pkg:npm/warn-{i}@1.0.0")
        findings.append(finding_for_vulnerability(product_id, vuln["id"]))
    return findings


class TestWarningThresholdBoundary:
    def test_exactly_three_warnings_conditional_pass(self, api):
        """PRD §3.7: "The verdict ladder is strict and ordered: ... more than
        three warnings fail it; between one and three warnings inclusive yield
        a `CONDITIONAL_PASS`". PRD §3.7: "The `warning_findings_count` tallies
        `RESTRICTED` entries lacking an approved license request plus `HIGH`
        findings still `OPEN` or `CONFIRMED`."

        Design: Difficulty/boundary_precision_check/warning_findings_threshold_exactly_3_vs_4
        """
        ctx = setup_gate_ready(manifest=_warning_specs(4),
                               product_overrides={"product_code": "BOUNDARY-3"})
        product_id = ctx["product"]["id"]
        findings = _register_high_vulns(product_id, 4, "601")
        # Retire one finding as a false positive: warnings count only OPEN or
        # CONFIRMED findings (PRD §3.7), leaving exactly three.
        validate_success(api.mark_false_positive(
            product_id, findings[0]["id"], SECURITY))

        evaluated = validate_success(
            evaluate_gate(product_id, ctx["gate"]["id"]))
        assert evaluated["blocking_findings_count"] == 0
        assert evaluated["warning_findings_count"] == 3
        assert evaluated["obligations_fulfilled_pct"] == pytest.approx(100.0)
        assert evaluated["evaluation_result"] == "CONDITIONAL_PASS"

    def test_four_warnings_fail(self, api):
        """PRD §3.7: "The verdict ladder is strict and ordered: any blocking
        finding fails the gate; obligations below one hundred percent fail it;
        more than three warnings fail it". Four OPEN HIGH findings sit
        strictly past the conditional ceiling.

        Design: Difficulty/boundary_precision_check/warning_findings_threshold_exactly_3_vs_4
        """
        ctx = setup_gate_ready(manifest=_warning_specs(4),
                               product_overrides={"product_code": "BOUNDARY-4"})
        product_id = ctx["product"]["id"]
        _register_high_vulns(product_id, 4, "602")

        evaluated = validate_success(
            evaluate_gate(product_id, ctx["gate"]["id"]))
        assert evaluated["blocking_findings_count"] == 0
        assert evaluated["warning_findings_count"] == 4
        assert evaluated["evaluation_result"] == "FAIL"


class TestObligationsPercentageBoundary:
    @staticmethod
    def _hundred_component_manifest():
        return [manifest_component_spec(
            package_url=f"pkg:npm/ob-{i:03d}@1.0.0", declared_license_spdx="MIT")
            for i in range(100)]

    def test_exactly_100_percent_passes(self, api):
        """PRD §3.7: "The `obligations_fulfilled_pct` is the share of the
        BOM's obligation tickets in `FULFILLED` or `WAIVED` status — fulfilled
        plus waived, divided by the total ticket count, multiplied by one
        hundred, rounded half-up to two decimal places." And the ladder:
        "a completely clean board yields a `PASS`." One hundred attribution
        tickets, all fulfilled, reach exactly 100.00.

        Design: Difficulty/boundary_precision_check/obligations_fulfilled_pct_exactly_100_vs_99_99
        """
        product = create_product(product_code="PCT-100")
        scan = create_scan(product["id"], self._hundred_component_manifest())
        process_scan(scan["id"])
        bom = list_boms(product["id"])[0]
        fulfill_all_obligation_tickets(product["id"])
        generate_notice(product["id"], bom["id"])
        gate = create_gate(product["id"], bom["id"])

        evaluated = validate_success(evaluate_gate(product["id"], gate["id"]))
        assert evaluated["obligations_fulfilled_pct"] == pytest.approx(100.0)
        assert evaluated["blocking_findings_count"] == 0
        assert evaluated["warning_findings_count"] == 0
        assert evaluated["evaluation_result"] == "PASS"

    def test_99_of_100_fulfilled_fails(self, api):
        """PRD §3.7: "The verdict ladder is strict and ordered: any blocking
        finding fails the gate; obligations below one hundred percent fail
        it". With 99 of 100 tickets fulfilled the share is 99.00 — one point
        short of the bar, and the gate fails.

        Design: Difficulty/boundary_precision_check/obligations_fulfilled_pct_exactly_100_vs_99_99
        """
        product = create_product(product_code="PCT-99")
        scan = create_scan(product["id"], self._hundred_component_manifest())
        process_scan(scan["id"])
        bom = list_boms(product["id"])[0]
        fulfill_all_obligation_tickets(product["id"], leave_unresolved=1)
        generate_notice(product["id"], bom["id"])
        gate = create_gate(product["id"], bom["id"])

        evaluated = validate_success(evaluate_gate(product["id"], gate["id"]))
        assert evaluated["obligations_fulfilled_pct"] == pytest.approx(99.0)
        assert evaluated["obligations_fulfilled_pct"] < 100.0
        assert evaluated["evaluation_result"] == "FAIL"


class TestStrictModeDualVariant:
    def _product_with_two_warnings(self, distribution_model, code):
        ctx = setup_gate_ready(distribution_model,
                               manifest=_warning_specs(2),
                               product_overrides={"product_code": code})
        _register_high_vulns(ctx["product"]["id"], 2,
                             "603" if distribution_model == "SaaS" else "604")
        return ctx

    def test_saas_two_warnings_conditional_pass(self, api):
        """PRD §3.7: "between one and three warnings inclusive yield a
        `CONDITIONAL_PASS`".

        Design: Difficulty/dual_variant_calc/release_gate_strict_mode_embedded_vs_saas
        """
        ctx = self._product_with_two_warnings("SaaS", "SAAS-GATE")
        evaluated = validate_success(
            evaluate_gate(ctx["product"]["id"], ctx["gate"]["id"]))
        assert evaluated["warning_findings_count"] == 2
        assert evaluated["evaluation_result"] == "CONDITIONAL_PASS"

    def test_embedded_two_warnings_fail(self, api):
        """PRD §3.7: "Two contexts forbid conditional passes entirely: for an
        `EMBEDDED` product, or while an audit engagement is active on the
        product, the conditional ceiling drops to zero and any warning at all
        fails the gate."

        Design: Difficulty/dual_variant_calc/release_gate_strict_mode_embedded_vs_saas
        """
        ctx = self._product_with_two_warnings("EMBEDDED", "EMBED-GATE")
        evaluated = validate_success(
            evaluate_gate(ctx["product"]["id"], ctx["gate"]["id"]))
        assert evaluated["warning_findings_count"] == 2
        assert evaluated["evaluation_result"] == "FAIL"


class TestGateCrossEntityDependencies:
    def test_gate_creation_refused_on_blocked_product(self, api,
                                                      release_manager_headers):
        """PRD §3.7: "Creation is refused unless the referenced BOM is
        `FINALIZED` — surfacing `ERR_BOM_NOT_FINALIZED` (HTTP 409) — and
        refused with `ERR_PRODUCT_BLOCKED` (HTTP 409) while the product is
        `BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/release_gate_depends_on_bom_and_product
        """
        ctx = setup_blocked_product(
            product_overrides={"product_code": "XENT-1"})
        assert ctx["bom"]["status"] == "FINALIZED"
        resp = api.create_release_gate(
            ctx["product"]["id"],
            {"bom_id": ctx["bom"]["id"], "release_version": "1.0.0"},
            release_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)

    def test_gate_creation_refused_for_superseded_bom(self, api,
                                                      release_manager_headers):
        """PRD §3.7: "Creation is refused unless the referenced BOM is
        `FINALIZED` — surfacing `ERR_BOM_NOT_FINALIZED` (HTTP 409)". PRD
        §3.3: "When a newer BOM for the same product reaches `FINALIZED`, the
        older `FINALIZED` BOM becomes `SUPERSEDED`" — and a SUPERSEDED BOM is
        no longer FINALIZED.

        Design: Difficulty/cross_entity_state_dependency/release_gate_depends_on_bom_and_product
        """
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": "XENT-1B"}, manifest=[SPEC_MIT])
        product_id = ctx["product"]["id"]
        old_bom = ctx["bom"]

        scan2 = create_scan(product_id, [
            SPEC_MIT,
            manifest_component_spec(package_url="pkg:npm/lgb@1.0.0",
                                    declared_license_spdx="LGPL-2.1"),
        ], analyst=ctx["analyst_headers"])
        process_scan(scan2["id"])

        superseded = get_bom(product_id, old_bom["id"])
        assert superseded["status"] == "SUPERSEDED"
        resp = api.create_release_gate(
            product_id, {"bom_id": old_bom["id"], "release_version": "2.0.0"},
            release_manager_headers)
        validate_error(resp, ApiErrorId.ERR_BOM_NOT_FINALIZED, 409)


class TestEvaluationSideEffects:
    def test_evaluation_computes_the_three_counts(self, api):
        """PRD §3.7: "The evaluation itself computes three numbers. The
        `blocking_findings_count` tallies entries whose
        `effective_classification` is `PROHIBITED` plus `CRITICAL` findings
        still `OPEN` or `CONFIRMED`. The `warning_findings_count` tallies
        `RESTRICTED` entries lacking an approved license request plus `HIGH`
        findings still `OPEN` or `CONFIRMED`. The `obligations_fulfilled_pct`
        is the share of the BOM's obligation tickets in `FULFILLED` or
        `WAIVED` status". With one permissive entry and no findings the counts
        are 0/0 and — the single attribution ticket being unresolved — the
        share is 0.00, so "obligations below one hundred percent fail it".

        Design: Corner/state_machines/release_gate_side_effect_execution
        """
        ctx = setup_gate_ready(manifest=[SPEC_MIT], fulfill_tickets=False,
                               product_overrides={"product_code": "SIDE-EFF"})
        evaluated = validate_success(
            evaluate_gate(ctx["product"]["id"], ctx["gate"]["id"]))
        assert_release_gate(evaluated)
        assert evaluated["blocking_findings_count"] == 0
        assert evaluated["warning_findings_count"] == 0
        assert evaluated["obligations_fulfilled_pct"] == pytest.approx(0.0)
        assert evaluated["evaluation_result"] == "FAIL"


class TestGateBypass:
    def _gate_with_warning(self, code):
        """Product with a gate whose evaluation records one HIGH warning;
        the product is never BLOCKED (a bypass requires that, PRD §3.7)."""
        ctx = setup_gate_ready(manifest=_warning_specs(1),
                               fulfill_tickets=False,
                               product_overrides={"product_code": code})
        _register_high_vulns(ctx["product"]["id"], 1, "605")
        validate_success(evaluate_gate(ctx["product"]["id"], ctx["gate"]["id"]))
        return ctx

    def test_ciso_can_bypass_gate(self, api):
        """PRD §3.7: "When the business cannot wait, the `CISO` may bypass a
        gate that is `EVALUATING`, supplying a `bypass_reason`". PRD §3.7: "A
        bypassed gate records `evaluation_result` of `CONDITIONAL_PASS`,
        stamps `bypass_approved_by` with the acting CISO, and lives on a
        shorter leash: `evaluation_expires_at` is set only seven days out
        rather than thirty."

        Design: Corner/roles/ciso_can_bypass_gate
        """
        ctx = self._gate_with_warning("BYPASS")
        product_id = ctx["product"]["id"]
        assert get_product(product_id)["compliance_posture"] != "BLOCKED"

        bypassed = validate_success(api.bypass_release_gate(
            product_id, ctx["gate"]["id"],
            bypass_gate_payload("Emergency release for critical customer fix"),
            {"X-User-ID": "ciso-bypass-1", "X-User-Role": "CISO",
             "Content-Type": "application/json"}))
        assert bypassed["gate_status"] == "BYPASSED"
        assert bypassed["bypass_approved_by"] == "ciso-bypass-1"
        assert bypassed["evaluation_result"] == "CONDITIONAL_PASS"
        assert bypassed["evaluation_expires_at"].startswith("2026-08-08"), (
            f"bypass at the 2026-08-01 startup clock expires seven days out, "
            f"got {bypassed['evaluation_expires_at']!r}")

    def test_release_manager_cannot_bypass(self, api, release_manager_headers):
        """PRD §4: bypass is the CISO's operation; "an authenticated user
        attempting an operation outside their role is rejected with
        `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)" (PRD §2.1). Authorization
        is layer 2 of the pipeline of §2.5, ahead of any state check.

        Design: Corner/roles/release_manager_cannot_bypass
        """
        ctx = self._gate_with_warning("NO-BYPASS")
        resp = api.bypass_release_gate(
            ctx["product"]["id"], ctx["gate"]["id"],
            bypass_gate_payload("Unauthorized attempt"),
            release_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
