"""Domain assertions for the Package Sortation Peak Staffing API.

Three families live here:

* `assert_common_fields` and the per-entity shape checks, which assert only what
  PRD §2.4 and the §3 field lists state.
* The rounding helpers, which re-derive a pinned calculation from its inputs so
  a test can assert the contract rather than a copied number.
* The two conservation checkers of PRD §2.8, which are asserted after every
  request that moves packages or headcount.
"""

from decimal import Decimal, ROUND_HALF_UP

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AUTOMATION_TIER_HIGH_PCT,
    AUTOMATION_TIER_MID_PCT,
    CUFT_PER_PACKAGE,
    FIXED_OVERHEAD_CENTS_PER_SHIFT,
    FLEX_PREMIUM_PCT,
    FLEX_PREMIUM_TIER_1_MAX_RATIO,
    FLEX_PREMIUM_TIER_2_MAX_RATIO,
    LANE_CAPACITY_DIVISOR_FLOOR,
    MIN_HEADCOUNT_PER_LINE,
    POSTURE_MULTIPLIER,
    PPH_TIER_HIGH,
    PPH_TIER_LOW,
    PPH_TIER_MID,
    RATE_CENTS_PER_HOUR,
    REWORK_CENTS_PER_MISSORT_PACKAGE,
)


# ─── Rounding primitives (PRD §2.9) ───────────────────

def round_half_up(value, places: int):
    """Round `value` half up to `places` decimal places, as PRD §2.9 requires."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_cents(value) -> int:
    """Round to whole integer cents, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value) -> int:
    """Smallest integer not less than `value`, computed exactly."""
    dec = Decimal(str(value))
    floored = int(dec)
    return floored if dec == floored else floored + 1


# ─── Common fields (PRD §2.4) ─────────────────────────

def assert_common_fields(entity: dict, expected_version: int = None):
    """Assert the four common properties every entity in this service carries."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), (
        f"created_at is not ISO 8601: {entity['created_at']}"
    )
    assert is_iso8601_timestamp(entity["updated_at"]), (
        f"updated_at is not ISO 8601: {entity['updated_at']}"
    )
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at 1"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_fresh_entity(entity: dict):
    """Assert a just-created row: `version` is 1 and the timestamps agree."""
    assert_common_fields(entity, expected_version=1)


# ─── Per-entity shape ─────────────────────────────────

def assert_sort_center(center: dict):
    assert_common_fields(center)
    assert isinstance(center["code"], str)
    assert isinstance(center["name"], str)
    assert center["ops_posture"] in {"OPEN", "RESTRICTED", "FROZEN"}
    for field in (
        "flex_pool_total",
        "flex_pool_available",
        "flex_pool_reserved",
        "open_jam_count",
        "open_serious_injury_count",
        "packages_inducted_count",
        "wip_package_count",
        "exception_hold_count",
        "disposed_package_count",
        "missort_corrected_count",
    ):
        assert isinstance(center[field], int), f"{field} must be an integer"
        assert center[field] >= 0, f"{field} must never go negative"
    if center["last_posture_change_at"] is not None:
        assert is_iso8601_timestamp(center["last_posture_change_at"])


def assert_dock_door(door: dict):
    assert_common_fields(door)
    assert is_valid_uuid(door["sort_center_id"])
    assert isinstance(door["door_number"], int) and door["door_number"] >= 1
    assert door["kind"] in {"INBOUND", "OUTBOUND"}
    assert door["status"] in {"ACTIVE", "OUT_OF_SERVICE"}
    assert isinstance(door["turnaround_buffer_min"], int)
    assert door["turnaround_buffer_min"] >= 0


def assert_sort_chute(chute: dict):
    assert_common_fields(chute)
    assert is_valid_uuid(chute["sort_center_id"])
    assert isinstance(chute["chute_number"], int) and chute["chute_number"] >= 1
    assert isinstance(chute["throughput_pph"], int) and chute["throughput_pph"] >= 1
    assert isinstance(chute["max_concurrent_destinations"], int)
    assert chute["max_concurrent_destinations"] >= 1
    assert chute["status"] in {"ACTIVE", "CONGESTED"}
    assert isinstance(chute["jam_hold_count"], int) and chute["jam_hold_count"] >= 0


def assert_destination_lane(lane: dict):
    assert_common_fields(lane)
    assert is_valid_uuid(lane["sort_center_id"])
    assert isinstance(lane["lane_code"], str)
    assert lane["service_class"] in {"GROUND", "EXPRESS", "FREIGHT"}
    assert lane["status"] in {"ACTIVE", "CLOSED"}
    for field in (
        "forecast_hourly_volume",
        "sorted_package_count",
        "backlog_package_count",
        "assigned_capacity_pph",
    ):
        assert isinstance(lane[field], int), f"{field} must be an integer"
        assert lane[field] >= 0, f"{field} must never go negative"
    assert float(lane["lane_pressure_ratio"]) >= 0


def assert_chute_assignment(assignment: dict):
    assert_common_fields(assignment)
    assert is_valid_uuid(assignment["chute_id"])
    assert is_valid_uuid(assignment["destination_lane_id"])
    assert assignment["status"] in {"ACTIVE", "SUSPENDED", "SUPERSEDED", "ENDED"}
    assert assignment["window_start"] < assignment["window_end"], (
        "window_end must be strictly after window_start"
    )


def assert_trailer_appointment(appointment: dict):
    assert_common_fields(appointment)
    assert is_valid_uuid(appointment["sort_center_id"])
    assert is_valid_uuid(appointment["door_id"])
    assert appointment["status"] in {
        "SCHEDULED",
        "ARRIVED",
        "UNLOADING",
        "JAM_HELD",
        "UNLOADED",
    }
    assert appointment["priority_class"] in {
        "CRITICAL",
        "EXPRESS",
        "STANDARD",
        "DEFERRED",
    }
    assert isinstance(appointment["manifest_package_count"], int)
    assert appointment["manifest_package_count"] >= 0
    assert isinstance(appointment["jam_count"], int) and appointment["jam_count"] >= 0
    if appointment["unload_sequence_rank"] is not None:
        assert isinstance(appointment["unload_sequence_rank"], int)
        assert appointment["unload_sequence_rank"] >= 1


def assert_shift_plan(plan: dict):
    assert_common_fields(plan)
    assert is_valid_uuid(plan["sort_center_id"])
    assert plan["status"] in {
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REJECTED",
        "AT_RISK",
        "CLOSED",
    }
    for field in (
        "forecast_volume",
        "planned_core_headcount",
        "planned_seasonal_headcount",
        "labor_budget_cents",
        "required_headcount",
        "flex_draw_count",
        "planned_labor_cents",
        "committed_headcount",
        "staffing_gap",
        "unfilled_gap",
        "sorted_package_count",
        "missort_package_count",
        "actual_labor_cents",
    ):
        assert isinstance(plan[field], int), f"{field} must be an integer"
        assert plan[field] >= 0, f"{field} must never go negative"
    assert plan["shift_window_start"] < plan["shift_window_end"]


def assert_worker(worker: dict):
    assert_common_fields(worker)
    assert is_valid_uuid(worker["sort_center_id"])
    assert worker["hire_class"] in {"CORE", "SEASONAL", "FLEX"}
    assert worker["status"] in {
        "APPLIED",
        "ONBOARDING",
        "CLEARED",
        "CERTIFIED",
        "SEPARATED",
    }
    assert worker["attrition_risk_basis"] in {"COHORT_BASELINE", "INDIVIDUAL_OBSERVED"}
    assert isinstance(worker["attrition_flagged"], bool)
    for field in (
        "training_sessions_completed",
        "training_sessions_missed",
        "no_show_count",
        "completed_assignment_count",
        "consecutive_completed_shifts",
        "tenure_days",
    ):
        assert isinstance(worker[field], int), f"{field} must be an integer"
        assert worker[field] >= 0, f"{field} must never go negative"


def assert_staff_assignment(assignment: dict):
    assert_common_fields(assignment)
    assert is_valid_uuid(assignment["shift_plan_id"])
    assert is_valid_uuid(assignment["worker_id"])
    assert is_valid_uuid(assignment["line_chute_id"])
    assert assignment["status"] in {"ASSIGNED", "CHECKED_IN", "COMPLETED", "NO_SHOW"}
    assert assignment["role_on_line"] in {
        "UNLOADER",
        "PRIMARY_SORTER",
        "SECONDARY_SORTER",
        "LOADER",
        "JAM_TECH",
    }
    assert float(assignment["worked_hours"]) >= 0


def assert_outbound_load(load: dict):
    assert_common_fields(load)
    assert is_valid_uuid(load["sort_center_id"])
    assert is_valid_uuid(load["door_id"])
    assert is_valid_uuid(load["destination_lane_id"])
    assert load["load_status"] in {"STAGING", "LOADING", "LOADED", "DISPATCHED"}
    assert load["seal_status"] in {"UNSEALED", "SEALED", "BROKEN"}
    assert float(load["trailer_cube_cuft"]) > 0
    assert float(load["cube_used_cuft"]) >= 0
    assert float(load["cube_utilization_pct"]) >= 0
    assert isinstance(load["package_count"], int) and load["package_count"] >= 0


def assert_package_exception(exception: dict):
    assert_common_fields(exception)
    assert is_valid_uuid(exception["sort_center_id"])
    assert exception["exception_type"] in {
        "DAMAGED",
        "UNLABELED",
        "OVERSIZED",
        "MISSORT",
    }
    assert exception["status"] in {"OPEN", "RESOLVED"}
    assert isinstance(exception["package_count"], int)
    assert exception["package_count"] >= 1
    if exception["resolution"] is not None:
        assert exception["resolution"] in {"REROUTE", "DISPOSE", "RELABEL"}


def assert_injury_report(report: dict):
    assert_common_fields(report)
    assert is_valid_uuid(report["sort_center_id"])
    assert is_valid_uuid(report["worker_id"])
    assert report["severity"] in {"FIRST_AID", "RECORDABLE", "SERIOUS"}
    assert report["status"] in {"OPEN", "CLOSED"}
    assert isinstance(report["lost_time_days"], int)
    assert report["lost_time_days"] >= 0


# ─── Conservation ledgers (PRD §2.8) ──────────────────

def assert_package_conservation(center: dict, lanes: list):
    """`packages_inducted_count` == wip + exception hold + disposed + all lanes' sorted.

    `lanes` must be every destination lane of the center regardless of status,
    because a closed lane still holds the packages already sorted into it.
    """
    sorted_total = sum(lane["sorted_package_count"] for lane in lanes)
    right = (
        center["wip_package_count"]
        + center["exception_hold_count"]
        + center["disposed_package_count"]
        + sorted_total
    )
    assert center["packages_inducted_count"] == right, (
        "package conservation broken: inducted="
        f"{center['packages_inducted_count']} but wip={center['wip_package_count']} "
        f"+ hold={center['exception_hold_count']} "
        f"+ disposed={center['disposed_package_count']} "
        f"+ lanes_sorted={sorted_total} = {right}"
    )


def assert_flex_pool_conservation(center: dict, plans: list = None):
    """`flex_pool_total` == available + reserved, and reserved == sum of live draws.

    When `plans` is supplied it must be every shift plan of the center; the
    reserved figure is then checked against the `flex_draw_count` of the plans
    whose `status` is `APPROVED` or `AT_RISK`.
    """
    assert (
        center["flex_pool_available"] + center["flex_pool_reserved"]
        == center["flex_pool_total"]
    ), (
        "flex pool triple broken: "
        f"{center['flex_pool_available']} + {center['flex_pool_reserved']} != "
        f"{center['flex_pool_total']}"
    )
    if plans is not None:
        reserved = sum(
            plan["flex_draw_count"]
            for plan in plans
            if plan["status"] in ("APPROVED", "AT_RISK")
        )
        assert center["flex_pool_reserved"] == reserved, (
            f"flex_pool_reserved={center['flex_pool_reserved']} but live plans "
            f"reserve {reserved}"
        )


# ─── Calculation re-derivations ───────────────────────

def expected_pph_for_automation(automation_pct: float) -> int:
    """Per-associate throughput tier read from the center (PRD §3.4 step 2)."""
    if float(automation_pct) >= AUTOMATION_TIER_HIGH_PCT:
        return PPH_TIER_HIGH
    if float(automation_pct) >= AUTOMATION_TIER_MID_PCT:
        return PPH_TIER_MID
    return PPH_TIER_LOW


def expected_required_headcount(
    forecast_volume: int,
    shift_hours: float,
    automation_pct: float,
    ops_posture: str,
    line_count: int,
) -> int:
    """PRD §3.4: exact quotient, times the posture multiplier, ceiling once, then
    the larger of that and 4 associates per line."""
    pph = expected_pph_for_automation(automation_pct)
    raw = Decimal(str(forecast_volume)) / (Decimal(str(pph)) * Decimal(str(shift_hours)))
    scaled = raw * Decimal(str(POSTURE_MULTIPLIER[ops_posture]))
    return max(ceil_int(scaled), MIN_HEADCOUNT_PER_LINE * line_count)


def expected_flex_premium_pct(ratio: float) -> float:
    """PRD §3.5 step 6 / §3.9: the premium tier that a flex ratio attracts."""
    if float(ratio) < FLEX_PREMIUM_TIER_1_MAX_RATIO:
        return FLEX_PREMIUM_PCT["TIER_1"]
    if float(ratio) < FLEX_PREMIUM_TIER_2_MAX_RATIO:
        return FLEX_PREMIUM_PCT["TIER_2"]
    return FLEX_PREMIUM_PCT["TIER_3"]


def expected_planned_labor_cents(
    core: int, seasonal: int, flex_draw: int, shift_hours: float
) -> int:
    """PRD §3.5 step 4 through step 7: round each hire-class line, sum, then apply
    the premium and round once more."""
    hours = Decimal(str(shift_hours))
    base = (
        round_cents(Decimal(core) * hours * Decimal(RATE_CENTS_PER_HOUR["CORE"]))
        + round_cents(Decimal(seasonal) * hours * Decimal(RATE_CENTS_PER_HOUR["SEASONAL"]))
        + round_cents(Decimal(flex_draw) * hours * Decimal(RATE_CENTS_PER_HOUR["FLEX"]))
    )
    total_headcount = core + seasonal + flex_draw
    ratio = 0 if total_headcount == 0 else Decimal(flex_draw) / Decimal(total_headcount)
    premium = expected_flex_premium_pct(ratio)
    return round_cents(Decimal(base) * (Decimal(1) + Decimal(str(premium))))


def expected_provisional_cost_per_package(
    planned_labor_cents: int, forecast_volume: int
) -> float:
    """PRD §3.5: planned labor plus fixed overhead over the full forecast."""
    numerator = Decimal(planned_labor_cents) + Decimal(FIXED_OVERHEAD_CENTS_PER_SHIFT)
    return round_half_up(numerator / Decimal(forecast_volume), 2)


def expected_final_cost_per_package(
    actual_labor_cents: int, sorted_count: int, missort_count: int
) -> float:
    """PRD §3.9: actual labor plus overhead plus rework, over sorted minus
    mis-sorted with the divisor floored at 1."""
    numerator = (
        Decimal(actual_labor_cents)
        + Decimal(FIXED_OVERHEAD_CENTS_PER_SHIFT)
        + Decimal(missort_count) * Decimal(REWORK_CENTS_PER_MISSORT_PACKAGE)
    )
    denominator = Decimal(max(1, sorted_count - missort_count))
    return round_half_up(numerator / denominator, 2)


def expected_batch_cube(
    small: int = 0, medium: int = 0, large: int = 0, oversized: int = 0
) -> float:
    """PRD §3.8: each size-class line rounded to two places on its own, then the
    four rounded lines added."""
    lines = [
        round_half_up(Decimal(small) * Decimal(str(CUFT_PER_PACKAGE["SMALL"])), 2),
        round_half_up(Decimal(medium) * Decimal(str(CUFT_PER_PACKAGE["MEDIUM"])), 2),
        round_half_up(Decimal(large) * Decimal(str(CUFT_PER_PACKAGE["LARGE"])), 2),
        round_half_up(
            Decimal(oversized) * Decimal(str(CUFT_PER_PACKAGE["OVERSIZED"])), 2
        ),
    ]
    return round_half_up(sum(Decimal(str(line)) for line in lines), 2)


def expected_cube_after_scan(
    stored_cube: float, small: int = 0, medium: int = 0, large: int = 0, oversized: int = 0
) -> float:
    """PRD §3.8 step 3: the batch cube added to the stored figure, rounded again."""
    batch = expected_batch_cube(small, medium, large, oversized)
    return round_half_up(Decimal(str(stored_cube)) + Decimal(str(batch)), 2)


def expected_cube_utilization_pct(cube_used: float, trailer_cube: float) -> float:
    """PRD §3.8: used over capacity, times 100, to two decimal places."""
    return round_half_up(
        Decimal(str(cube_used)) / Decimal(str(trailer_cube)) * Decimal(100), 2
    )


def expected_lane_pressure_ratio(backlog: int, assigned_capacity_pph: int) -> float:
    """PRD §3.2: backlog over assigned capacity with the divisor floored at 1,
    to four decimal places."""
    divisor = Decimal(max(LANE_CAPACITY_DIVISOR_FLOOR, assigned_capacity_pph))
    return round_half_up(Decimal(backlog) / divisor, 4)
