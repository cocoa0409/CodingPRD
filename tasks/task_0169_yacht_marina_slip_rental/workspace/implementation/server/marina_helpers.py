"""Shared marina-scoped lookups, overlap checks, and size-match validation.

These helpers are imported by route blueprints to keep route bodies focused
on HTTP concerns and to centralise the priority-ordered validation logic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from flask import g

from .clock import parse_iso
from .errors import ApiError
from .store import store


# ---- Marina-scoped entity fetchers (§2.5 — path resolution left-to-right) ---


def get_marina(marina_id: str) -> dict[str, Any]:
    m = store.marinas.get(marina_id)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", "Marina not found")
    return m


def get_boater(marina_id: str, boater_id: str) -> dict[str, Any]:
    b = store.boaters.get(boater_id)
    if b is None or b.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Boater not found")
    return b


def get_vessel(marina_id: str, vessel_id: str) -> dict[str, Any]:
    v = store.vessels.get(vessel_id)
    if v is None or v.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Vessel not found")
    return v


def get_slip(marina_id: str, slip_id: str) -> dict[str, Any]:
    s = store.slips.get(slip_id)
    if s is None or s.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Slip not found")
    return s


def get_reservation(marina_id: str, reservation_id: str) -> dict[str, Any]:
    r = store.reservations.get(reservation_id)
    if r is None or r.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Reservation not found")
    return r


def get_waitlist_entry(marina_id: str, waitlist_id: str) -> dict[str, Any]:
    w = store.waitlist.get(waitlist_id)
    if w is None or w.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Waitlist entry not found")
    return w


def get_transfer_request(marina_id: str, request_id: str) -> dict[str, Any]:
    t = store.transfer_requests.get(request_id)
    if t is None or t.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Transfer request not found")
    return t


def get_pump_out_job(marina_id: str, job_id: str) -> dict[str, Any]:
    p = store.pump_out_jobs.get(job_id)
    if p is None or p.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Pump-out job not found")
    return p


def get_policy(marina_id: str, policy_id: str) -> dict[str, Any]:
    p = store.policies.get(policy_id)
    if p is None or p.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Insurance policy not found")
    return p


def get_tow_contract(marina_id: str, contract_id: str) -> dict[str, Any]:
    c = store.tow_contracts.get(contract_id)
    if c is None or c.get("marina_id") != marina_id:
        raise ApiError("ERR_NOT_FOUND", "Tow contract not found")
    return c


# ---- Ownership (Boater RBAC, PRD §2.1) -------------------------------------


def enforce_boater_owns(boater_id: str) -> None:
    """If the caller is a Boater, X-User-ID must equal the boater id."""
    if g.user_role == "Boater" and g.user_id != boater_id:
        raise ApiError("ERR_FORBIDDEN", "Boater can only act on own resources")


# ---- Date helpers ----------------------------------------------------------


def parse_required_iso(body: dict, field: str) -> datetime:
    raw = body.get(field)
    if raw is None:
        raise ApiError("ERR_BAD_REQUEST", f"Missing required field: {field}")
    try:
        return parse_iso(raw)
    except ValueError as exc:
        raise ApiError("ERR_BAD_REQUEST", f"{field}: {exc}")


def ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- Half-open interval overlap (§2.9) -------------------------------------


def half_open_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True iff [a_start, a_end) and [b_start, b_end) share at least one instant."""
    a_start = ensure_aware(a_start)
    a_end = ensure_aware(a_end)
    b_start = ensure_aware(b_start)
    b_end = ensure_aware(b_end)
    return a_start < b_end and b_start < a_end


def pump_out_window_overlap(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Pump-out windows use (start, end] open-start, closed-end form (§2.9)."""
    a_start = ensure_aware(a_start)
    a_end = ensure_aware(a_end)
    b_start = ensure_aware(b_start)
    b_end = ensure_aware(b_end)
    # Overlap iff a_start < b_end AND b_start < a_end (open-start so equality at boundaries
    # does NOT cause overlap, which matches the half-open semantic for the open side).
    return a_start < b_end and b_start < a_end


# ---- Size-match checks (Reservation approve + Slip transfer offer) ---------


def assert_size_match(slip: dict, vessel: dict) -> None:
    """Apply the three size-match validations in priority order
    (ERR_LOA_EXCEEDS_SLIP → ERR_BEAM_BUFFER_VIOLATION → ERR_DRAFT_EXCEEDS_DEPTH)."""
    if slip["length_feet"] < vessel["loa_feet"]:
        raise ApiError("ERR_LOA_EXCEEDS_SLIP", "Vessel LOA exceeds slip length")
    if slip["beam_feet"] - 2.0 < vessel["beam_feet"]:
        raise ApiError("ERR_BEAM_BUFFER_VIOLATION", "Vessel beam violates slip buffer")
    if slip["depth_feet"] < vessel["draft_feet"]:
        raise ApiError("ERR_DRAFT_EXCEEDS_DEPTH", "Vessel draft exceeds slip depth")


# ---- Overlap helpers against the slip's reservation set --------------------


def reservation_overlaps_slip(
    slip_id: str,
    check_in: datetime,
    check_out: datetime,
    *,
    ignore_reservation_id: Optional[str] = None,
) -> bool:
    """True iff any APPROVED/CHECKED_IN reservation on `slip_id` overlaps [check_in, check_out)."""
    for r in store.reservations.values():
        if r.get("slip_id") != slip_id:
            continue
        if ignore_reservation_id is not None and r.get("id") == ignore_reservation_id:
            continue
        if r.get("status") not in ("APPROVED", "CHECKED_IN"):
            continue
        try:
            r_in = parse_iso(r["check_in_date"])
            r_out = parse_iso(r["check_out_date"])
        except (KeyError, ValueError):
            continue
        if half_open_overlap(check_in, check_out, r_in, r_out):
            return True
    return False


def schedule_overlaps_pump_out(slip_id: str, start: datetime, end: datetime,
                               *, ignore_job_id: Optional[str] = None) -> bool:
    """True iff any SCHEDULED PumpOutJob whose reservation is on this slip overlaps (start, end]."""
    for p in store.pump_out_jobs.values():
        if p.get("status") != "SCHEDULED":
            continue
        if ignore_job_id is not None and p.get("id") == ignore_job_id:
            continue
        # Locate the reservation to map job -> slip
        res = store.reservations.get(p.get("reservation_id"))
        if not res or res.get("slip_id") != slip_id:
            continue
        try:
            p_start = parse_iso(p["scheduled_start"])
            p_end = parse_iso(p["scheduled_end"])
        except (KeyError, ValueError):
            continue
        if pump_out_window_overlap(start, end, p_start, p_end):
            return True
    return False


# ---- Liveaboard count maintenance (§2.10) ----------------------------------


def recompute_liveaboard_count(marina: dict) -> None:
    count = 0
    for r in store.reservations.values():
        if r.get("marina_id") != marina["id"]:
            continue
        if r.get("liveaboard") and r.get("status") in ("APPROVED", "CHECKED_IN"):
            count += 1
    marina["liveaboard_active_count"] = count


# ---- Marina-scoped waitlist sequence allocator (§3.7) ----------------------


def next_waitlist_seq(marina_id: str) -> int:
    cur = store.waitlist_seq.get(marina_id, 0)
    nxt = cur + 1
    store.waitlist_seq[marina_id] = nxt
    return nxt
