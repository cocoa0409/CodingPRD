"""Derived-state machinery: the bond ledger, the compliance posture with its
suspension propagation, and the multi-link cascades of PRD 3.5 and 3.7.

Version discipline (PRD 2.4): a row's `version` increases by exactly 1 per
request, no matter how many cascade links touch it. `bump()` enforces that by
remembering which rows a request has already stamped.
"""

from flask import g

import calculations as calc
import constants as C
from db import D, ZERO, db, days, money, money_floor0, now, touch

PERMIT_TERMINAL = ("DENIED", "TERMINATED", "FORFEITED")
LEDGER_FROZEN = ("TERMINATED", "FORFEITED")


# ==========================================================================
# Version stamping
# ==========================================================================
def bump(row):
    """Refresh updated_at and increment version, at most once per request."""
    stamped = getattr(g, "_stamped_rows", None)
    if stamped is None:
        stamped = set()
        g._stamped_rows = stamped
    if row["id"] in stamped:
        row["updated_at"] = now()
        return
    stamped.add(row["id"])
    touch(row)


# ==========================================================================
# PRD 2.7 — the bond ledger
# ==========================================================================
def accepted_credit_total(permit_id):
    total = ZERO
    for instrument in db.instruments.values():
        if instrument["permit_id"] == permit_id and instrument["status"] == "ACCEPTED":
            total = total + D(instrument["credited_amount"])
    return money(total)


def recompute_deficiency(permit):
    permit["bond_deficiency_amount"] = money_floor0(
        D(permit["bond_required_amount"]) - D(permit["bond_held_amount"])
    )


def refresh_bond_ledger(permit):
    """bond_held_amount = sum(credited of ACCEPTED instruments) - released."""
    if permit["status"] in LEDGER_FROZEN:
        recompute_deficiency(permit)
        return
    permit["bond_held_amount"] = money(
        accepted_credit_total(permit["id"]) - D(permit["bond_released_to_date"])
    )
    recompute_deficiency(permit)


def rerun_bond_determination(permit):
    """Re-price the permit from its single ACCEPTED estimate under the current
    bond_basis, then refresh the derived deficiency."""
    estimate = calc.accepted_estimate(permit["id"])
    if estimate is not None:
        permit["bond_required_amount"] = calc.bond_required_amount(permit, estimate)
    recompute_deficiency(permit)


# ==========================================================================
# PRD 2.8 — compliance posture and suspension propagation
# ==========================================================================
def permit_notices(permit_id):
    return [n for n in db.notices.values() if n["permit_id"] == permit_id]


def has_notice_in(permit_id, statuses):
    return any(n["notice_status"] in statuses for n in permit_notices(permit_id))


def has_proceeding(permit_id):
    return any(p["permit_id"] == permit_id for p in db.proceedings.values())


def compute_posture(permit):
    permit_id = permit["id"]
    if has_proceeding(permit_id):
        return "FORFEITURE_PENDING"
    if has_notice_in(permit_id, ("CESSATION_ORDERED",)):
        return "CESSATION"
    if D(permit["bond_deficiency_amount"]) > 0:
        return "BOND_DEFICIENT"
    if has_notice_in(permit_id, ("ISSUED",)):
        return "NOTICE_ACTIVE"
    return "COMPLIANT"


def recompute_posture(permit):
    posture = compute_posture(permit)
    permit["compliance_posture"] = posture
    if posture in ("CESSATION", "BOND_DEFICIENT", "FORFEITURE_PENDING"):
        propagate_suspension(permit)
    return posture


def sync_posture(permit):
    """Recompute the posture (with propagation) and stamp the permit only when
    one of its own fields actually moved."""
    before = (permit["compliance_posture"], permit["last_notice_end_date"])
    recompute_posture(permit)
    if (permit["compliance_posture"], permit["last_notice_end_date"]) != before:
        bump(permit)


def propagate_suspension(permit):
    suspended_any = False
    for app in db.release_apps.values():
        if app["permit_id"] != permit["id"]:
            continue
        if app["status"] not in ("SUBMITTED", "PUBLIC_NOTICE"):
            continue
        app["status"] = "SUSPENDED"
        app["notice_start_date"] = None
        app["notice_end_date"] = None
        bump(app)
        suspended_any = True
    if suspended_any:
        recompute_last_notice_end_date(permit)


def recompute_last_notice_end_date(permit):
    latest = None
    for app in db.release_apps.values():
        if app["permit_id"] != permit["id"] or app["status"] == "SUSPENDED":
            continue
        end = app["notice_end_date"]
        if end is None:
            continue
        if latest is None or end > latest:
            latest = end
    permit["last_notice_end_date"] = latest


# ==========================================================================
# PRD 3.5 — window exclusion and the TERMINATED bubble-up
# ==========================================================================
def notice_window_conflict(permit, application):
    """True when the new window would open within fifteen days of another
    application's notice_end_date. The buffer boundary itself is permitted."""
    start = now()
    for other in db.release_apps.values():
        if other["id"] == application["id"] or other["permit_id"] != permit["id"]:
            continue
        if other["status"] not in ("PUBLIC_NOTICE", "APPROVED"):
            continue
        end = other["notice_end_date"]
        if end is None:
            continue
        if start < end + days(C.NOTICE_GAP_DAYS):
            return True
    return False


PHASE_ACRE_FIELD = {
    "PHASE_I": "phase1_released_acres",
    "PHASE_II": "phase2_released_acres",
    "PHASE_III": "phase3_released_acres",
}


def evaluate_termination(permit, application):
    """RECLAMATION_PHASE -> TERMINATED after a final-phase release approval."""
    if permit["status"] != "RECLAMATION_PHASE":
        return False
    if application["phase"] != "PHASE_III":
        return False
    if D(permit["phase3_released_acres"]) != D(permit["disturbed_acres"]):
        return False
    for instrument in db.instruments.values():
        if instrument["permit_id"] == permit["id"] and instrument["status"] == "ACCEPTED":
            instrument["status"] = "RELEASED"
            bump(instrument)
    permit["bond_released_to_date"] = money(
        D(permit["bond_released_to_date"]) + D(permit["bond_held_amount"])
    )
    permit["bond_held_amount"] = ZERO
    permit["bond_deficiency_amount"] = ZERO
    permit["status"] = "TERMINATED"
    return True


# ==========================================================================
# PRD 3.7 — the four-link forfeiture cascade
# ==========================================================================
def forfeiture_cascade(permit):
    # ---- Link 2: the permit is forfeited.
    for instrument in db.instruments.values():
        if instrument["permit_id"] == permit["id"] and instrument["status"] == "ACCEPTED":
            instrument["status"] = "FORFEITED"
            bump(instrument)
    permit["bond_held_amount"] = ZERO
    permit["bond_deficiency_amount"] = ZERO
    for inspection in db.inspections.values():
        if inspection["permit_id"] == permit["id"] and inspection["status"] == "SCHEDULED":
            inspection["status"] = "CANCELLED"
            bump(inspection)
    permit["status"] = "FORFEITED"
    recompute_posture(permit)
    bump(permit)

    # ---- Link 3: the operator is disqualified statewide.
    operator = db.operators.get(permit["operator_id"])
    if operator is None:
        return
    operator["forfeiture_count"] = operator["forfeiture_count"] + 1
    operator["self_bond_status"] = "DISQUALIFIED"
    operator["registry_status"] = "DISQUALIFIED"
    operator["self_bond_capacity_amount"] = ZERO
    bump(operator)

    # ---- Link 4: every self-bond elsewhere in the portfolio needs substituting.
    touched_permits = []
    for instrument in db.instruments.values():
        if instrument["instrument_type"] != "SELF_BOND" or instrument["status"] != "ACCEPTED":
            continue
        holder = db.permits.get(instrument["permit_id"])
        if holder is None or holder["id"] == permit["id"]:
            continue
        if holder["operator_id"] != operator["id"]:
            continue
        instrument["status"] = "SUBSTITUTION_REQUIRED"
        bump(instrument)
        if holder["id"] not in [p["id"] for p in touched_permits]:
            touched_permits.append(holder)
    for holder in touched_permits:
        refresh_bond_ledger(holder)
        recompute_posture(holder)
        bump(holder)


# ==========================================================================
# PRD 3.7 — reclassification of the land into the legacy inventory
# ==========================================================================
def reclassify_site_as_legacy(permit, proceeding):
    site = db.mine_sites.get(permit["mine_site_id"])
    if site is None:
        return
    site["site_class"] = "ABANDONED_LEGACY"
    site["funding_status"] = "NOMINATED"
    site["unfunded_reclamation_need"] = money(proceeding["deficiency_amount"])
    site["acres_affected"] = money(
        D(permit["disturbed_acres"]) - D(permit["reclaimed_acres_credited"])
    )
    site["legacy_priority_score"] = calc.legacy_priority_score(site)
    bump(site)
