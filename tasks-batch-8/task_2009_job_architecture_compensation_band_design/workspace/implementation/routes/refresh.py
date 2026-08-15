"""RefreshCycle lifecycle: schedule, compute-impact, approve, apply, cancel (§3.9)."""
from decimal import Decimal
from flask import Blueprint, request
from db import store, new_id
from middleware import require_roles, get_auth
from response import success_object, success_list
from errors import (
    not_found, invalid_request, invalid_enum, invalid_state_transition,
    already_terminal, stale_version, program_state_forbids,
    refresh_window_conflict, refresh_not_due, budget_impact_exceeds,
)
from services.common import (
    now_iso, require_fields, parse_iso_date, parse_pagination,
    sort_by_created_at, paginate, bump,
)
from services import clock, pricing
from services.employee_health import (
    recompute_employee_health, recompute_department_payroll,
    recompute_program_payroll,
)
from services.pricing import _to_date, market_composite, build_band_values

bp = Blueprint("refresh", __name__)

RC_STATES = ["SCHEDULED", "IMPACT_COMPUTED", "APPROVED", "APPLIED", "CANCELLED"]
RC_TERMINAL = {"APPLIED", "CANCELLED"}
RC_NONTERMINAL = {"SCHEDULED", "IMPACT_COMPUTED", "APPROVED"}


def rc_view(r):
    return {k: r[k] for k in ("id", "comp_program_id", "planned_window_start",
                              "planned_window_end", "effective_date", "status",
                              "budget_impact_cents", "affected_employee_count",
                              "applied_at", "created_at", "updated_at", "version")}


def get_rc_or_404(rid):
    r = store.refresh_cycles.get(rid)
    if r is None:
        raise not_found("refresh cycle not found")
    return r


def _plan_refresh_bands(program, effective_date_d):
    """Compute replacement band values for each PUBLISHED band of the program.
    Returns dict band_id -> (midpoint, min, max, composite, count, geo_ratio)
    for bands with non-empty OFFICIAL candidate sets. Others excluded."""
    plan = {}
    for b in store.pay_bands.values():
        if b["comp_program_id"] != program["id"]:
            continue
        if b["status"] != "PUBLISHED":
            continue
        try:
            composite, count = market_composite(b, "OFFICIAL", effective_date_d)
        except Exception:
            continue  # empty candidate set -> excluded from refresh
        zone = store.geo_zones[b["geo_zone_id"]]
        geo_ratio = Decimal(str(zone["effective_ratio"]))
        midpoint, min_c, max_c = build_band_values(b, composite, geo_ratio)
        plan[b["id"]] = (midpoint, min_c, max_c, composite, count, geo_ratio)
    return plan


def _candidate_employees(program, plan):
    """ACTIVE employees whose resolved PUBLISHED band received a replacement."""
    out = []
    for e in store.employees.values():
        if e["status"] != "ACTIVE":
            continue
        profile = store.job_profiles.get(e["job_profile_id"])
        if profile is None:
            continue
        for b in store.pay_bands.values():
            if b["comp_program_id"] != program["id"]:
                continue
            if b["status"] != "PUBLISHED":
                continue
            if b["job_family_id"] != profile["job_family_id"]:
                continue
            if b["job_level_id"] != profile["job_level_id"]:
                continue
            if b["geo_zone_id"] != e["geo_zone_id"]:
                continue
            if b["id"] in plan:
                out.append((e, b, plan[b["id"]]))
            break  # only the first matching PUBLISHED band (uniqueness invariant)
    return out


def _rollup(program, effective_date_d):
    """Returns (budget_impact_cents, affected_count, ordered [(employee, band, values)])."""
    plan = _plan_refresh_bands(program, effective_date_d)
    candidates = _candidate_employees(program, plan)
    candidates.sort(key=lambda t: (t[0]["hire_date"], t[0]["created_at"]))
    total = 0
    affected = 0
    for e, band, (mid, mn, mx, comp, cnt, gr) in candidates:
        adj = max(0, mn - e["base_salary_cents"])
        total += adj
        if adj > 0:
            affected += 1
    return total, affected, candidates, plan


@bp.route("/comp/refresh-cycles", methods=["POST"])
def create_cycle():
    require_roles("CompManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["comp_program_id", "planned_window_start",
                          "planned_window_end", "effective_date"])
    prog_id = body["comp_program_id"]
    if prog_id not in store.programs:
        raise not_found("comp program not found")
    pws = parse_iso_date(body["planned_window_start"], "planned_window_start")
    pwe = parse_iso_date(body["planned_window_end"], "planned_window_end")
    eff = parse_iso_date(body["effective_date"], "effective_date")
    start_d = _to_date(pws)
    end_d = _to_date(pwe)
    if not (end_d > start_d):
        raise invalid_request("planned_window_end must be after planned_window_start")
    prog = store.programs[prog_id]
    if prog["status"] != "PUBLISHED":
        raise program_state_forbids("refresh create requires program PUBLISHED")
    # Half-open window overlap vs non-terminal cycles of same program
    for rc in store.refresh_cycles.values():
        if rc["comp_program_id"] != prog_id:
            continue
        if rc["status"] not in RC_NONTERMINAL:
            continue
        os_ = _to_date(rc["planned_window_start"])
        oe_ = _to_date(rc["planned_window_end"])
        # half-open [s,e): overlap iff s < oe_ AND os_ < e
        if start_d < oe_ and os_ < end_d:
            raise refresh_window_conflict()
    now = now_iso()
    r = {"id": new_id(), "comp_program_id": prog_id,
         "planned_window_start": pws, "planned_window_end": pwe,
         "effective_date": eff, "status": "SCHEDULED",
         "budget_impact_cents": None, "affected_employee_count": None,
         "applied_at": None,
         "created_at": now, "updated_at": now, "version": 1}
    store.refresh_cycles[r["id"]] = r
    return success_object(rc_view(r), 201)


@bp.route("/comp/refresh-cycles", methods=["GET"])
def list_cycles():
    get_auth()
    limit, offset = parse_pagination(request.args)
    rows = list(store.refresh_cycles.values())
    v = request.args.get("comp_program_id")
    if v is not None:
        rows = [r for r in rows if r["comp_program_id"] == v]
    status_filter = request.args.get("status")
    if status_filter is not None:
        if status_filter not in RC_STATES:
            raise invalid_enum("status is not a declared member")
        rows = [r for r in rows if r["status"] == status_filter]
    rows = sort_by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return success_list([rc_view(r) for r in page], limit, offset, total)


@bp.route("/comp/refresh-cycles/<rid>", methods=["GET"])
def get_cycle(rid):
    get_auth()
    return success_object(rc_view(get_rc_or_404(rid)))


@bp.route("/comp/refresh-cycles/<rid>/compute-impact", methods=["POST"])
def compute_impact(rid):
    require_roles("CompAnalyst")
    r = get_rc_or_404(rid)
    if r["status"] in RC_TERMINAL:
        raise already_terminal("refresh cycle is terminal")
    if r["status"] != "SCHEDULED":
        raise invalid_state_transition("compute-impact declared only from SCHEDULED")
    prog = store.programs[r["comp_program_id"]]
    eff_d = _to_date(r["effective_date"])
    total, affected, _, _ = _rollup(prog, eff_d)
    r["budget_impact_cents"] = total
    r["affected_employee_count"] = affected
    r["status"] = "IMPACT_COMPUTED"
    bump(r)
    return success_object(rc_view(r))


@bp.route("/comp/refresh-cycles/<rid>/approve", methods=["POST"])
def approve_cycle(rid):
    require_roles("FinancePartner")
    r = get_rc_or_404(rid)
    if r["status"] in RC_TERMINAL:
        raise already_terminal("refresh cycle is terminal")
    if r["status"] != "IMPACT_COMPUTED":
        raise invalid_state_transition("approve declared only from IMPACT_COMPUTED")
    prog = store.programs[r["comp_program_id"]]
    if r["budget_impact_cents"] > prog["refresh_budget_cents"]:
        raise budget_impact_exceeds()
    r["status"] = "APPROVED"
    bump(r)
    return success_object(rc_view(r))


@bp.route("/comp/refresh-cycles/<rid>/apply", methods=["POST"])
def apply_cycle(rid):
    require_roles("CompManager")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["expected_comp_program_version"])
    r = get_rc_or_404(rid)
    prog = store.programs.get(r["comp_program_id"])
    if prog is None:
        raise not_found("comp program not found")
    # OCC (tier 5)
    expected = body["expected_comp_program_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("expected_comp_program_version must be an integer")
    if expected != prog["version"]:
        raise stale_version()
    # Posture (tier 6)
    if prog["status"] != "PUBLISHED":
        raise program_state_forbids("refresh apply requires program PUBLISHED")
    # Transition legality (tier 7)
    if r["status"] in RC_TERMINAL:
        raise already_terminal("refresh cycle is terminal")
    if r["status"] != "APPROVED":
        raise invalid_state_transition("apply declared only from APPROVED")
    # Temporal (tier 11): clock >= effective_date
    now_d = clock.now().date()
    eff_d = _to_date(r["effective_date"])
    if now_d < eff_d:
        raise refresh_not_due()
    # Link 1: re-price every PUBLISHED band; supersede; create replacement PUBLISHED
    _, _, candidates, plan = _rollup(prog, eff_d)
    replacements = {}  # old_band_id -> new_band
    for old_id, (mid, mn, mx, comp, cnt, gr) in plan.items():
        old = store.pay_bands[old_id]
        now = now_iso()
        newb = {"id": new_id(), "comp_program_id": old["comp_program_id"],
                "job_family_id": old["job_family_id"], "job_level_id": old["job_level_id"],
                "geo_zone_id": old["geo_zone_id"],
                "target_percentile": old["target_percentile"],
                "spread_pct": old["spread_pct"],
                "policy_adjustment_factor": old["policy_adjustment_factor"],
                "pricing_variant": "OFFICIAL",
                "market_composite_cents": comp, "composite_cut_count": cnt,
                "midpoint_cents": mid, "min_cents": mn, "max_cents": mx,
                "geo_ratio_snapshot": float(gr),
                "priced_at": clock.now_iso(), "status": "PUBLISHED",
                "superseded_by_band_id": None,
                "created_at": now, "updated_at": now, "version": 1}
        store.pay_bands[newb["id"]] = newb
        old["status"] = "SUPERSEDED"
        old["superseded_by_band_id"] = newb["id"]
        bump(old)
        replacements[old_id] = newb
    # Link 2: per-employee adjustments in rollup ordering
    for e, old_band, (mid, mn, mx, comp, cnt, gr) in candidates:
        new_band = replacements[old_band["id"]]
        mutated = False
        if e["base_salary_cents"] < mn:
            e["base_salary_cents"] = mn
            mutated = True
        # recompute against replacement band
        e["compa_ratio"] = None  # force recompute below
        # direct recompute against new_band (resolve_published_band would also find it)
        from decimal import Decimal as _D
        from services.common import round4 as _r4
        ratio = _D(e["base_salary_cents"]) / _D(new_band["midpoint_cents"])
        e["compa_ratio"] = float(_r4(ratio))
        if e["base_salary_cents"] < new_band["min_cents"]:
            e["range_position"] = "BELOW_MIN"
        elif e["base_salary_cents"] > new_band["max_cents"]:
            e["range_position"] = "ABOVE_MAX"
        else:
            e["range_position"] = "IN_RANGE"
        if e["base_salary_cents"] > new_band["max_cents"]:
            e["red_circled"] = True
        bump(e)
    # Link 3: auto-create exception for every employee landing ABOVE_MAX
    for e, old_band, _v in candidates:
        if e["range_position"] == "ABOVE_MAX":
            now = now_iso()
            new_band = replacements[old_band["id"]]
            er = {"id": new_id(), "employee_id": e["id"], "pay_band_id": new_band["id"],
                  "type": "ABOVE_MAX_HIRE",
                  "requested_salary_cents": e["base_salary_cents"],
                  "justification": "auto-created by refresh (red-circle)",
                  "status": "SUBMITTED",
                  "finance_required": True,
                  "pre_exception_salary_cents": None, "applied_delta_cents": None,
                  "created_by_user_id": "system", "comp_gate_by_user_id": None,
                  "applied_at": None,
                  "created_at": now, "updated_at": now, "version": 1}
            store.exception_requests[er["id"]] = er
    # Program accounting
    prog["refresh_budget_spent_cents"] += r["budget_impact_cents"]
    # Payroll rollups (salaries changed)
    for d in store.departments.values():
        recompute_department_payroll(d)
    recompute_program_payroll(prog)
    bump(prog)
    r["status"] = "APPLIED"
    r["applied_at"] = clock.now_iso()
    bump(r)
    return success_object(rc_view(r))


@bp.route("/comp/refresh-cycles/<rid>/cancel", methods=["POST"])
def cancel_cycle(rid):
    require_roles("CompManager")
    r = get_rc_or_404(rid)
    if r["status"] in RC_TERMINAL:
        raise already_terminal("refresh cycle is terminal")
    if r["status"] not in ("SCHEDULED", "IMPACT_COMPUTED"):
        raise invalid_state_transition("cancel declared only from SCHEDULED or IMPACT_COMPUTED")
    r["status"] = "CANCELLED"
    bump(r)
    return success_object(rc_view(r))
