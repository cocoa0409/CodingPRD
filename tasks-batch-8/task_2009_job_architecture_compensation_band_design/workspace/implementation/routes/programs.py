"""CompProgram CRUD + lifecycle transitions (§2.4)."""
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal,
)
from services.common import (
    now_iso, require_fields, parse_int, parse_iso_date, parse_pagination,
    sort_by_created_at, paginate, bump,
)

bp = Blueprint("programs", __name__)

PROGRAM_STATES = ["DRAFT", "FRAMEWORK_LOCKED", "PRICING", "MAPPING_OPEN", "PUBLISHED", "ARCHIVED"]
TERMINAL = {"ARCHIVED"}
TRANSITIONS = {
    "DRAFT": {"FRAMEWORK_LOCKED"},
    "FRAMEWORK_LOCKED": {"PRICING"},
    "PRICING": {"MAPPING_OPEN"},
    "MAPPING_OPEN": {"PUBLISHED"},
    "PUBLISHED": {"ARCHIVED"},
}


def program_view(p: dict) -> dict:
    return {k: p[k] for k in (
        "id", "fiscal_year", "refresh_cadence_months", "pricing_as_of_date",
        "merit_budget_cents", "refresh_budget_cents", "status",
        "total_payroll_projection_cents", "refresh_budget_spent_cents",
        "created_at", "updated_at", "version",
    )}


def get_program_or_404(pid):
    p = store.programs.get(pid)
    if p is None:
        raise not_found("program not found")
    return p


def _transition_precondition_errors(program, to_state):
    """Return the error to raise, or None. Preconditions per §2.4."""
    cur = program["status"]
    if cur == "DRAFT" and to_state == "FRAMEWORK_LOCKED":
        active_families = sum(1 for f in store.job_families.values() if f["status"] == "ACTIVE")
        if active_families < 1 or len(store.job_levels) < 2:
            return invalid_state_transition("framework lock preconditions unmet")
    elif cur == "FRAMEWORK_LOCKED" and to_state == "PRICING":
        if not any(pr["status"] == "APPROVED" for pr in store.job_profiles.values()):
            return invalid_state_transition("no APPROVED job profile exists")
    elif cur == "PRICING" and to_state == "MAPPING_OPEN":
        if not any(b["comp_program_id"] == program["id"] and b["status"] == "PUBLISHED"
                   for b in store.pay_bands.values()):
            return invalid_state_transition("no PUBLISHED pay band exists for this program")
    elif cur == "MAPPING_OPEN" and to_state == "PUBLISHED":
        open_states = {"SUBMITTED", "HRBP_REVIEWED", "COMP_TRIAGED"}
        for md in store.mapping_decisions.values():
            if md["status"] in open_states:
                return invalid_state_transition("mapping decisions still in flight")
    elif cur == "PUBLISHED" and to_state == "ARCHIVED":
        for rc in store.refresh_cycles.values():
            if rc["comp_program_id"] == program["id"] and rc["status"] in ("SCHEDULED", "IMPACT_COMPUTED", "APPROVED"):
                return invalid_state_transition("refresh cycles still in flight")
        inflight = {"SUBMITTED", "HRBP_PASSED", "FINANCE_REVIEW", "RETURNED"}
        for er in store.exception_requests.values():
            if er["status"] in inflight:
                emp = store.employees.get(er["employee_id"])
                if emp is not None:
                    # "employees in scope" — program scope = employees whose band belongs to this program
                    band = store.pay_bands.get(er["pay_band_id"])
                    if band is not None and band["comp_program_id"] == program["id"]:
                        return invalid_state_transition("exception requests still in flight")
    return None


@bp.route("/comp/programs", methods=["POST"])
def create_program():
    user_id, role = require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["fiscal_year", "merit_budget_cents", "refresh_budget_cents", "pricing_as_of_date"])
    fiscal_year = parse_int(body["fiscal_year"], "fiscal_year")
    merit = parse_int(body["merit_budget_cents"], "merit_budget_cents", minimum=0)
    refresh_budget = parse_int(body["refresh_budget_cents"], "refresh_budget_cents", minimum=0)
    pricing_as_of = parse_iso_date(body["pricing_as_of_date"], "pricing_as_of_date")
    cadence = body.get("refresh_cadence_months", 12)
    cadence = parse_int(cadence, "refresh_cadence_months", minimum=1)
    now = now_iso()
    p = {
        "id": new_id(),
        "fiscal_year": fiscal_year,
        "refresh_cadence_months": cadence,
        "pricing_as_of_date": pricing_as_of,
        "merit_budget_cents": merit,
        "refresh_budget_cents": refresh_budget,
        "status": "DRAFT",
        "total_payroll_projection_cents": 0,
        "refresh_budget_spent_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.programs[p["id"]] = p
    return success_object(program_view(p), 201)


@bp.route("/comp/programs", methods=["GET"])
def list_programs():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.programs.values())
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in PROGRAM_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [p for p in rows if p["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([program_view(p) for p in page], limit, offset, total)


@bp.route("/comp/programs/<pid>", methods=["GET"])
def get_program(pid):
    get_auth()
    p = get_program_or_404(pid)
    return success_object(program_view(p))


@bp.route("/comp/programs/<pid>", methods=["PATCH"])
def patch_program(pid):
    user_id, role = require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    p = get_program_or_404(pid)
    if p["status"] in TERMINAL:
        raise already_terminal("program is ARCHIVED")
    changed = False
    if "merit_budget_cents" in body and body["merit_budget_cents"] is not None:
        p["merit_budget_cents"] = parse_int(body["merit_budget_cents"], "merit_budget_cents", minimum=0)
        changed = True
    if "refresh_budget_cents" in body and body["refresh_budget_cents"] is not None:
        p["refresh_budget_cents"] = parse_int(body["refresh_budget_cents"], "refresh_budget_cents", minimum=0)
        changed = True
    if changed:
        bump(p)
    return success_object(program_view(p))


@bp.route("/comp/programs/<pid>/transition", methods=["POST"])
def transition_program(pid):
    user_id, role = require_roles("CompAdmin")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["to_state"])
    to_state = body["to_state"]
    if not isinstance(to_state, str) or to_state not in PROGRAM_STATES:
        raise invalid_enum("to_state is not a declared member of the program state machine")
    p = get_program_or_404(pid)
    if p["status"] in TERMINAL:
        raise already_terminal("program is ARCHIVED")
    if to_state not in TRANSITIONS.get(p["status"], set()):
        raise invalid_state_transition(f"transition {p['status']} -> {to_state} not declared")
    err = _transition_precondition_errors(p, to_state)
    if err is not None:
        raise err
    p["status"] = to_state
    bump(p)
    return success_object(program_view(p))
