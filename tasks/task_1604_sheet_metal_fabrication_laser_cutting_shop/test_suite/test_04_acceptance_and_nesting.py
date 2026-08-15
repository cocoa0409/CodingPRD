"""Acceptance cascade, nesting/yield, capacity window, and renest behavior."""
from test_helpers import (
    CLERK,
    MGR,
    PLAN,
    ApiErrorId,
    accept_quote,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    find_remnant_for_order,
    get_order_steps,
    get_step_by_station,
    release_order,
    rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

LINE_300X200_BEND4 = {"bbox_width_mm": 300, "bbox_height_mm": 200,
                      "hole_count": 0, "corner_fillet_count": 0,
                      "bend_count": 4, "weld_inches": 0, "finish": "NONE"}
LINE_100X100_QTY2 = {"bbox_width_mm": 100, "bbox_height_mm": 100,
                     "hole_count": 0, "corner_fillet_count": 0,
                     "bend_count": 0, "weld_inches": 0, "finish": "NONE"}


# --- accept cascade (Difficulty: accept_cascade_nest_consumes_stock_creates_remnant)

def _accept_ten_panel_order():
    """10x 300x200 parts on one 1200x2400 sheet: one nest sheet, plate 11000,
    remnant top strip 1200x1800 (PRD §3.5 guillotine grid)."""
    grade = create_grade()
    customer = create_customer()
    sheet = create_full_sheet(grade["id"])
    create_machine("LASER")
    create_machine("BRAKE")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=LINE_300X200_BEND4, qty=10)
    order = accept_quote(submitted["id"], customer["id"])
    return grade, customer, sheet, submitted, order


def test_accept_consumes_stock_and_creates_remnant(api):
    """PRD §3.5: "Nesting consumes a sheet, moving it from AVAILABLE to
    CONSUMED; when the leftover offcut qualifies, a child REMNANT row is
    created in AVAILABLE status and linked to the consuming order through
    `source_order_id`." PRD §3.5: "When the winning remnant's area is at least
    2,000 square centimeters, a new sheet-stock row of kind REMNANT is created
    in AVAILABLE status with its `source_order_id` pointing at the order ..."

    Design: Difficulty/transitive_cascade/accept_cascade_nest_consumes_stock_creates_remnant
    """
    grade, customer, sheet, quote, order = _accept_ten_panel_order()

    parent = validate_success(api.get_sheet_stock(sheet["id"], CLERK))
    assert parent["status"] == "CONSUMED"

    remnant = find_remnant_for_order(order["id"])
    assert remnant is not None, "qualifying offcut must be stocked as a REMNANT"
    assert remnant["status"] == "AVAILABLE"
    assert remnant["kind"] == "REMNANT"
    assert remnant["source_order_id"] == order["id"]
    # Guillotine grid: cols = 1200//300 = 4, rows used = 3 (10 parts);
    # right strip is 0x2400, top strip is 1200x1800 and wins.
    assert remnant["width_mm"] == 1200
    assert remnant["height_mm"] == 1800


def test_accept_sets_nest_sheet_values_and_plate_area(api):
    """PRD §3.5: "Each consumed sheet yields a nest-sheet row: `sheet_index`
    is the zero-based sheet number within the order's nest, `sheet_stock_id`
    identifies the stock unit consumed, `chargeable_area_cm2` is the sum of
    the areas of the parts placed on it, `kerf_allowance_cm2` is a fixed
    5,000-square-centimeter skeleton and kerf allowance charged per sheet,
    `plate_in_area_cm2` is the sum of those two, and `yield_pct` is the
    chargeable area divided by the plate-in area, rounded half-up to four
    decimal places." PRD §3.5: "The order's `total_plate_area_cm2` is the sum
    of `plate_in_area_cm2` across its nest sheets."

    Design: Difficulty/transitive_cascade/accept_cascade_nest_consumes_stock_creates_remnant
    """
    _g, _c, _s, _q, order = _accept_ten_panel_order()

    sheets, _meta = validate_paginated(api.list_order_nest_sheets(order["id"], PLAN))
    assert len(sheets) == 1
    nest = sheets[0]
    assert nest["sheet_index"] == 0
    assert nest["chargeable_area_cm2"] == 6000.0  # 10 parts x 600 cm2
    assert nest["kerf_allowance_cm2"] == 5000
    assert nest["plate_in_area_cm2"] == 11000
    assert nest["yield_pct"] == 0.5455  # 6000/11000, round-half-up at 4 dp
    assert nest["remnant_stock_id"], "remnant link must be set when eligible"
    assert order["total_plate_area_cm2"] == 11000


# --- immediate consistency (Corner: accept_response_immediately_shows_committed_totals)

def test_accept_response_immediately_shows_committed_totals(api):
    """PRD §3.4: "The response carries the newly created order." PRD §3.5:
    "Once at least one nest sheet exists, the order leaves NESTING for NESTED
    and its committed totals are computed."

    Design: Corner/consistency_model/accept_response_immediately_shows_committed_totals
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=LINE_300X200_BEND4, qty=10)
    create_machine("BRAKE")
    resp = api.accept_quote(submitted["id"], rep_headers(customer))
    order = validate_success(resp, 201)
    assert order["status"] == "NESTED"
    assert order["total_plate_area_cm2"] == 11000
    assert isinstance(order["committed_total_cents"], int)


# --- nest feasibility (Corner: error_nest_infeasible_when_stock_too_small) --

def test_nest_infeasible_when_stock_too_small(api):
    """PRD §3.5: "Feasibility is enforced atomically: if no eligible stock row
    can hold the largest part, or the full-sheet and remnant pools together
    cannot fit every part, the operation is rejected with `ERR_NEST_INFEASIBLE`
    and no partial nest persists."

    Design: Corner/errors/error_nest_infeasible_when_stock_too_small
    """
    grade = create_grade()
    customer = create_customer()
    small = validate_success(
        api.create_sheet_stock(
            {"grade_id": grade["id"], "thickness_mm": 1.0,
             "width_mm": 600, "height_mm": 600},
            CLERK,
        ),
        201,
    )
    create_machine("LASER")
    submitted = create_submitted_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 800, "bbox_height_mm": 800,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 0},
    )
    resp = api.accept_quote(submitted["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_NEST_INFEASIBLE, 409)

    quote = validate_success(api.get_quote(submitted["id"], MGR))
    assert quote["status"] == "SUBMITTED"
    orders, _meta = validate_paginated(
        api.list_orders(MGR, params={"quote_id": submitted["id"]}))
    assert orders == []
    sheet = validate_success(api.get_sheet_stock(small["id"], CLERK))
    assert sheet["status"] == "AVAILABLE", "no partial nest may persist"


# --- remnant minimum area (Corner: remnant_below_min_area_not_stocked) ------

def test_remnant_below_min_area_not_stocked(api):
    """PRD §3.5: "When the winning remnant's area is at least 2,000 square
    centimeters, a new sheet-stock row of kind REMNANT is created in AVAILABLE
    status with its `source_order_id` pointing at the order, and the nest
    sheet's `remnant_stock_id` links to it; otherwise the offcut is scrapped
    without creating any row."

    Design: Corner/calculations/remnant_below_min_area_not_stocked
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 1150, "bbox_height_mm": 2300,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 0},
    )
    order = accept_quote(submitted["id"], customer["id"])

    # right strip 50x2400 = 1200 cm2, top strip 1150x100 = 1150 cm2; the
    # larger candidate (1200) is below the 2,000 cm2 remnant minimum.
    remnant = find_remnant_for_order(order["id"])
    assert remnant is None, "offcut under 2,000 cm2 must not be stocked"
    sheets, _meta = validate_paginated(api.list_order_nest_sheets(order["id"], PLAN))
    assert len(sheets) == 1
    assert sheets[0].get("remnant_stock_id") in (None, ""), (
        "no remnant link when the offcut is scrapped"
    )


# --- renest (Corner: renest_recomputes_totals) ------------------------------

def test_renest_recomputes_totals_deterministically(api):
    """PRD §3.5: "Re-nesting is a self-loop rebuild available while the order
    is in NESTING or NESTED: the existing nest-sheet rows are discarded, their
    stock is released and re-selected, a fresh nest is built, and the committed
    totals are recomputed." PRD §3.5: "a `ProductionPlanner` may re-run it
    while an order is still in NESTING or NESTED — re-nesting from any other
    status is rejected with `ERR_INVALID_STATE`."

    Design: Corner/endpoints/renest_recomputes_totals
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    create_full_sheet(grade["id"])
    create_machine("LASER")
    submitted = create_submitted_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 300, "bbox_height_mm": 200,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 0},
        qty=10,
    )
    order = accept_quote(submitted["id"], customer["id"])
    assert order["total_plate_area_cm2"] == 11000

    renested = validate_success(api.renest_order(order["id"], PLAN))
    assert renested["status"] == "NESTED"
    assert renested["total_plate_area_cm2"] == 11000, (
        "unchanged inputs must recompute deterministically"
    )

    released = release_order(order["id"])
    assert released["status"] == "IN_PRODUCTION"
    resp = api.renest_order(order["id"], PLAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


# --- credit limit aggregate (Corner: credit_limit_aggregate_validation) -----

def test_credit_limit_aggregate_validation(api):
    """PRD §3.4: "only then the fiscal check applies — the sum of
    `quoted_total_cents` over the customer's quotes that already have accepted
    orders, plus this quote's `quoted_total_cents`, must not exceed the
    customer's `credit_limit_cents`, or the acceptance is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    Design: Corner/validations/credit_limit_aggregate_validation
    """
    grade = create_grade()
    customer = create_customer(credit_limit_cents=30000)
    create_full_sheet(grade["id"])
    create_full_sheet(grade["id"])
    create_machine("LASER")
    create_machine("BRAKE")

    qa = create_submitted_quote(customer["id"], grade["id"],
                                line_overrides=LINE_300X200_BEND4, qty=9)
    qb = create_submitted_quote(customer["id"], grade["id"],
                                line_overrides=LINE_300X200_BEND4, qty=9)

    first = api.accept_quote(qa["id"], rep_headers(customer))
    validate_success(first, 201)

    resp = api.accept_quote(qb["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)

    quote_b = validate_success(api.get_quote(qb["id"], MGR))
    assert quote_b["status"] == "SUBMITTED"


# --- machine selector (Corner: machine_selector_least_loaded_then_created_at)

def test_machine_selector_excludes_down_machine(api):
    """PRD §3.6: "Eligible machines are those whose `station` matches the
    step's station and whose `status` is ACTIVE. The selector picks the machine
    with the least booked minutes in the rolling horizon and breaks ties by
    earliest machine `created_at` ..."

    Design: Corner/calculations/machine_selector_least_loaded_then_created_at
    """
    grade = create_grade()
    machine_a = create_machine("LASER")          # earlier created_at
    machine_b = create_machine("LASER")
    validate_success(api.set_machine_status(machine_b["id"], "DOWN", MGR))
    customer = create_customer()
    create_full_sheet(grade["id"])
    submitted = create_submitted_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 50, "bbox_height_mm": 50,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 0},
    )
    order = accept_quote(submitted["id"], customer["id"])

    steps = get_order_steps(order["id"])
    laser = get_step_by_station(steps, "LASER")
    assert laser["machine_id"] == machine_a["id"], (
        "the DOWN machine must be excluded from the candidate set"
    )


# --- capacity window (Difficulty: machine_capacity_utilization_cap_window) --

def _tiny_laser_setup():
    """Machine with 1 bookable minute/day: 12-day capacity 12, cap 0.90 ->
    10.8 feasible minutes. Each 100x100 qty-2 order plans 6 LASER minutes
    (ceil(2*28/60) + one sheet x 5 load minutes)."""
    grade = create_grade()
    customer = create_customer()
    machine = create_machine("LASER", shift_minutes_per_day=1)
    create_full_sheet(grade["id"])
    create_full_sheet(grade["id"])
    return grade, customer, machine


def _submitted_small_quote(customer_id, grade_id):
    return create_submitted_quote(customer_id, grade_id,
                                  line_overrides=LINE_100X100_QTY2, qty=2)


def test_capacity_window_admits_within_cap_and_rejects_over(api):
    """PRD §3.6: "A machine's capacity over the horizon is its
    `shift_minutes_per_day` multiplied by twelve. A candidate machine can
    absorb a step only while its booked load plus the step's `planned_minutes`
    stays within ninety percent of capacity: a machine landing exactly at that
    cap remains feasible, while one minute over is not." PRD §3.6: "When no
    ACTIVE machine of a required station qualifies, the operation is rejected
    with `ERR_NO_MACHINE_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/machine_capacity_utilization_cap_window
    """
    grade, customer, machine = _tiny_laser_setup()

    q1 = _submitted_small_quote(customer["id"], grade["id"])
    order1 = accept_quote(q1["id"], customer["id"])
    laser = get_step_by_station(get_order_steps(order1["id"]), "LASER")
    assert laser["planned_minutes"] == 6  # ceil(2*28s/60) + 1 sheet x 5 load
    # 6 <= 12 * 0.90 = 10.8 -> feasible (inclusive boundary)

    q2 = _submitted_small_quote(customer["id"], grade["id"])
    resp = api.accept_quote(q2["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_NO_MACHINE_CAPACITY, 409)  # 6+6=12 > 10.8

    quote2 = validate_success(api.get_quote(q2["id"], MGR))
    assert quote2["status"] == "SUBMITTED", "failed accept is atomic"
    orders, _meta = validate_paginated(
        api.list_orders(MGR, params={"quote_id": q2["id"]}))
    assert orders == []


def test_completed_step_releases_capacity_for_next_order(api):
    """PRD §3.6: "This accounting runs at routing generation, releases a step's
    minutes when the step completes or is skipped, re-reserves them on rework
    resets, and re-validates on resume and re-nest." PRD §3.6: "A machine's
    booked load is the sum of `planned_minutes` over its routing steps in
    PENDING or IN_PROGRESS status whose `due_date` falls inside the window
    from now through the end of the horizon."

    Design: Difficulty/resource_temporal_overlap/machine_capacity_utilization_cap_window
    """
    from test_helpers import complete_step
    grade, customer, machine = _tiny_laser_setup()

    q1 = _submitted_small_quote(customer["id"], grade["id"])
    order1 = accept_quote(q1["id"], customer["id"])
    release_order(order1["id"])
    laser = get_step_by_station(get_order_steps(order1["id"]), "LASER")
    complete_step(laser["id"])  # releases the 6 booked minutes

    q2 = _submitted_small_quote(customer["id"], grade["id"])
    resp = api.accept_quote(q2["id"], rep_headers(customer))
    order2 = validate_success(resp, 201)
    assert order2["id"], "freed minutes make the follow-on order feasible"


# --- atomic cascade failure (Corner: cascading_accept_failure_is_atomic) ----

def test_cascading_accept_failure_is_atomic(api):
    """PRD §3.4: "A successful acceptance fires a single atomic cascade."
    PRD §3.4: "... if no ACTIVE machine of a required station can absorb the
    work it fails with `ERR_NO_MACHINE_CAPACITY`."

    Design: Corner/cross_cutting_layers/cascading_accept_failure_is_atomic
    """
    grade, customer, machine = _tiny_laser_setup()

    q1 = _submitted_small_quote(customer["id"], grade["id"])
    accept_quote(q1["id"], customer["id"])

    # The second full sheet is untouched so far; only capacity blocks quote 2.
    # (The first order's nest also stocked an AVAILABLE remnant row, so filter
    # by kind to isolate the spare full sheet.)
    sheets, _meta = validate_paginated(
        api.list_sheet_stock(CLERK, params={"grade_id": grade["id"],
                                            "status": "AVAILABLE",
                                            "kind": "FULL_SHEET"}))
    assert len(sheets) == 1
    spare_id = sheets[0]["id"]

    q2 = _submitted_small_quote(customer["id"], grade["id"])
    resp = api.accept_quote(q2["id"], rep_headers(customer))
    validate_error(resp, ApiErrorId.ERR_NO_MACHINE_CAPACITY, 409)

    spare = validate_success(api.get_sheet_stock(spare_id, CLERK))
    assert spare["status"] == "AVAILABLE", "nest consumption must roll back"
    orders, _meta = validate_paginated(
        api.list_orders(MGR, params={"quote_id": q2["id"]}))
    assert orders == []
    quote2 = validate_success(api.get_quote(q2["id"], MGR))
    assert quote2["status"] == "SUBMITTED"
