"""The four gates (PRD 2.7) plus the shared staff-safety rungs 18 and 19."""

import clock
import store
from errors import ApiError
from validation import touch

FROZEN_PERIOD_STATUSES = ("SUBMITTED", "CLOSED")


# --------------------------------------------------------------------------
# Period resolution (PRD 2.7)
# --------------------------------------------------------------------------
def period_for_site_visit(site_visit):
    return site_visit.get("program_period_id") if site_visit else None


def period_for_encounter(encounter):
    if not encounter:
        return None
    visit = store.get("site_visits", encounter["site_visit_id"])
    return period_for_site_visit(visit)


def period_for_procedure(procedure):
    if not procedure:
        return None
    return period_for_encounter(store.get("encounters", procedure["encounter_id"]))


def period_for_treatment_plan(plan):
    if not plan:
        return None
    return period_for_encounter(store.get("encounters", plan["encounter_id"]))


def period_for_sterilization_load(load):
    if not load or not load.get("site_visit_id"):
        return None
    return period_for_site_visit(store.get("site_visits", load["site_visit_id"]))


# --------------------------------------------------------------------------
# Rung 9 -- the global write gate
# --------------------------------------------------------------------------
def period_gate(program_period_id):
    """Refuse a gated write whose entity resolves to a frozen programme period."""
    if program_period_id is None:
        return
    period = store.get("program_periods", program_period_id)
    if period is None:
        return
    if period["status"] in FROZEN_PERIOD_STATUSES:
        raise ApiError("ERR_PERIOD_FROZEN")


# --------------------------------------------------------------------------
# Rung 10 -- the site hold gate
# --------------------------------------------------------------------------
def intersects(a_start, a_end, b_start, b_end):
    """Half-open interval intersection."""
    return a_start < b_end and b_start < a_end


def active_holds_for_site(site_id):
    return [
        h for h in store.all_rows("site_holds")
        if h["site_id"] == site_id and h["hold_status"] == "ACTIVE"
    ]


def site_hold_gate(site, window_start, window_end):
    if site["status"] == "SUSPENDED":
        raise ApiError("ERR_SITE_ON_HOLD")
    if window_start is None or window_end is None:
        return
    for hold in active_holds_for_site(site["id"]):
        if intersects(window_start, window_end, hold["starts_at"], hold["ends_at"]):
            raise ApiError("ERR_SITE_ON_HOLD")


# --------------------------------------------------------------------------
# Rungs 18 and 19 -- credentials and licences
# --------------------------------------------------------------------------
def credential_gate(staff_rows):
    for staff in staff_rows:
        if staff is None:
            continue
        if staff["credential_status"] != "ACTIVE":
            raise ApiError("ERR_CREDENTIAL_LAPSED")


def license_state_gate(staff_rows, site):
    for staff in staff_rows:
        if staff is None:
            continue
        if staff["license_state"] != site["state_code"]:
            raise ApiError("ERR_LICENSE_STATE_MISMATCH")


# --------------------------------------------------------------------------
# Rungs 23 and 24 -- the cited consent
# --------------------------------------------------------------------------
def consent_revoked_gate(consent):
    if consent["status"] in ("REVOKED", "SUPERSEDED"):
        raise ApiError("ERR_CONSENT_REVOKED")


def consent_expiry_sweep(consent):
    """Sweep 2 (rung 24), mutate-then-reject."""
    if consent["status"] == "EXPIRED":
        raise ApiError("ERR_CONSENT_EXPIRED")
    if consent["status"] not in ("PENDING_VERIFICATION", "ACTIVE"):
        return
    expires_at = consent.get("expires_at")
    if expires_at is None:
        return
    if clock.now() >= expires_at:
        consent["status"] = "EXPIRED"
        consent["expired_at"] = clock.now()
        touch(consent)
        raise ApiError("ERR_CONSENT_EXPIRED")


# --------------------------------------------------------------------------
# The stale-report cascade that rides on every successful period-gated write
# --------------------------------------------------------------------------
def mark_period_reports_stale(program_period_id):
    if program_period_id is None:
        return
    for report in store.all_rows("reports"):
        if report["program_period_id"] != program_period_id:
            continue
        if report["report_type"] != "PROGRAM_PERIOD":
            continue
        if report["status"] != "GENERATED":
            continue
        report["status"] = "STALE"
        report["stale_reason"] = "PERIOD_DATA_CHANGED"
        touch(report)


def stamp(row, field):
    row[field] = clock.now()
