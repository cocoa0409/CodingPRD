"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_audit_fields(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_doctor(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["practice_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["completed_case_count"], int)
    assert isinstance(data["account_credit_cents"], int)
    assert data["account_credit_cents"] >= 0


def assert_material(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["code"], str)
    assert isinstance(data["base_unit_price_cents"], int)
    assert data["base_unit_price_cents"] >= 1
    assert data["fabrication_process"] in ("MILLED", "PRINTED")
    assert isinstance(data["is_active"], bool)


def assert_mill_machine(data: dict):
    _assert_audit_fields(data)
    assert data["capability"] in ("MILLED", "PRINTED")
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_courier_route(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["max_stops"], int) and data["max_stops"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0


def assert_case(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["doctor_id"], str)
    assert data["intake_method"] in ("RX_PAPER", "IMPRESSION", "INTRAORAL_SCAN")
    assert isinstance(data["is_rush"], bool)
    assert data["status"] in (
        "INTAKE", "DESIGN", "FABRICATION", "TRY_IN", "REVISION",
        "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["billable_unit_count"], int) and data["billable_unit_count"] >= 0
    assert isinstance(data["sla_breached"], bool)


def assert_restoration(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["material_id"], str)
    assert data["restoration_type"] in ("CROWN", "BRIDGE", "DENTURE", "ALIGNER")
    assert isinstance(data["unit_count"], int) and data["unit_count"] >= 1
    assert isinstance(data["unit_price_cents"], int)


def assert_fabrication_unit(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["restoration_id"], str)
    assert data["status"] in (
        "QUEUED", "MILLING", "MILLED", "TRIED_IN", "PASSED", "REMADE_OUT",
    )
    assert isinstance(data["is_billable"], bool)


def assert_mill_job(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["fabrication_unit_id"], str)
    assert isinstance(data["mill_machine_id"], str)
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert data["status"] in ("SCHEDULED", "RUNNING", "DONE", "CANCELLED")


def assert_route_stop(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["courier_route_id"], str)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["window_minutes"], int) and data["window_minutes"] >= 1
    assert data["status"] in ("PLANNED", "COMPLETED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["case_id"], str)
    assert data["kind"] in ("PROVISIONAL", "FINAL")
    for f in ("subtotal_cents", "rush_surcharge_cents", "discount_cents",
              "tax_cents", "sla_credit_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["billing_status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert data["delivery_status"] in ("PENDING", "IN_TRANSIT", "DELIVERED")


def assert_credit_memo(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ISSUED", "VOID")


def assert_remake_request(data: dict):
    _assert_audit_fields(data)
    assert isinstance(data["case_id"], str)
    assert isinstance(data["fabrication_unit_id"], str)
    assert data["reason"] in ("SHADE_MISMATCH", "POOR_FIT", "FRACTURE", "CONTACT_OPEN")
    assert data["status"] in ("OPEN", "APPROVED", "DENIED", "COMPLETED")


def assert_invoice_total_identity(data: dict):
    """Invariant: total = subtotal + rush - discount + tax - sla_credit (PRD §3.3/§3.6)."""
    expected = (
        data["subtotal_cents"]
        + data["rush_surcharge_cents"]
        - data["discount_cents"]
        + data["tax_cents"]
        - data["sla_credit_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents identity violated: total={data['total_cents']} "
        f"!= subtotal+rush-discount+tax-sla_credit={expected}"
    )
