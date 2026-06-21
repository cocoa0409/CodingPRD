"""Interval-overlap clash checks.

berth_clash_check (SCAFFOLD §1.3): half-open [eta, etd) overlap on the same
berth; adjacency does NOT conflict. Candidates: SCHEDULED/BERTHED windows on the
same berth_id, examined ascending eta then ascending created_at.

gate_slot_clash_check (SCAFFOLD §1.3): per-container [window_start, window_end)
overlap with a GATE_BUFFER_MIN trailing buffer; adjacency DOES conflict.
Candidates: BOOKED/ARRIVED appointments for the same container_id, examined
ascending window_start then ascending created_at.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import db
from db import GATE_BUFFER_MIN
from services.common import minutes, parse_dt


def berth_conflict(
    berth_id: str, new_eta: str, new_etd: str, exclude_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Return the first conflicting BerthWindow, or None."""
    a_eta = parse_dt(new_eta)
    a_etd = parse_dt(new_etd)
    candidates: List[Dict[str, Any]] = [
        w
        for w in db.berth_windows.values()
        if w["berth_id"] == berth_id
        and w["id"] != exclude_id
        and w["status"] in ("SCHEDULED", "BERTHED")
    ]
    candidates.sort(key=lambda w: (parse_dt(w["eta"]), w["created_at"], w.get("_seq", 0)))
    for w in candidates:
        w_eta = parse_dt(w["eta"])
        w_etd = parse_dt(w["etd"])
        # half-open overlap: A.eta < B.etd and B.eta < A.etd
        if a_eta < w_etd and w_eta < a_etd:
            return w
    return None


def gate_conflict(
    container_id: str, new_start: str, new_end: str, exclude_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Return the first conflicting GateAppointment, or None.

    Each slot widened by GATE_BUFFER_MIN on its trailing edge before the test.
    """
    a_start = parse_dt(new_start)
    a_end = parse_dt(new_end)
    buf = minutes(GATE_BUFFER_MIN)
    candidates: List[Dict[str, Any]] = [
        g
        for g in db.gate_appointments.values()
        if g["container_id"] == container_id
        and g["id"] != exclude_id
        and g["status"] in ("BOOKED", "ARRIVED")
    ]
    candidates.sort(
        key=lambda g: (parse_dt(g["window_start"]), g["created_at"], g.get("_seq", 0))
    )
    for g in candidates:
        g_start = parse_dt(g["window_start"])
        g_end = parse_dt(g["window_end"])
        # conflict := A.start < (B.end + buf) and B.start < (A.end + buf)
        if a_start < (g_end + buf) and g_start < (a_end + buf):
            return g
    return None
