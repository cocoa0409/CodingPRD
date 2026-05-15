"""Bulletin endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, request

from ..auth import require_auth
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import BULLETIN_ARCHIVE_DAYS, VALID_CHANNELS
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/bulletins",
        view_func=require_auth("PressOfficer")(with_lock(create_bulletin)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/bulletins/<bid>",
        view_func=require_auth("CDCSupervisor", "PressOfficer")(with_lock(get_bulletin)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/bulletins",
        view_func=require_auth("CDCSupervisor", "PressOfficer")(with_lock(list_bulletins)),
        methods=["GET"],
        endpoint="list_bulletins",
    )
    app.add_url_rule(
        "/epi/bulletins/<bid>/publish",
        view_func=require_auth("PressOfficer")(with_lock(publish_bulletin)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/bulletins/<bid>/retract",
        view_func=require_auth("PressOfficer")(with_lock(retract_bulletin)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/bulletins/<bid>/archive",
        view_func=require_auth("PressOfficer")(with_lock(archive_bulletin)),
        methods=["POST"],
    )


def _validate_channels(channels) -> None:
    if not isinstance(channels, list) or not channels:
        raise ApiError("ERR_INVALID_CHANNELS", "channels must be a non-empty list.")
    for ch in channels:
        if ch not in VALID_CHANNELS:
            raise ApiError(
                "ERR_INVALID_CHANNELS",
                f"channel {ch!r} not in {sorted(VALID_CHANNELS)}.",
            )


def _snapshot(bdate: str) -> tuple[int, dict]:
    store = get_store()
    try:
        bdt = parse_iso(bdate)
    except Exception:
        return 0, {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    count = 0
    for c in store.cases.values():
        try:
            r_at = parse_iso(c.get("reported_at"))
        except Exception:
            continue
        if r_at.year == bdt.year and r_at.month == bdt.month and r_at.day == bdt.day:
            count += 1
    summary = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in store.regions.values():
        tier = r.get("current_risk_tier") or "LOW"
        if tier in summary:
            summary[tier] += 1
    return count, summary


def create_bulletin():
    body = get_json_body()
    store = get_store()
    bdate = body.get("bulletin_date")
    channels = body.get("channels")
    if not bdate:
        raise ApiError("ERR_INVALID_INPUT", "Missing bulletin_date.")
    _validate_channels(channels)
    # Uniqueness on bulletin_date (parsed-day equality)
    try:
        b_dt = parse_iso(bdate)
    except Exception as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid bulletin_date: {exc}")
    for existing in store.bulletins.values():
        try:
            e_dt = parse_iso(existing.get("bulletin_date"))
            if (
                e_dt.year == b_dt.year
                and e_dt.month == b_dt.month
                and e_dt.day == b_dt.day
            ):
                raise ApiError(
                    "ERR_DUPLICATE_BULLETIN", f"Bulletin already exists for {bdate}."
                )
        except ApiError:
            raise
        except Exception:
            continue
    total_new, tier_summary = _snapshot(bdate)
    row = {
        **common_fields_create(),
        "bulletin_date": bdate,
        "total_new_cases": total_new,
        "tier_summary": tier_summary,
        "status": "DRAFT",
        "channels": list(channels),
        "rumor_corrections": [],
    }
    store.bulletins[row["id"]] = row
    return ok(row, status=201)


def get_bulletin(bid: str):
    store = get_store()
    b = store.bulletins.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", f"Bulletin {bid} not found.")
    return ok(b)


def list_bulletins():
    store = get_store()
    status = request.args.get("status")
    since = request.args.get("since")
    until = request.args.get("until")
    limit, offset = parse_limit_offset()
    items = list(store.bulletins.values())
    if status:
        items = [b for b in items if b.get("status") == status]
    if since:
        try:
            s_dt = parse_iso(since)
            items = [b for b in items if parse_iso(b.get("bulletin_date")) >= s_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid since: {since!r}")
    if until:
        try:
            u_dt = parse_iso(until)
            items = [b for b in items if parse_iso(b.get("bulletin_date")) <= u_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid until: {until!r}")
    items.sort(key=lambda b: b.get("created_at", ""))
    return ok_list(items, limit, offset)


def publish_bulletin(bid: str):
    body = get_json_body()
    store = get_store()
    b = store.bulletins.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", f"Bulletin {bid} not found.")
    check_version(b, body)
    if b.get("status") not in ("DRAFT", "RETRACTED"):
        raise ApiError("ERR_INVALID_STATE", "Bulletin must be DRAFT or RETRACTED to publish.")
    if not isinstance(b.get("channels"), list) or len(b["channels"]) == 0:
        raise ApiError("ERR_INVALID_CHANNELS", "channels must be non-empty.")
    total_new, tier_summary = _snapshot(b.get("bulletin_date"))
    b["total_new_cases"] = total_new
    b["tier_summary"] = tier_summary
    b["status"] = "PUBLISHED"
    bump_version(b)
    return ok(b)


def retract_bulletin(bid: str):
    body = get_json_body()
    store = get_store()
    b = store.bulletins.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", f"Bulletin {bid} not found.")
    check_version(b, body)
    if b.get("status") != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "Bulletin must be PUBLISHED to retract.")
    reason = body.get("reason")
    if reason:
        b.setdefault("rumor_corrections", []).append(
            {"reason": reason, "at": now_iso_ms()}
        )
    b["status"] = "RETRACTED"
    bump_version(b)
    return ok(b)


def archive_bulletin(bid: str):
    body = get_json_body()
    store = get_store()
    b = store.bulletins.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", f"Bulletin {bid} not found.")
    check_version(b, body)
    if b.get("status") != "PUBLISHED":
        raise ApiError("ERR_INVALID_STATE", "Bulletin must be PUBLISHED to archive.")
    bdate = parse_iso(b.get("bulletin_date"))
    if now_dt() < bdate + timedelta(days=BULLETIN_ARCHIVE_DAYS):
        raise ApiError(
            "ERR_INVALID_STATE", "Archive may not run before the archive-delay has elapsed."
        )
    b["status"] = "ARCHIVED"
    bump_version(b)
    return ok(b)
