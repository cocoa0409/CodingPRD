"""Entity assertions and domain invariant checkers."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import FACING_CAPACITY_LB, THRESHOLDS


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict) -> None:
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_reading_only_fields(data: dict) -> None:
    """A temperature reading carries ONLY id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "a temperature reading must not carry updated_at"
    assert "version" not in data, "a temperature reading must not carry version"


def assert_three_fractional_digits(value: str) -> None:
    """Instants render as ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert value.endswith("Z"), f"instant must be UTC and end with Z, got {value!r}"
    assert "." in value, f"instant must carry fractional digits, got {value!r}"
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3, f"instant must carry three fractional digits, got {value!r}"


def assert_two_decimal_places(value: float) -> None:
    """Pound quantities carry two decimal places (PRD §2.5)."""
    assert float(value) == round(float(value) + 0.0, 2), (
        f"{value} must carry two decimal places"
    )


def assert_four_decimal_places(value: float) -> None:
    """Per-pound cost bases and ratios carry four decimal places (PRD §2.5)."""
    assert float(value) == round(float(value) + 0.0, 4), (
        f"{value} must carry four decimal places"
    )


def assert_whole_cents(value) -> None:
    """Whole-cent integers hold no fractional part at all (PRD §2.5)."""
    assert isinstance(value, int) or float(value) == int(value), (
        f"{value} must be a whole number of cents"
    )


def assert_price_ends_in_nine(value: int) -> None:
    """A shelf price always ends in the digit 9 whenever it is greater than
    zero (PRD §2.5)."""
    if int(value) > 0:
        assert int(value) % 10 == 9, f"shelf price {value} must end in the digit 9"


def assert_date(value: str) -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"expected a YYYY-MM-DD date, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_department(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["store_code"], str) and 2 <= len(data["store_code"]) <= 16
    assert 0 <= float(data["target_margin_pct"]) <= 0.60
    assert 1 <= int(data["shelf_life_days_ground"]) <= 10
    assert 1 <= int(data["shelf_life_days_whole_muscle"]) <= 20
    assert 1 <= int(data["shelf_life_days_vac_packed"]) <= 45
    assert float(data["max_safe_case_temp_c"]) >= 0.0
    assert float(data["max_safe_case_temp_c"]) < float(data["critical_case_temp_c"])
    assert 1 <= int(data["pickup_slot_capacity"]) <= 10
    assert 0 <= int(data["grind_sanitation_buffer_min"]) <= 240
    assert 0 <= float(data["markdown_floor_pct"]) <= 0.50
    assert 0 < float(data["shrink_tolerance_pct"]) <= 0.25
    assert 0 <= float(data["deposit_rate"]) <= 1.0
    assert data["case_posture"] in ("SALES_OPEN", "SALES_RESTRICTED", "SALES_HALTED")
    for counter in (
        "open_case_failure_count",
        "contained_case_failure_count",
        "consecutive_out_of_spec_readings",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be >= 0"
    assert 0 <= int(data["consecutive_out_of_spec_readings"]) <= 2


def assert_primal_purchase(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert data["primal_code"] in (
        "BEEF_RIBEYE_LIP_ON",
        "BEEF_STRIP_LOIN",
        "PORK_LOIN_BONELESS",
        "BEEF_CHUCK_ROLL",
    )
    assert data["product_class"] in ("WHOLE_MUSCLE", "VAC_PACKED")
    assert data["country_of_origin"] in ("USA", "CAN", "MEX", "AUS")
    assert float(data["net_weight_lb"]) > 0
    assert_two_decimal_places(data["net_weight_lb"])
    assert_four_decimal_places(data["landed_cost_per_lb_cents"])
    assert data["status"] in ("RECEIVED", "CUT_TESTED", "RECONCILED")
    assert_cost_ledger_conserves(data)


def assert_cost_ledger_conserves(purchase: dict) -> None:
    """PRD §2.6: `unallocated_cost_cents` is always exactly the total minus the
    allocated amount, the residual is never negative and the allocated amount
    never exceeds the landed total."""
    total = int(purchase["landed_cost_total_cents"])
    allocated = int(purchase["allocated_cost_cents"])
    unallocated = int(purchase["unallocated_cost_cents"])
    assert allocated + unallocated == total, (
        f"ledger must conserve: {allocated} + {unallocated} != {total}"
    )
    assert unallocated >= 0, "the residual is never allowed to go negative"
    assert allocated <= total, "allocated_cost_cents never exceeds landed_cost_total_cents"


def assert_cutting_test(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["primal_purchase_id"])
    assert float(data["test_weight_lb"]) > 0
    assert 0 <= int(data["revision_count"]) <= 2
    assert_two_decimal_places(data["total_yield_weight_lb"])
    assert_two_decimal_places(data["unaccounted_lb"])
    for pct in ("salable_yield_pct", "trim_yield_pct", "loss_pct"):
        assert_four_decimal_places(data[pct])
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")


def assert_cutting_test_line(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["cutting_test_id"])
    assert 1 <= int(data["line_seq"]) <= 40
    assert data["disposition"] in ("SALABLE_CUT", "GRIND_TRIM", "FAT_BONE_LOSS")
    assert float(data["yield_weight_lb"]) >= 0
    assert int(data["market_value_per_lb_cents"]) >= 0
    if data["disposition"] == "FAT_BONE_LOSS":
        assert int(data["market_value_per_lb_cents"]) == 0, (
            "market value must be exactly 0 on a FAT_BONE_LOSS line"
        )
        assert int(data["allocated_cost_cents"]) == 0, (
            "FAT_BONE_LOSS lines keep allocated_cost_cents at 0"
        )
    else:
        assert int(data["market_value_per_lb_cents"]) > 0, (
            "market value must be strictly greater than 0 on any other line"
        )
    if data["disposition"] == "GRIND_TRIM":
        assert data.get("lean_pct") is not None, "lean_pct is required on a GRIND_TRIM line"
        assert 50.0 <= float(data["lean_pct"]) <= 99.0
    else:
        assert data.get("lean_pct") in (None, 0, 0.0), (
            "lean_pct is forbidden outside a GRIND_TRIM line"
        )
    if data["disposition"] == "SALABLE_CUT":
        assert data.get("retail_item_id"), "retail_item_id is required on a SALABLE_CUT line"
    assert_four_decimal_places(data["allocated_cost_per_lb_cents"])


def assert_retail_item(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert 2 <= len(data["item_code"]) <= 24
    assert 1 <= len(data["subprimal_code"]) <= 60
    assert data["product_class"] in ("GROUND", "WHOLE_MUSCLE", "VAC_PACKED")
    assert data["country_of_origin_label"] in (
        "PENDING",
        "USA",
        "CAN",
        "MEX",
        "AUS",
        "MULTIPLE",
    )
    expected_source = (
        "GRIND_BLEND" if data["product_class"] == "GROUND" else "CUT_TEST_LINE"
    )
    assert data["cost_basis_source"] == expected_source, (
        f"cost_basis_source for a {data['product_class']} item must be {expected_source}"
    )
    assert data["price_status"] in (
        "UNPRICED",
        "PROPOSED",
        "PRICED",
        "REPRICE_REQUIRED",
        "SUSPENDED",
    )
    assert_price_ends_in_nine(data["provisional_price_per_lb_cents"])
    assert_price_ends_in_nine(data["final_price_per_lb_cents"])
    assert_four_decimal_places(data["yield_adjusted_cost_per_lb_cents"])
    assert_four_decimal_places(data["price_variance_pct"])
    assert int(data["shelf_life_days"]) >= 0


def assert_case_plan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert_date(data["service_date"])
    assert data["plan_status"] in ("DRAFT", "PUBLISHED", "SUSPENDED", "CLOSED")
    assert data["fill_status"] in ("UNFILLED", "PARTIAL", "FILLED")
    for total in (
        "total_expected_movement_lb",
        "total_required_fill_lb",
        "total_actual_fill_lb",
    ):
        assert float(data[total]) >= 0
        assert_two_decimal_places(data[total])
    assert int(data["price_stale_line_count"]) >= 0
    assert_fill_status_follows_totals(data)


def assert_fill_status_follows_totals(plan: dict) -> None:
    """PRD §3.6: the plan moves UNFILLED -> PARTIAL while total actual pounds
    are above 0 but still below total required pounds, and PARTIAL -> FILLED
    once total actual pounds reach or exceed total required pounds."""
    actual = float(plan["total_actual_fill_lb"])
    required = float(plan["total_required_fill_lb"])
    if actual == 0:
        expected = "UNFILLED"
    elif actual < required:
        expected = "PARTIAL"
    else:
        expected = "FILLED"
    assert plan["fill_status"] == expected, (
        f"fill_status {plan['fill_status']} does not follow "
        f"{actual} actual against {required} required (expected {expected})"
    )


def assert_case_plan_line(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["case_plan_id"])
    assert is_valid_uuid(data["retail_item_id"])
    assert 1 <= int(data["line_seq"]) <= 60
    assert 1 <= int(data["facings"]) <= 12
    assert float(data["expected_movement_lb"]) > 0
    for pounds in ("required_fill_lb", "actual_fill_lb", "staged_lb", "markdown_lb", "shrink_lb"):
        assert float(data[pounds]) >= 0
        assert_two_decimal_places(data[pounds])
    assert data["line_status"] in (
        "PLANNED",
        "FILLED",
        "MARKED_DOWN",
        "HELD",
        "SHRUNK_OUT",
    )
    assert isinstance(data["price_stale"], bool)
    assert_line_pounds_available(data)


def assert_line_pounds_available(line: dict) -> None:
    """PRD §2.11 rung 39: `markdown_lb`, `shrink_lb` and staged pounds together
    never exceed `actual_fill_lb`."""
    encumbered = float(line["markdown_lb"]) + float(line["shrink_lb"]) + float(line["staged_lb"])
    assert round(encumbered, 2) <= round(float(line["actual_fill_lb"]), 2) + 1e-9, (
        f"encumbered pounds {encumbered} exceed actual_fill_lb {line['actual_fill_lb']}"
    )


def assert_trim_lot(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert 2 <= len(data["lot_code"]) <= 24
    assert float(data["received_lb"]) > 0
    assert 0 <= int(data["rework_generation"]) <= THRESHOLDS["REGRIND_GENERATION_LIMIT"]
    assert data["status"] in (
        "AVAILABLE",
        "PARTIALLY_COMMITTED",
        "FULLY_COMMITTED",
        "CONSUMED",
        "DISCARDED",
    )
    assert_four_decimal_places(data["cost_per_lb_cents"])
    assert_trim_lot_buckets_conserve(data)


def assert_trim_lot_buckets_conserve(lot: dict) -> None:
    """PRD §3.5: `received_lb` always equals `allocated_lb` plus `consumed_lb`
    plus `discarded_lb` plus `remaining_lb`."""
    total = round(
        float(lot["allocated_lb"])
        + float(lot["consumed_lb"])
        + float(lot["discarded_lb"])
        + float(lot["remaining_lb"]),
        2,
    )
    assert total == round(float(lot["received_lb"]), 2), (
        f"trim lot buckets must conserve: {total} != {lot['received_lb']}"
    )


def assert_grind_run(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert is_valid_uuid(data["target_retail_item_id"])
    assert data["scheduled_end_at"] > data["scheduled_start_at"]
    assert data["declared_coo"] in ("USA", "CAN", "MEX", "AUS", "MULTIPLE")
    assert 60.0 <= float(data["target_lean_pct"]) <= 95.0
    assert 0.0 < float(data["lean_tolerance_pct"]) <= 10.0
    assert float(data["batch_weight_lb"]) >= 0
    assert_two_decimal_places(data["batch_weight_lb"])
    assert_four_decimal_places(data["blend_cost_per_lb_cents"])
    assert data["coo_label"] in ("PENDING", "USA", "CAN", "MEX", "AUS", "MULTIPLE")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")


def assert_grind_input(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["grind_run_id"])
    assert is_valid_uuid(data["trim_lot_id"])
    assert 1 <= int(data["input_seq"]) <= 20
    assert float(data["weight_lb"]) > 0
    assert isinstance(data["consumed"], bool)


def assert_temperature_log(data: dict) -> None:
    assert_reading_only_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert 1 <= len(data["case_code"]) <= 24
    assert -10.0 <= float(data["reading_c"]) <= 15.0
    assert isinstance(data["out_of_spec"], bool)
    assert 0 <= int(data["consecutive_index"]) <= THRESHOLDS["CONSECUTIVE_FAILURE_THRESHOLD"]


def assert_case_failure(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert is_valid_uuid(data["trigger_temperature_log_id"])
    assert data["status"] in ("OPEN", "CONTAINED", "ESCALATED", "RESOLVED")
    assert data["disposition"] in ("NONE", "MARKDOWN", "DISCARD")
    assert int(data["reopen_count"]) >= 0
    assert int(data["affected_line_count"]) >= 0


def assert_pre_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert is_valid_uuid(data["retail_item_id"])
    assert 1 <= len(data["customer_name"]) <= 120
    assert 7 <= len(data["customer_phone"]) <= 20
    assert float(data["requested_weight_lb"]) > 0
    assert data["pickup_window_end_at"] > data["pickup_window_start_at"]
    assert 0 <= int(data["amend_count"]) <= THRESHOLDS["AMEND_LIMIT"]
    assert data["status"] in (
        "REQUESTED",
        "CONFIRMED",
        "STAGED",
        "HELD",
        "PICKED_UP",
        "CANCELLED",
        "FORFEITED",
    )


def assert_deposit_identity(order: dict) -> None:
    """PRD §2.6: once a pre-order has reached a terminal state, `deposit_cents`
    equals `deposit_applied_cents` plus `deposit_refund_cents` plus
    `deposit_forfeited_cents`."""
    parts = (
        int(order["deposit_applied_cents"])
        + int(order["deposit_refund_cents"])
        + int(order["deposit_forfeited_cents"])
    )
    assert parts == int(order["deposit_cents"]), (
        f"deposit identity broken: {parts} != {order['deposit_cents']}"
    )


def assert_shrink_reconciliation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["department_id"])
    assert_date(data["period_start_date"])
    assert_date(data["period_end_date"])
    assert data["period_end_date"] >= data["period_start_date"]
    assert data["basis"] in ("YIELD_MODEL", "PHYSICAL_COUNT")
    assert_two_decimal_places(data["expected_salable_lb"])
    assert_two_decimal_places(data["physical_salable_lb"])
    assert_two_decimal_places(data["variance_lb"])
    assert_four_decimal_places(data["variance_pct"])
    assert isinstance(data["within_tolerance"], bool)
    assert data["status"] in ("DRAFT", "POSTED", "DISPUTED")
    assert round(
        float(data["physical_salable_lb"]) - float(data["expected_salable_lb"]), 2
    ) == round(float(data["variance_lb"]), 2)


# ---------------------------------------------------------------------------
# Derivation helpers — recompute a PRD formula so a test can state the rule
# rather than only the literal it produces.
# ---------------------------------------------------------------------------

def expected_required_fill_lb(
    facings: int,
    product_class: str,
    expected_movement_lb: float,
    shelf_life_days: int,
    posture: str = "SALES_OPEN",
) -> float:
    """PRD §3.6: the base is the larger of the presentation pounds and the
    smaller of the demand pounds and the carrying-capacity pounds."""
    presentation = facings * FACING_CAPACITY_LB[product_class]
    demand = expected_movement_lb * THRESHOLDS["DEMAND_UPLIFT"]
    carry = expected_movement_lb * shelf_life_days * THRESHOLDS["CARRY_CAP_FACTOR"]
    base = max(presentation, min(demand, carry))
    rounded = _round_half_up(base, 2)
    if posture == "SALES_RESTRICTED":
        return _round_half_up(rounded * THRESHOLDS["POSTURE_RESTRICTED_HAIRCUT"], 2)
    return rounded


def expected_shelf_price_cents(cost_basis_cents: float, base_margin: float) -> int:
    """PRD §3.4: one pass over the tier table, then the nudge up to the next
    whole-cent value whose last digit is 9."""
    first_pass = _round_half_up(cost_basis_cents / (1 - base_margin), 0)
    if first_pass < THRESHOLDS["TIER_1_CEILING_CENTS"]:
        bump = THRESHOLDS["TIER_1_BUMP"]
    elif first_pass < THRESHOLDS["TIER_2_CEILING_CENTS"]:
        bump = THRESHOLDS["TIER_2_BUMP"]
    else:
        bump = THRESHOLDS["TIER_3_BUMP"]
    effective = min(base_margin + bump, THRESHOLDS["EFFECTIVE_MARGIN_CAP"])
    second_pass = int(_round_half_up(cost_basis_cents / (1 - effective), 0))
    return _nudge_to_nine(second_pass)


def _nudge_to_nine(value: int) -> int:
    """Advance upward to the nearest whole-cent value whose last digit is 9."""
    if value % 10 == 9:
        return value
    return value + ((9 - value % 10) % 10)


def _round_half_up(value: float, places: int) -> float:
    from decimal import ROUND_HALF_UP, Decimal

    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))


def expected_deposit_cents(
    quoted_price_per_lb_cents: int, requested_weight_lb: float, deposit_rate: float
) -> int:
    """PRD §3.8: the deposit is rounded **up** to the next whole cent."""
    from decimal import ROUND_CEILING, Decimal

    exact = (
        Decimal(str(quoted_price_per_lb_cents))
        * Decimal(str(requested_weight_lb))
        * Decimal(str(deposit_rate))
    )
    return int(exact.quantize(Decimal(1), rounding=ROUND_CEILING))


def expected_markdown_floor_cents(
    yield_adjusted_cost_per_lb_cents: float, markdown_floor_pct: float
) -> int:
    """PRD §3.6: the floor in cents is the item's yield-adjusted cost per pound
    multiplied by one plus the department's markdown floor percentage."""
    return int(
        _round_half_up(yield_adjusted_cost_per_lb_cents * (1 + markdown_floor_pct), 0)
    )


def assert_posture(department: dict, expected: str, note: Optional[str] = None) -> None:
    assert department["case_posture"] == expected, (
        f"expected posture {expected}, got {department['case_posture']}"
        + (f" ({note})" if note else "")
    )
