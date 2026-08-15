"""Domain services: derived-state reconciliation, cascades, and the
deadline-driven automation sweep (PRD 2.4 / 2.10)."""

from __future__ import annotations

from datetime import timedelta

import db
from constants import (
    CASE_TERMINAL,
    ENCROACHMENT_TERMINAL,
    FILING_WINDOW_DAYS,
    OFFER_COMMITTED_STATUSES,
    OWNER_RESPONSE_WINDOW_DAYS,
    REMEDIATION_WINDOW_DAYS,
    VIOLATION_OPEN_STATUSES,
    VIOLATION_REMEDIATION_THRESHOLD,
)
from errors import raise_err
from services import calculations
from util import parse_ts_stored


# ---------------------------------------------------------------------------
# Scoped lookups (existence, left to right; PRD 2.9)
# ---------------------------------------------------------------------------

def get_case_or_404(case_id: str) -> dict:
    case = db.cases.get(case_id)
    if case is None:
        raise_err("ERR_CASE_NOT_FOUND", "EasementCase with given caseId does not exist")
    return case


def get_document_or_404(case: dict, doc_id: str) -> dict:
    doc = db.documents.get(doc_id)
    if doc is None or doc["case_id"] != case["id"]:
        raise_err("ERR_DOCUMENT_NOT_FOUND", "EasementDocument with given docId does not exist")
    return doc


def get_encroachment_or_404(case: dict, enc_id: str) -> dict:
    enc = db.encroachments.get(enc_id)
    if enc is None or enc["case_id"] != case["id"]:
        raise_err("ERR_ENCROACHMENT_NOT_FOUND", "Encroachment with given encId does not exist")
    return enc


def get_offer_or_404(case: dict, offer_id: str) -> dict:
    offer = db.offers.get(offer_id)
    if offer is None or offer["case_id"] != case["id"]:
        raise_err("ERR_OFFER_NOT_FOUND", "AcquisitionOffer with given offerId does not exist")
    return offer


def get_permit_or_404(case: dict, permit_id: str) -> dict:
    permit = db.permits.get(permit_id)
    if permit is None or permit["case_id"] != case["id"]:
        raise_err("ERR_PERMIT_NOT_FOUND", "ThirdPartyPermit with given permitId does not exist")
    return permit


def get_zone_or_404(case: dict, zone_id: str) -> dict:
    zone = db.zones.get(zone_id)
    if zone is None or zone["case_id"] != case["id"]:
        raise_err("ERR_ZONE_NOT_FOUND", "VegetationZone with given zoneId does not exist")
    return zone


def get_violation_or_404(zone: dict, viol_id: str) -> dict:
    viol = db.violations.get(viol_id)
    if viol is None or viol["zone_id"] != zone["id"]:
        raise_err("ERR_VIOLATION_NOT_FOUND", "VegetationViolation with given violId does not exist")
    return viol


def get_task_or_404(case: dict, task_id: str) -> dict:
    task = db.title_tasks.get(task_id)
    if task is None or task["case_id"] != case["id"]:
        raise_err("ERR_TITLE_TASK_NOT_FOUND", "TitleSearchTask with given taskId does not exist")
    return task


def get_referral_or_404(case: dict, ref_id: str) -> dict:
    ref = db.referrals.get(ref_id)
    if ref is None or ref["case_id"] != case["id"]:
        raise_err("ERR_REFERRAL_NOT_FOUND", "LitigationReferral with given refId does not exist")
    return ref


def ensure_case_not_closed(case: dict) -> None:
    if case["status"] in CASE_TERMINAL:
        raise_err("ERR_CASE_ALREADY_CLOSED", "Case is in a terminal CLOSED_* state")


def check_expected_case_version(case: dict, body: dict) -> None:
    """OCC gate (PRD 2.7): expected_case_version must match case.version."""
    expected = body.get("expected_case_version")
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        expected_int = None
    if expected_int is None or expected_int != case["version"]:
        raise_err(
            "ERR_STALE_CASE_VERSION",
            "expected_case_version does not match EasementCase.version",
        )


# ---------------------------------------------------------------------------
# Case derived-state reconciliation (PRD 2.4)
# ---------------------------------------------------------------------------

def reconcile_case(case: dict, bump: bool = False) -> None:
    """Recompute every derived field of the case from its children; reconcile
    the ACTIVE_MONITORING <-> RESOLUTION_PENDING movement; bump version when
    anything changed (or when the triggering operation is defined as a case
    mutation, e.g. the three OCC writes)."""
    cid = case["id"]
    changed = False

    committed = sum(
        o["total_compensation_cents"]
        for o in db.offers.values()
        if o["case_id"] == cid and o["status"] in OFFER_COMMITTED_STATUSES
    )
    if case["compensation_committed_cents"] != committed:
        case["compensation_committed_cents"] = committed
        changed = True
    balance = case["acquisition_budget_cents"] - committed
    if case["compensation_balance_cents"] != balance:
        case["compensation_balance_cents"] = balance
        changed = True

    open_count = sum(
        1
        for e in db.encroachments.values()
        if e["case_id"] == cid and e["status"] not in ENCROACHMENT_TERMINAL
    )
    if case["open_encroachment_count"] != open_count:
        case["open_encroachment_count"] = open_count
        changed = True

    pressure = calculations.encroachment_pressure_score(cid)
    if case["encroachment_pressure_score"] != pressure:
        case["encroachment_pressure_score"] = pressure
        changed = True

    cleared = calculations.title_cleared(cid)
    if case["title_cleared"] != cleared:
        case["title_cleared"] = cleared
        changed = True

    active_permits = sum(
        1
        for p in db.permits.values()
        if p["case_id"] == cid
        and p["approval_status"] == "APPROVED"
        and p["field_inspection_status"] != "FAILED"
    )
    if case["active_permit_count"] != active_permits:
        case["active_permit_count"] = active_permits
        changed = True

    # Automatic state movement in both directions (PRD 2.4).
    if case["status"] == "ACTIVE_MONITORING" and open_count > 0:
        case["status"] = "RESOLUTION_PENDING"
        changed = True
    elif case["status"] == "RESOLUTION_PENDING" and open_count == 0:
        case["status"] = "ACTIVE_MONITORING"
        changed = True

    if changed or bump:
        db.touch(case)


# ---------------------------------------------------------------------------
# Vegetation zone reconciliation (PRD 3.6)
# ---------------------------------------------------------------------------

def reconcile_zone(zone: dict) -> None:
    zid = zone["id"]
    open_violations = [
        v for v in db.violations.values()
        if v["zone_id"] == zid and v["status"] in VIOLATION_OPEN_STATUSES
    ]
    total = sum(1 for v in db.violations.values() if v["zone_id"] == zid)
    count = len(open_violations)
    zone["violation_count"] = count

    if count == 0:
        # All violations terminal -> CLEARED (a never-violated zone stays in
        # ACTIVE_MONITORING).
        if total > 0 and zone["status"] != "CLEARED":
            zone["status"] = "CLEARED"
    elif count >= VIOLATION_REMEDIATION_THRESHOLD:
        if zone["status"] != "REMEDIATION_REQUIRED":
            zone["status"] = "REMEDIATION_REQUIRED"
            # Every open violation gets its remediation_deadline set/refreshed.
            deadline = db.fmt_dt(db.get_clock_dt() + timedelta(days=REMEDIATION_WINDOW_DAYS))
            for v in open_violations:
                v["remediation_deadline"] = deadline
                db.touch(v)
    else:
        if zone["status"] != "VIOLATION_DETECTED":
            zone["status"] = "VIOLATION_DETECTED"


# ---------------------------------------------------------------------------
# Litigation referral auto-creation
# ---------------------------------------------------------------------------

def auto_referral(case: dict, reason: str, encroachment_id=None, violation_id=None,
                  offer_id=None) -> dict:
    ref = {
        "case_id": case["id"],
        "encroachment_id": encroachment_id,
        "referral_reason": reason,
        "referred_by": "system",
        "accepted_by": None,
        "filing_deadline": None,
        "status": "REFERRED",
        "_violation_id": violation_id,
        "_offer_id": offer_id,
    }
    db.stamp_new(ref)
    db.referrals[ref["id"]] = ref
    return ref


# ---------------------------------------------------------------------------
# Deadline-driven automation sweep (PRD 2.10). Runs on clock advance and
# lazily at the start of every request.
# ---------------------------------------------------------------------------

def sweep_deadlines() -> None:
    now = db.get_clock_dt()

    # Offers: TENDERED/COUNTERED past negotiation_deadline -> EXPIRED
    for offer in list(db.offers.values()):
        if offer["status"] not in ("TENDERED", "COUNTERED"):
            continue
        deadline = parse_ts_stored(offer.get("negotiation_deadline"))
        if deadline is None or now <= deadline:
            continue
        case = db.cases.get(offer["case_id"])
        if case is not None and case["status"] in CASE_TERMINAL:
            continue
        offer["status"] = "EXPIRED"
        db.touch(offer)
        if case is not None:
            reconcile_case(case, bump=True)

    # Encroachments: NOTIFIED past owner_response_due_date -> ESCALATED_TO_LEGAL
    for enc in list(db.encroachments.values()):
        if enc["status"] != "NOTIFIED":
            continue
        due = parse_ts_stored(enc.get("owner_response_due_date"))
        if due is None or now <= due:
            continue
        case = db.cases.get(enc["case_id"])
        if case is not None and case["status"] in CASE_TERMINAL:
            continue
        enc["status"] = "ESCALATED_TO_LEGAL"
        db.touch(enc)
        if case is not None:
            auto_referral(case, "NEGOTIATION_FAILED", encroachment_id=enc["id"])
            reconcile_case(case, bump=True)

    # Vegetation violations: NOTIFIED past remediation_deadline -> ESCALATED_TO_LEGAL
    for viol in list(db.violations.values()):
        if viol["status"] != "NOTIFIED":
            continue
        deadline = parse_ts_stored(viol.get("remediation_deadline"))
        if deadline is None or now <= deadline:
            continue
        case = db.cases.get(viol["case_id"])
        if case is not None and case["status"] in CASE_TERMINAL:
            continue
        viol["status"] = "ESCALATED_TO_LEGAL"
        db.touch(viol)
        zone = db.zones.get(viol["zone_id"])
        if zone is not None:
            reconcile_zone(zone)
            db.touch(zone)
        if case is not None:
            auto_referral(case, "VEGETATION_REMEDIATION_FAILED", violation_id=viol["id"])
