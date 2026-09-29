"""Shape assertions and cross-field invariant checkers.

The shape helpers assert that a representation carries the fields the PRD says
it carries, with the right kinds of value. The invariant helpers assert
relationships the PRD states must hold between fields of one or more entities.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing.assertions import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ALARA_RESTRICTED_RATIO,
    ALARA_REVIEW_THRESHOLD_MREM,
    AT_RISK_CEILING_MULTIPLIER,
    CONTINGENCY_DOSE_PCT,
    CONTINGENCY_RATE_TIER_1,
    CONTINGENCY_RATE_TIER_2,
    CONTINGENCY_RATE_TIER_3,
    CONTINGENCY_TIER_1_CEILING_USD,
    CONTINGENCY_TIER_2_CEILING_USD,
    DOSE_PENALTY_CEILING,
    DURATION_PRESSURE_CEILING,
    DURATION_PRESSURE_MULTIPLIER,
    PRIORITY_CRITICAL_MIN_SCORE,
    PRIORITY_HIGH_MIN_SCORE,
    REGULATORY_COMMITMENT_BONUS,
    SAFETY_FUNCTION_BONUS,
    WO_TYPE_WEIGHTS,
)

TOLERANCE = 0.01


# --------------------------------------------------------------- arithmetic
def round_half_up(value, places=2):
    """PRD 2.5: every decimal figure is rounded half up."""
    quant = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def approx_equal(actual, expected, tolerance=TOLERANCE):
    return abs(float(actual) - float(expected)) <= tolerance


# ------------------------------------------------------------- timestamps
def normalise_instant(value):
    """Reduce an ISO 8601 UTC instant to a comparable canonical form.

    PRD 2.4 fixes the wire format at three fractional digits; this helper lets
    a test compare the instant a stamped field carries against the instant the
    logical clock was set to without depending on how many trailing zeros the
    two spellings happen to use.
    """
    assert value is not None, "expected an instant, got null"
    text = str(value).strip()
    assert text.endswith("Z"), "expected a UTC instant ending in Z, got {!r}".format(value)
    body = text[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = frac.rstrip("0")
        body = head if not frac else "{}.{}".format(head, frac)
    return body + "Z"


def assert_same_instant(actual, expected, label="instant"):
    assert normalise_instant(actual) == normalise_instant(expected), (
        "{} should be {} but was {}".format(label, expected, actual)
    )


def assert_system_timestamps(data, entity="entity"):
    """PRD 2.4: created_at and updated_at are ISO 8601 UTC instants and
    version starts at 1 and increments by one per mutation."""
    assert "id" in data and is_valid_uuid(data["id"]), (
        "{} id should be a bare UUID, got {!r}".format(entity, data.get("id"))
    )
    assert_timestamp_format(data["created_at"])
    assert_timestamp_format(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        "{} version should be a positive integer, got {!r}".format(
            entity, data.get("version")
        )
    )


# ------------------------------------------------------------ shape checks
def assert_spent_fuel_pool(data):
    assert_system_timestamps(data, "spent fuel pool")
    for field in (
        "station_unit",
        "cells_total",
        "cells_baseline_occupied",
        "full_core_offload_reserve_cells",
        "cells_occupied",
        "cells_reserved",
        "cells_available",
        "protected_cells_available",
    ):
        assert field in data, "spent fuel pool should expose {}".format(field)
    for field in (
        "cells_occupied",
        "cells_reserved",
        "cells_available",
        "protected_cells_available",
    ):
        assert isinstance(data[field], int), (
            "PRD 3.1 says all four ledger figures are integers; {} was {!r}".format(
                field, data[field]
            )
        )
    assert_pool_ledger_consistent(data)


def assert_rad_area(data):
    assert_system_timestamps(data, "rad area")
    for field in (
        "station_unit",
        "area_code",
        "dose_rate_mrem_per_hr",
        "occupancy_limit_workers",
        "survey_buffer_hours",
    ):
        assert field in data, "rad area should expose {}".format(field)


def assert_safety_function(data):
    assert_system_timestamps(data, "safety function")
    for field in (
        "station_unit",
        "function_code",
        "trains_total",
        "min_trains_required",
        "max_concurrent_oos_trains",
    ):
        assert field in data, "safety function should expose {}".format(field)
    assert data["max_concurrent_oos_trains"] == (
        data["trains_total"] - data["min_trains_required"]
    ), "PRD 3.1: max_concurrent_oos_trains is trains_total less min_trains_required"


def assert_outage(data):
    assert_system_timestamps(data, "outage")
    for field in (
        "station_unit",
        "designation",
        "status",
        "schedule_posture",
        "alara_posture",
        "duration_target_hours",
        "dose_budget_total_mrem",
        "cost_budget_usd",
        "scope_freeze_at",
        "required_training_modules",
        "required_badged_workers",
        "dose_committed_mrem",
        "dose_budget_remaining_mrem",
        "approved_scope_cost_usd",
        "scope_contingency_usd",
        "total_scope_cost_usd",
        "approved_emergent_hours",
        "projected_duration_hours",
        "risk_adjusted_duration_hours",
        "badged_worker_count",
        "critical_path_activity_id",
        "scope_locked_at",
        "actual_duration_hours",
        "actual_cost_usd",
        "review_notes",
        "duration_variance_pct",
        "adjusted_duration_variance_pct",
        "dose_variance_pct",
        "cost_variance_pct",
        "outage_performance_index",
        "adjusted_performance_index",
        "created_by_user_id",
    ):
        assert field in data, "outage should expose {}".format(field)


def assert_work_order(data):
    assert_system_timestamps(data, "work order")
    for field in (
        "outage_id",
        "wo_type",
        "title",
        "estimated_hours",
        "estimated_cost_usd",
        "estimated_dose_mrem",
        "regulatory_commitment",
        "safety_function_id",
        "requires_rad_work",
        "status",
        "origin",
        "priority_score",
        "priority",
        "deferral_reason",
        "return_reason",
    ):
        assert field in data, "work order should expose {}".format(field)
    assert_priority_band_matches_score(data)


def assert_schedule_activity(data):
    assert_system_timestamps(data, "schedule activity")
    for field in (
        "outage_id",
        "label",
        "planned_start_offset_hours",
        "planned_duration_hours",
        "work_order_id",
        "predecessor_activity_id",
        "oos_safety_function_id",
        "oos_train_label",
        "execution_status",
        "constraint_status",
        "path_length_hours",
        "risk_adjusted_path_length_hours",
        "is_critical_path",
        "started_at",
        "completed_at",
    ):
        assert field in data, "schedule activity should expose {}".format(field)


def assert_core_load_pattern(data):
    assert_system_timestamps(data, "core load pattern")
    for field in (
        "outage_id",
        "cycle_length_mwd_mtu",
        "fresh_assembly_count",
        "discharge_assembly_count",
        "reactivity_margin_pcm",
        "status",
        "created_by_user_id",
        "approved_by_user_id",
    ):
        assert field in data, "core load pattern should expose {}".format(field)


def assert_pool_cell_reservation(data):
    assert_system_timestamps(data, "pool cell reservation")
    for field in (
        "outage_id",
        "spent_fuel_pool_id",
        "cells_requested",
        "purpose",
        "availability_variant",
        "status",
        "release_reason",
    ):
        assert field in data, "pool cell reservation should expose {}".format(field)


def assert_supplemental_worker(data):
    assert_system_timestamps(data, "supplemental worker")
    for field in (
        "outage_id",
        "full_name",
        "craft",
        "sponsoring_contractor",
        "status",
        "background_status",
        "training_status",
        "training_modules_completed",
        "badge_number",
    ):
        assert field in data, "supplemental worker should expose {}".format(field)


def assert_rwp(data):
    assert_system_timestamps(data, "radiological work permit")
    for field in (
        "outage_id",
        "work_order_id",
        "rad_area_id",
        "worker_count",
        "shielding_factor",
        "planned_start_offset_hours",
        "planned_duration_hours",
        "per_worker_dose_mrem",
        "collective_dose_mrem",
        "contingency_dose_mrem",
        "committed_dose_mrem",
        "alara_review_required",
        "alara_review_reference",
        "actual_dose_mrem",
        "void_reason",
        "status",
    ):
        assert field in data, "radiological work permit should expose {}".format(field)


def assert_dose_transaction(data):
    """PRD 2.4 singles this entity out: it carries only id and created_at, so
    neither updated_at nor version should appear in its representation."""
    assert is_valid_uuid(data["id"]), "dose transaction id should be a bare UUID"
    assert is_iso8601_timestamp(data["created_at"]), (
        "dose transaction created_at should be an ISO 8601 UTC instant"
    )
    for field in ("rwp_id", "direction", "amount_mrem", "reason"):
        assert field in data, "dose transaction should expose {}".format(field)
    assert "updated_at" not in data, (
        "PRD 2.4: updated_at should not appear on a dose transaction"
    )
    assert "version" not in data, (
        "PRD 2.4: version should not appear on a dose transaction"
    )
    assert float(data["amount_mrem"]) > 0, (
        "PRD 3.7: every ledger row carries an unsigned amount_mrem greater than zero"
    )


def assert_emergent_item(data):
    assert_system_timestamps(data, "emergent work item")
    for field in (
        "discovered_from_work_order_id",
        "description",
        "estimated_hours",
        "estimated_cost_usd",
        "estimated_dose_mrem",
        "discovered_during_inspection",
        "status",
        "disposition_note",
        "created_work_order_id",
    ):
        assert field in data, "emergent work item should expose {}".format(field)


def assert_startup_test(data):
    assert_system_timestamps(data, "startup test")
    for field in (
        "outage_id",
        "test_code",
        "sequence_index",
        "hold_point_type",
        "predicted_reactivity_pcm",
        "measured_reactivity_pcm",
        "reactivity_deviation_pcm",
        "nrc_release_reference",
        "status",
        "created_by_user_id",
        "satisfied_by_user_id",
    ):
        assert field in data, "startup test should expose {}".format(field)


# --------------------------------------------------------------- invariants
def assert_pool_ledger_consistent(pool):
    """PRD 3.1 and 3.3: cells_available is cells_total less cells_occupied
    less cells_reserved, and protected_cells_available is cells_available less
    full_core_offload_reserve_cells."""
    assert pool["cells_available"] == (
        pool["cells_total"] - pool["cells_occupied"] - pool["cells_reserved"]
    ), (
        "cells_available {} should be cells_total {} less occupied {} less reserved {}".format(
            pool["cells_available"],
            pool["cells_total"],
            pool["cells_occupied"],
            pool["cells_reserved"],
        )
    )
    assert pool["protected_cells_available"] == (
        pool["cells_available"] - pool["full_core_offload_reserve_cells"]
    ), "protected_cells_available should be cells_available less the reserve block"


def assert_dose_budget_consistent(outage):
    """PRD 3.7: dose_budget_remaining_mrem is dose_budget_total_mrem less
    dose_committed_mrem."""
    assert approx_equal(
        outage["dose_budget_remaining_mrem"],
        float(outage["dose_budget_total_mrem"]) - float(outage["dose_committed_mrem"]),
    ), (
        "remaining {} should be total {} less committed {}".format(
            outage["dose_budget_remaining_mrem"],
            outage["dose_budget_total_mrem"],
            outage["dose_committed_mrem"],
        )
    )


def assert_scope_rollup_consistent(outage):
    """PRD 3.2: total_scope_cost_usd is the base plus the contingency, and the
    contingency rate is selected from the base alone."""
    base = float(outage["approved_scope_cost_usd"])
    contingency = float(outage["scope_contingency_usd"])
    assert approx_equal(
        outage["total_scope_cost_usd"], base + contingency
    ), "total_scope_cost_usd should be approved_scope_cost_usd plus scope_contingency_usd"
    assert approx_equal(contingency, expected_contingency(base)), (
        "contingency {} should be the base {} at the rate the base alone selects".format(
            contingency, base
        )
    )


def assert_priority_band_matches_score(work_order):
    """PRD 3.2: at least 75 is CRITICAL, at least 45 is HIGH, anything lower
    is DISCRETIONARY, both comparisons made on the rounded figure."""
    assert work_order["priority"] == expected_priority_band(
        work_order["priority_score"]
    ), (
        "priority {} does not match the band a score of {} selects".format(
            work_order["priority"], work_order["priority_score"]
        )
    )


def assert_alara_posture_consistent(outage):
    """PRD 3.7: SUSPENDED when the remaining budget is at or below zero,
    otherwise RESTRICTED when the unrounded remaining-to-total ratio is at or
    below one quarter, otherwise NORMAL."""
    assert outage["alara_posture"] == expected_alara_posture(
        outage["dose_budget_remaining_mrem"], outage["dose_budget_total_mrem"]
    ), (
        "alara_posture {} does not follow from remaining {} against total {}".format(
            outage["alara_posture"],
            outage["dose_budget_remaining_mrem"],
            outage["dose_budget_total_mrem"],
        )
    )


def assert_ledger_rows_ascending(rows):
    """PRD 3.7: a permit's ledger rows are read in ascending created_at
    order."""
    stamps = [normalise_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "dose ledger rows should be in ascending created_at order"


def assert_post_outage_fields_null(outage):
    """PRD 3.2: every post-outage field is null until the review runs."""
    for field in (
        "actual_duration_hours",
        "actual_cost_usd",
        "review_notes",
        "duration_variance_pct",
        "adjusted_duration_variance_pct",
        "dose_variance_pct",
        "cost_variance_pct",
        "outage_performance_index",
        "adjusted_performance_index",
    ):
        assert outage[field] is None, "{} should be null before the review runs".format(field)


# ------------------------------------------------------- derived quantities
def expected_priority_band(score):
    score = float(score)
    if score >= PRIORITY_CRITICAL_MIN_SCORE:
        return "CRITICAL"
    if score >= PRIORITY_HIGH_MIN_SCORE:
        return "HIGH"
    return "DISCRETIONARY"


def expected_priority_score(
    wo_type,
    estimated_hours,
    duration_target_hours,
    estimated_dose_mrem,
    has_safety_function=False,
    regulatory_commitment=False,
):
    """PRD 3.2's scoring rule, reproduced exactly: type weight, two bonuses, a
    capped duration-pressure term, less a capped whole-block dose penalty."""
    total = Decimal(WO_TYPE_WEIGHTS[wo_type])
    if has_safety_function:
        total += Decimal(SAFETY_FUNCTION_BONUS)
    if regulatory_commitment:
        total += Decimal(REGULATORY_COMMITMENT_BONUS)
    pressure = Decimal(str(estimated_hours)) / Decimal(str(duration_target_hours))
    pressure = pressure * Decimal(DURATION_PRESSURE_MULTIPLIER)
    pressure = pressure.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total += min(pressure, Decimal(DURATION_PRESSURE_CEILING))
    penalty = int(Decimal(str(estimated_dose_mrem)) // Decimal(100))
    total -= Decimal(min(penalty, DOSE_PENALTY_CEILING))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_contingency(base):
    """PRD 3.2: 8 percent below 5,000,000, 12 percent below 20,000,000 and 15
    percent otherwise, selected from the base alone."""
    base_d = Decimal(str(base))
    if base_d < Decimal(CONTINGENCY_TIER_1_CEILING_USD):
        rate = Decimal(str(CONTINGENCY_RATE_TIER_1))
    elif base_d < Decimal(CONTINGENCY_TIER_2_CEILING_USD):
        rate = Decimal(str(CONTINGENCY_RATE_TIER_2))
    else:
        rate = Decimal(str(CONTINGENCY_RATE_TIER_3))
    return float((base_d * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_reactivity_margin(fresh_assembly_count, cycle_length_mwd_mtu):
    """PRD 3.3: 800 pcm, plus 12 pcm per fresh assembly, less 15 pcm per
    gigawatt-day per metric ton."""
    value = (
        Decimal(800)
        + Decimal(12) * Decimal(str(fresh_assembly_count))
        - Decimal(15) * (Decimal(str(cycle_length_mwd_mtu)) / Decimal(1000))
    )
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_rwp_doses(dose_rate_mrem_per_hr, planned_duration_hours, shielding_factor, worker_count):
    """PRD 3.7's pinned rounding order: the per-worker figure is rounded before
    it is multiplied by the crew size."""
    per_worker = (
        Decimal(str(dose_rate_mrem_per_hr))
        * Decimal(str(planned_duration_hours))
        * (Decimal(1) - Decimal(str(shielding_factor)))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    collective = (per_worker * Decimal(str(worker_count))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    contingency = (collective * Decimal(str(CONTINGENCY_DOSE_PCT))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    committed = (collective + contingency).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "per_worker_dose_mrem": float(per_worker),
        "collective_dose_mrem": float(collective),
        "contingency_dose_mrem": float(contingency),
        "committed_dose_mrem": float(committed),
        "alara_review_required": float(collective) >= ALARA_REVIEW_THRESHOLD_MREM,
    }


def expected_alara_posture(remaining, total):
    remaining_d = Decimal(str(remaining))
    if remaining_d <= 0:
        return "SUSPENDED"
    ratio = remaining_d / Decimal(str(total))
    if ratio <= Decimal(str(ALARA_RESTRICTED_RATIO)):
        return "RESTRICTED"
    return "NORMAL"


def expected_schedule_posture(projected_duration_hours, duration_target_hours):
    """PRD 3.4: both boundaries are inclusive and the AT_RISK ceiling is the
    target multiplied by 1.10 and rounded half up."""
    projected = Decimal(str(projected_duration_hours))
    target = Decimal(str(duration_target_hours))
    if projected <= target:
        return "ON_TRACK"
    ceiling = (target * Decimal(str(AT_RISK_CEILING_MULTIPLIER))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if projected <= ceiling:
        return "AT_RISK"
    return "RECOVERY_REQUIRED"


def expected_variance_pct(actual, budget):
    value = (
        (Decimal(str(actual)) - Decimal(str(budget))) / Decimal(str(budget)) * Decimal(100)
    )
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def expected_performance_index(duration_variance_pct, dose_variance_pct, cost_variance_pct):
    """PRD 3.9: each rounded percentage is multiplied by its weight, the three
    products are summed without intermediate rounding, and the subtraction from
    100 is rounded once at the end. Both indices are floored at zero."""
    penalty = (
        max(Decimal(0), Decimal(str(duration_variance_pct))) * Decimal("0.5")
        + max(Decimal(0), Decimal(str(dose_variance_pct))) * Decimal("0.3")
        + max(Decimal(0), Decimal(str(cost_variance_pct))) * Decimal("0.2")
    )
    index = (Decimal(100) - penalty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(max(Decimal(0), index))
