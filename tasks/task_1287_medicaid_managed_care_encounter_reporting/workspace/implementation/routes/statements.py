"""CapitationStatement + RiskScoreSnapshot + ProviderScorecard routes."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store, new_id, now_iso
from middleware import get_auth, require_role, get_body, req_string, apply_pagination
from response import success_object, success_list
from errors import not_found, invalid_request, invalid_state, ApiError
from services.core import touch, round0, enrolled_overlapping_members
from routes.cycles import snapshot_view

bp = Blueprint("statements", __name__)

WITHHOLD_PERCENT = Decimal("0.05")


def statement_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "cycle_id": s["cycle_id"],
        "member_months": s["member_months"],
        "provisional_paid_cents": s["provisional_paid_cents"],
        "final_amount_cents": s["final_amount_cents"],
        "adjustment_cents": s["adjustment_cents"],
        "withhold_applied": s["withhold_applied"],
        "status": s["status"],
    }


def _find_rate(program_id, aid_category, window_start_date):
    """Find the schedule of (program, aid_category) whose CLOSED window contains the date."""
    for s in store.rate_schedules.values():
        if s["program_id"] != program_id or s["aid_category"] != aid_category:
            continue
        if s["_effective_from"] <= window_start_date <= s["_effective_to"]:
            return s
    return None


def _member_rate_map(cycle):
    """Map member_id -> pmpm_cents for enrolled-overlapping members. Raises ERR_RATE_NOT_FOUND."""
    members = enrolled_overlapping_members(cycle["program_id"], cycle["_window_start_at"], cycle["_window_end_at"])
    ws_date = cycle["_window_start_at"].date()
    rate_map = {}
    # rate coverage first: every aid_category with >= 1 enrolled-overlapping member must have coverage
    categories = {m["aid_category"] for m in members}
    for cat in categories:
        if _find_rate(cycle["program_id"], cat, ws_date) is None:
            raise ApiError("ERR_RATE_NOT_FOUND",
                           "No rate schedule covers the cycle window start for an enrolled member's aid_category",
                           422)
    for m in members:
        sched = _find_rate(cycle["program_id"], m["aid_category"], ws_date)
        rate_map[m["id"]] = sched["pmpm_cents"]
    return members, rate_map


@bp.route("/programs/capitation-statements", methods=["POST"])
def create_statement():
    _, role = get_auth()
    require_role(role, {"McoFinance"})
    body = get_body()
    cycle_id = req_string(body, "cycle_id")
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise not_found("cycle not found")
    # rate coverage first, then one-statement-per-cycle
    members, rate_map = _member_rate_map(cycle)
    for s in store.statements.values():
        if s["cycle_id"] == cycle_id:
            raise ApiError("ERR_STATEMENT_EXISTS", "A capitation statement already exists for the cycle", 409)
    member_months = len(members)
    # provisional: risk 1.0 per member => line = round_half_up(pmpm * 1.0) = pmpm
    provisional = 0
    for m in members:
        line = round0(Decimal(rate_map[m["id"]]) * Decimal("1.0"))
        provisional += line
    sid = new_id()
    s = {
        "id": sid,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "cycle_id": cycle_id,
        "member_months": member_months,
        "provisional_paid_cents": provisional,
        "final_amount_cents": None,
        "adjustment_cents": None,
        "withhold_applied": False,
        "status": "PROVISIONAL_ISSUED",
    }
    store.statements[sid] = s
    return success_object(statement_view(s), 201)


@bp.route("/programs/capitation-statements/<sid>", methods=["GET"])
def get_statement(sid):
    get_auth()
    s = store.statements.get(sid)
    if s is None:
        raise not_found()
    return success_object(statement_view(s))


@bp.route("/programs/capitation-statements", methods=["GET"])
def list_statements():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    status = request.args.get("status")
    items = list(store.statements.values())
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([statement_view(s) for s in page], limit, offset, total)


@bp.route("/programs/capitation-statements/<sid>/reconcile", methods=["POST"])
def reconcile_statement(sid):
    _, role = get_auth()
    require_role(role, {"McoFinance"})
    get_body(required=False)
    s = store.statements.get(sid)
    if s is None:
        raise not_found()
    if s["status"] != "PROVISIONAL_ISSUED":
        raise invalid_state("Statement is not PROVISIONAL_ISSUED")
    cycle = store.cycles.get(s["cycle_id"])
    if cycle is None:
        raise not_found("cycle not found")
    if cycle["risk_computed_at"] is None:
        raise ApiError("ERR_SNAPSHOTS_REQUIRED",
                       "Statement reconcile requires compute-risk-scores to have run for the cycle", 409)

    members, rate_map = _member_rate_map(cycle)
    snapshots = {snap["member_id"]: snap for snap in store.risk_snapshots.values()
                 if snap["cycle_id"] == cycle["id"]}

    # pinned rounding: per-member round first, then sum
    subtotal = 0
    for m in members:
        snap = snapshots.get(m["id"])
        risk = Decimal(str(snap["normalized_score"])) if snap is not None else Decimal("0")
        line = round0(Decimal(rate_map[m["id"]]) * risk)
        subtotal += line

    # withhold gate: audit determination FAIL
    audit = None
    for a in store.audits.values():
        if a["cycle_id"] == cycle["id"]:
            audit = a
            break
    withhold_applied = False
    if audit is not None and audit["determination"] == "FAIL":
        final = round0(Decimal(subtotal) * (Decimal(1) - WITHHOLD_PERCENT))
        withhold_applied = True
    else:
        final = subtotal

    s["final_amount_cents"] = final
    s["adjustment_cents"] = final - s["provisional_paid_cents"]
    s["withhold_applied"] = withhold_applied
    s["status"] = "RECONCILED"
    touch(s)

    # snapshots -> APPLIED
    for snap in snapshots.values():
        snap["status"] = "APPLIED"
        touch(snap)

    return success_object(statement_view(s))


# ------------------------------------------------------------ risk snapshots ---

@bp.route("/programs/risk-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    get_auth()
    s = store.risk_snapshots.get(sid)
    if s is None:
        raise not_found()
    return success_object(snapshot_view(s))


@bp.route("/programs/risk-snapshots", methods=["GET"])
def list_snapshots():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = list(store.risk_snapshots.values())
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = apply_pagination(items)
    return success_list([snapshot_view(s) for s in page], limit, offset, total)


# ------------------------------------------------------------ scorecards ---

def scorecard_view(sc):
    return {
        "id": sc["id"],
        "created_at": sc["created_at"],
        "updated_at": sc["updated_at"],
        "version": sc["version"],
        "cycle_id": sc["cycle_id"],
        "provider_id": sc["provider_id"],
        "run_count": sc["run_count"],
        "fatal_finding_count": sc["fatal_finding_count"],
        "error_rate": sc["error_rate"],
        "tier": sc["tier"],
        "status": sc["status"],
    }


@bp.route("/programs/scorecards/<scid>", methods=["GET"])
def get_scorecard_route(scid):
    get_auth()
    sc = store.scorecards.get(scid)
    if sc is None:
        raise not_found()
    return success_object(scorecard_view(sc))


@bp.route("/programs/scorecards", methods=["GET"])
def list_scorecards():
    get_auth()
    cycle_id = request.args.get("cycle_id")
    provider_id = request.args.get("provider_id")
    tier = request.args.get("tier")
    items = list(store.scorecards.values())
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    if provider_id is not None:
        items = [s for s in items if s["provider_id"] == provider_id]
    if tier is not None:
        items = [s for s in items if s["tier"] == tier]
    page, limit, offset, total = apply_pagination(items)
    return success_list([scorecard_view(s) for s in page], limit, offset, total)


@bp.route("/programs/scorecards/<scid>/acknowledge-remediation", methods=["POST"])
def acknowledge_remediation(scid):
    _, role = get_auth()
    require_role(role, {"McoEncounterOps"})
    get_body(required=False)
    sc = store.scorecards.get(scid)
    if sc is None:
        raise not_found()
    if not (sc["status"] == "OPEN" and sc["tier"] == "RED"):
        raise invalid_state("Remediation acknowledgment applies only to OPEN scorecards with tier RED")
    sc["status"] = "ACKNOWLEDGED"
    touch(sc)
    return success_object(scorecard_view(sc))
