"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API, so a
test may call any of them against an empty database. All setup calls use the
lenient success validator so a broken precondition surfaces as a setup failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_supplier_payload, create_fiber_grade_payload,
    create_market_index_quote_payload, create_paper_grade_spec_payload,
    create_paper_machine_payload, create_purchase_order_payload,
    create_receipt_payload, create_pulp_batch_payload, create_run_payload,
    complete_run_payload, create_roll_set_payload, create_customer_order_payload,
    create_effluent_permit_payload, create_effluent_reading_payload,
    create_sludge_manifest_payload, create_steam_allocation_payload,
    furnish_line, sublot, reel_reading,
)
from .test_users import TEST_USERS, make_supplier_headers, make_customer_headers

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
LAB = TEST_USERS["lab_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
CERTIFIER = TEST_USERS["lab_cert_headers"]
OPERATOR = TEST_USERS["operator_headers"]
OPERATOR_ALT = TEST_USERS["operator_alt_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENV_LOGGER = TEST_USERS["env_logger_headers"]
ENV_PREPARER = TEST_USERS["env_preparer_headers"]
ENV_SIGNER = TEST_USERS["env_signer_headers"]
ENERGY = TEST_USERS["energy_headers"]


# ============================================================ reference data ==

def declare_fiber_grade(**overrides) -> dict:
    return get_success_data(
        api_client.create_fiber_grade(create_fiber_grade_payload(**overrides), BUYER))


def declare_paper_grade_spec(**overrides) -> dict:
    return get_success_data(
        api_client.create_paper_grade_spec(create_paper_grade_spec_payload(**overrides),
                                           PLANNER))


def publish_quote(**overrides) -> dict:
    return get_success_data(
        api_client.create_market_index_quote(
            create_market_index_quote_payload(**overrides), BUYER))


def register_supplier(**overrides) -> dict:
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), BUYER))


def register_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), PLANNER))


def register_machine(**overrides) -> dict:
    return get_success_data(
        api_client.create_paper_machine(create_paper_machine_payload(**overrides), PLANNER))


def register_permit(**overrides) -> dict:
    return get_success_data(
        api_client.create_effluent_permit(create_effluent_permit_payload(**overrides), ENV))


def machine_version(machine_id: str) -> int:
    """Fresh read of a machine's version — cascades bump it, so never cache."""
    return get_success_data(api_client.get_paper_machine(machine_id, PLANNER))["version"]


def order_version(order_id: str) -> int:
    return get_success_data(api_client.get_customer_order(order_id, PLANNER))["version"]


def po_version(po_id: str) -> int:
    return get_success_data(api_client.get_purchase_order(po_id, BUYER))["version"]


def set_clock(to_iso8601: str, headers=None) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, headers or PLANNER))


# ============================== standard reference set used across the suite ==

# OCC_11 with the MIX_54 fallback; both are needed by every downgrade path.
def declare_standard_grades(occ_overrides=None, mix_overrides=None):
    """MIX_54 fallback grade plus OCC_11 pointing at it. Returns (occ, mix)."""
    mix_payload = {
        "grade_code": "MIX_54", "index_symbol": "PPI_OCC",
        "max_contamination_pct": 6.00, "max_moisture_pct": 14.00,
        "nominal_yield_pct": 78.00, "deink_required": False,
        "downgrade_target_grade_code": None, "rank_order": 5,
    }
    mix_payload.update(mix_overrides or {})
    mix = declare_fiber_grade(**mix_payload)
    occ_payload = {
        "grade_code": "OCC_11", "index_symbol": "PPI_OCC",
        "max_contamination_pct": 3.00, "max_moisture_pct": 12.00,
        "nominal_yield_pct": 88.00, "deink_required": False,
        "downgrade_target_grade_code": "MIX_54", "rank_order": 1,
    }
    occ_payload.update(occ_overrides or {})
    occ = declare_fiber_grade(**occ_payload)
    return occ, mix


def declare_tl_140(**overrides) -> dict:
    """The workhorse CONTAINERBOARD spec: no brightness requirement, no deink."""
    payload = {
        "product_code": "TL_140", "family": "CONTAINERBOARD",
        "basis_weight_gsm": 140.0, "target_moisture_pct": 7.50,
        "moisture_tolerance_pct": 0.80, "min_sct_kn_m": 2.20,
        "min_brightness_iso": None, "requires_deink_pulp": False,
        "rank_order": 10,
    }
    payload.update(overrides)
    return declare_paper_grade_spec(**payload)


def declare_tis_16(**overrides) -> dict:
    """A TISSUE spec that requires deinked pulp and carries a brightness floor."""
    payload = {
        "product_code": "TIS_16", "family": "TISSUE",
        "basis_weight_gsm": 16.0, "target_moisture_pct": 5.00,
        "moisture_tolerance_pct": 0.50, "min_sct_kn_m": 0.00,
        "min_brightness_iso": 78.0, "requires_deink_pulp": True,
        "rank_order": 40,
    }
    payload.update(overrides)
    return declare_paper_grade_spec(**payload)


# ================================================= purchase orders + receipts ==

def create_draft_po(supplier_id, fiber_grade_code="OCC_11", **overrides) -> dict:
    return get_success_data(api_client.create_purchase_order(
        create_purchase_order_payload(supplier_id, fiber_grade_code, **overrides), BUYER))


def create_priced_po(supplier_id, fiber_grade_code="OCC_11", **overrides) -> dict:
    po = create_draft_po(supplier_id, fiber_grade_code, **overrides)
    return get_success_data(api_client.price_purchase_order(
        po["id"], {"expected_purchase_order_version": po["version"]}, BUYER))


def create_confirmed_po(supplier_id, fiber_grade_code="OCC_11", **overrides) -> dict:
    po = create_priced_po(supplier_id, fiber_grade_code, **overrides)
    return get_success_data(api_client.confirm_purchase_order(
        po["id"], make_supplier_headers(supplier_id)))


def record_receipt(po_id, sublots_list=None, truck_reference=None,
                   sampler_headers=None) -> dict:
    payload = create_receipt_payload(
        **({"sublots": sublots_list} if sublots_list is not None else {}))
    if truck_reference is not None:
        payload["truck_reference"] = truck_reference
    return get_success_data(api_client.create_receipt(
        po_id, payload, sampler_headers or SAMPLER))


def disposition(receipt_id, verb, headers=None, **extra) -> dict:
    payload = {"disposition": verb}
    payload.update(extra)
    return get_success_data(api_client.disposition_receipt(
        receipt_id, payload, headers or DISPOSER))


def lots_of_receipt(receipt_id) -> list:
    data, _ = _paginated(api_client.list_inventory_lots(OPERATOR, {"receipt_id": receipt_id}))
    return data


def _paginated(response):
    body = response.json()
    return body["data"], body["meta"]


def setup_available_lot(sublots_list=None, grade_code="OCC_11",
                        contracted_tons=200.00, freight_per_ton=22.00,
                        supplier_name="Riverbend Fiber", declare_grades=True,
                        publish_index=True):
    """Reference data + supplier + CONFIRMED purchase order + ACCEPTED truck.

    Returns a dict with keys: supplier, purchase_order, receipt, lot.
    The default single sublot yields net_tons 36.00 at contamination 2.73 when
    the two-sublot recipe tonnages are passed in explicitly.
    """
    if declare_grades:
        declare_standard_grades()
    if publish_index:
        publish_quote(index_symbol="PPI_OCC", effective_month="2026-07",
                      published_price_per_ton=190.00)
        publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                      published_price_per_ton=195.00)
    supplier = register_supplier(name=supplier_name, freight_per_ton=freight_per_ton)
    po = create_confirmed_po(supplier["id"], grade_code,
                             contracted_tons=contracted_tons,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08")
    if sublots_list is None:
        sublots_list = [sublot(1, 22.000, 2.000, 14.50, 2.50),
                        sublot(2, 18.000, 1.500, 11.00, 3.00)]
    receipt = record_receipt(po["id"], sublots_list)
    disposition(receipt["id"], "ACCEPT")
    lots = lots_of_receipt(receipt["id"])
    assert lots, "Setup failed: acceptance did not create an inventory lot"
    return {"supplier": supplier, "purchase_order": po,
            "receipt": receipt, "lot": lots[0]}


# ================================================================ pulp batches ==

def queue_batch(target_product_code, furnish, pulper_line="OCC_LINE", **overrides) -> dict:
    return get_success_data(api_client.create_pulp_batch(
        create_pulp_batch_payload(target_product_code, furnish,
                                  pulper_line=pulper_line, **overrides), OPERATOR))


def drive_batch_to_cleaned(batch_id, measured_reject_tons=4.500) -> dict:
    get_success_data(api_client.start_pulp_batch(batch_id, OPERATOR))
    get_success_data(api_client.screen_pulp_batch(batch_id, OPERATOR))
    return get_success_data(api_client.clean_pulp_batch(
        batch_id, {"measured_reject_tons": measured_reject_tons}, OPERATOR))


def approve_batch(batch_id) -> dict:
    return get_success_data(api_client.approve_pulp_batch(batch_id, CERTIFIER))


def setup_approved_batch(target_product_code="TL_140", tons_charged=30.000,
                         measured_reject_tons=4.500, lot_bundle=None,
                         pulper_line="OCC_LINE", declare_spec=True):
    """Available lot -> QUEUED -> PULPING -> SCREENED -> CLEANED -> APPROVED.

    Returns a dict with keys: supplier, purchase_order, receipt, lot, batch.
    With the default recipe the batch carries charged_tons 30.000,
    provisional_accepted_tons 24.926 and final_accepted_tons 25.500.
    """
    if declare_spec:
        declare_tl_140()
    bundle = lot_bundle or setup_available_lot()
    batch = queue_batch(target_product_code,
                        [furnish_line(bundle["lot"]["id"], tons_charged)],
                        pulper_line=pulper_line)
    drive_batch_to_cleaned(batch["id"], measured_reject_tons)
    batch = approve_batch(batch["id"])
    out = dict(bundle)
    out["batch"] = batch
    return out


# ============================================================== production runs ==

def schedule_run(machine_id, product_code, pulp_batch_id, **overrides) -> dict:
    payload = create_run_payload(product_code, pulp_batch_id,
                                 machine_version(machine_id), **overrides)
    return get_success_data(api_client.create_run(machine_id, payload, PLANNER))


def start_run(machine_id, run_id, headers=None) -> dict:
    return get_success_data(api_client.start_run(machine_id, run_id, headers or OPERATOR))


def complete_run(machine_id, run_id, reel_readings=None, broke_tons=0.000,
                 headers=None) -> dict:
    return get_success_data(api_client.complete_run(
        machine_id, run_id,
        complete_run_payload(reel_readings=reel_readings, broke_tons=broke_tons),
        headers or OPERATOR))


ON_SPEC_REELS_TL_140 = [
    reel_reading(1, 5.000, 140.0, 7.50, 2.50),
    reel_reading(2, 5.000, 140.0, 7.50, 2.50),
]


def setup_run_ready_to_start(machine_overrides=None, run_overrides=None,
                             batch_overrides=None, permit_overrides=None,
                             with_permit=True):
    """Everything a run start needs: permit, machine, approved batch, SCHEDULED run.

    Returns a dict with keys: supplier, purchase_order, receipt, lot, batch,
    machine, run, permit (permit is None when with_permit is False).
    """
    permit = register_permit(**(permit_overrides or {})) if with_permit else None
    machine = register_machine(**(machine_overrides or {}))
    bundle = setup_approved_batch(**(batch_overrides or {}))
    run = schedule_run(machine["id"], "TL_140", bundle["batch"]["id"],
                       **(run_overrides or {}))
    out = dict(bundle)
    out.update({"machine": machine, "run": run, "permit": permit})
    return out


def setup_completed_run(reel_readings=None, broke_tons=0.000, **kwargs):
    """A run driven SCHEDULED -> RUNNING -> COMPLETED (quality axis PROVISIONAL)."""
    bundle = setup_run_ready_to_start(**kwargs)
    start_run(bundle["machine"]["id"], bundle["run"]["id"])
    bundle["run"] = complete_run(
        bundle["machine"]["id"], bundle["run"]["id"],
        reel_readings if reel_readings is not None else ON_SPEC_REELS_TL_140,
        broke_tons)
    return bundle


def setup_certified_run(reel_readings=None, broke_tons=0.000, **kwargs):
    """A COMPLETED run whose quality axis has been certified by a second identity."""
    bundle = setup_completed_run(reel_readings=reel_readings,
                                 broke_tons=broke_tons, **kwargs)
    bundle["run"] = get_success_data(api_client.certify_run(
        bundle["machine"]["id"], bundle["run"]["id"], CERTIFIER))
    return bundle


# ==================================================================== roll sets ==

def wind_roll_set(run_id, **overrides) -> dict:
    return get_success_data(api_client.create_roll_set(
        run_id, create_roll_set_payload(**overrides), OPERATOR))


def wrap_roll_set(roll_set_id, wrap_spec="KRAFT_ONLY") -> dict:
    return get_success_data(api_client.wrap_roll_set(
        roll_set_id, {"wrap_spec": wrap_spec}, OPERATOR))


# =============================================================== customer orders ==

def submit_order(customer, product_code="TL_140", **overrides) -> dict:
    headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.create_customer_order(
        create_customer_order_payload(customer["id"], product_code, **overrides),
        headers))


def schedule_order(order_id, run_id) -> dict:
    return get_success_data(api_client.schedule_customer_order(
        order_id, {"run_id": run_id, "expected_order_version": order_version(order_id)},
        PLANNER))


def allocate_roll_set(roll_set_id, order_id) -> dict:
    return get_success_data(api_client.allocate_roll_set(
        roll_set_id,
        {"order_id": order_id, "expected_order_version": order_version(order_id)},
        PLANNER))


def setup_order_in_production(ordered_tons=10.00, roll_width_mm=2400,
                              roll_diameter_mm=1400, wrap_spec="KRAFT_ONLY",
                              customer_overrides=None, order_overrides=None,
                              **kwargs):
    """Approved batch + machine + SCHEDULED run + order sequenced onto it, then the
    run started so the order sits in IN_PRODUCTION.

    Returns the run bundle plus keys: customer, order.
    """
    bundle = setup_run_ready_to_start(**kwargs)
    customer = register_customer(**(customer_overrides or {}))
    order = submit_order(customer, "TL_140", ordered_tons=ordered_tons,
                         roll_width_mm=roll_width_mm,
                         roll_diameter_mm=roll_diameter_mm,
                         wrap_spec=wrap_spec, **(order_overrides or {}))
    schedule_order(order["id"], bundle["run"]["id"])
    start_run(bundle["machine"]["id"], bundle["run"]["id"])
    bundle["customer"] = customer
    bundle["order"] = get_success_data(
        api_client.get_customer_order(order["id"], PLANNER))
    return bundle


def setup_wrapped_set_on_certified_run(ordered_tons=10.00, set_net_tons=5.000,
                                       reel_readings=None, **kwargs):
    """Order IN_PRODUCTION on a run that has produced one WRAPPED set and is CERTIFIED.

    Returns the bundle plus keys: customer, order, roll_set.
    """
    bundle = setup_order_in_production(ordered_tons=ordered_tons, **kwargs)
    machine_id = bundle["machine"]["id"]
    run_id = bundle["run"]["id"]
    roll_set = wind_roll_set(run_id, net_tons=set_net_tons)
    bundle["run"] = complete_run(
        machine_id, run_id,
        reel_readings if reel_readings is not None else ON_SPEC_REELS_TL_140)
    roll_set = wrap_roll_set(roll_set["id"])
    bundle["run"] = get_success_data(api_client.certify_run(machine_id, run_id, CERTIFIER))
    bundle["roll_set"] = roll_set
    bundle["order"] = get_success_data(
        api_client.get_customer_order(bundle["order"]["id"], PLANNER))
    return bundle


# ================================================================ environmental ==

def log_reading(permit_id, headers=None, **overrides) -> dict:
    return get_success_data(api_client.create_effluent_reading(
        permit_id, create_effluent_reading_payload(**overrides),
        headers or ENV_LOGGER))


def prepare_manifest(reject_stream_ids, headers=None, **overrides) -> dict:
    return get_success_data(api_client.create_sludge_manifest(
        create_sludge_manifest_payload(reject_stream_ids, **overrides),
        headers or ENV_PREPARER))


def sign_manifest(manifest_id, headers=None) -> dict:
    return get_success_data(api_client.sign_sludge_manifest(
        manifest_id, headers or ENV_SIGNER))


def solids_rows(**filters) -> list:
    data, _ = _paginated(api_client.list_reject_streams(ENV, filters or None))
    return data


def solids_summary() -> dict:
    return get_success_data(api_client.get_solids_summary(ENV))


def fiber_balance() -> dict:
    return get_success_data(api_client.get_fiber_balance(PLANNER))


def drive_permit_to_exceedance(permit_id, reading_date="2026-08-01"):
    """One reading whose BOD load lifts the rolling ratio above 1.00.

    Requires a permit registered with a bod_limit low enough for a single
    reading to breach it — pass bod_limit_kg_per_day=100.00 when registering.
    """
    return log_reading(permit_id, reading_date=reading_date,
                       flow_m3=100.00, bod_kg=500.00, tss_kg=10.00)


def request_steam(headers=None, **overrides) -> dict:
    return get_success_data(api_client.create_steam_allocation(
        create_steam_allocation_payload(**overrides), headers or ENERGY))


# ============================================== the deink route (DIP_LINE) ==

DLK_SUBLOTS = [sublot(1, 12.000, 1.000, 10.00, 1.50),
               sublot(2, 10.000, 1.000, 12.00, 1.80)]


def setup_deink_lot(contracted_tons=150.00, freight_per_ton=18.00,
                    sublots_list=None, declare_grade=True, publish_index=True):
    """DLK_37 grade + supplier + CONFIRMED order + ACCEPTED truck on a deink grade.

    With the default sublots the lot opens at tons_received 19.82 and
    contamination_pct 1.64.
    """
    if declare_grade:
        declare_fiber_grade(grade_code="DLK_37", index_symbol="PPI_DLK",
                            max_contamination_pct=2.00, max_moisture_pct=10.00,
                            nominal_yield_pct=72.00, deink_required=True,
                            downgrade_target_grade_code=None, rank_order=3)
    if publish_index:
        publish_quote(index_symbol="PPI_DLK", effective_month="2026-07",
                      published_price_per_ton=150.00)
    supplier = register_supplier(name="Northgate Recovered",
                                 freight_per_ton=freight_per_ton)
    po = create_confirmed_po(supplier["id"], "DLK_37",
                             contracted_tons=contracted_tons,
                             index_basis="PRIOR_MONTH", priced_for_month="2026-08")
    receipt = record_receipt(po["id"],
                            sublots_list if sublots_list is not None else DLK_SUBLOTS,
                            truck_reference="TRK-D-001")
    disposition(receipt["id"], "ACCEPT")
    lots = lots_of_receipt(receipt["id"])
    assert lots, "Setup failed: acceptance did not create an inventory lot"
    return {"supplier": supplier, "purchase_order": po,
            "receipt": receipt, "lot": lots[0]}


def setup_cleaned_deink_batch(tons_charged=15.000, measured_reject_tons=2.000,
                              spec_overrides=None, declare_spec=True,
                              lot_bundle=None, pulper_line="DIP_LINE"):
    """A DIP_LINE batch of a deink-requiring TISSUE grade driven to CLEANED."""
    if declare_spec:
        declare_tis_16(**(spec_overrides or {"min_brightness_iso": 80.0}))
    bundle = lot_bundle or setup_deink_lot()
    batch = queue_batch("TIS_16", [furnish_line(bundle["lot"]["id"], tons_charged)],
                        pulper_line=pulper_line)
    drive_batch_to_cleaned(batch["id"], measured_reject_tons)
    out = dict(bundle)
    out["batch"] = batch
    return out


def run_deink_pass(batch_id, caustic_kg, peroxide_kg, surfactant_kg) -> dict:
    return get_success_data(api_client.deink_pulp_batch(
        batch_id, {"caustic_kg": caustic_kg, "peroxide_kg": peroxide_kg,
                   "surfactant_kg": surfactant_kg}, OPERATOR))


def record_brightness(batch_id, brightness_iso, headers=None) -> dict:
    return get_success_data(api_client.record_brightness(
        batch_id, {"brightness_iso": brightness_iso}, headers or CERTIFIER))


def setup_batch_at_deink_hold(caustic_kg=40.0, peroxide_kg=25.0, surfactant_kg=6.0,
                              failing_brightness=78.0, **kwargs):
    """A DIP_LINE batch whose first deink pass fell short of the brightness floor."""
    bundle = setup_cleaned_deink_batch(**kwargs)
    run_deink_pass(bundle["batch"]["id"], caustic_kg, peroxide_kg, surfactant_kg)
    bundle["batch"] = record_brightness(bundle["batch"]["id"], failing_brightness)
    return bundle
