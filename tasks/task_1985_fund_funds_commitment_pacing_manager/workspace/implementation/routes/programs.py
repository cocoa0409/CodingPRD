"""FoFProgram endpoints: lifecycle, ledger, forecast, scoped list views."""

from flask import Blueprint

import db
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_BUFFER_BREACH,
    ERR_POSTURE_GATED, ERR_INVALID_REQUEST,
)
from middleware import auth_context, require_role, ALL_ROLES
from response import ok, list_response
from services import domain
from util import dec
from validate import (
    body, req_str, req_enum, req_num, req_positive_num, req_nonneg_num, req_int,
    opt_str,
)

bp = Blueprint("programs", __name__)

CURRENCIES = ["USD", "EUR", "GBP"]
LEDGER_KINDS = ["CONTRIBUTION", "MANUAL_ADJUSTMENT"]


def get_program_or_404(pid):
    prog = STORE.programs.get(pid)
    if prog is None:
        raise_err(ERR_NOT_FOUND, "program id does not exist")
    return prog


@bp.route("/fof/programs", methods=["POST"])
def create_program():
    _, role = auth_context()
    require_role(role, ["CIO"])
    data = body()
    fields = {
        "program_name": req_str(data, "program_name"),
        "base_currency": req_enum(data, "base_currency", CURRENCIES),
        "total_nav_budget": req_positive_num(data, "total_nav_budget"),
        "strategy_cap_pct": req_num(data, "strategy_cap_pct"),
        "manager_cap_pct": req_num(data, "manager_cap_pct"),
        "max_vintage_band_years": req_int(data, "max_vintage_band_years"),
        "liquidity_buffer_min": req_nonneg_num(data, "liquidity_buffer_min"),
        "overdue_grace_days": req_int(data, "overdue_grace_days"),
        "secondary_premium_cap_pct": req_nonneg_num(data, "secondary_premium_cap_pct"),
        "secondary_discount_cap_pct": req_nonneg_num(data, "secondary_discount_cap_pct"),
    }
    for f in ("strategy_cap_pct", "manager_cap_pct"):
        if not (0 < fields[f] <= 1):
            raise_err(ERR_INVALID_REQUEST, "%s must be in (0, 1]" % f)
    if fields["max_vintage_band_years"] < 1:
        raise_err(ERR_INVALID_REQUEST, "max_vintage_band_years must be >= 1")
    if fields["overdue_grace_days"] < 0:
        raise_err(ERR_INVALID_REQUEST, "overdue_grace_days must be >= 0")
    for f in ("secondary_premium_cap_pct", "secondary_discount_cap_pct"):
        if fields[f] > 1:
            raise_err(ERR_INVALID_REQUEST, "%s must be in [0, 1]" % f)
    fields["status"] = "DRAFT"
    fields["unrestricted_cash"] = 0
    fields["committed_total"] = 0
    fields["deployed_total"] = 0
    fields["returned_total"] = 0
    fields["secondary_purchase_unfunded_total"] = 0
    fields["unfunded_total"] = 0
    prog = new_entity(STORE.programs, fields)
    # Posture is computed on creation; a DRAFT program with zero cash and a
    # positive buffer sits RESTRICTED until funded and opened.
    domain.recompute_posture(prog)
    return ok(public(prog), status=201)


@bp.route("/fof/programs", methods=["GET"])
def list_programs():
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    from flask import request
    return list_response(
        STORE.programs.values(),
        filters={"status": request.args.get("status")},
    )


@bp.route("/fof/programs/<pid>", methods=["GET"])
def get_program(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    return ok(public(get_program_or_404(pid)))


def _lifecycle(pid, action):
    _, role = auth_context()
    require_role(role, ["CIO"])
    prog = get_program_or_404(pid)
    st = prog["status"]
    if action == "open":
        if st != "DRAFT":
            raise_err(ERR_INVALID_STATE, "program is not in DRAFT")
        if dec(prog["unrestricted_cash"]) < dec(prog["liquidity_buffer_min"]):
            raise_err(ERR_BUFFER_BREACH,
                      "unrestricted_cash below liquidity_buffer_min")
        has_contribution = any(
            e["program_id"] == pid and e["entry_kind"] == "CONTRIBUTION"
            for e in STORE.ledger_entries.values())
        if not has_contribution:
            raise_err(ERR_BUFFER_BREACH,
                      "at least one CONTRIBUTION ledger entry is required")
        prog["status"] = "OPEN"
    elif action == "suspend":
        if st != "OPEN":
            raise_err(ERR_INVALID_STATE, "program is not OPEN")
        prog["status"] = "SUSPENDED"
    elif action == "resume":
        if st != "SUSPENDED":
            raise_err(ERR_INVALID_STATE, "program is not SUSPENDED")
        if dec(prog["unrestricted_cash"]) < dec(prog["liquidity_buffer_min"]):
            raise_err(ERR_BUFFER_BREACH,
                      "unrestricted_cash below liquidity_buffer_min")
        prog["status"] = "OPEN"
    elif action == "close":
        if st != "OPEN":
            raise_err(ERR_INVALID_STATE, "program is not OPEN")
        for c in STORE.commitments.values():
            if c["program_id"] != pid:
                continue
            if c["status"] == "PENDING_DOCS":
                raise_err(ERR_INVALID_STATE,
                          "a commitment is still PENDING_DOCS")
            if c["status"] == "EXECUTED" and dec(c["unfunded_amount"]) > 0:
                raise_err(ERR_INVALID_STATE,
                          "an EXECUTED commitment still has unfunded amount")
        for c in STORE.calls.values():
            if c["program_id"] == pid and c["status"] in ("ISSUED", "OVERDUE"):
                raise_err(ERR_INVALID_STATE,
                          "a capital call is still ISSUED or OVERDUE")
        for b in STORE.secondary_bids.values():
            if (b["program_id"] == pid
                    and b["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED")):
                raise_err(ERR_INVALID_STATE,
                          "a secondary bid is still in flight")
        prog["status"] = "CLOSED"
        # Cascades: APPROVED plans -> ARCHIVED; DRAFT/RECOMMENDED proposals
        # -> WITHDRAWN.
        for plan in STORE.pacing_plans.values():
            if plan["program_id"] == pid and plan["status"] == "APPROVED":
                plan["status"] = "ARCHIVED"
                touch(plan)
        for p in STORE.proposals.values():
            if p["program_id"] == pid and p["status"] in ("DRAFT", "RECOMMENDED"):
                p["status"] = "WITHDRAWN"
                touch(p)
    domain.recompute_posture(prog)
    touch(prog)
    return ok(public(prog))


@bp.route("/fof/programs/<pid>/open", methods=["POST"])
def open_program(pid):
    return _lifecycle(pid, "open")


@bp.route("/fof/programs/<pid>/suspend", methods=["POST"])
def suspend_program(pid):
    return _lifecycle(pid, "suspend")


@bp.route("/fof/programs/<pid>/resume", methods=["POST"])
def resume_program(pid):
    return _lifecycle(pid, "resume")


@bp.route("/fof/programs/<pid>/close", methods=["POST"])
def close_program(pid):
    return _lifecycle(pid, "close")


@bp.route("/fof/programs/<pid>/ledger-entries", methods=["POST"])
def append_ledger_entry(pid):
    _, role = auth_context()
    require_role(role, ["OperationsAnalyst"])
    prog = get_program_or_404(pid)
    if prog["posture"] == "FROZEN":
        raise_err(ERR_POSTURE_GATED, "program posture is FROZEN")
    data = body()
    entry_kind = req_enum(data, "entry_kind", LEDGER_KINDS)
    amount = req_num(data, "amount")
    note = opt_str(data, "note")
    entry = domain.append_ledger(prog, entry_kind, amount,
                                 ref_entity=None, ref_id=None, note=note)
    return ok(public(entry), status=201)


@bp.route("/fof/programs/<pid>/ledger-entries", methods=["GET"])
def list_ledger_entries(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    from flask import request
    rows = [e for e in STORE.ledger_entries.values() if e["program_id"] == pid]
    return list_response(rows,
                         filters={"entry_kind": request.args.get("entry_kind")})


@bp.route("/fof/programs/<pid>/liquidity-forecast", methods=["GET"])
def get_liquidity_forecast(pid):
    _, role = auth_context()
    require_role(role, ["CIO", "Analyst", "InvestmentCommittee", "OperationsAnalyst"])
    prog = get_program_or_404(pid)
    from flask import request
    stress = request.args.get("stress") == "true"
    return ok(domain.liquidity_forecast(prog, stress=stress))


# ---------------------------------------------------------------------------
# Program-scoped convenience lists.
# ---------------------------------------------------------------------------

@bp.route("/fof/programs/<pid>/proposals", methods=["GET"])
def list_program_proposals(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    from flask import request
    rows = [p for p in STORE.proposals.values() if p["program_id"] == pid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/programs/<pid>/calls", methods=["GET"])
def list_program_calls(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    from flask import request
    rows = [c for c in STORE.calls.values() if c["program_id"] == pid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/programs/<pid>/distributions", methods=["GET"])
def list_program_distributions(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    get_program_or_404(pid)
    from flask import request
    rows = [d for d in STORE.distributions.values() if d["program_id"] == pid]
    return list_response(rows, filters={"status": request.args.get("status")})


@bp.route("/fof/programs/<pid>/look-through", methods=["GET"])
def get_look_through(pid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    prog = get_program_or_404(pid)
    from flask import request
    group_by = request.args.get("group_by")
    if group_by not in ("sector", "geography"):
        raise_err(ERR_INVALID_REQUEST, "group_by must be sector or geography")
    quarter = request.args.get("as_of_quarter")
    return ok(domain.look_through(prog, group_by, quarter))
