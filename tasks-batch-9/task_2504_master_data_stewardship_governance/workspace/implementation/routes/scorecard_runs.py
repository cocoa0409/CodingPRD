"""Immutable scorecard-run reads (PRD 3.4)."""

from flask import Blueprint

import db
import response
import validation as v
from auth import endpoint

bp = Blueprint("scorecard_runs", __name__)

BASES = ("PROVISIONAL", "CERTIFIED")
READERS = ("GovernanceAdmin", "DataOwner", "DataSteward", "Auditor")


@bp.get("/mdm/scorecard-runs")
@endpoint(*READERS)
def list_runs():
    limit, offset = v.pagination()
    domain_id = v.str_filter("domain_id")
    basis = v.enum_filter("basis", BASES)

    rows = db.ordered(db.store.scorecard_runs)
    if domain_id is not None:
        rows = [r for r in rows if r["domain_id"] == domain_id]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    return response.collection(rows, limit, offset)


@bp.get("/mdm/scorecard-runs/<run_id>")
@endpoint(*READERS)
def read_run(run_id):
    run = db.resolve(db.store.scorecard_runs, run_id, "ERR_SCORECARD_RUN_NOT_FOUND")
    return response.entity(run)
