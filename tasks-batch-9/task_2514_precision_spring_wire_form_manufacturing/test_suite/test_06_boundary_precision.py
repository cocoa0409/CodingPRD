"""Values sitting exactly on a boundary, and one unit off it.

Four comparisons in this API decide their outcome on the last digit that
survives rounding: a capability index against a characteristic's floor, a
pre-discount subtotal against a volume-tier breakpoint, a lot's piece count
against a program's minimum order quantity, and an aggregate oven load against a
capacity over closed time intervals. Every instance is driven twice, once with
the metric resting exactly on its boundary and once one unit away from it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BELOW_MINIMUM_ORDER_QUANTITY,
    ERR_OVEN_CAPACITY_EXCEEDED,
)
from test_helpers.test_users import (
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

# An industrial program, so nothing but the characteristic's own floor governs
# the control state of a subgroup.
_INDUSTRIAL_PROGRAM = {
    "program_code": "PGM-IND-5",
    "customer_name": "Bramble Industrial Supply",
    "application_class": C.CLASS_INDUSTRIAL,
    "ppap_level": 1,
    "committed_pieces": 100_000,
    "minimum_order_quantity": 1_000,
    "required_salt_spray_hours": 96,
    "biocompatibility_required": False,
    "min_fatigue_margin": 1.2,
    "required_ppk": 1.0,
    "amortization_method": C.FORECAST_BASIS,
}

# The free-length print the canonical safety-critical characteristic carries.
_LSL = 59.5
_USL = 60.5
_CPK_FLOOR = 1.333

# Readings a flat 0.125 either side of nominal: the Bessel-corrected sigma is
# 0.125000 and the binding 0.5 distance gives Cpk exactly 1.333, the floor.
_AT_FLOOR_SUBGROUP = [59.875, 60.0, 60.125]

# One ten-thousandth wider on each outer reading: sigma 0.125100 and Cpk 1.332,
# one thousandth below the floor, with both readings still inside the band.
_BELOW_FLOOR_SUBGROUP = [59.8749, 60.0, 60.1251]


def _running_run_world(api: ApiClient) -> X.World:
    """A 1 000-piece run of the canonical design, RUNNING after an accepted FAI."""
    return X.build_world(
        api,
        "running",
        program=_INDUSTRIAL_PROGRAM,
        run={"planned_pieces": 1_000},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )


def test_cpk_exactly_on_the_characteristic_floor_stays_in_control(api):
    """A subgroup whose rounded Cpk equals the floor exactly must pass.

    PRD §2.6: "All rounding in this system is **round half up** — a value exactly on the midpoint rounds away from zero — and every quantity is rounded to the decimal count its own rule names, never to a house default."
    PRD §2.6: "Inspection statistics use three different counts on the same record: the subgroup mean to **4 decimal places**, the Bessel-corrected standard deviation to **6 decimal places**, and both capability indices to **3 decimal places**."
    PRD §2.6: "Capability floors are compared against the **rounded** index."
    PRD §3.7: "`mean_value` is their arithmetic mean, rounded half up to four decimal places."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "The comparison against the floor is made after rounding, and a `cpk_value` exactly equal to the floor passes."

    Design: Difficulty/boundary_precision_check/cpk_exactly_at_characteristic_floor_versus_one_unit_below_on_inspections
    """
    world = _running_run_world(api)
    characteristic = world.characteristics[0]

    assert characteristic["cpk_floor"] == _CPK_FLOOR, (
        f"the print carries a 1.333 capability floor, got {characteristic['cpk_floor']}"
    )
    assert characteristic["is_safety_critical"] is True, (
        "only a safety-critical characteristic can escalate, so the control state matters here"
    )

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(characteristic["id"], _AT_FLOOR_SUBGROUP),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    assert record["mean_value"] == A.expected_mean_value(_AT_FLOOR_SUBGROUP), (
        f"the mean of a symmetric subgroup is 60.0000, got {record['mean_value']}"
    )
    assert record["sigma_value"] == A.expected_sigma_value(_AT_FLOOR_SUBGROUP), (
        f"the Bessel-corrected sigma is 0.125000, got {record['sigma_value']}"
    )
    assert record["sigma_value"] == 0.125, (
        f"a population sigma would read 0.102062 instead, got {record['sigma_value']}"
    )
    assert record["cpk_value"] == A.expected_cpk_value(
        _AT_FLOOR_SUBGROUP, _LSL, _USL
    ), f"0.5 over three times 0.125 is exactly 1.333, got {record['cpk_value']}"
    assert record["cpk_value"] == _CPK_FLOOR, (
        f"the index lands exactly on the floor, got {record['cpk_value']}"
    )
    assert record["control_state"] == C.CONTROL_IN_CONTROL, (
        f"an index exactly equal to the floor passes, got {record['control_state']}"
    )
    assert record["ppk_value"] == A.expected_ppk_value(_AT_FLOOR_SUBGROUP, _LSL, _USL), (
        "the only pooled record so far is this one, so Ppk matches Cpk at 1.333, got "
        f"{record['ppk_value']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_OPEN, (
        f"an in-control subgroup never holds a run, got {run['quality_status']}"
    )
    assert run["min_cpk_observed"] == _CPK_FLOOR, (
        "min_cpk_observed drops from the first article's 3.333 to this 1.333, got "
        f"{run['min_cpk_observed']}"
    )
    assert run["min_ppk_observed"] == _CPK_FLOOR, (
        f"the only safety-critical SPC Ppk on the run is 1.333, got {run['min_ppk_observed']}"
    )


def test_cpk_one_thousandth_below_the_floor_holds_the_run(api):
    """Widening the outer readings by a ten-thousandth drops the index below the floor.

    PRD §2.6: "Inspection statistics use three different counts on the same record: the subgroup mean to **4 decimal places**, the Bessel-corrected standard deviation to **6 decimal places**, and both capability indices to **3 decimal places**."
    PRD §2.6: "Capability floors are compared against the **rounded** index."
    PRD §3.7: "`sigma_value` is the Bessel-corrected sample standard deviation: take each measurement's deviation from the **unrounded** mean, square it, sum the squares, divide by one less than the subgroup size, take the square root, and round half up to six decimal places."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is below the characteristic's `cpk_floor`, or when any single measurement in the subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.7: "The comparison against the floor is made after rounding, and a `cpk_value` exactly equal to the floor passes."
    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."

    Design: Difficulty/boundary_precision_check/cpk_exactly_at_characteristic_floor_versus_one_unit_below_on_inspections
    """
    world = _running_run_world(api)
    characteristic = world.characteristics[0]

    at_floor = validate_success(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(characteristic["id"], _AT_FLOOR_SUBGROUP),
            QUALITY_INSPECTOR_HEADERS,
        ),
        201,
    )
    assert at_floor["control_state"] == C.CONTROL_IN_CONTROL, (
        f"the on-boundary subgroup passes first, got {at_floor['control_state']}"
    )

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(characteristic["id"], _BELOW_FLOOR_SUBGROUP),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    assert record["sigma_value"] == A.expected_sigma_value(_BELOW_FLOOR_SUBGROUP), (
        f"the sixth decimal of sigma decides this boundary: 0.125100, got {record['sigma_value']}"
    )
    assert record["sigma_value"] == 0.1251, (
        f"the stored sigma is 0.125100, got {record['sigma_value']}"
    )
    assert record["cpk_value"] == A.expected_cpk_value(
        _BELOW_FLOOR_SUBGROUP, _LSL, _USL
    ), f"0.5 over three times 0.1251 rounds to 1.332, got {record['cpk_value']}"
    assert record["cpk_value"] == 1.332, (
        f"one thousandth below the 1.333 floor, got {record['cpk_value']}"
    )
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        f"an index below the floor is OUT_OF_CONTROL, got {record['control_state']}"
    )
    assert all(_LSL <= value <= _USL for value in _BELOW_FLOOR_SUBGROUP), (
        "no reading escapes the specification band, so the verdict rests purely on the index"
    )
    assert record["ppk_value"] == A.expected_ppk_value(
        _AT_FLOOR_SUBGROUP + _BELOW_FLOOR_SUBGROUP, _LSL, _USL
    ), f"six pooled measurements give Ppk 1.490, got {record['ppk_value']}"
    assert record["ppk_value"] == 1.49, (
        f"the pooled sigma over six values is 0.111848, lifting Ppk to 1.490, got {record['ppk_value']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        f"an out-of-control safety-critical subgroup holds the run, got {run['quality_status']}"
    )
    assert run["min_cpk_observed"] == 1.332, (
        f"min_cpk_observed follows the lowest Cpk on the run, got {run['min_cpk_observed']}"
    )
    assert run["min_ppk_observed"] == _CPK_FLOOR, (
        "the earlier record's 1.333 is still the lowest pooled figure, got "
        f"{run['min_ppk_observed']}"
    )


def test_the_below_floor_subgroup_holds_the_run_on_its_own_pooled_figure(api):
    """The one-unit-off subgroup fails on its own, with nothing else pooled in.

    PRD §2.6: "Capability floors are compared against the **rounded** index."
    PRD §3.7: "`control_state` is `OUT_OF_CONTROL` when the **rounded** `cpk_value` is below the characteristic's `cpk_floor`, or when any single measurement in the subgroup lies above `usl` or below `lsl`; it is `IN_CONTROL` otherwise."
    PRD §3.7: "The comparison against the floor is made after rounding, and a `cpk_value` exactly equal to the floor passes."
    PRD §3.7: "First-article records therefore move `min_cpk_observed` but leave `min_ppk_observed` untouched."
    PRD §3.8: "Hop two: the run's `quality_status` transitions `OPEN → SPC_HOLD`."

    Design: Difficulty/boundary_precision_check/cpk_exactly_at_characteristic_floor_versus_one_unit_below_on_inspections
    """
    world = _running_run_world(api)
    characteristic = world.characteristics[0]

    assert world.run["min_ppk_observed"] is None, (
        f"the accepted first article left min_ppk_observed null, got {world.run['min_ppk_observed']}"
    )

    response = api.record_inspection(
        world.run_id,
        F.measurement_payload(characteristic["id"], _BELOW_FLOOR_SUBGROUP),
        QUALITY_INSPECTOR_HEADERS,
    )
    record = validate_success(response, 201)

    assert record["cpk_value"] == 1.332, (
        f"the index is 1.332 whether or not other records exist, got {record['cpk_value']}"
    )
    assert record["ppk_value"] == A.expected_ppk_value(
        _BELOW_FLOOR_SUBGROUP, _LSL, _USL
    ), f"pooling only itself, Ppk matches Cpk at 1.332, got {record['ppk_value']}"
    assert record["control_state"] == C.CONTROL_OUT_OF_CONTROL, (
        f"1.332 sits below the 1.333 floor, got {record['control_state']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_SPC_HOLD, (
        f"the single failing subgroup is enough to hold the run, got {run['quality_status']}"
    )
    assert run["min_ppk_observed"] == 1.332, (
        f"the run's only pooled figure is now 1.332, got {run['min_ppk_observed']}"
    )


# The same industrial posture on a second program, left without any approval
# package so `quote_frozen` stays false and the endpoint can be called twice.
_QUOTE_PROGRAM = dict(_INDUSTRIAL_PROGRAM, program_code="PGM-IND-6")

# The lowest volume-tier breakpoint, in cents.
_TIER_BREAKPOINT_CENTS = 50_000

# At 21.2573 cents of base unit cost, 2 352 pieces subtotal 49 997 cents — the
# largest quantity still under the breakpoint — and 2 353 pieces subtotal 50 018.
_LOWER_TIER_QTY = 2_352
_UPPER_TIER_QTY = 2_353

_TOOL_COST_CENTS = 4_800_000

# The canonical design's stored figures, which are the only inputs the quote reads.
_MASS_PER_PIECE_KG = 0.021185
_WIRE_COST_PER_KG_CENTS = 850
_CYCLE_SECONDS = 1.8


def _unquoted_program_world(api: ApiClient) -> X.World:
    """A program, a design and a 4 800 000-cent tool, with no quote yet on file."""
    world = X.World()
    world.program = X.open_program(api, **_QUOTE_PROGRAM)
    world.material = X.register_material(api)
    world.design = X.draft_design(
        api, world.program_id, world.material_id, part_number="D1-QUOTE"
    )
    world.tooling = X.capitalise_tooling(
        api,
        world.design_id,
        tool_code="TL-D1-Q",
        original_cost_cents=_TOOL_COST_CENTS,
    )
    return world


def test_a_subtotal_just_below_the_tier_breakpoint_takes_the_zero_discount(api):
    """2 352 pieces subtotal 49 997 cents, the last quantity inside the 0.00 tier.

    PRD §2.6: "Money is integral cents everywhere it is stored."
    PRD §2.6: "Inside the quoting calculation, per-piece amounts are carried to **4 decimal places** (tenths of a mill) while the intermediate terms accumulate, and are collapsed to whole cents only at the four steps that the quoting narrative names."
    PRD §3.11: "The eleven steps below run **in this exact order**, and the order is pinned because the dependency looks circular: the discount tier is keyed on a subtotal computed before any discount or amortization, while the amortization cap is keyed on the unit price after the discount."
    PRD §3.11: "`quoted_pre_discount_subtotal_cents` is the base unit cost multiplied by `quoted_qty`, rounded to whole cents."
    PRD §3.11: "`quoted_volume_discount_pct` is read off that subtotal against the breakpoints 50000, 250000 and 1000000 cents: below 50000 it is 0.00, below 250000 it is 0.03, below 1000000 it is 0.06, and at or above 1000000 it is 0.09."
    PRD §3.11: "The comparisons are strict below and inclusive at the top tier."
    PRD §3.11: "The endpoint also increments the program's `version` by 1."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_breakpoint_at_and_below_fifty_thousand_cents_on_quote
    """
    world = _unquoted_program_world(api)
    version_before = world.program["version"]
    expected = A.expected_quote(
        _MASS_PER_PIECE_KG,
        _WIRE_COST_PER_KG_CENTS,
        _CYCLE_SECONDS,
        _LOWER_TIER_QTY,
        _TOOL_COST_CENTS,
    )

    response = api.quote_program(
        world.program_id,
        F.quote_payload(world.design_id, version_before, quoted_qty=_LOWER_TIER_QTY),
        PROGRAM_MANAGER_HEADERS,
    )
    program = validate_success(response, 200)

    assert program["quoted_pre_discount_subtotal_cents"] == 49_997, (
        "2 352 pieces at 21.2573 cents subtotal 49 997 cents, got "
        f"{program['quoted_pre_discount_subtotal_cents']}"
    )
    assert program["quoted_pre_discount_subtotal_cents"] == expected[
        "quoted_pre_discount_subtotal_cents"
    ], "the stored subtotal must match the pinned eleven-step calculation"
    assert program["quoted_pre_discount_subtotal_cents"] < _TIER_BREAKPOINT_CENTS, (
        "the subtotal sits three cents under the 50 000-cent breakpoint"
    )
    assert program["quoted_volume_discount_pct"] == 0.00, (
        f"a subtotal below 50 000 cents earns no discount, got {program['quoted_volume_discount_pct']}"
    )
    assert program["quoted_tooling_amort_per_piece_cents"] == 5, (
        "the cap of a quarter of the 21.2573-cent discounted unit cost binds at 5 cents, got "
        f"{program['quoted_tooling_amort_per_piece_cents']}"
    )
    assert program["quoted_unit_price_cents"] == 26, (
        f"21.2573 plus 5 cents rounds to a 26-cent unit price, got {program['quoted_unit_price_cents']}"
    )
    assert program["quoted_total_cents"] == 186_152, (
        "26 cents over 2 352 pieces plus the 125 000-cent setup fee is 186 152, got "
        f"{program['quoted_total_cents']}"
    )
    assert program["quoted_qty"] == _LOWER_TIER_QTY, (
        f"the program records the quantity it was quoted on, got {program['quoted_qty']}"
    )
    assert program["version"] == version_before + 1, (
        f"pricing a program bumps its version once, got {program['version']}"
    )
    assert program["quote_frozen"] is False, (
        "no approval package exists, so the terms are still open to re-quoting"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["unamortized_cents"] == _TOOL_COST_CENTS, (
        f"quoting never posts to the tooling ledger, got {tooling['unamortized_cents']}"
    )


def test_one_more_piece_crosses_the_breakpoint_into_the_three_percent_tier(api):
    """2 353 pieces subtotal 50 018 cents, the first quantity in the 0.03 tier.

    PRD §3.11: "The eleven steps below run **in this exact order**, and the order is pinned because the dependency looks circular: the discount tier is keyed on a subtotal computed before any discount or amortization, while the amortization cap is keyed on the unit price after the discount."
    PRD §3.11: "`quoted_pre_discount_subtotal_cents` is the base unit cost multiplied by `quoted_qty`, rounded to whole cents."
    PRD §3.11: "`quoted_volume_discount_pct` is read off that subtotal against the breakpoints 50000, 250000 and 1000000 cents: below 50000 it is 0.00, below 250000 it is 0.03, below 1000000 it is 0.06, and at or above 1000000 it is 0.09."
    PRD §3.11: "The comparisons are strict below and inclusive at the top tier."
    PRD §3.11: "The discounted unit cost is the base unit cost multiplied by one minus the discount fraction, rounded to 4 decimal places."
    PRD §3.11: "The amortization cap is 0.25 of the discounted unit cost, rounded **down** to a whole cent."
    PRD §3.11: "`quoted_tooling_amort_per_piece_cents` is the smaller of the raw ask and the cap."
    PRD §3.11: "`quoted_unit_price_cents` is the discounted unit cost plus that per-piece amortization, rounded to whole cents."
    PRD §3.11: "`quoted_total_cents` is `quoted_unit_price_cents` multiplied by `quoted_qty` plus the flat setup fee of 125000 cents."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_breakpoint_at_and_below_fifty_thousand_cents_on_quote
    """
    world = _unquoted_program_world(api)

    lower = validate_success(
        api.quote_program(
            world.program_id,
            F.quote_payload(
                world.design_id, world.program["version"], quoted_qty=_LOWER_TIER_QTY
            ),
            PROGRAM_MANAGER_HEADERS,
        ),
        200,
    )
    assert lower["quoted_volume_discount_pct"] == 0.00, (
        f"the smaller quantity stays in the zero tier, got {lower['quoted_volume_discount_pct']}"
    )

    expected = A.expected_quote(
        _MASS_PER_PIECE_KG,
        _WIRE_COST_PER_KG_CENTS,
        _CYCLE_SECONDS,
        _UPPER_TIER_QTY,
        _TOOL_COST_CENTS,
    )
    response = api.quote_program(
        world.program_id,
        F.quote_payload(
            world.design_id, lower["version"], quoted_qty=_UPPER_TIER_QTY
        ),
        PROGRAM_MANAGER_HEADERS,
    )
    upper = validate_success(response, 200)

    assert upper["quoted_pre_discount_subtotal_cents"] == 50_018, (
        "one more piece lifts the subtotal to 50 018 cents, got "
        f"{upper['quoted_pre_discount_subtotal_cents']}"
    )
    assert upper["quoted_pre_discount_subtotal_cents"] == expected[
        "quoted_pre_discount_subtotal_cents"
    ], "the stored subtotal must match the pinned eleven-step calculation"
    assert upper["quoted_pre_discount_subtotal_cents"] >= _TIER_BREAKPOINT_CENTS, (
        "the subtotal has crossed the 50 000-cent breakpoint"
    )
    assert upper["quoted_volume_discount_pct"] == 0.03, (
        f"a subtotal at or above 50 000 cents earns three percent, got {upper['quoted_volume_discount_pct']}"
    )
    assert upper["quoted_tooling_amort_per_piece_cents"] == 5, (
        "a quarter of the 20.6196-cent discounted unit cost still floors at 5 cents, got "
        f"{upper['quoted_tooling_amort_per_piece_cents']}"
    )
    assert upper["quoted_unit_price_cents"] == 26, (
        f"20.6196 plus 5 cents still rounds to 26, got {upper['quoted_unit_price_cents']}"
    )
    assert upper["quoted_unit_price_cents"] == lower["quoted_unit_price_cents"], (
        "the unit price is identical on both sides of the breakpoint, so only the discount "
        "field and the subtotal reveal the tier change"
    )
    assert upper["quoted_volume_discount_pct"] != lower["quoted_volume_discount_pct"], (
        "the discount fraction is the field that moves across the breakpoint"
    )
    assert upper["quoted_total_cents"] == 186_178, (
        "26 cents over 2 353 pieces plus the 125 000-cent setup fee is 186 178, got "
        f"{upper['quoted_total_cents']}"
    )
    assert upper["quoted_qty"] == _UPPER_TIER_QTY, (
        f"the second quote fully supersedes the first, got {upper['quoted_qty']}"
    )
    assert upper["version"] == lower["version"] + 1, (
        f"each quote bumps the program's version once, got {upper['version']}"
    )
    assert upper["quote_frozen"] is False, (
        "the terms stay open because no customer verdict has landed"
    )

    tooling = X.refresh_tooling(api, world.tooling_id)
    assert tooling["unamortized_cents"] == _TOOL_COST_CENTS, (
        f"two quotes post nothing to the tooling ledger, got {tooling['unamortized_cents']}"
    )


# A fully qualified safety program whose minimum order quantity is set high
# enough that the canonical 25 500-piece run can satisfy it exactly once.
_MOQ_PROGRAM = {
    "program_code": "PGM-AUTO-4",
    "customer_name": "Northwind Drivetrain",
    "application_class": C.CLASS_AUTOMOTIVE_SAFETY,
    "ppap_level": 3,
    "committed_pieces": 500_000,
    "minimum_order_quantity": 25_000,
    "required_salt_spray_hours": 96,
    "biocompatibility_required": False,
    "min_fatigue_margin": 1.2,
    "required_ppk": 1.33,
    "amortization_method": C.FORECAST_BASIS,
}

_MOQ_PIECES = 25_000
_BELOW_MOQ_PIECES = 24_999


def _allocatable_world(api: ApiClient) -> X.World:
    """A COMPLETE, heat-treated, quoted and customer-approved run of 25 500 pieces."""
    return X.build_world(
        api,
        "approved",
        program=_MOQ_PROGRAM,
        oven={"oven_code": "OV-2"},
        submission={"ppap_level": 3},
        activation_clock=C.CLOCK_INSIDE_SETUP_WINDOW,
    )


def test_a_lot_exactly_at_the_minimum_order_quantity_allocates(api):
    """25 000 pieces against a 25 000-piece minimum is inclusive at the boundary.

    PRD §3.1: "Volume terms come next. `committed_pieces` is the total number of pieces the customer has committed to over the life of the program and must be greater than zero; `minimum_order_quantity` is the smallest shippable lot size the program accepts and must likewise be greater than zero."
    PRD §3.11: "Then the quantity gates: `piece_count` must be at least the program's `minimum_order_quantity`, inclusive at the boundary, otherwise `ERR_BELOW_MINIMUM_ORDER_QUANTITY` (HTTP 422); `piece_count` must not exceed the run's `produced_pieces` minus the pieces already carried by lots of this run whose `lot_status` is `ALLOCATED`, `PACKED` or `SHIPPED` — quarantined and returned lots do not consume run availability — otherwise `ERR_RUN_PIECES_EXHAUSTED` (HTTP 422)."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with `packaging_method` null, and it snapshots the commercial terms at creation: `unit_price_cents` from the program's `quoted_unit_price_cents`, `tooling_amort_per_piece_cents` from the program's `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count` multiplied by `unit_price_cents`."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."

    Design: Difficulty/boundary_precision_check/minimum_order_quantity_inclusive_at_and_one_piece_below_on_lot_creation
    """
    world = _allocatable_world(api)
    program = world.program

    assert program["minimum_order_quantity"] == _MOQ_PIECES, (
        f"the program accepts nothing smaller than 25 000 pieces, got {program['minimum_order_quantity']}"
    )
    assert program["quoted_unit_price_cents"] == 24, (
        f"the 26 000-piece quote froze a 24-cent unit price, got {program['quoted_unit_price_cents']}"
    )
    assert program["quoted_tooling_amort_per_piece_cents"] == 4, (
        "the quote froze four cents of per-piece amortization, got "
        f"{program['quoted_tooling_amort_per_piece_cents']}"
    )
    assert world.run["produced_pieces"] == 25_500, (
        f"the run yielded 25 500 good pieces, got {world.run['produced_pieces']}"
    )

    response = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, piece_count=_MOQ_PIECES),
        PROGRAM_MANAGER_HEADERS,
    )
    lot = validate_success(response, 201)

    assert lot["piece_count"] == _MOQ_PIECES, (
        f"the lot carries exactly the minimum quantity, got {lot['piece_count']}"
    )
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"a lot resting on the boundary opens ALLOCATED, got {lot['lot_status']}"
    )
    assert lot["packaging_method"] is None, (
        f"a freshly allocated lot has no packaging yet, got {lot['packaging_method']}"
    )
    assert lot["unit_price_cents"] == 24, (
        f"the lot snapshots the program's quoted unit price, got {lot['unit_price_cents']}"
    )
    assert lot["tooling_amort_per_piece_cents"] == 4, (
        f"the lot snapshots the quoted amortization, got {lot['tooling_amort_per_piece_cents']}"
    )
    assert lot["extended_price_cents"] == 600_000, (
        f"25 000 pieces at 24 cents is 600 000 cents, got {lot['extended_price_cents']}"
    )
    assert lot["tooling_recovery_cents"] == 0, (
        f"nothing is recovered until the lot ships, got {lot['tooling_recovery_cents']}"
    )
    assert lot["shipped_at"] is None, (
        f"an allocated lot has not shipped, got {lot['shipped_at']}"
    )
    assert lot["quarantine_reason"] is None, (
        f"an allocated lot carries no quarantine reason, got {lot['quarantine_reason']}"
    )

    after = X.refresh_program(api, world.program_id)
    assert after["allocated_pieces"] == _MOQ_PIECES, (
        f"the pieces moved onto the allocated counter, got {after['allocated_pieces']}"
    )
    assert after["open_commitment_pieces"] == 475_000, (
        "500 000 committed less the 25 000 just allocated is 475 000, got "
        f"{after['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(after)

    lots, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"run_id": world.run_id})
    )
    assert meta["total_count"] == 1, (
        f"exactly one lot exists on this run, got {meta['total_count']}"
    )
    assert lots[0]["id"] == lot["id"], "the listed lot is the one just allocated"


def test_one_piece_below_the_minimum_order_quantity_is_refused(api):
    """24 999 pieces is one short of the floor and buys nothing at all.

    PRD §2.8: "63. `ERR_BELOW_MINIMUM_ORDER_QUANTITY` — on `POST /shipment-lots`."
    PRD §3.11: "Then the quantity gates: `piece_count` must be at least the program's `minimum_order_quantity`, inclusive at the boundary, otherwise `ERR_BELOW_MINIMUM_ORDER_QUANTITY` (HTTP 422); `piece_count` must not exceed the run's `produced_pieces` minus the pieces already carried by lots of this run whose `lot_status` is `ALLOCATED`, `PACKED` or `SHIPPED` — quarantined and returned lots do not consume run availability — otherwise `ERR_RUN_PIECES_EXHAUSTED` (HTTP 422)."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."
    PRD §3.11: "Lots may be listed filtered by `run_id`, `program_id` and `lot_status`."

    Design: Difficulty/boundary_precision_check/minimum_order_quantity_inclusive_at_and_one_piece_below_on_lot_creation
    """
    world = _allocatable_world(api)

    response = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, piece_count=_BELOW_MOQ_PIECES),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_BELOW_MINIMUM_ORDER_QUANTITY, 422)

    after = X.refresh_program(api, world.program_id)
    assert after["allocated_pieces"] == 0, (
        f"a refused allocation moves no pieces, got {after['allocated_pieces']}"
    )
    assert after["open_commitment_pieces"] == 500_000, (
        f"the whole commitment is still open, got {after['open_commitment_pieces']}"
    )
    assert after["quarantined_lot_count"] == 0, (
        f"no lot exists to quarantine, got {after['quarantined_lot_count']}"
    )
    A.assert_commitment_conserved(after)

    _lots, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"program_id": world.program_id})
    )
    assert meta["total_count"] == 0, (
        f"the rejected request created no lot, got {meta['total_count']}"
    )


def test_the_shortfall_lot_is_refused_and_the_boundary_lot_then_allocates(api):
    """One request either side of the floor, in order, on the same run.

    PRD §3.11: "Then the quantity gates: `piece_count` must be at least the program's `minimum_order_quantity`, inclusive at the boundary, otherwise `ERR_BELOW_MINIMUM_ORDER_QUANTITY` (HTTP 422); `piece_count` must not exceed the run's `produced_pieces` minus the pieces already carried by lots of this run whose `lot_status` is `ALLOCATED`, `PACKED` or `SHIPPED` — quarantined and returned lots do not consume run availability — otherwise `ERR_RUN_PIECES_EXHAUSTED` (HTTP 422)."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with `packaging_method` null, and it snapshots the commercial terms at creation: `unit_price_cents` from the program's `quoted_unit_price_cents`, `tooling_amort_per_piece_cents` from the program's `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count` multiplied by `unit_price_cents`."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."

    Design: Difficulty/boundary_precision_check/minimum_order_quantity_inclusive_at_and_one_piece_below_on_lot_creation
    """
    world = _allocatable_world(api)

    validate_error(
        api.create_lot(
            F.lot_payload(
                world.run_id, world.program_id, piece_count=_BELOW_MOQ_PIECES
            ),
            PROGRAM_MANAGER_HEADERS,
        ),
        ERR_BELOW_MINIMUM_ORDER_QUANTITY,
        422,
    )

    lot = validate_success(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, piece_count=_MOQ_PIECES),
            PROGRAM_MANAGER_HEADERS,
        ),
        201,
    )
    assert lot["piece_count"] == _MOQ_PIECES, (
        "the single extra piece is the whole difference between the two requests, got "
        f"{lot['piece_count']}"
    )
    assert lot["lot_status"] == C.LOT_ALLOCATED, (
        f"the boundary request succeeds after the shortfall failed, got {lot['lot_status']}"
    )
    assert lot["extended_price_cents"] == _MOQ_PIECES * lot["unit_price_cents"], (
        f"the extended price is a plain product, got {lot['extended_price_cents']}"
    )

    after = X.refresh_program(api, world.program_id)
    assert after["allocated_pieces"] == _MOQ_PIECES, (
        "only the accepted request moved pieces, got "
        f"{after['allocated_pieces']}"
    )
    assert after["open_commitment_pieces"] == 500_000 - _MOQ_PIECES, (
        f"exactly one allocation was charged to the commitment, got {after['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(after)

    _lots, meta = validate_paginated(
        api.list_lots(PROGRAM_MANAGER_HEADERS, {"program_id": world.program_id})
    )
    assert meta["total_count"] == 1, (
        f"one refusal and one success leave a single lot, got {meta['total_count']}"
    )


# A 250 kg oven already carrying a 180 kg basket over the afternoon, so 70 kg
# more lands exactly on capacity and 80 kg more is 10 kg over it.
_OVEN_CAPACITY_KG = 250.0
_FIRST_LOAD_KG = 180.0
_FITTING_LOAD_KG = 70.0
_OVERFULL_LOAD_KG = 80.0
_ONE_KILOGRAM = 1.0
_BATCH_TEMP_C = 425.0

# The resident basket's closed window, and two candidate second windows: one
# whose start touches the resident end exactly, one a single minute clear of it.
_FIRST_BATCH_START = "2026-08-05T09:00:00Z"
_FIRST_BATCH_END = "2026-08-05T13:00:00Z"
_TOUCHING_START = "2026-08-05T13:00:00Z"
_CLEAR_START = "2026-08-05T13:01:00Z"
_SECOND_BATCH_END = "2026-08-05T17:00:00Z"


def _loaded_oven_world(api: ApiClient) -> X.World:
    """A RUNNING run plus a 250 kg oven holding one 180 kg basket until 13:00."""
    world = _running_run_world(api)
    world.oven = X.commission_oven(
        api, oven_code="OV-3", capacity_kg=_OVEN_CAPACITY_KG
    )
    world.batch = X.schedule_batch(
        api,
        world.oven_id,
        world.run_id,
        window_start=_FIRST_BATCH_START,
        window_end=_FIRST_BATCH_END,
        load_kg=_FIRST_LOAD_KG,
        target_temp_c=_BATCH_TEMP_C,
        peening_requested=False,
    )
    return world


def test_an_aggregate_load_exactly_at_oven_capacity_is_accepted(api):
    """180 kg plus 70 kg is 250.000 kg on a 250 kg oven, and that fits.

    PRD §2.6: "Every kilogram quantity on a wire lot, a production run, an oven and a heat-treat batch is carried to **3 decimal places**, with the rounding applied once per posting."
    PRD §3.9: "A new oven opens with `scheduled_load_kg` at 0.000, and that field is always the sum of `load_kg` over the oven's batches whose `batch_status` is `SCHEDULED` or `RUNNING`."
    PRD §3.9: "Oven windows are **closed** intervals, so two windows collide even when they merely touch at a single endpoint: they collide when the first window's start is at or before the second window's end **and** the second window's start is at or before the first window's end."
    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half up to three decimal places, and compare it against the oven's `capacity_kg`: the comparison is strict, so a total that exceeds capacity is rejected with `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is accepted."
    PRD §3.9: "A successful booking opens the batch in `batch_status` `SCHEDULED` and adds its `load_kg` to the oven's `scheduled_load_kg`."
    PRD §3.9: "The run's `heat_treat_state` stays `NOT_STARTED` — scheduling a batch is not charging one."

    Design: Difficulty/boundary_precision_check/oven_aggregate_load_exactly_at_capacity_and_closed_interval_touch_on_heat_treat
    """
    world = _loaded_oven_world(api)

    assert world.oven["capacity_kg"] == _OVEN_CAPACITY_KG, (
        f"the oven holds 250 kg at any instant, got {world.oven['capacity_kg']}"
    )
    resident = X.refresh_oven(api, world.oven_id)
    assert resident["scheduled_load_kg"] == _FIRST_LOAD_KG, (
        f"the resident basket accounts for 180 kg, got {resident['scheduled_load_kg']}"
    )

    over = api.create_batch(
        F.batch_payload(
            world.oven_id,
            world.run_id,
            window_start=_TOUCHING_START,
            window_end=_SECOND_BATCH_END,
            load_kg=_OVERFULL_LOAD_KG,
            target_temp_c=_BATCH_TEMP_C,
            peening_requested=False,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(over, ERR_OVEN_CAPACITY_EXCEEDED, 409)

    unchanged = X.refresh_oven(api, world.oven_id)
    assert unchanged["scheduled_load_kg"] == _FIRST_LOAD_KG, (
        f"the refused booking posted no mass, got {unchanged['scheduled_load_kg']}"
    )

    fitting = validate_success(
        api.create_batch(
            F.batch_payload(
                world.oven_id,
                world.run_id,
                window_start=_TOUCHING_START,
                window_end=_SECOND_BATCH_END,
                load_kg=_FITTING_LOAD_KG,
                target_temp_c=_BATCH_TEMP_C,
                peening_requested=False,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        201,
    )
    assert fitting["load_kg"] == _FITTING_LOAD_KG, (
        f"the accepted basket weighs 70 kg, got {fitting['load_kg']}"
    )
    assert fitting["batch_status"] == C.BATCH_SCHEDULED, (
        f"a successful booking opens SCHEDULED, got {fitting['batch_status']}"
    )
    assert fitting["peening_performed"] is None, (
        f"the peening outcome stays null until discharge, got {fitting['peening_performed']}"
    )

    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == A.round_half_up(
        _FIRST_LOAD_KG + _FITTING_LOAD_KG, 3
    ), f"the oven now carries 250.000 kg, got {oven['scheduled_load_kg']}"
    assert oven["scheduled_load_kg"] == _OVEN_CAPACITY_KG, (
        f"the aggregate rests exactly on capacity, got {oven['scheduled_load_kg']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        f"scheduling two baskets charges neither, got {run['heat_treat_state']}"
    )


def test_a_window_starting_one_minute_after_the_closed_end_does_not_collide(api):
    """The 80 kg basket refused at 13:00 is accepted at 13:01.

    PRD §3.9: "Scheduling a batch is a `ProcessTechnician`'s act. The payload names the `oven_id`, the `run_id` whose pieces are being relieved, the occupation window as `window_start` and `window_end` — both **inclusive** for this entity — the weighed basket `load_kg` in kilograms carried to three decimal places and greater than zero, the requested soak `target_temp_c` greater than zero, and the optional `peening_requested` flag recording whether shot peening is part of this batch's recipe, defaulting to false."
    PRD §3.9: "Oven windows are **closed** intervals, so two windows collide even when they merely touch at a single endpoint: they collide when the first window's start is at or before the second window's end **and** the second window's start is at or before the first window's end."
    PRD §3.9: "Sum `load_kg` over every batch on the same oven whose `batch_status` is `SCHEDULED` or `RUNNING` and whose window collides with the new one; batches that are `CANCELLED` or `COMPLETE` are excluded even when their windows collide, because their mass has left the oven."
    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half up to three decimal places, and compare it against the oven's `capacity_kg`: the comparison is strict, so a total that exceeds capacity is rejected with `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is accepted."
    PRD §3.9: "Batches may be listed filtered by `oven_id`, `run_id` and `batch_status`."

    Design: Difficulty/boundary_precision_check/oven_aggregate_load_exactly_at_capacity_and_closed_interval_touch_on_heat_treat
    """
    world = _loaded_oven_world(api)

    touching = api.create_batch(
        F.batch_payload(
            world.oven_id,
            world.run_id,
            window_start=_TOUCHING_START,
            window_end=_SECOND_BATCH_END,
            load_kg=_OVERFULL_LOAD_KG,
            target_temp_c=_BATCH_TEMP_C,
            peening_requested=False,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(touching, ERR_OVEN_CAPACITY_EXCEEDED, 409)

    clear = validate_success(
        api.create_batch(
            F.batch_payload(
                world.oven_id,
                world.run_id,
                window_start=_CLEAR_START,
                window_end=_SECOND_BATCH_END,
                load_kg=_OVERFULL_LOAD_KG,
                target_temp_c=_BATCH_TEMP_C,
                peening_requested=False,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        201,
    )
    assert clear["window_start"].startswith("2026-08-05T13:01:00"), (
        "the accepted window opens one minute after the resident basket's closed end, got "
        f"{clear['window_start']}"
    )
    assert clear["load_kg"] == _OVERFULL_LOAD_KG, (
        f"the very load refused at 13:00 is accepted at 13:01, got {clear['load_kg']}"
    )
    assert clear["batch_status"] == C.BATCH_SCHEDULED, (
        f"a non-colliding booking opens SCHEDULED, got {clear['batch_status']}"
    )

    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == A.round_half_up(
        _FIRST_LOAD_KG + _OVERFULL_LOAD_KG, 3
    ), f"the oven's booked total is now 260.000 kg, got {oven['scheduled_load_kg']}"
    assert oven["scheduled_load_kg"] > oven["capacity_kg"], (
        "the field sums every scheduled batch, colliding or not, so it may legally exceed "
        f"capacity, got {oven['scheduled_load_kg']} against {oven['capacity_kg']}"
    )

    batches, meta = validate_paginated(
        api.list_batches(
            PROCESS_TECHNICIAN_HEADERS,
            {"oven_id": world.oven_id, "batch_status": C.BATCH_SCHEDULED},
        )
    )
    assert meta["total_count"] == 2, (
        f"one refusal and two bookings leave two scheduled batches, got {meta['total_count']}"
    )
    assert {b["id"] for b in batches} == {world.batch_id, clear["id"]}, (
        "the two scheduled batches are the resident basket and the 13:01 booking"
    )


def test_one_kilogram_over_a_full_oven_waits_for_a_cancellation(api):
    """At 250.000 kg the oven refuses a single further kilogram until a basket is pulled.

    PRD §3.9: "Oven windows are **closed** intervals, so two windows collide even when they merely touch at a single endpoint: they collide when the first window's start is at or before the second window's end **and** the second window's start is at or before the first window's end."
    PRD §3.9: "Sum `load_kg` over every batch on the same oven whose `batch_status` is `SCHEDULED` or `RUNNING` and whose window collides with the new one; batches that are `CANCELLED` or `COMPLETE` are excluded even when their windows collide, because their mass has left the oven."
    PRD §3.9: "Add the new batch's `load_kg` to that occupied total, round the sum half up to three decimal places, and compare it against the oven's `capacity_kg`: the comparison is strict, so a total that exceeds capacity is rejected with `ERR_OVEN_CAPACITY_EXCEEDED` (HTTP 409) while a total exactly equal to capacity is accepted."
    PRD §3.9: "Cancelling a batch is available only from `SCHEDULED`; anything else answers `ERR_BATCH_INVALID_STATE`."
    PRD §3.9: "The batch moves to `CANCELLED` and its `load_kg` is removed from the oven's `scheduled_load_kg`, so the interval it occupied stops counting toward capacity for every later batch booking."

    Design: Difficulty/boundary_precision_check/oven_aggregate_load_exactly_at_capacity_and_closed_interval_touch_on_heat_treat
    """
    world = _loaded_oven_world(api)

    def _book(load_kg):
        return api.create_batch(
            F.batch_payload(
                world.oven_id,
                world.run_id,
                window_start=_TOUCHING_START,
                window_end=_SECOND_BATCH_END,
                load_kg=load_kg,
                target_temp_c=_BATCH_TEMP_C,
                peening_requested=False,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        )

    filling = validate_success(_book(_FITTING_LOAD_KG), 201)
    full = X.refresh_oven(api, world.oven_id)
    assert full["scheduled_load_kg"] == _OVEN_CAPACITY_KG, (
        f"the two baskets fill the oven exactly, got {full['scheduled_load_kg']}"
    )

    validate_error(_book(_ONE_KILOGRAM), ERR_OVEN_CAPACITY_EXCEEDED, 409)
    still_full = X.refresh_oven(api, world.oven_id)
    assert still_full["scheduled_load_kg"] == _OVEN_CAPACITY_KG, (
        "one kilogram over capacity is refused and posts nothing, got "
        f"{still_full['scheduled_load_kg']}"
    )

    cancelled = validate_success(
        api.cancel_batch(filling["id"], PROCESS_TECHNICIAN_HEADERS), 200
    )
    assert cancelled["batch_status"] == C.BATCH_CANCELLED, (
        f"pulling the 70 kg basket cancels it, got {cancelled['batch_status']}"
    )
    assert cancelled["load_kg"] == _FITTING_LOAD_KG, (
        f"the cancelled batch keeps its weighed load on the record, got {cancelled['load_kg']}"
    )

    freed = X.refresh_oven(api, world.oven_id)
    assert freed["scheduled_load_kg"] == _FIRST_LOAD_KG, (
        f"the cancelled mass leaves the oven's booked total, got {freed['scheduled_load_kg']}"
    )

    admitted = validate_success(_book(_ONE_KILOGRAM), 201)
    assert admitted["load_kg"] == _ONE_KILOGRAM, (
        "the kilogram refused a moment ago is now admitted over the very same window, got "
        f"{admitted['load_kg']}"
    )
    assert admitted["batch_status"] == C.BATCH_SCHEDULED, (
        f"the readmitted basket opens SCHEDULED, got {admitted['batch_status']}"
    )

    oven = X.refresh_oven(api, world.oven_id)
    assert oven["scheduled_load_kg"] == A.round_half_up(
        _FIRST_LOAD_KG + _ONE_KILOGRAM, 3
    ), f"the oven carries 181.000 kg once the 70 kg basket is out, got {oven['scheduled_load_kg']}"

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        f"no basket was ever charged, got {run['heat_treat_state']}"
    )
