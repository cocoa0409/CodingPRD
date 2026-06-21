"""Payload factories — one per writeable entity, input fields only.

All factories accept **overrides so tests can pin the precise input values
that drive their assertions. Numeric defaults are deliberately wide so
fixtures do not trip credit, FK, or window-overlap guards by accident.
"""
import uuid


# ─── Counters / unique-token helpers ──────────────────────────────


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _digits(n: int) -> str:
    """Pull n digit characters from a uuid; pad with '0' if it ran short."""
    out = "".join(c for c in uuid.uuid4().hex if c.isdigit())
    return (out + "0" * n)[:n]


def _mc_number() -> str:
    """6- or 7-digit numeric string (PRD §3.1)."""
    return _digits(7)


def _usdot_number() -> str:
    """5- to 8-digit numeric string (PRD §3.1)."""
    return _digits(8)


def _email(local: str = "ap") -> str:
    return f"{local}-{_suffix()}@example.test"


# ─── Shipper (POST /freight/shippers) ─────────────────────────────


def create_shipper_payload(**overrides) -> dict:
    """PRD §3.1: required fields are legal_name, billing_email, credit_limit_cents."""
    defaults = {
        "legal_name": f"Test Shipper {_suffix()}",
        "billing_email": _email("ap"),
        "credit_limit_cents": 100_000_000,  # $1,000,000 default headroom
    }
    defaults.update(overrides)
    return defaults


# ─── Carrier (POST /freight/carriers) ─────────────────────────────


def create_carrier_payload(**overrides) -> dict:
    """PRD §3.1: legal_name, mc_number, usdot_number, insurance_expiry_utc,
    safety_score required; smartway_tier optional, defaulting to NONE."""
    defaults = {
        "legal_name": f"Test Carrier {_suffix()}",
        "mc_number": _mc_number(),
        "usdot_number": _usdot_number(),
        "smartway_tier": "NONE",
        "insurance_expiry_utc": "2027-12-31T00:00:00Z",
        "safety_score": 30.0,
    }
    defaults.update(overrides)
    return defaults


def reject_carrier_payload(reason_code: str = "BAD_MC", **overrides) -> dict:
    defaults = {"reason_code": reason_code}
    defaults.update(overrides)
    return defaults


# ─── Contract rate ────────────────────────────────────────────────


def create_contract_rate_payload(shipper_id: str, **overrides) -> dict:
    """PRD §3.2 required fields."""
    defaults = {
        "shipper_id": shipper_id,
        "lane_origin": "10001",
        "lane_destination": "30303",
        "rate_per_mile_cents": 250,
        "fuel_surcharge_per_mile_cents": 60,
        "detention_free_minutes": 120,
        "detention_rate_per_hour_cents": 7500,
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "effective_until_utc": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def activate_contract_rate_payload(expected_version: int) -> dict:
    """PRD §3.2: activate requires expected_contract_rate_version (OCC)."""
    return {"expected_contract_rate_version": expected_version}


# ─── Quote request ────────────────────────────────────────────────


def create_quote_request_payload(shipper_id: str, **overrides) -> dict:
    """PRD §3.3 required input fields."""
    defaults = {
        "shipper_id": shipper_id,
        "lane_origin": "10001",
        "lane_destination": "30303",
        "distance_miles": 400,
        "pickup_window_start_utc": "2026-06-10T08:00:00Z",
        "pickup_window_end_utc": "2026-06-10T18:00:00Z",
        "requested_equipment": "DRY_VAN",
    }
    defaults.update(overrides)
    return defaults


def award_quote_payload(carrier_id: str, expected_version: int) -> dict:
    """PRD §3.4: carrier_id + expected_quote_request_version (OCC)."""
    return {
        "carrier_id": carrier_id,
        "expected_quote_request_version": expected_version,
    }


# ─── Load action payloads ─────────────────────────────────────────


def pickup_payload(actual_pickup_at_utc: str) -> dict:
    return {"actual_pickup_at_utc": actual_pickup_at_utc}


def deliver_payload(actual_delivery_at_utc: str) -> dict:
    return {"actual_delivery_at_utc": actual_delivery_at_utc}


def add_accessorial_payload(code: str, amount_cents: int, note: str = None) -> dict:
    body = {"code": code, "amount_cents": amount_cents}
    if note is not None:
        body["note"] = note
    return body


# ─── Invoice payments ─────────────────────────────────────────────


def payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


# ─── Factoring requests ───────────────────────────────────────────


def create_factoring_request_payload(invoice_id: str, carrier_id: str,
                                     factoring_fee_pct: float = 2.0) -> dict:
    return {
        "invoice_id": invoice_id,
        "carrier_id": carrier_id,
        "factoring_fee_pct": factoring_fee_pct,
    }


# ─── Dispute claims ───────────────────────────────────────────────


def create_dispute_claim_payload(invoice_id: str, claim_type: str = "OVERCHARGE",
                                 claimed_amount_cents: int = 5000) -> dict:
    return {
        "invoice_id": invoice_id,
        "claim_type": claim_type,
        "claimed_amount_cents": claimed_amount_cents,
    }


def resolve_dispute_payload(resolution_kind: str,
                            resolution_amount_cents: int) -> dict:
    return {
        "resolution_kind": resolution_kind,
        "resolution_amount_cents": resolution_amount_cents,
    }


# ─── SmartWay audits ──────────────────────────────────────────────


def create_smartway_audit_payload(shipper_id: str, quarter_label: str) -> dict:
    return {"shipper_id": shipper_id, "quarter_label": quarter_label}


# ─── Test-driving clock ───────────────────────────────────────────


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
