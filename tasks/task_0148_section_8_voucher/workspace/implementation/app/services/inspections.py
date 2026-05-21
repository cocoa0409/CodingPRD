"""Inspection scheduling + completion (with cascades into Tenancy)."""

from __future__ import annotations

from datetime import timedelta
from typing import List, Optional

from app import clock, store
from app.errors import APIError, fk_not_found, invalid_state, not_found, validation
from app.services.common import occ_check, touch
from app.util import new_id, parse_iso, require_str


_VALID_TYPES = ("INITIAL", "ANNUAL", "REINSPECTION")
_VALID_OUTCOMES = ("PASS", "FAIL_NONLIFETHREATENING", "FAIL_LIFETHREATENING", "CURED")


def schedule_inspection(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        tenancy_id = require_str(payload.get("tenancy_id"), field="tenancy_id")
        inspection_type = require_str(payload.get("inspection_type"), field="inspection_type", allowed=_VALID_TYPES)
        scheduled_for = parse_iso(payload.get("scheduled_for"))
        if scheduled_for is None:
            raise ValueError("scheduled_for is required")
    except ValueError as exc:
        raise validation(str(exc))

    tenancy = store.tenancies.get(tenancy_id)
    if tenancy is None:
        raise fk_not_found(f"tenancy_id {tenancy_id!r} not found")
    unit_id = tenancy["unit_id"]

    # ANNUAL gap guard (priority 15) — at least 365 days from previous PASS/CURED on same unit.
    if inspection_type == "ANNUAL":
        last_pass = _last_pass_completed_at(unit_id)
        if last_pass is not None:
            gap_days = (scheduled_for - last_pass).days
            if gap_days < 365:
                raise APIError(
                    "ERR_INSPECTION_TOO_SOON",
                    409,
                    "ANNUAL inspection within 365 days of last passing inspection",
                )

    now = clock.now()
    insp_id = new_id()
    record = {
        "id": insp_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "tenancy_id": tenancy_id,
        "unit_id": unit_id,
        "inspection_type": inspection_type,
        "scheduled_for": scheduled_for,
        "completed_at": None,
        "outcome": None,
        "defects": [],
        "cure_deadline": None,
        "status": "SCHEDULED",
        "abatement_source": False,
    }
    store.inspections[insp_id] = record
    return record


def _inspector_pha_id(inspector_id: Optional[str]) -> Optional[str]:
    """Derive the Inspector's PHA from the X-User-ID prefix convention
    `inspector-<PHA_ID>-<suffix>` per PRD §3.5. Returns None if the id
    does not match the convention (so callers fall back to the default
    PHA)."""
    if not inspector_id or not inspector_id.startswith("inspector-"):
        return None
    rest = inspector_id[len("inspector-"):]
    # PHA ids are like PHA_001 — first chunk up to the next dash.
    pha_part = rest.split("-", 1)[0]
    return pha_part or None


def complete_inspection(inspection_id: str, payload: dict, caller_id: Optional[str] = None) -> dict:
    payload = payload or {}
    insp = store.inspections.get(inspection_id)
    if insp is None:
        raise not_found("Inspection not found")
    occ_check(insp, payload.get("version"))

    # Already-complete guard (priority on Inspection.status).
    if insp["status"] != "SCHEDULED":
        raise APIError("ERR_INSPECTION_ALREADY_COMPLETED", 409, "Inspection already completed")

    # Inspector-scope gate (priority 8 per §2.10): an Inspector may only
    # complete inspections whose tenancy's voucher is administered by
    # the inspector's own PHA. Inspector IDs encode PHA membership via
    # the `inspector-<PHA_ID>-<suffix>` prefix convention.
    tenancy = store.tenancies.get(insp.get("tenancy_id"))
    voucher = store.vouchers.get(tenancy["voucher_id"]) if tenancy else None
    voucher_pha = voucher.get("administering_pha_id") if voucher else None
    inspector_pha = _inspector_pha_id(caller_id)
    if voucher_pha is not None and inspector_pha is not None and voucher_pha != inspector_pha:
        raise APIError(
            "ERR_INSPECTOR_OUT_OF_SCOPE",
            403,
            "Inspector PHA does not match voucher administering PHA",
        )

    try:
        outcome = require_str(payload.get("outcome"), field="outcome", allowed=_VALID_OUTCOMES)
        defects = payload.get("defects", [])
        if not isinstance(defects, list):
            raise ValueError("defects must be an array")
    except ValueError as exc:
        raise validation(str(exc))

    # PASS requires empty defects; FAIL_* requires non-empty defects.
    if outcome == "PASS" and len(defects) != 0:
        raise APIError("ERR_INSPECTION_OUTCOME_MISMATCH", 422, "PASS must have empty defects")
    if outcome in ("FAIL_NONLIFETHREATENING", "FAIL_LIFETHREATENING") and len(defects) == 0:
        raise APIError("ERR_INSPECTION_OUTCOME_MISMATCH", 422, "FAIL_* requires non-empty defects")
    # CURED is only valid on REINSPECTION per §3.5.
    if outcome == "CURED" and insp.get("inspection_type") != "REINSPECTION":
        raise APIError(
            "ERR_INSPECTION_OUTCOME_MISMATCH",
            422,
            "CURED outcome only valid on REINSPECTION",
        )

    now = clock.now()
    insp["completed_at"] = now
    insp["outcome"] = outcome
    insp["defects"] = list(defects)
    if outcome == "PASS":
        insp["status"] = "COMPLETED_PASS"
        insp["cure_deadline"] = None
    elif outcome == "FAIL_NONLIFETHREATENING":
        insp["status"] = "COMPLETED_FAIL_CURABLE"
        insp["cure_deadline"] = now + timedelta(days=30)
    elif outcome == "FAIL_LIFETHREATENING":
        insp["status"] = "COMPLETED_FAIL_LIFETHREAT"
        insp["cure_deadline"] = now + timedelta(hours=24)
    elif outcome == "CURED":
        insp["status"] = "CURED"
        insp["cure_deadline"] = None
    touch(insp)

    _cascade_inspection_into_tenancy(insp)
    return insp


def _last_pass_completed_at(unit_id: str):
    best = None
    for i in store.inspections.values():
        if i.get("unit_id") != unit_id:
            continue
        if i.get("outcome") in ("PASS", "CURED") and i.get("completed_at"):
            if best is None or i["completed_at"] > best:
                best = i["completed_at"]
    return best


def _cascade_inspection_into_tenancy(insp: dict) -> None:
    """Apply §3.5 cascades to the parent tenancy + unit + HAP."""
    tenancy = store.tenancies.get(insp["tenancy_id"])
    if tenancy is None:
        return
    outcome = insp["outcome"]
    itype = insp["inspection_type"]
    now = insp["completed_at"]

    if outcome == "PASS":
        # INITIAL pass moves PENDING_INSPECTION → PENDING_RENT_REASONABLE.
        if itype == "INITIAL" and tenancy["status"] == "PENDING_INSPECTION":
            tenancy["status"] = "PENDING_RENT_REASONABLE"
            touch(tenancy)
        # ANNUAL pass leaves the tenancy where it was; the unit's
        # last_inspection_passed_at is computed on read, so nothing to do.

    elif outcome in ("FAIL_NONLIFETHREATENING", "FAIL_LIFETHREATENING"):
        if itype == "ANNUAL" and tenancy["status"] == "ACTIVE":
            tenancy["status"] = "ABATED"
            tenancy["abatement_started_at"] = now
            insp["abatement_source"] = True
            touch(tenancy)
            # Emit a next-month HAP row at $0 / ABATED_SUSPENDED.
            from app.services.hap import emit_abatement_row
            emit_abatement_row(tenancy, source_inspection_id=insp["id"])
        # INITIAL fail just leaves tenancy in PENDING_INSPECTION (or PENDING_RENT_REASONABLE
        # blocking finalize). Nothing to cascade here.

    elif outcome == "CURED":
        # REINSPECTION CURED. If parent was ABATED → ACTIVE.
        if tenancy["status"] == "ABATED":
            tenancy["status"] = "ACTIVE"
            tenancy["abatement_started_at"] = None
            touch(tenancy)
        elif tenancy["status"] == "PENDING_INSPECTION":
            tenancy["status"] = "PENDING_RENT_REASONABLE"
            touch(tenancy)
        # Mark the originating failed inspection as CURED so its sweep finds
        # nothing to expire.
        for prior in store.inspections.values():
            if prior.get("tenancy_id") != tenancy["id"]:
                continue
            if prior["id"] == insp["id"]:
                continue
            if prior.get("status") in ("COMPLETED_FAIL_CURABLE", "COMPLETED_FAIL_LIFETHREAT"):
                prior["status"] = "CURED"
                touch(prior)
