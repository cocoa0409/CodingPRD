"""Entity assertions and domain invariant checkers.

Field sets follow the PRD exactly: every primary resource carries id,
created_at, updated_at, version (PRD §2.4), plus its domain fields (PRD §3).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer, got {data.get('version')!r}"
    )


def assert_jurisdiction_profile(data: dict):
    _assert_common(data, "JurisdictionProfile")
    assert isinstance(data["code"], str) and data["code"]
    for f in ("deposit_return_deadline_days", "dispute_window_days", "annual_interest_rate_bp",
              "stale_check_days", "small_claims_cap_cents", "bad_faith_multiplier"):
        assert isinstance(data[f], int), f"JurisdictionProfile.{f} must be int"
    for f in ("interest_required", "lock_change_allowed", "allow_actual_cost_charge"):
        assert isinstance(data[f], bool), f"JurisdictionProfile.{f} must be bool"
    assert data["interest_basis"] in ("ACTUAL_DAYS", "WHOLE_YEARS")


def assert_property(data: dict):
    _assert_common(data, "Property")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["address"], str)
    assert is_valid_uuid(data.get("jurisdiction_profile_id", ""))
    for f in ("key_charge_cents", "fob_charge_cents", "lock_change_cents"):
        assert isinstance(data[f], int), f"Property.{f} must be int"


def assert_unit(data: dict):
    _assert_common(data, "Unit")
    assert is_valid_uuid(data.get("property_id", ""))
    assert isinstance(data["unit_number"], str) and data["unit_number"]
    assert isinstance(data["carpet_installed_on"], str)
    assert isinstance(data["carpet_life_years"], int)
    assert isinstance(data["paint_applied_on"], str)
    assert isinstance(data["paint_life_years"], int)
    assert data["occupancy_status"] in ("AVAILABLE", "OCCUPIED", "RESERVED")


def assert_tenancy(data: dict):
    _assert_common(data, "Tenancy")
    assert is_valid_uuid(data.get("unit_id", ""))
    assert isinstance(data["tenant_display_name"], str)
    assert data.get("forwarding_address") is None or isinstance(data["forwarding_address"], str)
    assert isinstance(data["lease_start_on"], str)
    assert isinstance(data["lease_end_on"], str)
    for f in ("monthly_rent_cents", "deposit_cents", "keys_issued", "fobs_issued",
              "keys_returned", "fobs_returned", "interest_accrued_cents",
              "pending_deductions_cents", "total_deductions_cents", "refund_paid_cents",
              "penalty_paid_cents", "escheated_cents", "balance_remaining_cents",
              "released_cents", "reserved_cents"):
        assert isinstance(data[f], int), f"Tenancy.{f} must be int, got {data.get(f)!r}"
    for f in ("move_in_on", "notice_given_on", "move_out_on"):
        assert data.get(f) is None or isinstance(data[f], str)
    assert data["status"] in ("PENDING_MOVE_IN", "OCCUPIED", "NOTICE_GIVEN",
                              "VACATED", "SETTLED", "ESCHEATED")


def assert_inspection(data: dict):
    _assert_common(data, "Inspection")
    assert is_valid_uuid(data.get("tenancy_id", ""))
    assert data["kind"] in ("MOVE_IN", "MOVE_OUT")
    assert isinstance(data["inspector_user_id"], str)
    assert isinstance(data["scheduled_start_at"], str)
    assert isinstance(data["scheduled_end_at"], str)
    assert data.get("completed_at") is None or isinstance(data["completed_at"], str)
    assert data["status"] in ("DRAFT", "COMPLETED")


def assert_inspection_item(data: dict):
    _assert_common(data, "InspectionItem")
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert isinstance(data["area_name"], str)
    assert data["category"] in ("CARPET", "PAINT", "OTHER")
    assert data["condition"] in ("NEW", "GOOD", "FAIR", "WORN", "DAMAGED", "MISSING")
    assert isinstance(data["photo_count"], int)
    assert data["determination"] in ("UNASSESSED", "NORMAL_WEAR", "TENANT_DAMAGE")
    assert data.get("linked_move_in_item_id") is None or isinstance(data["linked_move_in_item_id"], str)
    assert data.get("replacement_cost_cents") is None or isinstance(data["replacement_cost_cents"], int)
    assert data.get("actual_repair_cents") is None or isinstance(data["actual_repair_cents"], int)
    assert data.get("notes") is None or isinstance(data["notes"], str)


def assert_deduction_item(data: dict):
    _assert_common(data, "DeductionItem")
    assert is_valid_uuid(data.get("tenancy_id", ""))
    assert data.get("inspection_item_id") is None or isinstance(data["inspection_item_id"], str)
    assert data.get("statement_id") is None or isinstance(data["statement_id"], str)
    assert data["source"] in ("MOVE_OUT_DAMAGE", "KEY_NOT_RETURNED", "FOB_NOT_RETURNED",
                              "LOCK_CHANGE", "UNPAID_RENT", "CLEANING", "OTHER")
    assert isinstance(data["description"], str)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("DRAFT", "BILLED")


def assert_deposit_statement(data: dict):
    _assert_common(data, "DepositStatement")
    assert is_valid_uuid(data.get("tenancy_id", ""))
    assert isinstance(data["statement_seq"], int)
    assert data.get("issued_at") is None or isinstance(data["issued_at"], str)
    assert data.get("deadline_on") is None or isinstance(data["deadline_on"], str)
    assert data.get("late") is None or isinstance(data["late"], bool)
    for f in ("interest_cents", "deduction_total_cents", "released_cents",
              "refund_due_cents", "projected_deductions_cents", "projected_refund_cents"):
        assert isinstance(data[f], int), f"DepositStatement.{f} must be int, got {data.get(f)!r}"
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "SUPERSEDED", "SETTLED")


def assert_dispute(data: dict):
    _assert_common(data, "Dispute")
    assert is_valid_uuid(data.get("statement_id", ""))
    assert is_valid_uuid(data.get("tenancy_id", ""))
    assert isinstance(data["disputed_amount_cents"], int)
    assert isinstance(data["reason"], str)
    assert data.get("counter_amount_cents") is None or isinstance(data["counter_amount_cents"], int)
    assert data.get("exposure_cents") is None or isinstance(data["exposure_cents"], int)
    assert data["status"] in ("OPEN", "MANAGER_COUNTERED", "CLOSED_AGREED",
                              "ESCALATED_SMALL_CLAIMS", "COURT_RESOLVED", "WITHDRAWN")


def assert_disbursement(data: dict):
    _assert_common(data, "Disbursement")
    assert is_valid_uuid(data.get("tenancy_id", ""))
    assert is_valid_uuid(data.get("statement_id", ""))
    assert data["kind"] in ("REFUND", "PENALTY")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["payee_name"], str)
    assert isinstance(data["sent_at"], str)
    assert data.get("cashed_at") is None or isinstance(data["cashed_at"], str)
    assert data.get("escheatment_reference") is None or isinstance(data["escheatment_reference"], str)
    assert data["status"] in ("SENT", "CASHED", "REVERSED", "STALE_DATED", "ESCHEATED")


def assert_tenancy_ledger_invariant(tenancy: dict):
    """The deposit-ledger identity of PRD §2.7 must hold on every read:
    balance == deposit + interest - total_deductions + released - refund_paid
              - escheated - reserved.
    """
    expected = (
        tenancy["deposit_cents"]
        + tenancy["interest_accrued_cents"]
        - tenancy["total_deductions_cents"]
        + tenancy["released_cents"]
        - tenancy["refund_paid_cents"]
        - tenancy["escheated_cents"]
        - tenancy["reserved_cents"]
    )
    assert tenancy["balance_remaining_cents"] == expected, (
        f"Ledger invariant violated: balance_remaining_cents "
        f"{tenancy['balance_remaining_cents']} != computed {expected} "
        f"(deposit={tenancy['deposit_cents']}, interest={tenancy['interest_accrued_cents']}, "
        f"billed={tenancy['total_deductions_cents']}, released={tenancy['released_cents']}, "
        f"paid={tenancy['refund_paid_cents']}, escheated={tenancy['escheated_cents']}, "
        f"reserved={tenancy['reserved_cents']})"
    )
