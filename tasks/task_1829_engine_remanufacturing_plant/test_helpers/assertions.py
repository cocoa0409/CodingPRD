"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.4: created_at / updated_at are ISO 8601 UTC timestamps with three
# fractional digits.
_ISO8601_3F_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# PRD §3.8: serial numbers are the literal prefix RMN- followed by a
# six-digit zero-padded sequence number.
_SERIAL_RE = re.compile(r"^RMN-\d{6}$")


def assert_common_fields(data: dict):
    """Fields every primary resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert _ISO8601_3F_RE.match(data.get("created_at", "") or ""), (
        f"created_at must be ISO 8601 UTC with three fractional digits: "
        f"{data.get('created_at')!r}"
    )
    assert _ISO8601_3F_RE.match(data.get("updated_at", "") or ""), (
        f"updated_at must be ISO 8601 UTC with three fractional digits: "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def assert_distributor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["distributor_code"], str) and data["distributor_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["emissions_requirement"] in ("FEDERAL", "CALIFORNIA")
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["volume_discount_pct"], (int, float))
    assert 0 <= data["volume_discount_pct"] <= 0.5
    assert isinstance(data["deposits_held_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)


def assert_core_return(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["build_spec_id"])
    assert data["core_deposit_id"] is None or is_valid_uuid(data["core_deposit_id"])
    assert data["status"] in ("RECEIVED", "GRADED", "DISPUTED", "CLOSED")
    assert data["grade"] is None or data["grade"] in (
        "GRADE_A", "GRADE_B", "GRADE_C", "REJECT")
    assert isinstance(data["missing_components"], list)
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["final_credit_cents"] is None or isinstance(
        data["final_credit_cents"], int)
    assert isinstance(data["dispute_count"], int) and data["dispute_count"] >= 0


def assert_core_deposit(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["distributor_id"])
    assert is_valid_uuid(data["reman_engine_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("HELD", "CLOSED_REFUNDED", "FORFEITED")
    assert isinstance(data["refunded_cents"], int)
    assert isinstance(data["forfeited_cents"], int)
    assert data["age_days_at_close"] is None or isinstance(
        data["age_days_at_close"], int)
    if data["status"] in ("CLOSED_REFUNDED", "FORFEITED"):
        # PRD §3.4: refunded + forfeited always recombines to the amount.
        assert data["refunded_cents"] + data["forfeited_cents"] == data["amount_cents"]


def assert_build_spec(data: dict):
    assert_common_fields(data)
    assert isinstance(data["engine_family"], str) and data["engine_family"]
    assert isinstance(data["application_code"], str) and data["application_code"]
    assert data["emissions_tier"] in ("FEDERAL", "CALIFORNIA")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["core_deposit_cents"], int)
    assert isinstance(data["core_base_credit_cents"], int)
    assert isinstance(data["allowed_reuse_grades"], list)
    assert set(data["allowed_reuse_grades"]) <= {"REUSE_OK", "REWORK"}
    assert isinstance(data["allowed_interchange_groups"], list)
    assert isinstance(data["dyno_min_horsepower"], int)
    assert isinstance(data["dyno_min_oil_pressure_psi"], (int, float))
    assert isinstance(data["dyno_max_coolant_temp_f"], int)
    assert isinstance(data["required_op_sequence"], list)
    assert set(data["required_op_sequence"]) <= {"BORE", "DECK", "CRANK_GRIND"}


def assert_work_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["core_return_id"])
    assert is_valid_uuid(data["build_spec_id"])
    assert data["status"] in ("QUEUED", "TEARDOWN", "MACHINING", "ASSEMBLY",
                              "DYNO_TEST", "CLOSED", "CANCELLED")
    assert data["reman_engine_id"] is None or is_valid_uuid(data["reman_engine_id"])
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_machine_operation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["op_type"] in ("BORE", "DECK", "CRANK_GRIND")
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["status"] in ("PENDING", "COMPLETED", "FAILED")
    assert data["result"] is None or data["result"] in ("PASS", "FAIL")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_component(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert data["part_type"] in ("CRANKSHAFT", "CYLINDER_HEAD",
                                 "ENGINE_BLOCK", "CAMSHAFT")
    assert isinstance(data["interchange_group"], str)
    assert data["reuse_grade"] is None or data["reuse_grade"] in (
        "REUSE_OK", "REWORK", "SCRAP")
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "CONSUMED", "SCRAPPED")
    assert data["consumed_by_work_order_id"] is None or is_valid_uuid(
        data["consumed_by_work_order_id"])


def assert_reman_engine(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["work_order_id"])
    assert is_valid_uuid(data["build_spec_id"])
    assert _SERIAL_RE.match(data.get("serial_number", "") or ""), (
        f"serial_number must be 'RMN-' + six digits: {data.get('serial_number')!r}"
    )
    assert data["status"] in ("BUILT", "DYNO_PASSED", "SEALED", "SOLD",
                              "RETURNED", "SCRAPPED")
    assert data["latest_dyno_result"] is None or data["latest_dyno_result"] in (
        "PASS", "FAIL")
    assert data["distributor_id"] is None or is_valid_uuid(data["distributor_id"])
    assert data["sale_price_cents"] is None or isinstance(
        data["sale_price_cents"], int)


def assert_dyno_test(data: dict):
    """DynoTest is immutable: id + created_at only, no updated_at/version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "DynoTest must not carry updated_at"
    assert "version" not in data, "DynoTest must not carry version"
    assert is_valid_uuid(data["reman_engine_id"])
    assert isinstance(data["recorded_by"], str) and data["recorded_by"]
    assert isinstance(data["dyno_cell_code"], str) and data["dyno_cell_code"]
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["attempt"], int) and data["attempt"] >= 1
    assert isinstance(data["horsepower"], int)
    assert isinstance(data["oil_pressure_psi"], (int, float))
    assert isinstance(data["coolant_temp_f"], int)


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["reman_engine_id"])
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["failure_description"], str)
    assert data["status"] in ("OPEN", "TEARDOWN_COMPLETE", "APPROVED_CREDIT",
                              "APPROVED_REPLACEMENT", "DENIED")
    assert isinstance(data["months_in_service"], int)
    assert data["months_in_service"] >= 0
    assert data["settled_credit_cents"] is None or isinstance(
        data["settled_credit_cents"], int)


def assert_ledger_invariants(distributor: dict):
    """Distributor ledger sanity (PRD §3.1): deposits held never negative."""
    assert distributor["deposits_held_cents"] >= 0, (
        f"deposits_held_cents went negative: {distributor['deposits_held_cents']}"
    )
