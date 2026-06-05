from __future__ import annotations

"""Entity serializers: render entity dicts as JSON-friendly payloads."""
import db


def _common(entity: dict, *, include_version: bool = True, include_updated_at: bool = True) -> dict:
    out = {
        "id": entity["id"],
        "created_at": db.format_ts(entity["created_at"]),
    }
    if include_updated_at:
        out["updated_at"] = db.format_ts(entity["updated_at"])
    if include_version:
        out["version"] = entity["version"]
    return out


def chapter(c: dict) -> dict:
    out = _common(c)
    out.update({
        "name": c["name"],
        "greek_type": c["greek_type"],
        "quota_total": c["quota_total"],
        "dues_per_member_cents": c["dues_per_member_cents"],
        "legacy_priority_slots": c["legacy_priority_slots"],
        "risk_status": c["risk_status"],
        "risk_points": c["risk_points"],
        "pledged_count": c["pledged_count"],
        "legacy_pledged_count": c["legacy_pledged_count"],
        "dues_balance_cents": c.get("dues_balance_cents", 0),
    })
    return out


def pnm(p: dict) -> dict:
    out = _common(p)
    out.update({
        "full_name": p["full_name"],
        "gpa": p["gpa"],
        "legacy_chapter_id": p["legacy_chapter_id"],
        "is_legacy": p["is_legacy"],
        "status": p["status"],
        "matched_chapter_id": p["matched_chapter_id"],
    })
    return out


def round_(r: dict) -> dict:
    out = _common(r)
    out.update({
        "cycle_label": r["cycle_label"],
        "phase": r["phase"],
        "bid_day_at": db.format_ts(r["bid_day_at"]),
    })
    return out


def party(p: dict) -> dict:
    out = _common(p)
    out.update({
        "round_id": p["round_id"],
        "chapter_id": p["chapter_id"],
        "scheduled_start_utc": db.format_ts(p["scheduled_start_utc"]),
        "duration_minutes": p["duration_minutes"],
        "capacity": p["capacity"],
        "confirmed_count": p["confirmed_count"],
        "status": p["status"],
    })
    return out


def invitation(i: dict) -> dict:
    out = _common(i)
    out.update({
        "party_id": i["party_id"],
        "pnm_id": i["pnm_id"],
        "rsvp_status": i["rsvp_status"],
    })
    return out


def preference(p: dict) -> dict:
    out = _common(p)
    out.update({
        "round_id": p["round_id"],
        "side": p["side"],
        "pnm_id": p["pnm_id"],
        "chapter_id": p["chapter_id"],
        "rank": p["rank"],
    })
    return out


def bid_match(b: dict) -> dict:
    out = _common(b)
    out.update({
        "round_id": b["round_id"],
        "chapter_id": b["chapter_id"],
        "pnm_id": b["pnm_id"],
        "status": b["status"],
        "priority_kind": b["priority_kind"],
        "dues_charged_cents": b["dues_charged_cents"],
    })
    return out


def dues_ledger_entry(e: dict) -> dict:
    # DuesLedgerEntry is append-only: only id + created_at, no updated_at / version.
    return {
        "id": e["id"],
        "created_at": db.format_ts(e["created_at"]),
        "chapter_id": e["chapter_id"],
        "bid_match_id": e["bid_match_id"],
        "amount_cents": e["amount_cents"],
        "entry_kind": e["entry_kind"],
        "running_balance_cents": e["running_balance_cents"],
    }


def risk_incident(r: dict) -> dict:
    out = _common(r)
    out.update({
        "chapter_id": r["chapter_id"],
        "party_id": r["party_id"],
        "severity_points": r["severity_points"],
        "status": r["status"],
        "reason": r["reason"],
    })
    return out
