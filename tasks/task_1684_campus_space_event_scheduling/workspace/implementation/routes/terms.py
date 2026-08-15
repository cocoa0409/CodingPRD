"""Term windows (PRD 3.3)."""

import db
import serializers
from middleware import endpoint
from routes.common import one
from validate import get_term, req_dt, req_str

ALL_READ_ROLES = ["Scheduler", "FacilitiesManager", "ServiceCoordinator", "FinanceAdmin", "OrgRequester"]


@endpoint("POST", "/campus/terms", roles=["Scheduler"], code=201)
def create_term(ctx):
    body = ctx.body
    name = req_str(body, "name")
    start_raw, start_dt = req_dt(body, "term_start_date")
    end_raw, end_dt = req_dt(body, "term_end_date")
    priority_raw, priority_dt = req_dt(body, "priority_open_at")
    general_raw, general_dt = req_dt(body, "general_open_at")
    row = db.new_row(
        db.terms,
        name=name,
        term_start_date=start_raw,
        term_end_date=end_raw,
        priority_open_at=priority_raw,
        general_open_at=general_raw,
        status="DRAFT",
        current_draft_run_id=None,
        _term_start=start_dt,
        _term_end=end_dt,
        _priority_open=priority_dt,
        _general_open=general_dt,
    )
    return one(serializers.term(row), status=201)


@endpoint("GET", "/campus/terms/{id}", roles=ALL_READ_ROLES, code=200)
def get_term_detail(ctx):
    return one(serializers.term(get_term(ctx.id)))
