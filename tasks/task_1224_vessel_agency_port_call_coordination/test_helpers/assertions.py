"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_principal(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_port_call(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("principal_id", ""))
    assert isinstance(data["vessel_name"], str)
    assert isinstance(data["imo_number"], str)
    assert isinstance(data["vessel_gt"], int) and data["vessel_gt"] > 0
    assert isinstance(data["port_code"], str)
    assert data["ops_status"] in (
        "NOMINATED", "PRE_ARRIVAL_FILED", "CLEARED_TO_ENTER",
        "ALONGSIDE", "SAILED", "CLOSED", "CANCELLED",
    )
    assert isinstance(data["alongside_days_estimated"], int) and data["alongside_days_estimated"] >= 1


def assert_authority_notification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["authority_type"] in ("PORT_STATE_CONTROL", "IMMIGRATION", "CUSTOMS", "HARBOR_MASTER")
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED", "REJECTED", "WITHDRAWN")
    assert isinstance(data.get("revision_count", 0), int)


def assert_berth_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert isinstance(data["berth_code"], str)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "OCCUPIED", "RELEASED", "CANCELLED")


def assert_service_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["kind"] in ("PILOT", "TUG", "LINEBOAT", "LAUNCH")
    assert data["status"] in ("ORDERED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimated_cents"], int)
    assert isinstance(data.get("cancellation_fee_cents", 0), int)


def assert_crew_change(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["direction"] in ("ON_SIGNER", "OFF_SIGNER")
    assert data["status"] in (
        "REQUESTED", "DOCS_VERIFIED", "VISA_PENDING", "VISA_GRANTED",
        "SHORE_PASS_ISSUED", "PASS_EXPIRED", "COMPLETED", "CANCELLED", "REPATRIATED",
    )


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["categories"], list) and len(data["categories"]) >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert is_valid_uuid(data.get("vendor_id", ""))
    assert data["category"] in ("PROVISIONS", "BUNKERS", "REPAIRS", "STORES")
    assert isinstance(data["estimated_cents"], int)
    assert data["status"] in (
        "DRAFT", "SENT", "ACKNOWLEDGED", "DELIVERED", "INVOICED",
        "DISPUTED", "MATCHED", "CANCELLED",
    )


def assert_cargo_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["doc_type"] in ("BILL_OF_LADING", "CARGO_MANIFEST", "DELIVERY_ORDER")
    assert data["status"] in ("RECEIVED", "VERIFIED", "ON_HOLD", "RELEASED")


def assert_tariff(data: dict):
    _assert_common(data)
    assert isinstance(data["port_code"], str)
    assert data["component"] in ("PORT_DUES", "BERTH_HIRE", "PILOTAGE")
    assert isinstance(data["gt_tiers"], list) and len(data["gt_tiers"]) >= 1
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")


def assert_disbursement_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["status"] in (
        "PRO_FORMA", "SENT_TO_PRINCIPAL", "FUNDED", "FINAL",
        "DISPUTED", "SETTLED", "SUPERSEDED",
    )
    assert isinstance(data["total_estimated_cents"], int)
    assert isinstance(data["agency_fee_estimated_cents"], int)
    assert isinstance(data["advance_required_cents"], int)
    assert isinstance(data["advances_received_cents"], int)
    assert isinstance(data["advances_applied_cents"], int)
    assert isinstance(data["advances_refunded_cents"], int)
    assert isinstance(data["funding_available_cents"], int)


def assert_da_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("da_id", ""))
    assert data["category"] in (
        "PORT_DUES", "PILOTAGE", "TOWAGE", "BERTH_HIRE", "PROVISIONS",
        "BUNKERS", "REPAIRS", "STORES", "CREW_COSTS", "CANCELLATION_FEE", "SUNDRY",
    )
    assert data["status"] in ("ESTIMATED", "ACTUALIZED", "DISPUTED")
    assert data["source_type"] in ("TARIFF", "SERVICE_ORDER", "PURCHASE_ORDER", "MANUAL")
    assert isinstance(data["estimated_cents"], int)


def assert_funding_advance(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("da_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["applied_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ("RECEIVED", "APPLIED", "REFUNDED")


def assert_cost_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("da_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in (
        "RAISED", "UNDER_REVIEW", "REJECTED", "ESCALATED",
        "UPHELD", "RESOLVED_ACCEPTED", "RESOLVED_REJECTED",
    )


def assert_husbandry_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("port_call_id", ""))
    assert data["case_type"] in ("MEDICAL", "REPATRIATION", "DESERTION", "OTHER")
    assert data["severity"] in ("ROUTINE", "URGENT", "CRITICAL")
    assert data["status"] in ("OPEN", "IN_TREATMENT", "CLEARED", "REPATRIATED")


def assert_da_funding_invariants(da: dict):
    """Ledger invariants that must hold after any funding operation."""
    available = (
        da["advances_received_cents"]
        - da["advances_applied_cents"]
        - da["advances_refunded_cents"]
    )
    assert available >= 0, "funding available must never go negative"
    assert da["funding_available_cents"] == available, (
        f"funding_available_cents {da['funding_available_cents']} != "
        f"received - applied - refunded = {available}"
    )
