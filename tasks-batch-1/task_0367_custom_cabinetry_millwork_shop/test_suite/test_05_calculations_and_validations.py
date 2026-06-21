"""Settlement late-fee tiering, cross-entity fiscal/state validations, and
domain error guards.

Breadth coverage of the Corner-design `calculations`, `validations`, and `errors`
sections: the late-fee tier-1 boundary and the on-time zero-fee case; credit-hold,
cross-shop, finish-required, and balance-outstanding validations; and the
empty-draw, reservation-locked, deposit-paid-cancel, and pagination errors.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    set_clock,
    setup_base_shop,
    setup_quoted_project,
    setup_contracted_project,
    setup_committed_reservation,
    create_shop,
    create_material,
    create_customer,
    create_project,
    add_spec,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]


# ===========================================================================
# Corner / calculations
# ===========================================================================
def test_draw_settlement_late_fee_tier1_boundary_30_days(api):
    """PRD §3.8: "if `days_late` is from 1 through 30 inclusive the rate is 150
    basis points; and if `days_late` is greater than 30 the rate is 400 basis
    points. The `late_fee_cents` is the draw's `amount_cents` multiplied by the
    selected rate, divided by 10000 and rounded half up."

    Design: Corner/calculations/draw_settlement_late_fee_tier1_boundary_30_days
    """
    # tax0 STAIN qty2 -> contract_total 291600. Clock 2026-06-01; a PROGRESS draw
    # at 1000 bps -> amount 29160, due 2026-06-10; paid at 2026-07-10 == 30 days late.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    set_clock(shop_id, "2026-06-01T00:00:00Z")

    # Issue+pay the deposit first to mirror the design chain, then a PROGRESS draw.
    dep_id = ctx["deposit_draw"]["id"]
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    prog = get_success_data(api.create_draw(
        shop_id, proj_id,
        {"draw_type": "PROGRESS", "requested_pct_bps": 1000, "due_utc": "2026-06-10T00:00:00Z"},
        MANAGER,
    ))
    assert prog["amount_cents"] == 29160, f"PROGRESS amount expected 29160, got {prog['amount_cents']}"
    get_success_data(api.issue_draw(shop_id, proj_id, prog["id"], MANAGER))

    set_clock(shop_id, "2026-07-10T00:00:00Z")
    paid = validate_success(api.pay_draw(shop_id, proj_id, prog["id"], cust))
    assert paid["late_fee_cents"] == 437, (
        f"late fee at 30 days (tier1 150bps of 29160 = rhu(437.4)) expected 437, got {paid['late_fee_cents']}"
    )


def test_draw_settlement_no_late_fee_when_paid_on_time(api):
    """PRD §3.8: "If the draw has no `due_utc`, or the shop's `current_utc` is at or
    before the `due_utc`, then the draw is not late and `days_late` is zero."

    Design: Corner/calculations/draw_settlement_no_late_fee_when_paid_on_time
    """
    # Clock 2026-06-01; the deposit draw has no due_utc, so it is never late.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    set_clock(shop_id, "2026-06-01T00:00:00Z")
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))

    paid = validate_success(api.pay_draw(shop_id, proj_id, dep_id, cust))
    assert paid["late_fee_cents"] == 0, f"on-time (no due_utc) late fee expected 0, got {paid['late_fee_cents']}"


# ===========================================================================
# Corner / validations
# ===========================================================================
def test_contract_blocked_when_customer_on_credit_hold(api):
    """PRD §2.10: "A customer flagged with `credit_hold` set to true may neither
    have a new draw issued nor accept a new contract; both attempts are rejected
    with `ERR_CUSTOMER_CREDIT_HOLD`."

    Design: Corner/validations/contract_blocked_when_customer_on_credit_hold
    """
    ctx = setup_quoted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    cust_id = ctx["customer"]["id"]
    get_success_data(api.update_customer(shop_id, cust_id, {"credit_hold": True}, MANAGER))

    cust = make_customer_headers(cust_id)
    resp = api.contract_project(shop_id, proj_id, {"expected_project_version": ctx["quote_version"]}, cust)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value)


def test_cross_shop_material_reference_rejected(api):
    """PRD §3.6: "The referenced machine must belong to the same shop as the
    project — a material, machine, or project referenced from a different shop is
    rejected with `ERR_CROSS_SHOP_REFERENCE`, a check that also guards spec
    creation and reservation creation."

    Design: Corner/validations/cross_shop_material_reference_rejected
    """
    shop_a = create_shop(name="A")
    shop_b = create_shop(name="B")
    mat_b = create_material(shop_b["id"])
    customer = create_customer(shop_a["id"])
    project = create_project(shop_a["id"], customer["id"], title="P")

    resp = api.create_spec(
        shop_a["id"], project["id"],
        {"label": "B", "width_mm": 600, "height_mm": 720, "depth_mm": 560, "quantity": 2,
         "base_unit_price_cents": 100000, "material_id": mat_b["id"]},
        DESIGNER,
    )
    validate_error(resp, ApiErrorId.ERR_CROSS_SHOP_REFERENCE.value)


def test_quote_without_finish_rejected(api):
    """PRD §3.5: "Moving a `MEASURED` project to `QUOTED` requires that exactly one
    finish selection is active, failing with `ERR_FINISH_REQUIRED` otherwise; the
    quote step recomputes `estimate_total_cents` including the active finish's
    upcharge."

    Design: Corner/validations/quote_without_finish_rejected
    """
    shop, material, customer = setup_base_shop()
    project = create_project(shop["id"], customer["id"], title="P")
    add_spec(shop["id"], project["id"], material["id"], quantity=2, base_unit_price_cents=100000)
    get_success_data(api.measure_project(shop["id"], project["id"], DESIGNER))

    resp = api.quote_project(shop["id"], project["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_FINISH_REQUIRED.value)


def test_project_close_with_outstanding_balance_blocked(api):
    """PRD §3.10: "Closing requires the project to be fully paid —
    `paid_to_date_cents` must be at least `contract_total_cents`, otherwise
    `ERR_BALANCE_OUTSTANDING` — and requires that no punch item on any of the
    project's installations is still `OPEN`, otherwise `ERR_PUNCH_OPEN`."

    Design: Corner/validations/project_close_with_outstanding_balance_blocked
    """
    from test_helpers import setup_installed_project
    # INSTALLED with only the deposit paid -> balance still outstanding; no open punch.
    ctx = setup_installed_project(
        specs=[{"quantity": 2}], finish_code="STAIN",
        shop_overrides={"tax_rate_bps": 0, "deposit_pct_bps": 3000, "retainage_pct_bps": 1000, "max_installs_per_day": 2},
        build_start="2026-07-24T09:00:00Z", build_end="2026-07-24T12:00:00Z",
        install_date="2026-09-13", window_start="2026-09-13T08:00:00Z", window_end="2026-09-13T12:00:00Z",
    )
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    # The setup helper already issued and paid the deposit (only the deposit), so
    # the contract balance remains outstanding; do not re-issue the PAID deposit.

    resp = api.close_project(shop_id, proj_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)


# ===========================================================================
# Corner / errors
# ===========================================================================
def test_empty_draw_issue_returns_empty_draw_error(api):
    """PRD §2.10: "A draw whose computed `amount_cents` is zero cannot be issued,
    and the attempt is rejected with `ERR_EMPTY_DRAW`."
    PRD §3.8: "for a `PROGRESS` draw it is the contract total multiplied by the
    request's `requested_pct_bps`, divided by 10000 and rounded half up"

    Design: Corner/errors/empty_draw_issue_returns_empty_draw_error
    """
    # Contracted project; a PROGRESS draw at requested_pct_bps=0 -> amount 0.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    zero = get_success_data(api.create_draw(shop_id, proj_id, {"draw_type": "PROGRESS", "requested_pct_bps": 0}, MANAGER))
    assert zero["amount_cents"] == 0, f"PROGRESS at 0 bps expected amount 0, got {zero['amount_cents']}"

    resp = api.issue_draw(shop_id, proj_id, zero["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_EMPTY_DRAW.value)


def test_release_committed_reservation_while_in_production_locked(api):
    """PRD §3.6: "a `COMMITTED` reservation may be released only while the project
    is not `IN_PRODUCTION`, and an attempt to release a committed reservation
    during production is rejected with `ERR_RESERVATION_LOCKED`."

    Design: Corner/errors/release_committed_reservation_while_in_production_locked
    """
    # IN_PRODUCTION project with a COMMITTED reservation.
    ctx = setup_committed_reservation(reservation_sheets=3, restock=10)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    res_id = ctx["reservation"]["id"]

    resp = api.release_reservation(shop_id, proj_id, res_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_RESERVATION_LOCKED.value)


def test_cancel_contracted_after_deposit_paid_blocked(api):
    """PRD §3.10: "From `CONTRACTED`, cancellation is allowed only if nothing has
    been paid yet: `paid_to_date_cents` must be zero, otherwise the cancel is
    rejected with `ERR_DEPOSIT_PAID_NO_CANCEL`"

    Design: Corner/errors/cancel_contracted_after_deposit_paid_blocked
    """
    # CONTRACTED project with the deposit issued and paid.
    ctx = setup_contracted_project(specs=[{"quantity": 2}], finish_code="STAIN")
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api.pay_draw(shop_id, proj_id, dep_id, cust))

    resp = api.cancel_project(shop_id, proj_id, MANAGER)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_PAID_NO_CANCEL.value)


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A request whose `limit` falls outside the range of 1 through 100,
    or whose `offset` is negative, is rejected with `ERR_VALIDATION_PAGINATION`
    (HTTP 422)."

    Design: Corner/errors/pagination_limit_out_of_bounds_rejected
    """
    shop = create_shop()
    resp = api.list_materials(shop["id"], MANAGER, params={"limit": 200})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_PAGINATION.value)
