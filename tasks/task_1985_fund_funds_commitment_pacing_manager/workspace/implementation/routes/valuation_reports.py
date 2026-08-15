"""ValuationReport endpoints: create, publish (NAV/IRR/fee computations)."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_QUARTER,
    ERR_NO_SNAPSHOTS, ERR_POSTURE_GATED,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from validate import body, req_quarter

bp = Blueprint("valuation_reports", __name__)


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


def get_report_or_404(pid, rid):
    r = STORE.valuation_reports.get(rid)
    if r is None or r["program_id"] != pid:
        raise_err(ERR_NOT_FOUND, "valuation report id does not exist")
    return r


@bp.route("/fof/programs/<pid>/valuation-reports", methods=["POST"])
def create_report(pid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    data = body()
    quarter = req_quarter(data, "as_of_quarter")
    for r in STORE.valuation_reports.values():
        if r["program_id"] == pid and r["as_of_quarter"] == quarter:
            raise_err(ERR_DUPLICATE_QUARTER,
                      "a report for this quarter already exists")
    r = new_entity(STORE.valuation_reports, {
        "program_id": pid,
        "as_of_quarter": quarter,
        "nav_provisional": None,
        "nav_final": None,
        "nav_reported": None,
        "irr_provisional_pct": None,
        "irr_final_pct": None,
        "total_fee_burden_pct": None,
        "status": "OPEN",
    })
    return ok(public(r), status=201)


@bp.route("/fof/programs/<pid>/valuation-reports", methods=["GET"])
def list_reports(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    rows = [r for r in STORE.valuation_reports.values()
            if r["program_id"] == pid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/programs/<pid>/valuation-reports/<rid>", methods=["GET"])
def get_report(pid, rid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    return ok(public(get_report_or_404(pid, rid)))


@bp.route("/fof/programs/<pid>/valuation-reports/<rid>/publish", methods=["POST"])
def publish_report(pid, rid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    r = get_report_or_404(pid, rid)
    if r["status"] not in ("OPEN", "RESTATED"):
        raise_err(ERR_INVALID_STATE, "report is not OPEN or RESTATED")
    quarter = r["as_of_quarter"]
    has_snapshot = any(
        s["as_of_quarter"] == quarter and s["status"] != "RESTATED"
        and (STORE.commitments.get(s["commitment_id"]) or {}).get("program_id") == pid
        for s in STORE.snapshots.values())
    if not has_snapshot:
        raise_err(ERR_NO_SNAPSHOTS,
                  "at least one snapshot is required for the quarter")
    nav_prov, nav_final, nav_reported = domain.nav_rollup(prog, quarter)
    irr_p, irr_f = domain.irr_dual(prog, quarter, nav_prov, nav_final)
    r["nav_provisional"] = nav_prov
    r["nav_final"] = nav_final
    r["nav_reported"] = nav_reported
    r["irr_provisional_pct"] = irr_p
    r["irr_final_pct"] = irr_f
    r["total_fee_burden_pct"] = domain.fee_layering(prog, quarter, nav_reported)
    r["status"] = "PUBLISHED"
    touch(r)
    return ok(public(r))
