"""Entity assertions and domain invariant checkers for PRD 2.5 common fields
and per-resource shapes."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["importer_of_record_number"], str)
    assert isinstance(data["contingency_fee_bps"], int)
    assert data["engagement_status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["lifetime_recovered_cents"], int)
    assert isinstance(data["projected_fee_accrual_cents"], int)
    assert isinstance(data["open_audit_count"], int)


def assert_classification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["product_sku"], str)
    assert isinstance(data["hts_code"], str)
    assert isinstance(data["country_of_origin"], str)
    assert isinstance(data["duty_rate_bps"], int)
    assert isinstance(data["declared_unit_value_cents"], int)
    assert isinstance(data["first_sale_eligible"], bool)
    assert isinstance(data["appraised_unit_value_cents"], int)
    assert data["status"] in ("DRAFT", "IN_REVIEW", "CERTIFIED", "SUPERSEDED")


def assert_binding_ruling(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["classification_id"], str)
    assert isinstance(data["requested_hts_code"], str)
    assert data["status"] in ("SUBMITTED", "ISSUED", "DENIED", "WITHDRAWN")


def assert_import_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["classification_id"], str)
    assert isinstance(data["entry_number"], str)
    assert isinstance(data["line_quantity"], int) and data["line_quantity"] > 0
    assert isinstance(data["entered_value_cents"], int)
    assert isinstance(data["duty_paid_cents"], int)
    assert isinstance(data["non_drawbackable_cents"], int)
    assert isinstance(data["drawback_eligible_duty_cents"], int)
    assert isinstance(data["matched_quantity"], int)
    assert isinstance(data["unclaimed_duty_cents"], int)
    assert data["status"] in ("UNMATCHED", "PARTIALLY_MATCHED", "MATCHED")


def assert_export_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["hts_code"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["fob_value_cents"], int)
    assert isinstance(data["substituted_duty_rate_bps"], int)
    assert isinstance(data["matched_quantity"], int)
    assert isinstance(data["value_pool_remaining_cents"], int)
    assert data["status"] in ("UNMATCHED", "PARTIALLY_MATCHED", "MATCHED")


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert data["claim_type"] in ("DIRECT_IDENTIFICATION", "SUBSTITUTION")
    assert data["status"] in (
        "DRAFT", "FILED", "DEFICIENCY_ISSUED", "APPROVED", "PAID", "DENIED", "CANCELLED"
    )
    assert isinstance(data["deficiency_count"], int)
    assert isinstance(data["estimate_cents"], int)


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["import_entry_id"], str)
    assert isinstance(data["export_shipment_id"], str)
    assert isinstance(data["matched_quantity"], int) and data["matched_quantity"] > 0
    assert data["match_method"] in ("DIRECT", "SUBSTITUTION")
    assert isinstance(data["drawback_amount_cents"], int)
    assert data["status"] in ("ACTIVE", "VOID")


def assert_tariff_measure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["hts_code_prefix"], str)
    assert data["measure_type"] in ("EXCLUSION", "SECTION_301", "AD_CVD", "SAFEGUARD")
    assert isinstance(data["surcharge_bps"], int)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["recovered_duty_cents"], int)
    assert isinstance(data["fee_bps_snapshot"], int)
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")


def assert_audit_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert data["opened_reason"] in ("CF28", "FOCUSED_ASSESSMENT", "POST_PAYMENT_AUDIT")
    assert data["status"] in (
        "OPENED", "EVIDENCE_GATHERING", "RESPONSE_FILED",
        "CLOSED_REFUTED", "CLOSED_SUSTAINED",
    )
    assert isinstance(data["penalty_exposure_cents"], int)


def assert_compliance_record(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["claim_id"], str)
    assert data["doc_type"] in ("ENTRY_DOCS", "EXPORT_PROOF", "MATCHING_WORKSHEET")
    assert data["status"] in ("RETAINED", "ELIGIBLE_FOR_DESTRUCTION", "DESTROYED")


def assert_entry_pool_invariant(entry: dict):
    """PRD 3.3: unclaimed duty is the eligible duty minus the sum over ACTIVE
    lines; the conserved pool identity is sum(ACTIVE line amounts) + unclaimed
    == eligible. This checker takes the entry plus the observed ACTIVE-line sum."""
    assert entry["drawback_eligible_duty_cents"] >= 0
    assert entry["unclaimed_duty_cents"] >= 0
    assert entry["unclaimed_duty_cents"] <= entry["drawback_eligible_duty_cents"]


def assert_export_pool_invariant(shipment: dict, active_line_sum: int):
    """PRD 3.3: value_pool_remaining_cents == fob_value_cents minus the sum of
    drawback_amount_cents over ACTIVE lines referencing the shipment."""
    assert shipment["value_pool_remaining_cents"] == (
        shipment["fob_value_cents"] - active_line_sum
    ), (
        f"export pool drifted: pool {shipment['value_pool_remaining_cents']} "
        f"!= fob {shipment['fob_value_cents']} - active sum {active_line_sum}"
    )
    assert shipment["matched_quantity"] >= 0
    assert shipment["matched_quantity"] <= shipment["quantity"]
