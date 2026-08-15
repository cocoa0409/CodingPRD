"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["controlled_content_pct"], int)
    assert 0 <= data["controlled_content_pct"] <= 100
    assert isinstance(data["unit_value_cents"], int) and data["unit_value_cents"] > 0
    assert data["status"] in ("UNCLASSIFIED", "CLASSIFIED")
    assert isinstance(data["classification_count"], int) and data["classification_count"] >= 0
    assert "active_classification_id" in data


def assert_classification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["jurisdiction"] in ("EAR", "ITAR")
    assert isinstance(data["classification_code"], str) and data["classification_code"]
    assert data["determination_basis"] in ("SELF_CLASSIFICATION", "CCATS", "CJ_DETERMINATION")
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACTIVE", "REJECTED", "SUPERSEDED")


def assert_party(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 3
    assert isinstance(data["city"], str) and data["city"]
    assert data["party_type"] in ("CUSTOMER", "CONSIGNEE", "END_USER", "FOREIGN_NATIONAL")
    assert isinstance(data["is_foreign_national"], bool)
    assert data["screening_posture"] in ("UNSCREENED", "CLEAR", "REVIEW_REQUIRED", "BLOCKED")
    assert isinstance(data["active_grant_count"], int) and data["active_grant_count"] >= 0
    assert "last_screened_at" in data


def assert_screening_list_entry(data: dict):
    _assert_common_fields(data)
    assert data["list_source"] in ("SDN", "DENIED_PERSONS", "ENTITY_LIST", "EMBARGOED_COUNTRY")
    assert isinstance(data["match_name"], str) and data["match_name"]
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 3
    assert data["severity"] in ("PROHIBITED", "RESTRICTED")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_screening_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("party_id", ""))
    assert data["trigger_context"] in ("ORDER", "SHIPMENT", "MANUAL", "LIST_CHANGE")
    assert data["algorithm_variant"] in ("EXACT", "FUZZY")
    assert data["status"] in ("CLEAR", "POTENTIAL_MATCH", "FALSE_POSITIVE", "CONFIRMED_MATCH")
    assert "matched_entry_id" in data
    assert "score" in data
    assert "threshold_used" in data


def assert_export_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("party_id", ""))
    assert isinstance(data["destination_country"], str) and len(data["destination_country"]) == 3
    assert data["end_use"] in ("CIVILIAN", "MILITARY", "DUAL_USE")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert "license_id" in data
    assert data["provisional_determination"] in ("NOT_REQUIRED", "LICENSE_REQUIRED", "PROHIBITED")
    assert "determination" in data
    assert "determination_classification_sequence" in data
    assert isinstance(data["goods_value_cents"], int) and data["goods_value_cents"] > 0
    assert isinstance(data["surcharge_cents"], int) and data["surcharge_cents"] >= 0
    assert isinstance(data["total_value_cents"], int)
    assert isinstance(data["accumulated_fees_cents"], int) and data["accumulated_fees_cents"] >= 0
    assert isinstance(data["shipped_quantity"], int) and data["shipped_quantity"] >= 0
    assert "pre_hold_status" in data
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "CLEARED", "HELD", "LICENSED", "RELEASED", "CLOSED", "CANCELLED",
    )


def assert_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["issuing_authority"] in ("BIS", "DDTC", "OFAC")
    assert isinstance(data["approved_value_cents"], int) and data["approved_value_cents"] > 0
    assert isinstance(data["approved_quantity"], int) and data["approved_quantity"] > 0
    assert isinstance(data["valid_from"], str) and len(data["valid_from"]) == 10
    assert isinstance(data["valid_until"], str) and len(data["valid_until"]) == 10
    assert isinstance(data["conditions"], list)
    assert "license_number" in data
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "DENIED", "RETURNED_FOR_INFO",
        "EXPIRED", "EXHAUSTED", "REVOKED",
    )


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["planned_ship_date"], str) and len(data["planned_ship_date"]) == 10
    assert "screening_result_id" in data
    assert isinstance(data["consumed_value_cents"], int) and data["consumed_value_cents"] >= 0
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in (
        "PLANNED", "SCREENED", "HELD", "RELEASED", "IN_TRANSIT",
        "DELIVERED", "RETURNED", "CANCELLED",
    )


def assert_tcp(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["enclave_id"], str) and data["enclave_id"]
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["segregation_level"] in ("LEVEL_1", "LEVEL_2", "LEVEL_3")
    assert isinstance(data["effective_from"], str) and len(data["effective_from"]) == 10
    assert isinstance(data["effective_to"], str) and len(data["effective_to"]) == 10
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_access_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("tcp_id", ""))
    assert is_valid_uuid(data.get("party_id", ""))
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date"], str) and len(data["end_date"]) == 10
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "ACTIVE", "REVOKED", "EXPIRED")


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert data["source_type"] in ("ORDER", "SHIPMENT", "ACCESS_GRANT", "SCREENING", "OTHER")
    assert isinstance(data["source_id"], str)
    assert data["severity"] in ("MINOR", "MATERIAL", "CRITICAL")
    assert isinstance(data["description"], str)
    assert data["status"] in (
        "IDENTIFIED", "UNDER_REVIEW", "SUBSTANTIATED", "UNFOUNDED", "DISCLOSED", "CLOSED",
    )


def assert_audit_record(data: dict):
    """AuditRecord is append-only: id + created_at present; version/updated_at ABSENT (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "AuditRecord must not carry updated_at"
    assert "version" not in data, "AuditRecord must not carry version"
    assert data["event_type"] in (
        "CLASSIFICATION_ACTIVATED", "LICENSE_APPROVED", "LICENSE_REVOKED", "ORDER_RELEASED",
        "SHIPMENT_RELEASED", "SHIPMENT_RETURNED", "GRANT_ACTIVATED", "GRANT_REVOKED",
        "SCREENING_CONFIRMED_MATCH", "VSD_SUBMITTED", "VIOLATION_CLOSED",
    )
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert data["actor_role"] in (
        "ComplianceAnalyst", "ComplianceManager", "TradeOpsSpecialist", "ComplianceDirector",
    )
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
    assert isinstance(data["detail"], str)
    assert isinstance(data["retain_until"], str) and data["retain_until"]


def assert_license_consumption_invariants(data: dict):
    """License ledger invariants (PRD §3.5): approved == remaining + consumed, after approval."""
    assert data["approved_value_cents"] == data["remaining_value_cents"] + data["consumed_value_cents"], (
        f"value invariant broken: {data['approved_value_cents']} != "
        f"{data['remaining_value_cents']} + {data['consumed_value_cents']}"
    )
    assert data["approved_quantity"] == data["remaining_quantity"] + data["consumed_quantity"], (
        f"quantity invariant broken: {data['approved_quantity']} != "
        f"{data['remaining_quantity']} + {data['consumed_quantity']}"
    )
