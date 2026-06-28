"""Service plans: PRORATED vs FORFEIT refund variants, the grace-period prorate,
the installed-project activation gate, the seasonal cycle counter, and the
pending-plan close block.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_installed_project,
    setup_project_with_transformer_and_zone,
    assign_fixtures_to_zone,
    setup_accepted_quote,
    create_pending_service_plan,
    set_clock,
    make_customer_headers,
    api_client,
    TEST_USERS,
)
import test_helpers.factories as F

DESIGNER = TEST_USERS["lighting_designer_headers"]
TECH = TEST_USERS["install_tech_headers"]
ADMIN = TEST_USERS["operations_admin_headers"]


def _wallet(api, cust_id):
    return validate_success(api.get_customer(cust_id, ADMIN))["wallet_credit_cents"]


def _activate_plan(api, ctx, plan_id):
    return validate_success(api.activate_service_plan(plan_id, make_customer_headers(ctx["cust_id"])))


def _cancel_plan(api, ctx, plan_id):
    return validate_success(api.cancel_service_plan(plan_id, make_customer_headers(ctx["cust_id"])))


# ---------------------------------------------------------------------------
# PRORATED vs FORFEIT (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------
def test_non_refundable_plan_past_grace_forfeits(api):
    """PRD §3.9: "Otherwise — the plan is not refundable and more than 30 days
    have elapsed — the refund is **FORFEIT** and equals zero, the whole prepaid
    fee being given up."

    A non-refundable plan cancelled 91 days after activation forfeits: the cancel
    credits the wallet by 0.

    Design: Difficulty/dual_variant_calc/service_plan_refund_prorated_vs_forfeit
    """
    ctx = setup_installed_project()
    set_clock("2026-04-01T00:00:00Z")
    plan = validate_success(api.create_service_plan(
        F.create_service_plan_payload(ctx["project_id"], tier="BASIC",
                                      annual_fee_cents=48000, refundable=False), ADMIN),
        expected_status=201)
    _activate_plan(api, ctx, plan["id"])
    set_clock("2026-07-01T00:00:00Z")
    wallet_before = _wallet(api, ctx["cust_id"])
    cancelled = _cancel_plan(api, ctx, plan["id"])
    wallet_after = _wallet(api, ctx["cust_id"])
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert wallet_after - wallet_before == 0, f"forfeit credited {wallet_after - wallet_before}"


def test_refundable_plan_past_grace_prorates(api):
    """PRD §3.9: "If the plan's `refundable` flag is true, or the elapsed days are
    at most the 30-day grace period (`REFUND_GRACE_DAYS`), the refund is
    **PRORATED**: the `annual_fee_cents` multiplied by the unused days, divided by
    365, rounded half up to a whole cent."

    A refundable plan cancelled at the same 91 elapsed days prorates: unused 274
    days, 48000 * 274 / 365 = 36033 credited.

    Design: Difficulty/dual_variant_calc/service_plan_refund_prorated_vs_forfeit
    """
    ctx = setup_installed_project()
    set_clock("2026-04-01T00:00:00Z")
    plan = validate_success(api.create_service_plan(
        F.create_service_plan_payload(ctx["project_id"], tier="PREMIUM",
                                      annual_fee_cents=48000, refundable=True), ADMIN),
        expected_status=201)
    _activate_plan(api, ctx, plan["id"])
    set_clock("2026-07-01T00:00:00Z")
    wallet_before = _wallet(api, ctx["cust_id"])
    cancelled = _cancel_plan(api, ctx, plan["id"])
    wallet_after = _wallet(api, ctx["cust_id"])
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    assert wallet_after - wallet_before == 36033, f"prorate credited {wallet_after - wallet_before}"


# ---------------------------------------------------------------------------
# Activate requires INSTALLED project (difficulty: cross_entity_state_dependency)
# ---------------------------------------------------------------------------
def _accepted_not_installed_project_with_pending_plan():
    """Project at commercial_status ACCEPTED (quote accepted, no install energized)
    with a PENDING service plan. Returns (ctx, plan_id)."""
    ctx = setup_project_with_transformer_and_zone()
    assign_fixtures_to_zone(ctx, [{"model_code": "PATH-3W", "category": "PATH",
                                   "wattage_w": 3, "purchase_price_cents": 4000}])
    setup_accepted_quote(ctx, lines=[{"model_code": "PATH-3W", "quantity": 1, "unit_price_cents": 4000}])
    plan = validate_success(api_client.create_service_plan(
        F.create_service_plan_payload(ctx["project_id"], tier="BASIC", annual_fee_cents=12000), ADMIN),
        expected_status=201)
    return ctx, plan["id"]


def test_activate_plan_on_accepted_project_rejected(api):
    """PRD §3.9: "A customer activates the plan, moving it from `PENDING` to
    `ACTIVE`, which is allowed only when the project's `commercial_status` is
    `INSTALLED` (otherwise `ERR_PROJECT_NOT_INSTALLED`)".

    Activating on an ACCEPTED-but-not-installed project is rejected.

    Design: Difficulty/cross_entity_state_dependency/service_plan_activate_requires_project_installed
    """
    ctx, plan_id = _accepted_not_installed_project_with_pending_plan()
    validate_error(
        api.activate_service_plan(plan_id, make_customer_headers(ctx["cust_id"])),
        ApiErrorId.ERR_PROJECT_NOT_INSTALLED.value,
    )


def test_activate_plan_on_accepted_project_leaves_plan_pending(api):
    """PRD §3.9: "It begins `PENDING` with its `season_cycle_count` at zero and
    its `activated_at` null."
    PRD §3.9: "A customer activates the plan, moving it from `PENDING` to `ACTIVE`,
    which is allowed only when the project's `commercial_status` is `INSTALLED`
    (otherwise `ERR_PROJECT_NOT_INSTALLED`)".

    The rejected activation leaves the plan in PENDING.

    Design: Difficulty/cross_entity_state_dependency/service_plan_activate_requires_project_installed
    """
    ctx, plan_id = _accepted_not_installed_project_with_pending_plan()
    validate_error(
        api.activate_service_plan(plan_id, make_customer_headers(ctx["cust_id"])),
        ApiErrorId.ERR_PROJECT_NOT_INSTALLED.value,
    )
    plan_now = validate_success(api.get_service_plan(plan_id, ADMIN))
    assert plan_now["status"] == "PENDING", plan_now["status"]


# ---------------------------------------------------------------------------
# Seasonal cycle increments count (corner: state_machines)
# ---------------------------------------------------------------------------
def test_seasonal_cycle_returns_active_with_incremented_count(api):
    """PRD §3.9: "Beginning a seasonal adjustment moves the plan from `ACTIVE` to
    `ADJUSTING`; completing one moves it back from `ADJUSTING` to `ACTIVE` and
    increments `season_cycle_count` by one — this is the cyclic seasonal loop."

    Design: Corner/state_machines/seasonal_cycle_increments_count
    """
    ctx = setup_installed_project()
    plan = validate_success(api.create_service_plan(
        F.create_service_plan_payload(ctx["project_id"], tier="PREMIUM", annual_fee_cents=12000), ADMIN),
        expected_status=201)
    _activate_plan(api, ctx, plan["id"])
    validate_success(api.begin_seasonal_adjustment(plan["id"], TECH))
    completed = validate_success(api.complete_seasonal_adjustment(plan["id"], TECH))
    assert completed["status"] == "ACTIVE", completed["status"]
    assert completed["season_cycle_count"] == 1, completed["season_cycle_count"]


# ---------------------------------------------------------------------------
# Activate debits then grace-prorated refund (corner: endpoints)
# ---------------------------------------------------------------------------
def test_activate_debits_then_grace_prorated_refund(api):
    """PRD §3.9: "activation stamps `activated_at` from the logical clock and
    debits the customer's `wallet_credit_cents` by the `annual_fee_cents`." and
    "If the plan's `refundable` flag is true, or the elapsed days are at most the
    30-day grace period (`REFUND_GRACE_DAYS`), the refund is **PRORATED**: the
    `annual_fee_cents` multiplied by the unused days, divided by 365, rounded half
    up to a whole cent."

    Activate debits 48000; cancel within grace (elapsed 20 days, unused 345) credits
    PRORATED 45370, leaving the wallet at -2630.

    Design: Corner/endpoints/service_plan_activate_debits_then_prorated_grace_refund
    """
    ctx = setup_installed_project()
    set_clock("2026-04-01T00:00:00Z")
    plan = validate_success(api.create_service_plan(
        F.create_service_plan_payload(ctx["project_id"], tier="BASIC",
                                      annual_fee_cents=48000, refundable=False), ADMIN),
        expected_status=201)
    wallet_before = _wallet(api, ctx["cust_id"])
    _activate_plan(api, ctx, plan["id"])
    set_clock("2026-04-21T00:00:00Z")  # elapsed 20 <= 30 grace
    cancelled = _cancel_plan(api, ctx, plan["id"])
    assert cancelled["status"] == "CANCELLED", cancelled["status"]
    # Net of the §3.9 activation debit (48000) then the PRORATED grace refund
    # (round_half_up(48000 * 345 / 365) = 45370): -48000 + 45370 = -2630.
    assert _wallet(api, ctx["cust_id"]) - wallet_before == -2630, _wallet(api, ctx["cust_id"]) - wallet_before


# ---------------------------------------------------------------------------
# Close blocked by pending plan (corner: validations)
# ---------------------------------------------------------------------------
def test_close_project_blocked_by_pending_plan(api):
    """PRD §3.12: "A project cannot be closed while it still carries an obligation:
    if any service plan on the project is in `PENDING` or `ADJUSTING`, the close
    is rejected with `ERR_PLAN_BLOCKS_CLOSE`."

    Design: Corner/validations/close_project_blocked_by_pending_plan
    """
    ctx = setup_installed_project()
    create_pending_service_plan(ctx, plan_overrides={"tier": "BASIC", "annual_fee_cents": 12000})
    validate_error(api.close_project(ctx["project_id"], ADMIN), ApiErrorId.ERR_PLAN_BLOCKS_CLOSE.value)
    project = validate_success(api.get_project(ctx["project_id"], DESIGNER))
    assert project["commercial_status"] == "INSTALLED", project["commercial_status"]
