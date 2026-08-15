"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_fields(data: dict):
    """Ledger records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_generator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["hq_state_code"], str) and len(data["hq_state_code"]) == 2
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["total_credits"], (int, float))
    assert data["credit_tier"] in ["STANDARD", "SILVER", "GOLD"]


def assert_offtaker(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["hq_state_code"], str) and len(data["hq_state_code"]) == 2
    assert isinstance(data["receiving_state_codes"], list)
    assert all(isinstance(code, str) for code in data["receiving_state_codes"])


def assert_stream(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["generator_id"])
    assert data["material_type"] in [
        "FLY_ASH",
        "SLAG",
        "GYPSUM",
        "FOUNDRY_SAND",
        "BIOSOLIDS",
    ]
    assert isinstance(data["declared_moisture_pct"], (int, float))
    assert isinstance(data["expected_tons_per_month"], int)
    assert data["status"] in ["DRAFT", "CHARACTERIZED", "ACTIVE"]


def assert_characterization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["stream_id"])
    assert isinstance(data["lab_name"], str) and data["lab_name"]
    assert isinstance(data["sampled_on"], str) and data["sampled_on"]
    assert isinstance(data["ph"], (int, float))
    assert isinstance(data["arsenic_ppm"], (int, float))
    assert isinstance(data["lead_ppm"], (int, float))
    assert isinstance(data["moisture_pct_measured"], (int, float))
    assert data["status"] in ["SUBMITTED", "VERIFIED", "REJECTED"]


def assert_eligibility(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["stream_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["use_case"] in [
        "CEMENT_ADDITIVE",
        "ROAD_BASE",
        "SOIL_AMENDMENT",
        "MINE_RECLAMATION",
    ]
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DENIED",
        "SUSPENDED",
        "EXPIRED",
    ]


def assert_state_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["material_type"] in [
        "FLY_ASH",
        "SLAG",
        "GYPSUM",
        "FOUNDRY_SAND",
        "BIOSOLIDS",
    ]
    assert data["regime"] in ["PERMIT", "NOTIFICATION"]
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert isinstance(data["issued_on"], str)
    assert isinstance(data["expires_on"], str)
    assert data["status"] in ["FILED", "ACTIVE", "REVOKED", "EXPIRED"]


def assert_supply_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["generator_id"])
    assert is_valid_uuid(data["stream_id"])
    assert isinstance(data["committed_monthly_tons"], int)
    assert 0 < data["revenue_share_pct_to_generator"] < 1
    assert 0 <= data["freight_share_pct_to_generator"] <= 1
    assert isinstance(data["term_start"], str)
    assert isinstance(data["term_end"], str)
    assert isinstance(data["booked_month_to_date_tons"], (int, float))
    assert isinstance(data["delivered_month_to_date_tons"], (int, float))
    assert isinstance(data["counter_month"], str)
    assert data["fulfillment_status"] in ["UNMET", "MET"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_offtake_commitment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["offtaker_id"])
    assert is_valid_uuid(data["stream_id"])
    assert isinstance(data["destination_state_code"], str)
    assert isinstance(data["committed_monthly_tons"], int)
    assert isinstance(data["max_moisture_pct"], (int, float))
    assert isinstance(data["max_arsenic_ppm"], (int, float))
    assert isinstance(data["accepted_month_to_date_tons"], (int, float))
    assert isinstance(data["cumulative_rejected_tons"], (int, float))
    assert isinstance(data["counter_month"], str)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["supply_agreement_id"])
    assert is_valid_uuid(data["offtake_commitment_id"])
    assert isinstance(data["pickup_date"], str)
    assert isinstance(data["distance_miles"], int) and data["distance_miles"] >= 0
    assert isinstance(data["gross_tons"], (int, float)) and data["gross_tons"] > 0
    assert isinstance(data["loading_moisture_pct"], (int, float))
    assert isinstance(data["price_at_pickup_cents_per_ton"], int)
    assert isinstance(data["freight_total_cents"], int)
    assert isinstance(data["generator_freight_share_cents"], int)
    assert isinstance(data["broker_freight_share_cents"], int)
    assert isinstance(data["provisional_settlement_cents"], int)
    assert data["status"] in [
        "BOOKED",
        "DISPATCHED",
        "DELIVERED",
        "ACCEPTED",
        "REJECTED",
        "RECONDITIONING",
        "VOIDED",
        "CANCELLED",
        "DISPOSED",
    ]


def assert_storage_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["material_types_allowed"], list)
    assert isinstance(data["capacity_tons"], int) and data["capacity_tons"] > 0
    assert isinstance(data["current_inventory_tons"], (int, float))
    assert data["current_inventory_tons"] >= 0


def assert_storage_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["stream_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["tons"], (int, float)) and data["tons"] > 0
    assert data["status"] in ["RESERVED", "CHECKED_IN", "RELEASED", "CANCELLED"]


def assert_price_index_entry(data: dict):
    _assert_append_only_fields(data)
    assert data["material_type"] in [
        "FLY_ASH",
        "SLAG",
        "GYPSUM",
        "FOUNDRY_SAND",
        "BIOSOLIDS",
    ]
    assert isinstance(data["region_code"], str) and len(data["region_code"]) == 2
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["price_cents_per_ton"], int) and data["price_cents_per_ton"] > 0
    assert isinstance(data["published_by_user_id"], str) and data["published_by_user_id"]


def assert_credit_entry(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data["generator_id"])
    assert is_valid_uuid(data["shipment_id"])
    assert data["entry_type"] in ["ACCRUAL", "REVERSAL"]
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert isinstance(data["tons_credited"], (int, float))
    assert isinstance(data["credits"], (int, float)) and data["credits"] > 0


def assert_freight_split_invariants(shipment: dict):
    """Freight split must always conserve the total (PRD §3.4)."""
    assert (
        shipment["generator_freight_share_cents"] + shipment["broker_freight_share_cents"]
        == shipment["freight_total_cents"]
    ), "generator + broker freight shares must sum to freight_total_cents"
    assert shipment["generator_freight_share_cents"] <= 60000, "generator share is capped"
