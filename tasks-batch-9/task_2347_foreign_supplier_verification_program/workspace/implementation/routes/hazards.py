"""HazardAnalysis and Hazard."""
from flask import Blueprint, g

import core
import serialize
from core import write_txn
from db import store
from errors import fail
from middleware import CO, FDA, QI, endpoint
from response import object_response
from routes._common import acting_qi, find, paged, require_qi_current
from shapes import (
    body,
    pagination,
    query_bool,
    query_enum,
    query_str,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("hazards", __name__)


@bp.post("/fsvp/hazard-analyses")
@endpoint([QI])
def create_analysis():
    b = body()
    pair_id = req_str(b, "pair_id")
    expected_pair_version = req_int(b, "expected_pair_version", lo=0)
    methodology_note = req_str(b, "methodology_note")

    pair = find("pair", pair_id, "ERR_PAIR_NOT_FOUND")

    # rung 14
    author = acting_qi()
    if author is not None and author["importer_id"] != pair["importer_id"]:
        fail("ERR_IMPORTER_SCOPE_MISMATCH", "the pair belongs to a different importer")

    # rung 17
    if expected_pair_version != pair["version"]:
        fail("ERR_STALE_PAIR_VERSION", "expected_pair_version does not match the pair's version")

    # rung 26
    require_qi_current(author)

    # rung 42
    if len(methodology_note) < 20:
        fail("ERR_JUSTIFICATION_INSUFFICIENT", "methodology_note must be at least 20 characters")

    with write_txn():
        for existing in core.sort_rows(core.analyses_of_pair(pair["id"])):
            if existing["status"] == "DRAFT":
                existing["status"] = "WITHDRAWN"
                store.touch(existing)
        row = store.new_row("analysis")
        row.update(
            {
                "pair_id": pair_id,
                "authored_by_qi_id": g.user_id,
                "methodology_note": methodology_note,
                "pair_version_at_create": expected_pair_version,
                "status": "DRAFT",
                "approved_at": None,
            }
        )
        store.insert(row)
        store.touch(pair)
    return object_response(serialize.analysis_out(row), 201)


@bp.get("/fsvp/hazard-analyses/<analysis_id>")
@endpoint([CO, QI, FDA])
def read_analysis(analysis_id):
    row = find("analysis", analysis_id, "ERR_HAZARD_ANALYSIS_NOT_FOUND")
    return object_response(serialize.analysis_out(row))


@bp.get("/fsvp/hazard-analyses")
@endpoint([CO, QI, FDA])
def list_analyses():
    pair_id = query_str("pair_id")
    author_id = query_str("authored_by_qi_id")
    status = query_enum("status", core.ANALYSIS_STATUSES)
    limit, offset = pagination()

    rows = list(store.analyses.values())
    if pair_id is not None:
        rows = [r for r in rows if r["pair_id"] == pair_id]
    if author_id is not None:
        rows = [r for r in rows if r["authored_by_qi_id"] == author_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, serialize.analysis_out, limit, offset)


@bp.post("/fsvp/hazard-analyses/<analysis_id>/hazards")
@endpoint([QI])
def create_hazard(analysis_id):
    b = body()
    hazard_type = req_enum(b, "hazard_type", core.HAZARD_TYPES)
    hazard_name = req_str(b, "hazard_name", minlen=1)
    severity = req_int(b, "severity", lo=1, hi=5)
    probability = req_int(b, "probability", lo=1, hi=5)
    control_owner = req_enum(b, "control_owner", core.CONTROL_OWNERS)

    analysis = find("analysis", analysis_id, "ERR_HAZARD_ANALYSIS_NOT_FOUND")

    # rung 22
    if analysis["status"] != "DRAFT":
        fail("ERR_ANALYSIS_NOT_DRAFT", "hazards may only be added to a draft analysis")

    # rung 26
    require_qi_current()

    pair = store.pairs.get(analysis["pair_id"])
    food = core.food_of_pair(pair) if pair else None
    if food is None:
        fail("ERR_PAIR_NOT_FOUND")

    risk_score, requires_control = core.compute_hazard_risk(
        food, hazard_type, severity, probability, control_owner
    )

    with write_txn():
        row = store.new_row("hazard", versioned=False)
        row.update(
            {
                "hazard_analysis_id": analysis_id,
                "hazard_type": hazard_type,
                "hazard_name": hazard_name,
                "severity": severity,
                "probability": probability,
                "control_owner": control_owner,
                "risk_score": risk_score,
                "requires_control": requires_control,
            }
        )
        store.insert(row)
    return object_response(serialize.hazard_out(row), 201)


@bp.get("/fsvp/hazard-analyses/<analysis_id>/hazards")
@endpoint([CO, QI, FDA])
def list_hazards(analysis_id):
    hazard_type = query_enum("hazard_type", core.HAZARD_TYPES)
    requires_control = query_bool("requires_control")
    limit, offset = pagination()

    analysis = find("analysis", analysis_id, "ERR_HAZARD_ANALYSIS_NOT_FOUND")
    rows = core.hazards_of_analysis(analysis["id"])
    if hazard_type is not None:
        rows = [r for r in rows if r["hazard_type"] == hazard_type]
    if requires_control is not None:
        rows = [r for r in rows if r["requires_control"] == requires_control]
    return paged(rows, serialize.hazard_out, limit, offset)


@bp.post("/fsvp/hazard-analyses/<analysis_id>/approval")
@endpoint([QI])
def approve_analysis(analysis_id):
    b = body()
    req_str(b, "approval_note", minlen=1)

    analysis = find("analysis", analysis_id, "ERR_HAZARD_ANALYSIS_NOT_FOUND")

    # rung 22
    if analysis["status"] != "DRAFT":
        fail("ERR_ANALYSIS_NOT_DRAFT", "only a draft analysis can be approved")

    # rung 26
    require_qi_current()

    # rung 30
    if core.analysis_hazard_count(analysis) < 1:
        fail("ERR_HAZARD_ANALYSIS_EMPTY", "the analysis documents no hazard")

    pair = store.pairs.get(analysis["pair_id"])

    with write_txn():
        if pair is not None:
            for other in core.sort_rows(core.analyses_of_pair(pair["id"])):
                if other["id"] != analysis["id"] and other["status"] == "APPROVED":
                    other["status"] = "SUPERSEDED"
                    store.touch(other)
        analysis["status"] = "APPROVED"
        analysis["approved_at"] = core.clock()
        store.touch(analysis)
        if pair is not None:
            pair["active_hazard_analysis_id"] = analysis["id"]
            if pair["verification_status"] in ("DRAFT", "HAZARD_ANALYZED"):
                pair["verification_status"] = "HAZARD_ANALYZED"
            store.touch(pair)
    return object_response(serialize.analysis_out(analysis))
