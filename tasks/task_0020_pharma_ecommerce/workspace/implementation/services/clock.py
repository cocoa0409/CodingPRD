"""Clock advance and time-driven auto sweeps (PRD §2.11, §3.1)."""

from __future__ import annotations

import datetime as _dt
import math

from db import (
    append_audit_log,
    db,
    emit_external_event,
    fmt_iso,
    parse_iso,
    set_platform_clock,
    stamp_update,
)
from services.cascades import cascade_off_shelve_to_orders


def _pharmacist_sweep(platform: dict, new_clock: _dt.datetime) -> None:
    """ACTIVE → EXPIRED for any pharmacist whose certificate_expires_at <= new clock."""
    for ph in db.pharmacists.values():
        if ph.get("platform_id") != platform["id"]:
            continue
        if ph.get("qualification_status") != "ACTIVE":
            continue
        cert_exp = parse_iso(ph["certificate_expires_at"])
        if new_clock >= cert_exp:
            ph["qualification_status"] = "EXPIRED"
            stamp_update(ph, platform)


def _vendor_sweep(platform: dict, new_clock: _dt.datetime) -> None:
    """ACTIVE → REVIEW_REQUIRED on YELLOW/RED tier (PRD §3.1); REVIEW_REQUIRED → SUSPENDED at max(L,P)."""
    from services.calculations import ALERT_DAYS, vendor_score

    for v in list(db.vendors.values()):
        if v.get("platform_id") != platform["id"]:
            continue
        l_exp = parse_iso(v["business_license_expires_at"])
        p_exp = parse_iso(v["drug_operation_permit_expires_at"])
        earlier = min(l_exp, p_exp)
        later = max(l_exp, p_exp)
        if v.get("qualification_status") == "ACTIVE":
            score = vendor_score(platform, v)
            alert_threshold = earlier - _dt.timedelta(days=ALERT_DAYS)
            if score["tier"] in ("YELLOW", "RED") or new_clock >= alert_threshold:
                v["qualification_status"] = "REVIEW_REQUIRED"
                stamp_update(v, platform)
                emit_external_event(
                    platform=platform,
                    channel="REGULATORY_AUTHORITY",
                    event_type="vendor.review_required",
                    subject_type="VENDOR",
                    subject_id=v["id"],
                    payload={"vendor_id": v["id"], "version": v["version"]},
                    idempotency_key=f"vendor.review_required:{v['id']}:{v['version']}",
                )
        if v.get("qualification_status") == "REVIEW_REQUIRED":
            if new_clock >= later:
                v["qualification_status"] = "SUSPENDED"
                stamp_update(v, platform)
                append_audit_log(
                    platform=platform,
                    subject_type="VENDOR",
                    subject_id=v["id"],
                    action="VENDOR_SUSPENDED",
                    actor_role="system",
                    actor_id="system",
                    payload={"vendor_id": v["id"], "version": v["version"]},
                )
                # Cascade: ON_SHELF drugs → OFF_SHELF; that further cascades into outstanding orders.
                drugs_to_off_shelve = [
                    d
                    for d in list(db.drugs.values())
                    if d.get("platform_id") == platform["id"]
                    and d.get("vendor_id") == v["id"]
                    and d.get("status") == "ON_SHELF"
                ]
                for d in drugs_to_off_shelve:
                    d["status"] = "OFF_SHELF"
                    stamp_update(d, platform)
                    cascade_off_shelve_to_orders(platform, d["id"])


def advance_clock(platform: dict, new_clock: _dt.datetime) -> None:
    """Set the platform clock and run auto sweeps in the prescribed order:
    pharmacist expiry → vendor review/suspension."""
    set_platform_clock(platform, fmt_iso(new_clock))
    stamp_update(platform, platform)
    _pharmacist_sweep(platform, new_clock)
    _vendor_sweep(platform, new_clock)
