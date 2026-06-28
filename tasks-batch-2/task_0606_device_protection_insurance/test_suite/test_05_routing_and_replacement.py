"""Routing repair vs replace, replacement-value calculation, stock cascade and OCC on ship.

Covers difficulty rules dual_variant_calc (replacement value book vs capped),
combinatorial_formula (floor then cap), non_linear_state_machine (branch fork),
boundary_precision_check (zero stock), cross_entity_state_dependency (ship requires routed),
compensating_invariant (cancel restores stock), and corner/cross_cutting instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, SKU_BOOK, SKU_CAPPED,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# dual_variant_calc: replacement value book vs capped
# --------------------------------------------------------------------------
def test_replacement_value_book_vs_capped_diverges(api, admin_headers, adjuster_headers):
    """PRD 3.8: "When the depreciated value is strictly below the plan's
    `replacement_value_cap_cents`, the claim pays the depreciated book value on a
    chronological device-age basis. When the depreciated value is at least the plan's
    `replacement_value_cap_cents`, the claim pays the plan cap instead".
    PRD 3.8: "the raw value is the SKU's `msrp_cents` minus the depreciation amount,
    where the depreciation amount is the SKU's `msrp_cents` multiplied by its
    `depreciation_rate_bps_per_month`, multiplied by the age in months, divided by
    10000, and rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/replacement_value_book_vs_capped_diverges
    """
    fx.set_clock()
    # SKU_BOOK: 90000 - round(90000*200*6/10000)=90000-10800=79200 (< cap 80000) -> book value
    book = fx.setup_routed_replace(carrier="CA-DV-1A", sku_overrides=dict(SKU_BOOK), peril="LOST")
    assert book["claim"]["replacement_value_cents"] == 79200, \
        f"book value expected 79200, got {book['claim']['replacement_value_cents']}"
    # SKU_CAPPED: 200000 - round(200000*100*6/10000)=200000-12000=188000 (>= cap) -> cap 80000
    capped = fx.setup_routed_replace(carrier="CA-DV-1B", sku_overrides=dict(SKU_CAPPED), peril="LOST")
    assert capped["claim"]["replacement_value_cents"] == 80000, \
        f"capped value expected 80000, got {capped['claim']['replacement_value_cents']}"


def test_replacement_value_net_payout_diverges_book_vs_capped(api, admin_headers, adjuster_headers):
    """PRD 3.8: "The `net_payout_cents` is the `replacement_value_cents` minus the
    claim's `deductible_cents`, floored at zero so it never goes negative."
    PRD 3.6: "for a `LOST` or `THEFT` claim the tier base is the plan's
    `base_deductible_cents` multiplied by the plan's `loss_deductible_multiplier_bps`
    and divided by 10000, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/replacement_value_book_vs_capped_diverges
    """
    fx.set_clock()
    # LOST deductible: 10000 * 15000/10000 = 15000
    book = fx.setup_routed_replace(carrier="CA-DV-1C", sku_overrides=dict(SKU_BOOK), peril="LOST")
    assert book["claim"]["net_payout_cents"] == 79200 - 15000  # 64200
    capped = fx.setup_routed_replace(carrier="CA-DV-1D", sku_overrides=dict(SKU_CAPPED), peril="LOST")
    assert capped["claim"]["net_payout_cents"] == 80000 - 15000  # 65000


# --------------------------------------------------------------------------
# combinatorial_formula: floor then cap nonlinear
# --------------------------------------------------------------------------
def test_replacement_value_floor_binds(api, admin_headers, adjuster_headers):
    """PRD 3.8: "The depreciated value is then the greater of that raw value and a
    minimum residual floor of 5000 cents. Finally, `replacement_value_cents` is the
    lesser of the depreciated value and the plan's `replacement_value_cap_cents`."

    Design: Difficulty/combinatorial_formula/replacement_value_floor_then_cap_nonlinear
    """
    fx.set_clock()
    # SKU_FLOOR: msrp 60000, dep 2000bps/mo, age 6 -> dep amount = round(60000*2000*6/10000)=72000
    # raw = 60000 - 72000 = -12000; max(.,5000)=5000; min(5000,cap)=5000
    floor = fx.setup_routed_replace(carrier="CA-DV-4",
                                    sku_overrides={"model_name": "FLOOR", "msrp_cents": 60000,
                                                   "depreciation_rate_bps_per_month": 2000,
                                                   "stock_on_hand": 5},
                                    peril="LOST")
    assert floor["claim"]["replacement_value_cents"] == 5000, \
        f"floor expected 5000, got {floor['claim']['replacement_value_cents']}"


def test_replacement_value_floor_net_payout_floored_at_zero(api, admin_headers, adjuster_headers):
    """PRD 3.8: "The `net_payout_cents` is the `replacement_value_cents` minus the
    claim's `deductible_cents`, floored at zero so it never goes negative."

    Design: Difficulty/combinatorial_formula/replacement_value_floor_then_cap_nonlinear
    """
    fx.set_clock()
    floor = fx.setup_routed_replace(carrier="CA-DV-4B",
                                    sku_overrides={"model_name": "FLOOR", "msrp_cents": 60000,
                                                   "depreciation_rate_bps_per_month": 2000,
                                                   "stock_on_hand": 5},
                                    peril="LOST")
    # rv 5000 - deductible 15000 -> floored at 0
    assert floor["claim"]["net_payout_cents"] == 0


# --------------------------------------------------------------------------
# non_linear_state_machine: branch fork repair vs replace
# --------------------------------------------------------------------------
def test_cracked_economical_routes_repair(api, admin_headers, adjuster_headers):
    """PRD 3.7: "The claim is routed to the repair branch — `ROUTED_REPAIR` — when the
    peril is `CRACKED` and the supplied `repair_cost_cents` is less than or equal to the
    depreciated replacement value computed for this claim".
    PRD 3.7: "When routing to repair, the system creates a repair order in `OPEN` status
    carrying the supplied `repair_cost_cents`, pins the claim's `routing` to `REPAIR`,
    sets the claim status to `ROUTED_REPAIR`".

    Design: Difficulty/non_linear_state_machine/claim_branch_fork_repair_vs_replace
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-5A", sku_overrides=dict(SKU_BOOK))
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    routed = fx.route_claim(cl["id"], repair_cost_cents=30000)  # 30000 <= 79200 -> REPAIR
    assert routed["routing"] == "REPAIR" and routed["status"] == "ROUTED_REPAIR"
    ro = fx.repair_order_for_claim(cl["id"])
    assert ro["claim_id"] == cl["id"]
    axs, _ = fx._list(api.list_advanced_exchanges(adjuster_headers, params={"claim_id": cl["id"]}))
    assert axs == [], "no advanced exchange should exist for a repair-routed claim"


def test_cracked_over_cost_routes_replace_and_decrements_stock(api, admin_headers, adjuster_headers):
    """PRD 3.7: "The claim is routed to the replace branch — `ROUTED_REPLACE` — when the
    peril is `LOST` or `THEFT`, or when the peril is `CRACKED` but the supplied
    `repair_cost_cents` is strictly greater than the depreciated replacement value
    computed for this claim."
    PRD 3.7: "creates an advanced exchange in `RESERVED` status ... decrements that SKU's
    `stock_on_hand` by one as the unit is reserved".

    Design: Difficulty/non_linear_state_machine/claim_branch_fork_repair_vs_replace
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-5B", sku_overrides=dict(SKU_BOOK))
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    routed = fx.route_claim(cl["id"], repair_cost_cents=90000)  # 90000 > 79200 -> REPLACE
    assert routed["routing"] == "REPLACE" and routed["status"] == "ROUTED_REPLACE"
    ax = fx.exchange_for_claim(cl["id"])
    assert ax["claim_id"] == cl["id"]
    sku = validate_success(api.get_replacement_sku(base["sku"]["id"], admin_headers))
    assert sku["stock_on_hand"] == 4, f"expected stock 4 after reserve, got {sku['stock_on_hand']}"


# --------------------------------------------------------------------------
# cross_cutting: cascade route replace decrements stock
# --------------------------------------------------------------------------
def test_route_replace_decrements_stock_creates_reserved_exchange(api, admin_headers, adjuster_headers):
    """PRD 2.6: "When a claim is routed to replacement, the chosen replacement SKU's
    `stock_on_hand` is decremented as a unit is reserved."
    PRD 3.7: "creates an advanced exchange in `RESERVED` status whose `replacement_sku_id`
    is copied from the enrollment, decrements that SKU's `stock_on_hand` by one".

    Design: Corner/cross_cutting_complexity_layers/cascade_route_replace_decrements_stock
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-25", sku_overrides=dict(SKU_BOOK))
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="LOST", incident_at="2026-05-10T00:00:00Z")
    routed = fx.route_claim(cl["id"])
    assert routed["routing"] == "REPLACE" and routed["status"] == "ROUTED_REPLACE"
    sku = validate_success(api.get_replacement_sku(base["sku"]["id"], admin_headers))
    assert sku["stock_on_hand"] == 4
    ax = fx.exchange_for_claim(cl["id"])
    assert ax["status"] == "RESERVED"


# --------------------------------------------------------------------------
# boundary_precision_check: zero stock -> ERR_NO_STOCK
# --------------------------------------------------------------------------
def test_route_replace_zero_stock_rejected(api, admin_headers, adjuster_headers):
    """PRD 3.7: "When routing to replace, the system requires that the enrollment's
    replacement SKU has `stock_on_hand` of at least 1; if no unit is available the
    request is rejected with `ERR_NO_STOCK`."

    Design: Difficulty/boundary_precision_check/route_replace_zero_stock_empty_pool
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-12",
                                       sku_overrides={"model_name": "NOSTOCK", "msrp_cents": 90000,
                                                      "depreciation_rate_bps_per_month": 200,
                                                      "stock_on_hand": 0})
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="LOST", incident_at="2026-05-10T00:00:00Z")
    resp = api.route_claim(cl["id"], {}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_NO_STOCK.value, 409)
    after = validate_success(api.get_claim(cl["id"], adjuster_headers))
    assert after["status"] == "APPROVED", "claim must stay APPROVED"
    sku = validate_success(api.get_replacement_sku(base["sku"]["id"], admin_headers))
    assert sku["stock_on_hand"] == 0, "stock must not decrement on rejected route"


def test_route_replace_zero_stock_via_corner_stub(api, admin_headers, adjuster_headers):
    """PRD 3.7: "the system requires that the enrollment's replacement SKU has
    `stock_on_hand` of at least 1; if no unit is available the request is rejected with
    `ERR_NO_STOCK`."

    Design: Difficulty/boundary_precision_check/route_replace_zero_stock_empty_pool
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-DV-12B",
                                       sku_overrides={"model_name": "NOSTOCK2", "msrp_cents": 90000,
                                                      "depreciation_rate_bps_per_month": 200,
                                                      "stock_on_hand": 0})
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="LOST", incident_at="2026-05-10T00:00:00Z")
    resp = api.route_claim(cl["id"], {}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_NO_STOCK.value, 409)


# --------------------------------------------------------------------------
# Corner: route CRACKED missing repair_cost_cents
# --------------------------------------------------------------------------
def test_route_cracked_missing_repair_cost_rejected(api, admin_headers, adjuster_headers):
    """PRD 3.7: "For a `CRACKED` claim the route payload must supply `repair_cost_cents`;
    if it is missing the request is rejected with `ERR_ROUTE_INPUT_MISSING`."

    Design: Corner/validations/route_cracked_missing_repair_cost_returns_error
    """
    fx.set_clock()
    base = fx.create_active_enrollment(carrier="CA-CN-18", sku_overrides=dict(SKU_BOOK))
    enr = base["enrollment"]
    cl = fx.submit_screen_approve(enr["id"], peril="CRACKED", incident_at="2026-05-10T00:00:00Z")
    resp = api.route_claim(cl["id"], {}, adjuster_headers)
    validate_error(resp, ApiErrorId.ERR_ROUTE_INPUT_MISSING.value, 422)


# --------------------------------------------------------------------------
# cross_entity_state_dependency: ship requires claim ROUTED_REPLACE
# --------------------------------------------------------------------------
def test_ship_exchange_succeeds_when_claim_routed_replace(api, admin_headers, logistics_headers):
    """PRD 3.10: "Shipping moves a `RESERVED` exchange to `SHIPPED`, and is permitted
    only when the parent claim is in `ROUTED_REPLACE` status ... On success the status
    becomes `SHIPPED`, `return_due_at` is set to the current logical clock plus the
    return window of 30 days".

    Design: Difficulty/cross_entity_state_dependency/exchange_ship_requires_claim_routed_replace
    """
    fx.set_clock()
    base = fx.setup_routed_replace(carrier="CA-DV-14", peril="LOST")
    assert base["claim"]["status"] == "ROUTED_REPLACE"
    ax = base["exchange"]
    shipped = validate_success(api.ship_advanced_exchange(
        ax["id"], {"expected_claim_version": base["claim_version"]}, logistics_headers))
    assert shipped["status"] == "SHIPPED"
    assert shipped["return_due_at"] is not None, "return_due_at must be set after ship"


def test_ship_sets_return_due_at(api, admin_headers, logistics_headers):
    """PRD 3.10: "On success the status becomes `SHIPPED`, `return_due_at` is set to the
    current logical clock plus the return window of 30 days, and the exchange's
    `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/exchange_ship_requires_claim_routed_replace
    """
    fx.set_clock()
    base = fx.setup_routed_replace(carrier="CA-DV-14B", peril="LOST")
    ax = base["exchange"]
    before_v = ax["version"]
    shipped = validate_success(api.ship_advanced_exchange(
        ax["id"], {"expected_claim_version": base["claim_version"]}, logistics_headers))
    assert shipped["return_due_at"] is not None
    assert shipped["version"] == before_v + 1


# --------------------------------------------------------------------------
# OCC on ship: stale claim version
# --------------------------------------------------------------------------
def test_ship_stale_claim_version_rejected(api, admin_headers, logistics_headers):
    """PRD 2.5: "The ship request must carry `expected_claim_version` matching the target
    claim's current `version`. If the claim's version has advanced since the client last
    observed it ... the dispatch is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_ship_rejected
    """
    fx.set_clock()
    base = fx.setup_routed_replace(carrier="CA-CN-24", peril="LOST")
    ax = base["exchange"]
    stale = base["claim_version"] - 1
    resp = api.ship_advanced_exchange(ax["id"], {"expected_claim_version": stale}, logistics_headers)
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value, 412)
    after = validate_success(api.get_advanced_exchange(ax["id"], logistics_headers))
    assert after["status"] == "RESERVED", "exchange must stay RESERVED"


# --------------------------------------------------------------------------
# compensating_invariant: cancel restores stock
# --------------------------------------------------------------------------
def test_cancel_reserved_exchange_restores_stock(api, admin_headers, logistics_headers):
    """PRD 2.6: "When a reserved exchange is cancelled, that same unit is returned to
    `stock_on_hand` as a compensating restore."
    PRD 3.10: "Cancellation is the compensating action for the stock reservation taken at
    replace routing: it increments the replacement SKU's `stock_on_hand` by one to
    restore the reserved unit".

    Design: Difficulty/compensating_invariant/exchange_cancel_restores_stock_invariant
    """
    fx.set_clock()
    base = fx.setup_routed_replace(carrier="CA-DV-17", sku_overrides=dict(SKU_BOOK), peril="LOST")
    sku_after_route = validate_success(api.get_replacement_sku(base["sku"]["id"], admin_headers))
    assert sku_after_route["stock_on_hand"] == 4
    ax = base["exchange"]
    cancelled = validate_success(api.cancel_advanced_exchange(ax["id"], logistics_headers))
    assert cancelled["status"] == "CANCELLED"
    sku_after_cancel = validate_success(api.get_replacement_sku(base["sku"]["id"], admin_headers))
    assert sku_after_cancel["stock_on_hand"] == 5, \
        f"stock must restore to 5, got {sku_after_cancel['stock_on_hand']}"


def test_cancel_reserved_exchange_terminal_cancelled(api, admin_headers, logistics_headers):
    """PRD 3.10: "A reserved exchange may be cancelled by a `LogisticsAgent` while it is
    still in `RESERVED` status, moving it to `CANCELLED`."

    Design: Difficulty/compensating_invariant/exchange_cancel_restores_stock_invariant
    """
    fx.set_clock()
    base = fx.setup_routed_replace(carrier="CA-DV-17B", sku_overrides=dict(SKU_BOOK), peril="LOST")
    ax = base["exchange"]
    cancelled = validate_success(api.cancel_advanced_exchange(ax["id"], logistics_headers))
    assert cancelled["status"] == "CANCELLED"
