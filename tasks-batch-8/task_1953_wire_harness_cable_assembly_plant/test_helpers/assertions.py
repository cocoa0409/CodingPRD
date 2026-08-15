"""Entity assertions and domain invariant checkers.

Each assert_* verifies the field presence and types the PRD declares for the
resource's representation. Append-only evidence records (crimp pull tests,
electrical test records) must NOT carry `updated_at` or `version`.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')}"
    assert "-" in data.get("id", ""), "id must be a bare UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_harness_drawing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drawing_number"], str) and data["drawing_number"]
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["revision"], str) and data["revision"]
    assert data["workmanship_class"] in ("IPC_CLASS_1", "IPC_CLASS_2", "IPC_CLASS_3")
    assert data["status"] in ("DRAFT", "RELEASED", "SUPERSEDED")


def assert_drawing_component(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drawing_id", "")), "drawing_id must be a UUID"
    assert isinstance(data["find_number"], str) and data["find_number"]
    assert data["component_type"] in ("CONNECTOR", "TERMINAL", "WIRE", "SEAL", "SLEEVE")
    assert isinstance(data["mpn"], str) and data["mpn"]
    assert isinstance(data["qty_per_harness"], int) and data["qty_per_harness"] >= 1
    assert data["supply_type"] in ("FACTORY_STOCK", "CUSTOMER_CONSIGNED")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0


def assert_consigned_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["owner_customer_code"], str) and data["owner_customer_code"]
    assert isinstance(data["mpn"], str) and data["mpn"]
    assert isinstance(data["unit_liability_cents"], int) and data["unit_liability_cents"] >= 0
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] >= 0
    assert isinstance(data["qty_received"], int) and data["qty_received"] >= 1
    for bucket in ("qty_on_hand", "qty_issued_open", "qty_consumed", "qty_scrapped", "qty_returned"):
        assert isinstance(data[bucket], int) and data[bucket] >= 0, f"{bucket} must be a non-negative integer"
    assert isinstance(data["book_liability_cents"], int)
    assert isinstance(data["replacement_liability_cents"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "RETURNED")


def assert_consigned_lot_conservation(data: dict):
    """PRD §3.6 five-bucket conserved invariant:
    on_hand + issued_open + consumed + scrapped + returned == qty_received."""
    total = (
        data["qty_on_hand"]
        + data["qty_issued_open"]
        + data["qty_consumed"]
        + data["qty_scrapped"]
        + data["qty_returned"]
    )
    assert total == data["qty_received"], (
        f"consigned piece conservation violated: buckets sum to {total}, "
        f"qty_received is {data['qty_received']}"
    )


def assert_operator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["operator_name"], str) and data["operator_name"]
    assert isinstance(data["badge_no"], str) and data["badge_no"]


def assert_operator_certification(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert data["workmanship_class"] in ("IPC_CLASS_1", "IPC_CLASS_2", "IPC_CLASS_3")
    assert is_iso8601_timestamp(data["issued_at"]), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_applicator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["applicator_code"], str) and data["applicator_code"]
    assert isinstance(data["compatible_terminal_mpn"], str) and data["compatible_terminal_mpn"]
    assert data["status"] in ("AVAILABLE", "IN_SETUP", "QUALIFIED", "QUARANTINED")


def assert_applicator_setup(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("applicator_id", "")), "applicator_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("setup_operator_id", "")), "setup_operator_id must be a UUID"
    assert is_iso8601_timestamp(data["planned_start_at"]), "planned_start_at must be ISO 8601"
    assert is_iso8601_timestamp(data["planned_end_at"]), "planned_end_at must be ISO 8601"
    assert data["status"] in ("OPEN", "CLOSED")


def assert_machine_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert is_valid_uuid(data.get("drawing_id", "")), "drawing_id must be a UUID"
    assert is_valid_uuid(data.get("applicator_id", "")), "applicator_id must be a UUID"
    assert isinstance(data["wire_gauge_awg"], int) and 12 <= data["wire_gauge_awg"] <= 26
    assert isinstance(data["wire_type"], str) and data["wire_type"]
    assert data["cut_length_mm"] > 0
    assert data["strip_length_mm"] > 0
    assert isinstance(data["terminal_mpn"], str) and data["terminal_mpn"]
    assert data["terminal_type"] in ("OPEN_BARREL", "CLOSED_BARREL")
    assert isinstance(data["min_pull_force_n"], (int, float))
    assert data["status"] in ("DRAFT", "QUALIFIED", "HELD")


def assert_build_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_code"], str) and data["order_code"]
    assert is_valid_uuid(data.get("drawing_id", "")), "drawing_id must be a UUID"
    assert isinstance(data["drawing_revision_pinned"], str) and data["drawing_revision_pinned"]
    assert data["workmanship_class"] in ("IPC_CLASS_1", "IPC_CLASS_2", "IPC_CLASS_3")
    assert isinstance(data["qty_ordered"], int) and data["qty_ordered"] >= 1
    for counter in (
        "material_spent_cents",
        "qty_built",
        "qty_scrapped",
        "standard_cost_cents",
        "actual_cost_cents",
        "scrap_recovery_credit_cents",
        "next_unit_seq",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be a non-negative integer"
    assert isinstance(data["use_as_is_flag"], bool)
    assert data["status"] in ("OPEN", "KITTING", "IN_BUILD", "TESTING", "COMPLETED", "CANCELLED", "QC_HOLD")


def assert_build_order_quantity_conservation(data: dict):
    """PRD §3.5: qty_built + qty_scrapped is conserved across build/scrap and
    invariant under ship; it never exceeds qty_ordered."""
    assert data["qty_built"] + data["qty_scrapped"] <= data["qty_ordered"], (
        f"qty_built + qty_scrapped ({data['qty_built']} + {data['qty_scrapped']}) "
        f"exceeds qty_ordered ({data['qty_ordered']})"
    )


def assert_kit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_order_id", "")), "build_order_id must be a UUID"
    assert isinstance(data["kit_seq"], int) and data["kit_seq"] >= 1
    assert data["status"] in ("PICKING", "STAGED", "DELIVERED_LINESIDE", "RETURNED")
    assert isinstance(data["issues"], list)
    assert isinstance(data["shortage_count"], int) and data["shortage_count"] >= 0
    for issue in data["issues"]:
        assert is_valid_uuid(issue.get("component_id", "")), "issue.component_id must be a UUID"
        assert isinstance(issue["qty_issued"], int) and issue["qty_issued"] >= 1
        assert issue["source"] in ("FACTORY_STOCK", "CONSIGNED_LOT")
        assert isinstance(issue["unit_cost_snapshot_cents"], int)
        assert isinstance(issue["voided"], bool)


def assert_harness_unit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("build_order_id", "")), "build_order_id must be a UUID"
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["drawing_revision_built"], str) and data["drawing_revision_built"]
    assert is_valid_uuid(data.get("built_by_operator_id", "")), "built_by_operator_id must be a UUID"
    assert data["status"] in ("BUILT", "TEST_PASS", "REWORK", "SUSPECT", "SHIPPED", "SCRAPPED")
    assert isinstance(data["rework_count"], int) and 0 <= data["rework_count"] <= 2
    assert isinstance(data["continuity_pass"], bool)
    assert isinstance(data["hipot_pass"], bool)


def assert_crimp_pull_test(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("applicator_id", "")), "applicator_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert data["sample_kind"] in ("FIRST_ARTICLE", "LOT_SAMPLE")
    assert isinstance(data["measured_force_n"], (int, float))
    assert isinstance(data["min_pull_force_n_snapshot"], (int, float))
    assert data["result"] in ("PASS", "FAIL")
    assert is_iso8601_timestamp(data["tested_at"]), "tested_at must be ISO 8601"


def assert_electrical_test_record(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("harness_unit_id", "")), "harness_unit_id must be a UUID"
    assert is_valid_uuid(data.get("test_operator_id", "")), "test_operator_id must be a UUID"
    assert data["test_type"] in ("CONTINUITY", "HIPOT")
    if data["test_type"] == "CONTINUITY":
        assert isinstance(data["opens_count"], int) and data["opens_count"] >= 0
    else:
        assert isinstance(data["hipot_voltage_v"], (int, float))
        assert isinstance(data["dwell_seconds"], (int, float))
        assert isinstance(data["measured_leakage_ua"], (int, float))
        assert isinstance(data["leakage_limit_ua"], (int, float))
    assert data["result"] in ("PASS", "FAIL")
    assert is_iso8601_timestamp(data["tested_at"]), "tested_at must be ISO 8601"


def assert_ecn(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("drawing_id", "")), "drawing_id must be a UUID"
    assert isinstance(data["from_revision"], str) and data["from_revision"]
    assert isinstance(data["to_revision"], str) and data["to_revision"]
    assert data["wip_disposition"] in ("REWORK", "USE_AS_IS", "SCRAP")
    assert data["status"] in ("OPEN", "APPLIED", "CANCELLED")
