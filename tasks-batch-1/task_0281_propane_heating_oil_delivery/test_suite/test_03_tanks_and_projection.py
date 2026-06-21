"""Tank consumption projection, the two independent tank state dimensions, and
automatic replenishment.

Translates queue A (Difficulty) rules dual_variant_calc, non_linear_state_machine
(tank dimensions), and boundary_precision_check (reorder threshold), plus queue B
(Corner) instances from `calculations`, `validations`, and
`cross_cutting_complexity_layers` (derived-field reconciliation).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_tank_payload,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]
DRIVER = TEST_USERS["driver_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — MONITOR_BASED vs DEGREE_DAY_ESTIMATE
# ---------------------------------------------------------------------------
def test_monitor_based_projection_yields_ok_after_reading(api):
    """PRD §3.3: "The **monitor-based** variant is used when the tank has `monitor_installed` set true and a `TankMonitorReading` exists whose `read_at` is after the tank's `last_delivery_at`; it anchors the baseline level to that latest reading's `reading_gallons` and the baseline time to that reading's `read_at` — an actual measured anchor."
    PRD §3.3: "Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise."

    Design: Difficulty/dual_variant_calc/tank_projection_monitor_vs_degreeday_divergence
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "delivery_mode": "AUTOMATIC",
                        "monitor_installed": True, "current_gallons": 450})
    tank = base["tank"]
    for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"):
        fx.record_degree_day("NE_01", f"{d}T00:00:00Z", 50)
    fx.record_reading(tank["id"], 380, "2026-01-03T00:00:00Z")
    fx.set_clock("2026-01-05T00:00:00Z")

    result = validate_success(api.evaluate_reorder(tank["id"], DISP))
    # MONITOR_BASED: baseline 380 @ 01-03; HDD [01-03,01-05) = 100; consumed
    # floor(1800*100/1000)=180; proj 200; pct floor(200*100/500)=40 > 30 -> OK.
    assert result["reorder_status"] == "OK"


def test_degree_day_variant_diverges_to_due_on_identical_clock(api):
    """PRD §3.3: "The **degree-day estimate** variant is used otherwise, that is, when no monitor is installed or no monitor reading exists after the baseline anchor; it anchors the baseline level to the tank's `current_gallons` as last set by a delivery (or at tank creation) and the baseline time to the tank's `last_delivery_at`, falling back to the tank's `created_at` when `last_delivery_at` is null."
    PRD §3.3: "Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise."

    Design: Difficulty/dual_variant_calc/tank_projection_monitor_vs_degreeday_divergence
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "current_gallons": 450})
    tank = base["tank"]
    for d in ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"):
        fx.record_degree_day("NE_01", f"{d}T00:00:00Z", 50)
    fx.set_clock("2026-01-05T00:00:00Z")

    result = validate_success(api.evaluate_reorder(tank["id"], DISP))
    # DEGREE_DAY_ESTIMATE: baseline 450 @ created 01-01; HDD [01-01,01-05) = 200;
    # consumed floor(1800*200/1000)=360; proj 90; pct floor(90*100/500)=18 <= 30 -> DUE.
    assert result["reorder_status"] == "DUE"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — Tank's two independent dimensions
# ---------------------------------------------------------------------------
def test_failed_inspection_locks_service_dimension_reorder_unchanged(api):
    """PRD §3.3: "These two dimensions move independently: the reorder dimension is never gated by service-status transitions."
    PRD §3.8: "a `FAILED` result on a tank that is `IN_SERVICE` locks it out (`IN_SERVICE → LOCKED_OUT`)"

    Design: Difficulty/non_linear_state_machine/tank_parallel_service_and_reorder_dimensions
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "current_gallons": 100})
    tank = base["tank"]
    fx.record_degree_day("NE_01", "2026-01-01T00:00:00Z", 10)
    fx.set_clock("2026-01-02T00:00:00Z")
    before = validate_success(api.evaluate_reorder(tank["id"], DISP))
    # current 100 of 500 = pct 20 <= 30 already DUE.
    assert before["reorder_status"] == "DUE"

    validate_success(api.create_inspection(
        tank["id"], {"result": "FAILED", "inspected_at": "2026-01-02T00:00:00Z"}, INSP),
        expected_status=201)
    after = validate_success(api.get_tank(tank["id"], DISP))
    assert after["service_status"] == "LOCKED_OUT"
    assert after["reorder_status"] == "DUE"


def test_tank_reorder_dimension_due_independent_of_service(api):
    """PRD §3.3: "The second is its computed `reorder_status`, either `OK` or `DUE`, which starts at `OK` and is recomputed by readings, deliveries, explicit re-evaluation, and the auto-generation sweep. These two dimensions move independently"

    Design: Difficulty/non_linear_state_machine/tank_parallel_service_and_reorder_dimensions
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "current_gallons": 100})
    tank = base["tank"]
    fx.record_degree_day("NE_01", "2026-01-01T00:00:00Z", 10)
    fx.set_clock("2026-01-02T00:00:00Z")
    evaluated = validate_success(api.evaluate_reorder(tank["id"], DISP))
    # The reorder dimension is DUE while service_status is still IN_SERVICE.
    assert evaluated["reorder_status"] == "DUE"
    assert evaluated["service_status"] == "IN_SERVICE"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — reorder threshold at exactly 30
# ---------------------------------------------------------------------------
def test_reorder_threshold_at_exactly_30_is_due(api):
    """PRD §3.3: "Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise."
    PRD §3.7: "a tank is `DUE` exactly when its projected fill percent is at or below `reorder_threshold_pct` — the boundary is inclusive."

    Design: Difficulty/boundary_precision_check/reorder_threshold_at_exactly_30_is_due
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "current_gallons": 450})
    tank = base["tank"]
    fx.record_degree_day("NE_01", "2026-01-01T00:00:00Z", 167)
    fx.set_clock("2026-01-02T00:00:00Z")
    result = validate_success(api.evaluate_reorder(tank["id"], DISP))
    # consumed floor(1800*167/1000)=300; proj 150; pct floor(150*100/500)=30 == 30 -> DUE.
    assert result["reorder_status"] == "DUE"


def test_reorder_threshold_just_above_is_ok(api):
    """PRD §3.3: "Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise."

    Design: Difficulty/boundary_precision_check/reorder_threshold_at_exactly_30_is_due
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "current_gallons": 450})
    tank = base["tank"]
    # 166 HDD: consumed floor(1800*166/1000)=298; proj 152; pct floor(152*100/500)=30.
    # To land strictly above 30 we need proj pct 31: proj 155 -> consumed 295 ->
    # HDD floor gives 1800*164/1000=295.2 -> 295; proj 155; pct 31 > 30 -> OK.
    fx.record_degree_day("NE_01", "2026-01-01T00:00:00Z", 164)
    fx.set_clock("2026-01-02T00:00:00Z")
    result = validate_success(api.evaluate_reorder(tank["id"], DISP))
    assert result["reorder_status"] == "OK"


# ---------------------------------------------------------------------------
# Corner: calculations — auto_delivery_target
# ---------------------------------------------------------------------------
def test_auto_delivery_target_fill_to_capacity(api):
    """PRD §3.7: "the order's `requested_gallons` is computed as a fill-to-capacity target: the tank's `capacity_gallons` minus the projected gallons from the reorder projection. The resulting order is created with `origin` of `AUTOMATIC"

    Design: Corner/calculations/auto_delivery_target_fill_to_capacity
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "delivery_mode": "AUTOMATIC", "current_gallons": 450})
    tank = base["tank"]
    fx.record_degree_day("NE_01", "2026-01-01T00:00:00Z", 167)
    fx.set_clock("2026-01-02T00:00:00Z")
    reorder = validate_success(api.evaluate_reorder(tank["id"], DISP))
    assert reorder["reorder_status"] == "DUE"

    resp = api.generate_auto_order(tank["id"], DISP)
    data = validate_success(resp, expected_status=201)
    # requested_gallons = capacity 500 - projected 150 = 350.
    assert data["requested_gallons"] == 350
    assert data["origin"] == "AUTOMATIC"


# ---------------------------------------------------------------------------
# Corner: validations — auto-order guards
# ---------------------------------------------------------------------------
def test_generate_auto_order_on_will_call_tank_rejected(api):
    """PRD §3.7: "it succeeds only when the tank's `delivery_mode` is `AUTOMATIC` (a will-call tank is rejected with `ERR_TANK_NOT_AUTOMATIC`)"

    Design: Corner/validations/generate_auto_order_on_will_call_tank_rejected
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "delivery_mode": "WILL_CALL", "current_gallons": 100})
    tank = base["tank"]
    validate_success(api.evaluate_reorder(tank["id"], DISP))
    resp = api.generate_auto_order(tank["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_AUTOMATIC.value)


def test_generate_auto_order_not_due_rejected(api):
    """PRD §3.7: "its `reorder_status` is `DUE` (a tank still `OK` is rejected with `ERR_TANK_NOT_DUE`)."

    Design: Corner/validations/generate_auto_order_not_due_rejected
    """
    fx.set_clock("2026-01-01T00:00:00Z")
    base = fx.setup_tank_for_projection(
        region_code="NE_01", created_clock="2026-01-01T00:00:00Z",
        tank_overrides={"capacity_gallons": 500, "k_factor": 1800,
                        "reorder_threshold_pct": 30, "monitor_installed": False,
                        "delivery_mode": "AUTOMATIC", "current_gallons": 480})
    tank = base["tank"]
    reorder = validate_success(api.evaluate_reorder(tank["id"], DISP))
    assert reorder["reorder_status"] == "OK"
    resp = api.generate_auto_order(tank["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_TANK_NOT_DUE.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers — derived-field reconciliation
# ---------------------------------------------------------------------------
def test_reading_recomputes_reorder_derived_field(api):
    """PRD §3.4: "it sets the tank's `current_gallons` to the reported `reading_gallons` and its `last_reading_at` to the supplied `read_at`, and it then recomputes the tank's `reorder_status` through the projection described in §3.3"
    PRD §3.3: "Finally, `reorder_status` becomes `DUE` when that projected percent is at or below the tank's `reorder_threshold_pct`, and `OK` otherwise."

    Design: Corner/cross_cutting_complexity_layers/reading_recomputes_reorder_derived_field
    """
    fx.set_clock("2026-01-05T00:00:00Z")
    account = fx.create_account(region_code="NE_07", fuel_type="PROPANE",
                                customer_name="Derive Dora")
    tank = fx.create_tank(account["id"], capacity_gallons=500, k_factor=1500,
                          reorder_threshold_pct=30, monitor_installed=True,
                          current_gallons=400)
    fx.record_reading(tank["id"], 100, "2026-01-05T00:00:00Z")
    low = validate_success(api.get_tank(tank["id"], DISP))
    # 100/500 = 20% <= 30, no HDD elapsed -> DUE.
    assert low["reorder_status"] == "DUE"

    fx.record_reading(tank["id"], 450, "2026-01-05T01:00:00Z")
    high = validate_success(api.get_tank(tank["id"], DISP))
    # 450/500 = 90% > 30 -> OK.
    assert high["reorder_status"] == "OK"
