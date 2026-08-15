"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VESSEL_STATUSES = ["REGISTERED", "ACTIVE", "SUSPENDED", "DECOMMISSIONED"]
PERMIT_STATUSES = ["ISSUED", "SUSPENDED", "REVOKED", "EXPIRED"]
HOLDING_STATUSES = ["ACTIVE", "CLOSED"]
OPENING_STATUSES = ["SCHEDULED", "OPEN", "CLOSED", "CLOSED_EARLY"]
TRIP_STATUSES = ["PLANNED", "DEPARTED", "RETURNED", "LANDING_FINALIZED", "SETTLED", "CANCELLED"]
DECLARATION_STATUSES = ["DRAFT", "SUBMITTED", "DISPUTED", "AMENDED", "VERIFIED", "FINALIZED"]
TRANSFER_STATUSES = ["PROPOSED", "COUNTERED", "ACCEPTED", "SETTLED", "DECLINED", "WITHDRAWN", "EXPIRED"]
OBSERVER_STATUSES = ["AVAILABLE", "ON_ASSIGNMENT"]
ASSIGNMENT_STATUSES = [
    "REQUESTED", "ASSIGNED", "CONFIRMED", "DEPLOYED",
    "DEBRIEFED", "RELEASED", "WAIVED", "CANCELLED",
]
CREW_STATUSES = ["ACTIVE", "INACTIVE"]
EXPENSE_STATUSES = ["PENDING", "VERIFIED", "REJECTED"]
SETTLEMENT_STATUSES = ["DRAFT", "CALCULATED", "DISPUTED", "APPROVED", "PAID"]
VIOLATION_STATUSES = ["OPEN", "ADJUDICATED", "DISMISSED", "APPEALED", "REVERSED", "UPHELD"]
GEAR_ASSET_STATUSES = ["OPERATIONAL", "DOWN"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """PRD §2.4: append-only event records carry only id and created_at —
    both updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_vessel(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["home_port"], str) and data["home_port"]
    assert isinstance(data["length_ft"], int) and data["length_ft"] > 0
    assert data["observer_coverage_class"] in ["FULL", "PARTIAL", "EXEMPT"]
    assert isinstance(data["compliance_points"], int)
    assert data["status"] in VESSEL_STATUSES


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert data["fishery_code"] in ["HALIBUT", "SABLEFISH", "POLLOCK", "PACIFIC_COD"]
    assert data["gear_type"] in ["TRAWL_NET", "LONGLINE", "POT", "GILLNET"]
    assert data["status"] in PERMIT_STATUSES


def assert_quota_holding(data: dict):
    _assert_common_fields(data)
    assert data["fishery_code"] in ["HALIBUT", "SABLEFISH", "POLLOCK", "PACIFIC_COD"]
    assert isinstance(data["season_year"], int)
    assert isinstance(data["initial_pounds"], int) and data["initial_pounds"] > 0
    assert isinstance(data["landed_pounds"], int) and data["landed_pounds"] >= 0
    assert data["status"] in HOLDING_STATUSES


def assert_season_opening(data: dict):
    _assert_common_fields(data)
    assert data["fishery_code"] in ["HALIBUT", "SABLEFISH", "POLLOCK", "PACIFIC_COD"]
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert isinstance(data["tac_pounds"], int) and data["tac_pounds"] > 0
    assert isinstance(data["landed_against_tac_pounds"], int)
    assert data["status"] in OPENING_STATUSES


def assert_fishing_trip(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["vessel_id"])
    assert is_valid_uuid(data["season_opening_id"])
    assert isinstance(data["observer_required"], bool)
    assert isinstance(data["observer_waived"], bool)
    assert data["status"] in TRIP_STATUSES


def assert_catch_report(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["haul_seq"], int) and data["haul_seq"] >= 1
    assert data["fishery_code"] in ["HALIBUT", "SABLEFISH", "POLLOCK", "PACIFIC_COD"]
    assert data["report_type"] in ["HARVEST", "DISCARD"]
    assert isinstance(data["reported_lbs"], int) and data["reported_lbs"] > 0


def assert_landing_declaration(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["port_code"], str) and data["port_code"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in DECLARATION_STATUSES


def assert_quota_transfer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["from_vessel_id"])
    assert is_valid_uuid(data["to_vessel_id"])
    assert isinstance(data["pounds"], int) and data["pounds"] > 0
    assert isinstance(data["price_per_lb_cents"], int) and data["price_per_lb_cents"] >= 0
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["last_offered_by"] in ["FROM_VESSEL", "TO_VESSEL"]
    assert data["status"] in TRANSFER_STATUSES


def assert_observer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["observer_name"], str) and data["observer_name"]
    assert data["certification_level"] in ["A", "B", "C"]
    assert data["status"] in OBSERVER_STATUSES


def assert_observer_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["trip_id"])
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_crew_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_name"], str) and data["crew_name"]
    assert data["share_points"] > 0
    assert data["status"] in CREW_STATUSES


def assert_expense_record(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ["FUEL", "BAIT", "ICE", "GROCERIES", "GEAR_REPAIR", "OTHER"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in EXPENSE_STATUSES


def assert_trip_settlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] > 0
    assert isinstance(data["provisional_total_expenses_cents"], int)
    assert isinstance(data["provisional_processing_fee_cents"], int)
    assert isinstance(data["provisional_vessel_share_cents"], int)
    assert isinstance(data["provisional_crew_pool_cents"], int)
    assert data["status"] in SETTLEMENT_STATUSES


def assert_gear_asset(data: dict):
    _assert_common_fields(data)
    assert data["gear_type"] in ["TRAWL_NET", "LONGLINE", "POT", "GILLNET"]
    assert isinstance(data["units_total"], int) and data["units_total"] > 0
    assert isinstance(data["units_lost"], int) and data["units_lost"] >= 0
    assert isinstance(data["units_in_maintenance"], int) and data["units_in_maintenance"] >= 0
    assert isinstance(data["units_operational"], int)
    assert data["units_operational"] == (
        data["units_total"] - data["units_lost"] - data["units_in_maintenance"]
    ), "units_operational must equal units_total - units_lost - units_in_maintenance"
    assert data["status"] in GEAR_ASSET_STATUSES


def assert_gear_event(data: dict):
    _assert_append_only_fields(data)
    assert data["event_type"] in ["LOSS", "REPAIR", "MAINTENANCE_START", "MAINTENANCE_END"]
    assert isinstance(data["units"], int) and data["units"] > 0


def assert_vms_ping(data: dict):
    _assert_append_only_fields(data)
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert data["violation_type"] in [
        "OVER_QUOTA", "OUT_OF_SEASON", "OBSERVER_BREACH",
        "VMS_GAP", "GEAR_MISMATCH", "MANUAL_CITATION",
    ]
    assert isinstance(data["season_year"], int)
    assert data["status"] in VIOLATION_STATUSES


def assert_settlement_books_balance(settlement: dict):
    """PRD §3.8: gross revenue equals the sum of total expenses, observer fee,
    gear loss charge, processing fee, vessel share, and crew pool."""
    total = (
        settlement["total_expenses_cents"]
        + settlement["observer_fee_cents"]
        + settlement["gear_loss_charge_cents"]
        + settlement["processing_fee_cents"]
        + settlement["vessel_share_cents"]
        + settlement["crew_pool_cents"]
    )
    assert total == settlement["gross_revenue_cents"], (
        f"Books do not balance: components sum to {total}, "
        f"gross is {settlement['gross_revenue_cents']}"
    )


def assert_crew_payouts_sum_to_pool(settlement: dict):
    """PRD §3.8: crew payouts always sum exactly to crew_pool_cents."""
    payouts = settlement.get("crew_payouts") or []
    total = sum(p["payout_cents"] for p in payouts)
    assert total == settlement["crew_pool_cents"], (
        f"Crew payouts sum to {total}, crew_pool_cents is {settlement['crew_pool_cents']}"
    )


def payout_for(settlement: dict, crew_contract_id: str) -> int:
    for entry in settlement.get("crew_payouts") or []:
        if entry["crew_contract_id"] == crew_contract_id:
            return entry["payout_cents"]
    raise AssertionError(f"No crew_payouts entry for contract {crew_contract_id}")
