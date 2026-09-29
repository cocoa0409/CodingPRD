"""Mutation bookkeeping and the cross-entity cascades of PRD section 2.8."""
from flask import g

import calc
import db as store
from errors import ApiError
from util import now_iso


def _touched():
    if not hasattr(g, "touched_rows"):
        g.touched_rows = set()
    return g.touched_rows


def touch(rec):
    """Refresh updated_at and increment version once per row per request."""
    if rec is None or "version" not in rec:
        return
    seen = _touched()
    if rec["id"] in seen:
        return
    seen.add(rec["id"])
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ------------------------------------------------------------------ project ---

def recompute_project(project, bubble=True):
    """Recompute the project's derived figures (posture included) and, when the
    posture lands on CLEAR while the project is CLEARANCE_ACTIVE, advance the
    project to LETTING_READY.  Always a mutation of the project row."""
    if project is None:
        return
    if bubble and project["status"] == "CLEARANCE_ACTIVE" \
            and calc.clearance_posture(project) == "CLEAR":
        project["status"] = "LETTING_READY"
    touch(project)


def guard_project_open(project):
    """Rung 12."""
    if project is not None and project["status"] == "CLOSED":
        raise ApiError("ERR_PROJECT_CLOSED",
                       "The owning project is closed; no further writes are accepted.")


def guard_posture(project):
    """Rung 14."""
    if project is not None and calc.clearance_posture(project) == "FUNDING_BLOCKED":
        raise ApiError("ERR_CLEARANCE_POSTURE_BLOCKED",
                       "The project's clearance posture is FUNDING_BLOCKED.")


def guard_owner_hold(owner):
    """Rung 15."""
    if owner is not None and owner["reimbursement_hold"]:
        raise ApiError("ERR_OWNER_ON_REIMBURSEMENT_HOLD",
                       "The counterparty utility owner is on reimbursement hold.")


# ------------------------------------------------------- delinquency cascade --

def apply_delinquency_cascade(owner):
    """Links 1-4 of PRD 3.7: strike, hold, agreements HELD, documents HELD."""
    owner["delinquency_strikes"] += 1
    touch(owner)
    if owner["delinquency_strikes"] >= calc.DELINQUENCY_HOLD_THRESHOLD \
            and not owner["reimbursement_hold"]:
        owner["reimbursement_hold"] = True
    if not owner["reimbursement_hold"]:
        return
    for agreement in store.agreements_of_owner(owner["id"]):
        if agreement["settlement_status"] != "PENDING_FINAL_INVOICE":
            continue
        agreement["settlement_status"] = "HELD"
        touch(agreement)
        for document in store.documents_of_agreement(agreement["id"]):
            if document["review_status"] == "SUBMITTED":
                document["review_status"] = "HELD"
                touch(document)


def release_hold_cascade(owner):
    """Administrative release: reverses links 3 and 4 and clears the strikes."""
    owner["reimbursement_hold"] = False
    owner["delinquency_strikes"] = 0
    for agreement in store.agreements_of_owner(owner["id"]):
        if agreement["settlement_status"] != "HELD":
            continue
        agreement["settlement_status"] = "PENDING_FINAL_INVOICE"
        touch(agreement)
        for document in store.documents_of_agreement(agreement["id"]):
            if document["review_status"] == "HELD":
                document["review_status"] = "SUBMITTED"
                touch(document)
    touch(owner)


# ------------------------------------------------------------- slot / owner ---

def recompute_slot(slot):
    """The slot's occupancy figures are derived; the row is still mutated."""
    if slot is not None:
        touch(slot)


def recompute_owner(owner):
    if owner is not None:
        touch(owner)
