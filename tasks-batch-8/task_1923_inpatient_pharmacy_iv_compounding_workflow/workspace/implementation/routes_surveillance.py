"""Discrepancy resolution and diversion surveillance (PRD Section 3.7)."""

from flask import Blueprint, request

import db
import validate as V
import calc
import ops
from auth import authenticate
from errors import err_not_found, err_invalid_state, err_invalid_request
from response import ok, ok_list, serialize, paginate

bp = Blueprint("surveillance", __name__)

CASE_READERS = ["PharmacyAdmin", "Pharmacist", "DiversionOfficer"]
DIVERSION_READERS = ["PharmacyAdmin", "DiversionOfficer"]
OFFICER = ["DiversionOfficer"]


def _get_case(cid):
    case = db.discrepancies.get(cid)
    if case is None:
        raise err_not_found("Discrepancy case not found")
    return case


@bp.get("/pharmacy/discrepancy-cases/<cid>")
def get_discrepancy_case(cid):
    authenticate(CASE_READERS)
    return ok(serialize(_get_case(cid)))


@bp.get("/pharmacy/discrepancy-cases")
def list_discrepancy_cases():
    authenticate(CASE_READERS)
    items = list(db.discrepancies.values())
    for param in ("pocket_id", "status", "resolved_by_staff_id"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.post("/pharmacy/discrepancy-cases/<cid>/investigate")
def investigate_case(cid):
    authenticate(["Pharmacist"])
    V.body()
    case = _get_case(cid)
    if case["status"] != "OPEN":
        raise err_invalid_state("Discrepancy case is not OPEN")
    case["status"] = "INVESTIGATING"
    db.touch(case)
    return ok(serialize(case))


@bp.post("/pharmacy/discrepancy-cases/<cid>/resolve")
def resolve_case(cid):
    uid, _, _ = authenticate(["Pharmacist"])
    d = V.body()
    resolution = V.req_enum(d, "resolution", {"FOUND_ERROR", "UNRESOLVED_ESCALATE"})
    adjustment_units = V.opt_int(d, "adjustment_units")
    subject_staff_id = V.opt_str(d, "subject_staff_id")
    case = _get_case(cid)
    if subject_staff_id is not None and subject_staff_id not in db.staff:
        raise err_not_found("Subject staff member not found")
    if case["status"] != "INVESTIGATING":
        raise err_invalid_state("Discrepancy case is not INVESTIGATING")

    if resolution == "FOUND_ERROR":
        if adjustment_units is None or adjustment_units == 0:
            raise err_invalid_request("adjustment_units is required and must be non-zero")
        pocket = db.pockets[case["pocket_id"]]
        ops.append_event(pocket, "ADJUSTMENT", adjustment_units, uid)
        db.touch(pocket)
        case["adjustment_units"] = adjustment_units
        case["resolution"] = "FOUND_ERROR"
        case["resolved_by_staff_id"] = uid
        case["status"] = "RESOLVED"
        db.touch(case)
        return ok(serialize(case))

    # UNRESOLVED_ESCALATE: auto-open a diversion case.
    if subject_staff_id is None:
        raise err_invalid_request("subject_staff_id is required for UNRESOLVED_ESCALATE")
    pocket = db.pockets[case["pocket_id"]]
    diversion = db.base_fields()
    diversion.update({
        "station_id": pocket["station_id"],
        "subject_staff_id": subject_staff_id,
        "source_discrepancy_case_id": case["id"],
        "reason": f"Escalated from discrepancy case {case['id']}",
        "status": "OPEN",
        "outcome_note": None,
        "opened_via": "ESCALATION",
    })
    db.diversions[diversion["id"]] = diversion
    case["resolution"] = "UNRESOLVED_ESCALATE"
    case["resolved_by_staff_id"] = uid
    case["status"] = "ESCALATED"
    db.touch(case)
    return ok(serialize(case))


# ---------------------------------------------------------------------------
# Diversion cases
# ---------------------------------------------------------------------------

def _get_diversion(did):
    case = db.diversions.get(did)
    if case is None:
        raise err_not_found("Diversion case not found")
    return case


@bp.post("/pharmacy/diversion-cases")
def create_diversion_case():
    authenticate(OFFICER)
    d = V.body()
    station_id = V.req_str(d, "station_id")
    subject_staff_id = V.req_str(d, "subject_staff_id")
    reason = V.req_str(d, "reason")
    source_discrepancy_case_id = V.opt_str(d, "source_discrepancy_case_id")
    if station_id not in db.stations:
        raise err_not_found("ADC station not found")
    if subject_staff_id not in db.staff:
        raise err_not_found("Subject staff member not found")
    if source_discrepancy_case_id is not None and source_discrepancy_case_id not in db.discrepancies:
        raise err_not_found("Source discrepancy case not found")
    case = db.base_fields()
    case.update({
        "station_id": station_id,
        "subject_staff_id": subject_staff_id,
        "source_discrepancy_case_id": source_discrepancy_case_id,
        "reason": reason,
        "status": "OPEN",
        "outcome_note": None,
        "opened_via": "ESCALATION" if source_discrepancy_case_id else "MANUAL",
    })
    db.diversions[case["id"]] = case
    return ok(serialize(case), 201)


@bp.get("/pharmacy/diversion-cases/<did>")
def get_diversion_case(did):
    authenticate(DIVERSION_READERS)
    return ok(serialize(_get_diversion(did)))


@bp.get("/pharmacy/diversion-cases")
def list_diversion_cases():
    authenticate(DIVERSION_READERS)
    items = list(db.diversions.values())
    for param in ("station_id", "subject_staff_id", "status",
                  "source_discrepancy_case_id"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.post("/pharmacy/diversion-cases/<did>/review")
def review_diversion_case(did):
    authenticate(OFFICER)
    V.body()
    case = _get_diversion(did)
    if case["status"] != "OPEN":
        raise err_invalid_state("Diversion case is not OPEN")
    case["status"] = "UNDER_REVIEW"
    db.touch(case)
    return ok(serialize(case))


@bp.post("/pharmacy/diversion-cases/<did>/adjudicate")
def adjudicate_diversion_case(did):
    authenticate(OFFICER)
    d = V.body()
    outcome = V.req_enum(d, "outcome", {"SUBSTANTIATED", "CLOSED_UNSUBSTANTIATED"})
    note = V.req_str(d, "note")
    case = _get_diversion(did)
    if case["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Diversion case is not UNDER_REVIEW")
    case["status"] = outcome
    case["outcome_note"] = note
    db.touch(case)
    return ok(serialize(case))


@bp.post("/pharmacy/diversion-risk/evaluate")
def evaluate_diversion_risk():
    authenticate(OFFICER)
    d = V.body()
    station_id = V.req_str(d, "station_id")
    subject_staff_id = V.req_str(d, "subject_staff_id")
    drug_product_id = V.req_str(d, "drug_product_id")
    if station_id not in db.stations:
        raise err_not_found("ADC station not found")
    if subject_staff_id not in db.staff:
        raise err_not_found("Subject staff member not found")
    drug = db.drugs.get(drug_product_id)
    if drug is None:
        raise err_not_found("Drug product not found")

    score, tier, window_count = calc.diversion_risk_score(
        station_id, subject_staff_id, drug
    )
    diversion_case_id = None
    if tier == "OPEN_CASE":
        case = db.base_fields()
        case.update({
            "station_id": station_id,
            "subject_staff_id": subject_staff_id,
            "source_discrepancy_case_id": None,
            "reason": "Auto-created by diversion risk evaluation",
            "status": "OPEN",
            "outcome_note": None,
            "opened_via": "RISK_SCORE",
        })
        db.diversions[case["id"]] = case
        diversion_case_id = case["id"]
    return ok({
        "score": score,
        "tier": tier,
        "window_event_count": window_count,
        "diversion_case_id": diversion_case_id,
    })
