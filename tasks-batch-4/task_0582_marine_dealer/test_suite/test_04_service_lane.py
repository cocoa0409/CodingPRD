"""Service lane: RO reopen cycle, invoice→consume cascade, part reservation invariants."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    fixtures,
    create_service_line_payload, create_repair_order_payload,
)

MANAGER = TEST_USERS["manager_headers"]
SERVICE = TEST_USERS["service_advisor_headers"]
PARTS = TEST_USERS["parts_clerk_headers"]

DIAG = {"ro_type": "DIAGNOSTIC", "labor_rate_cents_per_hour": 11000,
        "tax_rate_bps": 700, "estimated_hours": 1.0}


# --- non_linear_state_machine: reopen back-edge ----------------------------------
def test_reopen_completed_repair_order_returns_in_progress(api):
    """PRD §3.5: "A completed order may be reopened, moving it from `COMPLETED` back to
    `IN_PROGRESS` and clearing `final_total_cents` until it is completed again."

    Design: Difficulty/non_linear_state_machine/repair_order_reopen_cycle
    """
    _u, _b, ro_done, _l = fixtures.create_completed_ro(ro_overrides=DIAG)
    reopened = validate_success(api.reopen_repair_order(ro_done["id"], SERVICE))
    assert reopened["status"] == "IN_PROGRESS", \
        f"Expected IN_PROGRESS after reopen, got {reopened['status']}"


def test_reopened_repair_order_can_be_recompleted(api):
    """PRD §3.5: "A completed order may be reopened, moving it from `COMPLETED` back to
    `IN_PROGRESS` and clearing `final_total_cents` until it is completed again." PRD
    §3.5: "Completing work moves it from `IN_PROGRESS` to `COMPLETED`".

    Design: Difficulty/non_linear_state_machine/repair_order_reopen_cycle
    """
    _u, _b, ro_done, _l = fixtures.create_completed_ro(ro_overrides=DIAG)
    validate_success(api.reopen_repair_order(ro_done["id"], SERVICE))
    recompleted = validate_success(api.complete_repair_order(ro_done["id"], SERVICE))
    assert recompleted["status"] == "COMPLETED", \
        f"Expected COMPLETED after re-complete, got {recompleted['status']}"


# --- transitive_cascade: invoice -> consume -> decrement stock -------------------
def test_invoice_marks_ro_invoiced_and_part_line_consumed(api):
    """PRD §3.6: "On a successful invoice, the order becomes `INVOICED`, which drives
    each `ACTIVE` non-warranty `PART` line to `CONSUMED`".

    Design: Difficulty/transitive_cascade/invoice_cascades_part_consume_available
    """
    part = fixtures.create_part(on_hand_qty=10, list_price_cents=6000)
    _u, _b, ro_done, lines = fixtures.create_completed_ro(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 2.0},
        lines=[("PART", {"part_id": part["id"], "quantity": 3, "unit_price_cents": 6000})],
    )
    invoiced = validate_success(api.invoice_repair_order(ro_done["id"], SERVICE))
    assert invoiced["status"] == "INVOICED", f"Expected INVOICED, got {invoiced['status']}"
    line = validate_success(api.get_service_line(lines[0]["id"], SERVICE))
    assert line["status"] == "CONSUMED", f"Expected CONSUMED, got {line['status']}"


def test_invoice_decrements_part_on_hand_and_recomputes_available(api):
    """PRD §3.6: "each consumed line decreases both the part's `on_hand_qty` and its
    `reserved_qty` by that line's `quantity`, and the part's `available_qty` is
    recomputed accordingly."

    Design: Difficulty/transitive_cascade/invoice_cascades_part_consume_available
    """
    part = fixtures.create_part(on_hand_qty=10, list_price_cents=6000)
    _u, _b, ro_done, _l = fixtures.create_completed_ro(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 2.0},
        lines=[("PART", {"part_id": part["id"], "quantity": 3, "unit_price_cents": 6000})],
    )
    validate_success(api.invoice_repair_order(ro_done["id"], SERVICE))
    p = validate_success(api.get_part(part["id"], PARTS))
    assert p["on_hand_qty"] == 7, f"Expected on_hand 7, got {p['on_hand_qty']}"
    assert p["reserved_qty"] == 0, f"Expected reserved 0, got {p['reserved_qty']}"
    assert p["available_qty"] == 7, f"Expected available 7, got {p['available_qty']}"


# --- compensating_invariant: reserve then void conserves inventory ---------------
def test_void_part_line_releases_reservation(api):
    """PRD §3.6: "When a `PART` line is voided, the part's `reserved_qty` decreases by
    that line's `quantity` and its `available_qty` is recomputed."

    Design: Difficulty/compensating_invariant/part_reserve_then_void_conserves_inventory
    """
    part = fixtures.create_part(on_hand_qty=10, list_price_cents=9000)
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    line = fixtures.add_service_line(ro["id"], "PART", part_id=part["id"],
                                     quantity=4, unit_price_cents=9000)
    voided = validate_success(api.void_service_line(line["id"], SERVICE))
    assert voided["status"] == "VOID", f"Expected VOID, got {voided['status']}"
    p = validate_success(api.get_part(part["id"], PARTS))
    assert p["reserved_qty"] == 0, f"Expected reserved 0, got {p['reserved_qty']}"
    assert p["available_qty"] == 10, f"Expected available 10, got {p['available_qty']}"


def test_void_part_line_leaves_on_hand_untouched(api):
    """PRD §3.6: "`available_qty` is `on_hand_qty` minus `reserved_qty`." PRD §3.6:
    "When a `PART` line is voided, the part's `reserved_qty` decreases by that line's
    `quantity` and its `available_qty` is recomputed."

    Design: Difficulty/compensating_invariant/part_reserve_then_void_conserves_inventory
    """
    part = fixtures.create_part(on_hand_qty=10, list_price_cents=9000)
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    line = fixtures.add_service_line(ro["id"], "PART", part_id=part["id"],
                                     quantity=4, unit_price_cents=9000)
    validate_success(api.void_service_line(line["id"], SERVICE))
    p = validate_success(api.get_part(part["id"], PARTS))
    assert p["on_hand_qty"] == 10, f"Expected on_hand unchanged 10, got {p['on_hand_qty']}"


# --- boundary_precision_check: PART quantity floor at 1 --------------------------
def test_part_line_zero_quantity_rejected(api):
    """PRD §3.6: "a `PART` line whose `quantity` is less than 1 is rejected with
    `ERR_INVALID_QUANTITY` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/service_line_part_zero_quantity_rejected
    """
    part = fixtures.create_part(on_hand_qty=5, list_price_cents=1600)
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    payload = create_service_line_payload(ro["id"], "PART", part_id=part["id"],
                                          quantity=0, unit_price_cents=1600)
    validate_error(api.create_service_line(payload, SERVICE),
                   ApiErrorId.ERR_INVALID_QUANTITY.value)


def test_part_line_quantity_one_accepted(api):
    """PRD §3.6: "a part line must carry a `part_id` and a `quantity`". PRD §3.6: "a
    `PART` line whose `quantity` is less than 1 is rejected with `ERR_INVALID_QUANTITY`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/service_line_part_zero_quantity_rejected
    """
    part = fixtures.create_part(on_hand_qty=5, list_price_cents=1600)
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    payload = create_service_line_payload(ro["id"], "PART", part_id=part["id"],
                                          quantity=1, unit_price_cents=1600)
    line = validate_success(api.create_service_line(payload, SERVICE), expected_status=201)
    assert line["status"] == "ACTIVE"


# --- Corner: line guards, insufficient stock, window, computed availability -------
def test_part_line_missing_part_id_rejected(api):
    """PRD §3.6: "a `PART` line missing its `part_id` is rejected with
    `ERR_PART_REQUIRED_FOR_LINE` (HTTP 422)".

    Design: Corner/validations/part_line_missing_part_id_rejected
    """
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    payload = create_service_line_payload(ro["id"], "PART", quantity=2, unit_price_cents=1000)
    validate_error(api.create_service_line(payload, SERVICE),
                   ApiErrorId.ERR_PART_REQUIRED_FOR_LINE.value)


def test_labor_line_missing_hours_rejected(api):
    """PRD §3.6: "a `LABOR` line missing its `hours` is rejected with
    `ERR_HOURS_REQUIRED_FOR_LABOR` (HTTP 422)".

    Design: Corner/validations/labor_line_missing_hours_rejected
    """
    _u, _b, ro = fixtures.create_ro_scenario(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0})
    payload = create_service_line_payload(ro["id"], "LABOR", unit_price_cents=11000)
    validate_error(api.create_service_line(payload, SERVICE),
                   ApiErrorId.ERR_HOURS_REQUIRED_FOR_LABOR.value)


def test_invoice_insufficient_on_hand_stock_rejected(api):
    """PRD §3.6: "each such line's `quantity` must be less than or equal to the
    referenced part's `on_hand_qty`, otherwise the invoice is rejected with
    `ERR_INSUFFICIENT_STOCK` (HTTP 409)."

    Design: Corner/validations/invoice_insufficient_on_hand_stock_rejected
    """
    part = fixtures.create_part(on_hand_qty=5, list_price_cents=1500)
    _u, _b, ro_done, _l = fixtures.create_completed_ro(
        ro_overrides={"ro_type": "CUSTOM", "labor_rate_cents_per_hour": 11000,
                      "tax_rate_bps": 700, "estimated_hours": 1.0},
        lines=[("PART", {"part_id": part["id"], "quantity": 8, "unit_price_cents": 1500})],
    )
    validate_error(api.invoice_repair_order(ro_done["id"], SERVICE),
                   ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_repair_order_window_end_not_after_start_rejected(api):
    """PRD §3.5: "The window must be well-formed: `scheduled_end` must be strictly
    later than `scheduled_start`, otherwise the create is rejected with
    `ERR_SCHEDULE_WINDOW_INVALID` (HTTP 422)."

    Design: Corner/validations/repair_order_window_end_not_after_start_rejected
    """
    unit = fixtures.create_unit(acquisition_type="CASH")
    bay = fixtures.create_service_bay(bay_type="RIGGING")
    payload = create_repair_order_payload(
        unit["id"], bay["id"], ro_type="DIAGNOSTIC", estimated_hours=1.0,
        scheduled_start="2026-06-09T11:00:00Z", scheduled_end="2026-06-09T09:00:00Z")
    validate_error(api.create_repair_order(payload, SERVICE),
                   ApiErrorId.ERR_SCHEDULE_WINDOW_INVALID.value)


def test_part_available_qty_computed_on_create(api):
    """PRD §3.6: "`available_qty` is `on_hand_qty` minus `reserved_qty`." PRD §3.6:
    "`is_low` is true when `available_qty` is less than or equal to `reorder_point`."

    Design: Corner/entities/part_available_qty_computed_on_create
    """
    part = fixtures.create_part(on_hand_qty=12, reorder_point=3, list_price_cents=2400)
    p = validate_success(api.get_part(part["id"], PARTS))
    assert p["reserved_qty"] == 0, f"Expected reserved 0, got {p['reserved_qty']}"
    assert p["available_qty"] == 12, f"Expected available 12, got {p['available_qty']}"
    assert p["is_low"] is False, f"Expected is_low False, got {p['is_low']}"
