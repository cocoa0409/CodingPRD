"""Entity assertions and domain invariant checkers for the PRD's contract."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS


# ─── Shared record shape ──────────────────────────────

def assert_audit_triple(data: dict) -> None:
    """Most resources carry a server-minted id plus the standard audit triple."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer revision counter, got {data.get('version')!r}"
    )


def assert_append_only_record(data: dict) -> None:
    """A ballot and a ledger entry each carry only id and created_at: neither has
    an updated_at field and neither has a version field."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry a version field"


# ─── AttractionProject ────────────────────────────────

def assert_attraction_project(data: dict) -> None:
    assert_audit_triple(data)
    assert isinstance(data["project_code"], str) and 1 <= len(data["project_code"]) <= 32
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["design_phase"] in [
        "BLUE_SKY", "CONCEPT", "SCHEMATIC", "DESIGN_DEVELOPMENT", "PRODUCTION",
        "INSTALLATION", "TECHNICAL_REHEARSAL", "SOFT_OPEN", "OPERATIONS_HANDOVER",
    ], f"unexpected design_phase {data['design_phase']!r}"
    assert data["readiness_posture"] in ["OPEN", "RESTRICTED", "FROZEN"], (
        f"unexpected readiness_posture {data['readiness_posture']!r}"
    )
    assert isinstance(data["design_day_attendance"], int) and data["design_day_attendance"] >= 1
    assert 0 < float(data["peak_hour_share"]) <= 1
    assert isinstance(data["budget_ceiling_cents"], int) and data["budget_ceiling_cents"] >= 1
    assert isinstance(data["required_hourly_capacity_guests"], int)
    assert isinstance(data["committed_cost_cents"], int)
    assert isinstance(data["forecast_cost_cents"], int)
    assert isinstance(data["open_critical_finding_count"], int)
    assert isinstance(data["open_major_finding_count"], int)
    assert isinstance(data["queue_capacity_total_guests"], int)
    assert isinstance(data["soft_open_validated"], bool)


def assert_newly_opened_project(data: dict) -> None:
    """A new programme is written with every derived field at its opening value."""
    assert data["design_phase"] == "BLUE_SKY"
    assert data["readiness_posture"] == "OPEN"
    assert data["selected_ride_system_id"] is None
    assert data["committed_cost_cents"] == 0
    assert data["forecast_cost_cents"] == 0
    assert data["open_critical_finding_count"] == 0
    assert data["open_major_finding_count"] == 0
    assert data["queue_capacity_total_guests"] == 0
    assert float(data["show_quality_score"]) == 0.00
    assert data["soft_open_validated"] is False
    assert data["handover_accepted_at"] is None
    assert data["ledger_sequence_high_water"] == 0


def assert_posture_matches_thresholds(project: dict) -> None:
    """Re-derive the readiness posture from the programme's own reported figures."""
    ceiling = project["budget_ceiling_cents"]
    committed = project["committed_cost_cents"]
    restricted = (ceiling * THRESHOLDS["RESTRICTED_UTILISATION_PCT"]) // 100
    if project["open_critical_finding_count"] > 0 or committed > ceiling:
        expected = "FROZEN"
    elif project["open_major_finding_count"] > 0 or committed > restricted:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert project["readiness_posture"] == expected, (
        f"posture {project['readiness_posture']} does not follow from committed={committed}, "
        f"ceiling={ceiling}, restricted_utilisation={restricted}, "
        f"critical={project['open_critical_finding_count']}, major={project['open_major_finding_count']}"
    )


# ─── RideSystem ───────────────────────────────────────

def assert_ride_system(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["CANDIDATE", "SELECTED", "ENGINEERED", "COMMISSIONED"]
    assert data["system_type"] in [
        "DARK_RIDE_TRACKLESS", "OMNIMOVER", "LAUNCH_COASTER",
        "BOAT_FLUME", "MOTION_BASE_THEATER",
    ]
    assert isinstance(data["vehicle_count"], int) and data["vehicle_count"] >= 1
    assert isinstance(data["riders_per_vehicle"], int) and data["riders_per_vehicle"] >= 1
    assert isinstance(data["block_zone_count"], int) and data["block_zone_count"] >= 2
    assert isinstance(data["cycle_time_seconds"], int) and data["cycle_time_seconds"] >= 1
    assert isinstance(data["dispatch_interval_seconds"], int)
    assert data["dispatch_interval_seconds"] >= THRESHOLDS["MIN_DISPATCH_INTERVAL_SECONDS"], (
        "dispatch_interval_seconds must never fall below the twenty-second minimum"
    )
    assert isinstance(data["theoretical_hourly_capacity_guests"], int)
    assert isinstance(data["operational_hourly_capacity_guests"], int)
    assert data["operational_hourly_capacity_guests"] <= data["theoretical_hourly_capacity_guests"]


def assert_ride_capacity_variants(data: dict, dispatch: int, theoretical: int,
                                  operational: int) -> None:
    assert data["dispatch_interval_seconds"] == dispatch, (
        f"expected dispatch_interval_seconds {dispatch}, got {data['dispatch_interval_seconds']}"
    )
    assert data["theoretical_hourly_capacity_guests"] == theoretical, (
        f"expected theoretical_hourly_capacity_guests {theoretical}, "
        f"got {data['theoretical_hourly_capacity_guests']}"
    )
    assert data["operational_hourly_capacity_guests"] == operational, (
        f"expected operational_hourly_capacity_guests {operational}, "
        f"got {data['operational_hourly_capacity_guests']}"
    )


# ─── QueueSegment ─────────────────────────────────────

def assert_queue_segment(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["PROPOSED", "ACCEPTED", "RETIRED"]
    assert data["routing_type"] in ["STANDARD", "ACCESSIBLE", "VIRTUAL_RETURN"]
    assert isinstance(data["position_index"], int) and data["position_index"] >= 1
    assert isinstance(data["capacity_guests"], int) and data["capacity_guests"] >= 0


# ─── ShowScene ────────────────────────────────────────

def assert_show_scene(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["DRAFT", "SEQUENCED", "PROGRAMMED", "VALIDATED", "HELD"]
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 1


def assert_scene_not_held(data: dict) -> None:
    """Outside a freeze both hold fields are cleared to null."""
    assert data["held_from_status"] is None, (
        f"held_from_status must be null when the scene is not held, got {data['held_from_status']!r}"
    )
    assert data["hold_reason"] is None, (
        f"hold_reason must be null when the scene is not held, got {data['hold_reason']!r}"
    )


def assert_scene_held_from(data: dict, held_from_status: str, hold_reason: str) -> None:
    assert data["status"] == "HELD", f"expected HELD, got {data['status']}"
    assert data["held_from_status"] == held_from_status
    assert data["hold_reason"] == hold_reason


# ─── EffectCue ────────────────────────────────────────

def assert_effect_cue(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["PLANNED", "VERIFIED"]
    assert data["discipline_channel"] in [
        "LIGHTING", "AUDIO", "MEDIA", "ANIMATION", "SPECIAL_EFFECT",
    ]
    assert isinstance(data["offset_ms"], int) and data["offset_ms"] >= 0
    assert isinstance(data["duration_ms"], int) and data["duration_ms"] >= 1


# ─── DesignPackage ────────────────────────────────────

def assert_design_package(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SUPERSEDED",
    ]
    assert data["discipline_scope"] in [
        "SHOW_SET", "RIDE_AND_CONTROLS", "MEDIA_AND_AV", "INTEGRATED",
    ]
    assert isinstance(data["base_construction_cost_cents"], int)
    assert isinstance(data["design_fee_cents"], int)
    assert isinstance(data["contingency_cents"], int)
    assert isinstance(data["total_cost_of_work_cents"], int)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_package_pricing(data: dict, base: int, design_fee: int,
                          contingency: int, total: int) -> None:
    assert data["base_construction_cost_cents"] == base
    assert data["design_fee_cents"] == design_fee, (
        f"expected design_fee_cents {design_fee}, got {data['design_fee_cents']}"
    )
    assert data["contingency_cents"] == contingency, (
        f"expected contingency_cents {contingency}, got {data['contingency_cents']}"
    )
    assert data["total_cost_of_work_cents"] == total, (
        f"expected total_cost_of_work_cents {total}, got {data['total_cost_of_work_cents']}"
    )
    assert data["total_cost_of_work_cents"] == (
        data["base_construction_cost_cents"] + data["design_fee_cents"] + data["contingency_cents"]
    ), "total cost of work must be base plus design fee plus contingency"


# ─── SafetyReview / SafetyFinding ─────────────────────

def assert_safety_review(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["IN_REVIEW", "FINDINGS_ISSUED", "CLEARED"]
    assert data["standard_code"] in ["ASTM_F2291", "EN_13814"]
    assert isinstance(data["open_finding_count"], int) and data["open_finding_count"] >= 0


def assert_safety_finding(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["OPEN", "RESOLVED", "CLOSED", "WAIVED"]
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert isinstance(data["remediation_cost_estimate_cents"], int)
    assert data["remediation_cost_estimate_cents"] >= 0


# ─── ValueEngineeringItem / VEBallot ──────────────────

def assert_value_engineering_item(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["PROPOSED", "UNDER_REVIEW", "ADOPTED", "REJECTED"]
    assert isinstance(data["ballot_count"], int) and data["ballot_count"] >= 0
    assert isinstance(data["veto_present"], bool)


def assert_ve_ballot(data: dict) -> None:
    assert_append_only_record(data)
    assert data["party_role"] in ["OwnerRep", "ContractorPM", "CreativeDirector"]
    assert data["decision"] in ["APPROVE", "ABSTAIN", "VETO"]


# ─── RehearsalRun ─────────────────────────────────────

def assert_rehearsal_run(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED"]
    assert data["run_kind"] in ["TECHNICAL_REHEARSAL", "CAST_REHEARSAL", "SOFT_OPEN"]
    assert data["window_end_utc"] > data["window_start_utc"]


def assert_newly_booked_run(data: dict) -> None:
    """A booked run is created SCHEDULED with every measured figure still null."""
    assert data["status"] == "SCHEDULED"
    assert data["guests_cycled"] is None
    assert data["duration_minutes"] is None
    assert data["measured_hourly_throughput_guests"] is None
    assert data["result"] is None


# ─── BudgetLedgerEntry ────────────────────────────────

def assert_ledger_entry(data: dict) -> None:
    assert_append_only_record(data)
    assert data["entry_kind"] in ["COMMITMENT", "CHANGE_ORDER", "VE_SAVING", "REVERSAL"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["reversed"], bool)


# ─── MaintenanceItem ──────────────────────────────────

def assert_maintenance_item(data: dict) -> None:
    assert_audit_triple(data)
    assert data["status"] in ["DRAFT", "APPROVED", "HANDED_OVER"]
    assert data["criticality"] in ["SHOW_CRITICAL", "RUN_CRITICAL", "NON_CRITICAL"]
    assert isinstance(data["recommended_stock_qty"], int)
    assert data["recommended_stock_qty"] >= 0


# ─── Cross-entity invariants ──────────────────────────

def assert_committed_cost_reconciles(project: dict, ledger_rows: list) -> None:
    """The committed basis is a chronological replay of every ledger entry."""
    replay = sum(row["amount_cents"] for row in ledger_rows)
    assert project["committed_cost_cents"] == replay, (
        f"committed_cost_cents {project['committed_cost_cents']} does not equal the "
        f"replay of {len(ledger_rows)} ledger rows totalling {replay}"
    )


def assert_budget_position_identities(budget: dict) -> None:
    """headroom is the ceiling less committed; the restricted-utilisation
    threshold is ninety percent of the ceiling rounded down."""
    assert budget["headroom_cents"] == budget["budget_ceiling_cents"] - budget["committed_cost_cents"]
    expected_restricted = (
        budget["budget_ceiling_cents"] * THRESHOLDS["RESTRICTED_UTILISATION_PCT"]
    ) // 100
    assert budget["restricted_utilisation_cents"] == expected_restricted, (
        f"expected restricted_utilisation_cents {expected_restricted}, "
        f"got {budget['restricted_utilisation_cents']}"
    )
