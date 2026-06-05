"""Payload factories — one per writeable entity, input fields only.

Each factory accepts **overrides so tests can pin specific fields when their
assertions depend on a particular value.
"""
import uuid
from typing import Optional


def _suffix() -> str:
    """Fresh suffix for unique fields (email, package code)."""
    return uuid.uuid4().hex[:8]


def _code(prefix: str = "PKG") -> str:
    """ContractPackage.code — uppercase A-Z 3..16 chars; unique."""
    # Strip non-letters and uppercase; pad if needed.
    base = "".join(c for c in uuid.uuid4().hex if c.isalpha()).upper()
    candidate = (prefix + base)[:16]
    if len(candidate) < 3:
        candidate = (candidate + "AAA")[:3]
    return candidate


def _email(local: str = "user") -> str:
    return f"{local}-{_suffix()}@example.com"


# ─── ContractPackage ────────────────────────────────────────────


def create_contract_package_payload(**overrides) -> dict:
    """Payload for POST /contract-packages.

    Required fields per PRD §3.1: code, name, annual_premium_cents,
    service_fee_cents, copay_cap_cents, copay_share_pct,
    return_visit_window_days, max_covered_items.
    """
    defaults = {
        "code": _code("PLUS"),
        "name": "Test Plus Package",
        "annual_premium_cents": 50_000,
        "service_fee_cents": 7_500,
        "copay_cap_cents": 25_000,
        "copay_share_pct": 0.20,
        "return_visit_window_days": 30,
        "max_covered_items": 5,
    }
    defaults.update(overrides)
    return defaults


# ─── Customer ───────────────────────────────────────────────────


def create_customer_payload(**overrides) -> dict:
    """Payload for POST /customers. Required: email, full_name, home_address (PRD §3.1)."""
    defaults = {
        "email": _email("customer"),
        "full_name": "Test Customer",
        "home_address": "1 Main St",
    }
    defaults.update(overrides)
    return defaults


# ─── Contract ───────────────────────────────────────────────────


def create_contract_payload(customer_id: str, package_id: str, **overrides) -> dict:
    """Payload for POST /contracts. Required: customer_id, package_id (PRD §3.2)."""
    payload = {"customer_id": customer_id, "package_id": package_id}
    payload.update(overrides)
    return payload


def renew_contract_payload(expected_contract_version: int,
                           new_package_id: Optional[str] = None, **overrides) -> dict:
    """Payload for POST /contracts/{id}/renew. Required: expected_contract_version.
    Optional: new_package_id (PRD §3.8).
    """
    payload = {"expected_contract_version": expected_contract_version}
    if new_package_id is not None:
        payload["new_package_id"] = new_package_id
    payload.update(overrides)
    return payload


# ─── CoveredItem ────────────────────────────────────────────────


def create_covered_item_payload(contract_id: str,
                                category: str = "HVAC",
                                brand: str = "Carrier",
                                model: str = "XR15",
                                install_year: int = 2022,
                                **overrides) -> dict:
    """Payload for POST /covered-items. Required: contract_id, category, brand,
    model, install_year. Optional: pre_existing_flag (defaults to false; PRD §3.3).
    """
    payload = {
        "contract_id": contract_id,
        "category": category,
        "brand": brand,
        "model": model,
        "install_year": install_year,
    }
    payload.update(overrides)
    return payload


# ─── ClaimTicket ────────────────────────────────────────────────


def create_claim_payload(contract_id: str, covered_item_id: str,
                         issue_summary: str = "Stopped working", **overrides) -> dict:
    """Payload for POST /claims. Required: contract_id, covered_item_id,
    issue_summary (PRD §3.4)."""
    payload = {
        "contract_id": contract_id,
        "covered_item_id": covered_item_id,
        "issue_summary": issue_summary,
    }
    payload.update(overrides)
    return payload


def assess_claim_payload(estimated_repair_cost_cents: int, **overrides) -> dict:
    """Payload for POST /claims/{id}/assess. Required: estimated_repair_cost_cents
    > 0 (PRD §3.4)."""
    payload = {"estimated_repair_cost_cents": estimated_repair_cost_cents}
    payload.update(overrides)
    return payload


def reject_claim_payload(rejection_reason: str, **overrides) -> dict:
    """Payload for POST /claims/{id}/reject. rejection_reason must be one of
    PRE_EXISTING_EXCLUDED, OUT_OF_COVERAGE, NOT_COVERED_CATEGORY (PRD §3.4)."""
    payload = {"rejection_reason": rejection_reason}
    payload.update(overrides)
    return payload


def dispatch_claim_payload(technician_id: str, scheduled_utc: str, **overrides) -> dict:
    """Payload for POST /claims/{id}/dispatch. Required: technician_id (non-empty),
    scheduled_utc (>= clock_now) (PRD §3.5)."""
    payload = {"technician_id": technician_id, "scheduled_utc": scheduled_utc}
    payload.update(overrides)
    return payload


def resolve_claim_payload(actual_repair_cost_cents: int, **overrides) -> dict:
    """Payload for POST /claims/{id}/resolve. actual_repair_cost_cents > 0 (PRD §3.6)."""
    payload = {"actual_repair_cost_cents": actual_repair_cost_cents}
    payload.update(overrides)
    return payload


# ─── Clock ──────────────────────────────────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    """Payload for POST /_clock/set. (PRD §3.9)"""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
