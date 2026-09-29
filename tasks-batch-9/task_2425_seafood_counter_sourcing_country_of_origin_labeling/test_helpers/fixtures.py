"""Composite setup chains.

Every precondition is built through PRD-declared endpoints only: the harness
restarts the API before each test, so each chain starts from an empty database.
Ownership-gated calls thread the entity-backed identities of PRD §2.1 — a
SeafoodManager acts as the counter id, a SupplierRep as the supplier id.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import DEFAULT_CLOCK
from .test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_COOL_USER_ID,
    OFFICER_SAMPLING_USER_ID,
    make_chain_admin_headers,
    make_compliance_officer_headers,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
    make_supplier_rep_headers,
)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601: str = DEFAULT_CLOCK) -> None:
    """Move the server-held logical clock to the given instant."""
    response = api.set_clock({"to_iso8601": to_iso8601}, make_chain_admin_headers())
    get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Configuration records
# --------------------------------------------------------------------------
def register_counter(api, **overrides) -> dict:
    response = api.create_counter(factories.counter_payload(**overrides), make_chain_admin_headers())
    return get_success_data(response, expected_status=201)


def register_supplier(api, **overrides) -> dict:
    response = api.create_supplier(
        factories.supplier_payload(**overrides), make_chain_admin_headers()
    )
    return get_success_data(response, expected_status=201)


def register_species(api, payload: dict) -> dict:
    response = api.create_species(payload, make_chain_admin_headers())
    return get_success_data(response, expected_status=201)


def register_atlantic_cod(api, **overrides) -> dict:
    return register_species(api, factories.atlantic_cod_payload(**overrides))


def register_tilapia(api, **overrides) -> dict:
    return register_species(api, factories.tilapia_payload(**overrides))


def register_red_snapper(api, **overrides) -> dict:
    return register_species(api, factories.red_snapper_payload(**overrides))


def base_environment(api, clock: str = DEFAULT_CLOCK) -> dict:
    """Clock, one counter, one dealer and the Atlantic Cod species record."""
    set_clock(api, clock)
    counter = register_counter(api)
    supplier = register_supplier(api)
    cod = register_atlantic_cod(api)
    return {"counter": counter, "supplier": supplier, "cod": cod}


# --------------------------------------------------------------------------
# Lots
# --------------------------------------------------------------------------
def receive_lot(api, counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    response = api.create_lot(
        factories.lot_payload(counter_id, supplier_id, species_id, **overrides),
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=201)


def receive_tilapia_lot(api, counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    response = api.create_lot(
        factories.tilapia_lot_payload(counter_id, supplier_id, species_id, **overrides),
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=201)


def receive_snapper_lot(api, counter_id: str, supplier_id: str, species_id: str, **overrides) -> dict:
    response = api.create_lot(
        factories.snapper_lot_payload(counter_id, supplier_id, species_id, **overrides),
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=201)


def read_lot(api, counter_id: str, lot_id: str) -> dict:
    response = api.get_lot(lot_id, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def lot_version(api, counter_id: str, lot_id: str) -> int:
    return read_lot(api, counter_id, lot_id)["version"]


def case_lot(api, counter_id: str, lot_id: str, case_slot: int = 1) -> dict:
    response = api.case_lot(
        lot_id, {"case_slot": case_slot}, make_seafood_manager_headers(counter_id)
    )
    return get_success_data(response, expected_status=200)


def record_sales(api, counter_id: str, lot_id: str, sold_weight_kg: float) -> dict:
    response = api.record_sales(
        lot_id, {"sold_weight_kg": sold_weight_kg}, make_seafood_manager_headers(counter_id)
    )
    return get_success_data(response, expected_status=200)


def cased_lot(api, counter_id: str, supplier_id: str, species_id: str,
              case_slot: int = 1, **overrides) -> dict:
    """Receive a lot and place it straight into an ice-bed slot."""
    lot = receive_lot(api, counter_id, supplier_id, species_id, **overrides)
    return case_lot(api, counter_id, lot["id"], case_slot)


def relabel_lot(api, counter_id: str, lot_id: str, corrected_species_id: str,
                corrected_market_name: str) -> dict:
    response = api.relabel_lot(
        lot_id,
        {
            "corrected_species_id": corrected_species_id,
            "corrected_market_name": corrected_market_name,
        },
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=200)


def settle_chargeback(api, supplier_id: str, lot_id: str, payment_amount_cents: int) -> dict:
    response = api.settle_chargeback(
        lot_id,
        {"payment_amount_cents": payment_amount_cents},
        make_supplier_rep_headers(supplier_id),
    )
    return get_success_data(response, expected_status=200)


def reverse_chargeback(api, lot_id: str, reversal_note: str,
                       officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.reverse_chargeback(
        lot_id, {"reversal_note": reversal_note}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Case labels
# --------------------------------------------------------------------------
def publish_case_label(api, counter_id: str, lot_id: str, certification_id: str = None,
                       expected_lot_version: int = None) -> dict:
    """Publish a label, reading the lot's current version when none was supplied."""
    if expected_lot_version is None:
        expected_lot_version = lot_version(api, counter_id, lot_id)
    payload = factories.case_label_payload(lot_id, expected_lot_version)
    if certification_id is not None:
        payload["certification_id"] = certification_id
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=201)


def withdraw_case_label(api, counter_id: str, label_id: str, reason: str = "MANUAL") -> dict:
    response = api.withdraw_case_label(
        label_id, {"reason": reason}, make_seafood_manager_headers(counter_id)
    )
    return get_success_data(response, expected_status=200)


def read_case_label(api, counter_id: str, label_id: str) -> dict:
    response = api.get_case_label(label_id, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def list_case_labels(api, counter_id: str, params: dict = None) -> list:
    response = api.list_case_labels(make_seafood_manager_headers(counter_id), params=params)
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Advertisements
# --------------------------------------------------------------------------
def draft_ad_item(api, counter_id: str, lot_id: str, **overrides) -> dict:
    response = api.create_ad_item(
        factories.ad_item_payload(counter_id, lot_id, **overrides), make_merchandising_lead_headers()
    )
    return get_success_data(response, expected_status=201)


def clear_ad_cool(api, item_id: str, officer_id: str = OFFICER_COOL_USER_ID) -> dict:
    response = api.clear_ad_cool(
        item_id, {"decision": "CLEAR"}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def reject_ad_cool(api, item_id: str, rejection_category: str,
                   officer_id: str = OFFICER_COOL_USER_ID) -> dict:
    response = api.clear_ad_cool(
        item_id,
        {"decision": "REJECT", "rejection_category": rejection_category},
        make_compliance_officer_headers(officer_id),
    )
    return get_success_data(response, expected_status=200)


def clear_ad_claim(api, item_id: str, officer_id: str = OFFICER_CLAIM_USER_ID) -> dict:
    response = api.clear_ad_claim(
        item_id, {"decision": "CLEAR"}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def approved_ad_item(api, counter_id: str, lot_id: str, **overrides) -> dict:
    """Draft an advertisement and clear both review branches with two distinct officers."""
    item = draft_ad_item(api, counter_id, lot_id, **overrides)
    clear_ad_cool(api, item["id"])
    return clear_ad_claim(api, item["id"])


def publish_ad_item(api, item_id: str) -> dict:
    response = api.publish_ad_item(item_id, {}, make_merchandising_lead_headers())
    return get_success_data(response, expected_status=200)


def published_ad_item(api, counter_id: str, lot_id: str, **overrides) -> dict:
    """Take an advertisement all the way to a live window (the lot must carry a label)."""
    item = approved_ad_item(api, counter_id, lot_id, **overrides)
    return publish_ad_item(api, item["id"])


def read_ad_item(api, item_id: str) -> dict:
    response = api.get_ad_item(item_id, make_merchandising_lead_headers())
    return get_success_data(response, expected_status=200)


def list_ad_items(api, params: dict = None) -> list:
    response = api.list_ad_items(make_merchandising_lead_headers(), params=params)
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Cold chain
# --------------------------------------------------------------------------
def submit_reading(api, counter_id: str, case_slot: int, reading_at: str,
                   temperature_c: float, **overrides) -> dict:
    response = api.create_ice_bed_reading(
        factories.ice_bed_reading_payload(
            counter_id, case_slot, reading_at, temperature_c, **overrides
        ),
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=201)


def list_excursions(api, counter_id: str, params: dict = None) -> list:
    response = api.list_excursions(make_seafood_manager_headers(counter_id), params=params)
    return get_success_data(response, expected_status=200)


def open_excursion_on_slot(api, counter_id: str, case_slot: int, reading_at: str,
                           temperature_c: float = 6.2) -> dict:
    """Submit one breaching probe reading and return the excursion it opened."""
    submit_reading(api, counter_id, case_slot, reading_at, temperature_c)
    excursions = list_excursions(api, counter_id, {"case_slot": case_slot, "status": "OPEN"})
    assert len(excursions) == 1, f"expected exactly one open excursion, got {len(excursions)}"
    return excursions[0]


def resolve_excursion(api, excursion_id: str, resolution: str, note: str = None,
                      officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    payload = {"resolution": resolution}
    if note is not None:
        payload["note"] = note
    response = api.resolve_excursion(
        excursion_id, payload, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Verification samples
# --------------------------------------------------------------------------
def draw_sample(api, lot_id: str, officer_id: str = OFFICER_SAMPLING_USER_ID, **overrides) -> dict:
    response = api.create_verification_sample(
        factories.verification_sample_payload(lot_id, **overrides),
        make_compliance_officer_headers(officer_id),
    )
    return get_success_data(response, expected_status=201)


def send_sample_to_lab(api, sample_id: str, lab_reference: str,
                       officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.send_sample_to_lab(
        sample_id, {"lab_reference": lab_reference}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def record_sample_result(api, sample_id: str, observed_species_id: str,
                         officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.record_sample_result(
        sample_id,
        {"observed_species_id": observed_species_id},
        make_compliance_officer_headers(officer_id),
    )
    return get_success_data(response, expected_status=200)


def dispute_sample(api, supplier_id: str, sample_id: str, dispute_reason: str) -> dict:
    response = api.dispute_sample(
        sample_id, {"dispute_reason": dispute_reason}, make_supplier_rep_headers(supplier_id)
    )
    return get_success_data(response, expected_status=200)


def sample_with_result(api, lot_id: str, observed_species_id: str,
                       lab_reference: str = "LAB-A-0001") -> dict:
    """Draw a sample, send it to the laboratory and record the identification."""
    sample = draw_sample(api, lot_id)
    send_sample_to_lab(api, sample["id"], lab_reference)
    return record_sample_result(api, sample["id"], observed_species_id)


def close_verification_cycle(api, counter_id: str, expected_counter_version: int,
                             officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.close_verification_cycle(
        counter_id,
        {"expected_counter_version": expected_counter_version},
        make_compliance_officer_headers(officer_id),
    )
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Import-monitoring documents
# --------------------------------------------------------------------------
def create_simp_document(api, supplier_id: str, lot_id: str, **overrides) -> dict:
    response = api.create_simp_document(
        factories.simp_document_payload(lot_id, **overrides), make_supplier_rep_headers(supplier_id)
    )
    return get_success_data(response, expected_status=201)


def submit_simp_document(api, supplier_id: str, document_id: str, **payload) -> dict:
    response = api.submit_simp_document(
        document_id, dict(payload), make_supplier_rep_headers(supplier_id)
    )
    return get_success_data(response, expected_status=200)


def review_simp_document(api, document_id: str, decision: str, review_note: str = None,
                         officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    response = api.review_simp_document(
        document_id, payload, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def accepted_simp_document(api, supplier_id: str, lot_id: str, **overrides) -> dict:
    """Open, submit and accept an import-monitoring record for a covered-species lot."""
    document = create_simp_document(api, supplier_id, lot_id, **overrides)
    submit_simp_document(api, supplier_id, document["id"])
    return review_simp_document(api, document["id"], "ACCEPT")


# --------------------------------------------------------------------------
# Sustainability certifications
# --------------------------------------------------------------------------
def file_certification(api, counter_id: str, supplier_id: str, species_id: str,
                       **overrides) -> dict:
    response = api.create_certification(
        factories.certification_payload(counter_id, supplier_id, species_id, **overrides),
        make_supplier_rep_headers(supplier_id),
    )
    return get_success_data(response, expected_status=201)


def review_certification(api, certification_id: str, decision: str, review_note: str = None,
                         officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    payload = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    response = api.review_certification(
        certification_id, payload, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def enforce_certification(api, certification_id: str, decision: str, note: str = None,
                          officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    response = api.enforce_certification(
        certification_id, payload, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def active_certification(api, counter_id: str, supplier_id: str, species_id: str,
                         **overrides) -> dict:
    """File a certificate and approve it so its claim text is usable."""
    certification = file_certification(api, counter_id, supplier_id, species_id, **overrides)
    return review_certification(api, certification["id"], "APPROVE")


# --------------------------------------------------------------------------
# Shrink events
# --------------------------------------------------------------------------
def create_shrink_event(api, counter_id: str, lot_id: str, **overrides) -> dict:
    response = api.create_shrink_event(
        factories.shrink_event_payload(lot_id, **overrides),
        make_seafood_manager_headers(counter_id),
    )
    return get_success_data(response, expected_status=201)


def approve_conversion(api, counter_id: str, event_id: str) -> dict:
    response = api.approve_conversion(event_id, {}, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def convert_shrink_event(api, counter_id: str, event_id: str) -> dict:
    response = api.convert_shrink_event(event_id, {}, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def post_shrink_event(api, counter_id: str, event_id: str) -> dict:
    response = api.post_shrink_event(event_id, {}, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def reverse_shrink_event(api, event_id: str, reversal_note: str,
                         officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.reverse_shrink_event(
        event_id, {"reversal_note": reversal_note}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def list_shrink_events(api, counter_id: str, params: dict = None) -> list:
    response = api.list_shrink_events(make_seafood_manager_headers(counter_id), params=params)
    return get_success_data(response, expected_status=200)


def only_shrink_event(api, counter_id: str, lot_id: str) -> dict:
    events = list_shrink_events(api, counter_id, {"lot_id": lot_id})
    assert len(events) == 1, f"expected exactly one shrink event, got {len(events)}"
    return events[0]


# --------------------------------------------------------------------------
# Compliance violations
# --------------------------------------------------------------------------
def list_violations(api, counter_id: str, params: dict = None) -> list:
    response = api.list_violations(make_seafood_manager_headers(counter_id), params=params)
    return get_success_data(response, expected_status=200)


def only_violation(api, counter_id: str, params: dict = None) -> dict:
    violations = list_violations(api, counter_id, params)
    assert len(violations) == 1, f"expected exactly one violation, got {len(violations)}"
    return violations[0]


def cure_violation(api, counter_id: str, violation_id: str, cure_note: str) -> dict:
    response = api.cure_violation(
        violation_id, {"cure_note": cure_note}, make_seafood_manager_headers(counter_id)
    )
    return get_success_data(response, expected_status=200)


def expunge_violation(api, violation_id: str, expunge_note: str,
                      officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.expunge_violation(
        violation_id, {"expunge_note": expunge_note}, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


# --------------------------------------------------------------------------
# Read-back helpers
# --------------------------------------------------------------------------
def read_counter(api, counter_id: str) -> dict:
    response = api.get_counter(counter_id, make_chain_admin_headers())
    return get_success_data(response, expected_status=200)


def read_supplier(api, supplier_id: str) -> dict:
    response = api.get_supplier(supplier_id, make_chain_admin_headers())
    return get_success_data(response, expected_status=200)


def read_species(api, species_id: str) -> dict:
    response = api.get_species(species_id, make_chain_admin_headers())
    return get_success_data(response, expected_status=200)


def read_sample(api, sample_id: str, officer_id: str = OFFICER_SAMPLING_USER_ID) -> dict:
    response = api.get_verification_sample(
        sample_id, make_compliance_officer_headers(officer_id)
    )
    return get_success_data(response, expected_status=200)


def read_excursion(api, counter_id: str, excursion_id: str) -> dict:
    response = api.get_excursion(excursion_id, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def read_shrink_event(api, counter_id: str, event_id: str) -> dict:
    response = api.get_shrink_event(event_id, make_seafood_manager_headers(counter_id))
    return get_success_data(response, expected_status=200)


def read_certification(api, supplier_id: str, certification_id: str) -> dict:
    response = api.get_certification(certification_id, make_supplier_rep_headers(supplier_id))
    return get_success_data(response, expected_status=200)


def read_simp_document(api, supplier_id: str, document_id: str) -> dict:
    response = api.get_simp_document(document_id, make_supplier_rep_headers(supplier_id))
    return get_success_data(response, expected_status=200)
