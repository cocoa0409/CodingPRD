"""Delivery lifecycle, tote-exchange mass conservation, dual-variant invoice
pricing with pinned per-line rounding, OCC on scheduling, fiscal gates, and
order list filtering."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_delivery_order,
    assert_invoice,
    bring_station_online,
    create_accepted_design,
    create_account,
    create_and_issue_invoice,
    create_asset,
    create_delivery_order_payload,
    create_pending_order,
    create_product,
    create_station,
    deliver_and_close_order,
    make_customer_contact_headers,
    post_telemetry,
    schedule_order,
    set_clock,
    setup_commissioned_asset,
    setup_delivery_ready,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
CHEMIST = TEST_USERS["chemist_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual-variant invoice pricing
# ---------------------------------------------------------------------------

def _two_product_subtree(account_name, billing_model, service_rate):
    """Account with one asset, ACCEPTED design at the given service rate, and
    ONLINE stations for INH-100 (unit 399 / contract 350) and INH-200
    (unit 201 / contract 181), both in 55-gal containers."""
    set_clock("2026-08-01T00:00:00Z")
    p100 = create_product(product_code="INH-100", active_pct=10, container_size_gal=55,
                          unit_price_cents_per_gal=399, contract_price_cents_per_gal=350)
    p200 = create_product(product_code="INH-200", active_pct=20, container_size_gal=55,
                          unit_price_cents_per_gal=201, contract_price_cents_per_gal=181)
    account = create_account(account_name=account_name, billing_model=billing_model)
    asset = create_asset(account["id"], asset_tag="CT-1", recirculation_rate_gpm=500,
                         system_volume_gal=12000)
    create_accepted_design(asset["id"], account["id"], proposed_coc=4.0,
                           inhibitor_target_ppm=5, conductivity_max_umhos=4000,
                           service_rate_cents_per_month=service_rate)
    fs1 = bring_station_online(
        create_station(asset["id"], p100["id"], capacity_cap_ml_per_min=50)["id"]
    )
    fs2 = bring_station_online(
        create_station(asset["id"], p200["id"], capacity_cap_ml_per_min=50)["id"]
    )
    return account, asset, fs1, fs2


def _standard_deliveries(account_id, fs1, fs2):
    """110 gal of INH-100 and 55 gal of INH-200, both CLOSED with
    scheduled_for inside [2026-08-05, 2026-09-01)."""
    o1 = deliver_and_close_order(account_id, fs1["id"], 110, "2026-08-06T00:00:00Z")
    o2 = deliver_and_close_order(account_id, fs2["id"], 55, "2026-08-07T00:00:00Z")
    return o1, o2


def test_invoice_product_variant_totals(api):
    """PRD §3.9: "Under the `PRODUCT` variant, each line is the order's
    `delivered_gal` times the product's `unit_price_cents_per_gal`, rounded
    half up to whole cents, and the `service_fee_cents` is 0." "The
    `product_charges_cents` is the sum of the rounded lines and
    `invoice_total_cents` is `product_charges_cents` plus
    `service_fee_cents`". "Issuing — `DRAFT` → `ISSUED` — snapshots the
    `pricing_variant` from the account's current `billing_model`".

    Design: Difficulty/dual_variant_calc/invoice_pricing_service_contract_vs_product_on_invoice
    """
    account, _, fs1, fs2 = _two_product_subtree("Prod Co", "PRODUCT", 75000)
    _standard_deliveries(account["id"], fs1, fs2)

    invoice = create_and_issue_invoice(
        account["id"], "2026-08-05T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert_invoice(invoice)
    assert invoice["pricing_variant"] == "PRODUCT"
    # 110 * 399 + 55 * 201 = 43890 + 11055
    assert invoice["product_charges_cents"] == 54945
    assert invoice["service_fee_cents"] == 0
    assert invoice["invoice_total_cents"] == 54945


def test_invoice_service_contract_variant_totals(api):
    """PRD §3.9: "Under the `SERVICE_CONTRACT` variant, each line is
    `delivered_gal` times the `contract_price_cents_per_gal`, rounded the
    same way, and the `service_fee_cents` is the
    `service_rate_cents_per_month` from the `ACCEPTED` program design of the
    destination station's asset — 0 when no accepted design exists." "the
    same delivery set therefore yields a different total under the two
    variants."

    Design: Difficulty/dual_variant_calc/invoice_pricing_service_contract_vs_product_on_invoice
    """
    account, _, fs1, fs2 = _two_product_subtree("Svc Co", "SERVICE_CONTRACT", 75000)
    _standard_deliveries(account["id"], fs1, fs2)

    invoice = create_and_issue_invoice(
        account["id"], "2026-08-05T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert_invoice(invoice)
    assert invoice["pricing_variant"] == "SERVICE_CONTRACT"
    # 110 * 350 + 55 * 181 = 38500 + 9955, plus the 75000 flat fee.
    assert invoice["product_charges_cents"] == 48455
    assert invoice["service_fee_cents"] == 75000
    assert invoice["invoice_total_cents"] == 123455


# ---------------------------------------------------------------------------
# Difficulty: pinned per-line rounding
# ---------------------------------------------------------------------------

def _rounding_subtree():
    """PRODUCT account with stations for RND-1 (container 33.335 gal) and
    RND-2 (container 10.005 gal), both at 100 cents/gal list."""
    set_clock("2026-08-01T00:00:00Z")
    p1 = create_product(product_code="RND-1", active_pct=10, container_size_gal=33.335,
                        unit_price_cents_per_gal=100, contract_price_cents_per_gal=80)
    p2 = create_product(product_code="RND-2", active_pct=10, container_size_gal=10.005,
                        unit_price_cents_per_gal=100, contract_price_cents_per_gal=80)
    account = create_account(account_name="Rounding Co", billing_model="PRODUCT")
    asset = create_asset(account["id"], asset_tag="BLR-1", asset_type="BOILER",
                         recirculation_rate_gpm=200, system_volume_gal=4000)
    create_accepted_design(asset["id"], account["id"], proposed_coc=3.0,
                           inhibitor_target_ppm=4, service_rate_cents_per_month=0)
    fs1 = bring_station_online(
        create_station(asset["id"], p1["id"], capacity_cap_ml_per_min=100)["id"]
    )
    fs2 = bring_station_online(
        create_station(asset["id"], p2["id"], capacity_cap_ml_per_min=100)["id"]
    )
    deliver_and_close_order(account["id"], fs1["id"], 33.335, "2026-08-06T00:00:00Z")
    deliver_and_close_order(account["id"], fs2["id"], 10.005, "2026-08-07T00:00:00Z")
    return account


def test_invoice_rounding_per_line_then_sum(api):
    """PRD §3.9: "the rounding order is pinned: each line is rounded half up
    to whole cents first, and only then are lines summed — never sum raw
    values and round once."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_mode_b_per_line_then_sum
    """
    account = _rounding_subtree()
    invoice = create_and_issue_invoice(
        account["id"], "2026-08-05T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    # Line 1: 33.335 * 100 = 3333.5 -> 3334; line 2: 10.005 * 100 = 1000.5 -> 1001.
    # Pinned order sums the rounded lines: 4335 (sum-then-round would give 4334).
    assert invoice["product_charges_cents"] == 4335
    assert invoice["invoice_total_cents"] == 4335


def test_invoice_rounding_not_sum_then_round(api):
    """PRD §3.9: "each line is rounded half up to whole cents first, and only
    then are lines summed — never sum raw values and round once."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_mode_b_per_line_then_sum
    """
    account = _rounding_subtree()
    invoice = create_and_issue_invoice(
        account["id"], "2026-08-05T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert invoice["product_charges_cents"] == 4335
    assert invoice["product_charges_cents"] != 4334, (
        "4334 is the sum-then-round outcome the pinned order forbids"
    )


# ---------------------------------------------------------------------------
# Difficulty: tote-exchange mass conservation
# ---------------------------------------------------------------------------

def _mass_conservation_subtree(account_name):
    """Commissioned asset; 110 gal delivered and CLOSED with 4 gal residual
    returned; ~40.0009 gal consumed via telemetry; a second order left
    SCHEDULED for 2026-08-06. Clock ends at 2026-08-05."""
    subtree = setup_commissioned_asset(
        account_name=account_name,
        asset_overrides={"recirculation_rate_gpm": 500, "system_volume_gal": 9000},
        design_overrides={"proposed_coc": 4.0, "inhibitor_target_ppm": 5,
                          "ph_min": 7.0, "ph_max": 9.5,
                          "conductivity_max_umhos": 4000},
    )
    account_id, station_id = subtree["account"]["id"], subtree["station"]["id"]
    deliver_and_close_order(account_id, station_id, 110, "2026-08-02T00:00:00Z",
                            delivered_gal=110, returned_residual_gal=4)
    for recorded_at in ("2026-08-02T06:00:00Z", "2026-08-03T06:00:00Z",
                        "2026-08-04T06:00:00Z", "2026-08-04T18:00:00Z"):
        set_clock(recorded_at)
        post_telemetry(station_id, recorded_at=recorded_at, feed_pulses=7571,
                       ml_per_pulse=5.0, level_gal=100)
    o2 = create_pending_order(account_id, station_id, 55)
    schedule_order(o2["id"], "2026-08-06T00:00:00Z", o2["version"])
    set_clock("2026-08-05T00:00:00Z")
    return subtree, o2


def test_tote_exchange_mass_conservation(api):
    """PRD §3.9: "reconciles the tote-exchange mass invariant per station:
    the sum of `delivered_gal` minus the sum of `returned_residual_gal`
    equals consumed gallons plus on-hand `inventory_gal`." PRD §3.3: "The
    station's `inventory_gal` reconciles deliveries against consumption: the
    sum of `delivered_gal` over the station's delivery orders in `DELIVERED`
    or `CLOSED` status, minus the sum of `returned_residual_gal` over its
    `CLOSED` orders, minus lifetime consumed gallons."

    Design: Difficulty/compensating_invariant/tote_exchange_mass_conservation_per_station
    """
    subtree, _ = _mass_conservation_subtree("Mass Co")
    station = validate_success(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST)
    )
    # 110 delivered - 4 returned - 4 * (7571 * 5.0 / 3785.411) consumed = 65.9991.
    assert station["inventory_gal"] == pytest.approx(65.9991, abs=1e-3)


def test_scheduled_order_cancel_moves_no_inventory(api):
    """PRD §3.9: "cancelling a `SCHEDULED` order releases its tote allocation,
    a pure compensation since no inventory has yet moved, while cancelling
    from `DRAFT` or `PENDING` has no inventory effect."

    Design: Difficulty/compensating_invariant/tote_exchange_mass_conservation_per_station
    """
    subtree, o2 = _mass_conservation_subtree("Mass Co 2")
    before = validate_success(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST)
    )

    cancelled = validate_success(api_client.cancel_delivery_order(o2["id"], MANAGER))
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(
        api_client.get_feed_station(subtree["station"]["id"], CHEMIST)
    )
    assert after["inventory_gal"] == pytest.approx(before["inventory_gal"], abs=1e-9)
    assert after["inventory_gal"] == pytest.approx(65.9991, abs=1e-3)


# ---------------------------------------------------------------------------
# Difficulty: priority pair — state gate (tier 7) beats fiscal gate (tier 14)
# ---------------------------------------------------------------------------

def _credit_hold_subtree(account_name, accept_design):
    """Account on credit_hold with an ONLINE station; optionally an ACCEPTED
    design on the destination asset."""
    set_clock("2026-08-01T00:00:00Z")
    account = create_account(account_name=account_name, credit_hold=True)
    asset = create_asset(account["id"], asset_tag="CT-D", recirculation_rate_gpm=300)
    product = create_product()
    station = create_station(asset["id"], product["id"], capacity_cap_ml_per_min=50)
    bring_station_online(station["id"])
    if accept_design:
        create_accepted_design(asset["id"], account["id"], proposed_coc=3.0,
                               inhibitor_target_ppm=4)
    order = create_pending_order(account["id"], station["id"], 55)
    return account, asset, station, order


def test_schedule_reports_program_gate_before_credit_hold(api):
    """PRD §2.6: "Every request passes through a single validation pipeline of
    fifteen tiers, evaluated strictly in ascending priority order. The first
    tier whose check fails determines the error response; later tiers are
    never consulted for that request." Tier 7: "scheduling a delivery
    requires an `ACCEPTED` program design on the destination asset
    (`ERR_PROGRAM_NOT_ACCEPTED`)". Tier 14: "An account on `credit_hold`
    cannot have deliveries scheduled (`ERR_CREDIT_HOLD`, HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_delivery_schedule
    """
    _, _, _, order = _credit_hold_subtree("DualFail Co", accept_design=False)
    resp = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": order["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCEPTED)
    body = resp.json()
    assert body["data"]["error_id"] != "ERR_CREDIT_HOLD"

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "PENDING"


def test_schedule_reports_credit_hold_when_program_accepted(api):
    """PRD §3.9: "the account's `credit_hold` must be `false`
    (`ERR_CREDIT_HOLD`)". With the tier-7 program gate satisfied, the fiscal
    gate is the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_delivery_schedule
    """
    _, _, _, order = _credit_hold_subtree("DualFail Co 2", accept_design=True)
    resp = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": order["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_HOLD)
    assert resp.status_code == 409

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Corner: delivery-order list filtering
# ---------------------------------------------------------------------------

def test_list_filter_by_status(api):
    """PRD §3.9: "The orders list supports `account_id`, `station_id`, and
    `status` filters."

    Design: Corner/entities/list_filter_by_status
    """
    subtree = setup_delivery_ready(account_name="Filter Co")
    account, station = subtree["account"], subtree["station"]
    o1 = validate_success(
        api_client.create_delivery_order(
            create_delivery_order_payload(account["id"], station["id"], 55), MANAGER
        ),
        expected_status=201,
    )
    validate_success(api_client.cancel_delivery_order(o1["id"], MANAGER))
    o2 = create_pending_order(account["id"], station["id"], 110)
    schedule_order(o2["id"], "2026-08-10T00:00:00Z", o2["version"])

    data, meta = validate_paginated(
        api_client.list_delivery_orders(
            MANAGER, params={"account_id": account["id"], "status": "CANCELLED"}
        )
    )
    ids = [o["id"] for o in data]
    assert ids == [o1["id"]]
    assert o2["id"] not in ids


# ---------------------------------------------------------------------------
# Corner: invoice input-set filtering
# ---------------------------------------------------------------------------

def test_invoice_excludes_cancelled_and_out_of_window_orders(api):
    """PRD §3.9: "The line set is the account's delivery orders in `DELIVERED`
    or `CLOSED` status whose `scheduled_for` falls within the billing
    window". "Issuing also debits the account: `open_balance_cents` is
    increased by `invoice_total_cents`."

    Design: Corner/calculations/invoice_excludes_cancelled_and_out_of_window_orders
    """
    subtree = setup_delivery_ready(account_name="InvF Co",
                                   account_overrides={"billing_model": "PRODUCT"})
    account, station = subtree["account"], subtree["station"]

    # In-window billable delivery: 55 gal at 100c = 5500.
    deliver_and_close_order(account["id"], station["id"], 55, "2026-08-06T00:00:00Z")
    # Cancelled from DRAFT: never billed.
    o2 = validate_success(
        api_client.create_delivery_order(
            create_delivery_order_payload(account["id"], station["id"], 110), MANAGER
        ),
        expected_status=201,
    )
    validate_success(api_client.cancel_delivery_order(o2["id"], MANAGER))
    # CLOSED but scheduled outside the billing window.
    deliver_and_close_order(account["id"], station["id"], 110, "2026-09-05T00:00:00Z")

    invoice = create_and_issue_invoice(
        account["id"], "2026-08-05T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert invoice["product_charges_cents"] == 5500
    assert invoice["invoice_total_cents"] == 5500

    acct = validate_success(api_client.get_account(account["id"], MANAGER))
    assert acct["open_balance_cents"] == 5500


# ---------------------------------------------------------------------------
# Corner: order field and temporal gates
# ---------------------------------------------------------------------------

def test_quantity_not_container_multiple_rejected(api):
    """PRD §3.9: "a `quantity_gal` that must be strictly positive and a whole
    multiple of the destination product's `container_size_gal`
    (`ERR_QUANTITY_NOT_CONTAINER_MULTIPLE` when it is not)."

    Design: Corner/validations/quantity_not_container_multiple_rejected
    """
    account = create_account(account_name="Mult Co")
    asset = create_asset(account["id"], asset_type="BOILER", recirculation_rate_gpm=100,
                         system_volume_gal=500)
    product = create_product()  # container 55 gal
    station = create_station(asset["id"], product["id"])
    bring_station_online(station["id"])

    resp = api_client.create_delivery_order(
        create_delivery_order_payload(account["id"], station["id"], 100), MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_QUANTITY_NOT_CONTAINER_MULTIPLE)
    assert resp.status_code == 422


def test_schedule_in_past_rejected(api):
    """PRD §3.9: "the request supplies a `scheduled_for` that must be strictly
    later than the current clock (`ERR_SCHEDULE_IN_PAST`)". A `scheduled_for`
    equal to the current clock is not strictly in the future.

    Design: Corner/validations/schedule_in_past_rejected
    """
    subtree = setup_delivery_ready(account_name="Past Co")
    order = create_pending_order(subtree["account"]["id"], subtree["station"]["id"], 55)
    set_clock("2026-08-10T00:00:00Z")

    resp = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": order["version"]},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_IN_PAST)
    assert resp.status_code == 422


def test_dispatch_before_scheduled_for_rejected(api):
    """PRD §3.9: "Dispatch — `SCHEDULED` → `IN_TRANSIT` — is refused before
    the scheduled instant: the current clock must be at or after
    `scheduled_for` (`ERR_TOO_EARLY_TO_DISPATCH`)."

    Design: Corner/endpoints/dispatch_before_scheduled_for_rejected
    """
    subtree = setup_delivery_ready(account_name="Early Co")
    order = create_pending_order(subtree["account"]["id"], subtree["station"]["id"], 55)
    schedule_order(order["id"], "2026-08-10T00:00:00Z", order["version"])

    set_clock("2026-08-09T23:59:59Z")  # one second early
    resp = api_client.dispatch_delivery_order(order["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_TOO_EARLY_TO_DISPATCH)
    assert resp.status_code == 422

    set_clock("2026-08-10T00:00:00Z")  # exactly at scheduled_for: allowed
    dispatched = validate_success(api_client.dispatch_delivery_order(order["id"], MANAGER))
    assert dispatched["status"] == "IN_TRANSIT"


def test_confirm_delivery_over_quantity_rejected(api):
    """PRD §3.9: "the `delivered_gal` actually dropped; it must be strictly
    positive and no more than the ordered `quantity_gal`
    (`ERR_DELIVERY_QUANTITY`)."

    Design: Corner/validations/confirm_delivery_over_quantity_rejected
    """
    subtree = setup_delivery_ready(account_name="Over Co")
    order = create_pending_order(subtree["account"]["id"], subtree["station"]["id"], 55)
    schedule_order(order["id"], "2026-08-02T00:00:00Z", order["version"])
    set_clock("2026-08-02T00:00:00Z")
    validate_success(api_client.dispatch_delivery_order(order["id"], MANAGER))

    resp = api_client.confirm_delivery(order["id"], {"delivered_gal": 56}, CHEMIST)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_QUANTITY)
    assert resp.status_code == 422

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "IN_TRANSIT"


def test_residual_exceeds_container_rejected(api):
    """PRD §3.9: "the chemist reports the `returned_residual_gal` left in the
    exchanged tote; it must be zero or more and no more than the product's
    `container_size_gal` (`ERR_RESIDUAL_EXCEEDS_CONTAINER`)."

    Design: Corner/validations/residual_exceeds_container_rejected
    """
    subtree = setup_delivery_ready(account_name="Resid Co")
    order = create_pending_order(subtree["account"]["id"], subtree["station"]["id"], 55)
    schedule_order(order["id"], "2026-08-02T00:00:00Z", order["version"])
    set_clock("2026-08-02T00:00:00Z")
    validate_success(api_client.dispatch_delivery_order(order["id"], MANAGER))
    delivered = validate_success(
        api_client.confirm_delivery(order["id"], {"delivered_gal": 55}, CHEMIST)
    )
    assert_delivery_order(delivered)

    resp = api_client.close_delivery_order(
        order["id"], {"returned_residual_gal": 56}, CHEMIST
    )
    validate_error(resp, ApiErrorId.ERR_RESIDUAL_EXCEEDS_CONTAINER)
    assert resp.status_code == 422

    after = validate_success(api_client.get_delivery_order(order["id"], MANAGER))
    assert after["status"] == "DELIVERED"


# ---------------------------------------------------------------------------
# Corner: fiscal gate on account close, and open-balance reconciliation
# ---------------------------------------------------------------------------

def test_close_account_with_unpaid_balance_rejected(api):
    """PRD §3.1: "Closing an account is permitted only from `ACTIVE` and only
    when `open_balance_cents` is exactly zero; a non-zero balance is rejected
    with `ERR_UNPAID_BALANCE`. Closure decommissions every asset of the
    account, moving each to `DECOMMISSIONED`."

    Design: Corner/validations/close_account_with_unpaid_balance_rejected
    """
    subtree = setup_commissioned_asset(account_name="Close Co")
    account, station = subtree["account"], subtree["station"]
    deliver_and_close_order(account["id"], station["id"], 55, "2026-08-02T00:00:00Z")
    invoice = create_and_issue_invoice(
        account["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )

    resp = api_client.close_account(account["id"], MANAGER)
    validate_error(resp, ApiErrorId.ERR_UNPAID_BALANCE)
    assert resp.status_code == 409

    paid = validate_success(
        api_client.pay_invoice(invoice["id"], make_customer_contact_headers(account["id"]))
    )
    assert paid["status"] == "PAID"
    acct = validate_success(api_client.get_account(account["id"], MANAGER))
    assert acct["open_balance_cents"] == 0

    closed = validate_success(api_client.close_account(account["id"], MANAGER))
    assert closed["status"] == "CLOSED"
    asset = validate_success(api_client.get_asset(subtree["asset"]["id"], CHEMIST))
    assert asset["status"] == "DECOMMISSIONED"


def test_derived_field_open_balance_reconciliation(api):
    """PRD §3.1: "that balance is a computed figure, the sum of
    `invoice_total_cents` over the account's invoices currently in `ISSUED`
    or `OVERDUE` status." PRD §3.9: "Payment — from either `ISSUED` or
    `OVERDUE` to `PAID` — belongs to the `CustomerContact`, who must own the
    invoice's account (`ERR_FORBIDDEN` otherwise), and credits the account:
    `open_balance_cents` is decreased by `invoice_total_cents`."

    Design: Corner/cross_cutting_layers/derived_field_open_balance_reconciliation
    """
    subtree = setup_delivery_ready(account_name="Recon Co")
    account, station = subtree["account"], subtree["station"]
    deliver_and_close_order(account["id"], station["id"], 55, "2026-08-02T00:00:00Z")

    acct = validate_success(api_client.get_account(account["id"], MANAGER))
    assert acct["open_balance_cents"] == 0

    invoice = create_and_issue_invoice(
        account["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z"
    )
    assert invoice["invoice_total_cents"] == 5500
    acct = validate_success(api_client.get_account(account["id"], MANAGER))
    assert acct["open_balance_cents"] == 5500

    paid = validate_success(
        api_client.pay_invoice(invoice["id"], make_customer_contact_headers(account["id"]))
    )
    assert paid["status"] == "PAID"
    acct = validate_success(api_client.get_account(account["id"], MANAGER))
    assert acct["open_balance_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: OCC on delivery scheduling
# ---------------------------------------------------------------------------

def test_occ_stale_version_on_delivery_schedule(api):
    """PRD §2.7: "A `POST /wt/delivery-orders/{orderId}/schedule` request —
    both the initial scheduling and rescheduling after a failed delivery —
    must carry `expected_delivery_order_version` equal to the order's current
    `version`." PRD §3.9: "A successful schedule stores the supplied
    `scheduled_for` and increments the order's `version` by one."
    PRD §2.5: "Every mutation of a resource — including system-driven changes
    to computed fields such as a station's `setpoint_ml_per_min`, an asset's
    `posture`, or an account's `open_balance_cents` — refreshes that
    resource's `updated_at` and increments its `version`."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_delivery_schedule
    """
    subtree = setup_delivery_ready(account_name="OCC2 Co")
    order = validate_success(
        api_client.create_delivery_order(
            create_delivery_order_payload(subtree["account"]["id"], subtree["station"]["id"], 55),
            MANAGER,
        ),
        expected_status=201,
    )
    creation_version = order["version"]
    submitted = validate_success(api_client.submit_delivery_order(order["id"], MANAGER))
    assert submitted["version"] != creation_version, "submit mutates the order"

    resp = api_client.schedule_delivery_order(
        order["id"],
        {"scheduled_for": "2026-08-10T00:00:00Z",
         "expected_delivery_order_version": creation_version},
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert resp.status_code == 412

    scheduled = validate_success(
        api_client.schedule_delivery_order(
            order["id"],
            {"scheduled_for": "2026-08-10T00:00:00Z",
             "expected_delivery_order_version": submitted["version"]},
            MANAGER,
        )
    )
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["version"] == submitted["version"] + 1
