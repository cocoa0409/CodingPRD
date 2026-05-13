"""Shared helpers: common-field stamping, audit entries, OCC, serialization."""
from __future__ import annotations

import copy
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from clock import clock
from db import new_id, store
from response import iso_format


def stamp_create(obj: dict) -> None:
    now = clock.now()
    obj["id"] = obj.get("id") or new_id()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1


def stamp_immutable_create(obj: dict) -> None:
    obj["id"] = obj.get("id") or new_id()
    obj["created_at"] = clock.now()


def touch(obj: dict) -> None:
    obj["updated_at"] = clock.now()
    obj["version"] = int(obj.get("version", 0)) + 1


def emit_audit(
    subject_type: str,
    subject_id: str,
    event: str,
    *,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    actor_role: str,
    actor_id: Optional[str],
    payload: Optional[dict] = None,
) -> dict:
    entry = {
        "id": new_id(),
        "created_at": clock.now(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event": event,
        "from_state": from_state,
        "to_state": to_state,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload or {},
    }
    store.audit_entries.append(entry)
    store.audit_by_id[entry["id"]] = entry
    return entry


def emit_external_sync(
    project_id: str,
    target_system: str,
    trigger_event: str,
    payload: Optional[dict] = None,
    *,
    actor_role: str = "system",
    actor_id: Optional[str] = None,
) -> dict:
    rec = {
        "id": new_id(),
        "created_at": clock.now(),
        "project_id": project_id,
        "target_system": target_system,
        "trigger_event": trigger_event,
        "payload": payload or {},
    }
    store.external_sync_records.append(rec)
    store.sync_by_id[rec["id"]] = rec
    # Companion audit entry per PRD §3.9
    emit_audit(
        subject_type="Project",
        subject_id=project_id,
        event="EXTERNAL_SYNC",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"target_system": target_system, "trigger_event": trigger_event},
    )
    return rec


def round_half_up_cents(value) -> int:
    """Half-up rounding to integer cents (Decimal-safe)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value) -> float:
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Return a float for JSON-friendliness but preserve 2dp
    return float(q)


def serialize_dt(value):
    if value is None:
        return None
    return iso_format(value)


# --- OCC ---

def check_version(entity: dict, supplied_version) -> None:
    from errors import err
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int) or isinstance(supplied_version, bool):
        raise err("ERR_VALIDATION_FAILED", "version must be an integer.")
    if supplied_version != entity.get("version"):
        raise err("ERR_VERSION_CONFLICT", "Version mismatch.")


# --- Serializers ---

def _common_out(obj: dict) -> dict:
    return {
        "id": obj["id"],
        "created_at": serialize_dt(obj["created_at"]),
        "updated_at": serialize_dt(obj["updated_at"]),
        "version": obj["version"],
    }


def _immutable_common_out(obj: dict) -> dict:
    return {
        "id": obj["id"],
        "created_at": serialize_dt(obj["created_at"]),
    }


def serialize_client(c: dict) -> dict:
    out = _common_out(c)
    out.update({
        "name": c["name"],
        "contact_email": c["contact_email"],
        "tax_rate_bps": c["tax_rate_bps"],
        "payment_cycle_days": c["payment_cycle_days"],
        "status": c["status"],
    })
    return out


def serialize_translator(t: dict) -> dict:
    out = _common_out(t)
    out.update({
        "display_name": t["display_name"],
        "language_pairs": copy.deepcopy(t["language_pairs"]),
        "domains": list(t["domains"]),
        "grade": t["grade"],
        "test_translation_passed": t["test_translation_passed"],
        "availability_status": t["availability_status"],
        "workload_segments_open": t["workload_segments_open"],
        "rolling_quality_score": t["rolling_quality_score"],
        "latest_quality_score": t["latest_quality_score"],
    })
    return out


def serialize_project(p: dict) -> dict:
    out = _common_out(p)
    out.update({
        "client_id": p["client_id"],
        "name": p["name"],
        "source_lang": p["source_lang"],
        "target_lang": p["target_lang"],
        "domain": p["domain"],
        "word_count": p["word_count"],
        "deadline_at": serialize_dt(p["deadline_at"]),
        "urgency_tier": p.get("urgency_tier") or "STANDARD",
        "unit_pricing_mode": p["unit_pricing_mode"],
        "base_unit_price_cents": p["base_unit_price_cents"],
        "package_size_segments": p["package_size_segments"],
        "template_id": p.get("template_id"),
        "state": p["state"],
        "quoted_total_cents": p.get("quoted_total_cents"),
        "final_payout_cents": p.get("final_payout_cents"),
        "tax_amount_cents": p.get("tax_amount_cents"),
        "payable_at": serialize_dt(p.get("payable_at")),
    })
    return out


def serialize_project_template(t: dict) -> dict:
    out = _immutable_common_out(t)
    out.update({
        "name": t["name"],
        "default_domain": t["default_domain"],
        "default_unit_pricing_mode": t["default_unit_pricing_mode"],
        "default_base_unit_price_cents": t["default_base_unit_price_cents"],
        "default_package_size_segments": t["default_package_size_segments"],
    })
    return out


def serialize_document(d: dict) -> dict:
    out = _common_out(d)
    out.update({
        "project_id": d["project_id"],
        "filename": d["filename"],
        "file_format": d["file_format"],
        "split_mode": d["split_mode"],
        "word_count": d["word_count"],
        "state": d["state"],
    })
    return out


def serialize_segment(s: dict) -> dict:
    out = _common_out(s)
    out.update({
        "document_id": s["document_id"],
        "project_id": s["project_id"],
        "ordinal": s["ordinal"],
        "source_text": s["source_text"],
        "word_count": s["word_count"],
        "repetition_class": s["repetition_class"],
        "tm_leverage_pct": s["tm_leverage_pct"],
        "translated_text": s.get("translated_text"),
        "reviewed_text": s.get("reviewed_text"),
        "state": s["state"],
        "assignment_id": s.get("assignment_id"),
    })
    return out


def serialize_assignment(a: dict) -> dict:
    out = _common_out(a)
    out.update({
        "project_id": a["project_id"],
        "translator_id": a["translator_id"],
        "role": a["role"],
        "segment_ids": list(a["segment_ids"]),
        "dispatched_at": serialize_dt(a["dispatched_at"]),
        "accept_deadline_at": serialize_dt(a["accept_deadline_at"]),
        "stage_deadline_at": serialize_dt(a.get("stage_deadline_at")),
        "accepted_at": serialize_dt(a.get("accepted_at")),
        "state": a["state"],
    })
    return out


def serialize_terminology(t: dict) -> dict:
    out = _common_out(t)
    out.update({
        "scope_type": t["scope_type"],
        "scope_id": t["scope_id"],
        "source_lang": t["source_lang"],
        "target_lang": t["target_lang"],
        "source_term": t["source_term"],
        "target_term": t["target_term"],
        "state": t["state"],
    })
    return out


def serialize_quality_score(q: dict) -> dict:
    out = _common_out(q)
    out.update({
        "segment_id": q["segment_id"],
        "translator_id": q.get("translator_id"),
        "errors": copy.deepcopy(q.get("errors", [])),
        "error_density": q.get("error_density", 0.00),
        "score": q.get("score", 100.00),
        "state": q["state"],
    })
    return out


def serialize_audit(e: dict) -> dict:
    out = _immutable_common_out(e)
    out.update({
        "subject_type": e["subject_type"],
        "subject_id": e["subject_id"],
        "event": e["event"],
        "from_state": e.get("from_state"),
        "to_state": e.get("to_state"),
        "actor_role": e["actor_role"],
        "actor_id": e.get("actor_id"),
        "payload": copy.deepcopy(e.get("payload", {})),
    })
    return out


def serialize_sync(s: dict) -> dict:
    out = _immutable_common_out(s)
    out.update({
        "project_id": s["project_id"],
        "target_system": s["target_system"],
        "trigger_event": s["trigger_event"],
        "payload": copy.deepcopy(s.get("payload", {})),
    })
    return out


# --- Pagination helpers ---

def paginate(items: list, limit: int, offset: int):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def parse_pagination(args) -> tuple[int, int]:
    from errors import err
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", "limit/offset must be integers.")
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION_FAILED", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_VALIDATION_FAILED", "offset must be non-negative.")
    return limit, offset


def sort_by_created_at(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda x: (x["created_at"], x["id"]))


# --- Datetime helpers ---

def parse_iso_datetime(value) -> "datetime":
    """Parse ISO 8601 datetime, accept Z suffix."""
    from datetime import datetime, timezone
    from errors import err
    if not isinstance(value, str):
        raise err("ERR_VALIDATION_FAILED", "datetime must be an ISO string.")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_VALIDATION_FAILED", f"invalid datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
