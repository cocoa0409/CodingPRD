"""State machines: the cyclic quote/revise loop, the damage-report charge/waive
branch, lifecycle preconditions, idempotency, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error,
    set_clock, new_customer, new_venue, new_equipment, new_order,
    add_reservation, quote, submit_coi, approve_coi,
    setup_confirmed_order_single_led, setup_in_event_order_single_led,
    make_client_headers,
)


# ─── non_linear_state_machine / order_quote_revise_cycle ──────────────
def test_revise_returns_quoted_order_to_draft_and_clears_pricing_variant(api, account_manager_headers):
    """PRD §3.6: "Should the client request changes, an `AccountManager` revises a
    quoted order, returning it from `QUOTED` to `DRAFT` so reservations and assignments
    can be added or released and the order re-quoted."
    PRD §3.6: "Revision sets `pricing_variant` back to `NONE`, marking the prior quote
    stale, and increments the order's `version`."

    Design: Difficulty/non_linear_state_machine/order_quote_revise_cycle
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=1)
    quote(order["id"])

    revised = validate_success(api.revise_order(order["id"], account_manager_headers), 200)
    assert revised["status"] == "DRAFT"
    assert revised["pricing_variant"] == "NONE"


def test_requote_after_revise_returns_quoted_and_provisional(api, account_manager_headers):
    """PRD §3.6: "Quoting runs the full provisional pricing pass, sets `pricing_variant`
    to `PROVISIONAL`, and increments the order's `version`."
    PRD §3.6: "This draft-and-quote loop may repeat any number of times."

    Design: Difficulty/non_linear_state_machine/order_quote_revise_cycle
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    order = new_order(cust["id"], ven["id"])
    add_reservation(order["id"], led["id"], qty=1)
    quote(order["id"])
    validate_success(api.revise_order(order["id"], account_manager_headers), 200)

    requoted = validate_success(api.quote_order(order["id"], account_manager_headers), 200)
    assert requoted["status"] == "QUOTED"
    assert requoted["pricing_variant"] == "PROVISIONAL"


# ─── non_linear_state_machine / damage_report_branch_charge_vs_waive ──
def test_charge_branch_captures_deposit(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "The captured amount is the smaller of the report's `assessed_cost_cents`
    and the deposit's running remaining balance — where that remaining balance is
    `deposit_held_cents` less `deposit_captured_cents` less `deposit_released_cents`. That
    amount is written to the report's `captured_cents`, a deposit ledger entry of type
    `CAPTURE` is written for it carrying the report's `damage_report_id`, and the order's
    `deposit_captured_cents` (the sum of all `CAPTURE` amounts), `deposit_outstanding_cents`,
    `deposit_at_risk_cents`, and `open_damage_count` are all recomputed, with the open
    count falling by one."

    Design: Difficulty/non_linear_state_machine/damage_report_branch_charge_vs_waive
    """
    ctx = setup_in_event_order_single_led(qty=2)
    dr = validate_success(api.create_damage_report(
        ctx["ord_id"], {"reservation_id": ctx["res_id"], "damaged_units": 1},
        warehouse_manager_headers), 201)
    validate_success(api.assess_damage_report(
        dr["id"], {"assessed_cost_cents": 100000}, warehouse_manager_headers), 200)

    charged = validate_success(api.charge_damage_report(dr["id"], account_manager_headers), 200)
    assert charged["status"] == "CHARGED"
    assert charged["captured_cents"] == 100000, charged["captured_cents"]
    order = validate_success(api.get_order(ctx["ord_id"], account_manager_headers), 200)
    assert order["deposit_captured_cents"] == 100000, order["deposit_captured_cents"]


def test_waive_branch_captures_nothing(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "The alternative path, waiving a report, moves it from `ASSESSED` to
    `WAIVED` without moving any money: no ledger entry is written, and only the order's
    `deposit_at_risk_cents` and `open_damage_count` (again falling by one) are
    recomputed."

    Design: Difficulty/non_linear_state_machine/damage_report_branch_charge_vs_waive
    """
    ctx = setup_in_event_order_single_led(qty=2)
    dr = validate_success(api.create_damage_report(
        ctx["ord_id"], {"reservation_id": ctx["res_id"], "damaged_units": 1},
        warehouse_manager_headers), 201)
    validate_success(api.assess_damage_report(
        dr["id"], {"assessed_cost_cents": 100000}, warehouse_manager_headers), 200)

    waived = validate_success(api.waive_damage_report(dr["id"], account_manager_headers), 200)
    assert waived["status"] == "WAIVED"
    assert waived["captured_cents"] == 0, waived["captured_cents"]
    order = validate_success(api.get_order(ctx["ord_id"], account_manager_headers), 200)
    assert order["deposit_captured_cents"] == 0, order["deposit_captured_cents"]


# ─── state_machines / approve_coi_twice_second_returns_invalid_state ──
def test_approve_coi_twice_second_rejected(api, account_manager_headers):
    """PRD §3.5: "Approval moves it from `SUBMITTED` to `APPROVED`, but only if two
    conditions both hold: the certificate's `coverage_amount_cents` must be at least the
    `required_coverage_cents` of the order's venue, and its `expiry_date` must be strictly
    after the order's `event_end_date`."
    PRD §2.7: "The target resource must be in a state that admits the requested
    transition, and for child-creation endpoints the parent order must be in an
    accepting lifecycle state (detailed per workflow in §3). A violation yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_coi_twice_second_returns_invalid_state
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    order = new_order(cust["id"], ven["id"])
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=100000)
    approve_coi(coi["id"])

    res = api.approve_coi(coi["id"], account_manager_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── state_machines / reject_then_approve_returns_invalid_state_terminal_lockdown ──
def test_approve_rejected_coi_returns_invalid_state(api, account_manager_headers):
    """PRD §3.5: "Alternatively, an `AccountManager` may reject a submitted certificate,
    moving it to `REJECTED` and recording the supplied `reason` into the certificate's
    `reject_reason`; a rejection leaves `has_approved_coi` unchanged, so the order remains
    uninsured unless some other approved certificate already exists for it."
    PRD §2.7: "The target resource must be in a state that admits the requested
    transition, and for child-creation endpoints the parent order must be in an accepting
    lifecycle state (detailed per workflow in §3). A violation yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reject_then_approve_returns_invalid_state_terminal_lockdown
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    order = new_order(cust["id"], ven["id"])
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=100000)
    validate_success(api.reject_coi(coi["id"], {"reason": "bad form"}, account_manager_headers), 200)

    res = api.approve_coi(coi["id"], account_manager_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── state_machines / quote_order_with_no_reservations_rejected ───────
def test_quote_without_reservations_rejected(api, account_manager_headers):
    """PRD §3.6: "If the order has no reservation in `HELD` at all, the quote is refused
    with `ERR_NO_RESERVATIONS`."

    Design: Corner/state_machines/quote_order_with_no_reservations_rejected
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    order = new_order(cust["id"], ven["id"])

    res = api.quote_order(order["id"], account_manager_headers)
    validate_error(res, "ERR_NO_RESERVATIONS", expected_status=409)


# ─── state_machines / coi_expiry_on_event_end_returns_expired ─────────
def test_coi_expiry_on_event_end_rejected(api, account_manager_headers):
    """PRD §3.5: "one whose expiry date is on or before the event's last day is rejected
    with `ERR_COI_EXPIRED`."

    Design: Corner/state_machines/coi_expiry_on_event_end_returns_expired
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    order = new_order(cust["id"], ven["id"], event_start_date="2026-06-10",
                     event_end_date="2026-06-12")
    coi = submit_coi(order["id"], cust["id"], coverage_amount_cents=100000,
                     expiry_date="2026-06-12")

    res = api.approve_coi(coi["id"], account_manager_headers)
    validate_error(res, "ERR_COI_EXPIRED", expected_status=409)


# ─── state_machines / start_event_with_held_reservation_returns_not_checked_out ──
def test_start_event_with_held_reservation_rejected(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.8: "An `AccountManager` starts the event, advancing the order from
    `LOADED_OUT` to `IN_EVENT`, but only once every reservation is either `CHECKED_OUT`
    or `RELEASED`; if any reservation is still merely held, the transition is refused
    with `ERR_RESERVATIONS_NOT_CHECKED_OUT`."

    Design: Corner/state_machines/start_event_with_held_reservation_returns_not_checked_out
    """
    ctx = setup_confirmed_order_single_led()
    validate_success(api.load_out_order(ctx["ord_id"], warehouse_manager_headers), 200)

    res = api.start_event_order(ctx["ord_id"], account_manager_headers)
    validate_error(res, "ERR_RESERVATIONS_NOT_CHECKED_OUT", expected_status=409)


# ─── state_machines / load_in_with_checked_out_reservation_returns_not_checked_in ──
def test_load_in_with_checked_out_reservation_rejected(api, warehouse_manager_headers):
    """PRD §3.8: "Once all outstanding gear has come back, a `WarehouseManager` records
    load-in, advancing the order from `IN_EVENT` to `LOADED_IN`; this requires that
    every reservation that had been checked out is now either `CHECKED_IN` or `DAMAGED`,
    and a still-out reservation refuses the transition with
    `ERR_RESERVATIONS_NOT_CHECKED_IN`."

    Design: Corner/state_machines/load_in_with_checked_out_reservation_returns_not_checked_in
    """
    ctx = setup_in_event_order_single_led()  # reservation is CHECKED_OUT, order IN_EVENT

    res = api.load_in_order(ctx["ord_id"], warehouse_manager_headers)
    validate_error(res, "ERR_RESERVATIONS_NOT_CHECKED_IN", expected_status=409)


# ─── state_machines / settle_with_open_damage_report_rejected ─────────
def test_settle_with_open_damage_report_rejected(api, account_manager_headers, warehouse_manager_headers):
    """PRD §3.9: "An `AccountManager` settles a `LOADED_IN` order, advancing it to
    `SETTLED`, but only once every damage report on the order is either `CHARGED` or
    `WAIVED` — a still-open report refuses settlement with `ERR_OPEN_DAMAGE_REPORT`"

    Design: Corner/state_machines/settle_with_open_damage_report_rejected
    """
    ctx = setup_in_event_order_single_led(qty=2)
    dr = validate_success(api.create_damage_report(
        ctx["ord_id"], {"reservation_id": ctx["res_id"], "damaged_units": 1},
        warehouse_manager_headers), 201)
    validate_success(api.assess_damage_report(
        dr["id"], {"assessed_cost_cents": 50000}, warehouse_manager_headers), 200)
    validate_success(api.check_in_reservation(
        ctx["res_id"], {"damaged": False}, warehouse_manager_headers), 200)
    validate_success(api.load_in_order(ctx["ord_id"], warehouse_manager_headers), 200)

    res = api.settle_order(ctx["ord_id"], account_manager_headers)
    validate_error(res, "ERR_OPEN_DAMAGE_REPORT", expected_status=409)


# ─── state_machines / damage_report_cross_order_reservation_mismatch ──
def test_damage_report_cross_order_reservation_mismatch(api, warehouse_manager_headers):
    """PRD §2.10: "When a damage report or a sub-rental supplies a `reservation_id`, that
    reservation must belong to the same order named in the path; a reservation that
    exists but belongs to a different order is rejected with
    `ERR_RESERVATION_ORDER_MISMATCH`."

    Design: Corner/state_machines/damage_report_cross_order_reservation_mismatch
    """
    cust = new_customer(credit_limit_cents=100_000_000)
    ven = new_venue(required_coverage_cents=0)
    led = new_equipment()
    order_a = new_order(cust["id"], ven["id"], event_name="Order A")
    res_a = add_reservation(order_a["id"], led["id"], qty=1)
    order_b = new_order(cust["id"], ven["id"], event_name="Order B")

    res = api.create_damage_report(
        order_b["id"], {"reservation_id": res_a["id"], "damaged_units": 1},
        warehouse_manager_headers)
    validate_error(res, "ERR_RESERVATION_ORDER_MISMATCH", expected_status=409)
