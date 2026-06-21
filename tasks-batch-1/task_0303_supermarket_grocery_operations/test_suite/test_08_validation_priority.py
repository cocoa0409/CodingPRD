"""Validation-order precedence (PRD §2.10), cross-entity state dependencies, the
empty-sale boundary, the receiving variance gate, and start-receiving emptiness.

Translates difficulty instances (queue A: priority_pair_validation_conflict,
boundary_precision_check, cross_entity_state_dependency) and corner instances
(queue B: validations, errors).

The priority-conflict tests are legitimate because PRD §2.10 states an explicit
numbered priority order and that "A check earlier in this order always masks one
later", uniquely determining which error a PRD-only implementer returns.
"""
from test_helpers import (
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    fixtures,
)

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / sale_not_open_beats_insufficient_stock
# State (priority 6) masks business stock (priority 11).
# ---------------------------------------------------------------------------
def test_second_finalize_reports_sale_not_open_over_insufficient_stock(api):
    """PRD §2.10: "(6) the target resource being in a state that permits the requested transition, else the transition's specific state error ... (11) FEFO stock sufficiency, else `ERR_INSUFFICIENT_STOCK` ... A check earlier in this order always masks one later ..."
    PRD §3.7: "Finalizing advances `fulfillment_status` from `OPEN` to `FINALIZED` ... It is permitted only when the sale is `OPEN` (else `ERR_SALE_NOT_OPEN`) ..."

    Design: Difficulty/priority_pair_validation_conflict/sale_not_open_beats_insufficient_stock
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Oats", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                         expected_total_cents=500)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 5)
    fixtures.finalize_sale(sale["id"])  # now FINALIZED, on-hand 0
    resp = api.finalize_sale(sale["id"], {}, CSH)
    validate_error(resp, ApiErrorId.ERR_SALE_NOT_OPEN.value)


def test_finalized_sale_blocks_second_finalize_state_error(api):
    """PRD §3.7: "Adding a line, or finalizing or voiding the sale, requires the sale's `fulfillment_status` to be `OPEN`, else `ERR_SALE_NOT_OPEN`."
    PRD §2.10: "an unauthorized caller never learns whether the resource exists,
    and a malformed body is rejected before any state or stock reasoning."

    Design: Difficulty/priority_pair_validation_conflict/sale_not_open_beats_insufficient_stock
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Oats2", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100, expected_total_cents=500)
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 5)
    fixtures.finalize_sale(sale["id"])
    resp = api.finalize_sale(sale["id"], {}, CSH)
    # Confirm it is the state error and not the stock error.
    err = validate_error(resp, ApiErrorId.ERR_SALE_NOT_OPEN.value)
    assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_STOCK.value


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / product_not_found_beats_invalid_window_on_priceplan
# Existence (priority 3) masks window (priority 7).
# ---------------------------------------------------------------------------
def test_priceplan_missing_product_reports_not_found_over_invalid_window(api):
    """PRD §2.10: "(3) existence of every path id and body foreign key, validated left to right, else the matching not-found error ... (7) window validity, else `ERR_INVALID_WINDOW` ..."
    PRD §2.9: "every referenced id must resolve to an existing record of the right type, or the matching not-found error is returned (for example `ERR_PRODUCT_NOT_FOUND` ...)."

    Design: Difficulty/priority_pair_validation_conflict/product_not_found_beats_invalid_window_on_priceplan
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    # A real product exists to source a plausible version literal.
    decoy = fixtures.create_product(name="Decoy", unit_price_cents=99, reorder_point_qty=0)
    resp = api.create_price_plan(
        {"product_id": NON_EXISTENT_UUID, "ad_price_cents": 100,
         "effective_start": "2026-06-10T00:00:00Z",
         "effective_end": "2026-06-01T00:00:00Z",  # also an invalid window
         "expected_product_version": decoy["version"]}, PM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_priceplan_missing_product_not_invalid_window(api):
    """PRD §2.10: "A check earlier in this order always masks one later ..."
    PRD §2.8: "a window whose end is not strictly after its start is rejected with `ERR_INVALID_WINDOW` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/product_not_found_beats_invalid_window_on_priceplan
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    decoy = fixtures.create_product(name="Decoy2", unit_price_cents=99, reorder_point_qty=0)
    resp = api.create_price_plan(
        {"product_id": NON_EXISTENT_UUID, "ad_price_cents": 100,
         "effective_start": "2026-06-10T00:00:00Z",
         "effective_end": "2026-06-01T00:00:00Z",
         "expected_product_version": decoy["version"]}, PM)
    err = validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)
    assert err["error_id"] != ApiErrorId.ERR_INVALID_WINDOW.value


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / finalize_empty_sale_returns_sale_empty
# ---------------------------------------------------------------------------
def test_finalize_empty_sale_returns_sale_empty(api):
    """PRD §3.7: "It is permitted only when the sale is `OPEN` (else `ERR_SALE_NOT_OPEN`) and has at least one line item (else `ERR_SALE_EMPTY`) ..."

    Design: Difficulty/boundary_precision_check/finalize_empty_sale_returns_sale_empty
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    sale = fixtures.open_sale()
    resp = api.finalize_sale(sale["id"], {}, CSH)
    validate_error(resp, ApiErrorId.ERR_SALE_EMPTY.value)


def test_finalize_empty_sale_not_treated_as_open_error(api):
    """PRD §3.7: "and has at least one line item (else `ERR_SALE_EMPTY`) ..."
    PRD §2.10: "(6) the target resource being in a state that permits the requested
    transition, else the transition's specific state error ..."

    Design: Difficulty/boundary_precision_check/finalize_empty_sale_returns_sale_empty
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    sale = fixtures.open_sale()  # OPEN but no lines
    resp = api.finalize_sale(sale["id"], {}, CSH)
    err = validate_error(resp, ApiErrorId.ERR_SALE_EMPTY.value)
    assert err["error_id"] != ApiErrorId.ERR_SALE_NOT_OPEN.value


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / finalize_blocked_when_member_suspended
# ---------------------------------------------------------------------------
def test_finalize_blocked_when_member_suspended(api):
    """PRD §3.7: "if a `member_id` is set, that member must be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_when_member_suspended
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Salt", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100, expected_total_cents=500)
    member = fixtures.create_member(email="c@x.com")
    get_success_data(api.suspend_member(member["id"], SM))
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1, member_id=member["id"])
    resp = api.finalize_sale(sale["id"], {}, CSH)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


def test_suspend_then_finalize_member_active_precondition(api):
    """PRD §3.6: "Suspending requires the member to be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`, and moves it to `SUSPENDED` ..."
    PRD §3.7: "if a `member_id` is set, that member must be `ACTIVE`, else `ERR_MEMBER_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/finalize_blocked_when_member_suspended
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Salt2", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100, expected_total_cents=500)
    member = fixtures.create_member(email="c2@x.com")
    suspended = validate_success(api.suspend_member(member["id"], SM))
    assert suspended["status"] == "SUSPENDED"
    sale, _ = fixtures.open_sale_with_each_line(product["id"], 1, member_id=member["id"])
    resp = api.finalize_sale(sale["id"], {}, CSH)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Corner: validations / receive_variance_exceeded_without_override
# ---------------------------------------------------------------------------
def test_receive_variance_exceeded_without_override(api):
    """PRD §3.2: "if that scaled relative variance exceeds 500 basis points the receipt is rejected with `ERR_RECEIVE_VARIANCE_EXCEEDED`, unless a `StoreManager` sets `override_variance` to true on the receive."

    Design: Corner/validations/receive_variance_exceeded_without_override
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    dept = fixtures.create_department()
    product = fixtures.create_product(department_id=dept["id"], name="Var",
                                      unit_price_cents=120, reorder_point_qty=0)
    ship = get_success_data(api.create_shipment(
        {"vendor_name": "V", "reference_code": "REF-VAR", "expected_total_cents": 10000}, RC))
    get_success_data(api.add_shipment_line(
        ship["id"], {"product_id": product["id"], "ordered_qty": 100,
                     "accepted_qty": 100, "unit_cost_cents": 90}, RC))
    get_success_data(api.start_receiving(ship["id"], RC))
    # received 9000 vs expected 10000 -> 1000 bps > 500 tolerance, no override.
    resp = api.receive_shipment(
        ship["id"], {"expected_product_version": product["version"]}, RC)
    validate_error(resp, ApiErrorId.ERR_RECEIVE_VARIANCE_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Corner: errors / start_receiving_empty_shipment_returns_shipment_empty
# ---------------------------------------------------------------------------
def test_start_receiving_empty_shipment_returns_shipment_empty(api):
    """PRD §3.2: "this requires the shipment to be in `PENDING`, else `ERR_SHIPMENT_NOT_PENDING`, and requires at least one line in `OPEN`, else `ERR_SHIPMENT_EMPTY`."

    Design: Corner/errors/start_receiving_empty_shipment_returns_shipment_empty
    """
    ship = get_success_data(api.create_shipment(
        {"vendor_name": "V", "reference_code": "REF-EMPTY", "expected_total_cents": 100}, RC))
    resp = api.start_receiving(ship["id"], RC)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_EMPTY.value)
