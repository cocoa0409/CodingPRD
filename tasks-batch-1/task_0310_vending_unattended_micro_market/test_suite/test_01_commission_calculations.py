"""Commission statement calculations: flat vs net guarantee floor, tiered
marginal bands with category exclusion, shrink chargeback rounding order, and
the finalize -> lifetime-balance ledger cascade.

All amounts are integer cents. Expected values are copied verbatim from the
design indices; they are not recomputed here.
"""
from test_helpers import (
    validate_success,
    api_client,
    counted_line,
)
from test_helpers import (
    set_clock, make_host, make_product, make_machine, make_slot, make_driver,
    make_route, make_stop, dispatch, open_visit, reconcile, make_sale,
    make_statement, machine_version,
)
from test_helpers.test_users import TEST_USERS, make_route_driver_headers

FIELD_OPS = TEST_USERS["field_ops_headers"]
FINANCE = TEST_USERS["finance_clerk_headers"]


def _stocked_machine_for_host(host, *, clock, slot_price, capacity, refill,
                              product_overrides=None, machine_overrides=None,
                              service_date=None):
    """Build a stocked single-slot machine under an existing host. Returns
    (machine, slot, driver, route, stop)."""
    product = make_product(**(product_overrides or {"sku": "C-PROD"}))
    machine = make_machine(host["id"], **(machine_overrides or {"asset_tag": "C-M"}))
    slot = make_slot(machine["id"], product["id"], slot_code="A1",
                     capacity=capacity, par_level=capacity, price_cents=slot_price)
    driver = make_driver(employee_code="C-EMP")
    route = make_route(driver["id"], service_date or clock)
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(slot["id"], 0, refill)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    return machine, slot, driver, route, stop


# ─── dual_variant_calc / dvc_gross_vs_net_commission_on_statement ──────────

def test_net_commission_floored_by_monthly_guarantee():
    """PRD §3.7: "The net_commission_cents is computed last, after both
    gross_commission_cents and shrink_chargeback_cents are known. The raw net is
    gross_commission_cents minus shrink_chargeback_cents, and the net commission
    is the larger of that raw net and the host's monthly_guarantee_cents, so the
    guarantee acts as a floor."
    PRD §3.7: "Under FLAT, it is the host's gross_sales_cents multiplied by
    flat_commission_pct, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/dvc_gross_vs_net_commission_on_statement
    """
    set_clock("2026-06-10T00:00:00Z")
    host = make_host(name="Lobby B", contact_email="b@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10,
                     monthly_guarantee_cents=80000)
    machine, slot, driver, route, stop = _stocked_machine_for_host(
        host, clock="2026-06-10T00:00:00Z", slot_price=150, capacity=40, refill=30,
        product_overrides={"sku": "SODA1", "name": "Soda", "category": "BEVERAGE", "unit_cost_cents": 30},
        machine_overrides={"asset_tag": "M-2", "machine_type": "BEVERAGE_VENDOR"},
    )
    # Two SETTLED cashless sales: gross 600 and 450 -> gross_sales 1050.
    make_sale(machine["id"], slot["id"], 4, "CASHLESS")
    make_sale(machine["id"], slot["id"], 3, "CASHLESS")
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    res = api_client.finalize_statement(statement["id"], FINANCE)
    final = validate_success(res, 200)
    assert final["gross_sales_cents"] == 1050, final
    assert final["gross_commission_cents"] == 105, final
    assert final["net_commission_cents"] == 80000, final


def test_flat_gross_commission_below_guarantee_still_recorded():
    """PRD §3.7: "Under FLAT, it is the host's gross_sales_cents multiplied by
    flat_commission_pct, rounded half-up to whole cents."
    PRD §3.7: "the net commission is the larger of that raw net and the host's
    monthly_guarantee_cents, so the guarantee acts as a floor."

    Design: Difficulty/dual_variant_calc/dvc_gross_vs_net_commission_on_statement
    """
    set_clock("2026-06-10T00:00:00Z")
    host = make_host(name="Lobby B2", contact_email="b2@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10,
                     monthly_guarantee_cents=80000)
    machine, slot, driver, route, stop = _stocked_machine_for_host(
        host, clock="2026-06-10T00:00:00Z", slot_price=150, capacity=40, refill=30,
        product_overrides={"sku": "SODA2", "name": "Soda", "category": "BEVERAGE", "unit_cost_cents": 30},
        machine_overrides={"asset_tag": "M-2b", "machine_type": "BEVERAGE_VENDOR"},
    )
    make_sale(machine["id"], slot["id"], 4, "CASHLESS")
    make_sale(machine["id"], slot["id"], 3, "CASHLESS")
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    # gross_commission (105) is strictly less than guarantee (80000), so net is the floor.
    assert final["gross_commission_cents"] == 105, final
    assert final["net_commission_cents"] == 80000, final
    assert final["net_commission_cents"] > final["gross_commission_cents"], final


# ─── combinatorial_formula / cf_tiered_commission... ───────────────────────

def test_tiered_commission_marginal_bands_excludes_fresh_food():
    """PRD §3.7: "Under TIERED, the system first forms a tiered base equal to the
    sum of gross_cents over the period's SETTLED sales whose slot's product
    category is not FRESH_FOOD (fresh food is excluded from the tiered base),
    then applies marginal band rates to that base: the portion of the tiered base
    from 0 up to but not including 500000 cents (that is, 5,000 dollars) is paid
    at 8 percent; the portion from 500000 cents up to but not including 1500000
    cents (that is, 15,000 dollars) is paid at 12 percent; and any portion at or
    above 1500000 cents is paid at 15 percent."
    PRD §3.7: "The three band contributions are summed and the total is rounded
    half-up to whole cents exactly once at the end (sum-then-round)."

    Design: Difficulty/combinatorial_formula/cf_tiered_commission_marginal_bands_with_category_exclusion
    """
    set_clock("2026-06-10T00:00:00Z")
    host = make_host(name="Tier Host", contact_email="t@x.com", commission_model="TIERED")
    snk = make_product(sku="SNK", name="Snack", category="SNACK", unit_cost_cents=100)
    frsh = make_product(sku="FRSH", name="Sandwich", category="FRESH_FOOD",
                        unit_cost_cents=200, shelf_life_days=3)
    machine = make_machine(host["id"], asset_tag="M-3", machine_type="MICRO_MARKET_KIOSK")
    snk_slot = make_slot(machine["id"], snk["id"], slot_code="S1",
                         capacity=1000, par_level=1000, price_cents=1000)
    frsh_slot = make_slot(machine["id"], frsh["id"], slot_code="S2",
                          capacity=1000, par_level=1000, price_cents=1000)
    driver = make_driver(full_name="Stocker", employee_code="EMP3")
    route = make_route(driver["id"], "2026-06-10T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(
        stop["id"],
        [counted_line(snk_slot["id"], 0, 1000), counted_line(frsh_slot["id"], 0, 1000)],
        v0, driver["id"],
    )
    reconcile(visit["id"], v0, driver["id"])
    # 800000 SNACK gross + 200000 FRESH_FOOD gross; tiered base excludes fresh -> 800000.
    make_sale(machine["id"], snk_slot["id"], 800, "CASHLESS")
    make_sale(machine["id"], frsh_slot["id"], 200, "CASHLESS")
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    assert final["gross_sales_cents"] == 1000000, final
    assert final["gross_commission_cents"] == 76000, final


def test_tiered_base_first_band_only():
    """PRD §3.7: "the portion of the tiered base from 0 up to but not including
    500000 cents (that is, 5,000 dollars) is paid at 8 percent".
    PRD §3.7: "the sum of gross_cents over the period's SETTLED sales whose slot's
    product category is not FRESH_FOOD (fresh food is excluded from the tiered
    base)".

    Design: Difficulty/combinatorial_formula/cf_tiered_commission_marginal_bands_with_category_exclusion
    """
    set_clock("2026-06-10T00:00:00Z")
    host = make_host(name="Tier Host 2", contact_email="t2@x.com", commission_model="TIERED")
    snk = make_product(sku="SNK2", name="Snack", category="SNACK", unit_cost_cents=100)
    machine = make_machine(host["id"], asset_tag="M-3b", machine_type="MICRO_MARKET_KIOSK")
    snk_slot = make_slot(machine["id"], snk["id"], slot_code="S1",
                         capacity=1000, par_level=1000, price_cents=1000)
    driver = make_driver(full_name="Stocker2", employee_code="EMP3b")
    route = make_route(driver["id"], "2026-06-10T00:00:00Z")
    stop = make_stop(route["id"], machine["id"])
    dispatch(route["id"])
    v0 = machine["version"]
    visit = open_visit(stop["id"], [counted_line(snk_slot["id"], 0, 1000)], v0, driver["id"])
    reconcile(visit["id"], v0, driver["id"])
    # 300 units * 1000c = 300000 gross, entirely within band 1 -> 300000 * 0.08 = 24000.
    make_sale(machine["id"], snk_slot["id"], 300, "CASHLESS")
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")

    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    assert final["gross_sales_cents"] == 300000, final
    assert final["gross_commission_cents"] == 24000, final


# ─── combinatorial_formula / cf_shrink_chargeback_round_per_visit_then_sum ──

def _shrink_host_with_two_visits():
    """Host FLAT 0.10; one slot price 1c; two reconciled visits whose
    shrink_value_cents come out to 101 and 103.

    Per PRD §3.5 a visit's shrink is the slot's pre-visit on_hand minus the
    line's physical_count (clamped at zero), valued at the slot's price_cents;
    reconcile only *adds* refill lots and never decrements on_hand for shrink.
    So a measurable shrink_value only arises on a *later* cycle whose
    physical_count falls short of the on_hand built up by earlier refills.
    Filler visits (physical_count == on_hand) carry zero shrink and so do not
    perturb the per-visit-rounded sum. Returns (host, visit_a, visit_b) where
    visit_a has shrink_value 101 and visit_b has shrink_value 103.
    """
    set_clock("2026-06-05T00:00:00Z")
    host = make_host(name="Shrink Host", contact_email="s@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10)
    prod = make_product(sku="PENNY", name="Penny Item", category="SNACK", unit_cost_cents=1)
    machine = make_machine(host["id"], asset_tag="M-4", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="P1",
                     capacity=300, par_level=300, price_cents=1)
    driver = make_driver(full_name="Pat", employee_code="EMP4")
    route = make_route(driver["id"], "2026-06-05T00:00:00Z")
    stop1 = make_stop(route["id"], machine["id"], 480, 540)
    stop2 = make_stop(route["id"], machine["id"], 600, 660)
    stop3 = make_stop(route["id"], machine["id"], 720, 780)
    stop4 = make_stop(route["id"], machine["id"], 840, 900)
    dispatch(route["id"])

    # Filler 1: fill 101 units against a fresh slot (theoretical 0 == physical 0,
    # so zero shrink). on_hand becomes 101.
    v = machine["version"]
    f1 = open_visit(stop1["id"], [counted_line(slot["id"], 0, 101)], v, driver["id"])
    reconcile(f1["id"], v, driver["id"])

    # Visit A: theoretical 101, physical 0, refill 0 -> shrink 101 units at 1c -> 101.
    v = machine_version(machine["id"])
    visit_a = open_visit(stop2["id"], [counted_line(slot["id"], 0, 0)], v, driver["id"])
    visit_a = reconcile(visit_a["id"], v, driver["id"])

    # Filler 2: theoretical 101 == physical 101 (zero shrink), refill 103 -> on_hand 204.
    v = machine_version(machine["id"])
    f2 = open_visit(stop3["id"], [counted_line(slot["id"], 101, 103)], v, driver["id"])
    reconcile(f2["id"], v, driver["id"])

    # Visit B: theoretical 204, physical 101, refill 0 -> shrink 103 units at 1c -> 103.
    v = machine_version(machine["id"])
    visit_b = open_visit(stop4["id"], [counted_line(slot["id"], 101, 0)], v, driver["id"])
    visit_b = reconcile(visit_b["id"], v, driver["id"])

    return host, visit_a, visit_b


def test_shrink_chargeback_rounds_per_visit_then_sums():
    """PRD §3.7: "For each RECONCILED restock visit on this host's machines whose
    reconcile time (its updated_at) falls within the period, the system takes that
    visit's shrink_value_cents, multiplies by the one-half host share, and rounds
    that product half-up to whole cents; it then sums those per-visit rounded
    chargebacks."
    PRD §3.7: "This rounding order — round each visit's chargeback to cents, then
    sum — is the opposite of the commission's sum-then-round order, and the two
    must not be conflated."

    Design: Difficulty/combinatorial_formula/cf_shrink_chargeback_round_per_visit_then_sum
    """
    host, visit1, visit2 = _shrink_host_with_two_visits()
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    # rhu(101*0.5)=51 + rhu(103*0.5)=52 = 103 (NOT rhu(204*0.5)=102).
    assert final["shrink_chargeback_cents"] == 103, final


def test_shrink_value_per_visit_matches_lost_retail():
    """PRD §3.5: "the line's shrink value is those shrink units multiplied by the
    slot's current price_cents, valuing each shrunk unit at lost retail revenue.
    The visit's total_shrink_units is the sum of the per-line shrink units, and
    its shrink_value_cents is the sum of the per-line shrink values; the per-line
    multiply-then-sum order is fixed."

    A second restock cycle on the same slot lets the driver report a physical_count
    short of the system on_hand, producing a measurable shrink_value.

    Design: Difficulty/combinatorial_formula/cf_shrink_chargeback_round_per_visit_then_sum
    """
    set_clock("2026-06-05T00:00:00Z")
    host = make_host(name="Shrink Host 2", contact_email="s2@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10)
    prod = make_product(sku="PENNY2", name="Penny Item", category="SNACK", unit_cost_cents=1)
    machine = make_machine(host["id"], asset_tag="M-4b", machine_type="SNACK_VENDOR")
    slot = make_slot(machine["id"], prod["id"], slot_code="P1",
                     capacity=200, par_level=200, price_cents=1)
    driver = make_driver(full_name="Pat2", employee_code="EMP4b")
    route = make_route(driver["id"], "2026-06-05T00:00:00Z")
    stop1 = make_stop(route["id"], machine["id"], 480, 540)
    dispatch(route["id"])
    v0 = machine["version"]
    # Fill 101 units (system on_hand becomes 101).
    visit1 = open_visit(stop1["id"], [counted_line(slot["id"], 0, 101)], v0, driver["id"])
    reconcile(visit1["id"], v0, driver["id"])
    v1 = machine_version(machine["id"])
    # Second visit: driver physically counts 0 against theoretical 101 -> shrink 101 units
    # at price 1c -> shrink_value 101; refills 0 so no overfill.
    stop2 = make_stop(route["id"], machine["id"], 600, 660)
    visit2 = open_visit(stop2["id"], [counted_line(slot["id"], 0, 0)], v1, driver["id"])
    reconciled2 = reconcile(visit2["id"], v1, driver["id"])
    assert reconciled2["total_shrink_units"] == 101, reconciled2
    assert reconciled2["shrink_value_cents"] == 101, reconciled2


# ─── transitive_cascade / tc_finalize_statement_lifetime_balance_depth2 ────

def _life_host_with_sale():
    set_clock("2026-06-15T00:00:00Z")
    host = make_host(name="Life Host", contact_email="l@x.com",
                     commission_model="FLAT", flat_commission_pct=0.10)
    machine, slot, driver, route, stop = _stocked_machine_for_host(
        host, clock="2026-06-15T00:00:00Z", slot_price=100, capacity=50, refill=50,
        product_overrides={"sku": "LIFE", "name": "Life Item", "category": "BEVERAGE", "unit_cost_cents": 20},
        machine_overrides={"asset_tag": "M-8", "machine_type": "BEVERAGE_VENDOR"},
    )
    make_sale(machine["id"], slot["id"], 10, "CASHLESS")  # gross 1000
    statement = make_statement(host["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    return host, statement


def test_finalize_credits_host_lifetime_balance():
    """PRD §3.7: "On finalize the four amounts are recomputed and frozen, the
    host's lifetime_commission_cents is increased by this statement's
    net_commission_cents (a ledger-sync cascade onto the host), and the
    statement's status becomes FINALIZED."

    Design: Difficulty/transitive_cascade/tc_finalize_statement_lifetime_balance_depth2
    """
    host, statement = _life_host_with_sale()
    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    assert final["net_commission_cents"] == 100, final
    assert final["status"] == "FINALIZED", final
    host_after = validate_success(api_client.get_host_site(host["id"], FIELD_OPS), 200)
    assert host_after["lifetime_commission_cents"] == 100, host_after


def test_net_commission_is_the_value_credited():
    """PRD §3.7: "the host's lifetime_commission_cents is increased by this
    statement's net_commission_cents (a ledger-sync cascade onto the host)".
    PRD §3.7: "Under FLAT, it is the host's gross_sales_cents multiplied by
    flat_commission_pct, rounded half-up to whole cents."

    The lifetime credit equals the computed net (10% of 1000 gross = 100), proving
    the cascade is driven by the computed net rather than emitted independently.

    Design: Difficulty/transitive_cascade/tc_finalize_statement_lifetime_balance_depth2
    """
    host, statement = _life_host_with_sale()
    before = validate_success(api_client.get_host_site(host["id"], FIELD_OPS), 200)
    assert before["lifetime_commission_cents"] == 0, before
    final = validate_success(api_client.finalize_statement(statement["id"], FINANCE), 200)
    after = validate_success(api_client.get_host_site(host["id"], FIELD_OPS), 200)
    credited = after["lifetime_commission_cents"] - before["lifetime_commission_cents"]
    assert credited == final["net_commission_cents"], (credited, final["net_commission_cents"])
    assert credited == 100, after
