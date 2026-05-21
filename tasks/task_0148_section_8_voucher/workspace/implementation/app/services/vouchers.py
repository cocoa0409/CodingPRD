"""Voucher issuance + state transitions."""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app import clock, store
from app.errors import APIError, fk_not_found, invalid_state, validation
from app.services.common import touch
from app.util import new_id, require_bool, require_str


_VALID_ZONES = ("ZONE_A", "ZONE_B", "ZONE_C")


def _bedroom_size_for_household(household_size: int) -> int:
    if household_size <= 1:
        return 0
    if household_size == 2:
        return 1
    if household_size <= 4:
        return 2
    if household_size <= 6:
        return 3
    if household_size <= 8:
        return 4
    return 5


def issue_voucher(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation("Body must be a JSON object")
    try:
        applicant_id = require_str(payload.get("applicant_id"), field="applicant_id")
        zone = require_str(payload.get("zone"), field="zone", allowed=_VALID_ZONES)
        administering_pha_id = require_str(payload.get("administering_pha_id"), field="administering_pha_id")
        special_mobility_flag = payload.get("special_mobility_flag", False)
        if not isinstance(special_mobility_flag, bool):
            raise ValueError("special_mobility_flag must be a boolean")
    except ValueError as exc:
        raise validation(str(exc))

    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        raise fk_not_found(f"applicant_id {applicant_id!r} not found")
    if administering_pha_id not in store.CONFIGURED_PHAS:
        raise validation(f"administering_pha_id must be in {list(store.CONFIGURED_PHAS)}")
    if applicant.get("eligibility_status") != "ELIGIBLE":
        raise invalid_state("Applicant is not ELIGIBLE")

    now = clock.now()
    voucher_id = new_id()
    bedroom_size = _bedroom_size_for_household(applicant["household_size"])

    record = {
        "id": voucher_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "applicant_id": applicant_id,
        "bedroom_size": bedroom_size,
        "issued_at": now,
        "search_deadline": now + timedelta(days=120),
        "zone": zone,
        "special_mobility_flag": special_mobility_flag,
        "administering_pha_id": administering_pha_id,
        # ISSUED is momentary — flip immediately to SEARCHING per §3.2.
        "status": "SEARCHING",
    }
    store.vouchers[voucher_id] = record
    return record


def list_vouchers(*, status: Optional[str], administering_pha_id: Optional[str], special_mobility_flag: Optional[bool]):
    out = []
    for v in store.vouchers.values():
        if status and v.get("status") != status:
            continue
        if administering_pha_id and v.get("administering_pha_id") != administering_pha_id:
            continue
        if special_mobility_flag is not None and v.get("special_mobility_flag") != special_mobility_flag:
            continue
        out.append(v)
    return out
