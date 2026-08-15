"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every primary resource carries id / created_at / updated_at / version (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_owner_operator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["cdl_number"], str) and data["cdl_number"]
    assert data["classification_status"] in ("PENDING_REVIEW", "VERIFIED", "FLAGGED")


def assert_truck(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["year"], int)
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["odometer_current"], int)
    assert isinstance(data["powertrain_warranty_mileage_limit"], int)
    assert data["status"] in ("AVAILABLE", "LEASED", "IN_RETURN", "RETURNED", "SOLD")


def assert_lease_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["owner_operator_id"])
    assert is_valid_uuid(data["truck_id"])
    assert isinstance(data["term_weeks"], int) and data["term_weeks"] > 0
    for field in ("weekly_payment_cents", "escrow_weekly_contribution_cents",
                  "escrow_cap_cents", "buyout_base_price_cents",
                  "min_revenue_guarantee_weekly_cents", "missed_payment_count",
                  "arrears_cents", "total_payments_applied_cents"):
        assert isinstance(data[field], int), f"{field} must be int"
    assert isinstance(data["escrow_satisfied"], bool)
    assert data["status"] in ("APPLICATION", "ACTIVE", "DEFAULTED", "TERMINATED", "COMPLETED")


def assert_escrow_account(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    for field in ("balance_cents", "total_credited_cents",
                  "total_refunded_cents", "total_applied_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be int >= 0"
    assert data["status"] in ("ACCUMULATING", "FULL", "REFUND_PENDING", "REFUNDED", "CLOSED")


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["fuel_gallons"], (int, float))
    assert isinstance(data["fuel_price_cents_per_gallon"], int)
    assert isinstance(data["insurance_weekly_cents"], int)
    assert isinstance(data["miles_driven"], int)
    assert isinstance(data["load_declined_flag"], bool)
    for field in ("fuel_deduction_cents", "maintenance_deduction_cents",
                  "guarantee_top_up_cents", "escrow_contribution_cents",
                  "lease_payment_applied_cents", "net_pay_cents"):
        assert isinstance(data[field], int), f"{field} must be int"
    assert data["net_pay_cents"] >= 0, "net_pay_cents is never below zero"
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "FINALIZED", "CANCELLED")


def assert_lane_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["origin"], str) and data["origin"]
    assert isinstance(data["destination"], str) and data["destination"]
    assert isinstance(data["weekly_commitment_cents"], int)
    assert data["status"] in ("OFFERED", "ACCEPTED", "COMPLETED", "DECLINED", "REVOKED")


def assert_service_bay(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert isinstance(data["location"], str) and data["location"]


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["service_bay_id"])
    assert data["category"] in ("PREVENTIVE", "REPAIR", "RECALL")
    assert isinstance(data["description"], str)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in ("OPEN", "COMPLETED", "CANCELLED")
    if data["status"] == "COMPLETED":
        assert data["billed_to"] in ("CARRIER", "OPERATOR", "WARRANTY")
        assert isinstance(data["actual_cost_cents"], int)
        assert isinstance(data["odometer_at_service"], int)
        assert is_iso8601_timestamp(data["completed_at"])


def assert_compliance_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["owner_operator_id"])
    assert data["doc_type"] in ("W9", "OPERATING_AUTHORITY", "INSURANCE_CERTIFICATE", "MEDICAL_CARD")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_buyout_quote(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["lease_id"])
    assert data["quote_kind"] in ("SCHEDULED", "EARLY")
    for field in ("quoted_price_cents", "escrow_credit_cents",
                  "arrears_carried_cents", "amount_due_cents"):
        assert isinstance(data[field], int), f"{field} must be int"
    assert data["amount_due_cents"] >= 0
    assert data["status"] in ("GENERATED", "ACCEPTED", "DECLINED", "SUPERSEDED")


def assert_escrow_conservation(data: dict):
    """Escrow dollars are conserved: lifetime credits always equal the sum of
    current balance, lifetime refunds, and lifetime applications."""
    lhs = data["total_credited_cents"]
    rhs = data["balance_cents"] + data["total_refunded_cents"] + data["total_applied_cents"]
    assert lhs == rhs, (
        f"Escrow conservation violated: total_credited_cents {lhs} != "
        f"balance {data['balance_cents']} + refunded {data['total_refunded_cents']} "
        f"+ applied {data['total_applied_cents']}"
    )


def assert_settlement_funds_conservation(data: dict):
    """Weekly settlement funds are conserved: gross + guarantee top-up always
    equals the sum of the five waterfall outflows and net pay."""
    lhs = data["gross_revenue_cents"] + data["guarantee_top_up_cents"]
    rhs = (data["fuel_deduction_cents"] + data["insurance_weekly_cents"]
           + data["maintenance_deduction_cents"] + data["escrow_contribution_cents"]
           + data["lease_payment_applied_cents"] + data["net_pay_cents"])
    assert lhs == rhs, (
        f"Settlement funds not conserved: gross+top_up {lhs} != fuel+insurance+maintenance"
        f"+escrow+lease+net {rhs}"
    )
