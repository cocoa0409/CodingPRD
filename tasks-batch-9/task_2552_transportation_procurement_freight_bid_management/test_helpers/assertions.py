"""Domain assertion helpers.

Shape checks for each resource type plus the conservation invariants the PRD
declares over lane volume, contract value and tender metrics.
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_present(entity: Dict[str, Any], fields: Iterable[str], label: str) -> None:
    for field in fields:
        assert field in entity, f"{label} is missing field {field!r}: {entity}"


def assert_decimal_places(value: float, places: int, label: str) -> None:
    """A numeric field carries no more precision than the PRD allows for it."""
    assert value is not None, f"{label} is null"
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 10 ** -(places + 4), (
        f"{label} carries more than {places} decimal places: {value}"
    )


def assert_common_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """The four system-managed fields carried by thirteen resource types."""
    _assert_present(entity, ("id", "created_at", "updated_at", "version"), label)
    assert is_valid_uuid(entity["id"]), f"{label} id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"{label} created_at is not an ISO 8601 UTC timestamp: {entity['created_at']}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"{label} updated_at is not an ISO 8601 UTC timestamp: {entity['updated_at']}"
    )
    assert isinstance(entity["version"], int), f"{label} version is not an integer"
    assert entity["version"] >= 1, f"{label} version must start at 1: {entity['version']}"


def assert_carrier(carrier: Dict[str, Any]) -> None:
    assert_common_fields(carrier, "carrier")
    _assert_present(
        carrier,
        (
            "legal_name",
            "scac_code",
            "status",
            "diversity_classification",
            "service_modes",
            "fleet_power_units",
            "auto_liability_limit_usd",
            "cargo_limit_usd",
            "insurance_expiry_date",
            "capability_score",
            "composite_score",
            "composite_score_variant",
            "published_scorecard_count",
            "active_primary_lane_count",
            "committed_volume_loads",
        ),
        "carrier",
    )
    assert len(carrier["scac_code"]) == 4, "scac_code is exactly four letters"
    assert_decimal_places(carrier["capability_score"], 2, "capability_score")
    assert_decimal_places(carrier["composite_score"], 2, "composite_score")


def assert_qualification_review(review: Dict[str, Any]) -> None:
    assert_common_fields(review, "qualification review")
    _assert_present(
        review,
        (
            "carrier_id",
            "status",
            "required_modes",
            "min_auto_liability_usd",
            "min_cargo_usd",
            "insurance_result",
            "capability_result",
            "remediation_count",
        ),
        "qualification review",
    )


def assert_scorecard(scorecard: Dict[str, Any]) -> None:
    assert_common_fields(scorecard, "scorecard")
    _assert_present(
        scorecard,
        (
            "carrier_id",
            "period_start",
            "period_end",
            "on_time_pct",
            "claims_ratio",
            "tender_acceptance_pct",
            "period_tender_count",
            "composite_score",
            "status",
        ),
        "scorecard",
    )
    assert_decimal_places(scorecard["claims_ratio"], 4, "claims_ratio")
    assert_decimal_places(scorecard["composite_score"], 2, "scorecard composite_score")


def assert_bid_event(event: Dict[str, Any]) -> None:
    assert_common_fields(event, "bid event")
    _assert_present(
        event,
        (
            "name",
            "cost_basis",
            "fuel_index_per_mile",
            "accessorial_inflation_factor",
            "rate_floor_per_mile",
            "rounds_allowed",
            "cost_weight",
            "service_weight",
            "capacity_weight",
            "diversity_weight",
            "diversity_min_pct",
            "max_award_share_pct",
            "max_carriers_per_lane",
            "contract_effective_from",
            "contract_effective_to",
            "status",
            "lane_count",
            "total_scope_volume_loads",
            "coverage_pct",
            "diversity_pct",
        ),
        "bid event",
    )
    weight_sum = (
        round(event["cost_weight"], 2)
        + round(event["service_weight"], 2)
        + round(event["capacity_weight"], 2)
        + round(event["diversity_weight"], 2)
    )
    assert abs(weight_sum - 1.00) < 1e-9, f"event weights must sum to 1.00, got {weight_sum}"


def assert_lane(lane: Dict[str, Any]) -> None:
    assert_common_fields(lane, "lane")
    _assert_present(
        lane,
        (
            "bid_event_id",
            "lane_code",
            "origin_zip3",
            "dest_zip3",
            "equipment_type",
            "mileage",
            "annual_volume_loads",
            "seasonality_peak_index",
            "accessorial_history_usd_per_load",
            "service_days_required",
            "status",
            "data_quality_flags",
            "unallocated_volume_loads",
            "awarded_coverage_pct",
        ),
        "lane",
    )
    assert isinstance(lane["data_quality_flags"], list), "data_quality_flags is a list"


def assert_invitation(invitation: Dict[str, Any]) -> None:
    assert_common_fields(invitation, "invitation")
    _assert_present(
        invitation,
        (
            "bid_event_id",
            "carrier_id",
            "status",
            "nda_required",
            "nda_signed",
            "qualification_snapshot_score",
            "qualification_snapshot_carrier_version",
            "snapshot_stale",
        ),
        "invitation",
    )


def assert_bid_round(bid_round: Dict[str, Any]) -> None:
    assert_common_fields(bid_round, "bid round")
    _assert_present(
        bid_round,
        (
            "bid_event_id",
            "round_no",
            "status",
            "incumbent_visibility",
            "target_reduction_pct",
            "opens_at",
            "closes_at",
            "submitted_bid_count",
        ),
        "bid round",
    )


def assert_lane_bid(bid: Dict[str, Any]) -> None:
    assert_common_fields(bid, "lane bid")
    _assert_present(
        bid,
        (
            "bid_round_id",
            "lane_id",
            "carrier_id",
            "rate_per_mile",
            "fuel_surcharge_included",
            "committed_volume_loads",
            "transit_days_offered",
            "status",
            "is_incumbent",
            "evaluated_basis",
            "effective_rate_per_mile",
            "awardable_volume_loads",
            "linehaul_per_load_usd",
            "accessorial_per_load_usd",
            "cost_per_load_usd",
            "evaluated_total_cost_usd",
            "service_credit_pct",
            "cost_rank_score",
            "rank_in_lane",
        ),
        "lane bid",
    )
    assert_decimal_places(bid["linehaul_per_load_usd"], 2, "linehaul_per_load_usd")
    assert_decimal_places(bid["accessorial_per_load_usd"], 2, "accessorial_per_load_usd")
    assert_decimal_places(bid["cost_per_load_usd"], 2, "cost_per_load_usd")
    assert_decimal_places(bid["evaluated_total_cost_usd"], 2, "evaluated_total_cost_usd")
    assert_decimal_places(bid["service_credit_pct"], 4, "service_credit_pct")


def assert_optimization_run(run: Dict[str, Any]) -> None:
    assert_common_fields(run, "optimization run")
    _assert_present(
        run,
        (
            "bid_event_id",
            "scenario_label",
            "max_carriers_per_lane",
            "diversity_min_pct",
            "min_capacity_coverage_pct",
            "status",
            "total_cost_usd",
            "coverage_pct",
            "diversity_pct",
            "objective_score",
            "infeasible_lane_ids",
            "proposed_primary_count",
            "proposed_backup_count",
        ),
        "optimization run",
    )
    assert_decimal_places(run["objective_score"], 6, "objective_score")


def assert_award_allocation(allocation: Dict[str, Any]) -> None:
    assert_common_fields(allocation, "award allocation")
    _assert_present(
        allocation,
        (
            "bid_event_id",
            "optimization_run_id",
            "lane_id",
            "carrier_id",
            "lane_bid_id",
            "routing_position",
            "allocated_volume_loads",
            "allocated_pct",
            "allocated_cost_usd",
            "status",
        ),
        "award allocation",
    )
    assert_decimal_places(allocation["allocated_pct"], 2, "allocated_pct")
    assert_decimal_places(allocation["allocated_cost_usd"], 2, "allocated_cost_usd")


def assert_contract(contract: Dict[str, Any]) -> None:
    assert_common_fields(contract, "contract")
    _assert_present(
        contract,
        (
            "bid_event_id",
            "carrier_id",
            "status",
            "signature_status",
            "rate_load_status",
            "effective_from",
            "effective_to",
            "base_committed_value_usd",
            "volume_discount_pct",
            "volume_discount_usd",
            "accessorial_allowance_pct",
            "accessorial_allowance_usd",
            "total_committed_value_usd",
            "amendment_count",
            "rate_record_count",
        ),
        "contract",
    )
    assert_decimal_places(
        contract["base_committed_value_usd"], 2, "base_committed_value_usd"
    )
    assert_decimal_places(
        contract["total_committed_value_usd"], 2, "total_committed_value_usd"
    )


def assert_rate_record(record: Dict[str, Any]) -> None:
    assert_common_fields(record, "rate record")
    _assert_present(
        record,
        (
            "contract_id",
            "lane_id",
            "carrier_id",
            "award_allocation_id",
            "routing_position",
            "rate_per_mile",
            "fuel_surcharge_included",
            "effective_from",
            "effective_to",
            "committed_volume_loads",
            "committed_value_usd",
            "status",
            "tender_count",
            "rejection_count",
            "rejection_pct",
            "acceptance_pct",
        ),
        "rate record",
    )
    assert_decimal_places(record["committed_value_usd"], 2, "committed_value_usd")
    assert_decimal_places(record["rejection_pct"], 2, "rejection_pct")
    assert_decimal_places(record["acceptance_pct"], 2, "acceptance_pct")


def assert_mini_bid(mini_bid: Dict[str, Any]) -> None:
    assert_common_fields(mini_bid, "mini-bid")
    _assert_present(
        mini_bid,
        (
            "bid_event_id",
            "lane_id",
            "rate_record_id",
            "trigger_reason",
            "origin",
            "status",
            "window_open_at",
            "window_close_at",
        ),
        "mini-bid",
    )


def assert_tender_event(tender: Dict[str, Any]) -> None:
    """A tender outcome is an immutable append: only ``id`` and ``created_at``."""
    _assert_present(
        tender, ("id", "created_at", "rate_record_id", "outcome", "load_reference"), "tender event"
    )
    assert is_valid_uuid(tender["id"]), f"tender event id is not a bare UUID: {tender['id']}"
    assert is_iso8601_timestamp(tender["created_at"]), (
        f"tender event created_at is not ISO 8601: {tender['created_at']}"
    )
    assert "updated_at" not in tender, (
        f"a tender event has no updated_at field: {tender}"
    )
    assert "version" not in tender, f"a tender event has no version field: {tender}"


# ─── Conserved quantities (PRD §2.12) ─────────────────────────────────────────

VOLUME_HOLDING_ALLOCATION_STATUSES = (
    "APPROVED",
    "EXECUTED",
    "ACTIVE",
    "SUSPENDED_ROUTING",
)

RATE_BASIS_STATUSES = ("STAGED", "LOADED", "LIVE", "AT_RISK")


def assert_lane_volume_conservation(
    lane: Dict[str, Any], allocations: List[Dict[str, Any]]
) -> None:
    """`unallocated_volume_loads` plus volume-holding allocations equals the plan."""
    held = sum(
        allocation["allocated_volume_loads"]
        for allocation in allocations
        if allocation["lane_id"] == lane["id"]
        and allocation["status"] in VOLUME_HOLDING_ALLOCATION_STATUSES
    )
    total = lane["unallocated_volume_loads"] + held
    assert total == lane["annual_volume_loads"], (
        "lane volume is not conserved: unallocated "
        f"{lane['unallocated_volume_loads']} + held {held} = {total}, "
        f"expected annual_volume_loads {lane['annual_volume_loads']}"
    )


def assert_contract_value_derivation(
    contract: Dict[str, Any], rate_records: List[Dict[str, Any]]
) -> None:
    """`base_committed_value_usd` is the sum of the in-basis records' values."""
    in_basis = [
        record
        for record in rate_records
        if record["contract_id"] == contract["id"]
        and record["status"] in RATE_BASIS_STATUSES
    ]
    expected_base = round(sum(record["committed_value_usd"] for record in in_basis), 2)
    assert contract["base_committed_value_usd"] == expected_base, (
        f"base_committed_value_usd {contract['base_committed_value_usd']} does not equal "
        f"the sum of in-basis committed_value_usd {expected_base}"
    )
    assert contract["rate_record_count"] == len(in_basis), (
        f"rate_record_count {contract['rate_record_count']} does not count the "
        f"{len(in_basis)} in-basis rate records"
    )


def assert_contract_value_round_trip(
    contract: Dict[str, Any], mini_bid: Dict[str, Any]
) -> None:
    """After an apply then a revert, the committed value returns to the cent."""
    before = mini_bid["contract_value_before_usd"]
    assert before is not None, "the mini-bid never snapshotted contract_value_before_usd"
    assert contract["total_committed_value_usd"] == before, (
        f"total_committed_value_usd {contract['total_committed_value_usd']} does not equal "
        f"the snapshotted contract_value_before_usd {before} exactly"
    )


def assert_tender_metrics(
    record: Dict[str, Any],
    expected_tender_count: int,
    expected_rejection_count: int,
    expected_rejection_pct: float,
    expected_acceptance_pct: Optional[float] = None,
) -> None:
    """The tender rollups on a rate record read as the PRD derives them."""
    assert record["tender_count"] == expected_tender_count, (
        f"tender_count {record['tender_count']} != {expected_tender_count}"
    )
    assert record["rejection_count"] == expected_rejection_count, (
        f"rejection_count {record['rejection_count']} != {expected_rejection_count}"
    )
    assert record["rejection_pct"] == expected_rejection_pct, (
        f"rejection_pct {record['rejection_pct']} != {expected_rejection_pct}"
    )
    if expected_acceptance_pct is not None:
        assert record["acceptance_pct"] == expected_acceptance_pct, (
            f"acceptance_pct {record['acceptance_pct']} != {expected_acceptance_pct}"
        )


def to_instant(value: str) -> "datetime":
    """Parses an ISO 8601 UTC instant, tolerating a `Z` suffix and any precision."""
    assert isinstance(value, str) and value, f"not an instant: {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_same_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Two ISO 8601 instants denote the same moment.

    The PRD pins the meaning of every `_at` field to the logical clock, not the
    number of fractional digits used to serialise it, so `2026-09-01T00:00:00Z`
    and `2026-09-01T00:00:00.000Z` are the same instant and both are accepted.
    """
    assert actual is not None, f"{label} is null, expected {expected}"
    assert is_iso8601_timestamp(actual), (
        f"{label} is not an ISO 8601 UTC timestamp: {actual!r}"
    )
    assert to_instant(actual) == to_instant(expected), (
        f"{label} is {actual!r}, expected the instant {expected!r}"
    )
