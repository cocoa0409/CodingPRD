"""Validation-ladder precedence (§2.7) and boundary precision: state-beats-temporal,
safety-beats-fiscal, exact-unit and exact-coverage boundaries, OCC stale version, and
the fiscal credit ceiling."""
from test_helpers import (
    validate_success, validate_error,
    new_customer, new_venue, new_equipment, new_order, add_reservation,
    submit_coi, approve_coi, order_version,
    setup_confirmed_order_single_led, setup_quoted_order_single_led,
    create_reservation_payload,
)


# ─── priority_pair_validation_conflict / reserve_state_beats_temporal ──
def test_reserve_conflicting_state_and_capacity_returns_state_error(api, warehouse_manager_headers):
    """PRD §3.2: "Reservations may only be created while the parent order is in `DRAFT`
    or `QUOTED`; an attempt to reserve against an order in any other state is rejected
    with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/reserve_state_beats_temporal
    """
    ctx = setup_confirmed_order_single_led(qty=8)  # order CONFIRMED; LED total 20, 12 remain
    res = api.create_reservation(
        ctx["ord_id"],
        create_reservation_payload(ctx["led_id"], qty=20,
                                   reserve_start_date="2026-06-10",
                                   reserve_end_date="2026-06-12"),
        warehouse_manager_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_error_preempts_equipment_unavailable(api, warehouse_manager_headers):
    """PRD §2.7: "a lower-priority failure must never mask a higher-priority one."
    PRD §2.7: "The target resource must be in a state that admits the requested
    transition, and for child-creation endpoints the parent order must be in an
    accepting lifecycle state (detailed per workflow in §3). A violation yields
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/reserve_state_beats_temporal
    """
    ctx = setup_confirmed_order_single_led(qty=8)
    res = api.create_reservation(
        ctx["ord_id"],
        create_reservation_payload(ctx["led_id"], qty=20,
                                   reserve_start_date="2026-06-10",
                                   reserve_end_date="2026-06-12"),
        warehouse_manager_headers)
    error = validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert error["error_id"] != "ERR_EQUIPMENT_UNAVAILABLE"


# ─── priority_pair_validation_conflict / confirm_safety_beats_fiscal ──
def test_confirm_missing_coi_and_over_credit_returns_coi_error(api, account_manager_headers):
    """PRD §3.7: "The order must have a valid certificate on file — an `APPROVED`
    certificate whose coverage is at least the venue's `required_coverage_cents` and
    whose expiry is strictly after `event_end_date` — or it is refused with
    `ERR_COI_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_safety_beats_fiscal
    """
    # quote_total 32400 > credit_limit 1000, AND no approved COI exists.
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=1000)
    version = order_version(ctx["ord_id"])
    res = api.confirm_order(ctx["ord_id"], {"expected_order_version": version},
                            account_manager_headers)
    validate_error(res, "ERR_COI_NOT_APPROVED", expected_status=409)


def test_safety_error_preempts_fiscal_error(api, account_manager_headers):
    """PRD §2.7: "Where a valid certificate of insurance is required, it must exist, be
    approved, be adequate, and be unexpired; otherwise `ERR_COI_NOT_APPROVED`."
    PRD §2.7: "At confirmation, the provisional quote total must fit within the
    customer's credit limit; otherwise `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_safety_beats_fiscal
    """
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=1000)
    version = order_version(ctx["ord_id"])
    res = api.confirm_order(ctx["ord_id"], {"expected_order_version": version},
                            account_manager_headers)
    error = validate_error(res, "ERR_COI_NOT_APPROVED", expected_status=409)
    assert error["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"


# ─── boundary_precision_check / reserve_exact_available_units_boundary ──
def test_reserve_exactly_remaining_units_succeeds(api, warehouse_manager_headers):
    """PRD §3.2: "reserving exactly the number of remaining units succeeds, while a
    request for even one more unit than remains is rejected with
    `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/reserve_exact_available_units_boundary
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=12)  # 8 units remain

    ok = validate_success(api.create_reservation(
        order["id"], create_reservation_payload(led["id"], qty=8),
        warehouse_manager_headers), 201)
    assert ok["status"] == "HELD"
    assert ok["qty"] == 8


def test_reserve_one_unit_over_capacity_rejected(api, warehouse_manager_headers):
    """PRD §3.2: "a request for even one more unit than remains is rejected with
    `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Difficulty/boundary_precision_check/reserve_exact_available_units_boundary
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment(category="LED", total_units=20, daily_rate_cents=12000,
                        replacement_value_cents=500000)
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=12)  # 8 remain
    add_reservation(order["id"], led["id"], qty=8)   # exactly fills capacity, 0 remain

    res = api.create_reservation(
        order["id"], create_reservation_payload(led["id"], qty=1),
        warehouse_manager_headers)
    validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE", expected_status=409)


# ─── boundary_precision_check / coi_coverage_exact_required_boundary ──
def test_coi_coverage_exactly_meets_requirement_approves(api, account_manager_headers):
    """PRD §3.5: "the certificate's `coverage_amount_cents` must be at least the
    `required_coverage_cents` of the order's venue, and its `expiry_date` must be strictly
    after the order's `event_end_date`."

    Design: Difficulty/boundary_precision_check/coi_coverage_exact_required_boundary
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=2000000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    coi_a = submit_coi(order["id"], cust["id"], insurer="Aon",
                       coverage_amount_cents=2000000, expiry_date="2026-12-31")

    approved = validate_success(api.approve_coi(coi_a["id"], account_manager_headers), 200)
    assert approved["status"] == "APPROVED"


def test_coi_coverage_one_cent_short_rejected(api, account_manager_headers):
    """PRD §3.5: "A certificate whose coverage falls below the venue's requirement is
    rejected with `ERR_COI_INSUFFICIENT_COVERAGE`; one whose expiry date is on or before
    the event's last day is rejected with `ERR_COI_EXPIRED`."

    Design: Difficulty/boundary_precision_check/coi_coverage_exact_required_boundary
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=2000000)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    coi_b = submit_coi(order["id"], cust["id"], insurer="Aon",
                       coverage_amount_cents=1999999, expiry_date="2026-12-31")

    res = api.approve_coi(coi_b["id"], account_manager_headers)
    validate_error(res, "ERR_COI_INSUFFICIENT_COVERAGE", expected_status=409)


# ─── cross_cutting / confirm_stale_expected_version_conflict ──────────
def test_confirm_stale_version_conflict(api, account_manager_headers):
    """PRD §2.8: "Before confirmation proceeds, the server compares
    `expected_order_version` to the order's current `version`. If they differ — meaning
    the order has been advanced since the client last read it, so the quote the client is
    about to lock in is stale — the confirmation is rejected with `ERR_STALE_VERSION` and
    an HTTP status of 412."

    Design: Corner/cross_cutting/confirm_stale_expected_version_conflict
    """
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=100_000_000)
    coi = submit_coi(ctx["ord_id"], ctx["cust_id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])
    version = order_version(ctx["ord_id"])

    res = api.confirm_order(ctx["ord_id"], {"expected_order_version": version - 1},
                            account_manager_headers)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── cross_cutting / confirm_credit_limit_exceeded_fiscal ─────────────
def test_confirm_credit_limit_exceeded(api, account_manager_headers):
    """PRD §3.7: "the order's `quote_total_cents` must not exceed the owning customer's
    `credit_limit_cents`; a quote that would exceed the credit ceiling is refused with
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/cross_cutting/confirm_credit_limit_exceeded_fiscal
    """
    # quote_total 32400 > credit_limit 1000, but an APPROVED COI clears the safety gate.
    ctx = setup_quoted_order_single_led(qty=1, credit_limit_cents=1000)
    coi = submit_coi(ctx["ord_id"], ctx["cust_id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])
    version = order_version(ctx["ord_id"])

    res = api.confirm_order(ctx["ord_id"], {"expected_order_version": version},
                            account_manager_headers)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=409)
