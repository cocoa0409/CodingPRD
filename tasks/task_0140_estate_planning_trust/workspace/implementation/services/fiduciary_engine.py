"""Fiduciary state machine (SCAFFOLD §1.2, PRD §3.1, §3.15).

Transitions:
    NOMINATED → CONFIRMED (CourtClerk)
    CONFIRMED → RESIGNED  (Fiduciary, self-only)
    NOMINATED → REMOVED   (CourtClerk)
    CONFIRMED → REMOVED   (CourtClerk)
"""
from __future__ import annotations

from db import store
from errors import ApiError
from services.calculations import compute_gross_estate_value, compute_required_bond
from services.common import bump


def transition_fiduciary(f: dict, estate: dict, to_status: str,
                         role: str, user_id: str) -> dict:
    current = f["status"]

    if current == "NOMINATED" and to_status == "CONFIRMED":
        if role != "CourtClerk":
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Only CourtClerk may CONFIRM a fiduciary.")
        eid = estate["id"]

        if f["scope_type"] == "EXECUTOR":
            # No other CONFIRMED EXECUTOR may exist (also covers concurrent race).
            for other in store.fiduciaries.values():
                if (other["estate_id"] == eid
                        and other["id"] != f["id"]
                        and other["scope_type"] == "EXECUTOR"
                        and other["status"] == "CONFIRMED"):
                    raise ApiError("ERR_DUPLICATE_EXECUTOR", 409,
                                   "Another EXECUTOR is already CONFIRMED for this estate.")
            # Bond check vs required_bond (forward-looking).
            gross = compute_gross_estate_value(eid, "forward_looking")
            req = compute_required_bond(gross)
            if (f.get("bond_amount_cents") or 0) < req:
                raise ApiError("ERR_BOND_INSUFFICIENT", 422,
                               "Executor bond is below the required bond amount.")

        if f["scope_type"] == "GUARDIAN":
            has_minor = any(
                b for b in store.beneficiaries.values()
                if b["estate_id"] == eid and b.get("is_minor") and b["status"] == "ACTIVE"
            )
            if not has_minor:
                raise ApiError("ERR_NO_MINOR_BENEFICIARY", 422,
                               "Cannot CONFIRM a GUARDIAN without a minor beneficiary.")

        f["status"] = "CONFIRMED"
        f["court_confirmation_at"] = store.now()
        bump(f)
        return f

    if current == "CONFIRMED" and to_status == "RESIGNED":
        if role != "Fiduciary":
            raise ApiError("ERR_FORBIDDEN", 403,
                           "RESIGN is self-only — must be performed by the Fiduciary themselves.")
        if user_id != f["contact_user_id"]:
            raise ApiError("ERR_FORBIDDEN", 403,
                           "RESIGN is self-only — X-User-ID must match Fiduciary.contact_user_id.")
        if (f["scope_type"] == "EXECUTOR"
                and estate["admin_phase"] in ("IN_PROBATE", "INVENTORIED", "DISTRIBUTING")):
            # Must have a NOMINATED successor EXECUTOR.
            has_successor = any(
                other for other in store.fiduciaries.values()
                if other["estate_id"] == estate["id"]
                and other["id"] != f["id"]
                and other["scope_type"] == "EXECUTOR"
                and other["status"] == "NOMINATED"
            )
            if not has_successor:
                raise ApiError("ERR_NO_SUCCESSOR", 409,
                               "EXECUTOR cannot resign mid-probate without a NOMINATED successor.")
        f["status"] = "RESIGNED"
        bump(f)
        return f

    if current in ("NOMINATED", "CONFIRMED") and to_status == "REMOVED":
        if role != "CourtClerk":
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Only CourtClerk may REMOVE a fiduciary.")
        f["status"] = "REMOVED"
        bump(f)
        return f

    raise ApiError("ERR_INVALID_STATE", 409,
                   f"Cannot transition fiduciary from {current} to {to_status}.")
