"""Composite setup helpers that build multi-step preconditions from scratch.

The harness restarts the server before every test, so each test starts with
an empty database and a logical clock reading 2026-08-01T00:00:00Z.  Every
helper below therefore builds the state it needs exclusively through the
public API.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import INITIAL_CLOCK
from .test_users import (
    ACCOUNT_MANAGER,
    DIRECTOR_APPROVER,
    FLAVORIST_SUBMITTER,
    LAB_COMPOUNDER,
    LAB_QC,
    PURCHASING_MANAGER,
    REGULATORY_AFFAIRS,
)

# ---------------------------------------------------------------------------
# Instant arithmetic on the logical clock
# ---------------------------------------------------------------------------

def _parse(instant: str) -> datetime:
    body = instant.strip()
    assert body.endswith("Z")
    return datetime.fromisoformat(body[:-1]).replace(tzinfo=timezone.utc)


def _render(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_plus(instant: str, days: int = 0, hours: int = 0,
             minutes: int = 0, seconds: int = 0) -> str:
    """Return the instant shifted by the supplied offset, rendered in UTC."""
    return _render(_parse(instant) + timedelta(days=days, hours=hours,
                                               minutes=minutes, seconds=seconds))


RETENTION_FROM = INITIAL_CLOCK
RETENTION_UNTIL = iso_plus(INITIAL_CLOCK, days=90)
GRANT_EXPIRES_AT = iso_plus(INITIAL_CLOCK, days=30)
TEST_WINDOW_START = iso_plus(INITIAL_CLOCK, hours=9)
TEST_WINDOW_END = iso_plus(INITIAL_CLOCK, hours=10)


def set_clock(api, instant: str) -> Dict[str, Any]:
    """Move the logical clock to the supplied instant."""
    response = api.set_current_utc(f.set_clock_payload(instant), ACCOUNT_MANAGER)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

def create_brief(api, **overrides) -> Dict[str, Any]:
    """Intake one customer brief in DRAFT."""
    response = api.create_customer_brief(
        f.create_customer_brief_payload(**overrides), ACCOUNT_MANAGER)
    return get_success_data(response, 201)


def create_submitted_brief(api, **overrides) -> Dict[str, Any]:
    brief = create_brief(api, **overrides)
    response = api.submit_customer_brief(brief["id"], ACCOUNT_MANAGER)
    return get_success_data(response, 200)


def create_accepted_brief(api, **overrides) -> Dict[str, Any]:
    """Intake, submit and accept one brief; its version reaches 3."""
    brief = create_submitted_brief(api, **overrides)
    response = api.decide_customer_brief(
        brief["id"], f.brief_decision_payload("ACCEPTED"), DIRECTOR_APPROVER)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Raw materials and their certificates
# ---------------------------------------------------------------------------

def create_material(api, **overrides) -> Dict[str, Any]:
    response = api.create_raw_material(
        f.create_raw_material_payload(**overrides), PURCHASING_MANAGER)
    return get_success_data(response, 201)


def reprice_material(api, material_id: str, cost_per_kg_cents: int) -> Dict[str, Any]:
    response = api.reprice_raw_material(
        material_id,
        f.reprice_raw_material_payload(cost_per_kg_cents),
        PURCHASING_MANAGER)
    return get_success_data(response, 200)


def file_certificate(api, material_id: str, claim_type: str,
                     **overrides) -> Dict[str, Any]:
    """File one certificate; it lands in PENDING at version 1."""
    response = api.create_substantiation_record(
        f.create_substantiation_record_payload(material_id, claim_type, **overrides),
        REGULATORY_AFFAIRS)
    return get_success_data(response, 201)


def create_verified_certificate(api, material_id: str, claim_type: str,
                                **overrides) -> Dict[str, Any]:
    """File and verify one certificate; it lands in VERIFIED at version 2."""
    record = file_certificate(api, material_id, claim_type, **overrides)
    response = api.verify_substantiation_record(record["id"], REGULATORY_AFFAIRS)
    return get_success_data(response, 200)


def revoke_certificate(api, record_id: str,
                       revocation_reason: str = "certificate withdrawn by the issuing body"
                       ) -> Dict[str, Any]:
    response = api.revoke_substantiation_record(
        record_id, f.revoke_substantiation_record_payload(revocation_reason),
        REGULATORY_AFFAIRS)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Formulas and their component graph
# ---------------------------------------------------------------------------

def create_formula(api, brief_id: str, **overrides) -> Dict[str, Any]:
    response = api.create_formula(
        f.create_formula_payload(brief_id, **overrides), FLAVORIST_SUBMITTER)
    return get_success_data(response, 201)


def add_material_line(api, formula_id: str, material_id: str,
                      weight_pct: float, **overrides) -> Dict[str, Any]:
    response = api.add_formula_component(
        formula_id,
        f.raw_material_component_payload(material_id, weight_pct, **overrides),
        FLAVORIST_SUBMITTER)
    return get_success_data(response, 201)


def add_sub_formula_line(api, formula_id: str, sub_formula_id: str,
                         weight_pct: float, **overrides) -> Dict[str, Any]:
    response = api.add_formula_component(
        formula_id,
        f.sub_formula_component_payload(sub_formula_id, weight_pct, **overrides),
        FLAVORIST_SUBMITTER)
    return get_success_data(response, 201)


def cost_formula(api, formula_id: str) -> Dict[str, Any]:
    response = api.cost_formula(formula_id, FLAVORIST_SUBMITTER)
    return get_success_data(response, 200)


def submit_formula(api, formula_id: str, headers=None) -> Dict[str, Any]:
    response = api.submit_formula(formula_id, headers or FLAVORIST_SUBMITTER)
    return get_success_data(response, 200)


def approve_formula(api, formula_id: str, headers=None) -> Dict[str, Any]:
    response = api.decide_formula(
        formula_id, f.formula_decision_payload("APPROVED"),
        headers or DIRECTOR_APPROVER)
    return get_success_data(response, 200)


def rework_formula(api, formula_id: str, headers=None) -> Dict[str, Any]:
    response = api.decide_formula(
        formula_id, f.formula_decision_payload("REWORK_REQUIRED"),
        headers or DIRECTOR_APPROVER)
    return get_success_data(response, 200)


def build_costed_formula(api, brief_id: str, material_id: str,
                         weight_pct: float = 100.0, **overrides) -> Dict[str, Any]:
    """One single-line formula taken as far as COSTED."""
    formula = create_formula(api, brief_id, **overrides)
    add_material_line(api, formula["id"], material_id, weight_pct)
    return cost_formula(api, formula["id"])


def build_approved_formula(api, brief_id: str, material_id: str,
                           weight_pct: float = 100.0, **overrides) -> Dict[str, Any]:
    """One single-line formula taken all the way to APPROVED."""
    formula = build_costed_formula(api, brief_id, material_id, weight_pct, **overrides)
    submit_formula(api, formula["id"])
    return approve_formula(api, formula["id"])


def create_revision(api, formula_id: str, expected_formula_version: int,
                    name: str = "Vanilla Cream F2", **overrides) -> Dict[str, Any]:
    response = api.create_formula_revision(
        formula_id,
        f.create_formula_revision_payload(name, expected_formula_version, **overrides),
        FLAVORIST_SUBMITTER)
    return get_success_data(response, 201)


# ---------------------------------------------------------------------------
# Sample lots
# ---------------------------------------------------------------------------

def compound_lot(api, formula_id: str, batch_size_g: int = 500,
                 headers=None) -> Dict[str, Any]:
    """Compound one lot; it lands PENDING / HELD with every gram available."""
    response = api.create_sample_lot(
        f.create_sample_lot_payload(formula_id, batch_size_g),
        headers or LAB_COMPOUNDER)
    return get_success_data(response, 201)


def record_qc(api, lot_id: str, result: str = "PASSED", headers=None,
              **overrides) -> Dict[str, Any]:
    """Record the QC verdict with an operator other than the compounder."""
    response = api.record_lot_qc(
        lot_id, f.lot_qc_payload(result, **overrides), headers or LAB_QC)
    return get_success_data(response, 200)


def release_lot(api, lot_id: str, headers=None) -> Dict[str, Any]:
    response = api.release_sample_lot(lot_id, headers or LAB_COMPOUNDER)
    return get_success_data(response, 200)


def build_released_lot(api, formula_id: str, batch_size_g: int = 500) -> Dict[str, Any]:
    """Compound, QC-pass and release one lot of an approved formula."""
    lot = compound_lot(api, formula_id, batch_size_g)
    record_qc(api, lot["id"], "PASSED")
    return release_lot(api, lot["id"])


# ---------------------------------------------------------------------------
# Retention cabinets and aliquots
# ---------------------------------------------------------------------------

def create_cabinet(api, **overrides) -> Dict[str, Any]:
    response = api.create_retention_cabinet(
        f.create_retention_cabinet_payload(**overrides), LAB_COMPOUNDER)
    return get_success_data(response, 201)


def store_retention_sample(api, lot_id: str, cabinet_id: str, quantity_g: int = 100,
                           stored_from: str = RETENTION_FROM,
                           stored_until: str = RETENTION_UNTIL,
                           **overrides) -> Dict[str, Any]:
    response = api.create_retention_sample(
        f.create_retention_sample_payload(lot_id, cabinet_id, quantity_g,
                                          stored_from, stored_until, **overrides),
        LAB_COMPOUNDER)
    return get_success_data(response, 201)


def withdraw_retention_sample(api, retention_id: str,
                              withdrawal_reason: str = "customer request"
                              ) -> Dict[str, Any]:
    response = api.withdraw_retention_sample(
        retention_id, f.withdraw_retention_sample_payload(withdrawal_reason),
        LAB_COMPOUNDER)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Application rigs and tests
# ---------------------------------------------------------------------------

def create_rig(api, **overrides) -> Dict[str, Any]:
    response = api.create_application_rig(
        f.create_application_rig_payload(**overrides), LAB_COMPOUNDER)
    return get_success_data(response, 201)


def schedule_application_test(api, lot_id: str, rig_id: str,
                              dosage_pct: float,
                              consumed_g: int = 50,
                              window_start: str = TEST_WINDOW_START,
                              window_end: str = TEST_WINDOW_END,
                              **overrides) -> Dict[str, Any]:
    response = api.create_application_test(
        f.create_application_test_payload(lot_id, rig_id, window_start, window_end,
                                          dosage_pct, consumed_g, **overrides),
        LAB_COMPOUNDER)
    return get_success_data(response, 201)


def start_application_test(api, test_id: str) -> Dict[str, Any]:
    response = api.start_application_test(test_id, LAB_COMPOUNDER)
    return get_success_data(response, 200)


def record_application_test_result(api, test_id: str, aroma_score: float,
                                   taste_score: float,
                                   stability_score: float) -> Dict[str, Any]:
    response = api.record_application_test_result(
        test_id,
        f.application_test_result_payload(aroma_score, taste_score, stability_score),
        LAB_COMPOUNDER)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Shipments and the documentation packet
# ---------------------------------------------------------------------------

def create_shipment(api, lot_id: str, shipped_g: int = 100,
                    destination_country: str = "US", **overrides) -> Dict[str, Any]:
    response = api.create_shipment(
        f.create_shipment_payload(lot_id, shipped_g, destination_country, **overrides),
        ACCOUNT_MANAGER)
    return get_success_data(response, 201)


def assemble_packet(api, shipment_id: str) -> Dict[str, Any]:
    response = api.assemble_shipment_packet(shipment_id, REGULATORY_AFFAIRS)
    return get_success_data(response, 200)


def dispatch_shipment(api, shipment_id: str,
                      tracking_reference: str = "TRK-0001") -> Dict[str, Any]:
    response = api.dispatch_shipment(
        shipment_id, f.dispatch_shipment_payload(tracking_reference),
        REGULATORY_AFFAIRS)
    return get_success_data(response, 200)


def cancel_shipment(api, shipment_id: str,
                    cancellation_reason: str = "customer hold") -> Dict[str, Any]:
    response = api.cancel_shipment(
        shipment_id, f.cancel_shipment_payload(cancellation_reason), ACCOUNT_MANAGER)
    return get_success_data(response, 200)


# ---------------------------------------------------------------------------
# Scale-up batches
# ---------------------------------------------------------------------------

def request_scale_up_batch(api, formula_id: str, target_kg: int = 150,
                           **overrides) -> Dict[str, Any]:
    response = api.create_scale_up_batch(
        f.create_scale_up_batch_payload(formula_id, target_kg, **overrides),
        DIRECTOR_APPROVER)
    return get_success_data(response, 201)


def set_batch_tolerance(api, batch_id: str) -> Dict[str, Any]:
    response = api.set_batch_tolerance(batch_id, DIRECTOR_APPROVER)
    return get_success_data(response, 200)


def report_pilot_run(api, batch_id: str, measured_yield_kg: float) -> Dict[str, Any]:
    response = api.report_batch_pilot_run(
        batch_id, f.batch_pilot_run_payload(measured_yield_kg), LAB_COMPOUNDER)
    return get_success_data(response, 200)


def decide_batch(api, batch_id: str, decision: str, **overrides) -> Dict[str, Any]:
    response = api.decide_scale_up_batch(
        batch_id, f.batch_decision_payload(decision, **overrides), DIRECTOR_APPROVER)
    return get_success_data(response, 200)


def build_toleranced_batch(api, formula_id: str, target_kg: int = 150) -> Dict[str, Any]:
    batch = request_scale_up_batch(api, formula_id, target_kg)
    return set_batch_tolerance(api, batch["id"])


# ---------------------------------------------------------------------------
# Forecasts and disclosure grants
# ---------------------------------------------------------------------------

def publish_forecast(api, brief_id: str, expected_brief_version: int,
                     annual_volume_kg: int = 500,
                     unit_price_cents_per_kg: int = 10000,
                     **overrides) -> Dict[str, Any]:
    response = api.create_commercialization_forecast(
        f.create_commercialization_forecast_payload(
            brief_id, annual_volume_kg, unit_price_cents_per_kg,
            expected_brief_version, **overrides),
        ACCOUNT_MANAGER)
    return get_success_data(response, 201)


def issue_grant(api, brief_id: str, formula_id: str,
                disclosed_tier: str = "TIER_2_RESTRICTED",
                redaction_level: str = "FULL",
                expires_at: str = GRANT_EXPIRES_AT, **overrides) -> Dict[str, Any]:
    response = api.create_disclosure_grant(
        f.create_disclosure_grant_payload(brief_id, formula_id, disclosed_tier,
                                          expires_at, redaction_level, **overrides),
        DIRECTOR_APPROVER)
    return get_success_data(response, 201)


# ---------------------------------------------------------------------------
# Composite scenarios
#
# Each builder returns a plain dict of the records it created so a test can
# name whichever one it needs.  They compose: the lot scenario builds on the
# approved-formula scenario, the packet scenario builds on the lot scenario.
# ---------------------------------------------------------------------------

def build_formula_with_lines(api, brief_id: str, lines, **overrides) -> Dict[str, Any]:
    """Open a formula and add one raw-material line per (material_id, weight_pct)."""
    formula = create_formula(api, brief_id, **overrides)
    components = [add_material_line(api, formula["id"], material_id, weight_pct)
                  for material_id, weight_pct in lines]
    return {"formula": formula, "components": components}


def approved_formula_scenario(api, **brief_overrides) -> Dict[str, Any]:
    """One material at 2000 cents/kg, an accepted brief, an APPROVED formula.

    The formula holds a single line at 100 percent, so its bench cost equals
    the material's list price exactly.
    """
    material = create_material(api)
    brief = create_accepted_brief(api, **brief_overrides)
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    return {"material": material, "brief": brief, "formula": formula}


def released_lot_scenario(api, batch_size_g: int = 500,
                          **brief_overrides) -> Dict[str, Any]:
    """An approved formula plus one compounded, QC-passed, released lot."""
    scenario = approved_formula_scenario(api, **brief_overrides)
    scenario["lot"] = build_released_lot(api, scenario["formula"]["id"], batch_size_g)
    return scenario


def retention_scenario(api, batch_size_g: int = 500, quantity_g: int = 100,
                       **cabinet_overrides) -> Dict[str, Any]:
    """A released lot, a cabinet, and one stored aliquot drawn from the lot."""
    scenario = released_lot_scenario(api, batch_size_g)
    scenario["cabinet"] = create_cabinet(api, **cabinet_overrides)
    scenario["retention"] = store_retention_sample(
        api, scenario["lot"]["id"], scenario["cabinet"]["id"], quantity_g)
    return scenario


def application_test_scenario(api, batch_size_g: int = 500,
                              consumed_g: int = 50) -> Dict[str, Any]:
    """A released lot, a matching rig, and one SCHEDULED application test."""
    scenario = released_lot_scenario(api, batch_size_g)
    scenario["rig"] = create_rig(
        api, matrix_type=scenario["brief"]["matrix_type"])
    scenario["test"] = schedule_application_test(
        api, scenario["lot"]["id"], scenario["rig"]["id"],
        scenario["brief"]["dosage_pct"], consumed_g)
    return scenario


def certificate_backed_scenario(api, batch_size_g: int = 500,
                                **brief_overrides) -> Dict[str, Any]:
    """A released lot whose only leaf material holds a verified allergen certificate.

    ALLERGEN_STATEMENT is always a required packet document and is
    certificate-backed, so this is the minimum state from which a packet can
    be assembled.
    """
    scenario = released_lot_scenario(api, batch_size_g, **brief_overrides)
    scenario["allergen_certificate"] = create_verified_certificate(
        api, scenario["material"]["id"], "ALLERGEN_FREE_STATEMENT")
    return scenario


def assembled_shipment_scenario(api, shipped_g: int = 100,
                                destination_country: str = "US",
                                batch_size_g: int = 500,
                                **brief_overrides) -> Dict[str, Any]:
    """A released lot, a verified allergen certificate and a PACKET_ASSEMBLED shipment."""
    scenario = certificate_backed_scenario(api, batch_size_g, **brief_overrides)
    shipment = create_shipment(api, scenario["lot"]["id"], shipped_g,
                               destination_country)
    scenario["shipment"] = assemble_packet(api, shipment["id"])
    return scenario


def restricted_formula_scenario(api,
                                confidentiality_tier: str = "TIER_2_RESTRICTED",
                                redaction_level: str = "FULL",
                                disclosed_tier: Optional[str] = None,
                                expires_at: str = GRANT_EXPIRES_AT) -> Dict[str, Any]:
    """A tier-gated approved formula together with a disclosure grant for it."""
    material = create_material(api)
    brief = create_accepted_brief(api, confidentiality_tier=confidentiality_tier)
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    grant = issue_grant(api, brief["id"], formula["id"],
                        disclosed_tier or confidentiality_tier,
                        redaction_level, expires_at)
    return {"material": material, "brief": brief, "formula": formula, "grant": grant}


def forecast_scenario(api, annual_volume_kg: int = 500,
                      unit_price_cents_per_kg: int = 10000,
                      **brief_overrides) -> Dict[str, Any]:
    """An accepted brief carrying one ACTIVE risk-weighted forecast."""
    brief = create_accepted_brief(api, **brief_overrides)
    forecast = publish_forecast(api, brief["id"], brief["version"],
                                annual_volume_kg, unit_price_cents_per_kg)
    return {"brief": brief, "forecast": forecast}


# ---------------------------------------------------------------------------
# Small read helpers
# ---------------------------------------------------------------------------

def read_formula(api, formula_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_formula(formula_id, FLAVORIST_SUBMITTER), 200)


def read_lot(api, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sample_lot(lot_id, LAB_COMPOUNDER), 200)


def read_brief(api, brief_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_customer_brief(brief_id, ACCOUNT_MANAGER), 200)


def read_material(api, material_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_raw_material(material_id, PURCHASING_MANAGER), 200)


def read_cabinet(api, cabinet_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retention_cabinet(cabinet_id, LAB_COMPOUNDER), 200)


def read_retention_sample(api, retention_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_retention_sample(retention_id, LAB_COMPOUNDER), 200)


def read_shipment(api, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shipment(shipment_id, ACCOUNT_MANAGER), 200)


def read_batch(api, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_scale_up_batch(batch_id, DIRECTOR_APPROVER), 200)


def read_forecast(api, forecast_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_commercialization_forecast(forecast_id, ACCOUNT_MANAGER), 200)


def read_application_test(api, test_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_application_test(test_id, LAB_COMPOUNDER), 200)


def read_substantiation_record(api, record_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_substantiation_record(record_id, REGULATORY_AFFAIRS), 200)


def read_grant(api, grant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_disclosure_grant(grant_id, DIRECTOR_APPROVER), 200)


def read_component(api, component_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_formula_component(component_id, FLAVORIST_SUBMITTER), 200)


def list_data(api, list_method, headers=None, **params) -> Dict[str, Any]:
    """Call a list endpoint and return its parsed body."""
    response = list_method(headers or ACCOUNT_MANAGER, params or None)
    return response.json()


def documents_of(api, shipment_id: str) -> List[Dict[str, Any]]:
    body = api.list_regulatory_documents(
        REGULATORY_AFFAIRS, {"shipment_id": shipment_id, "limit": 100}).json()
    return body["data"]


def components_of(api, formula_id: str) -> List[Dict[str, Any]]:
    body = api.list_formula_components(
        FLAVORIST_SUBMITTER, {"formula_id": formula_id, "limit": 100}).json()
    return body["data"]


# ---------------------------------------------------------------------------
# The three-material citrus chain
#
# A beverage brief at dosage 2.5 percent, annual volume 1200 kg and a
# cost-in-use cap of 74425 cents per tonne, carrying a formula whose three
# lines are 3.7500 / 1.2500 / 95.0000 percent of materials priced 45333,
# 9876 and 1215 cents per kilogram.
# ---------------------------------------------------------------------------

CITRUS_LINE_WEIGHTS = (3.75, 1.25, 95.0)


def citrus_materials(api) -> Dict[str, Any]:
    """The three priced materials of the citrus chain."""
    m1 = create_material(api, material_code="CITRAL-NAT", name="Natural Citral",
                         cost_per_kg_cents=45333, natural_status="NATURAL",
                         potency_class="HIGH_IMPACT", max_use_ppm=50000)
    m2 = create_material(api, material_code="ETHYL-BUT",
                         name="Ethyl Butyrate Natural", cost_per_kg_cents=9876,
                         natural_status="NATURAL", potency_class="STANDARD",
                         max_use_ppm=20000)
    m3 = create_material(api, material_code="PG-SOLV",
                         name="Propylene Glycol Solvent", cost_per_kg_cents=1215,
                         natural_status="NATURE_IDENTICAL",
                         potency_class="STANDARD", max_use_ppm=1000000)
    return {"m1": m1, "m2": m2, "m3": m3}


def citrus_brief_payload(**overrides) -> Dict[str, Any]:
    payload = f.create_customer_brief_payload(
        brief_code="BRF-0001", customer_name="Nordic Beverages",
        matrix_type="BEVERAGE_STILL", target_profile="CITRUS_TOP_NOTE",
        dosage_pct=2.5, annual_volume_kg=1200,
        cost_in_use_cap_cents_per_tonne=74425,
        confidentiality_tier="TIER_1_STANDARD")
    payload.update(overrides)
    return payload


def citrus_submitted_brief(api, **overrides) -> Dict[str, Any]:
    """The citrus brief taken as far as SUBMITTED but not yet decided."""
    return create_submitted_brief(api, **citrus_brief_payload(**overrides))


def citrus_accepted_brief(api, **overrides) -> Dict[str, Any]:
    return create_accepted_brief(api, **citrus_brief_payload(**overrides))


def citrus_draft_formula(api, **brief_overrides) -> Dict[str, Any]:
    """Materials, an accepted brief and a DRAFT formula with all three lines."""
    materials = citrus_materials(api)
    brief = citrus_accepted_brief(api, **brief_overrides)
    built = build_formula_with_lines(
        api, brief["id"],
        [(materials["m1"]["id"], CITRUS_LINE_WEIGHTS[0]),
         (materials["m2"]["id"], CITRUS_LINE_WEIGHTS[1]),
         (materials["m3"]["id"], CITRUS_LINE_WEIGHTS[2])],
        name="Citrus Top Note F1")
    scenario = dict(materials)
    scenario["brief"] = brief
    scenario["formula"] = built["formula"]
    scenario["components"] = built["components"]
    return scenario


def citrus_costed_formula(api, **brief_overrides) -> Dict[str, Any]:
    scenario = citrus_draft_formula(api, **brief_overrides)
    scenario["formula"] = cost_formula(api, scenario["formula"]["id"])
    return scenario


def citrus_approved_formula(api, **brief_overrides) -> Dict[str, Any]:
    scenario = citrus_costed_formula(api, **brief_overrides)
    submit_formula(api, scenario["formula"]["id"])
    scenario["formula"] = approve_formula(api, scenario["formula"]["id"])
    return scenario


def citrus_released_lot(api, batch_size_g: int = 500,
                        **brief_overrides) -> Dict[str, Any]:
    scenario = citrus_approved_formula(api, **brief_overrides)
    scenario["lot"] = build_released_lot(api, scenario["formula"]["id"], batch_size_g)
    return scenario


# ---------------------------------------------------------------------------
# The kosher gum-base chain
#
# A dairy brief that demands the kosher claim, one material carrying both an
# allergen-free and a kosher certificate, and a formula built entirely from
# that single material.
# ---------------------------------------------------------------------------

def gum_base_material(api, **overrides) -> Dict[str, Any]:
    return create_material(api, material_code="GUM-BASE",
                           name="Gum Arabic Base", cost_per_kg_cents=2000,
                           natural_status="NATURE_IDENTICAL",
                           potency_class="STANDARD", max_use_ppm=1000000,
                           **overrides)


def dairy_brief_payload(**overrides) -> Dict[str, Any]:
    payload = f.create_customer_brief_payload(
        brief_code="BRF-0002", customer_name="Baltic Dairy",
        matrix_type="DAIRY_YOGURT", target_profile="VANILLA_CREAM",
        dosage_pct=1.0, annual_volume_kg=500,
        cost_in_use_cap_cents_per_tonne=100000,
        confidentiality_tier="TIER_1_STANDARD")
    payload.update(overrides)
    return payload


def kosher_chain(api, batch_size_g: int = 500, **brief_overrides) -> Dict[str, Any]:
    """A kosher-requiring brief, an approved formula and a released lot.

    The single leaf material holds a VERIFIED allergen-free certificate valid
    to 2027-06-30 and a VERIFIED kosher certificate valid to 2027-12-31, so
    the allergen certificate is the earlier of the two.
    """
    material = gum_base_material(api)
    allergen = create_verified_certificate(
        api, material["id"], "ALLERGEN_FREE_STATEMENT",
        issuing_body="Nordic Lab Services", document_ref="AF-2026-118",
        valid_until="2027-06-30T00:00:00Z")
    kosher = create_verified_certificate(
        api, material["id"], "KOSHER", issuing_body="Baltic Kosher Council",
        document_ref="KOS-2026-441", valid_until="2027-12-31T00:00:00Z")
    brief = create_accepted_brief(
        api, **dairy_brief_payload(kosher_required=True, **brief_overrides))
    formula = build_approved_formula(api, brief["id"], material["id"], 100.0)
    lot = build_released_lot(api, formula["id"], batch_size_g)
    return {"material": material, "allergen_certificate": allergen,
            "kosher_certificate": kosher, "brief": brief,
            "formula": formula, "lot": lot}


# ---------------------------------------------------------------------------
# Component-line removal and error-body access
# ---------------------------------------------------------------------------

def delete_component(api, component_id: str, headers=None) -> None:
    """Remove one component line; the endpoint answers 204 with no body."""
    response = api.delete_formula_component(component_id,
                                            headers or FLAVORIST_SUBMITTER)
    assert response.status_code == 204, (
        f"expected 204 from component removal, got {response.status_code}: "
        f"{response.text}")


def error_id_of(response) -> str:
    """The error_id carried in the standard error envelope's data object."""
    return response.json()["data"]["error_id"]
