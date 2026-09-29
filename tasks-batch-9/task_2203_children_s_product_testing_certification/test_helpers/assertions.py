"""Per-entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import types as t


def _assert_audit_shape(entity: Dict[str, Any]) -> None:
    """Every entity but the material change log carries these four fields."""
    assert is_valid_uuid(entity["id"]), f"id is not a uuid: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1


def assert_applicable_rule(rule: Dict[str, Any]) -> None:
    _assert_audit_shape(rule)
    assert rule["hazard_class"] in t.HAZARD_CLASSES
    assert rule["limit_unit"] in t.LIMIT_UNITS
    assert rule["limit_comparator"] in t.LIMIT_COMPARATORS
    assert rule["limit_value"] >= 0
    assert 1 <= rule["periodic_interval_months"] <= 60
    assert rule["base_method_fee_cents"] >= 0
    assert isinstance(rule["component_reliance_allowed"], bool)
    assert 1 <= rule["severity_weight"] <= 10


def assert_product_category(category: Dict[str, Any]) -> None:
    _assert_audit_shape(category)
    assert isinstance(category["durable_infant_product"], bool)
    assert 0 <= category["intended_age_max_months"] <= 168
    assert category["sampling_floor_units"] >= 1


def assert_category_rule_mapping(mapping: Dict[str, Any]) -> None:
    _assert_audit_shape(mapping)
    assert is_valid_uuid(mapping["category_id"])
    assert is_valid_uuid(mapping["rule_id"])
    assert mapping["applicability_condition"] in t.APPLICABILITY_CONDITIONS
    assert mapping["mapping_state"] in t.MAPPING_STATES
    assert is_iso8601_timestamp(mapping["effective_from"])


def assert_supplier(supplier: Dict[str, Any]) -> None:
    _assert_audit_shape(supplier)
    assert supplier["reliance_agreement_state"] in t.RELIANCE_AGREEMENT_STATES
    assert len(supplier["country_code"]) == 2
    assert supplier["country_code"].isupper()
    assert supplier["certificates_issued_count"] >= 0


def assert_laboratory(lab: Dict[str, Any]) -> None:
    _assert_audit_shape(lab)
    assert lab["independence_class"] in t.INDEPENDENCE_CLASSES
    assert lab["operational_state"] in t.LAB_OPERATIONAL_STATES
    assert lab["influence_attestation_state"] in t.INFLUENCE_ATTESTATION_STATES
    assert 1 <= lab["concurrent_slot_capacity"] <= 10
    assert lab["billed_fee_cents_total"] >= 0
    assert lab["credited_fee_cents_total"] >= 0


def assert_lab_accreditation(accreditation: Dict[str, Any]) -> None:
    _assert_audit_shape(accreditation)
    assert is_valid_uuid(accreditation["laboratory_id"])
    assert is_valid_uuid(accreditation["rule_id"])
    assert accreditation["accreditation_state"] in t.ACCREDITATION_STATES
    assert 0 <= accreditation["fee_surcharge_basis_points"] <= 5000
    assert is_iso8601_timestamp(accreditation["valid_from"])
    assert is_iso8601_timestamp(accreditation["valid_through"])


def assert_product(product: Dict[str, Any]) -> None:
    _assert_audit_shape(product)
    assert is_valid_uuid(product["category_id"])
    assert product["certification_state"] in t.CERTIFICATION_STATES
    assert product["compliance_posture"] in t.COMPLIANCE_POSTURES
    if product["evidence_path"] is not None:
        assert product["evidence_path"] in t.EVIDENCE_PATHS
    assert isinstance(product["required_rule_ids"], list)
    assert 0 <= product["risk_weighted_gap_score"] <= 100
    assert product["projected_annual_units"] >= 1
    assert product["testing_budget_cents"] >= 0
    for counter in ("units_held", "units_released", "units_stopped", "units_destroyed"):
        assert product[counter] >= 0
    assert product["material_change_count"] >= 0


def assert_component_part(part: Dict[str, Any]) -> None:
    _assert_audit_shape(part)
    assert is_valid_uuid(part["product_id"])
    assert is_valid_uuid(part["supplier_id"])
    assert part["material_class"] in t.MATERIAL_CLASSES
    assert isinstance(part["accessible_to_child"], bool)
    assert isinstance(part["small_part_when_detached"], bool)
    assert part["reliance_status"] in t.PART_RELIANCE_STATUSES


def assert_component_part_certificate(certificate: Dict[str, Any]) -> None:
    _assert_audit_shape(certificate)
    assert is_valid_uuid(certificate["component_part_id"])
    assert is_valid_uuid(certificate["supplier_id"])
    assert is_valid_uuid(certificate["laboratory_id"])
    assert is_valid_uuid(certificate["rule_id"])
    assert certificate["reliance_state"] in t.PART_CERTIFICATE_STATES
    assert certificate["measured_value"] >= 0
    assert is_iso8601_timestamp(certificate["coverage_from"])
    assert is_iso8601_timestamp(certificate["coverage_through"])


def assert_sampling_plan(plan: Dict[str, Any]) -> None:
    _assert_audit_shape(plan)
    assert is_valid_uuid(plan["product_id"])
    assert plan["plan_type"] in t.PLAN_TYPES
    assert plan["plan_state"] in t.PLAN_STATES
    assert plan["resample_trigger"] in t.RESAMPLE_TRIGGERS
    assert 0 <= plan["resample_grace_days"] <= 365
    assert plan["baseline_units_produced"] >= 0
    assert_sample_unit_ledger(plan)


def assert_test_order(order: Dict[str, Any]) -> None:
    _assert_audit_shape(order)
    assert is_valid_uuid(order["product_id"])
    assert is_valid_uuid(order["sampling_plan_id"])
    assert is_valid_uuid(order["laboratory_id"])
    assert is_valid_uuid(order["rule_id"])
    assert order["order_state"] in t.ORDER_STATES
    assert order["sample_count"] >= 1
    assert isinstance(order["is_retest"], bool)
    assert isinstance(order["expedite_requested"], bool)
    assert order["line_fee_cents"] >= 0
    assert order["invoice_total_cents"] >= 0
    if order["result"] is not None:
        assert order["result"] in t.TEST_RESULTS


def assert_childrens_product_certificate(certificate: Dict[str, Any]) -> None:
    _assert_audit_shape(certificate)
    assert is_valid_uuid(certificate["product_id"])
    assert certificate["issuance_status"] in t.ISSUANCE_STATUSES
    assert certificate["accompaniment_status"] in t.ACCOMPANIMENT_STATUSES
    assert "@" in certificate["certifier_contact_email"]
    assert isinstance(certificate["cited_rule_ids"], list)
    assert certificate["cited_evidence_count"] >= 0
    assert 0 <= certificate["content_completeness_pct"] <= 100


def assert_production_batch(batch: Dict[str, Any]) -> None:
    _assert_audit_shape(batch)
    assert is_valid_uuid(batch["product_id"])
    assert is_valid_uuid(batch["certificate_id"])
    assert batch["distribution_state"] in t.DISTRIBUTION_STATES
    assert batch["quantity"] >= 1
    assert isinstance(batch["tracking_label_compliant"], bool)
    assert batch["release_rescind_count"] >= 0


def assert_noncompliance_case(case: Dict[str, Any]) -> None:
    _assert_audit_shape(case)
    assert is_valid_uuid(case["product_id"])
    assert is_valid_uuid(case["triggering_test_order_id"])
    assert is_valid_uuid(case["failed_rule_id"])
    assert case["case_state"] in t.CASE_STATES
    assert case["scope_variant"] in t.SCOPE_VARIANTS
    assert case["retest_round_count"] >= 0
    assert case["scope_units"] >= 0
    assert case["corrective_action_revision"] >= 0


def assert_material_change_event(event: Dict[str, Any]) -> None:
    """A material change event carries only id and created_at from the audit shape."""
    assert is_valid_uuid(event["id"])
    assert is_iso8601_timestamp(event["created_at"])
    assert "updated_at" not in event, "material change events carry no updated_at"
    assert "version" not in event, "material change events carry no version"
    assert event["subject_type"] in t.SUBJECT_TYPES
    assert event["change_kind"] in t.CHANGE_KINDS
    assert isinstance(event["triggers_resample"], bool)
    assert is_iso8601_timestamp(event["occurred_at"])


# ---------------------------------------------------------------------------
# Domain invariants (PRD 2.8)
# ---------------------------------------------------------------------------


def assert_sample_unit_ledger(plan: Dict[str, Any]) -> None:
    """units_committed plus units_available equals units_authorized at all times."""
    assert (
        plan["units_committed"] + plan["units_available"] == plan["units_authorized"]
    ), (
        f"sample unit ledger drift: committed={plan['units_committed']} "
        f"available={plan['units_available']} authorized={plan['units_authorized']}"
    )


def assert_distribution_ledger(summary: Dict[str, Any]) -> None:
    """The four distribution counters sum to the total quantity produced."""
    total = (
        summary["units_held"]
        + summary["units_released"]
        + summary["units_stopped"]
        + summary["units_destroyed"]
    )
    assert total == summary["units_total_produced"], (
        f"distribution ledger drift: {total} != {summary['units_total_produced']}"
    )
    assert summary["ledger_balanced"] is True


def assert_fee_ledger(laboratory: Dict[str, Any], expected_net_cents: int) -> None:
    """billed_fee_cents_total minus credited_fee_cents_total is the outstanding balance."""
    net = laboratory["billed_fee_cents_total"] - laboratory["credited_fee_cents_total"]
    assert net == expected_net_cents, (
        f"fee ledger net {net} != expected {expected_net_cents} "
        f"(billed={laboratory['billed_fee_cents_total']}, "
        f"credited={laboratory['credited_fee_cents_total']})"
    )


def assert_compliance_summary_shape(summary: Dict[str, Any]) -> None:
    """The computed summary read reports every field named by the PRD."""
    for field in (
        "product_id",
        "required_rule_ids",
        "covered_rule_ids",
        "uncovered_rule_ids",
        "risk_weighted_gap_score",
        "compliance_posture",
        "open_case_count",
        "resample_due_plan_count",
        "units_held",
        "units_released",
        "units_stopped",
        "units_destroyed",
        "units_total_produced",
        "ledger_balanced",
    ):
        assert field in summary, f"compliance summary is missing {field}"


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ascending by created_at: {stamps}"


def assert_material_change_log_ordering(rows: List[Dict[str, Any]]) -> None:
    """Newest first, by occurred_at descending then created_at descending."""
    keys = [(row["occurred_at"], row["created_at"]) for row in rows]
    assert keys == sorted(keys, reverse=True), f"log is not newest-first: {keys}"
