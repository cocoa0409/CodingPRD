"""Citation endpoints (PRD §3.8): issue, contest, final order, abatement."""
from flask import Blueprint

from db import STORE, now_dt, now_iso, fmt_iso
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CONTEST_WINDOW_PASSED, ERR_PENALTY_INVALID)
from middleware import get_auth, require_roles, RATES_READ_ROLES
from response import success_object, success_list
from services.core import (get_body, req_str, req_enum, req_number, opt_number,
                           req_date, base_fields, bump, serialize, lookup,
                           paginated, contest_deadline_for,
                           citation_establishment_id, recompute_posture)

bp = Blueprint("citations", __name__)

VIOLATION_TYPES = ("OTHER_THAN_SERIOUS", "SERIOUS", "WILLFUL", "REPEAT",
                   "FAILURE_TO_ABATE")
CONTEST_OUTCOMES = ("AFFIRMED", "MODIFIED", "VACATED")
SO = ("SafetyOfficer",)


@bp.post("/safety/citations")
def create_citation():
    auth = get_auth()
    require_roles(auth, SO)
    data = get_body()
    inspection_id = req_str(data, "inspection_id")
    standard_cited = req_str(data, "standard_cited", non_empty=True)
    violation_type = req_enum(data, "violation_type", VIOLATION_TYPES)
    proposed = req_number(data, "proposed_penalty_usd")
    abatement_due = req_date(data, "abatement_due_date")

    insp = lookup(STORE.inspections, inspection_id)
    if insp["status"] == "CLOSED_NO_CITATION":
        raise_error(ERR_INVALID_STATE,
                    "Inspection is closed; no citations may be added")
    if proposed < 0:
        raise_error(ERR_PENALTY_INVALID,
                    "proposed_penalty_usd must be non-negative")

    citation = base_fields()
    created_dt = now_dt()
    citation.update({
        "inspection_id": inspection_id,
        "standard_cited": standard_cited,
        "violation_type": violation_type,
        "proposed_penalty_usd": proposed,
        "abatement_due_date": abatement_due.isoformat(),
        "status": "ISSUED",
        "contested_at": None,
        "contest_deadline": fmt_iso(contest_deadline_for(created_dt)),
        "final_penalty_usd": None,
        "abated_at": None,
        "_late_abatement": False,
    })
    STORE.citations[citation["id"]] = citation
    # First citation under an inspection moves it OPEN -> CITATIONS_ISSUED.
    if insp["status"] == "OPEN":
        insp["status"] = "CITATIONS_ISSUED"
        bump(insp)
    return success_object(serialize(citation), status=201)


@bp.get("/safety/citations/<citationId>")
def get_citation(citationId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    citation = lookup(STORE.citations, citationId)
    return success_object(serialize(citation))


@bp.post("/safety/citations/<citationId>/contest")
def contest_citation(citationId):
    auth = get_auth()
    require_roles(auth, SO)
    citation = lookup(STORE.citations, citationId)
    if citation["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    from db import parse_datetime
    if now_dt() > parse_datetime(citation["contest_deadline"]):
        raise_error(ERR_CONTEST_WINDOW_PASSED,
                    "Contest attempted after the 15-working-day deadline")
    citation["status"] = "CONTESTED"
    citation["contested_at"] = now_iso()
    bump(citation)
    return success_object(serialize(citation))


@bp.post("/safety/citations/<citationId>/accept-final-order")
def accept_final_order(citationId):
    auth = get_auth()
    require_roles(auth, SO)
    citation = lookup(STORE.citations, citationId)
    if citation["status"] != "ISSUED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    # Available whether or not the contest window has lapsed.
    citation["final_penalty_usd"] = citation["proposed_penalty_usd"]
    # FINAL_ORDER -> ABATEMENT_PENDING happens immediately (system).
    citation["status"] = "ABATEMENT_PENDING"
    bump(citation)
    return success_object(serialize(citation))


@bp.post("/safety/citations/<citationId>/resolve-contest")
def resolve_contest(citationId):
    auth = get_auth()
    require_roles(auth, SO)
    citation = lookup(STORE.citations, citationId)
    data = get_body()
    outcome = req_enum(data, "outcome", CONTEST_OUTCOMES)
    final_penalty = opt_number(data, "final_penalty_usd")
    if citation["status"] != "CONTESTED":
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    if outcome == "MODIFIED":
        if final_penalty is None or final_penalty < 0:
            raise_error(ERR_PENALTY_INVALID,
                        "MODIFIED outcome requires an explicit, non-negative "
                        "final_penalty_usd")
        citation["final_penalty_usd"] = final_penalty
        citation["status"] = "ABATEMENT_PENDING"
    elif outcome == "AFFIRMED":
        citation["final_penalty_usd"] = citation["proposed_penalty_usd"]
        citation["status"] = "ABATEMENT_PENDING"
    else:  # VACATED
        citation["status"] = "VACATED"
        # Linked corrective actions are auto-cancelled.
        for a in STORE.corrective_actions.values():
            if (a.get("citation_id") == citation["id"]
                    and a["status"] not in ("VERIFIED", "CANCELLED")):
                a["status"] = "CANCELLED"
                bump(a)
    bump(citation)
    est_id = citation_establishment_id(citation)
    if outcome == "VACATED" and est_id:
        est = STORE.establishments.get(est_id)
        if est:
            recompute_posture(est)
    return success_object(serialize(citation))


@bp.post("/safety/citations/<citationId>/abate")
def abate_citation(citationId):
    auth = get_auth()
    require_roles(auth, SO)
    citation = lookup(STORE.citations, citationId)
    data = get_body()
    req_str(data, "abatement_evidence", non_empty=True)
    if citation["status"] not in ("ABATEMENT_PENDING", "OVERDUE"):
        raise_error(ERR_INVALID_STATE,
                    "Transition not allowed from current state")
    was_overdue = citation["status"] == "OVERDUE"
    citation["status"] = "ABATED"
    citation["abated_at"] = now_iso()
    if was_overdue:
        # Late abatement records the flag and FAILURE_TO_ABATE exposure on
        # the inspection; linked corrective actions are NOT auto-verified.
        citation["_late_abatement"] = True
        insp = STORE.inspections.get(citation["inspection_id"])
        if insp is not None:
            insp["_failure_to_abate_exposure"] = True
    for a in STORE.corrective_actions.values():
        if a.get("citation_id") == citation["id"]:
            a["_abatement_satisfied"] = True
    bump(citation)
    est_id = citation_establishment_id(citation)
    if est_id:
        est = STORE.establishments.get(est_id)
        if est:
            recompute_posture(est)
    return success_object(serialize(citation))


@bp.get("/safety/citations/<citationId>/corrective-actions")
def list_citation_corrective_actions(citationId):
    auth = get_auth()
    require_roles(auth, RATES_READ_ROLES)
    lookup(STORE.citations, citationId)
    items = [a for a in STORE.corrective_actions.values()
             if a.get("citation_id") == citationId]
    page, limit, offset, total = paginated(items)
    return success_list([serialize(a) for a in page], limit, offset, total)
