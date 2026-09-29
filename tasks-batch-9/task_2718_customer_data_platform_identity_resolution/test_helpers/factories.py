"""Payload factories.

Every numeric field is emitted as a JSON number and never as a string — money in
cents, quotas, counts, thresholds and rates all go out as int or float. Every
timestamp is an ISO 8601 UTC instant. Overrides are applied last, so a test can
change any single field or remove it altogether with the OMIT sentinel.
"""

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


class _Omit:
    """Sentinel that removes a field from a factory payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


OMIT = _Omit()


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ------------------------------------------------------------- logical clock
def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ------------------------------------------------------------- source systems
def source_system_payload(**overrides: Any) -> Dict[str, Any]:
    """The three required feed inputs; every optional one left to its default."""
    payload = {
        "code": f"FEED_{_next():04d}",
        "display_name": f"Retail Feed {_next()}",
        "channel_type": "TRANSACTIONS",
    }
    return _apply(payload, overrides)


def full_source_system_payload(**overrides: Any) -> Dict[str, Any]:
    """Every optional feed input supplied explicitly."""
    payload = {
        "code": f"FEED_{_next():04d}",
        "display_name": f"Retail Feed {_next()}",
        "channel_type": "LOYALTY",
        "trust_tier": 4,
        "dq_scoring_mode": "PENALIZED_WEIGHTED",
        "pii_completeness_floor": 0.80,
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------- raw records
def consent_signal(
    channel: str = "EMAIL",
    purpose: str = "MARKETING",
    consent_state: str = "OPT_IN",
) -> Dict[str, Any]:
    return {"channel": channel, "purpose": purpose, "consent_state": consent_state}


EMAIL_OPT_IN = [consent_signal("EMAIL", "MARKETING", "OPT_IN")]
SMS_OPT_IN = [consent_signal("SMS", "MARKETING", "OPT_IN")]


def raw_record(external_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A record on which all five data-quality components pass.

    email_raw parses, phone_raw reduces to eleven digits beginning with one,
    loyalty_number is LY plus eight digits, postal_code is five digits and both
    name halves are non-blank, so the weighted score is the full 1.00.
    """
    seq = _next()
    ext = external_id if external_id is not None else f"EXT{seq:05d}"
    payload = {
        "external_id": ext,
        "email_raw": f"person{seq:05d}@example.com",
        "phone_raw": f"+1 (555) {seq % 900 + 100:03d}-{seq % 9000 + 1000:04d}",
        "loyalty_number": f"LY{seq % 100000000:08d}",
        "first_name": "Ada",
        "last_name": "Alpha",
        "postal_code": "10001",
        "address_line": None,
        "event_timestamp": "2026-07-15T10:00:00Z",
        "consent_signals": [],
    }
    return _apply(payload, overrides)


def ingest_batch_payload(
    source_system_id: str, records: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "source_system_id": source_system_id,
        "batch_label": f"Batch {_next()}",
        "records": records if records is not None else [raw_record()],
    }
    return _apply(payload, overrides)


# ---------------------------------------------------------------- match rules
def probabilistic_rule_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "code": f"PROB_{_next():04d}",
        "rule_kind": "PROBABILISTIC",
        "deterministic_key": None,
        "missing_identifier_policy": "STRICT_ZERO",
        "auto_merge_threshold": 0.92,
        "review_floor": 0.65,
        "min_precision": 0.60,
    }
    return _apply(payload, overrides)


def deterministic_rule_payload(
    deterministic_key: str = "EMAIL_NORM", **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "code": f"DET_{_next():04d}",
        "rule_kind": "DETERMINISTIC",
        "deterministic_key": deterministic_key,
    }
    return _apply(payload, overrides)


# -------------------------------------------------------------- identity links
def evidence(
    email_similarity: Optional[float] = 1.0,
    phone_similarity: Optional[float] = 1.0,
    name_similarity: Optional[float] = 1.0,
    address_similarity: Optional[float] = 0.0,
) -> Dict[str, Any]:
    """All four evidence keys, each 1.0, 0.5, 0.0 or null."""
    return {
        "email_similarity": email_similarity,
        "phone_similarity": phone_similarity,
        "name_similarity": name_similarity,
        "address_similarity": address_similarity,
    }


def identity_link_payload(
    left_profile_id: str,
    right_profile_id: str,
    match_rule_id: str,
    evidence_values: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "left_profile_id": left_profile_id,
        "right_profile_id": right_profile_id,
        "match_rule_id": match_rule_id,
        "evidence": evidence_values if evidence_values is not None else evidence(),
    }
    return _apply(payload, overrides)


def link_decision_payload(decision: str = "CONFIRM", **overrides: Any) -> Dict[str, Any]:
    return _apply({"decision": decision}, overrides)


# ------------------------------------------------------------ consent records
def consent_record_payload(
    profile_id: str,
    source_system_id: str,
    expected_profile_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "profile_id": profile_id,
        "source_system_id": source_system_id,
        "channel": "EMAIL",
        "purpose": "MARKETING",
        "consent_state": "OPT_IN",
        "captured_at": "2026-07-20T10:00:00Z",
        "expected_profile_version": expected_profile_version,
    }
    return _apply(payload, overrides)


# -------------------------------------------------------- suppression entries
def suppression_entry_payload(profile_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "profile_id": profile_id,
        "entry_type": "DO_NOT_SELL",
        "reason_code": "CCPA_OPT_OUT",
        "effective_at": "2026-08-01T00:00:00Z",
    }
    return _apply(payload, overrides)


# -------------------------------------------------------------------- segments
def criterion(attribute: str, operator: str, value: Any) -> Dict[str, Any]:
    return {"attribute": attribute, "operator": operator, "value": value}


POSTAL_10001 = [criterion("postal_code", "EQ", "10001")]


def segment_payload(
    criteria: Optional[List[Dict[str, Any]]] = None, **overrides: Any
) -> Dict[str, Any]:
    payload = {
        "name": f"Audience {_next()}",
        "criteria": criteria if criteria is not None else [criterion("postal_code", "EQ", "10001")],
    }
    return _apply(payload, overrides)


def governance_decision_payload(
    decision: str = "APPROVE", sensitive_use_approved: Optional[bool] = False, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if sensitive_use_approved is not None:
        payload["sensitive_use_approved"] = sensitive_use_approved
    return _apply(payload, overrides)


# ---------------------------------------------------------------- destinations
def destination_payload(**overrides: Any) -> Dict[str, Any]:
    """The five required destination inputs; the eight optional ones defaulted."""
    payload = {
        "code": f"DEST_{_next():04d}",
        "platform_kind": "ADVERTISING",
        "channel": "EMAIL",
        "hashing_algorithm": "SHA256_EMAIL_LOWER",
        "daily_hash_quota": 1000,
    }
    return _apply(payload, overrides)


def permissive_destination_payload(**overrides: Any) -> Dict[str, Any]:
    """A destination whose safety envelope does not obstruct a one-profile audience."""
    payload = {
        "code": f"DEST_{_next():04d}",
        "platform_kind": "ADVERTISING",
        "channel": "EMAIL",
        "hashing_algorithm": "SHA256_EMAIL_LOWER",
        "daily_hash_quota": 1000,
        "min_audience_size": 1,
        "min_match_rate": 0.10,
        "cooldown_minutes": 0,
    }
    return _apply(payload, overrides)


# ----------------------------------------------------------------- activations
def activation_payload(
    segment_id: str,
    destination_id: str,
    expected_segment_version: int,
    window_start_at: str = "2026-08-02T00:00:00Z",
    window_end_at: str = "2026-08-02T02:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "segment_id": segment_id,
        "destination_id": destination_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "expected_segment_version": expected_segment_version,
    }
    return _apply(payload, overrides)


def conversion(profile_id: str, converted_at: str, revenue_cents: int) -> Dict[str, Any]:
    """revenue_cents is a JSON integer of whole cents, never a decimal string."""
    return {
        "profile_id": profile_id,
        "converted_at": converted_at,
        "revenue_cents": revenue_cents,
    }


def match_report_payload(
    vendor_matched_count: int,
    unusable_hash_count: int = 0,
    attributed_conversions: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vendor_matched_count": vendor_matched_count,
        "unusable_hash_count": unusable_hash_count,
    }
    if attributed_conversions is not None:
        payload["attributed_conversions"] = attributed_conversions
    return _apply(payload, overrides)


# ------------------------------------------------------------ erasure requests
def deletion_request_payload(profile_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = {
        "profile_id": profile_id,
        "request_origin": "DATA_SUBJECT",
        "requester_reference": f"DSR-{_next():05d}",
    }
    return _apply(payload, overrides)


def propagate_payload(expected_deletion_request_version: int, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"expected_deletion_request_version": expected_deletion_request_version}, overrides
    )


def vendor_ack_payload(outcome: str = "ACKNOWLEDGED", **overrides: Any) -> Dict[str, Any]:
    return _apply({"outcome": outcome}, overrides)


# ---------------------------------------------------------------- households
def household_assignment_payload(household_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"household_id": household_id}, overrides)
