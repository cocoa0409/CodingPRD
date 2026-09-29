"""Payload factories.

Each factory returns a valid-by-default request body that can be narrowed with
keyword overrides, e.g. ``supplier_payload(country_code="us")``. Money and mass
values are emitted as JSON numbers, never as strings.
"""

import itertools

from .constants import CLOCK_DEFAULT_SHORT
from .types import (
    ANNEX_A2_HEFA,
    DOC_ORIGIN_ATTESTATION,
    FEEDSTOCK_UCO,
    INSTRUMENT_FEEDSTOCK_SWAP,
    PROGRAM_LCFS,
    SCOPE_CATALYST_CHANGE,
)

_hash_counter = itertools.count(1)
_name_counter = itertools.count(1)


def unique_doc_hash(prefix: str = "doc-hash") -> str:
    """A per-process unique document hash of at least 8 characters."""
    return f"{prefix}-{next(_hash_counter):06d}"


def unique_unit_name(prefix: str = "HTU") -> str:
    """A per-process unique hydrotreating-unit name of at most 40 characters."""
    return f"{prefix}-{next(_name_counter):04d}"


# ---------------------------------------------------------------------------
# Suppliers and documents
# ---------------------------------------------------------------------------
def supplier_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Gulf Coast Renderers LLC",
        "country_code": "US",
        "feedstock_types": [FEEDSTOCK_UCO],
        "is_high_risk_origin": False,
    }
    payload.update(overrides)
    return payload


def traceability_document_payload(**overrides) -> dict:
    payload = {
        "doc_type": DOC_ORIGIN_ATTESTATION,
        "issued_at": "2026-07-01T00:00:00Z",
        "valid_until": "2027-12-31T00:00:00Z",
        "doc_hash": unique_doc_hash(),
    }
    payload.update(overrides)
    return payload


def due_diligence_payload(**overrides) -> dict:
    payload = {"valid_months": 12}
    payload.update(overrides)
    return payload


def suspension_payload(**overrides) -> dict:
    payload = {"reason": "Chain-of-custody attestation withdrawn by the certification body."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Feedstock lots, quality tests, pretreatment
# ---------------------------------------------------------------------------
def feedstock_lot_payload(supplier_id, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "feedstock_type": FEEDSTOCK_UCO,
        "mass_mt": 500.000,
        "attested_ci_gco2e_per_mj": 32.50,
        "purchase_price_usd_per_mt": 900.00,
        "received_at": CLOCK_DEFAULT_SHORT,
    }
    payload.update(overrides)
    return payload


def quality_test_payload(expected_lot_version, **overrides) -> dict:
    """A clean PASS test (tier NONE, fee 0.00) unless overridden."""
    payload = {
        "ffa_pct": 1.00,
        "moisture_pct": 0.20,
        "insolubles_ppm": 100,
        "phosphorus_ppm": 5,
        "sampled_at": CLOCK_DEFAULT_SHORT,
        "expected_lot_version": expected_lot_version,
    }
    payload.update(overrides)
    return payload


def pretreatment_payload(output_mass_mt, **overrides) -> dict:
    payload = {"output_mass_mt": output_mass_mt}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Units, charges, turnaround windows
# ---------------------------------------------------------------------------
def unit_payload(**overrides) -> dict:
    payload = {
        "name": "HTU-1",
        "nameplate_capacity_mt_per_day": 400.0,
        "max_saf_share_pct": 40.00,
    }
    payload.update(overrides)
    return payload


def catalyst_charge_payload(**overrides) -> dict:
    payload = {"design_throughput_mt": 60000.0, "installed_at": "2026-08-02T00:00:00Z"}
    payload.update(overrides)
    return payload


def turnaround_window_payload(**overrides) -> dict:
    payload = {
        "scope": SCOPE_CATALYST_CHANGE,
        "start_at": "2026-08-01T00:00:00Z",
        "end_at": "2026-08-03T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hydrogen
# ---------------------------------------------------------------------------
def hydrogen_contract_payload(**overrides) -> dict:
    payload = {
        "vendor_name": "Praxair Gulf",
        "daily_capacity_kg": 5000.0,
        "price_usd_per_kg": 3.50,
        "window_start": "2026-08-25T00:00:00Z",
        "window_end": "2026-09-30T00:00:00Z",
        "hydrogen_ci_gco2e_per_mj": 90.00,
    }
    payload.update(overrides)
    return payload


def nomination_payload(run_id, **overrides) -> dict:
    payload = {
        "run_id": run_id,
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2026-09-05T00:00:00Z",
        "kg_per_day": 2600.0,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Campaigns, allocations, completion
# ---------------------------------------------------------------------------
def processing_run_payload(unit_id, catalyst_charge_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "catalyst_charge_id": catalyst_charge_id,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-09-06T00:00:00Z",
        "target_saf_share_pct": 0.00,
    }
    payload.update(overrides)
    return payload


def allocation_payload(lot_id, mass_mt, expected_run_version, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "mass_mt": mass_mt,
        "expected_run_version": expected_run_version,
    }
    payload.update(overrides)
    return payload


def completion_payload(measured_rd_mt, measured_saf_mt=0.000, **overrides) -> dict:
    payload = {"measured_rd_mt": measured_rd_mt, "measured_saf_mt": measured_saf_mt}
    payload.update(overrides)
    return payload


def abort_payload(**overrides) -> dict:
    payload = {"reason": "Reactor pressure excursion; campaign abandoned."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------
def certification_request_payload(**overrides) -> dict:
    payload = {"astm_annex": ANNEX_A2_HEFA, "freeze_point_c": -47.0}
    payload.update(overrides)
    return payload


def certification_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def reservation_payload(**overrides) -> dict:
    payload = {"offtaker_name": "Chevron Products"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Pathways and credits
# ---------------------------------------------------------------------------
def pathway_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "program": PROGRAM_LCFS,
        "feedstock_type": FEEDSTOCK_UCO,
        "proposed_ci_gco2e_per_mj": 41.25,
    }
    payload.update(overrides)
    return payload


def review_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def credit_block_payload(batch_id, pathway_id, **overrides) -> dict:
    payload = {"batch_id": batch_id, "pathway_id": pathway_id}
    payload.update(overrides)
    return payload


def verification_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def retirement_payload(credits, **overrides) -> dict:
    payload = {"credits": credits}
    payload.update(overrides)
    return payload


def reversal_payload(**overrides) -> dict:
    payload = {"reason": "Registry rejected the retirement filing; credits returned to the account."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Hedges
# ---------------------------------------------------------------------------
def hedge_position_payload(**overrides) -> dict:
    payload = {
        "instrument": INSTRUMENT_FEEDSTOCK_SWAP,
        "notional_units": 1000.000,
        "strike_price_usd": 900.00,
        "maturity_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def unwind_payload(settlement_price_usd, **overrides) -> dict:
    payload = {"settlement_price_usd": settlement_price_usd}
    payload.update(overrides)
    return payload
