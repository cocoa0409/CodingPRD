"""Pig groups, mortality reports (event sub-resource), settlement preview.

PRD §3.2 (scheduling), §3.3 (phase dimension), §3.4 (mortality), §3.8 (close-out).
"""

from flask import Blueprint, request

from db import store, new_id
from errors import (
    api_error, conflict, malformed,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_BARN_VERSION,
    ERR_GROUP_NOT_ACTIVE,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_SITE_NOT_ACTIVE,
    ERR_BARN_NOT_PLACEABLE,
    ERR_PLACEMENT_DATE_PAST,
    ERR_TARGET_BEFORE_PLACEMENT,
    ERR_CONFIRM_TOO_EARLY,
    ERR_CROSS_SITE_REFERENCE,
    ERR_OCCUPANCY_OVERLAP,
    ERR_SPACE_HEAD_EXCEEDED,
    ERR_FLOOR_SPACE_EXCEEDED,
    ERR_REPORT_DATE_OUT_OF_RANGE,
    ERR_HEAD_COUNT_EXCEEDED,
    ERR_EMPTY_REPORT,
)
from middleware import (
    require_roles, check_grower_ownership, group_owner_id,
    ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER, ROLE_TRANSPORT_COORDINATOR,
)
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_pig_group, ser_mortality_report,
    occupancy_overlaps, maybe_auto_close, close_group, settlement_preview,
    group_mortality_total, group_cull_total, group_head_marketed,
    SQFT_PER_HEAD, PHASE_ORDER,
)
from util import (
    get_body, req, opt, as_str, as_int, as_num, as_date, as_enum, load_or_404,
)

bp = Blueprint("pig_groups", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER, ROLE_TRANSPORT_COORDINATOR]
REASON_CODES = {"DISEASE", "INJURY", "STRESS", "OTHER"}


def _space_checks(barn, head):
    """Two space gates, head ceiling first and floor space second (§3.2)."""
    if head > barn["capacity_head"]:
        raise conflict(ERR_SPACE_HEAD_EXCEEDED,
                       f"head {head} exceeds barn capacity {barn['capacity_head']}")
    if head * SQFT_PER_HEAD > barn["floor_space_sqft"]:
        raise conflict(ERR_FLOOR_SPACE_EXCEEDED,
                       f"head {head} * {SQFT_PER_HEAD} sqft exceeds barn floor space")


@bp.route("/pig-groups", methods=["POST"])
def create_pig_group():
    require_roles([ROLE_FIELD_TECH, ROLE_INTEGRATOR_ADMIN])
    body = get_body()
    # priority 4: body FK existence, left-to-right — barn_id then contract_id
    barn_id = as_str(req(body, "barn_id"), "barn_id")
    barn = load_or_404(store.barns, barn_id, "Barn")
    contract_id = as_str(req(body, "contract_id"), "contract_id")
    contract = load_or_404(store.contracts, contract_id, "Contract")
    # priority 5: OCC on Barn.version (before field shape / state / temporal)
    expected = opt(body, "expected_barn_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != barn["version"]:
            raise api_error(ERR_STALE_BARN_VERSION, 412,
                            f"expected_barn_version {expected} != current barn version "
                            f"{barn['version']}")
    # priority 6: field shape
    placement_date = as_date(req(body, "placement_date"), "placement_date")
    target_market_date = as_date(req(body, "target_market_date"), "target_market_date")
    head_placed = as_int(req(body, "head_placed"), "head_placed", 1)
    avg_start = as_num(req(body, "avg_start_weight_lbs"), "avg_start_weight_lbs",
                       0, exclusive_minimum=True)
    if expected is None:
        raise malformed("Missing required field: expected_barn_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise malformed("expected_barn_version must be an integer")
    # priority 7: state — barn must not be OUT_OF_SERVICE; site must be ACTIVE
    if barn["barn_status"] == "OUT_OF_SERVICE":
        raise conflict(ERR_BARN_NOT_PLACEABLE, "Barn is OUT_OF_SERVICE")
    site = store.sites.get(barn["site_id"])
    if site is None or site["site_status"] != "ACTIVE":
        raise conflict(ERR_SITE_NOT_ACTIVE, "Barn's site is not ACTIVE")
    # priority 9: temporal
    clock_date = store.now().date()
    if placement_date < clock_date:
        raise conflict(ERR_PLACEMENT_DATE_PAST, "placement_date is before the clock date")
    if target_market_date <= placement_date:
        raise conflict(ERR_TARGET_BEFORE_PLACEMENT,
                       "target_market_date must fall strictly after placement_date")
    # priority 10: cross-aggregate — barn and contract must share the site
    if barn["site_id"] != contract["site_id"]:
        raise conflict(ERR_CROSS_SITE_REFERENCE,
                       "Barn's site differs from the contract's site")
    # priority 11: occupancy overlap, then space limits
    if occupancy_overlaps(barn_id, placement_date, target_market_date):
        raise conflict(ERR_OCCUPANCY_OVERLAP,
                       "Occupancy interval collides with another group on this barn")
    _space_checks(barn, head_placed)
    rec = new_record()
    rec.update({
        "barn_id": barn_id, "contract_id": contract_id,
        "placement_date": placement_date, "target_market_date": target_market_date,
        "head_placed": head_placed, "avg_start_weight_lbs": avg_start,
        "group_status": "SCHEDULED", "current_phase": "STARTER",
        "placed_at": None, "closed_at": None,
        "head_unaccounted": 0, "pending_deductions_cents": 0,
    })
    store.pig_groups[rec["id"]] = rec
    # the act of scheduling advances the barn's version (the booking book changed)
    touch(barn)
    return success_object(ser_pig_group(rec), 201)


@bp.route("/pig-groups", methods=["GET"])
def list_pig_groups():
    require_roles(ROLES_READ)
    barn_id = request.args.get("barn_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("group_status")
    items = list(store.pig_groups.values())
    if barn_id is not None:
        items = [g for g in items if g["barn_id"] == barn_id]
    if contract_id is not None:
        items = [g for g in items if g["contract_id"] == contract_id]
    if status is not None:
        items = [g for g in items if g["group_status"] == status]
    return paginate(items, request.args, ser_pig_group)


def _load_group_with_ownership(gid, role, user_id):
    group = load_or_404(store.pig_groups, gid, "PigGroup")
    check_grower_ownership(role, user_id, group_owner_id(group))
    return group


@bp.route("/pig-groups/<gid>", methods=["GET"])
def get_pig_group(gid):
    role, user_id = require_roles(ROLES_READ)
    group = _load_group_with_ownership(gid, role, user_id)
    return success_object(ser_pig_group(group))


@bp.route("/pig-groups/<gid>/confirm-placement", methods=["POST"])
def confirm_placement(gid):
    require_roles([ROLE_FIELD_TECH])
    group = load_or_404(store.pig_groups, gid, "PigGroup")
    body = get_body()
    actual_head = opt(body, "actual_head_count")
    actual_weight = opt(body, "actual_avg_weight_lbs")
    if actual_head is not None:
        actual_head = as_int(actual_head, "actual_head_count", 1)
    if actual_weight is not None:
        actual_weight = as_num(actual_weight, "actual_avg_weight_lbs",
                               0, exclusive_minimum=True)
    # state: the group must be SCHEDULED, the barn AVAILABLE, the contract ACTIVE
    if group["group_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot confirm placement from {group['group_status']}")
    barn = store.barns.get(group["barn_id"])
    if barn is None or barn["barn_status"] != "AVAILABLE":
        raise conflict(ERR_BARN_NOT_PLACEABLE, "Barn is not AVAILABLE")
    contract = store.contracts.get(group["contract_id"])
    if contract is None or contract["contract_status"] != "ACTIVE":
        raise conflict(ERR_CONTRACT_NOT_ACTIVE, "Contract is not ACTIVE")
    # temporal: confirming before placement_date is too early
    if store.now().date() < group["placement_date"]:
        raise conflict(ERR_CONFIRM_TOO_EARLY, "Clock date is before placement_date")
    # a supplied actual head count must pass the same two space checks
    if actual_head is not None:
        _space_checks(barn, actual_head)
    # side effects: actuals overwrite the schedule; stamp placed_at; barn flips
    if actual_head is not None:
        group["head_placed"] = actual_head
    if actual_weight is not None:
        group["avg_start_weight_lbs"] = actual_weight
    group["placed_at"] = store.now()
    group["group_status"] = "PLACED"
    touch(group)
    barn["barn_status"] = "OCCUPIED"
    barn["current_group_id"] = group["id"]
    touch(barn)
    return success_object(ser_pig_group(group))


@bp.route("/pig-groups/<gid>/advance-phase", methods=["POST"])
def advance_phase(gid):
    require_roles([ROLE_FIELD_TECH])
    group = load_or_404(store.pig_groups, gid, "PigGroup")
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_GROUP_NOT_ACTIVE,
                       "Group must be PLACED or MARKETING to advance phase")
    current = group["current_phase"]
    idx = PHASE_ORDER.index(current)
    if idx >= len(PHASE_ORDER) - 1:
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "FINISHER_2 is the terminal feed phase")
    # feed-phase cascade: cancel the outgoing phase's REQUESTED/SCHEDULED orders
    for o in store.feed_orders.values():
        if (o["group_id"] == gid and o["phase"] == current
                and o["order_status"] in ("REQUESTED", "SCHEDULED")):
            o["order_status"] = "CANCELLED"
            touch(o)
    group["current_phase"] = PHASE_ORDER[idx + 1]
    touch(group)
    return success_object(ser_pig_group(group))


@bp.route("/pig-groups/<gid>/cancel", methods=["POST"])
def cancel_group(gid):
    require_roles([ROLE_FIELD_TECH])
    group = load_or_404(store.pig_groups, gid, "PigGroup")
    if group["group_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot cancel a group in {group['group_status']}")
    group["group_status"] = "CANCELLED"
    touch(group)
    # the barn is untouched: the group never occupied it
    return success_object(ser_pig_group(group))


@bp.route("/pig-groups/<gid>/close-out", methods=["POST"])
def close_out_group(gid):
    require_roles([ROLE_FIELD_TECH])
    group = load_or_404(store.pig_groups, gid, "PigGroup")
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot close out a group in {group['group_status']}")
    close_group(group, force=True)
    return success_object(ser_pig_group(group))


@bp.route("/pig-groups/<gid>/settlement-preview", methods=["GET"])
def get_settlement_preview(gid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER])
    group = _load_group_with_ownership(gid, role, user_id)
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_GROUP_NOT_ACTIVE,
                       "Settlement preview requires a PLACED or MARKETING group")
    return success_object(settlement_preview(group))


# --- mortality reports (append-only event sub-resource, §3.4) ---

@bp.route("/pig-groups/<gid>/mortality-reports", methods=["POST"])
def create_mortality_report(gid):
    role, user_id = require_roles([ROLE_GROWER])
    group = _load_group_with_ownership(gid, role, user_id)
    body = get_body()
    report_date = as_date(req(body, "report_date"), "report_date")
    mortality_count = as_int(req(body, "mortality_count"), "mortality_count", 0)
    cull_count = as_int(req(body, "cull_count"), "cull_count", 0)
    reason_code = as_enum(req(body, "reason_code"), "reason_code", REASON_CODES)
    # state: group must be PLACED or MARKETING
    if group["group_status"] not in ("PLACED", "MARKETING"):
        raise conflict(ERR_GROUP_NOT_ACTIVE,
                       "Mortality reports require a PLACED or MARKETING group")
    # temporal: report_date within [placement_date, clock date]
    clock_date = store.now().date()
    if report_date < group["placement_date"] or report_date > clock_date:
        raise conflict(ERR_REPORT_DATE_OUT_OF_RANGE,
                       "report_date is outside [placement_date, clock date]")
    # quota: a zero-loss report is rejected; head conservation is enforced
    if mortality_count == 0 and cull_count == 0:
        raise conflict(ERR_EMPTY_REPORT,
                       "Report carries zero mortality and zero culls")
    accounted = (group_mortality_total(gid) + group_cull_total(gid)
                 + group_head_marketed(gid) + mortality_count + cull_count)
    if accounted > group["head_placed"]:
        raise conflict(ERR_HEAD_COUNT_EXCEEDED,
                       "Report would push accounted head beyond head_placed")
    rec = {
        "id": new_id(),
        "created_at": store.now_str(),
        "_seq": store.next_seq(),
        "group_id": gid,
        "report_date": report_date,
        "mortality_count": mortality_count,
        "cull_count": cull_count,
        "reason_code": reason_code,
    }
    store.mortality_reports[rec["id"]] = rec
    touch(group)
    # a report that drains head_current to zero closes the group (§3.8 cascade)
    maybe_auto_close(group)
    return success_object(ser_mortality_report(rec), 201)


@bp.route("/pig-groups/<gid>/mortality-reports", methods=["GET"])
def list_mortality_reports(gid):
    role, user_id = require_roles([ROLE_INTEGRATOR_ADMIN, ROLE_FIELD_TECH, ROLE_GROWER])
    _load_group_with_ownership(gid, role, user_id)
    items = [r for r in store.mortality_reports.values() if r["group_id"] == gid]
    return paginate(items, request.args, ser_mortality_report)
