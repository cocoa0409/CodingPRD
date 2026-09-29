"""Boundary behaviour of the charge formula, the cube rounding order and the
density bracket table.

These three mechanics all sit on inclusive thresholds, so a single pound or a
single hundredth of a pound per cubic foot changes the answer.
"""

from test_helpers import (
    assert_capture_event,
    assert_correction_notice,
    assert_shipment,
    assert_shipment_line,
)
from test_helpers import fixtures as fx

CLOCK = "2026-01-10T08:00:00Z"


def _weight_break_env():
    return fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={"code": "TRM1", "name": "Chicago Dock"},
        customer_overrides={"account_code": "BREAK", "name": "Breakpoint Logistics"},
    )


def _weight_break_line(declared_weight_lb):
    return {
        "line_no": 1,
        "declared_class_code": 100,
        "declared_weight_lb": declared_weight_lb,
        "pieces": 5,
        "declared_length_in": 48.0,
        "declared_width_in": 40.0,
        "declared_height_in": 48.0,
    }


def _edge_env():
    return fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={"code": "TRM1", "name": "Chicago Dock"},
        customer_overrides={"account_code": "EDGE", "name": "Edge Freight"},
        profile_overrides={"nmfc_item": "049880", "description": "Assorted hardware"},
    )


def _edge_line(declared_weight_lb):
    return {
        "line_no": 1,
        "declared_class_code": 85,
        "declared_weight_lb": declared_weight_lb,
        "pieces": 3,
        "declared_length_in": 48.0,
        "declared_width_in": 40.0,
        "declared_height_in": 36.0,
    }


# ==========================================================================
# The 2,000-pound weight break
# ==========================================================================


def test_two_thousand_pound_shipment_bills_at_the_0_88_weight_break():
    """A 2,000-pound aggregate rating weight takes the 0.88 factor.

    PRD: "The five factors are declared in descending threshold order: 0.78 from
    5,000 pounds, 0.88 from 2,000 pounds, 1.00 from 1,000 pounds, 1.15 from 500
    pounds and 1.30 from nothing at all; the factor used is that of the first
    element whose threshold is less than or equal to the shipment rating weight."

    Design: Difficulty/boundary_precision_check/weight_break_boundary_2000_versus_1999_pounds
    """
    env = _weight_break_env()
    tendered = fx.setup_shipment_with_lines(
        env, "PRO9301", line_specs=[_weight_break_line(2000)],
        bol_declared_total_weight_lb=2000,
    )

    billed = fx.bill_shipment(tendered["shipment_id"])

    assert_shipment(billed)
    assert billed["declared_total_weight_lb"] == 2000, (
        "declared_total_weight_lb is the sum of declared_weight_lb across all lines"
    )
    assert billed["original_charge_cents"] == 48048, (
        f"2,000 pounds at class 100 under the 0.88 factor bills 48048, "
        f"got {billed['original_charge_cents']}"
    )
    assert billed["assessed_total_cents"] == 48048
    assert billed["billing_status"] == "BILLED"


def test_one_pound_lighter_shipment_bills_more_at_the_1_00_weight_break():
    """1,999 pounds misses the 2,000-pound threshold and costs more than 2,000.

    PRD: "the factor used is that of the first element whose threshold is less
    than or equal to the shipment rating weight."

    Design: Difficulty/boundary_precision_check/weight_break_boundary_2000_versus_1999_pounds
    """
    env = _weight_break_env()
    heavy = fx.setup_shipment_with_lines(
        env, "PRO9301", line_specs=[_weight_break_line(2000)],
        bol_declared_total_weight_lb=2000,
    )
    light = fx.setup_shipment_with_lines(
        env, "PRO9302", line_specs=[_weight_break_line(1999)],
        bol_declared_total_weight_lb=1999,
    )

    billed_heavy = fx.bill_shipment(heavy["shipment_id"])
    billed_light = fx.bill_shipment(light["shipment_id"])

    assert billed_light["declared_total_weight_lb"] == 1999
    assert billed_light["original_charge_cents"] == 54573, (
        f"1,999 pounds falls to the 1.00 factor and bills 54573, "
        f"got {billed_light['original_charge_cents']}"
    )
    assert billed_light["assessed_total_cents"] == 54573
    assert (
        billed_heavy["original_charge_cents"] - billed_light["original_charge_cents"]
        == -6525
    ), "the heavier shipment must bill 6525 cents less than the lighter one"
    assert billed_heavy["billing_status"] == "BILLED"
    assert billed_light["billing_status"] == "BILLED"


def test_declared_cube_is_unchanged_across_the_weight_break_boundary():
    """Only the weight moves across the break; the cube of both lines is equal.

    PRD: "The volume of one handling unit is length multiplied by width
    multiplied by height, divided by 1,728 cubic inches per cubic foot, and
    rounded to three decimal places. That per-unit figure is then multiplied by
    the piece count and rounded to two decimal places, which gives
    `declared_cubic_ft`."

    Design: Difficulty/boundary_precision_check/weight_break_boundary_2000_versus_1999_pounds
    """
    env = _weight_break_env()
    heavy = fx.setup_shipment_with_lines(
        env, "PRO9301", line_specs=[_weight_break_line(2000)],
        bol_declared_total_weight_lb=2000,
    )
    light = fx.setup_shipment_with_lines(
        env, "PRO9302", line_specs=[_weight_break_line(1999)],
        bol_declared_total_weight_lb=1999,
    )

    line_heavy = heavy["lines"][0]
    line_light = light["lines"][0]

    assert_shipment_line(line_heavy)
    assert_shipment_line(line_light)
    assert line_heavy["declared_cubic_ft"] == 266.67, (
        f"five 48.0 x 40.0 x 48.0 units cube to 266.67, got {line_heavy['declared_cubic_ft']}"
    )
    assert line_light["declared_cubic_ft"] == 266.67


# ==========================================================================
# The inclusive 15.00 pcf density bracket edge
# ==========================================================================


def test_density_exactly_on_the_break_takes_the_denser_lower_class_bracket():
    """A measured 15.00 pcf lands on the break and reclasses down to class 70.

    PRD: "The lower bound is inclusive, which means a density landing exactly on
    a break belongs to the denser, lower-class bracket rather than to the one
    below it."

    Design: Difficulty/boundary_precision_check/density_bracket_boundary_15_00_versus_14_99
    """
    env = _edge_env()
    scenario = fx.setup_billed_shipment(
        env=env, pro_number="PRO9201", line_specs=[_edge_line(1800)],
        shipment_overrides={"bol_declared_total_weight_lb": 1800},
    )
    assert scenario["shipment"]["original_charge_cents"] == 41769

    capture = fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1800,
        fx.single_line_measurement(
            1800, measured_length_in=48.0, measured_width_in=40.0, measured_height_in=36.0
        ),
    )
    line = fx.get_shipment_line(scenario["line_ids"][0])

    assert_capture_event(capture)
    assert_shipment_line(line)
    assert line["measured_cubic_ft"] == 120.00, (
        f"three 48.0 x 40.0 x 36.0 units cube to 120.00, got {line['measured_cubic_ft']}"
    )
    assert line["measured_density_pcf"] == 15.00, (
        f"1800 pounds over 120.00 cubic feet is 15.00 pcf, got {line['measured_density_pcf']}"
    )
    assert line["found_class_code"] == 70, (
        f"15.00 pcf belongs to the 15 break and its class 70, got {line['found_class_code']}"
    )
    assert capture["variance_pct"] == 0.00
    assert capture["triggered_reweigh"] is False
    assert capture["triggered_reclass"] is True
    assert capture["reclassed_line_count"] == 1


def test_density_one_hundredth_below_the_break_keeps_the_declared_class():
    """A measured 14.99 pcf misses the break, holds class 85 and raises no notice.

    PRD: "When neither a reweigh condition nor a class delta results, a first
    capture advances `class_status` `DECLARED → CAPTURED`, and a later capture
    holds `CAPTURED → CAPTURED` while overwriting the measured fields with the
    newer capture's values"

    Design: Difficulty/boundary_precision_check/density_bracket_boundary_15_00_versus_14_99
    """
    env = _edge_env()
    scenario = fx.setup_billed_shipment(
        env=env, pro_number="PRO9202", line_specs=[_edge_line(1799)],
        shipment_overrides={"bol_declared_total_weight_lb": 1799},
    )
    assert scenario["shipment"]["original_charge_cents"] == 41746

    capture = fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1799,
        fx.single_line_measurement(
            1799, measured_length_in=48.0, measured_width_in=40.0, measured_height_in=36.0
        ),
    )
    line = fx.get_shipment_line(scenario["line_ids"][0])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert line["measured_cubic_ft"] == 120.00
    assert line["measured_density_pcf"] == 14.99, (
        f"1799 pounds over 120.00 cubic feet is 14.99 pcf, got {line['measured_density_pcf']}"
    )
    assert line["found_class_code"] == 85, (
        f"14.99 pcf falls into the 13.5 break and its class 85, got {line['found_class_code']}"
    )
    assert capture["triggered_reclass"] is False
    assert capture["reclassed_line_count"] == 0
    assert shipment["class_status"] == "CAPTURED"
    assert shipment["open_notice_count"] == 0
    assert fx.list_notices_for(scenario["shipment_id"]) == [], (
        "a capture with no reweigh condition and no class delta opens no notice"
    )


def test_reclass_down_from_the_declared_class_produces_a_negative_final_delta():
    """Reclassing down from class 85 to class 70 makes `final_delta_cents` negative.

    PRD: "`final_delta_cents` is the audit-final figure that will actually be
    billed. It is the shipment charge on the reclassed basis minus the shipment
    charge on the declared basis"

    Design: Difficulty/boundary_precision_check/density_bracket_boundary_15_00_versus_14_99
    """
    env = _edge_env()
    scenario = fx.setup_billed_shipment(
        env=env, pro_number="PRO9201", line_specs=[_edge_line(1800)],
        shipment_overrides={"bol_declared_total_weight_lb": 1800},
    )
    fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        1800,
        fx.single_line_measurement(
            1800, measured_length_in=48.0, measured_width_in=40.0, measured_height_in=36.0
        ),
    )

    notice = fx.find_draft_notice(scenario["shipment_id"])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert_correction_notice(notice)
    assert notice["notice_type"] == "RECLASS", (
        f"only a class delta held, so the notice_type is RECLASS, got {notice['notice_type']}"
    )
    assert notice["final_delta_cents"] == -7371, (
        f"the reclassed leg is cheaper than the declared leg by 7371 cents, "
        f"got {notice['final_delta_cents']}"
    )
    assert shipment["open_notice_count"] == 1


# ==========================================================================
# The two-step cube rounding order
# ==========================================================================


def test_per_unit_cube_rounding_before_multiplying_lands_at_29_99_pcf():
    """Rounding each handling unit to three places first gives 101.86 cubic feet.

    PRD: "The volume of a single handling unit is rounded to three decimal places
    first; only then is it multiplied by the piece count, and that product is
    rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/cube_rounding_order_flips_density_bracket_and_fires_notice
    """
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={"code": "TRM1", "name": "Chicago Dock"},
        customer_overrides={"account_code": "BOLT", "name": "Bolt Supply"},
        profile_overrides={"nmfc_item": "049880", "description": "Fasteners in cartons"},
    )
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PRO3001",
        line_specs=[
            {
                "line_no": 1,
                "declared_class_code": 60,
                "declared_weight_lb": 3055,
                "pieces": 22,
                "declared_length_in": 20.0,
                "declared_width_in": 20.0,
                "declared_height_in": 20.0,
            }
        ],
        shipment_overrides={"bol_declared_total_weight_lb": 3055},
    )
    assert scenario["shipment"]["original_charge_cents"] == 44036

    capture = fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        3055,
        fx.single_line_measurement(
            3055, measured_length_in=20.0, measured_width_in=20.0, measured_height_in=20.0
        ),
        device_type="DIMENSIONER",
    )
    line = fx.get_shipment_line(scenario["line_ids"][0])

    assert line["measured_cubic_ft"] == 101.86, (
        f"22 units of 4.630 cubic feet each cube to 101.86, got {line['measured_cubic_ft']}"
    )
    assert line["measured_density_pcf"] == 29.99, (
        f"3055 pounds over 101.86 cubic feet is 29.99 pcf, got {line['measured_density_pcf']}"
    )
    assert line["found_class_code"] == 65, (
        f"29.99 pcf misses the 30 break and takes class 65, got {line['found_class_code']}"
    )
    assert line["effective_class_code"] == 65
    assert capture["variance_pct"] == 0.00
    assert capture["triggered_reweigh"] is False
    assert capture["triggered_reclass"] is True


def test_cube_rounding_order_raises_a_reclass_notice_and_the_assessed_total():
    """The 29.99 pcf result differs from declared class 60, so a notice is raised
    and issuing it lifts `assessed_total_cents`.

    PRD: "Its `triggered_reclass` flag is true when at least one line of the
    shipment ends up with a `found_class_code` differing from its
    `declared_class_code` after the capture is applied, and `reclassed_line_count`
    is how many such lines there are."

    Design: Difficulty/combinatorial_formula/cube_rounding_order_flips_density_bracket_and_fires_notice
    """
    env = fx.setup_pricing_environment(
        clock=CLOCK,
        terminal_overrides={"code": "TRM1", "name": "Chicago Dock"},
        customer_overrides={"account_code": "BOLT", "name": "Bolt Supply"},
        profile_overrides={"nmfc_item": "049880", "description": "Fasteners in cartons"},
    )
    scenario = fx.setup_billed_shipment(
        env=env,
        pro_number="PRO3001",
        line_specs=[
            {
                "line_no": 1,
                "declared_class_code": 60,
                "declared_weight_lb": 3055,
                "pieces": 22,
                "declared_length_in": 20.0,
                "declared_width_in": 20.0,
                "declared_height_in": 20.0,
            }
        ],
        shipment_overrides={"bol_declared_total_weight_lb": 3055},
    )
    fx.record_capture(
        scenario["shipment_id"],
        scenario["terminal_id"],
        3055,
        fx.single_line_measurement(
            3055, measured_length_in=20.0, measured_width_in=20.0, measured_height_in=20.0
        ),
        device_type="DIMENSIONER",
    )
    draft = fx.find_draft_notice(scenario["shipment_id"])
    assert draft["notice_type"] == "RECLASS"
    assert draft["final_delta_cents"] == 3670

    issued = fx.issue_notice(draft["id"])
    shipment = fx.get_shipment(scenario["shipment_id"])

    assert issued["applied_delta_cents"] == 3670, (
        f"applied_delta_cents freezes equal to final_delta_cents, "
        f"got {issued['applied_delta_cents']}"
    )
    assert issued["inspection_fee_cents"] == 4500, (
        f"a RECLASS notice freezes a $45.00 inspection fee, got {issued['inspection_fee_cents']}"
    )
    assert shipment["assessed_total_cents"] == 52206, (
        f"44036 plus 3670 plus 4500 is 52206, got {shipment['assessed_total_cents']}"
    )
