"""Entity assertions and domain invariant checkers.

Scores and percentages are decimals carrying exactly two fractional digits;
`as_decimal` accepts either a JSON number or a decimal string so that a
faithful serialisation choice is never mistaken for a compliance failure.
Monetary amounts are integer counts of cents and are compared exactly.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AllocationPosture,
    AssetStatus,
    AuditStatus,
    ConstructionStatus,
    ContingencyStatus,
    CycleStatus,
    DispositionStatus,
    EquipmentStatus,
    GpoTier,
    MemberSeat,
    Modality,
    ProjectRecordStatus,
    QuoteStatus,
    Region,
    RequestStatus,
    ScoreReason,
    ServiceEventCategory,
    VoteChoice,
)

TOLERANCE = 0.005


def as_decimal(value) -> float:
    """Coerce a two-decimal score or percentage field to a float."""
    assert value is not None, "expected a decimal value, got null"
    if isinstance(value, bool):
        raise AssertionError(f"expected a decimal value, got boolean {value!r}")
    if isinstance(value, str):
        return float(value)
    assert isinstance(value, (int, float)), f"expected a decimal value, got {value!r}"
    return float(value)


def assert_decimal(actual, expected: float, label: str = "value") -> None:
    """Assert a two-decimal score/percentage field equals the expected decimal."""
    got = as_decimal(actual)
    assert abs(got - expected) < TOLERANCE, f"{label}: expected {expected:.2f}, got {got}"


def assert_cents(actual, expected: int, label: str = "amount") -> None:
    """Assert an integer-cents monetary field equals the expected count of cents."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label}: monetary fields are integer counts of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


def as_instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting either a `Z` or an explicit offset."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def assert_instant(actual, expected: str, label: str = "timestamp") -> None:
    """Assert a timestamp field names the expected instant, whatever the offset spelling."""
    assert as_instant(actual) == as_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_versioned_entity(data: dict, label: str = "entity") -> None:
    """Identity, timestamps and version of a mutable resource."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def assert_append_only_record(data: dict, label: str = "record") -> None:
    """An append-only record carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{label} is append-only: updated_at must be absent"
    assert "version" not in data, f"{label} is append-only: version must be absent"


def assert_error_envelope_shape(body: dict) -> None:
    """The error envelope carries meta plus a data object of error_id and message."""
    assert body.get("response_type") == "error", (
        f"error responses carry response_type 'error', got {body.get('response_type')!r}"
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), "error envelope must carry a meta object"
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        "meta.api_request_id must be a server-generated string starting with 'req_'"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp must be an ISO 8601 UTC timestamp"
    )
    data = body.get("data")
    assert isinstance(data, dict), "error envelope must carry a data object"
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data holds exactly error_id and message, got {sorted(data.keys())}"
    )
    assert isinstance(data["error_id"], str) and data["error_id"], "error_id must be a string"
    assert isinstance(data["message"], str) and data["message"].strip(), (
        "message must be a non-empty human-readable explanation"
    )


# ─── Per-entity assertions ────────────────────────────────────────────


def assert_facility(data: dict) -> None:
    assert_versioned_entity(data, "facility")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 8
    assert data["region"] in [r.value for r in Region]
    assert isinstance(data["max_concurrent_construction"], int)
    assert 1 <= data["max_concurrent_construction"] <= 5
    assert isinstance(data["active_asset_count"], int) and data["active_asset_count"] >= 0


def assert_department(data: dict) -> None:
    assert_versioned_entity(data, "department")
    assert is_valid_uuid(data.get("facility_id", "")), "department.facility_id must be a UUID"
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["modality_scope"] in [m.value for m in Modality]
    assert isinstance(data["utilization_penalty_points"], int)
    assert 0 <= data["utilization_penalty_points"] <= 20
    assert isinstance(data["underperformance_flag"], bool)


def assert_asset(data: dict) -> None:
    assert_versioned_entity(data, "asset")
    assert is_valid_uuid(data.get("facility_id", "")), "asset.facility_id must be a UUID"
    assert is_valid_uuid(data.get("department_id", "")), "asset.department_id must be a UUID"
    assert data["modality"] in [m.value for m in Modality]
    assert data["status"] in [s.value for s in AssetStatus]
    assert data["disposition_status"] in [d.value for d in DispositionStatus]
    assert isinstance(data["expected_life_years"], int)
    assert 1 <= data["expected_life_years"] <= 30
    assert isinstance(data["acquisition_cost_cents"], int) and data["acquisition_cost_cents"] > 0
    assert 0.00 <= as_decimal(data["nominal_ruls_score"]) <= 100.00
    assert 0.00 <= as_decimal(data["adjusted_ruls_score"]) <= 100.00
    assert 0.00 <= as_decimal(data["service_penalty_points"]) <= 40.00
    assert isinstance(data["corrective_count_24m"], int) and data["corrective_count_24m"] >= 0
    assert isinstance(data["unresolved_recall"], bool)
    assert isinstance(data["trade_in_credit_applied_cents"], int)
    assert is_iso8601_timestamp(data.get("ruls_as_of", "")), "asset.ruls_as_of must be ISO 8601"


def assert_service_event(data: dict) -> None:
    assert_append_only_record(data, "service event")
    assert data["category"] in [c.value for c in ServiceEventCategory]
    assert 0.00 <= as_decimal(data["downtime_hours"]) <= 8760.00
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert isinstance(data["recall_resolved"], bool)


def assert_cycle(data: dict) -> None:
    assert_versioned_entity(data, "cycle")
    assert isinstance(data["plan_year"], int) and 2026 <= data["plan_year"] <= 2035
    assert data["status"] in [s.value for s in CycleStatus]
    assert isinstance(data["total_capital_cents"], int) and data["total_capital_cents"] > 0
    for field in (
        "system_contingency_cents",
        "distributable_cents",
        "unallocated_cents",
        "contingency_drawn_cents",
    ):
        assert isinstance(data[field], int), f"cycle.{field} must be integer cents"
    for field in (
        "allocation_count",
        "exhausted_allocation_count",
        "scored_count",
        "expedited_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"cycle.{field} must be a count"


def assert_allocation(data: dict) -> None:
    assert_versioned_entity(data, "allocation")
    assert is_valid_uuid(data.get("cycle_id", "")), "allocation.cycle_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "allocation.facility_id must be a UUID"
    assert data["posture"] in [p.value for p in AllocationPosture]
    assert data["contingency_status"] in [c.value for c in ContingencyStatus]
    for field in (
        "demand_cents",
        "allocated_cents",
        "contingency_reserve_cents",
        "released_contingency_cents",
        "committed_cents",
        "available_cents",
    ):
        assert isinstance(data[field], int), f"allocation.{field} must be integer cents"
    assert_conserved_capital_identity(data)


def assert_conserved_capital_identity(allocation: dict) -> None:
    """`allocated_cents` + `released_contingency_cents` == `committed_cents` + `available_cents`."""
    left = allocation["allocated_cents"] + allocation["released_contingency_cents"]
    right = allocation["committed_cents"] + allocation["available_cents"]
    assert left == right, (
        "conserved capital identity broken: "
        f"allocated {allocation['allocated_cents']} + released "
        f"{allocation['released_contingency_cents']} != committed "
        f"{allocation['committed_cents']} + available {allocation['available_cents']}"
    )
    assert allocation["available_cents"] >= 0, "available_cents may never fall below zero"


def assert_request(data: dict) -> None:
    assert_versioned_entity(data, "request")
    assert is_valid_uuid(data.get("cycle_id", "")), "request.cycle_id must be a UUID"
    assert is_valid_uuid(data.get("department_id", "")), "request.department_id must be a UUID"
    assert is_valid_uuid(data.get("asset_id", "")), "request.asset_id must be a UUID"
    assert data["status"] in [s.value for s in RequestStatus]
    for field in ("safety_driver", "growth_driver", "regulatory_driver", "eos_driver"):
        assert 0.00 <= as_decimal(data[field]) <= 100.00, f"request.{field} out of range"
    assert 0.00 <= as_decimal(data["composite_score"]) <= 100.00
    assert isinstance(data["expedited"], bool)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0
    assert isinstance(data["funded_amount_cents"], int)


def assert_priority_score(data: dict) -> None:
    assert_append_only_record(data, "score row")
    assert is_valid_uuid(data.get("request_id", "")), "score row.request_id must be a UUID"
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert data["reason"] in [r.value for r in ScoreReason]
    assert isinstance(data["department_penalty_points"], int)
    assert isinstance(data["expedited"], bool)
    assert 0.00 <= as_decimal(data["composite_score"]) <= 100.00


def assert_committee_member(data: dict) -> None:
    assert_versioned_entity(data, "committee member")
    assert data["seat"] in [s.value for s in MemberSeat]
    assert isinstance(data["voting_weight"], int) and 1 <= data["voting_weight"] <= 5
    assert isinstance(data["active"], bool)


def assert_committee_vote(data: dict) -> None:
    assert_append_only_record(data, "ballot")
    assert is_valid_uuid(data.get("request_id", "")), "ballot.request_id must be a UUID"
    assert data["vote"] in [v.value for v in VoteChoice]
    assert isinstance(data["counted_weight"], int) and 1 <= data["counted_weight"] <= 5
    assert isinstance(data["superseded"], bool)


def assert_gpo_contract(data: dict) -> None:
    assert_versioned_entity(data, "contract")
    assert isinstance(data["contract_code"], str) and 2 <= len(data["contract_code"]) <= 24
    assert isinstance(data["tier_mid_floor_cents"], int) and data["tier_mid_floor_cents"] > 0
    assert data["tier_large_floor_cents"] > data["tier_mid_floor_cents"]


def assert_vendor_quote(data: dict) -> None:
    assert_versioned_entity(data, "quote")
    assert is_valid_uuid(data.get("request_id", "")), "quote.request_id must be a UUID"
    assert data["status"] in [s.value for s in QuoteStatus]
    assert data["gpo_tier"] in [t.value for t in GpoTier]
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1
    for field in (
        "list_price_cents",
        "gpo_discount_cents",
        "multi_unit_addendum_cents",
        "subtotal_cents",
        "trade_in_credit_cents",
        "net_capital_cents",
    ):
        assert isinstance(data[field], int), f"quote.{field} must be integer cents"
    assert data["subtotal_cents"] == (
        data["list_price_cents"] - data["gpo_discount_cents"] - data["multi_unit_addendum_cents"]
    ), "subtotal is the list price less the discount less the addendum"
    assert data["net_capital_cents"] == data["subtotal_cents"] - data["trade_in_credit_cents"], (
        "net capital is the subtotal less the trade-in credit"
    )


def assert_installation_project(data: dict) -> None:
    assert_versioned_entity(data, "project")
    assert is_valid_uuid(data.get("request_id", "")), "project.request_id must be a UUID"
    assert is_valid_uuid(data.get("facility_id", "")), "project.facility_id must be a UUID"
    assert is_valid_uuid(data.get("department_id", "")), "project.department_id must be a UUID"
    assert data["record_status"] in [s.value for s in ProjectRecordStatus]
    assert data["construction_status"] in [s.value for s in ConstructionStatus]
    assert data["equipment_status"] in [s.value for s in EquipmentStatus]
    assert isinstance(data["construction_required"], bool)


def assert_utilization_audit(data: dict) -> None:
    assert_versioned_entity(data, "audit")
    assert is_valid_uuid(data.get("request_id", "")), "audit.request_id must be a UUID"
    assert is_valid_uuid(data.get("installation_project_id", "")), (
        "audit.installation_project_id must be a UUID"
    )
    assert data["status"] in [s.value for s in AuditStatus]
    assert isinstance(data["projected_annual_volume_snapshot"], int)
    assert isinstance(data["baseline_year1_opex_snapshot"], int)
