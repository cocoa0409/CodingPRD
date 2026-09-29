"""Network assessment cycles and adequacy scoring (PRD 3.9)."""
from flask import Blueprint

import clock
import response
import validate as V
from auth import ALL_ROLES, actor, require
from db import new_record, store, touch
from routes.common import ensure_from_state, ensure_not_terminal, get_assessment, get_network
from services import compute as K
from services import serialize as S

bp = Blueprint("assessments", __name__)

ASSESSMENT_TERMINAL = ("APPROVED",)


@bp.post("/network-assessments")
@require("ProgramManager")
def open_assessment():
    data = V.body()
    network_id = V.req_id(data, "network_id")
    cycle_year = V.req_int(data, "cycle_year", lo=2000, hi=2100)
    network = get_network(network_id)
    for row in store.assessments.values():
        if row["network_id"] == network_id and row["cycle_year"] == cycle_year:
            V.bad("An assessment already exists for this network and cycle year.")
    rec = new_record()
    rec.update({
        "network_id": network_id,
        "cycle_year": cycle_year,
        "status": "DRAFT",
        "return_count": 0,
        "submitted_at": None,
        "approved_at": None,
        "approved_by_user_id": None,
    })
    rec.update(K.network_adequacy_score(network))
    store.assessments[rec["id"]] = rec
    return response.object_response(S.assessment(rec), 201)


@bp.post("/network-assessments/<assessment_id>/submit")
@require("ProgramManager")
def submit_assessment(assessment_id):
    data = V.body()
    V.opt_string(data, "submission_note")
    rec = get_assessment(assessment_id)
    ensure_not_terminal(rec["status"], ASSESSMENT_TERMINAL, "network assessment")
    ensure_from_state(rec["status"], ("DRAFT",), "network assessment")
    network = store.networks.get(rec["network_id"])
    if network is not None:
        # Scoring is re-run from the network's present census before submission.
        rec.update(K.network_adequacy_score(network))
    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = clock.now()
    touch(rec)
    if network is not None:
        network["network_status"] = "UNDER_ASSESSMENT"
        network["current_assessment_year"] = rec["cycle_year"]
        touch(network)
    return response.object_response(S.assessment(rec))


@bp.post("/network-assessments/<assessment_id>/decision")
@require("EpaRegionalReviewer")
def decide_assessment(assessment_id):
    data = V.body()
    decision = V.req_enum(data, "decision", ("APPROVE", "RETURN"))
    V.opt_string(data, "decision_note")
    rec = get_assessment(assessment_id)
    ensure_not_terminal(rec["status"], ASSESSMENT_TERMINAL, "network assessment")
    ensure_from_state(rec["status"], ("SUBMITTED",), "network assessment")
    if decision == "APPROVE":
        rec["status"] = "APPROVED"
        rec["approved_at"] = clock.now()
        rec["approved_by_user_id"] = actor()
    else:
        rec["status"] = "DRAFT"
        rec["return_count"] += 1
    touch(rec)
    network = store.networks.get(rec["network_id"])
    if network is not None:
        # Under either decision the network returns to ACTIVE.
        network["network_status"] = "ACTIVE"
        touch(network)
    return response.object_response(S.assessment(rec))


@bp.get("/network-assessments/<assessment_id>")
@require(*ALL_ROLES)
def read_assessment(assessment_id):
    return response.object_response(S.assessment(get_assessment(assessment_id)))
