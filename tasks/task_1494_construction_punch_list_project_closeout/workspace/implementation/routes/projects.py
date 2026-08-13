"""Project lifecycle (PRD 3.1 setup, 3.4 SC/occupancy, 3.6 close)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from authz import GCPM, OWNER, ALL_ROLES, require_roles
from db import store
from derived import project_trades, recompute_project
from errors import (
    final_release_not_paid, invalid_request, invalid_state, no_trade_packages,
    occupancy_already_registered, occupancy_before_sc, occupancy_not_registered,
    open_life_safety_items, open_major_items, too_many_open_minor_items,
    walk_incomplete,
)
from respond import success
from serialize import ser_project
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_enum_default,
    req_bool, req_int, req_number, req_str, req_temporal,
)

bp = Blueprint("projects", __name__, url_prefix="/closeout")

# The five working phases in which correction activity is allowed (PRD 3.3).
WORKING_PHASES = (
    "PUNCH_ACTIVE", "SC_REVIEW", "SUBSTANTIALLY_COMPLETE",
    "CLOSEOUT_IN_PROGRESS", "FINAL_RELEASE_PENDING",
)


def check_sc_gates(p):
    """PRD 3.4: fixed safety-first gate order — life-safety, major, minor,
    then walk completion. Re-checked identically at determination time."""
    if p["open_life_safety_count"] > 0:
        raise open_life_safety_items()
    if p["open_major_count"] > 0:
        raise open_major_items()
    if p["open_minor_count"] > 5:
        raise too_many_open_minor_items()
    if any(not t["has_completed_walk"] for t in project_trades(p["id"])):
        raise walk_incomplete()


@bp.route("/projects", methods=["POST"])
def create_project():
    require_roles([GCPM])
    data = json_body()
    name = req_str(data, "name")
    cvc = req_int(data, "contract_value_cents")
    if cvc < 1000:
        raise invalid_request("contract_value_cents must be >= 1000")
    pct = Decimal(str(req_number(data, "retainage_pct")))
    if not pct.is_finite() or pct <= 0 or pct > Decimal("0.25"):
        raise invalid_request("retainage_pct must be in (0, 0.25]")
    reduction_policy = opt_enum_default(
        data, "reduction_policy", ("STANDARD", "ADJUSTED"), "STANDARD")
    warranty_sla_mode = opt_enum_default(
        data, "warranty_sla_mode", ("CALENDAR", "BUSINESS"), "CALENDAR")
    # PRD 2.6: the held figure is rounded half-up exactly once, at creation.
    held = int((Decimal(cvc) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    p = {
        "id": new_id(),
        "_seq": next(store.seq),
        "name": name,
        "contract_value_cents": cvc,
        "retainage_pct": float(pct),
        "reduction_policy": reduction_policy,
        "warranty_sla_mode": warranty_sla_mode,
        "status": "MOBILIZED",
        "open_life_safety_count": 0,
        "open_major_count": 0,
        "open_minor_count": 0,
        "sc_eligible": False,
        "substantial_completion_date": None,
        "warranty_start_date": None,
        "beneficial_occupancy_registered": False,
        "beneficial_occupancy_date": None,
        "retainage_held_cents": held,
        "retainage_paid_cents": 0,
        "retainage_outstanding_cents": held,
        "sc_rejection_count": 0,
        "closed_at": None,
    }
    p.update(new_common_fields())
    store.projects[p["id"]] = p
    return success(ser_project(p), status=201)


@bp.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    require_roles(ALL_ROLES)
    return success(ser_project(get_or_404(store.projects, pid)))


@bp.route("/projects/<pid>/begin-punch", methods=["POST"])
def begin_punch(pid):
    require_roles([GCPM])
    p = get_or_404(store.projects, pid)
    if p["status"] != "MOBILIZED":
        raise invalid_state("Project must be MOBILIZED to begin punch operations")
    if not project_trades(pid):
        raise no_trade_packages()
    recompute_project(p, {"status": "PUNCH_ACTIVE"})
    return success(ser_project(p))


@bp.route("/projects/<pid>/request-sc-review", methods=["POST"])
def request_sc_review(pid):
    require_roles([GCPM])
    p = get_or_404(store.projects, pid)
    if p["status"] != "PUNCH_ACTIVE":
        raise invalid_state("Project must be PUNCH_ACTIVE to request SC review")
    check_sc_gates(p)
    recompute_project(p, {"status": "SC_REVIEW"})
    return success(ser_project(p))


@bp.route("/projects/<pid>/determine-substantial-completion", methods=["POST"])
def determine_substantial_completion(pid):
    require_roles([OWNER])
    data = json_body()
    approved = req_bool(data, "approved")
    if not approved:
        req_str(data, "rejection_note")  # required when approved=false
    p = get_or_404(store.projects, pid)
    if p["status"] != "SC_REVIEW":
        raise invalid_state("Project must be SC_REVIEW for an SC determination")
    if approved:
        check_sc_gates(p)  # eligibility re-checked at determination time
        recompute_project(p, {
            "status": "SUBSTANTIALLY_COMPLETE",
            "substantial_completion_date": store.clock,
            "warranty_start_date": store.clock,
        })
    else:
        recompute_project(p, {
            "status": "PUNCH_ACTIVE",
            "sc_rejection_count": p["sc_rejection_count"] + 1,
        })
    return success(ser_project(p))


@bp.route("/projects/<pid>/register-beneficial-occupancy", methods=["POST"])
def register_beneficial_occupancy(pid):
    require_roles([OWNER])
    data = json_body()
    occupancy_date = req_temporal(data, "occupancy_date")
    p = get_or_404(store.projects, pid)
    if p["status"] != "SUBSTANTIALLY_COMPLETE":
        raise invalid_state("Occupancy may only be registered while SUBSTANTIALLY_COMPLETE")
    # Priority 10 (temporal) precedes priority 11 (idempotence) — PRD 2.10.
    if occupancy_date < p["substantial_completion_date"]:
        raise occupancy_before_sc()
    if p["beneficial_occupancy_registered"]:
        raise occupancy_already_registered()
    recompute_project(p, {
        "beneficial_occupancy_registered": True,
        "beneficial_occupancy_date": occupancy_date,
    })
    return success(ser_project(p))


@bp.route("/projects/<pid>/start-closeout", methods=["POST"])
def start_closeout(pid):
    require_roles([GCPM])
    p = get_or_404(store.projects, pid)
    if p["status"] != "SUBSTANTIALLY_COMPLETE":
        raise invalid_state("Project must be SUBSTANTIALLY_COMPLETE to start closeout")
    if not p["beneficial_occupancy_registered"]:
        raise occupancy_not_registered()
    recompute_project(p, {"status": "CLOSEOUT_IN_PROGRESS"})
    return success(ser_project(p))


@bp.route("/projects/<pid>/close", methods=["POST"])
def close_project(pid):
    require_roles([GCPM])
    p = get_or_404(store.projects, pid)
    if p["status"] != "FINAL_RELEASE_PENDING":
        raise invalid_state("Project must be FINAL_RELEASE_PENDING to close")
    if not any(
        r["project_id"] == pid and r["kind"] == "FINAL" and r["status"] == "PAID"
        for r in store.retainage_releases.values()
    ):
        raise final_release_not_paid()
    recompute_project(p, {"status": "CLOSED", "closed_at": store.clock})
    return success(ser_project(p))
