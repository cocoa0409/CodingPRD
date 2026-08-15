"""Dependency scan pipeline and bill-of-materials assembly: initial state,
terminal lockdown, transitive entry chaining, coverage precision, and the
scan-completion cascade that escalates product posture."""
import pytest

from test_helpers import (
    ApiErrorId,
    SPEC_MIT,
    SPEC_PROHIBITED_DISCOVERED,
    assert_bill_of_materials,
    assert_bom_entry,
    assert_dependency_scan,
    assert_percentage_two_decimals,
    assert_product,
    create_dependency_scan_payload,
    create_product,
    create_scan,
    get_product,
    get_success_data,
    manifest_component_spec,
    setup_blocked_product,
    setup_product_with_completed_scan,
    validate_error,
    validate_success,
)


class TestScanLifecycle:
    def test_scan_initial_state_queued(self, api, analyst_headers):
        """PRD §3.3: "The new scan lands in `QUEUED` with its
        `raw_manifest_hash` — the SHA-256 of the submitted manifest — recorded
        so that repeated submissions of identical bytes are recognized
        idempotently, and the product's `posture_version` is incremented at
        creation."

        Design: Corner/state_machines/scan_initial_state_queued
        """
        product = create_product(product_code="INIT-TEST")
        scan = create_scan(product["id"], [SPEC_MIT])
        assert_dependency_scan(scan)
        assert scan["status"] == "QUEUED"

    def test_scan_invalid_transition_terminal(self, api, analyst_headers):
        """PRD §3.3: "A `ComplianceAnalyst` may cancel a scan while it is still
        `QUEUED` or `PARSING`, moving it to `CANCELLED`; cancelling a scan that
        has progressed further is rejected with `ERR_SCAN_NOT_CANCELLABLE`
        (HTTP 409)."

        Design: Corner/state_machines/scan_invalid_transition_terminal
        """
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": "TERM-TEST"})
        assert ctx["scan"]["status"] == "COMPLETED"
        resp = api.cancel_dependency_scan(
            ctx["product"]["id"], ctx["scan"]["id"], analyst_headers)
        validate_error(resp, ApiErrorId.ERR_SCAN_NOT_CANCELLABLE, 409)

    def test_bom_entry_self_referential_parent(self, api):
        """PRD §3.3: "Inside a BOM, each entry records how its component
        participates: ... its `dependency_depth` in the dependency tree with
        zero marking direct dependencies, and — for transitive entries — the
        `parent_entry_id` chaining it to the entry that pulled it in, which is
        null for direct dependencies."

        Design: Corner/entities/bom_entry_self_referential_parent
        """
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": "TRANS-TEST"},
            manifest=[
                manifest_component_spec(package_url="pkg:npm/direct-lib@1.0.0",
                                        declared_license_spdx="MIT"),
                manifest_component_spec(package_url="pkg:npm/trans-lib@1.0.0",
                                        declared_license_spdx="MIT",
                                        is_direct=False, dependency_depth=1),
            ])
        entries = ctx["entries"]
        assert len(entries) == 2
        for entry in entries:
            assert_bom_entry(entry)
        direct = [e for e in entries if e["is_direct"]]
        transitive = [e for e in entries if not e["is_direct"]]
        assert len(direct) == 1 and len(transitive) == 1
        assert direct[0]["parent_entry_id"] is None
        assert direct[0]["dependency_depth"] == 0
        entry_ids = {e["id"] for e in entries}
        assert transitive[0]["parent_entry_id"] in entry_ids
        assert transitive[0]["dependency_depth"] > 0

    def test_license_scan_coverage_precision(self, api, analyst_headers,
                                             admin_headers):
        """PRD §3.3: "computing `license_scan_coverage_pct` — the number of
        resolved components whose `discovered_license_spdx` is populated,
        divided by `components_resolved`, multiplied by one hundred, rounded
        half-up to two decimal places, and recorded as 0.00 when nothing
        resolved at all." Two of three resolved packages carry a license:
        2/3 × 100 rounds half-up to 66.67.

        Design: Corner/calculations/license_scan_coverage_precision
        """
        product = create_product(product_code="PRECISION")
        scan = create_scan(product["id"], [
            manifest_component_spec(package_url="pkg:npm/lic-a@1.0.0",
                                    declared_license_spdx="MIT"),
            manifest_component_spec(package_url="pkg:npm/lic-b@1.0.0",
                                    declared_license_spdx="Apache-2.0"),
            # No license metadata at all: nothing is discovered for this one.
            manifest_component_spec(package_url="pkg:npm/nolic@1.0.0",
                                    declared_license_spdx=""),
        ])
        # The worker drives the pipeline; the coverage figure is computed as
        # the scan passes through SCORING regardless of the finalization
        # outcome.
        api.process_next_scan(scan["id"], admin_headers)
        scan_after = validate_success(api.get_dependency_scan(
            product["id"], scan["id"], analyst_headers))
        assert scan_after["components_resolved"] == 3
        assert_percentage_two_decimals(scan_after["license_scan_coverage_pct"])
        assert scan_after["license_scan_coverage_pct"] == pytest.approx(
            66.67, abs=0.005)


class TestScanCompletionCascade:
    def test_scan_completion_cascades_to_blocked_product(self, api):
        """PRD §3.3: "any entry classified `PROHIBITED` drives the product's
        `compliance_posture` to `BLOCKED`". PRD §3.3: "Its `bom_posture` is a
        three-color summary: `RED` as soon as any entry is `PROHIBITED`".
        PRD §3.4: "A `PROHIBITED` classification always yields
        `PROHIBITED_USE`."

        Design: Difficulty/transitive_cascade/scan_completion_cascade_depth_3
        """
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": "CASCADE-3"},
            manifest=[SPEC_PROHIBITED_DISCOVERED])
        assert ctx["scan"]["status"] == "COMPLETED"
        bom = ctx["bom"]
        assert_bill_of_materials(bom)
        assert bom["status"] == "FINALIZED"
        assert bom["bom_posture"] == "RED"
        assert bom["prohibited_components"] == 1
        assert ctx["product"]["compliance_posture"] == "BLOCKED"
        entry = ctx["entries"][0]
        assert entry["obligation_determination"] == "PROHIBITED_USE"
        component = get_success_data(api.list_components(
            ctx["analyst_headers"],
            params={"package_url": "pkg:npm/sneaky-lib@1.0.0"}))[0]
        assert component["effective_classification"] == "PROHIBITED"
        assert component["discovered_license_spdx"] == "WTFPL"

    def test_blocked_product_refuses_scans_and_gates(self, api,
                                                     release_manager_headers):
        """PRD §3.1: "A `BLOCKED` product refuses new dependency scans, new
        release gates, and remediation-plan approvals with
        `ERR_PRODUCT_BLOCKED` (HTTP 409)."

        Design: Difficulty/transitive_cascade/scan_completion_cascade_depth_3
        """
        ctx = setup_blocked_product(
            product_overrides={"product_code": "CASCADE-3B"})
        product_id = ctx["product"]["id"]
        assert ctx["product"]["compliance_posture"] == "BLOCKED"

        fresh = get_product(product_id)
        resp = api.create_dependency_scan(
            product_id,
            create_dependency_scan_payload(
                fresh["posture_version"], manifest=[SPEC_MIT]),
            ctx["analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)

        resp = api.create_release_gate(
            product_id,
            {"bom_id": ctx["bom"]["id"], "release_version": "1.0.0"},
            release_manager_headers)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)

    def test_blocked_product_lockdown_via_corner_path(self, api):
        """PRD §3.1: "A `BLOCKED` product refuses new dependency scans, new
        release gates, and remediation-plan approvals with
        `ERR_PRODUCT_BLOCKED` (HTTP 409)." The blockade holds until an explicit
        CISO unblock.

        Design: Corner/state_machines/product_terminal_state_lockdown_blocked
        """
        ctx = setup_blocked_product()
        product_id = ctx["product"]["id"]
        fresh = get_product(product_id)
        resp = api.create_dependency_scan(
            product_id,
            create_dependency_scan_payload(
                fresh["posture_version"], manifest=[SPEC_MIT]),
            ctx["analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)

    def test_posture_change_visible_immediately_after_scan(self, api,
                                                           admin_headers):
        """PRD §2.7: "Changes propagate upward without requiring a client
        request on the parent". The same worker response that completes the
        scan is immediately followed by a read showing the escalated posture —
        consistency is immediate, with no eventual lag.

        Design: Corner/consistency_model/immediate_consistency_product_posture
        """
        product = create_product(product_code="IMMEDIATE")
        scan = create_scan(product["id"], [SPEC_PROHIBITED_DISCOVERED])
        completed = validate_success(
            api.process_next_scan(scan["id"], admin_headers))
        assert completed["status"] == "COMPLETED"
        product_after = get_product(product["id"])
        assert_product(product_after)
        assert product_after["compliance_posture"] == "BLOCKED"
        assert product_after["posture_version"] > product["posture_version"]
