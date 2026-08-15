"""Work-order sizing and the dual cost variants: forward-looking estimate at
dispatch, chronological actual at completion, rounding order, and variance."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_work_order,
    complete_work_order,
    create_crew,
    make_crew_lead_headers,
    setup_confirmed_break,
    setup_dispatched_work_order,
    setup_isolated_break,
    setup_on_site_work_order,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _api
from test_helpers import create_work_order_payload

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty: wo_estimate_vs_actual_cost_diverge (2 tests)
# ---------------------------------------------------------------------------

def _oak_split_dispatched():
    """Segment diameter 10, SPLIT break isolated, LIGHT crew rate 9000,
    work order est_pipe_length_ft=12 dispatched."""
    return setup_dispatched_work_order(
        segment_ref="MAIN-10-OAK", diameter_inches=10, install_year=1985,
        break_type="SPLIT", severity="HIGH",
        location_description="1200 Oak St",
        crew_name="Crew Alpha", crew_size=4, crew_rate=9000,
        est_pipe_length_ft=12,
    )


def test_estimate_variant_uses_forward_looking_formula(api):
    """PRD §3.4: "Dispatch also computes `estimated_cost_cents`, the
    forward-looking cost variant: take the `est_pipe_length_ft`, multiply it by
    a per-foot rate of 12000 cents when the diameter is less than 8 inches,
    18000 cents when the diameter is from 8 up to and including 16 inches, or
    25000 cents when greater than 16, then multiply that product by a
    break-type multiplier of 1.0 for `CIRCUMFERENTIAL`, 1.25 for `SPLIT`, or
    1.6 for `BLOWOUT`, and round the result half-up to whole cents; add a
    clamp-kit fee of 40000 cents for `CIRCUMFERENTIAL`, 85000 for `SPLIT`, or
    150000 for `BLOWOUT`; and add the assigned crew's `hourly_rate_cents`
    multiplied by the estimated hours from the break-type table above."

    Design: Difficulty/dual_variant_calc/wo_estimate_vs_actual_cost_diverge
    """
    ctx = _oak_split_dispatched()
    wo = ctx["work_order"]
    # round(12 * 18000 * 1.25) = 270000; kit 85000; crew 9000 * 6h = 54000
    assert wo["estimated_cost_cents"] == 409000, (
        f"forward-looking estimate must be 409000, got {wo['estimated_cost_cents']}"
    )


def test_actual_variant_and_variance_diverge_from_estimate(api):
    """PRD §3.4: "The chronological actual-cost variant computes
    `actual_cost_cents` as follows: labor is `labor_hours` multiplied by the
    crew's `hourly_rate_cents`, rounded half-up to whole cents; each materials
    line is rounded individually before any summing, as `quantity` times
    `unit_price_cents` times a waste factor of 1.10, rounded half-up per line;
    and the total is the rounded labor plus the sum of the individually rounded
    lines."
    PRD §3.4: "`cost_variance_cents` is then set to `actual_cost_cents` minus
    `estimated_cost_cents`."

    Design: Difficulty/dual_variant_calc/wo_estimate_vs_actual_cost_diverge
    """
    ctx = _oak_split_dispatched()
    wo, crew = ctx["work_order"], ctx["crew"]
    get_success = validate_success(
        _api.arrive_work_order(wo["id"], make_crew_lead_headers(crew["id"])), 200
    )
    assert get_success["work_status"] == "ON_SITE"
    done = complete_work_order(
        wo["id"], crew["id"],
        actual_pipe_length_ft=10, labor_hours=5.5,
        materials_used=[{"item_code": "PIPE-10IN", "quantity": 2,
                         "unit_price_cents": 40000}],
    )
    # labor round(5.5*9000)=49500; line round(2*40000*1.10)=88000
    assert done["actual_cost_cents"] == 137500, (
        f"chronological actual must be 137500, got {done['actual_cost_cents']}"
    )
    assert done["cost_variance_cents"] == 137500 - 409000, (
        f"variance must be actual - estimated = -271500, got {done['cost_variance_cents']}"
    )
    assert done["actual_cost_cents"] != done["estimated_cost_cents"], (
        "the two cost variants must diverge for this fixture"
    )


# ---------------------------------------------------------------------------
# Difficulty: blowout_large_diameter_estimate_combinatorial (2 tests)
# ---------------------------------------------------------------------------

def _maple_blowout_created():
    """Diameter-20 segment, BLOWOUT break isolated, HEAVY crew rate 12000,
    work order est length 8 created (not yet dispatched)."""
    ctx = setup_isolated_break(
        segment_ref="MAIN-20-MAPLE", material="CAST_IRON", diameter_inches=20,
        install_year=1955, break_type="BLOWOUT", severity="HIGH",
        location_description="77 Maple Ave", source="SENSOR_SCADA",
    )
    crew = create_crew(crew_name="Crew Heavy", crew_size=6,
                       equipment_class="HEAVY", hourly_rate_cents=12000)
    wo = validate_success(
        _api.create_work_order(
            create_work_order_payload(
                break_report_id=ctx["break"]["id"], est_pipe_length_ft=8
            ),
            DISPATCHER,
        ),
        201,
    )
    ctx.update({"crew": crew, "work_order": wo})
    return ctx


def test_blowout_large_diameter_material_sizing(api):
    """PRD §3.4: "The required equipment class is `HEAVY` when the segment's
    `diameter_inches` is greater than 12 or the break's `break_type` is
    `BLOWOUT`, and `LIGHT` otherwise; this is recorded on the work order as
    `required_equipment_class`. The clamp kit is tiered by diameter: `CLAMP_A`
    when `diameter_inches` is less than 8, `CLAMP_B` when it is from 8 up to
    and including 16, and `CLAMP_C` when it is greater than 16 — recorded as
    `required_clamp_kit`."

    Design: Difficulty/combinatorial_formula/blowout_large_diameter_estimate_combinatorial
    """
    ctx = _maple_blowout_created()
    wo = ctx["work_order"]
    assert wo["required_equipment_class"] == "HEAVY", (
        f"diameter 20 > 12 (and BLOWOUT) requires HEAVY, got {wo['required_equipment_class']!r}"
    )
    assert wo["required_clamp_kit"] == "CLAMP_C", (
        f"diameter 20 > 16 requires CLAMP_C, got {wo['required_clamp_kit']!r}"
    )


def test_blowout_large_diameter_estimate_combines_all_branches(api):
    """PRD §3.4: "Dispatch also computes `estimated_cost_cents`, the
    forward-looking cost variant: take the `est_pipe_length_ft`, multiply it by
    a per-foot rate of 12000 cents when the diameter is less than 8 inches,
    18000 cents when the diameter is from 8 up to and including 16 inches, or
    25000 cents when greater than 16, then multiply that product by a
    break-type multiplier of 1.0 for `CIRCUMFERENTIAL`, 1.25 for `SPLIT`, or
    1.6 for `BLOWOUT`, and round the result half-up to whole cents; add a
    clamp-kit fee of 40000 cents for `CIRCUMFERENTIAL`, 85000 for `SPLIT`, or
    150000 for `BLOWOUT`; and add the assigned crew's `hourly_rate_cents`
    multiplied by the estimated hours from the break-type table above."

    Design: Difficulty/combinatorial_formula/blowout_large_diameter_estimate_combinatorial
    """
    ctx = _maple_blowout_created()
    wo, crew = ctx["work_order"], ctx["crew"]
    resp = _api.dispatch_work_order(wo["id"], {"crew_id": crew["id"]}, DISPATCHER)
    dispatched = validate_success(resp, 200)
    # round(8 * 25000 * 1.6) = 320000; kit 150000; crew 12000 * 10h = 120000
    assert dispatched["estimated_cost_cents"] == 590000, (
        f"combinatorial estimate must be 590000, got {dispatched['estimated_cost_cents']}"
    )


# ---------------------------------------------------------------------------
# Difficulty: per_line_rounding_order_actual_cost (2 tests)
# ---------------------------------------------------------------------------

def _pine_on_site():
    """Diameter-6 segment, CIRCUMFERENTIAL break isolated, LIGHT crew rate 6000,
    work order est length 4 dispatched and arrived."""
    return setup_on_site_work_order(
        segment_ref="MAIN-6-PINE", material="PVC", diameter_inches=6,
        install_year=2001, break_type="CIRCUMFERENTIAL", severity="LOW",
        location_description="9 Pine Ct",
        crew_name="Crew Pine", crew_size=2, crew_rate=6000,
        est_pipe_length_ft=4,
    )


def test_actual_cost_rounds_each_materials_line_before_summing(api):
    """PRD §3.4: "each materials line is rounded individually before any
    summing, as `quantity` times `unit_price_cents` times a waste factor of
    1.10, rounded half-up per line; and the total is the rounded labor plus the
    sum of the individually rounded lines."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_actual_cost
    """
    ctx = _pine_on_site()
    wo, crew = ctx["work_order"], ctx["crew"]
    lines = [{"item_code": "BOLT-KIT", "quantity": 1, "unit_price_cents": 333}
             for _ in range(3)]
    done = complete_work_order(
        wo["id"], crew["id"], actual_pipe_length_ft=4, labor_hours=1,
        materials_used=lines,
    )
    # labor round(1*6000)=6000; each line round(1*333*1.10)=366; 3*366=1098
    assert done["actual_cost_cents"] == 7098, (
        f"per-line rounding must yield 7098, got {done['actual_cost_cents']}"
    )


def test_actual_cost_rejects_sum_then_round_alternative(api):
    """PRD §3.4: "(Summing raw line values and rounding once at the end is a
    different formula and yields different cents; the per-line order is the
    pinned one.)"
    PRD §2.8: "the chronological actual-cost calculation rounds each materials
    line individually before summing (see §3.4 and §3.6)."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_actual_cost
    """
    ctx = _pine_on_site()
    wo, crew = ctx["work_order"], ctx["crew"]
    lines = [{"item_code": "BOLT-KIT", "quantity": 1, "unit_price_cents": 333}
             for _ in range(3)]
    done = complete_work_order(
        wo["id"], crew["id"], actual_pipe_length_ft=4, labor_hours=1,
        materials_used=lines,
    )
    # Sum-then-round alternative: 6000 + round(999*1.10)=1099 -> 7099.
    assert done["actual_cost_cents"] != 7099, (
        "sum-then-round would yield 7099; the pinned per-line order yields 7098"
    )
    assert done["actual_cost_cents"] == 7098


# ---------------------------------------------------------------------------
# Corner: dispatch_response_immediately_consistent
# ---------------------------------------------------------------------------

def test_dispatch_response_immediately_consistent(api):
    """PRD §3.4: "A successful dispatch moves the work order from `DRAFT` to
    `DISPATCHED`, assigns `crew_id`, flips the crew to `DISPATCHED`, stamps
    `dispatch_window_start` with the clock now, and sets `dispatch_window_end`
    to the start plus an estimated duration of 4 hours for a `CIRCUMFERENTIAL`
    break, 6 hours for a `SPLIT`, or 10 hours for a `BLOWOUT`."
    PRD §3.4: "Dispatch also computes `estimated_cost_cents`, the
    forward-looking cost variant: take the `est_pipe_length_ft`, multiply it by
    a per-foot rate of 12000 cents when the diameter is less than 8 inches …"

    Design: Corner/consistency_model/dispatch_response_immediately_consistent
    """
    ctx = setup_isolated_break(
        segment_ref="MAIN-6-PINE", material="PVC", diameter_inches=6,
        install_year=2001, break_type="CIRCUMFERENTIAL", severity="LOW",
        location_description="9 Pine Ct",
    )
    crew = create_crew(crew_name="Crew Pine", crew_size=2,
                        equipment_class="LIGHT", hourly_rate_cents=6000)
    wo = validate_success(
        _api.create_work_order(
            create_work_order_payload(
                break_report_id=ctx["break"]["id"], est_pipe_length_ft=4
            ),
            DISPATCHER,
        ),
        201,
    )
    resp = _api.dispatch_work_order(wo["id"], {"crew_id": crew["id"]}, DISPATCHER)
    dispatched = validate_success(resp, 200)
    assert_work_order(dispatched)
    assert dispatched["work_status"] == "DISPATCHED"
    assert dispatched["crew_id"] == crew["id"]
    # 4 ft * 12000 * 1.0 = 48000; kit 40000; 6000 * 4h = 24000 -> 112000
    assert dispatched["estimated_cost_cents"] == 112000, (
        f"dispatch response must carry estimated_cost_cents 112000 with no "
        f"follow-up GET, got {dispatched['estimated_cost_cents']}"
    )


# ---------------------------------------------------------------------------
# Corner: duplicate_active_work_order_rejected
# ---------------------------------------------------------------------------

def test_duplicate_active_work_order_rejected(api):
    """PRD §3.4: "a break may have at most one work order in any of `DRAFT`,
    `DISPATCHED`, or `ON_SITE` at a time; a second attempt is rejected with
    `ERR_DUPLICATE_ACTIVE_WORK_ORDER`."
    PRD §3.4: "A `Dispatcher` may cancel a work order from `DRAFT` or from
    `DISPATCHED`."

    Design: Corner/validations/duplicate_active_work_order_rejected
    """
    ctx = setup_confirmed_break(break_type="SPLIT", severity="LOW")
    br = ctx["break"]
    w1 = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br["id"], est_pipe_length_ft=6),
            DISPATCHER,
        ),
        201,
    )
    assert w1["work_status"] == "DRAFT"

    resp = _api.create_work_order(
        create_work_order_payload(break_report_id=br["id"], est_pipe_length_ft=8),
        DISPATCHER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_WORK_ORDER)

    cancel = validate_success(_api.cancel_work_order(w1["id"], DISPATCHER), 200)
    assert cancel["work_status"] == "CANCELLED"

    w2 = validate_success(
        _api.create_work_order(
            create_work_order_payload(break_report_id=br["id"], est_pipe_length_ft=8),
            DISPATCHER,
        ),
        201,
    )
    assert w2["work_status"] == "DRAFT", (
        "after cancelling W1 a new work order must be accepted"
    )
