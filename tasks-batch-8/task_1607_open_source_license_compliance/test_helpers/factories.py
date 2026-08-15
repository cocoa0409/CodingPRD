"""Payload factories — one per creatable entity, input fields only (PRD §3).

A dependency scan submission references a manifest: the list of packages the
scanner resolves against the catalogue (PRD §3.3). `manifest_component_spec`
builds one manifest line; `create_dependency_scan_payload` bundles lines into
the scan-create body alongside `scan_tool`, `scan_scope`, and the OCC field
`expected_product_version` (PRD §2.8).
"""

DEFAULTS = {
    "PRODUCT_CODE": "PROD-001",
    "PRODUCT_NAME": "Test Product",
    "DISTRIBUTION_MODEL": "SaaS",
    "PACKAGE_URL": "pkg:npm/test-lib@1.0.0",
    "COMPONENT_NAME": "test-lib",
    "PACKAGE_VERSION": "1.0.0",
    "DECLARED_LICENSE": "MIT",
    "SCAN_TOOL": "SYFT",
    "SCAN_SCOPE": "FULL",
    "RELEASE_VERSION": "1.0.0",
    "CVE_ID": "CVE-2024-0001",
    "CVSS_SCORE": 7.5,
    "PUBLISHED_AT": "2026-08-01T00:00:00Z",
    "PLAN_TYPE": "PATCH",
    "MIGRATION_EFFORT_DAYS": 3,
    "AUDIT_TYPE": "M_AND_A",
    "REQUESTING_PARTY": "Acme Corp",
    "SCOPE_DESCRIPTION": "Full product audit",
    "TARGET_COMPLETION_AT": "2026-08-15T00:00:00Z",
}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "distribution_model": DEFAULTS["DISTRIBUTION_MODEL"],
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "package_url": DEFAULTS["PACKAGE_URL"],
        "component_name": DEFAULTS["COMPONENT_NAME"],
        "version": DEFAULTS["PACKAGE_VERSION"],
        "declared_license_spdx": DEFAULTS["DECLARED_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def manifest_component_spec(package_url=DEFAULTS["PACKAGE_URL"],
                            component_name=None, version=None,
                            declared_license_spdx=DEFAULTS["DECLARED_LICENSE"],
                            discovered_license_spdx=None, dependency_scope=None,
                            is_direct=None, dependency_depth=None) -> dict:
    """One line of a scan submission's referenced manifest (PRD §3.3)."""
    spec = {
        "package_url": package_url,
        "component_name": component_name
        or package_url.split("/")[-1].split("@")[0],
        "version": version
        or (package_url.split("@")[-1] if "@" in package_url else "1.0.0"),
        "declared_license_spdx": declared_license_spdx,
    }
    if discovered_license_spdx is not None:
        spec["discovered_license_spdx"] = discovered_license_spdx
    if dependency_scope is not None:
        spec["dependency_scope"] = dependency_scope
    if is_direct is not None:
        spec["is_direct"] = is_direct
    if dependency_depth is not None:
        spec["dependency_depth"] = dependency_depth
    return spec


def create_dependency_scan_payload(expected_product_version, manifest=None,
                                   **overrides) -> dict:
    """Scan-create body: tool, scope, manifest lines, and the OCC field
    `expected_product_version` carrying the last-observed product
    `posture_version` (PRD §2.8)."""
    defaults = {
        "scan_tool": DEFAULTS["SCAN_TOOL"],
        "scan_scope": DEFAULTS["SCAN_SCOPE"],
        "expected_product_version": expected_product_version,
        "manifest_components": manifest if manifest is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_vulnerability_payload(**overrides) -> dict:
    defaults = {
        "cve_id": DEFAULTS["CVE_ID"],
        "severity": "HIGH",
        "cvss_score": DEFAULTS["CVSS_SCORE"],
        "published_at": DEFAULTS["PUBLISHED_AT"],
        "affected_package_url": DEFAULTS["PACKAGE_URL"],
    }
    defaults.update(overrides)
    return defaults


def create_release_gate_payload(bom_id, **overrides) -> dict:
    defaults = {
        "bom_id": bom_id,
        "release_version": DEFAULTS["RELEASE_VERSION"],
    }
    defaults.update(overrides)
    return defaults


def create_remediation_plan_payload(finding_id, **overrides) -> dict:
    defaults = {
        "finding_id": finding_id,
        "plan_type": DEFAULTS["PLAN_TYPE"],
        "migration_effort_days": DEFAULTS["MIGRATION_EFFORT_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_engagement_payload(**overrides) -> dict:
    defaults = {
        "audit_type": DEFAULTS["AUDIT_TYPE"],
        "requesting_party": DEFAULTS["REQUESTING_PARTY"],
        "scope_description": DEFAULTS["SCOPE_DESCRIPTION"],
        "target_completion_at": DEFAULTS["TARGET_COMPLETION_AT"],
    }
    defaults.update(overrides)
    return defaults


def legal_decision_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"legal_decision": decision}
    defaults.update(overrides)
    return defaults


def engineering_decision_payload(decision="APPROVE") -> dict:
    return {"engineering_decision": decision}


def fulfill_ticket_payload(evidence_uri="s3://evidence/fulfillment.zip") -> dict:
    return {"fulfillment_evidence_uri": evidence_uri}


def waive_ticket_payload(reason="Obligation waived by counsel") -> dict:
    return {"waiver_reason": reason}


def verify_remediation_payload(evidence_uri="s3://evidence/fix.zip") -> dict:
    return {"verification_evidence_uri": evidence_uri}


def wont_fix_payload(rationale="Risk accepted by CISO") -> dict:
    return {"risk_acceptance_rationale": rationale}


def bypass_gate_payload(reason="Emergency release for critical customer fix") -> dict:
    return {"bypass_reason": reason}


def override_classification_payload(classification, rationale="Manual review") -> dict:
    return {
        "policy_override_classification": classification,
        "rationale": rationale,
    }


def complete_plan_payload(verification_scan_id) -> dict:
    return {"verification_scan_id": verification_scan_id}


def unblock_payload(justification="Documented remediation plan in progress") -> dict:
    return {"justification": justification}
