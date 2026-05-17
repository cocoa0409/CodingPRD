"""License-status projection and helper lookups.

Per §2.9 / §1.3 (state_license_status_projection):
  - If an AuditEvent(LICENSE_REVOKED) exists whose subject_id == this license id → REVOKED.
  - Else if clock.now() >= license.expires_at → EXPIRED.
  - Else → ACTIVE.

Status is a projection computed at read time and at state-machine precondition
checks; it is NOT a stable stored column.
"""
from typing import Any, Dict, List, Optional

from app.clock import clock
from app.store import store
from app.utils import parse_iso_datetime


def project_license_status(license_row: Dict[str, Any]) -> str:
    # Revocation: any AuditEvent of type LICENSE_REVOKED whose subject_id matches.
    for ev in store.audit_events:
        if (
            ev.get("event_type") == "LICENSE_REVOKED"
            and ev.get("subject_entity") == "StateLicense"
            and ev.get("subject_id") == license_row["id"]
        ):
            return "REVOKED"
    # Expiration: clock crossed expires_at.
    try:
        expires = parse_iso_datetime(license_row["expires_at"])
    except Exception:
        return "ACTIVE"
    if clock.now() >= expires:
        return "EXPIRED"
    return "ACTIVE"


def view_license(license_row: Dict[str, Any]) -> Dict[str, Any]:
    """Return a license dict for API output with projected status."""
    out = dict(license_row)
    out["status"] = project_license_status(license_row)
    return out


def list_licenses_for_physician(physician_id: str) -> List[Dict[str, Any]]:
    return [l for l in store.state_licenses.values() if l["physician_id"] == physician_id]


def find_active_matching_license(
    physician_id: str, state_code: str
) -> Optional[Dict[str, Any]]:
    """Return the first ACTIVE license for (physician_id, state_code), or None.

    Selection ordering: pick the most recently issued ACTIVE license to be
    deterministic when multiple non-overlapping intervals could match. In
    practice with half-open non-overlapping intervals at most one is ACTIVE
    at any given moment.
    """
    candidates: List[Dict[str, Any]] = []
    for lic in store.state_licenses.values():
        if lic["physician_id"] != physician_id:
            continue
        if lic["state_code"] != state_code:
            continue
        if project_license_status(lic) != "ACTIVE":
            continue
        # And license_type must be FULL or IMLC_EXPEDITED (only allowed values)
        if lic["license_type"] not in ("FULL", "IMLC_EXPEDITED"):
            continue
        candidates.append(lic)
    if not candidates:
        return None
    # Deterministic pick: latest issued_at.
    candidates.sort(key=lambda l: l.get("issued_at") or "", reverse=True)
    return candidates[0]
