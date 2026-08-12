"""Subcontract endpoints, negotiation loop, default/replacement."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, STANDARD_READ_ROLES, auth
from response import ok, ok_list
from services import (
    INS_SNAPSHOT_DEFAULTS,
    MAX_NEGOTIATION_ROUNDS,
    RETAINAGE_MAX,
    RETAINAGE_MIN,
    bids_of,
    certs_of,
    check_negotiation_completeness,
    ensure_no_open_life_safety_gap,
    ensure_sub_not_terminal,
    evaluate_package_bubble,
    fiscal_cap,
    get_bid,
    get_package,
    get_project,
    get_subcontract,
    insurance_gate,
    package_of,
    project_clock,
    projected_total,
    recompute_leveled_value,
    recompute_package,
    ser_round,
    ser_subcontract,
    sorted_created,
    stamp,
    subs_of,
    touch,
)
from util import (
    as_bool,
    as_int,
    as_list,
    as_num,
    as_str,
    body,
    pagination_args,
    required,
)

bp = Blueprint("subcontracts", __name__)


def _check_retainage(payment_terms):
    pct = payment_terms.get("retainage_pct") if isinstance(payment_terms, dict) else None
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise ApiError("ERR_VALIDATION", 422, "payment_terms.retainage_pct must be a number")
    value = Decimal(str(pct))
    if value < RETAINAGE_MIN or value > RETAINAGE_MAX:
        raise ApiError(
            "ERR_RETAINAGE_OUT_OF_BAND", 422, "retainage_pct outside [0.05, 0.10]"
        )


def _validate_payment_terms(value):
    if not isinstance(value, dict):
        raise ApiError("ERR_VALIDATION", 422, "payment_terms must be an object")
    as_num(required(value, "retainage_pct"), "payment_terms.retainage_pct")
    if "pay_if_paid" in value and value["pay_if_paid"] is not None:
        as_bool(value["pay_if_paid"], "payment_terms.pay_if_paid")
    return value


def _validate_authority_limits(value):
    tiers = as_list(value, "change_authority_limits")
    for i, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise ApiError(
                "ERR_VALIDATION", 422, f"change_authority_limits[{i}] must be an object"
            )
        as_int(required(tier, "max_value_cents"), "max_value_cents")
        as_num(required(tier, "max_cumulative_pct"), "max_cumulative_pct")
        roles = as_list(required(tier, "roles"), "roles")
        for r in roles:
            as_str(r, "roles")
    return tiers


def _validate_snapshot(value):
    if not isinstance(value, dict):
        raise ApiError(
            "ERR_VALIDATION", 422, "insurance_requirements_snapshot must be an object"
        )
    for f in ("gl_occurrence_cents", "gl_aggregate_cents", "auto_cents", "umbrella_cents"):
        if f in value and value[f] is not None:
            as_int(value[f], f)
    for f in ("ai_required", "wos_required", "ptd_required", "pollution_required"):
        if f in value and value[f] is not None:
            as_bool(value[f], f)
    if "workers_comp" in value and value["workers_comp"] is not None:
        as_str(value["workers_comp"], "workers_comp")
    return value


def _validate_dispositions(value):
    items = as_list(value, "allowance_dispositions")
    for i, d in enumerate(items):
        if not isinstance(d, dict):
            raise ApiError(
                "ERR_VALIDATION", 422, f"allowance_dispositions[{i}] must be an object"
            )
        as_str(required(d, "allowance_id"), "allowance_id")
        action = required(d, "action")
        if action not in ("ACCEPT", "REJECT", "REPRICE"):
            raise ApiError(
                "ERR_VALIDATION", 422, "action must be ACCEPT, REJECT, or REPRICE"
            )
        if action == "REPRICE":
            as_int(required(d, "priced_cents"), "priced_cents")
        elif "priced_cents" in d and d["priced_cents"] is not None:
            as_int(d["priced_cents"], "priced_cents")
    return items


def _validate_selections(value):
    items = as_list(value, "alternate_selections")
    for i, s in enumerate(items):
        if not isinstance(s, dict):
            raise ApiError(
                "ERR_VALIDATION", 422, f"alternate_selections[{i}] must be an object"
            )
        as_str(required(s, "alternate_id"), "alternate_id")
        as_bool(required(s, "selected"), "selected")
    return items


@bp.post("/trade-packages/<pkg_id>/subcontracts")
def create_subcontract(pkg_id):
    auth(["BuyoutLead"])
    pkg = get_package(pkg_id)
    data = body()
    subcontractor_name = as_str(required(data, "subcontractor_name"), "subcontractor_name")
    source_bid_id = as_str(required(data, "source_bid_id"), "source_bid_id")
    flow_down_terms = as_str(required(data, "flow_down_terms"), "flow_down_terms")
    payment_terms = _validate_payment_terms(required(data, "payment_terms"))
    change_authority_limits = _validate_authority_limits(
        required(data, "change_authority_limits")
    )
    snapshot_in = data.get("insurance_requirements_snapshot")
    if snapshot_in is not None:
        _validate_snapshot(snapshot_in)
    # Package state + competitive-tension gate.
    package_bids = bids_of(pkg)
    if (
        pkg["status"] != "UNDER_LEVELING"
        or len(package_bids) < 2
        or not any(b["status"] == "WITHDRAWN" for b in package_bids)
    ):
        raise ApiError(
            "ERR_TRADE_PACKAGE_NOT_ACCEPTING_BIDS",
            409,
            "Package not in a state that accepts subcontract drafts",
        )
    # Source-bid eligibility (existence within parent scope, then state).
    bid = DB["bids"].get(source_bid_id)
    if bid is None or bid["trade_package_id"] != pkg["id"]:
        raise ApiError("ERR_NOT_FOUND", 404, "Bid not found")
    if bid["status"] not in ("PLACED", "AWARDED"):
        raise ApiError("ERR_BID_NOT_AWARDABLE", 409, "Source bid not PLACED/AWARDED")
    for s in subs_of(pkg):
        if s["source_bid_id"] == source_bid_id and s["status"] not in (
            "DEFAULTED",
            "REPLACED",
            "TERMINATED",
        ):
            raise ApiError(
                "ERR_BID_NOT_AWARDABLE",
                409,
                "Source bid already referenced by a non-terminal subcontract",
            )
    _check_retainage(payment_terms)
    snapshot = dict(INS_SNAPSHOT_DEFAULTS)
    if snapshot_in:
        for k, v in snapshot_in.items():
            if v is not None:
                snapshot[k] = v
    rec = {
        "id": new_id(),
        "trade_package_id": pkg["id"],
        "subcontractor_name": subcontractor_name,
        "source_bid_id": source_bid_id,
        "replaces_subcontract_id": None,
        "replacement_subcontract_id": None,
        "flow_down_terms": flow_down_terms,
        "insurance_requirements_snapshot": snapshot,
        "payment_terms": payment_terms,
        "change_authority_limits": change_authority_limits,
        "contract_value_cents": 0,
        "cumulative_co_cents": 0,
        "negotiation_round": 0,
        "insurance_status": "MISSING",
        "bonding_requirement": (
            "NOT_REQUIRED" if pkg["bonding_policy"] == "WAIVED" else "PENDING_DECISION"
        ),
        "sov_status": "DRAFT",
        "default_flag": False,
        "default_recorded_at": None,
        "estimated_replacement_cost_cents": None,
        "status": "DRAFT",
    }
    stamp(rec)
    DB["subcontracts"][rec["id"]] = rec
    return ok(ser_subcontract(rec), status=201)


@bp.get("/subcontracts/<sub_id>")
def get_one_subcontract(sub_id):
    auth(ALL_ROLES)
    return ok(ser_subcontract(get_subcontract(sub_id)))


@bp.get("/trade-packages/<pkg_id>/subcontracts")
def list_subcontracts(pkg_id):
    auth(ALL_ROLES)
    pkg = get_package(pkg_id)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = sorted_created(subs_of(pkg))
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_subcontract(s) for s in page], total, limit, offset)


@bp.post("/subcontracts/<sub_id>/recommend-award")
def recommend_award(sub_id):
    auth(["BuyoutLead", "OperationsManager"])
    sub = get_subcontract(sub_id)
    data = body()
    contract_value_cents = as_int(
        required(data, "contract_value_cents"), "contract_value_cents"
    )
    dispositions_present = (
        "allowance_dispositions" in data and data["allowance_dispositions"] is not None
    )
    selections_present = (
        "alternate_selections" in data and data["alternate_selections"] is not None
    )
    dispositions = (
        _validate_dispositions(data["allowance_dispositions"])
        if dispositions_present
        else []
    )
    selections = (
        _validate_selections(data["alternate_selections"]) if selections_present else []
    )
    ensure_sub_not_terminal(sub)
    if sub["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in DRAFT"
        )
    if sub["negotiation_round"] >= MAX_NEGOTIATION_ROUNDS:
        raise ApiError(
            "ERR_NEGOTIATION_ROUND_EXCEEDED",
            409,
            "negotiation_round would exceed MAX_NEGOTIATION_ROUNDS (2)",
        )
    _check_retainage(sub["payment_terms"])
    bid = get_bid(sub["source_bid_id"])
    check_negotiation_completeness(
        bid, dispositions, selections, dispositions_present, selections_present
    )
    pkg = package_of(sub)
    if projected_total(pkg, contract_value_cents) > fiscal_cap(pkg):
        raise ApiError(
            "ERR_CONTINGENCY_EXCEEDED",
            409,
            "Projected awarded value exceeds estimated budget plus remaining contingency pool",
        )
    project = get_project(pkg["project_id"])
    round_rec = {
        "id": new_id(),
        "subcontract_id": sub["id"],
        "round_index": sub["negotiation_round"] + 1,
        "proposed_value_cents": contract_value_cents,
        "allowance_dispositions": dispositions,
        "alternate_selections": selections,
        "note": data.get("note"),
        "recorded_at": project["current_time_utc"],
    }
    # NegotiationRound is append-only: id + created_at, no updated_at / version.
    from db import now_iso

    round_rec["created_at"] = now_iso()
    DB["negotiation_rounds"][round_rec["id"]] = round_rec
    sub["contract_value_cents"] = contract_value_cents
    sub["status"] = "PENDING_AWARD"
    touch(sub)
    recompute_leveled_value(bid, round_rec)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/renegotiate")
def renegotiate(sub_id):
    auth(["BuyoutLead"])
    sub = get_subcontract(sub_id)
    ensure_sub_not_terminal(sub)
    if sub["status"] != "PENDING_AWARD":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in PENDING_AWARD"
        )
    sub["status"] = "DRAFT"
    sub["negotiation_round"] += 1
    sub["contract_value_cents"] = 0
    touch(sub)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/award")
def award_subcontract(sub_id):
    auth(["OperationsManager"])
    sub = get_subcontract(sub_id)
    ensure_sub_not_terminal(sub)
    if sub["status"] != "PENDING_AWARD":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in PENDING_AWARD"
        )
    pkg = package_of(sub)
    ensure_no_open_life_safety_gap(pkg)
    cap = fiscal_cap(pkg)
    if sub["contract_value_cents"] > cap:
        raise ApiError(
            "ERR_AWARD_EXCEEDS_BUDGET",
            409,
            "Final award value exceeds package cap at award time",
        )
    if projected_total(pkg, sub["contract_value_cents"], exclude_sub_id=sub["id"]) > cap:
        raise ApiError(
            "ERR_CONTINGENCY_EXCEEDED",
            409,
            "Projected awarded value exceeds estimated budget plus remaining contingency pool",
        )
    sub["status"] = "AWARDED"
    if pkg["bonding_policy"] != "WAIVED":
        sub["bonding_requirement"] = "PENDING_DECISION"
    touch(sub)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/issue")
def issue_subcontract(sub_id):
    auth(["BuyoutLead"])
    sub = get_subcontract(sub_id)
    ensure_sub_not_terminal(sub)
    if sub["status"] != "AWARDED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in AWARDED"
        )
    pkg = package_of(sub)
    project = get_project(pkg["project_id"])
    insurance_gate(sub, pkg, project)
    if pkg["bonding_policy"] != "WAIVED":
        has_decision = any(
            b["subcontract_id"] == sub["id"] for b in DB["bond_decisions"].values()
        )
        if not has_decision or sub["bonding_requirement"] not in (
            "NOT_REQUIRED",
            "SURETY_BOND",
            "SUBGUARD",
        ):
            raise ApiError(
                "ERR_BONDING_NOT_SATISFIED",
                409,
                "Required BondDecision missing at issue",
            )
    ensure_no_open_life_safety_gap(pkg)
    sub["status"] = "ISSUED"
    touch(sub)
    if pkg["status"] == "UNDER_LEVELING":
        pkg["status"] = "BUYOUT_IN_PROGRESS"
        touch(pkg)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/execute")
def execute_subcontract(sub_id):
    auth(["BuyoutLead"])
    sub = get_subcontract(sub_id)
    ensure_sub_not_terminal(sub)
    if sub["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in ISSUED"
        )
    pkg = package_of(sub)
    project = get_project(pkg["project_id"])
    insurance_gate(sub, pkg, project)
    sub["status"] = "EXECUTED"
    touch(sub)
    recompute_package(pkg)
    evaluate_package_bubble(pkg)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/declare-default")
def declare_default(sub_id):
    auth(["OperationsManager"])
    sub = get_subcontract(sub_id)
    data = body()
    as_str(required(data, "reason"), "reason")
    estimated_replacement_cost_cents = as_int(
        required(data, "estimated_replacement_cost_cents"),
        "estimated_replacement_cost_cents",
    )
    replacement_subcontract_id = data.get("replacement_subcontract_id")
    if replacement_subcontract_id is not None:
        as_str(replacement_subcontract_id, "replacement_subcontract_id")
    ensure_sub_not_terminal(sub)
    if sub["status"] != "EXECUTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not EXECUTED"
        )
    if any(
        s["subcontract_id"] == sub["id"] and s["status"] == "APPROVED"
        for s in DB["schedule_of_values"].values()
    ):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "APPROVED ScheduleOfValues blocks declare-default (cure via replacement)",
        )
    replacement = None
    if replacement_subcontract_id is not None:
        candidate = DB["subcontracts"].get(replacement_subcontract_id)
        if (
            candidate is None
            or candidate["status"] != "DRAFT"
            or candidate["trade_package_id"] != sub["trade_package_id"]
        ):
            raise ApiError(
                "ERR_REPLACEMENT_LINK_INVALID",
                409,
                "replacement_subcontract_id does not reference a DRAFT subcontract on the same package",
            )
        replacement = candidate
    pkg = package_of(sub)
    project = get_project(pkg["project_id"])
    sub["status"] = "DEFAULTED"
    sub["default_flag"] = True
    sub["default_recorded_at"] = project["current_time_utc"]
    sub["estimated_replacement_cost_cents"] = estimated_replacement_cost_cents
    touch(sub)
    if replacement is not None:
        replacement["replaces_subcontract_id"] = sub["id"]
        touch(replacement)
    recompute_package(pkg)
    evaluate_package_bubble(pkg)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/replace")
def replace_subcontract(sub_id):
    auth(["OperationsManager"])
    sub = get_subcontract(sub_id)
    data = body()
    as_str(required(data, "reason"), "reason")
    estimated_replacement_cost_cents = as_int(
        required(data, "estimated_replacement_cost_cents"),
        "estimated_replacement_cost_cents",
    )
    ensure_sub_not_terminal(sub)
    if sub["status"] != "EXECUTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not EXECUTED"
        )
    pkg = package_of(sub)
    if pkg["status"] not in ("UNDER_LEVELING", "BUYOUT_IN_PROGRESS"):
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            409,
            "Trade package not in UNDER_LEVELING or BUYOUT_IN_PROGRESS",
        )
    project = get_project(pkg["project_id"])
    sub["status"] = "REPLACED"
    sub["default_flag"] = True
    sub["default_recorded_at"] = project["current_time_utc"]
    sub["estimated_replacement_cost_cents"] = estimated_replacement_cost_cents
    replacement = {
        "id": new_id(),
        "trade_package_id": sub["trade_package_id"],
        "subcontractor_name": sub["subcontractor_name"],
        "source_bid_id": sub["source_bid_id"],
        "replaces_subcontract_id": sub["id"],
        "replacement_subcontract_id": None,
        "flow_down_terms": sub["flow_down_terms"],
        "insurance_requirements_snapshot": dict(sub["insurance_requirements_snapshot"]),
        "payment_terms": dict(sub["payment_terms"]),
        "change_authority_limits": [dict(t) for t in sub["change_authority_limits"]],
        "contract_value_cents": 0,
        "cumulative_co_cents": 0,
        "negotiation_round": 0,
        "insurance_status": "MISSING",
        "bonding_requirement": (
            "NOT_REQUIRED" if pkg["bonding_policy"] == "WAIVED" else "PENDING_DECISION"
        ),
        "sov_status": "DRAFT",
        "default_flag": False,
        "default_recorded_at": None,
        "estimated_replacement_cost_cents": None,
        "status": "DRAFT",
    }
    stamp(replacement)
    DB["subcontracts"][replacement["id"]] = replacement
    sub["replacement_subcontract_id"] = replacement["id"]
    touch(sub)
    for cert in certs_of(sub):
        if cert["status"] == "ISSUED":
            cert["status"] = "SUPERSEDED"
            touch(cert)
    recompute_package(pkg)
    evaluate_package_bubble(pkg)
    return ok(ser_subcontract(sub))


@bp.post("/subcontracts/<sub_id>/terminate")
def terminate_subcontract(sub_id):
    auth(["OperationsManager"])
    sub = get_subcontract(sub_id)
    ensure_sub_not_terminal(sub)
    if sub["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION", 409, "Subcontract is not in DRAFT"
        )
    sub["status"] = "TERMINATED"
    touch(sub)
    pkg = package_of(sub)
    evaluate_package_bubble(pkg)
    return ok(ser_subcontract(sub))


@bp.get("/subcontracts/<sub_id>/negotiation-rounds")
def list_negotiation_rounds(sub_id):
    auth(STANDARD_READ_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    items = sorted_created(
        [r for r in DB["negotiation_rounds"].values() if r["subcontract_id"] == sub["id"]]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_round(r) for r in page], total, limit, offset)


@bp.get("/subcontracts/<sub_id>/replacements")
def list_replacements(sub_id):
    auth(ALL_ROLES)
    sub = get_subcontract(sub_id)
    limit, offset = pagination_args()
    items = sorted_created(
        [s for s in subs_of(package_of(sub)) if s.get("replaces_subcontract_id") == sub["id"]]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_subcontract(s) for s in page], total, limit, offset)


@bp.get("/bids/<bid_id>/subcontracts")
def list_bid_subcontracts(bid_id):
    auth(ALL_ROLES)
    bid = get_bid(bid_id)
    limit, offset = pagination_args()
    items = sorted_created(
        [s for s in DB["subcontracts"].values() if s["source_bid_id"] == bid["id"]]
    )
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_subcontract(s) for s in page], total, limit, offset)
