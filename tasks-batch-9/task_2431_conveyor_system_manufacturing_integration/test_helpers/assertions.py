"""Entity assertions and domain invariant checkers for the PRD's resource types."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CertificateStatus,
    ChangeOrderStatus,
    CommercialStatus,
    CutoverWindowStatus,
    DeliveryStatus,
    DisputeStatus,
    EquipmentClass,
    FabricationLotStatus,
    FatResult,
    RampVerdict,
    ServiceTier,
    SimulationMethod,
    SimulationRunStatus,
    SpareCriticality,
    SparePartLineStatus,
    ZoneOpsStatus,
)

_VALUES = lambda enum_cls: [member.value for member in enum_cls]  # noqa: E731


# ---------------------------------------------------------------------------
# Common field discipline (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict) -> None:
    """id is a UUID with no type prefix; created_at/updated_at ISO 8601; version >= 1."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """Append-only records carry only id and created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_project(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert isinstance(data["customer_rep_user_id"], str) and data["customer_rep_user_id"]
    assert data["required_throughput_cph"] >= 1
    assert data["contract_base_cents"] >= 1
    assert data["authorized_ceiling_cents"] >= data["contract_base_cents"]
    assert isinstance(data["escalation_fee_cents"], int)
    assert isinstance(data["contract_value_cents"], int)
    assert data["spares_budget_cents"] >= 0
    assert data["service_tier"] in _VALUES(ServiceTier)
    assert data["response_sla_minutes"] in (480, 240, 60)
    assert data["design_version"] >= 1
    assert data["delivery_status"] in _VALUES(DeliveryStatus)
    assert data["commercial_status"] in _VALUES(CommercialStatus)
    assert isinstance(data["acceptance_ready"], bool)
    assert_share_ledger_conserved(data)
    assert_spares_ledger_conserved(data)


def assert_segment(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["segment_code"], str) and data["segment_code"]
    assert data["equipment_class"] in _VALUES(EquipmentClass)
    assert data["rated_capacity_cph"] >= 1
    assert 1 <= data["availability_pct"] <= 100
    if data.get("source_share_bps") is not None:
        assert 1 <= data["source_share_bps"] <= 10000
    assert data["inbound_link_count"] >= 0
    assert data["outbound_link_count"] >= 0
    assert data["flow_share_bps"] >= 0
    assert data["derated_capacity_cph"] >= 0


def assert_flow_link(data: dict) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["from_segment_id"], str)
    assert isinstance(data["to_segment_id"], str)
    assert 1 <= data["split_share_bps"] <= 10000


def assert_simulation_run(data: dict) -> None:
    assert_common_fields(data)
    assert data["method"] in _VALUES(SimulationMethod)
    assert data["status"] in _VALUES(SimulationRunStatus)
    assert data["design_version_at_run"] >= 1
    assert data["effective_throughput_cph"] >= 0
    assert isinstance(data["bottleneck_segment_code"], str)
    assert data["shortfall_cph"] >= 0


def assert_staging_bay(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["bay_code"], str) and data["bay_code"]
    assert data["concurrent_capacity"] >= 1


def assert_fabrication_lot(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["segment_codes"], list) and data["segment_codes"]
    assert data["occupancy_end_utc"] > data["occupancy_start_utc"]
    assert data["fat_target_cph"] >= 1
    assert data["fat_attempt_count"] >= 0
    assert data["status"] in _VALUES(FabricationLotStatus)


def assert_fat_test(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["attempt_no"] >= 1
    assert data["measured_cph"] >= 0
    assert data["defect_count"] >= 0
    assert data["target_cph_at_test"] >= 1
    assert data["result"] in _VALUES(FatResult)


def assert_site_zone(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert 1 <= data["throughput_share_bps"] <= 10000
    assert 0 <= data["protected_shift_start_minute"] <= 1439
    assert 1 <= data["protected_shift_end_minute"] <= 1440
    assert data["protected_shift_end_minute"] > data["protected_shift_start_minute"]
    assert data["buffer_minutes"] >= 0
    assert data["ops_status"] in _VALUES(ZoneOpsStatus)


def assert_cutover_window(data: dict) -> None:
    assert_common_fields(data)
    assert data["end_utc"] > data["start_utc"]
    assert data["status"] in _VALUES(CutoverWindowStatus)


def assert_commissioning_ramp(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["step_pct"] in (50, 75, 100)
    assert data["measured_cph"] >= 0
    assert data["sustained_minutes"] >= 0
    assert data["target_cph"] >= 1
    assert data["min_sustained_minutes"] in (30, 60, 120)
    assert data["verdict"] in _VALUES(RampVerdict)
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_acceptance_certificate(data: dict) -> None:
    assert_common_fields(data)
    assert data["accepted_throughput_cph"] >= 0
    assert data["bottleneck_availability_pct"] >= 1
    assert data["retention_amount_cents"] >= 0
    assert data["retention_release_cents"] >= 0
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data["dispute_deadline_utc"])
    assert data["status"] in _VALUES(CertificateStatus)


def assert_change_order(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["scope_delta_cph"], int)
    assert isinstance(data["price_delta_cents"], int)
    assert isinstance(data["schedule_delta_days"], int)
    assert 1 <= data["round_no"] <= 3
    assert data["status"] in _VALUES(ChangeOrderStatus)


def assert_spare_part_line(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["part_no"], str) and data["part_no"]
    assert data["criticality"] in _VALUES(SpareCriticality)
    assert data["unit_cost_cents"] >= 1
    assert data["min_stock_qty"] >= 1
    assert data["lead_time_days"] >= 0
    assert data["requested_cents"] == data["unit_cost_cents"] * data["min_stock_qty"], (
        "requested_cents must equal unit_cost_cents * min_stock_qty"
    )
    assert data["weighted_target_cents"] >= 0
    assert data["allocated_cents"] >= 0
    assert data["status"] in _VALUES(SparePartLineStatus)


def assert_performance_dispute(data: dict) -> None:
    assert_common_fields(data)
    assert data["claimed_cph"] >= 0
    assert data["damages_basis"] in ("NAMEPLATE", "OBSERVED_AVAILABILITY")
    assert data["provisional_nameplate_cents"] >= 0
    assert data["provisional_observed_cents"] >= 0
    assert data["bound_provisional_cents"] in (
        data["provisional_nameplate_cents"],
        data["provisional_observed_cents"],
    ), "bound_provisional_cents must be one of the two provisional figures"
    assert data["status"] in _VALUES(DisputeStatus)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_share_ledger_conserved(project: dict) -> None:
    """legacy + in_transition + cutover share always sums to exactly 10000 (PRD §2.9)."""
    total = (
        project["legacy_share_bps"]
        + project["in_transition_share_bps"]
        + project["cutover_share_bps"]
    )
    assert total == 10000, (
        "facility share ledger must sum to exactly 10000, got "
        f"{project['legacy_share_bps']} + {project['in_transition_share_bps']} + "
        f"{project['cutover_share_bps']} = {total}"
    )


def assert_spares_ledger_conserved(project: dict) -> None:
    """spares_budget_cents == spares_allocated_cents + spares_unallocated_cents (PRD §3.9)."""
    assert (
        project["spares_allocated_cents"] + project["spares_unallocated_cents"]
        == project["spares_budget_cents"]
    ), (
        "spares budget must equal allocated plus unallocated, got "
        f"{project['spares_allocated_cents']} + {project['spares_unallocated_cents']} "
        f"!= {project['spares_budget_cents']}"
    )


def assert_whole_cents(*amounts) -> None:
    """All money in this system is expressed in whole integer cents (PRD §2.8)."""
    for amount in amounts:
        assert isinstance(amount, int) and not isinstance(amount, bool), (
            f"monetary amounts must be whole integer cents, got {amount!r}"
        )


def assert_no_pagination_meta(meta: dict) -> None:
    """Single-resource responses omit the four pagination fields (PRD §2.3)."""
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field not in meta, f"single-resource meta must omit {field}"


def assert_request_envelope_meta(meta: dict) -> None:
    """meta.api_request_id starts with req_ and the timestamp is ISO 8601 (PRD §2.2)."""
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith(
        "req_"
    ), f"api_request_id must start with 'req_', got {meta.get('api_request_id')!r}"
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"
    )
