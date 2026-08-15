"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: every primary resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_lta(data: dict):
    _assert_common_fields(data, "LongTermAgreement")
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["ceiling_cents"], int) and data["ceiling_cents"] > 0
    assert isinstance(data["remaining_ceiling_cents"], int)
    assert isinstance(data["pricing_tiers"], list) and len(data["pricing_tiers"]) >= 1
    assert isinstance(data["committed_monthly_rate_units"], int)
    assert isinstance(data["consecutive_not_ready_count"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert data.get("last_audit_result") in [None, "READY", "MARGINAL", "NOT_READY"]


def assert_purchase_order(data: dict):
    _assert_common_fields(data, "PurchaseOrder")
    assert isinstance(data["lta_id"], str)
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["part_revision"], str) and data["part_revision"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["flowdown_clauses"], list)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["lta_version_pinned"], int)
    assert isinstance(data["unreleased_quantity"], int)
    assert isinstance(data["delivered_quantity"], int)
    assert data["status"] in [
        "RECEIVED",
        "ACCEPTED",
        "RELEASED",
        "CLOSED",
        "CANCELLED",
    ]


def assert_fai(data: dict):
    _assert_common_fields(data, "FirstArticleInspection")
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["part_revision"], str) and data["part_revision"]
    assert data["fai_type"] in ["FULL", "PARTIAL"]
    assert data["status"] in [
        "DRAFT",
        "IN_INSPECTION",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
    ]
    assert isinstance(data["characteristic_count"], int)
    assert isinstance(data["measured_count"], int)
    assert isinstance(data["characteristics_complete"], bool)


def assert_characteristic(data: dict):
    _assert_common_fields(data, "BalloonedCharacteristic")
    assert isinstance(data["fai_id"], str)
    assert isinstance(data["balloon_number"], int)
    assert isinstance(data["nominal"], (int, float))
    assert data["tolerance_plus"] >= 0
    assert data["tolerance_minus"] >= 0
    assert isinstance(data["is_key_characteristic"], bool)
    assert data["result"] in ["UNMEASURED", "PASS", "FAIL"]
    assert data["spc_eval_status"] in ["NONE", "MONITORING", "CAPABLE", "INCAPABLE"]
    # usl/lsl computed from nominal and tolerances (PRD §3.4)
    assert abs(data["usl"] - (data["nominal"] + data["tolerance_plus"])) < 1e-9
    assert abs(data["lsl"] - (data["nominal"] - data["tolerance_minus"])) < 1e-9


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert isinstance(data["po_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["special_processes_required"], list)
    assert data["status"] in [
        "PLANNED",
        "RELEASED",
        "IN_PRODUCTION",
        "QUALITY_HOLD",
        "FINAL_INSPECTION",
        "COMPLETED",
        "CANCELLED",
    ]
    assert isinstance(data["serials_created_count"], int)
    assert isinstance(data["good_quantity"], int)
    assert isinstance(data["scrapped_quantity"], int)
    assert data["spc_status"] in ["MONITORING", "CAPABLE", "INCAPABLE"]
    assert isinstance(data["requires_100pct_inspection"], bool)


def assert_serial(data: dict):
    _assert_common_fields(data, "SerialNumber")
    assert isinstance(data["wo_id"], str)
    assert isinstance(data["material_cert_id"], str)
    assert isinstance(data["serial_number"], str) and data["serial_number"].startswith(
        "SN-"
    )
    assert data["status"] in ["CREATED", "SHIPPED", "SCRAPPED", "QUARANTINED"]


def assert_material_cert(data: dict):
    _assert_common_fields(data, "MaterialCert")
    assert isinstance(data["source_id"], str)
    assert isinstance(data["heat_number"], str) and data["heat_number"]
    assert isinstance(data["material_spec"], str) and data["material_spec"]
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] > 0
    assert isinstance(data["quantity_available"], int)
    assert data["status"] in ["RECEIVED", "ACCEPTED", "REVOKED"]


def assert_source(data: dict):
    _assert_common_fields(data, "ApprovedSource")
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert data["approval_scope"] in ["RAW_MATERIAL", "SPECIAL_PROCESS", "DISTRIBUTOR"]
    assert data["counterfeit_risk_rating"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in ["PROVISIONAL", "APPROVED", "DISQUALIFIED"]


def assert_process_approval(data: dict):
    _assert_common_fields(data, "SpecialProcessApproval")
    assert isinstance(data["source_id"], str)
    assert data["process_code"] in [
        "HEAT_TREAT",
        "NDT",
        "PLATING",
        "WELDING",
        "SHOT_PEEN",
    ]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_ncr(data: dict):
    _assert_common_fields(data, "NonconformanceReport")
    assert isinstance(data["wo_id"], str)
    assert isinstance(data["defect_code"], str) and data["defect_code"]
    assert isinstance(data["quantity_affected"], int) and data["quantity_affected"] > 0
    assert isinstance(data["affected_serial_ids"], list)
    assert isinstance(data["detected_post_shipment"], bool)
    assert data["origin"] in ["MANUAL", "AUTO_SPC", "AUTO_COUNTERFEIT"]
    assert data["status"] in [
        "OPEN",
        "MRB_REVIEW",
        "DISPOSITIONED",
        "VERIFIED",
        "CLOSED",
    ]
    assert data.get("disposition") in [
        None,
        "USE_AS_IS",
        "REWORK",
        "SCRAP",
        "RETURN_TO_SUPPLIER",
    ]


def assert_escape_report(data: dict):
    _assert_common_fields(data, "EscapeReport")
    assert isinstance(data["ncr_id"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED"]
    assert is_iso8601_timestamp(
        data.get("due_at", "")
    ), "EscapeReport.due_at must be ISO 8601"


def assert_delegation(data: dict):
    _assert_common_fields(data, "DelegatedInspectionAuthority")
    assert isinstance(data["po_id"], str)
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_to"], str)
    assert data["status"] in ["ACTIVE", "REVOKED"]


def assert_spc_measurement(data: dict):
    """Append-only observation (PRD §2.4): only id + created_at as system fields."""
    assert is_valid_uuid(data.get("id", "")), "SpcMeasurement.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "SpcMeasurement.created_at must be ISO 8601"
    assert "updated_at" not in data, "SpcMeasurement must not carry updated_at"
    assert "version" not in data, "SpcMeasurement must not carry version"
    assert isinstance(data["wo_id"], str)
    assert isinstance(data["characteristic_id"], str)
    assert isinstance(data["measured_value"], (int, float))


def assert_po_quantity_conservation(po: dict, open_wo_quantities: list):
    """PO units are conserved: quantity == unreleased + sum(non-CANCELLED WO qty)."""
    assert po["quantity"] == po["unreleased_quantity"] + sum(open_wo_quantities), (
        f"PO quantity {po['quantity']} != unreleased {po['unreleased_quantity']} "
        f"+ open WO quantities {open_wo_quantities}"
    )


def assert_lta_ceiling_conservation(lta: dict, open_po_totals: list):
    """Agreement funds are conserved: ceiling == remaining + sum(non-CANCELLED PO totals)."""
    assert lta["ceiling_cents"] == lta["remaining_ceiling_cents"] + sum(
        open_po_totals
    ), (
        f"LTA ceiling {lta['ceiling_cents']} != remaining "
        f"{lta['remaining_ceiling_cents']} + open PO totals {open_po_totals}"
    )
