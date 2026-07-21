"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def create_analyst_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "full_name": "Ana Lyst",
        "email": f"analyst{n}@firm.test",
        "license_number": f"LIC-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "full_name": "Tax Payer",
        "email": f"client{n}@x.test",
        "entity_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_payload(**overrides) -> dict:
    n = next(_seq)
    defaults = {
        "name": f"County {n}",
        "state_code": "CA",
        "filing_window_days": 60,
        "equalization_ratio": 0.90,
    }
    defaults.update(overrides)
    return defaults


def create_fee_agreement_payload(client_id: str, **overrides) -> dict:
    defaults = {"client_id": client_id}
    defaults.update(overrides)
    return defaults


def create_parcel_payload(client_id: str, jurisdiction_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "apn": _uniq("APN"),
        "address": "1 Test St",
        "property_class": "RESIDENTIAL",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(parcel_id: str, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "tax_year": 2026,
        "original_assessed_value_cents": 30000000,
        "millage_rate": 25.0,
        "notice_date": "2026-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_exemption_claim_payload(parcel_id: str, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "tax_year": 2026,
        "exemption_type": "HOMESTEAD",
        "exemption_value_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(assessment_id: str, analyst_id: str, fee_agreement_id: str,
                          valuation_method: str = "SALES_COMPARISON", **overrides) -> dict:
    defaults = {
        "assessment_id": assessment_id,
        "analyst_id": analyst_id,
        "fee_agreement_id": fee_agreement_id,
        "valuation_method": valuation_method,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "comp_address": _uniq("comp"),
        "sale_price_cents": 27000000,
        "sale_date": "2025-06-01T00:00:00Z",
        "comp_assessed_value_cents": 27000000,
        "adjustment_pct": 0.00,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(representative_id: str, scheduled_start: str, scheduled_end: str,
                           docket_room: str = "R1", **overrides) -> dict:
    defaults = {
        "representative_id": representative_id,
        "docket_room": docket_room,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_offer_payload(offer_value_cents: int, expected_appeal_version: int,
                                    proposed_by: str = "FIRM",
                                    expires_at: str = "2026-12-31T00:00:00Z", **overrides) -> dict:
    defaults = {
        "proposed_by": proposed_by,
        "offer_value_cents": offer_value_cents,
        "expires_at": expires_at,
        "expected_appeal_version": expected_appeal_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, method: str = "CHECK", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "method": method}
    defaults.update(overrides)
    return defaults
