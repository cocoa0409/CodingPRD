"""Cash ordering: forecast variants, step rounding, capacity, dates, OCC."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, setup_forecast_history, teller_h,
    make_branch, make_teller, make_account, open_drawer, deposit,
    cash_order_payload,
)

MGR = TEST_USERS["manager_headers"]
HT = TEST_USERS["head_teller_headers"]
AUD = TEST_USERS["auditor_headers"]

# Mondays carry net outflows 260000/200000/240000/300000; other days 180000,
# 160000, 140000, 220000 — TRAILING mean over the 4 Mondays is exactly 250000,
# the unconditional 70/30 WEIGHTED blend is exactly 227500.
FORECAST_DAYS = [
    ("2026-08-03", 260_000), ("2026-08-04", 180_000), ("2026-08-10", 200_000),
    ("2026-08-12", 160_000), ("2026-08-17", 240_000), ("2026-08-20", 140_000),
    ("2026-08-22", 220_000), ("2026-08-24", 300_000),
]


def test_forecast_trailing_variant_used_with_three_plus_samples(api):
    """PRD §3.4: "When the same-weekday sample holds at least three days, the
    forecast trusts it alone: the projected need is the arithmetic mean of
    those days' net outflows, ceiled once to whole cents at the end."

    Design: Difficulty/dual_variant_calc/forecast_trailing_vs_weighted_divergence
    """
    ctx = setup_forecast_history(api, FORECAST_DAYS)
    get_success_data(api.set_clock("2026-08-28T00:00:00Z", MGR))
    data = validate_success(api.get_cash_forecast(ctx["branch"]["id"], "2026-08-31", HT))
    assert data["projected_need_cents"] == 250_000


def test_forecast_weighted_variant_diverges(api):
    """PRD §3.4: "the preview's response carries `projected_need_cents` (the
    official reading), `weighted_need_cents` (the seventy-thirty blend applied
    unconditionally, with a missing group contributing zero and no
    renormalization), and `suggested_order_cents`."

    Design: Difficulty/dual_variant_calc/forecast_trailing_vs_weighted_divergence
    """
    ctx = setup_forecast_history(api, FORECAST_DAYS)
    get_success_data(api.set_clock("2026-08-28T00:00:00Z", MGR))
    data = validate_success(api.get_cash_forecast(ctx["branch"]["id"], "2026-08-31", HT))
    assert data["weighted_need_cents"] == 227_500
    # vault 50,000,000 far exceeds the need -> suggestion floors at zero
    assert data["suggested_order_cents"] == 0


def test_forecast_below_min_samples_uses_weighted_blend(api):
    """PRD §3.4: "When the same-weekday sample is too thin but at least one
    sample exists anywhere, the projected need is a weighted blend — seventy
    percent of the same-weekday mean plus thirty percent of the other-days
    mean".

    Design: Corner/calculations/forecast_below_min_samples_uses_weighted_blend
    """
    days = [("2026-08-04", 180_000), ("2026-08-10", 200_000),
            ("2026-08-12", 160_000), ("2026-08-22", 220_000)]
    ctx = setup_forecast_history(api, days, vault_cash_cents=1_000_000,
                                 drawer_limit_cents=2_000_000, fund_amount=1_000_000)
    get_success_data(api.set_clock("2026-09-01T00:00:00Z", MGR))
    data = validate_success(api.get_cash_forecast(ctx["branch"]["id"], "2026-09-02", HT))
    # one Wednesday sample (160000), other-days mean 200000 -> 0.7*160000+0.3*200000
    assert data["projected_need_cents"] == 172_000
    assert data["suggested_order_cents"] == 172_000  # vault is empty after funding


def test_order_step_rounding_before_capacity_clamp_rejects(api):
    """PRD §3.4: "the remaining vault headroom — the vault capacity of
    100000000 cents minus the cash presently on hand, never below zero — is
    itself rounded down to a whole step. ... If that figure is zero, there is
    nothing to ship and the order is refused with `ERR_ORDER_BELOW_MINIMUM`."

    Design: Difficulty/combinatorial_formula/cash_order_step_rounding_before_capacity_clamp
    """
    branch = make_branch(api, vault_cash_cents=99_950_000)
    make_teller(api, branch, "T")
    resp = api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=500_000), HT)
    validate_error(resp, "ERR_ORDER_BELOW_MINIMUM", 422)


def test_order_step_rounding_floors_request_to_step(api):
    """PRD §3.4: "First, the raw quantity is the request's optional
    `requested_amount_cents` when supplied ... Second, that raw quantity is
    rounded down to a whole multiple of the 100000-cent shipment step."

    Design: Difficulty/combinatorial_formula/cash_order_step_rounding_before_capacity_clamp
    """
    branch = make_branch(api)
    make_teller(api, branch, "T")
    data = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=1_234_567), HT), 201)
    assert data["ordered_amount_cents"] == 1_200_000
    assert data["suggested_order_cents"] == 0  # no history -> zero projection
    assert data["status"] == "PENDING"


def test_duplicate_delivery_date_rejected_until_freed(api):
    """PRD §3.4: "A branch may hold at most one order in `PENDING` or `APPROVED`
    for a given delivery date; a second order for an occupied date is refused
    with `ERR_DUPLICATE_CASH_ORDER` — though once the occupying order is
    `REJECTED` (or otherwise terminal), the date is free again."

    Design: Difficulty/resource_temporal_overlap/cash_order_delivery_date_exclusion
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    o1 = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    v = validate_success(api.get_branch(branch["id"], MGR))["version"]
    resp = api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", v, requested_amount_cents=200_000), teller_h(teller))
    validate_error(resp, "ERR_DUPLICATE_CASH_ORDER", 409)
    validate_success(api.reject_cash_order(o1["id"], MGR))
    v = validate_success(api.get_branch(branch["id"], MGR))["version"]
    o2 = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", v, requested_amount_cents=200_000), teller_h(teller)), 201)
    assert o2["status"] == "PENDING"
    assert o2["ordered_amount_cents"] == 200_000


def test_rejected_order_frees_date_and_rejection_is_terminal(api):
    """PRD §3.4: "rejection to terminal `REJECTED`" — no further transition is
    possible from it.

    Design: Difficulty/resource_temporal_overlap/cash_order_delivery_date_exclusion
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    o1 = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    validate_success(api.reject_cash_order(o1["id"], MGR))
    resp = api.approve_cash_order(o1["id"], MGR)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_deliver_blocked_while_branch_frozen(api):
    """PRD §3.4: "Deliveries do not happen under an audit freeze." (§3.9: the
    freeze fails cash movements with `ERR_BRANCH_FROZEN`.)

    Design: Difficulty/cross_entity_state_dependency/cash_order_deliver_blocked_while_branch_frozen
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", branch["version"], requested_amount_cents=500_000), teller_h(teller)), 201)
    assert order["ordered_amount_cents"] == 500_000
    validate_success(api.approve_cash_order(order["id"], MGR))
    audit = validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    get_success_data(api.set_clock("2026-08-31T00:00:00Z", MGR))
    resp = api.deliver_cash_order(order["id"], HT)
    validate_error(resp, "ERR_BRANCH_FROZEN", 409)


def test_deliver_succeeds_after_audit_completes(api):
    """PRD §3.4: "a `HeadTeller` receives the shipment, moving the order to
    terminal `DELIVERED` and adding `ordered_amount_cents` to the branch's
    `vault_cash_cents`" and §3.9: "The freeze lifts — the branch returns to
    `OPEN`".

    Design: Difficulty/cross_entity_state_dependency/cash_order_deliver_blocked_while_branch_frozen
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", branch["version"], requested_amount_cents=500_000), teller_h(teller)), 201)
    validate_success(api.approve_cash_order(order["id"], MGR))
    audit = validate_success(api.create_audit(branch["id"], {"type": "SURPRISE"}, AUD), 201)
    get_success_data(api.set_clock("2026-08-31T00:00:00Z", MGR))
    validate_success(api.complete_audit(audit["id"], 50_000_000, [], AUD))
    delivered = validate_success(api.deliver_cash_order(order["id"], HT))
    assert delivered["status"] == "DELIVERED"
    branch = validate_success(api.get_branch(branch["id"], MGR))
    assert branch["vault_cash_cents"] == 50_500_000
    assert branch["status"] == "OPEN"


def test_deliver_before_date_rejected(api):
    """PRD §3.4: "the logical business date must equal `delivery_date`, or the
    attempt is `ERR_ORDER_NOT_DUE`".

    Design: Corner/state_machines/cash_order_deliver_before_date_rejected
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    validate_success(api.approve_cash_order(order["id"], MGR))
    resp = api.deliver_cash_order(order["id"], HT)
    validate_error(resp, "ERR_ORDER_NOT_DUE", 409)
    after = validate_success(api.get_cash_order(order["id"], MGR))
    assert after["status"] == "APPROVED"


def test_deliver_from_pending_rejected(api):
    """PRD §3.4: an order "begins `PENDING`" and only "an approved order" can
    be delivered — delivering a `PENDING` order is `ERR_INVALID_STATE`.

    Design: Corner/state_machines/cash_order_deliver_from_pending_rejected
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    get_success_data(api.set_clock("2026-08-03T00:00:00Z", MGR))
    resp = api.deliver_cash_order(order["id"], HT)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_weekend_delivery_date_rejected(api):
    """PRD §3.4: "The `delivery_date` must be a Monday-through-Friday date
    strictly later than the order's own business date, or the request fails
    with `ERR_INVALID_DELIVERY_DATE`."

    Design: Corner/errors/weekend_delivery_date_rejected
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    resp = api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-02", branch["version"], requested_amount_cents=100_000), teller_h(teller))
    validate_error(resp, "ERR_INVALID_DELIVERY_DATE", 422)


def test_stale_branch_version_rejected_occ(api):
    """PRD §2.6: "if the supplied value does not equal the branch's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_branch_version_rejected_occ
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    # the first order advanced the branch version; replaying it is stale
    resp = api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-04", branch["version"], requested_amount_cents=200_000), teller_h(teller))
    validate_error(resp, "ERR_STALE_VERSION", 412)


def test_deliver_over_capacity_rejected(api):
    """PRD §3.4: "if crediting the order would push the vault above its
    100000-cent-step capacity ceiling of 100000000 cents, the delivery is
    refused with `ERR_VAULT_CAPACITY_EXCEEDED` and the order remains
    `APPROVED`."

    Design: Corner/errors/deliver_over_capacity_rejected
    """
    branch = make_branch(api, vault_cash_cents=99_500_000, drawer_limit_cents=100_000)
    teller = make_teller(api, branch, "T")
    account = make_account(api, branch, balance_cents=0)
    drawer = open_drawer(api, teller)
    th = teller_h(teller)
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=500_000), th), 201)
    assert order["ordered_amount_cents"] == 500_000
    validate_success(api.approve_cash_order(order["id"], MGR))
    # fresh cash arrives after the order was placed
    deposit(api, drawer, account, teller, 200_000)
    validate_success(api.sell_to_vault(drawer["id"], 150_000, th))
    get_success_data(api.set_clock("2026-08-03T00:00:00Z", MGR))
    resp = api.deliver_cash_order(order["id"], HT)
    validate_error(resp, "ERR_VAULT_CAPACITY_EXCEEDED", 422)
    after = validate_success(api.get_cash_order(order["id"], MGR))
    assert after["status"] == "APPROVED"

def test_rejected_cash_order_is_terminal(api):
    """PRD §3.4: "rejection to terminal `REJECTED`." A terminal order accepts
    no further decisions.

    Design: Corner/state_machines/rejected_cash_order_is_terminal
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    order = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-03", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    validate_success(api.reject_cash_order(order["id"], MGR))
    resp = api.approve_cash_order(order["id"], MGR)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_approved_order_still_occupies_its_delivery_date(api):
    """PRD §3.4: "A branch may hold at most one order in `PENDING` or
    `APPROVED` for a given delivery date".

    Design: Difficulty/resource_temporal_overlap/cash_order_delivery_date_exclusion
    """
    branch = make_branch(api)
    teller = make_teller(api, branch, "T")
    o1 = validate_success(api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", branch["version"], requested_amount_cents=100_000), teller_h(teller)), 201)
    validate_success(api.approve_cash_order(o1["id"], MGR))
    v = validate_success(api.get_branch(branch["id"], MGR))["version"]
    resp = api.create_cash_order(branch["id"], cash_order_payload(
        "2026-08-31", v, requested_amount_cents=200_000), teller_h(teller))
    validate_error(resp, "ERR_DUPLICATE_CASH_ORDER", 409)
