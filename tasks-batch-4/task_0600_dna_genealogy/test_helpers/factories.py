"""Payload factories — one per write endpoint, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_seq = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{next(_seq)}@dna.test"


def unique_instrument_name(prefix: str = "SEQ") -> str:
    return f"{prefix}-{next(_seq)}"


# ─── Customer ───────────────────────────────────────────────────────────────

def create_customer_payload(**overrides) -> dict:
    payload = {"email": unique_email(), "display_name": "Test Customer"}
    payload.update(overrides)
    return payload


def add_credits_payload(**overrides) -> dict:
    payload = {"amount_cents": 10_000}
    payload.update(overrides)
    return payload


# ─── Subscription ───────────────────────────────────────────────────────────

def create_subscription_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id, "tier": "PLUS"}
    payload.update(overrides)
    return payload


def change_tier_payload(new_tier: str, expected_subscription_version: int, **overrides) -> dict:
    payload = {
        "new_tier": new_tier,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def billing_event_payload(event_type: str, **overrides) -> dict:
    payload = {"event_type": event_type}
    payload.update(overrides)
    return payload


# ─── Kit / sample ───────────────────────────────────────────────────────────

def create_kit_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id, "chip_version": "V5"}
    payload.update(overrides)
    return payload


def activate_kit_payload(barcode: str, **overrides) -> dict:
    payload = {"barcode": barcode}
    payload.update(overrides)
    return payload


def extract_payload(**overrides) -> dict:
    payload = {"dna_yield_ng": TEST_DEFAULTS["GOOD_YIELD_NG"]}
    payload.update(overrides)
    return payload


# ─── Lab instrument / batch ─────────────────────────────────────────────────

def create_instrument_payload(**overrides) -> dict:
    payload = {"name": unique_instrument_name(), "chip_version": "V5", "status": "ONLINE"}
    payload.update(overrides)
    return payload


def create_batch_payload(instrument_id: str, sample_ids=None, **overrides) -> dict:
    payload = {
        "instrument_id": instrument_id,
        "run_start_at": TEST_DEFAULTS["RUN_START_AT"],
        "run_end_at": TEST_DEFAULTS["RUN_END_AT"],
        "sample_ids": list(sample_ids or []),
    }
    payload.update(overrides)
    return payload


def sample_result(sample_id: str, call_rate=None, population_scores=None, genotype_markers=None) -> dict:
    """One entry of the `sample_results` array carried by batch finalize (PRD §3.5)."""
    return {
        "sample_id": sample_id,
        "call_rate": TEST_DEFAULTS["GOOD_CALL_RATE"] if call_rate is None else call_rate,
        "population_scores": (
            [{"population": "EUR", "raw_score": 100}]
            if population_scores is None
            else population_scores
        ),
        "genotype_markers": [1, 2] if genotype_markers is None else genotype_markers,
    }


def finalize_batch_payload(sample_results, **overrides) -> dict:
    payload = {"sample_results": list(sample_results)}
    payload.update(overrides)
    return payload


# ─── Consent ────────────────────────────────────────────────────────────────

def create_consent_payload(customer_id: str, scope: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "scope": scope,
        "effective_from": "2026-05-01T00:00:00Z",
        "effective_until": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Report ─────────────────────────────────────────────────────────────────

def generate_report_payload(expected_customer_version: int, **overrides) -> dict:
    payload = {
        "report_type": "ETHNICITY",
        "variant": "PROVISIONAL",
        "expected_customer_version": expected_customer_version,
    }
    payload.update(overrides)
    return payload


# ─── Family tree ────────────────────────────────────────────────────────────

def create_family_tree_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id, "name": "Test Tree"}
    payload.update(overrides)
    return payload


def create_tree_person_payload(tree_id: str, **overrides) -> dict:
    payload = {"tree_id": tree_id, "given_name": "Root", "surname": "Person"}
    payload.update(overrides)
    return payload


# ─── Privacy ────────────────────────────────────────────────────────────────

def create_data_request_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id, "request_type": "EXPORT"}
    payload.update(overrides)
    return payload


def decide_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ─── Clock ──────────────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
