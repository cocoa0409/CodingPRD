"""Emission targets, baselines, and trajectories (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_state, not_found
from http_util import (
    MANAGER,
    READ_ROLES,
    get_body,
    parse_pagination,
    require_roles,
    v_enum,
    v_int,
    v_num,
    v_str,
    v_version,
)
from store import db, new_entity, touch

bp = Blueprint("targets", __name__, url_prefix="/sustainability")

TARGET_STATUSES = {"DRAFT", "APPROVED", "ACTIVE", "ACHIEVED", "MISSED", "RETIRED"}
SCOPE_COVERAGES = {"SCOPE1_2", "SCOPE1_2_3"}

LEGAL_EDGES = {
    ("DRAFT", "APPROVED"),
    ("APPROVED", "ACTIVE"),
    ("ACTIVE", "RETIRED"),
}

# Cycle statuses at LOCKED or beyond (for the baseline-recalc activation gate).
LOCKED_OR_LATER = ("LOCKED", "UNDER_ASSURANCE", "ASSURED", "DISCLOSED")


def load_target(target_id):
    target = db.targets.get(target_id)
    if target is None:
        raise not_found(f"EmissionTarget {target_id} not found")
    return target


@bp.route("/targets", methods=["POST"])
@require_roles(MANAGER)
def create_target():
    body = get_body()
    name = v_str(body, "name")
    base_year = v_int(body, "base_year")
    target_year = v_int(body, "target_year")
    reduction_pct = v_num(body, "reduction_pct", gt=0, lt=100)
    scope_coverage = v_enum(body, "scope_coverage", SCOPE_COVERAGES)
    base_total = v_num(body, "base_year_total_tco2e")
    target = new_entity(
        {
            "name": name,
            "base_year": base_year,
            "target_year": target_year,
            "reduction_pct": reduction_pct,
            "scope_coverage": scope_coverage,
            "base_year_total_tco2e": base_total,
            "baseline_source": "PROVISIONAL",
            "baseline_shift_pct": None,
            "baseline_shift_significant": None,
            "status": "DRAFT",
            "trajectory_status": "NOT_EVALUATED",
        }
    )
    db.targets[target["id"]] = target
    return ok(domain.ser_target(target), status=201)


@bp.route("/targets/<target_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_target(target_id):
    return ok(domain.ser_target(load_target(target_id)))


@bp.route("/targets", methods=["GET"])
@require_roles(*READ_ROLES)
def list_targets():
    limit, offset = parse_pagination()
    items = sorted(db.targets.values(), key=lambda x: x["_seq"])
    status = request.args.get("status")
    base_year = request.args.get("base_year")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    if base_year is not None:
        try:
            year = int(base_year)
            items = [t for t in items if t["base_year"] == year]
        except (TypeError, ValueError):
            items = []
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_target(t) for t in page], limit, offset, total)


@bp.route("/targets/<target_id>/transition", methods=["POST"])
@require_roles(MANAGER)
def target_transition(target_id):
    target = load_target(target_id)
    body = get_body()
    to_state = v_enum(body, "to_state", TARGET_STATUSES)
    if (target["status"], to_state) not in LEGAL_EDGES:
        raise invalid_state(
            f"EmissionTarget in status {target['status']} cannot transition to {to_state}"
        )
    if to_state == "ACTIVE":
        # Priority 15 aggregate gate: a PROVISIONAL baseline cannot be
        # activated while a locked-or-later base-year cycle exists.
        if target["baseline_source"] == "PROVISIONAL" and any(
            c["reporting_year"] == target["base_year"]
            and c["status"] in LOCKED_OR_LATER
            for c in db.cycles.values()
        ):
            raise err(
                "ERR_BASELINE_RECALC_REQUIRED",
                409,
                "Baseline must be recalculated: a locked base-year cycle exists",
            )
        target["trajectory_status"] = "NOT_EVALUATED"
    target["status"] = to_state
    touch(target)
    return ok(domain.ser_target(target))


@bp.route("/targets/<target_id>/recalculate-baseline", methods=["POST"])
@require_roles(MANAGER)
def recalculate_baseline(target_id):
    body = get_body()
    # Priority 3: path id, then the body FK.
    target = load_target(target_id)
    bcid = body.get("base_cycle_id")
    if bcid is not None and (not isinstance(bcid, str) or bcid not in db.cycles):
        raise not_found("Field base_cycle_id does not resolve to an existing resource")
    # Priority 4: request shape (both fields non-optional, PRD 2.8).
    base_cycle = db.cycles[v_str(body, "base_cycle_id")]
    expected = v_version(body, "expected_target_version")
    # Priority 5: OCC.
    if expected != target["version"]:
        raise err(
            "ERR_STALE_VERSION",
            412,
            "expected_target_version does not match the target's current version",
        )
    # Priority 14 freeze gate: the base cycle's inventory must be FROZEN.
    inv = calc.inventory_for_cycle(base_cycle["id"])
    if inv["status"] != "FROZEN":
        raise err(
            "ERR_INVENTORY_STALE",
            409,
            "The base cycle's InventoryResult is not FROZEN",
        )
    # Repeatable by design: no state precondition on the target itself.
    old = calc.dec(target["base_year_total_tco2e"])
    new_base = calc.r2(calc.coverage_total(target, inv))
    if old == 0:
        shift = Decimal("0.0") if new_base == 0 else Decimal("100.0")
    else:
        shift = calc.r1(abs(new_base - old) / old * 100)
    target["base_year_total_tco2e"] = float(new_base)
    target["baseline_shift_pct"] = float(shift)
    target["baseline_shift_significant"] = bool(shift >= calc.BASELINE_SIGNIFICANCE)
    target["baseline_source"] = "RECALCULATED"
    touch(target)
    return ok(domain.ser_target(target))
