"""Payload factories — one per write endpoint, input fields only.

Field names mirror PRD prose exactly. Defaults give a working payload;
**overrides let tests target specific fields and edge cases.

Per PRD §2.1, factories never bake in role headers; the caller passes
headers separately to the api client.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Random / unique helpers
# ---------------------------------------------------------------------------
_ALPHA = string.ascii_uppercase
_NUM = string.digits


def unique_suffix(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHA + _NUM) for _ in range(length))


def unique_isrc() -> str:
    """ISRC: exactly 12 alphanumeric chars (PRD §3.1)."""
    return "".join(secrets.choice(_ALPHA + _NUM) for _ in range(12))


def unique_iswc() -> str:
    """ISWC: 'T' followed by ten digits, total 11 chars (PRD §3.1)."""
    return "T" + "".join(secrets.choice(_NUM) for _ in range(10))


def unique_cycle_tag() -> str:
    return f"CYC-{unique_suffix(8)}"


def unique_legal_name(prefix: str = "Holder") -> str:
    return f"{prefix} {unique_suffix(6)}"


def unique_version_tag() -> str:
    return f"v{unique_suffix(8)}"


def unique_source_identifier() -> str:
    return f"src-{unique_suffix(6)}".lower()


def utc_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with millisecond precision (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Playback HMAC helper.
#
# PRD §2.8 / §3.6 require HMAC-SHA256(canonical_payload, source_secret).
# The PRD does not name the secret-registration endpoint, so this helper
# computes the digest under a NAMED secret that callers pass in. The
# fixture layer treats any 64-hex string the implementation rejects as a
# legitimately invalid signature, and treats a known-good string as valid.
#
# For deterministic positive-path tests, fixtures call this with a stable
# secret string AND pass the same string to the implementation through an
# admin-registration helper if one is exposed. For tests that DO NOT need
# a known-valid signature (e.g., ingest with a fixed 64-hex pattern that
# happens to verify under a default secret), we just use the canonical
# default.
# ---------------------------------------------------------------------------
DEFAULT_PLAYBACK_SECRET = "test-secret"


def compute_hmac_signature(payload: Dict[str, Any],
                           secret: str = DEFAULT_PLAYBACK_SECRET) -> str:
    """HMAC-SHA256(canonical_payload, source_secret) hex digest.

    Canonical payload here is JSON-encoded with sort_keys=True and
    separators that strip whitespace, which is the natural canonical form
    for HMAC over a JSON body.
    """
    canonical = json.dumps(payload, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def invalid_hmac_signature() -> str:
    """A 64-hex-character string statistically unlikely to match any
    implementation's HMAC output."""
    return "0" * 64


# ===========================================================================
# Rights-holder payload (PRD §3.5)
# ===========================================================================
def create_rights_holder_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": unique_legal_name(),
        "holder_kind": "ORGANIZATION",
        "tax_jurisdiction": "US",
        "payout_currency": "USD",
        "bank_account_token": "tok_" + unique_suffix(16),
    }
    defaults.update(overrides)
    return defaults


def create_individual_rights_holder_payload(
    date_of_birth: str = "1990-01-01",
    **overrides: Any,
) -> Dict[str, Any]:
    """An adult individual (PRD §3.5: is_minor evaluated at creation)."""
    return create_rights_holder_payload(
        holder_kind="INDIVIDUAL",
        date_of_birth=date_of_birth,
        **overrides,
    )


def create_minor_rights_holder_payload(
    guardian_holder_id: str,
    date_of_birth: str = "2018-01-01",
    **overrides: Any,
) -> Dict[str, Any]:
    """A minor individual with mandatory guardian_holder_id (PRD §3.5)."""
    return create_rights_holder_payload(
        holder_kind="INDIVIDUAL",
        date_of_birth=date_of_birth,
        guardian_holder_id=guardian_holder_id,
        **overrides,
    )


# ===========================================================================
# Agency-binding payload (PRD §3.4)
# ===========================================================================
def create_agency_binding_payload(
    rights_holder_id: str,
    effective_from: str,
    effective_until: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "rights_holder_id": rights_holder_id,
        "agency_kind": "PUBLISHER",
        "agency_name": f"Agency {unique_suffix(6)}",
        "territory": "WW",
        "commission_percent": 10.00,
        "effective_from": effective_from,
    }
    if effective_until is not None:
        defaults["effective_until"] = effective_until
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Work payload (PRD §3.1)
# ===========================================================================
def create_recording_work_payload(**overrides: Any) -> Dict[str, Any]:
    """RECORDING work: needs ISRC (PRD §3.1)."""
    defaults: Dict[str, Any] = {
        "title": f"Test Work {unique_suffix(6)}",
        "duration_seconds": 300,
        "isrc": unique_isrc(),
        "rights_type": "RECORDING",
        "co_creators": [
            {"full_name": "Alice", "role": "PERFORMER",
             "contribution_percent": 100.00},
        ],
        "original_proof_url": "https://example.com/proof.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_composition_work_payload(**overrides: Any) -> Dict[str, Any]:
    """COMPOSITION work: needs ISWC (PRD §3.1)."""
    defaults: Dict[str, Any] = {
        "title": f"Test Comp {unique_suffix(6)}",
        "duration_seconds": 240,
        "iswc": unique_iswc(),
        "rights_type": "COMPOSITION",
        "co_creators": [
            {"full_name": "Bob", "role": "COMPOSER",
             "contribution_percent": 100.00},
        ],
        "original_proof_url": "https://example.com/comp-proof.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_performance_work_payload(**overrides: Any) -> Dict[str, Any]:
    return create_recording_work_payload(rights_type="PERFORMANCE", **overrides)


def create_lyrics_work_payload(**overrides: Any) -> Dict[str, Any]:
    return create_composition_work_payload(rights_type="LYRICS", **overrides)


# ===========================================================================
# Rights-share payload (PRD §3.3)
# ===========================================================================
def create_rights_share_payload(rights_holder_id: str,
                                share_percent: float = 100.00,
                                **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "rights_holder_id": rights_holder_id,
        "share_percent": share_percent,
    }
    defaults.update(overrides)
    return defaults


def patch_share_payload(**overrides: Any) -> Dict[str, Any]:
    return dict(overrides)


# ===========================================================================
# Playback batch payload (PRD §3.6)
# ===========================================================================
def make_playback_event(
    work_id: Optional[str] = None,
    play_duration_seconds: int = 300,
    played_at: Optional[str] = None,
    region: str = "US",
    **overrides: Any,
) -> Dict[str, Any]:
    if played_at is None:
        played_at = utc_iso(datetime.now(timezone.utc) - timedelta(days=1))
    event: Dict[str, Any] = {
        "play_duration_seconds": play_duration_seconds,
        "played_at": played_at,
        "region": region,
    }
    if work_id is not None:
        event["work_id"] = work_id
    event.update(overrides)
    return event


def create_playback_batch_payload(
    events: List[Dict[str, Any]],
    source_identifier: str,
    reporting_period_start: str,
    reporting_period_end: str,
    *,
    source_secret: Optional[str] = None,
    channel: str = "STREAMING",
    source_signature: Optional[str] = None,
    total_events_submitted: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a playback-batch payload (PRD §3.6) with auto-computed signature.

    The HMAC is computed over the canonical body that excludes the
    signature field itself. Tests that want an INVALID signature pass an
    explicit source_signature (e.g., invalid_hmac_signature()).

    PRD §2.8 says the secret is "pre-registered against the reporting
    source_identifier". PRD exposes no registration endpoint, so the
    natural deterministic mapping is secret == source_identifier (the
    source_identifier IS the registered key). Tests pass source_secret
    explicitly only when they want to forge a signature with the wrong
    secret.
    """
    if source_secret is None:
        source_secret = source_identifier
    body: Dict[str, Any] = {
        "channel": channel,
        "source_identifier": source_identifier,
        "reporting_period_start": reporting_period_start,
        "reporting_period_end": reporting_period_end,
        "total_events_submitted": (
            total_events_submitted
            if total_events_submitted is not None else len(events)
        ),
        "events": events,
    }
    body.update(overrides)
    if source_signature is None:
        source_signature = compute_hmac_signature(body, source_secret)
    body["source_signature"] = source_signature
    return body


# ===========================================================================
# Distribution-rule payload (PRD §3.7)
# ===========================================================================
def create_distribution_rule_payload(
    *,
    distribution_mode: str = "PER_PLAY",
    channel: str = "STREAMING",
    effective_from: Optional[str] = None,
    minimum_payout_cents: int = 0,
    micro_accumulation_cap_cents: int = 100_000,
    playback_type_weights: Optional[Dict[str, float]] = None,
    per_play_weight: Optional[float] = None,
    per_duration_weight: Optional[float] = None,
    version_tag: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if effective_from is None:
        effective_from = utc_iso(datetime.now(timezone.utc) - timedelta(days=365))
    if playback_type_weights is None:
        playback_type_weights = {
            "FULL_PLAY": 1.00,
            "SKIP": 1.00,
            "BACKGROUND": 1.00,
            "FOREGROUND": 1.00,
        }
    payload: Dict[str, Any] = {
        "version_tag": version_tag or unique_version_tag(),
        "channel": channel,
        "distribution_mode": distribution_mode,
        "playback_type_weights": playback_type_weights,
        "minimum_payout_cents": minimum_payout_cents,
        "micro_accumulation_cap_cents": micro_accumulation_cap_cents,
        "effective_from": effective_from,
    }
    # Mode-dependent weights (PRD §3.7).
    if distribution_mode == "PER_PLAY":
        payload["per_play_weight"] = (
            per_play_weight if per_play_weight is not None else 1.00
        )
    elif distribution_mode == "PER_DURATION":
        payload["per_duration_weight"] = (
            per_duration_weight if per_duration_weight is not None else 1.00
        )
    elif distribution_mode == "HYBRID":
        # HYBRID requires sum == 1.00 (PRD §3.7).
        payload["per_play_weight"] = (
            per_play_weight if per_play_weight is not None else 0.40
        )
        payload["per_duration_weight"] = (
            per_duration_weight if per_duration_weight is not None else 0.60
        )
    payload.update(overrides)
    return payload


# ===========================================================================
# Royalty-pool payload (PRD §3.8)
# ===========================================================================
def create_royalty_pool_payload(
    *,
    period_start: str,
    period_end: str,
    revenue_source: str = "STREAMING",
    region: str = "WW",
    gross_revenue_cents: int = 20_000_000,
    platform_share_percent: float = 30.00,
    pool_currency: str = "USD",
    mechanical_split_percent: float = 0.00,
    distribution_rule_version_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "revenue_source": revenue_source,
        "region": region,
        "gross_revenue_cents": gross_revenue_cents,
        "platform_share_percent": platform_share_percent,
        "pool_currency": pool_currency,
        "mechanical_split_percent": mechanical_split_percent,
    }
    if distribution_rule_version_id is not None:
        payload["distribution_rule_version_id"] = distribution_rule_version_id
    payload.update(overrides)
    return payload


# ===========================================================================
# Dispute payload (PRD §3.11)
# ===========================================================================
def create_dispute_payload(work_id: str,
                           dispute_kind: str = "OWNERSHIP",
                           claim_summary: Optional[str] = None,
                           **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "work_id": work_id,
        "dispute_kind": dispute_kind,
        "claim_summary": claim_summary or f"Test claim {unique_suffix(6)}",
    }
    payload.update(overrides)
    return payload


def submit_evidence_payload(
    url: str = "https://example.com/evidence.pdf",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"url": url}
    payload.update(overrides)
    return payload


def resolve_dispute_payload(
    outcome: str = "DISMISSED",
    arbitration_decision: str = "Decision text.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "arbitration_decision": arbitration_decision,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Payout-batch payload (PRD §3.12)
# ===========================================================================
def create_payout_batch_payload(
    cycle_tag: Optional[str] = None,
    scheduled_run_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if scheduled_run_at is None:
        scheduled_run_at = utc_iso(datetime.now(timezone.utc) - timedelta(seconds=1))
    payload: Dict[str, Any] = {
        "cycle_tag": cycle_tag or unique_cycle_tag(),
        "scheduled_run_at": scheduled_run_at,
    }
    payload.update(overrides)
    return payload


def abandon_payment_payload(policy: str = "RETURN_TO_MICRO",
                            **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"policy": policy}
    payload.update(overrides)
    return payload


# ===========================================================================
# Test-driving payloads
# ===========================================================================
def psp_callback_payload(payment_id: str, outcome: str = "SUCCESS",
                         reason: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"payment_id": payment_id, "outcome": outcome}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def clock_advance_payload(to: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def reject_work_payload(reject_reason: str = "Missing proof of originality.",
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reject_reason": reject_reason}
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULT_PLAYBACK_SECRET",
    "compute_hmac_signature", "invalid_hmac_signature",
    "unique_suffix", "unique_isrc", "unique_iswc",
    "unique_cycle_tag", "unique_legal_name", "unique_version_tag",
    "unique_source_identifier",
    "utc_iso",
    "create_rights_holder_payload",
    "create_individual_rights_holder_payload",
    "create_minor_rights_holder_payload",
    "create_agency_binding_payload",
    "create_recording_work_payload", "create_composition_work_payload",
    "create_performance_work_payload", "create_lyrics_work_payload",
    "create_rights_share_payload", "patch_share_payload",
    "make_playback_event", "create_playback_batch_payload",
    "create_distribution_rule_payload",
    "create_royalty_pool_payload",
    "create_dispute_payload", "submit_evidence_payload",
    "resolve_dispute_payload",
    "create_payout_batch_payload", "abandon_payment_payload",
    "psp_callback_payload", "clock_advance_payload",
    "reject_work_payload",
]
