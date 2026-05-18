"""Beneficiary state machine (SCAFFOLD §1.2, PRD §3.9, §3.10).

Transitions:
    ACTIVE → DISCLAIMED (Beneficiary, self-only)
    ACTIVE → REMOVED    (CourtClerk)

Cascades on disclaim:
  - PROPOSED + LOCKED designations referencing this beneficiary → VOIDED
  - Estate may force-revert DISTRIBUTING → INVENTORIED if any asset's
    LOCKED-sum < 10000 after the void cascade.
Cascades on remove (CourtClerk):
  - PROPOSED designations only → VOIDED (LOCKED rows are court-protected).
"""
from __future__ import annotations

from db import store
from errors import ApiError
from services.common import bump


def transition_beneficiary(b: dict, estate: dict, to_status: str,
                           role: str, user_id: str) -> dict:
    current = b["status"]

    if current == "ACTIVE" and to_status == "DISCLAIMED":
        # Per §3.9: actor is Beneficiary; self-only.
        if role != "Beneficiary":
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Only the Beneficiary themselves may DISCLAIM.")
        if user_id != b["id"]:
            raise ApiError("ERR_FORBIDDEN", 403,
                           "DISCLAIM is self-only.")
        if estate["admin_phase"] not in ("IN_PROBATE", "INVENTORIED", "DISTRIBUTING"):
            # PRD §3.9 says IN_PROBATE or INVENTORIED. §3.10 also handles
            # disclaim during DISTRIBUTING (it commits, designations void,
            # estate force-reverts). We allow DISTRIBUTING here.
            raise ApiError("ERR_INVALID_STATE", 409,
                           "DISCLAIM is only permitted during IN_PROBATE / INVENTORIED / DISTRIBUTING.")
        # No EXECUTED distribution may exist for this beneficiary.
        for d in store.distributions.values():
            if (d["estate_id"] == estate["id"]
                    and d["beneficiary_id"] == b["id"]
                    and d["status"] == "EXECUTED"):
                raise ApiError("ERR_HAS_DEPENDENCIES", 409,
                               "Beneficiary has an EXECUTED distribution.")

        b["status"] = "DISCLAIMED"
        bump(b)
        # Cascade: PROPOSED and LOCKED designations → VOIDED.
        for d in store.designations.values():
            if (d["estate_id"] == estate["id"]
                    and d["beneficiary_id"] == b["id"]
                    and d["status"] in ("PROPOSED", "LOCKED")):
                d["status"] = "VOIDED"

        # Possible force-revert DISTRIBUTING → INVENTORIED.
        from services.estate_engine import maybe_revert_to_inventoried
        maybe_revert_to_inventoried(estate)

        return b

    if current == "ACTIVE" and to_status == "REMOVED":
        if role != "CourtClerk":
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Only CourtClerk may REMOVE a beneficiary.")
        if estate["admin_phase"] == "SETTLED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "Cannot remove a beneficiary on a SETTLED estate.")
        b["status"] = "REMOVED"
        bump(b)
        # Cascade: PROPOSED designations → VOIDED (LOCKED preserved).
        for d in store.designations.values():
            if (d["estate_id"] == estate["id"]
                    and d["beneficiary_id"] == b["id"]
                    and d["status"] == "PROPOSED"):
                d["status"] = "VOIDED"
        return b

    raise ApiError("ERR_INVALID_STATE", 409,
                   f"Cannot transition beneficiary from {current} to {to_status}.")
