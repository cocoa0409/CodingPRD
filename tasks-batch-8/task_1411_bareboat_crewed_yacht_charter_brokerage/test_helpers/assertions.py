"""Entity assertions and domain invariant checkers (PRD sections 2.2-2.9)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_operator(data: dict):
    _assert_common_fields(data, "Operator")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_port"], str) and data["home_port"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_broker(data: dict):
    _assert_common_fields(data, "Broker")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["broker_type"] in ("CENTRAL_AGENT", "RETAIL_BROKER", "BOTH")
    assert isinstance(data["license_no"], str) and data["license_no"]


def assert_client(data: dict):
    _assert_common_fields(data, "Client")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["qualification_status"] in (
        "UNVERIFIED", "PENDING_REVIEW", "QUALIFIED", "REJECTED")


def assert_yacht(data: dict):
    _assert_common_fields(data, "Yacht")
    assert is_valid_uuid(data.get("operator_id", ""))
    assert is_valid_uuid(data.get("listing_central_agent_id", ""))
    assert data["charter_type"] in ("BAREBOAT", "CREWED")
    assert data["pricing_mode"] in ("PRO_RATA", "WEEKLY_PLUS_DAILY")
    assert data["status"] in ("DRAFT", "LISTED", "DELISTED")
    assert isinstance(data["capacity_berths"], int) and data["capacity_berths"] >= 1
    assert isinstance(data["weekly_base_rate_cents"], int)
    assert isinstance(data["min_charter_days"], int)
    assert data["required_resume_class"] in ("NONE", "COASTAL", "OFFSHORE", "OCEAN")
    assert isinstance(data["security_deposit_cents"], int)


def assert_availability_block(data: dict):
    _assert_common_fields(data, "AvailabilityBlock")
    assert is_valid_uuid(data.get("yacht_id", ""))
    assert data["block_type"] in ("MAINTENANCE", "OPERATOR_HOLD", "CHARTER")
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_charter_request(data: dict):
    _assert_common_fields(data, "CharterRequest")
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("yacht_id", ""))
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "OFFERED", "COUNTERED",
        "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    assert isinstance(data["guests_count"], int) and data["guests_count"] >= 1


def assert_charter_agreement(data: dict):
    _assert_common_fields(data, "CharterAgreement")
    assert is_valid_uuid(data.get("charter_request_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("yacht_id", ""))
    assert is_valid_uuid(data.get("operator_id", ""))
    assert is_valid_uuid(data.get("central_agent_id", ""))
    assert data["status"] in (
        "PENDING_SIGNATURES", "SIGNED", "IN_PREP", "UNDERWAY",
        "COMPLETED", "CANCELLED", "VOIDED")
    assert data["funds_status"] in (
        "UNFUNDED", "DEPOSIT_HELD", "FULLY_FUNDED",
        "SETTLING", "SETTLED", "REFUNDING", "REFUNDED")
    assert isinstance(data["charter_fee_cents"], int)
    assert isinstance(data["apa_amount_cents"], int)
    assert isinstance(data["signing_due_cents"], int)
    assert isinstance(data["final_due_cents"], int)


def assert_escrow_account(data: dict):
    _assert_common_fields(data, "EscrowAccount")
    assert is_valid_uuid(data.get("charter_agreement_id", ""))
    assert data["status"] in ("OPEN", "SETTLING", "CLOSED")
    for field in ("held_charter_fee_cents", "held_apa_cents", "held_deposit_cents",
                  "held_gratuity_cents", "total_funded_cents", "total_released_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"EscrowAccount.{field} must be a non-negative int"


def assert_escrow_movement(data: dict):
    """Ledger entry: only id + created_at from the common envelope."""
    assert is_valid_uuid(data.get("id", "")), "EscrowMovement.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "EscrowMovement.created_at must be ISO 8601"
    assert "updated_at" not in data, "EscrowMovement must not carry updated_at"
    assert "version" not in data, "EscrowMovement must not carry version"
    assert is_valid_uuid(data.get("escrow_account_id", ""))
    assert data["movement_type"] in (
        "CLIENT_FUND", "RELEASE_TO_OPERATOR", "RELEASE_TO_CENTRAL_AGENT",
        "RELEASE_TO_RETAIL_BROKER", "REFUND_TO_CLIENT")
    assert data["bucket"] in ("CHARTER_FEE", "APA", "DEPOSIT", "GRATUITY")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["memo"], str)


def assert_expense_entry(data: dict):
    _assert_common_fields(data, "ExpenseEntry")
    assert is_valid_uuid(data.get("charter_agreement_id", ""))
    assert data["bucket"] in ("APA", "DAMAGE_CLAIM")
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("PENDING", "APPROVED", "DISPUTED", "REJECTED")


def assert_itinerary_leg(data: dict):
    _assert_common_fields(data, "ItineraryLeg")
    assert is_valid_uuid(data.get("charter_agreement_id", ""))
    assert isinstance(data["seq_no"], int) and data["seq_no"] >= 1
    assert isinstance(data["port_name"], str) and data["port_name"]
    assert data["status"] in ("PLANNED", "PERMITTED")


def assert_port_permit(data: dict):
    _assert_common_fields(data, "PortPermit")
    assert is_valid_uuid(data.get("itinerary_leg_id", ""))
    assert isinstance(data["port_authority_ref"], str)
    assert data["status"] in ("REQUESTED", "GRANTED", "DENIED", "EXPIRED")


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data, "InsuranceCertificate")
    assert is_valid_uuid(data.get("charter_agreement_id", ""))
    assert isinstance(data["insurer_name"], str)
    assert isinstance(data["policy_no"], str)
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_commission_statement(data: dict):
    """Ledger-style resource: only id + created_at from the common envelope."""
    assert is_valid_uuid(data.get("id", "")), "CommissionStatement.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "CommissionStatement.created_at must be ISO 8601"
    assert "updated_at" not in data, "CommissionStatement must not carry updated_at"
    assert "version" not in data, "CommissionStatement must not carry version"
    assert is_valid_uuid(data.get("charter_agreement_id", ""))
    assert data["basis"] in ("CHARTER_FEE", "CANCELLATION_PENALTY")
    assert isinstance(data["basis_amount_cents"], int)
    assert isinstance(data["commission_total_cents"], int)
    assert isinstance(data["retail_share_cents"], int)
    assert isinstance(data["central_share_cents"], int)


def assert_escrow_closed_invariants(escrow: dict):
    """PRD closure invariant: funded == released, every held bucket at zero."""
    assert escrow["status"] == "CLOSED"
    assert escrow["total_funded_cents"] == escrow["total_released_cents"], (
        f"closed escrow must conserve cash: funded "
        f"{escrow['total_funded_cents']} != released {escrow['total_released_cents']}")
    for field in ("held_charter_fee_cents", "held_apa_cents",
                  "held_deposit_cents", "held_gratuity_cents"):
        assert escrow[field] == 0, f"closed escrow must have {field} == 0"


def summarize_movements(movements: list) -> dict:
    """Aggregate movement amounts keyed by (movement_type, bucket)."""
    totals: dict = {}
    for mv in movements:
        key = (mv["movement_type"], mv["bucket"])
        totals[key] = totals.get(key, 0) + mv["amount_cents"]
    return totals
