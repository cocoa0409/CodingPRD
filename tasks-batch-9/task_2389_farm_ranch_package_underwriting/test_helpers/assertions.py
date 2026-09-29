"""Entity assertions and domain invariant checkers."""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

MONEY_FIELDS_ON_POLICY = (
    "property_premium_cents",
    "livestock_premium_cents",
    "liability_premium_cents",
    "endorsement_premium_cents",
    "base_premium_cents",
    "cat_load_cents",
    "total_premium_cents",
)


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, label: str = "row") -> None:
    """Every persisted row carries a UUID `id` and an ISO 8601 `created_at`;
    most rows additionally carry `updated_at` and a `version` starting at 1."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version begins at 1, got {data['version']}"


def assert_three_fraction_digits(timestamp: str, label: str = "timestamp") -> None:
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(timestamp, str), f"{label} must be a string, got {timestamp!r}"
    assert is_iso8601_timestamp(timestamp), f"{label} is not ISO 8601 UTC: {timestamp!r}"
    assert "." in timestamp, f"{label} must carry fractional digits: {timestamp!r}"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"{label} must carry three fractional digits: {timestamp!r}"


def assert_all_null(data: dict, field_names, label: str = "row") -> None:
    for name in field_names:
        assert data.get(name, "MISSING") is None, (
            f"{label}.{name} must be null, got {data.get(name)!r}"
        )


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def assert_agent(data: dict) -> None:
    assert_common_fields(data, "Agent")
    assert isinstance(data["agency_name"], str) and 1 <= len(data["agency_name"]) <= 120
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert data["license_state"].isupper()
    assert data["appointment_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["authority_limit_cents"], int)
    assert data["authority_limit_cents"] >= 0


def assert_inspector(data: dict) -> None:
    assert_common_fields(data, "Inspector")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["region_code"], str) and 1 <= len(data["region_code"]) <= 12
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["daily_capacity_minutes"], int)
    assert data["daily_capacity_minutes"] >= 30


def assert_cat_capacity_pool(data: dict) -> None:
    assert_common_fields(data, "CatCapacityPool")
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) >= 1
    assert data["peril"] in ("HAIL", "WIND", "WILDFIRE")
    assert 0 < float(data["participation_pct"]) <= 1
    assert isinstance(data["total_capacity_cents"], int) and data["total_capacity_cents"] > 0
    assert data["status"] in ("OPEN", "FROZEN")
    for field in ("reserved_cents", "committed_cents", "available_cents"):
        assert isinstance(data[field], int), f"CatCapacityPool.{field} must be integer cents"
    assert_pool_capacity_identity(data)


def assert_pool_capacity_identity(data: dict) -> None:
    """`available_cents` is `total_capacity_cents` less `reserved_cents` less
    `committed_cents`."""
    expected = data["total_capacity_cents"] - data["reserved_cents"] - data["committed_cents"]
    assert data["available_cents"] == expected, (
        f"available_cents must be total {data['total_capacity_cents']} - reserved "
        f"{data['reserved_cents']} - committed {data['committed_cents']} = {expected}, "
        f"got {data['available_cents']}"
    )


# ---------------------------------------------------------------------------
# Account and policy
# ---------------------------------------------------------------------------


def assert_farm_account(data: dict) -> None:
    assert_common_fields(data, "FarmAccount")
    assert is_valid_uuid(data.get("agent_id", "")), "FarmAccount.agent_id must be a UUID"
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["county_name"], str) and 1 <= len(data["county_name"]) <= 60
    assert isinstance(data["cat_zone_code"], str) and 1 <= len(data["cat_zone_code"]) <= 24
    assert isinstance(data["acreage"], int) and data["acreage"] >= 1
    assert data["operation_type"] in ("CROP", "LIVESTOCK", "DAIRY", "RANCH", "MIXED")


def assert_farm_policy(data: dict) -> None:
    assert_common_fields(data, "FarmPolicy")
    assert is_valid_uuid(data.get("account_id", "")), "FarmPolicy.account_id must be a UUID"
    assert data["uw_status"] in ("DRAFT", "RATED", "REFERRED", "BOUND", "DECLINED", "CANCELLED")
    assert data["compliance_status"] in (
        "NOT_INSPECTED",
        "RECS_OPEN",
        "RECS_OVERDUE",
        "SUSPENDED",
        "COMPLIANT",
    )
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    for field in MONEY_FIELDS_ON_POLICY + ("exposed_tiv_cents",):
        assert isinstance(data[field], int), f"FarmPolicy.{field} must be integer cents"
    assert data["base_premium_cents"] == (
        data["property_premium_cents"]
        + data["livestock_premium_cents"]
        + data["liability_premium_cents"]
        + data["endorsement_premium_cents"]
    ), "base_premium_cents must be the sum of the four component premiums"
    assert data["total_premium_cents"] == data["base_premium_cents"] + data["cat_load_cents"], (
        "total_premium_cents must be base_premium_cents plus cat_load_cents"
    )


def assert_new_draft_policy(data: dict) -> None:
    """A newly opened policy is DRAFT / NOT_INSPECTED at version 1 with every
    premium field and exposed_tiv_cents at 0 and eight null fields."""
    assert_farm_policy(data)
    assert data["uw_status"] == "DRAFT"
    assert data["compliance_status"] == "NOT_INSPECTED"
    assert data["version"] == 1, f"a newly opened policy has version 1, got {data['version']}"
    for field in MONEY_FIELDS_ON_POLICY + ("exposed_tiv_cents",):
        assert data[field] == 0, f"a newly opened policy has {field} at 0, got {data[field]}"
    assert_all_null(
        data,
        (
            "rating_valuation_date",
            "quote_expires_at",
            "referred_at",
            "referred_by_user_id",
            "referral_reason_code",
            "bound_at",
            "bound_by_user_id",
            "closure_reason",
        ),
        "FarmPolicy",
    )


def assert_policy_money_zeroed(data: dict) -> None:
    """Every premium field and `exposed_tiv_cents` zeroed, `quote_expires_at` null."""
    for field in MONEY_FIELDS_ON_POLICY + ("exposed_tiv_cents",):
        assert data[field] == 0, f"expected {field} zeroed, got {data[field]}"
    assert data["quote_expires_at"] is None, "quote_expires_at must be null after an unwind"


# ---------------------------------------------------------------------------
# Exposures
# ---------------------------------------------------------------------------


def assert_scheduled_item(data: dict) -> None:
    assert_common_fields(data, "ScheduledItem")
    assert data["item_class"] in (
        "DWELLING",
        "FARM_STRUCTURE",
        "EQUIPMENT",
        "STORED_CROP",
        "HAY",
        "INPUTS",
    )
    assert isinstance(data["description"], str) and 1 <= len(data["description"]) <= 160
    assert data["valuation_basis"] in ("RC", "ACV")
    assert isinstance(data["stated_value_cents"], int) and data["stated_value_cents"] > 0
    assert isinstance(data["age_years"], int) and 0 <= data["age_years"] <= 100
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert isinstance(data["insured_value_cents"], int)


def assert_livestock_group(data: dict) -> None:
    assert_common_fields(data, "LivestockGroup")
    assert data["species"] in ("CATTLE", "SWINE", "POULTRY", "SHEEP", "EQUINE")
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert isinstance(data["per_head_value_cents"], int) and data["per_head_value_cents"] > 0
    assert data["limit_basis"] in ("PER_HEAD", "BLANKET")
    assert data["peril_scope"] in ("FULL_PERIL", "NAMED_PERIL", "CATASTROPHE_ONLY")
    assert isinstance(data["covered_limit_cents"], int)


def assert_liability_exposure(data: dict) -> None:
    assert_common_fields(data, "LiabilityExposure")
    assert data["exposure_type"] in (
        "GENERAL_FARM",
        "CUSTOM_FARMING",
        "AGRITOURISM",
        "ROADSIDE_STAND",
    )
    assert isinstance(data["annual_receipts_cents"], int) and data["annual_receipts_cents"] >= 0
    assert isinstance(data["exposure_premium_cents"], int)


def assert_labor_profile(data: dict) -> None:
    assert_common_fields(data, "LaborProfile")
    for field in ("full_time_count", "seasonal_count", "migrant_h2a_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_labor_units_two_decimals(data["labor_exposure_units"])
    assert isinstance(data["wc_required"], bool)
    assert data["coordination_status"] in ("NOT_REQUIRED", "PENDING_PROOF", "VERIFIED", "LAPSED")


def assert_labor_units_two_decimals(value) -> None:
    """The labor exposure measure carries exactly two decimal places."""
    assert isinstance(value, (int, float, str)), (
        f"labor_exposure_units must be a number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"labor_exposure_units must carry at most two decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Endorsements
# ---------------------------------------------------------------------------


def assert_endorsement(data: dict) -> None:
    assert_common_fields(data, "Endorsement")
    assert is_valid_uuid(data.get("policy_id", ""))
    assert data["form_code"] in (
        "POLLUTION_BUYBACK",
        "CHEMICAL_APPLICATION_BUYBACK",
        "AGRITOURISM_LIABILITY",
        "PEAK_SEASON_INCREASE",
    )
    assert isinstance(data["sublimit_cents"], int) and data["sublimit_cents"] > 0
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "SUSPENDED", "RESCINDED")
    assert isinstance(data["premium_cents"], int)
    assert isinstance(data["requires_inspection"], bool)


# ---------------------------------------------------------------------------
# Catastrophe reservations
# ---------------------------------------------------------------------------


def assert_cat_reservation(data: dict) -> None:
    assert_common_fields(data, "CatReservation")
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_valid_uuid(data.get("pool_id", ""))
    assert data["peril"] in ("HAIL", "WIND", "WILDFIRE")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["load_cents"], int)
    assert_utilization_six_decimals(data["utilization_at_rating"])
    assert float(data["scarcity_factor"]) in (1.00, 1.15, 1.35, 1.60)
    assert data["status"] in ("RESERVED", "COMMITTED", "RELEASED")


def assert_utilization_six_decimals(value) -> None:
    """The utilization ratio recorded on a catastrophe reservation is stored to
    six decimal places."""
    assert isinstance(value, (int, float, str)), f"utilization must be a number, got {value!r}"
    assert round(float(value), 6) == float(value), (
        f"utilization_at_rating must be stored to six decimal places, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Inspections and recommendations
# ---------------------------------------------------------------------------


def assert_inspection(data: dict) -> None:
    assert_common_fields(data, "Inspection")
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_valid_uuid(data.get("inspector_id", ""))
    assert data["inspection_type"] in ("INITIAL", "RE_INSPECTION", "LOSS_TRIGGERED")
    assert isinstance(data["scheduled_for"], str)
    assert isinstance(data["duration_minutes"], int)
    assert 30 <= data["duration_minutes"] <= 480
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert isinstance(data["hazard_score"], int)
    assert 0 <= data["hazard_score"] <= 100
    assert isinstance(data["recommendation_count"], int)


def assert_recommendation(data: dict) -> None:
    assert_common_fields(data, "Recommendation")
    assert is_valid_uuid(data.get("inspection_id", ""))
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert isinstance(data["description"], str) and 1 <= len(data["description"]) <= 240
    assert isinstance(data["due_date"], str)
    assert data["status"] in ("OPEN", "SUBMITTED", "VERIFIED", "WAIVED", "OVERDUE")


# ---------------------------------------------------------------------------
# Premium ledger
# ---------------------------------------------------------------------------


def assert_premium_transaction(data: dict) -> None:
    """A ledger entry is immutable, so it carries only `id` and `created_at` —
    both `updated_at` and `version` are absent from its representation."""
    assert is_valid_uuid(data.get("id", "")), "PremiumTransaction.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "a premium-transaction representation omits updated_at"
    assert "version" not in data, "a premium-transaction representation omits version"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert data["txn_type"] in (
        "BASE_PROPERTY",
        "BASE_LIVESTOCK",
        "BASE_LIABILITY",
        "CAT_LOAD",
        "ENDORSEMENT_ADD",
        "ENDORSEMENT_REMOVE",
        "REVERSAL",
    )
    assert data["reason_code"] in (
        "RATING",
        "RATING_REVERT",
        "ENDORSEMENT_APPROVAL",
        "ENDORSEMENT_RESCISSION",
        "COMPLIANCE_SUSPENSION",
        "COMPLIANCE_REINSTATEMENT",
        "POLICY_DECLINE",
        "POLICY_CANCELLATION",
    )
    assert isinstance(data["amount_cents"], int)
    if data["txn_type"] != "REVERSAL":
        assert data.get("reverses_sequence_no") is None, (
            "on entries that are not reversals, reverses_sequence_no is null"
        )


def assert_ledger_sums_to_total(entries: List[dict], total_premium_cents: int) -> None:
    """The sum of `amount_cents` across a policy's ledger entries equals its
    `total_premium_cents`."""
    ledger_sum = sum(entry["amount_cents"] for entry in entries)
    assert ledger_sum == total_premium_cents, (
        f"ledger sums to {ledger_sum} but total_premium_cents is {total_premium_cents}"
    )


def assert_ledger_sequence(entries: List[dict], expected_sequence: Optional[List[int]] = None) -> None:
    """`sequence_no` is assigned 1, 2, 3 and upward per policy and is the only
    ordering key for the ledger."""
    actual = [entry["sequence_no"] for entry in entries]
    assert actual == sorted(actual), f"ledger must be returned in sequence_no order, got {actual}"
    if expected_sequence is None:
        expected_sequence = list(range(1, len(entries) + 1))
    assert actual == expected_sequence, (
        f"expected sequence_no {expected_sequence}, got {actual}"
    )


def ledger_by_sequence(entries: List[dict]) -> Dict[int, dict]:
    return {entry["sequence_no"]: entry for entry in entries}


def assert_sweep_counters(data: dict, **expected) -> None:
    """The checkpoint reports five counters."""
    for name in (
        "policies_scanned",
        "recommendations_marked_overdue",
        "policies_marked_recs_overdue",
        "policies_suspended",
        "labor_profiles_lapsed",
    ):
        assert name in data, f"the compliance checkpoint must report {name}"
        assert isinstance(data[name], int), f"{name} must be an integer counter"
    for name, value in expected.items():
        assert data[name] == value, f"expected {name} == {value}, got {data[name]}"


__all__ = [
    "MONEY_FIELDS_ON_POLICY",
    "assert_common_fields",
    "assert_three_fraction_digits",
    "assert_all_null",
    "assert_agent",
    "assert_inspector",
    "assert_cat_capacity_pool",
    "assert_pool_capacity_identity",
    "assert_farm_account",
    "assert_farm_policy",
    "assert_new_draft_policy",
    "assert_policy_money_zeroed",
    "assert_scheduled_item",
    "assert_livestock_group",
    "assert_liability_exposure",
    "assert_labor_profile",
    "assert_labor_units_two_decimals",
    "assert_endorsement",
    "assert_cat_reservation",
    "assert_utilization_six_decimals",
    "assert_inspection",
    "assert_recommendation",
    "assert_premium_transaction",
    "assert_ledger_sums_to_total",
    "assert_ledger_sequence",
    "ledger_by_sequence",
    "assert_sweep_counters",
]
