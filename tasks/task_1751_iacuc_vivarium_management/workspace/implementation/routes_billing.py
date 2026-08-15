"""Per-diem billing runs and charge listings (PRD §3.7)."""
from flask import Blueprint

from db import STORE, new_rec
from domain import (
    budget_remaining,
    compute_charge_for_cage,
    day_start,
    ser_billing_run,
    ser_charge,
)
from envelope import get_body, list_response, ok_obj
from errors import (
    ApiError,
    ERR_CENSUS_DISCREPANCY,
    ERR_GRANT_INSOLVENT,
    ERR_STALE_VERSION,
    invalid_request,
    invalid_state,
)
from routes_admin import fetch
from validation import authenticate, require_role, req_dt, req_int

bp = Blueprint("billing", __name__)


@bp.post("/iacuc/billing-runs")
def create_billing_run():
    uid, role = authenticate()
    require_role(role, "BillingCoordinator")
    body = get_body()
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end <= period_start:
        raise invalid_request("period_end must fall after period_start")
    r = new_rec(
        "billing_runs",
        period_start=period_start,
        period_end=period_end,
        state="DRAFT",
        hold_reason=None,
    )
    return ok_obj(ser_billing_run(r), 201)


@bp.get("/iacuc/billing-runs/<rid>")
def get_billing_run(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator", "IacucAdministrator")
    return ok_obj(ser_billing_run(fetch("billing_runs", rid)))


@bp.get("/iacuc/billing-runs/<rid>/charges")
def list_run_charges(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator", "IacucAdministrator")
    fetch("billing_runs", rid)
    rows = [c for c in STORE["per_diem_charges"].values() if c.billing_run_id == rid]
    return list_response(rows, ser_charge)


@bp.get("/iacuc/grants/<rid>/charges")
def list_grant_charges(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator", "IacucAdministrator")
    fetch("grants", rid)
    rows = [c for c in STORE["per_diem_charges"].values() if c.grant_id == rid]
    return list_response(rows, ser_charge)


@bp.get("/iacuc/cages/<rid>/charges")
def list_cage_charges(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator", "IacucAdministrator")
    fetch("cages", rid)
    rows = [c for c in STORE["per_diem_charges"].values() if c.cage_id == rid]
    return list_response(rows, ser_charge)


@bp.get("/iacuc/protocols/<rid>/charges")
def list_protocol_charges(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator", "IacucAdministrator")
    fetch("protocols", rid)
    rows = [c for c in STORE["per_diem_charges"].values() if c.protocol_id == rid]
    return list_response(rows, ser_charge)


def _census_hold(run):
    """Any census record inside the period with discrepancy != 0 holds the run."""
    ps = day_start(run.period_start)
    pe = day_start(run.period_end)
    for c in STORE["census_records"].values():
        if ps <= day_start(c.census_date) < pe and c.discrepancy != 0:
            return c
    return None


def _create_charges(run, variant):
    for cage in STORE["cages"].values():
        if cage.status == "DECOMMISSIONED":
            continue
        result = compute_charge_for_cage(
            cage, run.period_start, run.period_end, variant
        )
        if result is None:
            continue
        protocol = STORE["protocols"].get(cage.protocol_id)
        grant_id = protocol.grant_id if protocol is not None else None
        new_rec(
            "per_diem_charges",
            billing_run_id=run.id,
            cage_id=cage.id,
            protocol_id=cage.protocol_id,
            grant_id=grant_id,
            cage_days=result["cage_days"],
            rate_cents=result["rate_cents"],
            amount_cents=result["amount_cents"],
            variant=variant,
        )


@bp.post("/iacuc/billing-runs/<rid>/compute-provisional")
def compute_provisional(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator")
    run = fetch("billing_runs", rid)
    if run.state != "DRAFT":
        raise invalid_state("BillingRun is not DRAFT")
    hold = _census_hold(run)
    if hold is not None:
        run.hold_reason = (
            f"Census discrepancy of {hold.discrepancy} on cage {hold.cage_id} "
            f"for {day_start(hold.census_date).date().isoformat()}"
        )
        run.touch()
        raise ApiError(
            ERR_CENSUS_DISCREPANCY, 422,
            "A census record in the period carries a nonzero discrepancy",
        )
    _create_charges(run, "PROVISIONAL")
    run.state = "PROVISIONAL"
    run.touch()
    return ok_obj(ser_billing_run(run))


@bp.post("/iacuc/billing-runs/<rid>/finalize")
def finalize_run(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator")
    body = get_body()
    expected = req_int(body, "expected_billing_run_version")
    run = fetch("billing_runs", rid)
    if run.state != "PROVISIONAL":
        raise invalid_state("BillingRun is not PROVISIONAL")
    if expected != run.version:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_billing_run_version does not match the current version",
        )
    # Replace provisional rows with FINAL rows (reconciled-census model).
    for cid in [
        c.id
        for c in STORE["per_diem_charges"].values()
        if c.billing_run_id == run.id and c.variant == "PROVISIONAL"
    ]:
        del STORE["per_diem_charges"][cid]
    _create_charges(run, "FINAL")
    run.state = "FINALIZED"
    run.touch()
    return ok_obj(ser_billing_run(run))


@bp.post("/iacuc/billing-runs/<rid>/post")
def post_run(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator")
    run = fetch("billing_runs", rid)
    if run.state != "FINALIZED":
        raise invalid_state("BillingRun is not FINALIZED")
    # Solvency gate: per grant, the sum of its charges must fit the remaining
    # budget, and the grant must not expire before period_end (atomic check).
    per_grant = {}
    for c in STORE["per_diem_charges"].values():
        if c.billing_run_id == run.id:
            per_grant[c.grant_id] = per_grant.get(c.grant_id, 0) + c.amount_cents
    for grant_id, total in per_grant.items():
        grant = STORE["grants"].get(grant_id)
        if grant is None:
            continue
        if total > budget_remaining(grant) or grant.expires_on < run.period_end:
            raise ApiError(
                ERR_GRANT_INSOLVENT, 402,
                "Posting would exceed grant budget or the grant expired before "
                "period_end",
            )
    run.state = "POSTED"
    run.touch()
    return ok_obj(ser_billing_run(run))


@bp.post("/iacuc/billing-runs/<rid>/void")
def void_run(rid):
    uid, role = authenticate()
    require_role(role, "BillingCoordinator")
    run = fetch("billing_runs", rid)
    if run.state not in ("DRAFT", "PROVISIONAL"):
        raise invalid_state("Only a DRAFT or PROVISIONAL run may be voided")
    if run.state == "PROVISIONAL":
        for cid in [
            c.id
            for c in STORE["per_diem_charges"].values()
            if c.billing_run_id == run.id and c.variant == "PROVISIONAL"
        ]:
            del STORE["per_diem_charges"][cid]
    run.state = "VOIDED"
    run.touch()
    return ok_obj(ser_billing_run(run))
