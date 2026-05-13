"""Payload factories for the IP Management API.

One factory per mutation endpoint, emitting EXACTLY the PRD-declared input
field set. All factories accept **overrides so tests can pin specific values
and let the rest take stable defaults.

Field names match PRD prose exactly: e.g. PRD §3.4 names the contract body
field `royalty_rate`, not `rate`; PRD §3.7 names `allocation_rules`, not
`allocations` (which is the computed output).
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ─────────────────── Helpers ────────────────────────


def _suffix() -> str:
    return secrets.token_hex(4)


def _unique_bu_code() -> str:
    """BusinessUnit.code regex per PRD §3.1: ^[A-Z0-9_]{2,16}$.
    Generate uppercase hex (uses A-F0-9) keeping length <= 16."""
    return f"BU{_suffix().upper()}"


def _unique_template_code() -> str:
    """ContractTemplate.code regex per PRD §3.1: ^[A-Z0-9_]{2,32}$."""
    return f"TMPL{_suffix().upper()}"


def _unique_filing_number() -> str:
    return f"FN{_suffix().upper()}"


def _unique_party_id(prefix: str = "PARTY") -> str:
    return f"{prefix}_{_suffix().upper()}"


def _unique_idempotency_key() -> str:
    return f"idem_{_suffix()}"


def _unique_qualification_number() -> str:
    return f"BAR{_suffix().upper()}"


def now_iso() -> str:
    """Server-side ISO 8601 UTC w/ 3 fractional digits per PRD §2.2."""
    n = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return n.replace("+00:00", "Z")


def iso_in_days(days: float) -> str:
    """An ISO 8601 timestamp offset from server-wall-clock by `days`."""
    t = datetime.now(timezone.utc) + timedelta(days=days)
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_at(year: int, month: int, day: int) -> str:
    """Fixed ISO timestamp for royalty-period boundary tests."""
    return (
        datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


# ─────────────────── BusinessUnit ────────────────────


def create_business_unit_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 — code matches ^[A-Z0-9_]{2,16}$; annual_budget_cents >= 0."""
    payload: Dict[str, Any] = {
        "code": _unique_bu_code(),
        "name": f"Test BU {_suffix()}",
        "annual_budget_cents": 1_000_000_000,  # $10M
    }
    payload.update(overrides)
    return payload


# ─────────────────── Agent ────────────────────


def create_agent_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 — Agent input fields."""
    payload: Dict[str, Any] = {
        "kind": "INTERNAL",
        "full_name": f"Test Agent {_suffix()}",
        "qualification_number": _unique_qualification_number(),
        "jurisdictions": ["US"],
        "hourly_rate_cents": 50_000,
    }
    payload.update(overrides)
    return payload


# ─────────────────── IPRight & Filings ────────────────


def create_ip_right_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — IPRight inputs. handling_mode=AGENCY requires
    assigned_agent_id; handling_mode=SELF requires assigned_agent_id == null.
    """
    payload: Dict[str, Any] = {
        "ip_type": "PATENT",
        "title": f"Test IP {_suffix()}",
        "handling_mode": "AGENCY",
        "assigned_agent_id": None,  # caller MUST inject the verified agent id
        "business_unit_id": "",  # caller MUST inject
        "primary_jurisdiction": "US",
    }
    payload.update(overrides)
    return payload


def create_filing_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — JurisdictionFiling inputs."""
    payload: Dict[str, Any] = {
        "jurisdiction": "US",
        "filing_number": _unique_filing_number(),
        "filed_at": now_iso(),
    }
    payload.update(overrides)
    return payload


def register_filing_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — `archive_url` body field for /register."""
    payload: Dict[str, Any] = {
        "archive_url": f"https://example.com/cert/{_suffix()}",
    }
    payload.update(overrides)
    return payload


def create_office_action_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2 — `jurisdiction_filing_id`, `assigned_agent_id`,
    `response_due_at`."""
    payload: Dict[str, Any] = {
        "jurisdiction_filing_id": "",  # caller injects
        "assigned_agent_id": "",  # caller injects
        "response_due_at": iso_in_days(30),
    }
    payload.update(overrides)
    return payload


# ─────────────────── AnnualFeeSchedule ──────────────


def create_annual_fee_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3 — required inputs include jurisdiction, fee_year, base_fee_cents,
    due_date, assigned_agent_id; auto_pay_authorized defaults to false."""
    payload: Dict[str, Any] = {
        "jurisdiction": "US",
        "fee_year": 1,
        "base_fee_cents": 100_000,
        "due_date": iso_in_days(10),
        "auto_pay_authorized": False,
        "assigned_agent_id": "",
    }
    payload.update(overrides)
    return payload


# ─────────────────── ContractTemplate / Contract ────────────────


def create_contract_template_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 — code matches ^[A-Z0-9_]{2,32}$."""
    payload: Dict[str, Any] = {
        "code": _unique_template_code(),
        "contract_type": "EXCLUSIVE_LICENSE",
        "body": "Standard exclusive license template body.",
    }
    payload.update(overrides)
    return payload


def _default_parties() -> List[Dict[str, Any]]:
    """A two-party signature-required body matching the structural
    constraints of PRD §3.4."""
    return [
        {
            "party_id": _unique_party_id("LICENSOR"),
            "role": "LICENSOR",
            "signature_required": True,
            "signed_at": None,
        },
        {
            "party_id": _unique_party_id("LICENSEE"),
            "role": "LICENSEE",
            "signature_required": True,
            "signed_at": None,
        },
    ]


def create_contract_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.4 — Contract inputs."""
    payload: Dict[str, Any] = {
        "ip_right_id": "",
        "template_id": "",
        "contract_type": "EXCLUSIVE_LICENSE",
        "parties": _default_parties(),
        "royalty_rate": 0.10,
        "min_guarantee_cents": 800_000,
        "business_unit_id": "",
    }
    payload.update(overrides)
    return payload


def sign_contract_payload(party_id: str) -> Dict[str, Any]:
    """PRD §3.4 — `/sign` body is `party_id`."""
    return {"party_id": party_id}


# ─────────────────── RoyaltySchedule ──────────────


def create_royalty_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5 — RoyaltySchedule inputs.

    period_start inclusive, period_end exclusive (PRD §3.5); period_end >
    period_start.
    """
    payload: Dict[str, Any] = {
        "period_index": 1,
        "period_start": iso_at(2026, 1, 1),
        "period_end": iso_at(2026, 4, 1),
        "forecast_revenue_cents": 10_000_000,
    }
    payload.update(overrides)
    return payload


def settle_royalty_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.5 — `/settle` body."""
    payload: Dict[str, Any] = {"actual_revenue_cents": 9_000_000}
    payload.update(overrides)
    return payload


# ─────────────────── ProtectionCase / Evidence ─────


def create_protection_case_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 — ProtectionCase inputs."""
    payload: Dict[str, Any] = {
        "ip_right_id": "",
        "assigned_agent_id": "",
        "business_unit_id": "",
        "rights_holder_currency": "USD",
    }
    payload.update(overrides)
    return payload


def create_evidence_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 — Evidence inputs. Caller toggles chain_of_custody_hash."""
    payload: Dict[str, Any] = {
        "kind": "DOCUMENT",
        "collected_at": now_iso(),
        "storage_uri": f"https://example.com/evidence/{_suffix()}",
        "chain_of_custody_hash": "0" * 64,
    }
    payload.update(overrides)
    return payload


def route_protection_case_payload(route: str = "DEMAND_LETTER") -> Dict[str, Any]:
    """PRD §3.6 — body for `/route`."""
    return {"route": route}


def resolve_protection_case_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6 — `/resolve` body."""
    payload: Dict[str, Any] = {
        "outcome": "WON",
        "recovered_amount_cents": 10_000_000,
        "legal_fees_cents": 1_500_000,
        "agent_fees_cents": 800_000,
        "punitive_cap_cents": 2_000_000,
    }
    payload.update(overrides)
    return payload


# ─────────────────── Cost ───────────────────────


def create_cost_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.7 — Cost inputs. allocation_rules sum to exactly 10000 bps."""
    payload: Dict[str, Any] = {
        "category": "APPLICATION",
        "ip_right_id": None,
        "protection_case_id": None,
        "agent_id": None,
        "currency": "USD",
        "amount_native_cents": 100_000,
        "fx_rate_to_usd": 1.0,
        "allocation_rules": [{"business_unit_id": "", "percent_bps": 10000}],
        "booked_at": now_iso(),
    }
    payload.update(overrides)
    return payload


def reallocate_cost_payload(allocation_rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """PRD §3.7 — body for PATCH /costs/{id}/allocation."""
    return {"allocation_rules": allocation_rules}


# ─────────────────── Test-driving / system endpoints ─────────


def advance_clock_payload(seconds: int) -> Dict[str, Any]:
    """PRD §3.8 — `/_clock/advance` body is `seconds`."""
    return {"seconds": seconds}


def advance_clock_days(days: float) -> Dict[str, Any]:
    """Helper — same as advance_clock_payload but in days."""
    return {"seconds": int(round(days * 86400))}


def payment_settled_event_payload(annual_fee_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §2.10 — `/_events/payment-settled` body is `annual_fee_id` +
    `idempotency_key`."""
    payload: Dict[str, Any] = {
        "annual_fee_id": annual_fee_id,
        "idempotency_key": _unique_idempotency_key(),
    }
    payload.update(overrides)
    return payload


def esign_completed_event_payload(
    contract_id: str, party_id: str, **overrides: Any
) -> Dict[str, Any]:
    """PRD §2.10 — `/_events/esign-completed` body."""
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "party_id": party_id,
        "idempotency_key": _unique_idempotency_key(),
    }
    payload.update(overrides)
    return payload


# ─────────────────── Convenience: parties matched to roles ───────


def parties_with_party_ids(
    licensor_party_id: Optional[str] = None,
    licensee_party_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Build a deterministic 2-party signature-required block.

    Returns explicit party_ids so tests can target them in /sign calls.
    """
    licensor = licensor_party_id or _unique_party_id("LICENSOR")
    licensee = licensee_party_id or _unique_party_id("LICENSEE")
    return [
        {
            "party_id": licensor,
            "role": "LICENSOR",
            "signature_required": True,
            "signed_at": None,
        },
        {
            "party_id": licensee,
            "role": "LICENSEE",
            "signature_required": True,
            "signed_at": None,
        },
    ]
