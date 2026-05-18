"""Case engine: state-machine helpers, OCC, cascades, and SoL guards.

Centralizes the bump-version + touch-updated_at logic so every cascade
hop produces the right side-effects (PRD §2.6).
"""
from __future__ import annotations

from datetime import date, datetime

from db import store
from errors import ApiError, raise_error
from services.calculations import (
    calc_damages_total,
    calc_sol_deadline,
    is_sol_expired,
    sum_received_medical_bills,
)
from utils import date_iso, parse_iso_date


# ── Common row helpers ─────────────────────────────────────────────────────


def now():
    return store.now()


def new_common_fields() -> dict:
    n = store.now()
    return {"created_at": n, "updated_at": n, "version": 1}


def touch(row: dict) -> None:
    row["updated_at"] = store.now()
    row["version"] = int(row.get("version", 1)) + 1


def check_version_match(row: dict, supplied_version) -> None:
    """OCC: if client supplied `version`, it must match stored. Else skip."""
    if supplied_version is None:
        return
    if not isinstance(supplied_version, int):
        raise_error("ERR_VERSION_MISMATCH", "version must be an integer.")
    if int(supplied_version) != int(row.get("version", 0)):
        raise_error("ERR_VERSION_MISMATCH", "Stored version does not match supplied.")


# ── Case lookups ───────────────────────────────────────────────────────────


def get_case_or_404(case_id: str) -> dict:
    row = store.cases.get(case_id)
    if not row:
        raise_error("ERR_NOT_FOUND", f"Case {case_id} not found.")
    return row


def assert_case_not_closed(case_row: dict) -> None:
    if case_row["status"] in ("DISMISSED", "CLOSED"):
        raise_error(
            "ERR_CASE_CLOSED",
            f"Case is in {case_row['status']}; no further operations permitted.",
        )


def assert_case_sol_not_expired(case_row: dict) -> None:
    if is_sol_expired(case_row, now()):
        raise_error(
            "ERR_STATUTE_OF_LIMITATIONS_EXPIRED",
            "Case statute of limitations has passed.",
        )


# ── SoL deadline recomputation ─────────────────────────────────────────────


def recompute_sol_deadline(case_row: dict, client_row: dict) -> None:
    """Recompute and store `sol_deadline` on the case row (no touch())."""
    incident_date = parse_iso_date(case_row["incident_date"])
    dob = parse_iso_date(client_row["date_of_birth"])
    is_minor = bool(client_row.get("is_minor_at_incident"))
    deadline = calc_sol_deadline(
        jurisdiction_state=case_row["jurisdiction_state"],
        incident_type=case_row["incident_type"],
        incident_date=incident_date,
        is_minor_at_incident=is_minor,
        date_of_birth=dob,
        sol_tolled_days=int(case_row.get("sol_tolled_days", 0)),
    )
    case_row["sol_deadline"] = date_iso(deadline)


# ── Damages cascade ────────────────────────────────────────────────────────


def recompute_damages_for_case(case_id: str) -> dict | None:
    """If a Damages row exists for the case, recompute and bump it. Return row."""
    damages_id = store.damages_by_case.get(case_id)
    if not damages_id:
        return None
    damages_row = store.damages[damages_id]
    received_total = sum_received_medical_bills(case_id, store.medical_requests)
    calc_damages_total(damages_row, received_total)
    touch(damages_row)
    return damages_row


# ── Demand-letter helpers ──────────────────────────────────────────────────


def find_active_demand_letter(case_id: str) -> dict | None:
    """Active = status IN {DRAFT, SENT}."""
    for d in store.demand_letters.values():
        if d["case_id"] == case_id and d["status"] in ("DRAFT", "SENT"):
            return d
    return None


# ── Court event helpers ───────────────────────────────────────────────────


def find_existing_complaint_filed(case_id: str) -> dict | None:
    for ev in store.court_events.values():
        if (
            ev["case_id"] == case_id
            and ev["event_type"] == "COMPLAINT_FILED"
            and ev["status"] != "CANCELED"
        ):
            return ev
    return None


def has_any_defendant_offer(case_id: str) -> bool:
    for o in store.settlement_offers.values():
        if o["case_id"] == case_id and o["offer_party"] == "DEFENDANT":
            return True
    return False
