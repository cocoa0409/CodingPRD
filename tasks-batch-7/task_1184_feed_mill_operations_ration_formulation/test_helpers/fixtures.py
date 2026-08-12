"""Composite setup helpers for the feed-mill test suite.

Every fixture builds its preconditions from scratch through the public API
(the runner restarts the server before each test, so nothing is carried over).
Setup steps use get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_ingredient_payload, create_price_tick_payload, create_contract_payload,
    create_bin_payload, create_customer_payload, create_employee_payload,
    create_formula_payload, create_order_payload, create_batch_payload,
    create_weighment_payload, create_sample_payload, create_sample_result_payload,
    create_flush_record_payload, create_line_payload, create_truck_payload,
    create_trip_payload,
)
from .test_users import (
    TEST_USERS, make_operator_headers, make_quality_tech_headers, make_customer_headers,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


# ---------------------------------------------------------------------------
# Atomic builders
# ---------------------------------------------------------------------------

def make_ingredient(profile="CORN", **overrides):
    """Create an ingredient as MillManager; returns the ingredient dict."""
    return get_success_data(api.create_ingredient(
        create_ingredient_payload(profile, **overrides), MM))


def add_price_tick(ingredient_id, price_cents_per_ton, effective_from="2026-04-01T00:00:00Z"):
    """Record a spot price tick; returns the PriceTick dict."""
    return get_success_data(api.create_price_tick(
        create_price_tick_payload(ingredient_id, price_cents_per_ton, effective_from), MM))


def make_contract(ingredient_id, **overrides):
    return get_success_data(api.create_contract(
        create_contract_payload(ingredient_id, **overrides), MM))


def make_customer(name="Acme Farms", credit_limit_cents=1000000, medicated_permit_ref=None):
    payload = create_customer_payload(name, credit_limit_cents)
    if medicated_permit_ref is not None:
        payload["medicated_permit_ref"] = medicated_permit_ref
    return get_success_data(api.create_customer(payload, MM))


def get_customer(customer_id):
    return get_success_data(api.get_customer(customer_id, MM))


def make_employee(full_name, capability):
    return get_success_data(api.create_employee(
        create_employee_payload(full_name, capability), MM))


def make_line(code="L1"):
    return get_success_data(api.create_line(create_line_payload(code), MM))


def make_bin(code, capacity_tons=50):
    return get_success_data(api.create_bin(create_bin_payload(code, capacity_tons), MM))


def make_stocked_bin(code, ingredient_id, tons, capacity_tons=50):
    """Create + assign + replenish a bin; returns the re-read bin dict."""
    b = make_bin(code, capacity_tons)
    get_success_data(api.assign_bin(b["id"], {"ingredient_id": ingredient_id}, MM))
    get_success_data(api.replenish_bin(b["id"], {"tons": tons}, MM))
    return get_success_data(api.get_bin(b["id"], MM))


def make_formula(code="F-GROW", min_protein_pct=19.5, max_fiber_pct=5.0,
                 min_energy_kcal_kg=3000):
    return get_success_data(api.create_formula(
        create_formula_payload(code, min_protein_pct, max_fiber_pct, min_energy_kcal_kg), NUT))


def optimize_formula(formula):
    """Optimize with the formula's current version (OCC per PRD §2.6)."""
    return get_success_data(api.optimize_formula(
        formula["id"], {"expected_formula_version": formula["version"]}, NUT))


def make_active_formula(code="F-GROW", min_protein_pct=19.5, max_fiber_pct=5.0,
                        min_energy_kcal_kg=3000):
    """Create + optimize + activate. Returns the ACTIVE formula dict."""
    f = make_formula(code, min_protein_pct, max_fiber_pct, min_energy_kcal_kg)
    f = optimize_formula(f)
    return get_success_data(api.activate_formula(f["id"], NUT))


def make_order(customer, formula_id, tons):
    """Create a QUOTED order as the Customer, reading the fresh customer
    version first (OCC per PRD §2.6). Returns the order dict."""
    fresh = get_customer(customer["id"])
    return get_success_data(api.create_order(
        create_order_payload(formula_id, tons, fresh["version"]),
        make_customer_headers(customer["id"])))


def confirm_order(order, customer_id):
    return get_success_data(api.confirm_order(order["id"], make_customer_headers(customer_id)))


def make_batch(order_id, line_id, target_tons,
               planned_start_at="2026-05-02T10:00:00Z",
               planned_end_at="2026-05-02T11:00:00Z"):
    return get_success_data(api.create_batch(
        create_batch_payload(order_id, line_id, target_tons,
                             planned_start_at, planned_end_at), MM))


def start_batch(batch_id, operator_id):
    return get_success_data(api.start_batch(batch_id, make_operator_headers(operator_id)))


def record_weighment(batch_id, ingredient_id, bin_id, actual_tons, operator_id):
    return get_success_data(api.record_weighment(
        batch_id, create_weighment_payload(ingredient_id, bin_id, actual_tons),
        make_operator_headers(operator_id)))


def mix_batch(batch_id, operator_id):
    return get_success_data(api.mix_batch(batch_id, make_operator_headers(operator_id)))


def collect_sample(batch_id, quality_tech_id, sample_type="COMPOSITE", retain_expiry_date=None):
    payload = create_sample_payload(batch_id, sample_type)
    if retain_expiry_date is not None:
        payload["retain_expiry_date"] = retain_expiry_date
    return get_success_data(api.create_sample(
        payload, make_quality_tech_headers(quality_tech_id)))


def enter_sample_result(sample_id, quality_tech_id, protein_pct_actual=20.0,
                        crude_fiber_pct_actual=4.0, moisture_pct=0):
    return get_success_data(api.submit_sample_result(
        sample_id,
        create_sample_result_payload(protein_pct_actual, crude_fiber_pct_actual, moisture_pct),
        make_quality_tech_headers(quality_tech_id)))


def release_batch(batch_id, quality_tech_id):
    return get_success_data(api.release_batch(
        batch_id, make_quality_tech_headers(quality_tech_id)))


def complete_order(order_id):
    return get_success_data(api.complete_order(order_id, MM))


def make_truck(plate_no="TRK-01", cargo_class_capability="STANDARD_ONLY", compartments=None):
    return get_success_data(api.create_truck(
        create_truck_payload(plate_no, cargo_class_capability, compartments), MM))


def advance_clock(to_iso8601):
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, MM))


# ---------------------------------------------------------------------------
# Composite scenarios
# ---------------------------------------------------------------------------

def setup_corn_sbm_catalog(corn_price=30000, sbm_price=52000):
    """CORN + SBM registered and priced. Returns {"corn": ..., "sbm": ...}."""
    corn = make_ingredient("CORN")
    sbm = make_ingredient("SBM")
    add_price_tick(corn["id"], corn_price)
    add_price_tick(sbm["id"], sbm_price)
    return {"corn": corn, "sbm": sbm}


def setup_active_grow_formula(corn_price=30000, sbm_price=52000,
                              code="F-GROW", min_protein_pct=19.5,
                              max_fiber_pct=5.0, min_energy_kcal_kg=3000):
    """CORN/SBM catalogue + an ACTIVE corn70/SBM30 formula (protein 19.5,
    fiber 2.44, energy 3080 at default prices; provisional cost 36600)."""
    cat = setup_corn_sbm_catalog(corn_price, sbm_price)
    formula = make_active_formula(code, min_protein_pct, max_fiber_pct, min_energy_kcal_kg)
    return {"formula": formula, "corn": cat["corn"], "sbm": cat["sbm"]}


def setup_confirmed_order(tons=10, credit_limit_cents=1000000,
                          customer_name="Acme Farms", medicated_permit_ref=None,
                          formula_code="F-GROW", corn_price=30000, sbm_price=52000,
                          formula_kwargs=None):
    """Catalogue + ACTIVE formula + customer + CONFIRMED order of `tons`.

    Returns ctx: formula, corn, sbm, customer, order.
    """
    fk = formula_kwargs or {}
    env = setup_active_grow_formula(corn_price, sbm_price, formula_code, **fk)
    customer = make_customer(customer_name, credit_limit_cents, medicated_permit_ref)
    order = make_order(customer, env["formula"]["id"], tons)
    order = confirm_order(order, customer["id"])
    return {**env, "customer": customer, "order": order}


def setup_batching_batch(target_tons=None, corn_stock=20, sbm_stock=20,
                         planned_start_at="2026-05-02T10:00:00Z",
                         planned_end_at="2026-05-02T11:00:00Z", **order_kwargs):
    """Confirmed order + operator/quality-tech employees + line L1 + stocked
    CORN/SBM bins + one batch moved PLANNED -> BATCHING.

    Returns ctx with: formula, corn, sbm, customer, order, op, qt, line,
    bin_corn, bin_sbm, batch.
    """
    ctx = setup_confirmed_order(**order_kwargs)
    tons = ctx["order"]["tons"] if target_tons is None else target_tons
    op = make_employee("Olly Operator", "OPERATOR")
    qt = make_employee("Quinn Quality", "QUALITY_TECH")
    line = make_line("L1")
    bin_corn = make_stocked_bin("BIN-C", ctx["corn"]["id"], corn_stock)
    bin_sbm = make_stocked_bin("BIN-S", ctx["sbm"]["id"], sbm_stock)
    batch = make_batch(ctx["order"]["id"], line["id"], tons,
                       planned_start_at, planned_end_at)
    batch = start_batch(batch["id"], op["id"])
    ctx.update({"op": op, "qt": qt, "line": line,
                "bin_corn": bin_corn, "bin_sbm": bin_sbm, "batch": batch})
    return ctx


def setup_mixed_batch(corn_actual=7.000, sbm_actual=3.000, target_tons=None,
                      capture_weighments=False, **kwargs):
    """BATCHING batch weighed on both pinned lines and mixed (BATCHING -> MIXED).

    Default targets derive from an order of 10t (corn 7.000 / SBM 3.000).
    """
    ctx = setup_batching_batch(target_tons=target_tons, **kwargs)
    w_corn = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                              ctx["bin_corn"]["id"], corn_actual, ctx["op"]["id"])
    w_sbm = record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                             ctx["bin_sbm"]["id"], sbm_actual, ctx["op"]["id"])
    batch = mix_batch(ctx["batch"]["id"], ctx["op"]["id"])
    ctx.update({"batch": batch, "w_corn": w_corn, "w_sbm": w_sbm})
    return ctx


def setup_released_batch(pass_protein=20.0, pass_fiber=4.0, pass_moisture=0,
                         **kwargs):
    """MIXED batch + PASS composite sample + release (MIXED -> RELEASED)."""
    ctx = setup_mixed_batch(**kwargs)
    sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
    sample = enter_sample_result(sample["id"], ctx["qt"]["id"],
                                 pass_protein, pass_fiber, pass_moisture)
    batch = release_batch(ctx["batch"]["id"], ctx["qt"]["id"])
    ctx.update({"batch": batch, "sample": sample})
    return ctx


def setup_completed_order(**kwargs):
    """Released batch + order completion (IN_PRODUCTION -> COMPLETED)."""
    ctx = setup_released_batch(**kwargs)
    order = complete_order(ctx["order"]["id"])
    ctx["order"] = order
    return ctx


def setup_medicated_mix_on_line():
    """Build a line whose contamination is MEDICATED.

    Ordering matters (PRD §2.8: an ingredient with no effective price is
    excluded from the optimizer's candidate set): the standard F-STD formula
    is optimized BEFORE the medicated additive is priced, so it solves to
    corn70/SBM30; F-MED is optimized after the MED-A tick, so it solves to
    med70/corn30. A permit-holding customer confirms a 1t medicated order;
    its batch is weighed 0.700/0.300 and mixed at the default clock, stamping
    the line MEDICATED.

    Returns ctx: med, corn, sbm, formula_std, formula_med, customer,
    order_med, op, line, bin_med, bin_corn, batch_med.
    """
    med = make_ingredient("MED-A")  # deliberately unpriced for now
    corn = make_ingredient("CORN")
    sbm = make_ingredient("SBM")
    add_price_tick(corn["id"], 30000)
    add_price_tick(sbm["id"], 52000)
    formula_std = make_active_formula("F-STD", min_protein_pct=19.5,
                                      max_fiber_pct=5.0, min_energy_kcal_kg=3000)
    add_price_tick(med["id"], 10000)
    formula_med = make_active_formula("F-MED", min_protein_pct=20.0,
                                      max_fiber_pct=5.0, min_energy_kcal_kg=2500)
    customer = make_customer("Permit Holder", 1000000, medicated_permit_ref="VFD-123")
    order_med = make_order(customer, formula_med["id"], 1)
    order_med = confirm_order(order_med, customer["id"])
    op = make_employee("Olly Operator", "OPERATOR")
    line = make_line("L1")
    bin_med = make_stocked_bin("BIN-M", med["id"], 10)
    bin_corn = make_stocked_bin("BIN-C", corn["id"], 10)
    batch_med = make_batch(order_med["id"], line["id"], 1,
                           "2026-05-02T08:00:00Z", "2026-05-02T09:00:00Z")
    batch_med = start_batch(batch_med["id"], op["id"])
    record_weighment(batch_med["id"], med["id"], bin_med["id"], 0.700, op["id"])
    record_weighment(batch_med["id"], corn["id"], bin_corn["id"], 0.300, op["id"])
    batch_med = mix_batch(batch_med["id"], op["id"])
    return {"med": med, "corn": corn, "sbm": sbm, "formula_std": formula_std,
            "formula_med": formula_med, "customer": customer,
            "order_med": order_med, "op": op, "line": line,
            "bin_med": bin_med, "bin_corn": bin_corn, "batch_med": batch_med}


def setup_standard_order_after_med(ctx, tons=1,
                                   planned_start_at="2026-05-02T13:00:00Z",
                                   planned_end_at="2026-05-02T14:00:00Z"):
    """On top of setup_medicated_mix_on_line: a CONFIRMED non-medicated order
    against F-STD for the same customer, plus a PLANNED batch for it on the
    contaminated line. Returns the batch dict (not yet started)."""
    order_std = make_order(ctx["customer"], ctx["formula_std"]["id"], tons)
    order_std = confirm_order(order_std, ctx["customer"]["id"])
    batch_std = make_batch(order_std["id"], ctx["line"]["id"], tons,
                           planned_start_at, planned_end_at)
    ctx.update({"order_std": order_std, "batch_std": batch_std})
    return batch_std
