"""Composite setup helpers — multi-step scenarios built from PRD endpoints.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the runner restarts the server before every test, so no state is
shared. Setup calls use get_success_data (lenient) so failures surface as
clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_import_entry_payload,
    create_processing_batch_payload,
    create_product_label_payload,
    create_receipt_lot_payload,
    create_species_verification_payload,
    create_supplier_evaluation_payload,
    create_supplier_payload,
)
from .test_users import TEST_USERS

CM = TEST_USERS["compliance_manager_headers"]
IC = TEST_USERS["import_coordinator_headers"]
RI = TEST_USERS["receiving_inspector_headers"]
QA = TEST_USERS["qa_tech_headers"]
PS = TEST_USERS["processing_supervisor_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

EVAL_PERIOD_START = "2024-01-01T00:00:00Z"
EVAL_PERIOD_END = "2024-12-31T00:00:00Z"
PASSING_SCORE = 90
ARRIVAL_FAR_FUTURE = "2026-08-10T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1 — supplier / entry progression
# ---------------------------------------------------------------------------

def create_supplier(name="Pacific Harvest Ltd", country="JP", frn="FRN-1000",
                    histamine=False, headers=None):
    """Create a ForeignSupplier (starts PENDING_EVALUATION). Returns supplier."""
    payload = create_supplier_payload(
        legal_name=name, country_code=country,
        facility_registration_number=frn,
        handles_histamine_susceptible_species=histamine,
    )
    return get_success_data(api_client.create_supplier(payload, headers or CM))


def create_approved_supplier(score=PASSING_SCORE, **supplier_kwargs):
    """Create a supplier and approve it via one passing evaluation.
    Returns the supplier dict (post-approval, refetched)."""
    supplier = create_supplier(**supplier_kwargs)
    evaluation = get_success_data(api_client.create_supplier_evaluation(
        create_supplier_evaluation_payload(
            supplier_id=supplier["id"],
            expected_supplier_version=supplier["version"],
            period_start=EVAL_PERIOD_START,
            period_end=EVAL_PERIOD_END,
            hazard_analysis_score=score,
            record_review_score=score,
            performance_score=score,
        ), CM))
    refreshed = get_success_data(api_client.get_supplier(supplier["id"], CM))
    return refreshed


def create_entry(supplier_id, entry_number="E-1001", species="COD",
                 transport_mode="ROAD",
                 scheduled_arrival=ARRIVAL_FAR_FUTURE,
                 goods_value_cents=100000, freight_cost_cents=5000,
                 duty_rate_pct=0.0, total_weight_kg=100, port_code="USBLA",
                 headers=None):
    """Create an ImportEntry in DRAFT. Returns the entry."""
    payload = create_import_entry_payload(
        supplier_id=supplier_id, entry_number=entry_number,
        species_declared=species, transport_mode=transport_mode,
        scheduled_arrival=scheduled_arrival, port_code=port_code,
        goods_value_cents=goods_value_cents,
        freight_cost_cents=freight_cost_cents, duty_rate_pct=duty_rate_pct,
        total_weight_kg=total_weight_kg,
    )
    return get_success_data(api_client.create_import_entry(payload,
                                                           headers or IC))


def release_entry(entry_id, headers=None):
    """Walk an entry DRAFT -> PRIOR_NOTICE_FILED -> ENTRY_FILED -> RELEASED."""
    h = headers or IC
    get_success_data(api_client.file_prior_notice(entry_id, h))
    get_success_data(api_client.file_entry(entry_id, h))
    return get_success_data(api_client.fda_disposition(entry_id, "RELEASED", h))


def create_released_entry(supplier_id, **entry_kwargs):
    """Create an entry and walk it to RELEASED. Returns the released entry."""
    entry = create_entry(supplier_id, **entry_kwargs)
    return release_entry(entry["id"])


# ---------------------------------------------------------------------------
# Tier 2 — receipt lots
# ---------------------------------------------------------------------------

def create_lot(entry_id, species="COD", grade="A", quantity_received_kg=100,
               ice_deduction_pct=0, harvest_country_code="US",
               production_method="WILD", freeze_protocol="NONE",
               vessel_name="FV Harbor", harvest_date="2026-07-20T00:00:00Z",
               catch_area_code="FAO67", receiving_temp_c=1.0, headers=None):
    """Create a ReceiptLot (UNDER_INSPECTION) against a RELEASED entry."""
    payload = create_receipt_lot_payload(
        import_entry_id=entry_id, vessel_name=vessel_name,
        harvest_date=harvest_date, catch_area_code=catch_area_code,
        harvest_country_code=harvest_country_code,
        production_method=production_method, species_declared=species,
        grade=grade, quantity_received_kg=quantity_received_kg,
        ice_deduction_pct=ice_deduction_pct, receiving_temp_c=receiving_temp_c,
        freeze_protocol=freeze_protocol,
    )
    return get_success_data(api_client.create_receipt_lot(payload,
                                                          headers or RI))


def verify_species(lot_id, verified_species, test_method="SENSORY",
                   sample_size=3, headers=None):
    """Record a species verification for a lot."""
    payload = create_species_verification_payload(
        receipt_lot_id=lot_id, test_method=test_method,
        sample_size=sample_size, verified_species=verified_species,
    )
    return get_success_data(api_client.create_species_verification(payload,
                                                                   headers or RI))


def record_histamine_pass(lot_id, measured_value=30.0, headers=None):
    """Record a SCREENING HISTAMINE record that PASSES (< 50.0 ppm)."""
    return get_success_data(api_client.create_haccp_record(
        {
            "hazard_type": "HISTAMINE",
            "receipt_lot_id": lot_id,
            "phase": "SCREENING",
            "measured_value": measured_value,
            "measured_at": "2026-07-25T10:00:00Z",
        }, headers or QA))


def accept_lot(lot_id, headers=None):
    """Accept a lot whose gates are all satisfied. Returns accepted lot."""
    return get_success_data(api_client.accept_receipt_lot(lot_id,
                                                          headers or RI))


def create_accepted_lot(entry_id, species="COD", verified_species=None,
                        histamine_susceptible=False, **lot_kwargs):
    """Create a lot, satisfy verification (+ histamine PASS when susceptible),
    and accept it. Returns the ACCEPTED lot."""
    lot = create_lot(entry_id, species=species, **lot_kwargs)
    verify_species(lot["id"], verified_species or species)
    if histamine_susceptible:
        record_histamine_pass(lot["id"])
    return accept_lot(lot["id"])


# ---------------------------------------------------------------------------
# Tier 3 — processing batches and full lifecycle
# ---------------------------------------------------------------------------

def create_batch(target_species="COD", product_form="FILLET", headers=None):
    """Create a ProcessingBatch (IN_PROCESS)."""
    return get_success_data(api_client.create_processing_batch(
        create_processing_batch_payload(
            target_species=target_species, product_form=product_form),
        headers or PS))


def add_input(batch_id, lot_id, quantity_kg, headers=None):
    """Add a batch input row (lot must be ACCEPTED)."""
    return get_success_data(api_client.add_batch_input(
        batch_id, {"receipt_lot_id": lot_id, "quantity_kg": quantity_kg},
        headers or PS))


def complete_batch(batch_id, actual_output_kg, trim_waste_kg, other_waste_kg,
                   headers=None):
    """Complete a batch, reading the fresh OCC version first."""
    h = headers or PS
    batch = get_success_data(api_client.get_processing_batch(batch_id, h))
    return get_success_data(api_client.complete_batch(
        batch_id,
        {
            "expected_batch_version": batch["version"],
            "actual_output_kg": actual_output_kg,
            "trim_waste_kg": trim_waste_kg,
            "other_waste_kg": other_waste_kg,
        }, h))


def create_completed_batch(lot_id, consume_kg, actual_output_kg,
                           trim_waste_kg, other_waste_kg,
                           target_species="COD", product_form="FILLET",
                           complete_headers=None):
    """Create a batch, consume the lot, complete it. Returns the COMPLETED
    batch dict."""
    batch = create_batch(target_species=target_species, product_form=product_form)
    add_input(batch["id"], lot_id, consume_kg)
    return complete_batch(batch["id"], actual_output_kg, trim_waste_kg,
                          other_waste_kg, headers=complete_headers)


# ---------------------------------------------------------------------------
# Tier 4 — labels and finished lots
# ---------------------------------------------------------------------------

def create_approved_label(species="COD", market_name="Pacific Cod",
                          supersedes_label_id=None, headers=None, **extra):
    """Create a ProductLabel and approve it. Returns the APPROVED label."""
    payload = create_product_label_payload(
        species=species, market_name=market_name,
        supersedes_label_id=supersedes_label_id, **extra)
    if supersedes_label_id is None:
        payload.pop("supersedes_label_id", None)
    label = get_success_data(api_client.create_product_label(payload,
                                                             headers or CM))
    return get_success_data(api_client.approve_product_label(label["id"],
                                                             headers or CM))


def create_finished_lot(batch_id, net_weight_kg, headers=None):
    """Create a FinishedProductLot (UNLABELED) from a COMPLETED/RECONCILED
    batch."""
    return get_success_data(api_client.create_finished_lot(
        {"processing_batch_id": batch_id, "net_weight_kg": net_weight_kg},
        headers or PS))
