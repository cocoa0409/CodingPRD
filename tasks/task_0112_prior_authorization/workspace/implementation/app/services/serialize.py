"""Resource serializers.

These shape outbound payloads to match the entity definitions in SCAFFOLD §1.1
without leaking internal helper fields (those prefixed with `_`).
"""
from copy import deepcopy


def _strip_internal(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_patient(p: dict) -> dict:
    return _strip_internal(deepcopy(p))


def serialize_provider(p: dict) -> dict:
    return _strip_internal(deepcopy(p))


def serialize_catalog_item(c: dict) -> dict:
    return _strip_internal(deepcopy(c))


def serialize_authorization(a: dict) -> dict:
    out = _strip_internal(deepcopy(a))
    # Ensure computed fields are present (None when not yet set)
    for f in [
        "submitted_at",
        "decision_deadline_at",
        "decided_at",
        "expires_at",
        "evidence_completeness_score",
        "evidence_reuse_discount",
    ]:
        out.setdefault(f, None)
    out.setdefault("service_code", None)
    out.setdefault("service_catalog_item_version", None)
    out.setdefault("prior_request_id", None)
    return out


def serialize_evidence(e: dict) -> dict:
    return _strip_internal(deepcopy(e))


def serialize_p2p(p: dict) -> dict:
    out = _strip_internal(deepcopy(p))
    out.setdefault("notes", None)
    return out


def serialize_decision(d: dict) -> dict:
    out = _strip_internal(deepcopy(d))
    out.setdefault("denial_reason_code", None)
    out.setdefault("supersedes_decision_id", None)
    return out


def serialize_appeal(a: dict) -> dict:
    out = _strip_internal(deepcopy(a))
    out.setdefault("decided_at", None)
    return out
