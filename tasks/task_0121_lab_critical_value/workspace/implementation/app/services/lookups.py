"""Existence lookups — raise ERR_NOT_FOUND when a row is missing."""
from __future__ import annotations

from typing import Any

from ..errors import err_not_found
from ..store import store


def get_patient(pid: str) -> dict[str, Any]:
    row = store().patients.get(pid)
    if not row:
        raise err_not_found(f"Patient {pid} not found")
    return row


def get_clinician(cid: str) -> dict[str, Any]:
    row = store().clinicians.get(cid)
    if not row:
        raise err_not_found(f"Clinician {cid} not found")
    return row


def get_test_panel(pid: str) -> dict[str, Any]:
    row = store().test_panels.get(pid)
    if not row:
        raise err_not_found(f"TestPanel {pid} not found")
    return row


def get_lab_order(oid: str) -> dict[str, Any]:
    row = store().lab_orders.get(oid)
    if not row:
        raise err_not_found(f"LabOrder {oid} not found")
    return row


def get_specimen(sid: str) -> dict[str, Any]:
    row = store().specimens.get(sid)
    if not row:
        raise err_not_found(f"Specimen {sid} not found")
    return row


def get_transport_leg(lid: str) -> dict[str, Any]:
    row = store().transport_legs.get(lid)
    if not row:
        raise err_not_found(f"TransportLeg {lid} not found")
    return row


def get_lab_result(rid: str) -> dict[str, Any]:
    row = store().lab_results.get(rid)
    if not row:
        raise err_not_found(f"LabResult {rid} not found")
    return row


def get_critical_notification(nid: str) -> dict[str, Any]:
    row = store().critical_notifications.get(nid)
    if not row:
        raise err_not_found(f"CriticalNotification {nid} not found")
    return row


def get_retest_request(rid: str) -> dict[str, Any]:
    row = store().retest_requests.get(rid)
    if not row:
        raise err_not_found(f"RetestRequest {rid} not found")
    return row
