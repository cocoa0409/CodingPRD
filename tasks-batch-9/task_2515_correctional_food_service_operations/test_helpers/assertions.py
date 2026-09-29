"""Per-entity shape assertions and domain invariant checkers."""

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    MISSED_MEAL_TOLERANCE_RATE,
    SHARP_TOOL_CLASSES,
)

Json = Dict[str, Any]


# --- Envelope-level helpers --------------------------------------------------


def assert_versioned_entity(entity: Json) -> None:
    """Every mutable entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_versionless_entity(entity: Json) -> None:
    """The PRD declares that a population count and a temperature reading carry
    only `id` and `created_at`: neither has `updated_at` and neither has
    `version`."""
    assert is_valid_uuid(entity["id"]), f"id must be a UUID, got {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert "updated_at" not in entity, "this entity must not expose updated_at"
    assert "version" not in entity, "this entity must not expose version"


# --- Per-entity assertions ---------------------------------------------------


def assert_service_contract(contract: Json) -> None:
    assert_versioned_entity(contract)
    assert contract["status"] in ("DRAFT", "ACTIVE", "RECONCILING", "CLOSED")
    for field in (
        "total_trays_served",
        "meal_days_served",
        "missed_meal_total",
        "substitution_total",
        "grievance_sla_breach_count",
        "raw_liquidated_damages_cents",
        "substitution_surcharge_cents",
        "liquidated_damages_cents",
        "gross_food_cost_cents",
        "cost_recovery_credit_cents",
        "net_liquidated_damages_cents",
    ):
        assert isinstance(contract[field], int), f"{field} must be an integer"
    for field in (
        "substitution_rate_pct",
        "cost_cents_per_meal_day_actual",
        "performance_score",
    ):
        assert isinstance(contract[field], (int, float)), f"{field} must be numeric"


def assert_contract_ledger_zeroed(contract: Json) -> None:
    """The declared creation defaults: eleven integer ledger fields at 0, three
    decimal fields at 0.00, and the variant and both timestamps null."""
    for field in (
        "total_trays_served",
        "meal_days_served",
        "missed_meal_total",
        "substitution_total",
        "grievance_sla_breach_count",
        "raw_liquidated_damages_cents",
        "substitution_surcharge_cents",
        "liquidated_damages_cents",
        "gross_food_cost_cents",
        "cost_recovery_credit_cents",
        "net_liquidated_damages_cents",
    ):
        assert contract[field] == 0, f"{field} should default to 0, got {contract[field]}"
    assert float(contract["substitution_rate_pct"]) == 0.0
    assert float(contract["cost_cents_per_meal_day_actual"]) == 0.0
    assert float(contract["performance_score"]) == 0.0
    assert contract["ld_variant"] is None
    assert contract["reconciled_at"] is None
    assert contract["closed_at"] is None


def assert_facility(facility: Json) -> None:
    assert_versioned_entity(facility)
    assert facility["kitchen_posture"] in ("OPEN", "RESTRICTED", "LOCKDOWN")
    assert isinstance(facility["corrective_action_required"], bool)
    for field in (
        "satellite_site_count",
        "blast_chiller_capacity",
        "sharps_authorized_count",
        "sharps_issued_count",
        "sharps_unaccounted_count",
        "sharps_audit_shortfall",
        "sharps_on_board_count",
        "open_sharps_discrepancy_count",
        "open_contraband_incident_count",
        "active_special_diet_count",
    ):
        assert isinstance(facility[field], int), f"{field} must be an integer"


def assert_menu_cycle(cycle: Json) -> None:
    assert_versioned_entity(cycle)
    assert cycle["status"] in ("DRAFT", "NUTRITION_APPROVED", "ACTIVE", "RETIRED")
    assert isinstance(cycle["item_count"], int)


def assert_menu_cycle_draft_defaults(cycle: Json) -> None:
    """A freshly created cycle opens in DRAFT with no items and no approved
    figures."""
    assert cycle["status"] == "DRAFT"
    assert cycle["item_count"] == 0
    for field in (
        "approved_kcal_per_meal_day",
        "approved_protein_grams_per_meal_day",
        "approved_sodium_mg_per_meal_day",
        "approved_cost_cents_per_meal_day",
    ):
        assert cycle[field] is None, f"{field} should be null on a DRAFT cycle"
    assert cycle["nutrition_signed_by_user_id"] is None
    assert cycle["activated_by_user_id"] is None
    assert cycle["activated_at"] is None


def assert_menu_cycle_item(item: Json) -> None:
    assert_versioned_entity(item)
    assert item["meal_slot"] in ("BREAKFAST", "LUNCH", "DINNER")
    assert item["cycle_day"] >= 1


def assert_inmate(inmate: Json) -> None:
    assert_versioned_entity(inmate)
    assert inmate["status"] in ("IN_CUSTODY", "RELEASED", "TRANSFERRED")
    assert inmate["housing_unit"] in ("GENERAL", "SEGREGATION", "SATELLITE", "MEDICAL")
    assert isinstance(inmate["active_diet_order_count"], int)


def assert_diet_order(order: Json) -> None:
    assert_versioned_entity(order)
    assert order["status"] in (
        "PENDING_VERIFICATION",
        "ACTIVE",
        "SUSPENDED",
        "EXPIRED",
        "REVOKED",
    )
    assert order["order_type"] in ("RELIGIOUS", "MEDICAL")
    assert isinstance(order["reverification_count"], int)


def assert_population_count(count: Json) -> None:
    assert_versionless_entity(count)
    assert count["source"] in ("FORMAL_COUNT", "EMERGENCY_COUNT")
    assert count["total_population"] == (
        count["general_population"]
        + count["segregation_population"]
        + count["satellite_population"]
        + count["medical_population"]
    ), "total_population must be the sum of the four segment counts"


def assert_meal_forecast(forecast: Json) -> None:
    assert_versioned_entity(forecast)
    assert forecast["status"] in ("DRAFT", "LOCKED", "SUPERSEDED")
    assert forecast["forecast_variant"] in ("COUNT_DRIVEN", "ROSTER_DRIVEN")
    assert forecast["total_forecast_trays"] == (
        forecast["line_trays"] + forecast["waste_allowance_trays"]
    ), "total_forecast_trays must be line_trays plus waste_allowance_trays"


def assert_production_batch(batch: Json) -> None:
    assert_versioned_entity(batch)
    assert batch["production_stage"] in (
        "PLANNED",
        "COOKED",
        "CHILLED",
        "STAGED",
        "SERVED",
        "DISCARDED",
    )
    assert batch["qa_status"] in ("QA_PENDING", "QA_PASSED", "QA_HELD", "QA_CONDEMNED")
    assert isinstance(batch["cook_chill_compliant"], bool)


def assert_batch_creation_defaults(batch: Json) -> None:
    assert batch["production_stage"] == "PLANNED"
    assert batch["qa_status"] == "QA_PENDING"
    assert batch["produced_trays"] == 0
    assert batch["cook_end_at"] is None
    assert batch["chill_final_at"] is None
    assert batch["chill_minutes"] is None
    assert batch["qa_reason"] is None
    assert batch["cook_chill_compliant"] is False


def assert_temperature_log(log: Json) -> None:
    assert_versionless_entity(log)
    assert log["log_point"] in (
        "COOK_END",
        "CHILL_INTERMEDIATE",
        "CHILL_FINAL",
        "TRANSPORT_DEPART",
        "TRANSPORT_ARRIVE",
        "REHEAT_SERVE",
    )
    assert isinstance(log["in_range"], bool)


def assert_inmate_worker(worker: Json) -> None:
    assert_versioned_entity(worker)
    assert worker["clearance_status"] in ("CLEARED", "SUSPENDED", "BARRED")
    assert worker["assignment_status"] in ("UNASSIGNED", "ASSIGNED")
    assert worker["work_area"] in (
        None,
        "BAKERY",
        "COOK_CHILL",
        "SERVING_LINE",
        "SANITATION",
    )
    assert isinstance(worker["contraband_strike_count"], int)


def assert_worker_enrollment_defaults(worker: Json) -> None:
    assert worker["clearance_status"] == "CLEARED"
    assert worker["assignment_status"] == "UNASSIGNED"
    assert worker["work_area"] is None
    assert worker["contraband_strike_count"] == 0


def assert_tool_issuance(issuance: Json) -> None:
    assert_versioned_entity(issuance)
    assert issuance["status"] in ("ISSUED", "UNACCOUNTED", "RETURNED")
    assert issuance["tool_class"] in (
        "SHARP_KNIFE",
        "MEAT_SAW",
        "SCISSORS",
        "NON_SHARP",
    )
    assert isinstance(issuance["recovered"], bool)


def assert_contraband_incident(incident: Json) -> None:
    assert_versioned_entity(incident)
    assert incident["status"] in ("OPEN", "SANCTIONED", "CLEARED")
    assert incident["item_class"] in (
        "SHARP",
        "YEAST_ALCOHOL",
        "FOOD_DIVERSION",
        "COMMISSARY_ITEM",
    )
    assert incident["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_meal_service_record(record: Json) -> None:
    assert_versioned_entity(record)
    assert record["status"] in ("OPEN", "CLOSED", "DISPUTED")
    assert record["total_trays_served"] == (
        record["trays_served_general"]
        + record["trays_served_segregation"]
        + record["trays_served_satellite"]
    ), "total_trays_served is the sum of the three site counts only"


def assert_menu_substitution(substitution: Json) -> None:
    assert_versioned_entity(substitution)
    assert substitution["approval_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(substitution["nutrition_equivalent"], bool)


def assert_grievance(grievance: Json) -> None:
    assert_versioned_entity(grievance)
    assert grievance["status"] in (
        "FILED",
        "UNDER_INVESTIGATION",
        "DIET_REVIEW",
        "DUAL_TRACK",
        "READY_FOR_RESPONSE",
        "RESPONDED",
        "ESCALATED",
        "CLOSED",
    )
    assert isinstance(grievance["investigation_complete"], bool)
    assert isinstance(grievance["diet_review_complete"], bool)
    assert isinstance(grievance["diet_remedy_required"], bool)
    assert isinstance(grievance["sla_breached"], bool)


def assert_grievance_filed_defaults(grievance: Json) -> None:
    assert grievance["status"] == "FILED"
    assert grievance["routed_branch"] is None
    assert grievance["investigation_complete"] is False
    assert grievance["diet_review_complete"] is False
    assert grievance["diet_remedy_required"] is False
    assert grievance["remedy"] is None
    assert grievance["refeed_tray_count"] == 0
    assert grievance["response_at"] is None
    assert grievance["responded_by_user_id"] is None
    assert grievance["sla_breached"] is False


# --- Domain invariant checkers ----------------------------------------------


def assert_sharps_conservation(facility: Json) -> None:
    """The PRD's conservation identity: on-board plus issued plus unaccounted
    always equals the authorized count."""
    total = (
        facility["sharps_on_board_count"]
        + facility["sharps_issued_count"]
        + facility["sharps_unaccounted_count"]
    )
    assert total == facility["sharps_authorized_count"], (
        "sharps conservation identity broken: "
        f"{facility['sharps_on_board_count']} on board + "
        f"{facility['sharps_issued_count']} issued + "
        f"{facility['sharps_unaccounted_count']} unaccounted "
        f"!= {facility['sharps_authorized_count']} authorized"
    )


def assert_sharps_summary_conservation(summary: Json) -> None:
    total = (
        summary["sharps_on_board_count"]
        + summary["sharps_issued_count"]
        + summary["sharps_unaccounted_count"]
    )
    assert total == summary["sharps_authorized_count"], summary


def expected_missed_meal_tolerance(expected_service_trays: int) -> int:
    """Floor of two percent of the expected tray count."""
    import math

    return math.floor(expected_service_trays * MISSED_MEAL_TOLERANCE_RATE)


def assert_only_sharp_classes_counted(tool_class: str, counted: bool) -> None:
    """Only the three sharp classes participate in the sharps counters."""
    is_sharp = tool_class in SHARP_TOOL_CLASSES
    assert counted == is_sharp, (
        f"tool_class {tool_class} should "
        f"{'participate in' if is_sharp else 'be excluded from'} the sharps counters"
    )


def assert_fields_equal(left: Json, right: Json, fields: Iterable[str]) -> None:
    """Every named field must agree between two representations of one row."""
    for field in fields:
        assert left.get(field) == right.get(field), (
            f"field {field!r} disagrees: {left.get(field)!r} vs {right.get(field)!r}"
        )


def assert_decimal_2dp(value: Any, expected: float) -> None:
    """Compare a 2-decimal-place figure exactly."""
    assert round(float(value) + 0.0, 2) == round(expected, 2), (
        f"expected {expected}, got {value}"
    )


def _version_of(value: Any) -> int:
    """Accept either a raw version integer or the entity body carrying it."""
    if isinstance(value, dict):
        return int(value["version"])
    return int(value)


def assert_version_bumped_by(before: Any, after: Any, delta: int = 1) -> None:
    old, new = _version_of(before), _version_of(after)
    assert new == old + delta, (
        f"expected version {old} + {delta} = {old + delta}, got {new}"
    )


def assert_no_version_change(before: Any, after: Any) -> None:
    old, new = _version_of(before), _version_of(after)
    assert new == old, f"version changed from {old} to {new}"


def find_by_id(rows: Iterable[Json], row_id: str) -> Optional[Json]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None


def same_instant(left: Optional[str], right: Optional[str]) -> bool:
    """Compare two ISO 8601 instants without caring about the Z / +00:00 spelling."""
    if left is None or right is None:
        return left is right
    from datetime import datetime

    def parse(text: str) -> datetime:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    return parse(left) == parse(right)


def assert_instant(actual: Optional[str], expected: str) -> None:
    assert same_instant(actual, expected), f"expected instant {expected}, got {actual}"
