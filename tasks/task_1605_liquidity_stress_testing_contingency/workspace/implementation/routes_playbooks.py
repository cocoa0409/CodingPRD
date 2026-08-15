"""Routes: contingency playbooks, playbook actions, borrowing lines,
collateral pledges."""
from datetime import timedelta

from flask import Blueprint, g, request

from db import mint_id, store
from errors import (
    ApiError,
    ERR_ACTIONS_NOT_ALL_TERMINAL,
    ERR_ASSET_NOT_AVAILABLE,
    ERR_ASSET_NOT_PLEDGEABLE,
    ERR_INSUFFICIENT_BORROWING_POWER,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LINE_SUSPENDED,
    ERR_NOT_FOUND,
    ERR_PLAYBOOK_ALREADY_ACTIVE,
    ERR_POSTURE_INSUFFICIENT,
    ERR_PREREQUISITE_ACTION_INCOMPLETE,
    ERR_REPAY_EXCEEDS_DRAWN,
    ERR_SETTLEMENT_NOT_DUE,
    ERR_SOD_VIOLATION,
    ERR_STALE_VERSION,
)
from helpers import (
    MISSING,
    fmt_dt,
    get_json_body,
    new_entity,
    opt_enum,
    opt_int,
    opt_str,
    paginate,
    pub,
    req_enum,
    req_int,
    req_str,
    sorted_by_created,
    touch,
)
from middleware import BIZ4, require_roles
from responses import ok, ok_list
from services import (
    POSTURE_ORD,
    block_line_actions,
    capacity_test,
    current_posture_level,
    recompute_line,
    wake_line_actions,
)

bp = Blueprint("playbooks", __name__)

POSTURES = ("NORMAL", "HEIGHTENED", "SEVERE", "CRISIS")
ACTION_KINDS = ("ASSET_SALE", "LINE_DRAWDOWN")
LINE_TYPES = ("FED_DISCOUNT_WINDOW", "FHLB", "REPO")


def _get_or_404(table, entity_id, label):
    ent = table.get(entity_id)
    if ent is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"{label} not found: {entity_id}")
    return ent


# ---------------------------------------------------------------------------
# Contingency playbooks
# ---------------------------------------------------------------------------
@bp.post("/liquidity/contingency-playbooks")
@require_roles("TreasuryAnalyst")
def create_playbook():
    body = get_json_body(required=True)
    # Existence (priority 3) precedes remaining shape checks (priority 4).
    raw_scenario = body.get("scenario_id")
    if isinstance(raw_scenario, str) and raw_scenario not in store.scenarios:
        raise ApiError(ERR_NOT_FOUND, 404, f"StressScenario not found: {raw_scenario}")
    name = req_str(body, "name")
    scenario_id = req_str(body, "scenario_id")
    min_posture = req_enum(body, "min_activation_posture", POSTURES)
    target = req_int(body, "target_capacity_cents", min_v=1)
    ent = new_entity({
        "id": mint_id(),
        "name": name,
        "scenario_id": scenario_id,
        "min_activation_posture": min_posture,
        "target_capacity_cents": target,
        "status": "DRAFT",
        "created_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "tested_at": None,
        "activated_at": None,
    })
    store.playbooks[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/contingency-playbooks")
@require_roles(*BIZ4)
def list_playbooks():
    items = list(store.playbooks.values())
    scenario_id = request.args.get("scenario_id")
    status = request.args.get("status")
    if scenario_id is not None:
        items = [p for p in items if p["scenario_id"] == scenario_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(p) for p in page], pagination)


@bp.get("/liquidity/contingency-playbooks/<playbook_id>")
@require_roles(*BIZ4)
def get_playbook(playbook_id):
    return ok(pub(_get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")))


@bp.patch("/liquidity/contingency-playbooks/<playbook_id>")
@require_roles("TreasuryAnalyst")
def patch_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    body = get_json_body(required=True)
    expected = req_int(body, "expected_playbook_version")
    name = opt_str(body, "name", default=MISSING)
    min_posture = opt_enum(body, "min_activation_posture", POSTURES, default=MISSING)
    target = opt_int(body, "target_capacity_cents", default=MISSING, min_v=1)
    # OCC (priority 5) precedes the state check (priority 6).
    if expected != pb["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412,
            "expected_playbook_version does not match the playbook's current version.")
    if pb["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not DRAFT.")
    if name is not MISSING:
        pb["name"] = name
    if min_posture is not MISSING:
        pb["min_activation_posture"] = min_posture
    if target is not MISSING:
        pb["target_capacity_cents"] = target
    touch(pb)
    return ok(pub(pb))


# ---------------------------------------------------------------------------
# Playbook actions
# ---------------------------------------------------------------------------
@bp.post("/liquidity/contingency-playbooks/<playbook_id>/actions")
@require_roles("TreasuryAnalyst")
def create_action(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    body = get_json_body(required=True)
    # Existence of body-supplied FKs (priority 3) precedes cross-field shape
    # rules (priority 4).
    raw_asset = body.get("asset_id")
    raw_line = body.get("line_id")
    raw_prereq = body.get("prerequisite_action_id")
    if isinstance(raw_asset, str) and raw_asset not in store.assets:
        raise ApiError(ERR_NOT_FOUND, 404, f"LiquidAsset not found: {raw_asset}")
    if isinstance(raw_line, str) and raw_line not in store.lines:
        raise ApiError(ERR_NOT_FOUND, 404, f"BorrowingLine not found: {raw_line}")
    if isinstance(raw_prereq, str) and raw_prereq not in store.actions:
        raise ApiError(ERR_NOT_FOUND, 404, f"PlaybookAction not found: {raw_prereq}")

    kind = req_enum(body, "kind", ACTION_KINDS)
    sequence_no = req_int(body, "sequence_no", min_v=1)
    est = req_int(body, "estimated_proceeds_cents", min_v=1)
    lag = req_int(body, "settlement_lag_days", min_v=0)

    # Kind-required references.
    if kind == "ASSET_SALE":
        if raw_asset is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "asset_id is required when kind == ASSET_SALE.")
        if raw_line is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line_id is forbidden when kind == ASSET_SALE.")
    else:
        if raw_line is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "line_id is required when kind == LINE_DRAWDOWN.")
        if raw_asset is not None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "asset_id is forbidden when kind == LINE_DRAWDOWN.")
    if raw_asset is not None and not isinstance(raw_asset, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field asset_id must be a string.")
    if raw_line is not None and not isinstance(raw_line, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field line_id must be a string.")

    # Prerequisite: same playbook, strictly smaller sequence_no.
    if raw_prereq is not None:
        if not isinstance(raw_prereq, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Field prerequisite_action_id must be a string.")
        prereq = store.actions[raw_prereq]
        if prereq["playbook_id"] != pb["id"] or prereq["sequence_no"] >= sequence_no:
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "prerequisite_action_id must reference an action of the same "
                "playbook with a strictly smaller sequence_no.")

    # sequence_no unique within the playbook.
    if any(a["playbook_id"] == pb["id"] and a["sequence_no"] == sequence_no
           for a in store.actions.values()):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            f"sequence_no {sequence_no} already exists within this playbook.")

    if pb["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not DRAFT.")

    ent = new_entity({
        "id": mint_id(),
        "playbook_id": pb["id"],
        "kind": kind,
        "sequence_no": sequence_no,
        "estimated_proceeds_cents": est,
        "settlement_lag_days": lag,
        "asset_id": raw_asset,
        "line_id": raw_line,
        "prerequisite_action_id": raw_prereq,
        "status": "PENDING",
        "executed_at": None,
    })
    store.actions[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/contingency-playbooks/<playbook_id>/actions")
@require_roles(*BIZ4)
def list_playbook_actions(playbook_id):
    _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    items = [a for a in store.actions.values() if a["playbook_id"] == playbook_id]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(a) for a in page], pagination)


@bp.get("/liquidity/playbook-actions/<action_id>")
@require_roles(*BIZ4)
def get_action(action_id):
    return ok(pub(_get_or_404(store.actions, action_id, "PlaybookAction")))


@bp.get("/liquidity/playbook-actions")
@require_roles(*BIZ4)
def list_actions():
    items = list(store.actions.values())
    for param in ("playbook_id", "prerequisite_action_id", "line_id", "asset_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(a) for a in page], pagination)


# ---------------------------------------------------------------------------
# Playbook lifecycle transitions
# ---------------------------------------------------------------------------
@bp.post("/liquidity/contingency-playbooks/<playbook_id>/capacity-test")
@require_roles("RiskOfficer")
def run_capacity_test(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    # Shape (priority 4): at least one action required.
    actions = [a for a in store.actions.values() if a["playbook_id"] == pb["id"]]
    if not actions:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Capacity test requires at least one PlaybookAction.")
    if pb["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not DRAFT.")
    result = capacity_test(pb)
    if result["result"] == "PASSED":
        pb["status"] = "TESTED"
        pb["tested_at"] = fmt_dt(store.clock)
        touch(pb)
    return ok(result)


@bp.post("/liquidity/contingency-playbooks/<playbook_id>/approve")
@require_roles("RiskOfficer")
def approve_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    if pb["status"] != "TESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not TESTED.")
    if g.user_id == pb["created_by_user_id"]:
        raise ApiError(
            ERR_SOD_VIOLATION, 403,
            "Approver must differ from the playbook creator.")
    pb["status"] = "APPROVED"
    pb["approved_by_user_id"] = g.user_id
    touch(pb)
    return ok(pub(pb))


@bp.post("/liquidity/contingency-playbooks/<playbook_id>/activate")
@require_roles("LiquidityCommittee")
def activate_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    if pb["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not APPROVED.")
    current = current_posture_level()
    if POSTURE_ORD[current] < POSTURE_ORD[pb["min_activation_posture"]]:
        raise ApiError(
            ERR_POSTURE_INSUFFICIENT, 409,
            "Current posture is below the playbook's min_activation_posture.")
    if any(
        p["id"] != pb["id"] and p["status"] in ("ACTIVATED", "EXECUTING")
        for p in store.playbooks.values()
    ):
        raise ApiError(
            ERR_PLAYBOOK_ALREADY_ACTIVE, 409,
            "Another playbook already holds status ACTIVATED or EXECUTING.")
    pb["status"] = "ACTIVATED"
    pb["activated_at"] = fmt_dt(store.clock)
    for a in store.actions.values():
        if a["playbook_id"] == pb["id"] and a["status"] == "PENDING":
            a["status"] = "READY"
            touch(a)
    touch(pb)
    return ok(pub(pb))


@bp.post("/liquidity/contingency-playbooks/<playbook_id>/stand-down")
@require_roles("LiquidityCommittee")
def stand_down_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    if pb["status"] not in ("ACTIVATED", "EXECUTING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not ACTIVATED or EXECUTING.")
    if any(a["playbook_id"] == pb["id"] and a["status"] == "EXECUTING"
           for a in store.actions.values()):
        raise ApiError(ERR_INVALID_STATE, 409, "An action is still EXECUTING.")
    for a in store.actions.values():
        if a["playbook_id"] == pb["id"] and a["status"] in ("PENDING", "READY", "BLOCKED"):
            a["status"] = "SKIPPED"
            touch(a)
    pb["status"] = "STOOD_DOWN"
    touch(pb)
    return ok(pub(pb))


@bp.post("/liquidity/contingency-playbooks/<playbook_id>/revise")
@require_roles("TreasuryAnalyst")
def revise_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    if pb["status"] != "STOOD_DOWN":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not STOOD_DOWN.")
    pb["status"] = "DRAFT"
    pb["tested_at"] = None
    pb["approved_by_user_id"] = None
    for a in store.actions.values():
        if a["playbook_id"] == pb["id"] and a["status"] == "SKIPPED":
            a["status"] = "PENDING"
            touch(a)
    touch(pb)
    return ok(pub(pb))


@bp.post("/liquidity/contingency-playbooks/<playbook_id>/complete")
@require_roles("LiquidityCommittee")
def complete_playbook(playbook_id):
    pb = _get_or_404(store.playbooks, playbook_id, "ContingencyPlaybook")
    if pb["status"] != "EXECUTING":
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not EXECUTING.")
    if any(
        a["playbook_id"] == pb["id"] and a["status"] not in ("SETTLED", "FAILED", "SKIPPED")
        for a in store.actions.values()
    ):
        raise ApiError(
            ERR_ACTIONS_NOT_ALL_TERMINAL, 409,
            "All PlaybookActions must be in {SETTLED, FAILED, SKIPPED} to complete.")
    pb["status"] = "COMPLETED"
    touch(pb)
    return ok(pub(pb))


# ---------------------------------------------------------------------------
# Action execution lifecycle
# ---------------------------------------------------------------------------
@bp.post("/liquidity/playbook-actions/<action_id>/execute")
@require_roles("TreasuryOps")
def execute_action(action_id):
    a = _get_or_404(store.actions, action_id, "PlaybookAction")
    if a["status"] != "READY":
        raise ApiError(ERR_INVALID_STATE, 409, "PlaybookAction is not READY.")
    pb = store.playbooks.get(a["playbook_id"])
    if pb is None or pb["status"] not in ("ACTIVATED", "EXECUTING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Playbook is not ACTIVATED or EXECUTING.")
    # Business-safety gates (priority 7).
    if a["kind"] == "ASSET_SALE":
        asset = store.assets.get(a["asset_id"])
        if asset is None or asset["encumbrance_status"] != "UNENCUMBERED":
            raise ApiError(
                ERR_ASSET_NOT_AVAILABLE, 409,
                "Referenced asset is not UNENCUMBERED.")
    else:
        line = store.lines.get(a["line_id"])
        if line is None:
            raise ApiError(ERR_NOT_FOUND, 404, "BorrowingLine not found.")
        if line["status"] != "ACTIVE":
            raise ApiError(ERR_LINE_SUSPENDED, 409, "Referenced line is SUSPENDED.")
    # Prerequisite enforcement (priority 9).
    if a["prerequisite_action_id"] is not None:
        prereq = store.actions.get(a["prerequisite_action_id"])
        if prereq is None or prereq["status"] != "SETTLED":
            raise ApiError(
                ERR_PREREQUISITE_ACTION_INCOMPLETE, 409,
                "Prerequisite action is not SETTLED.")
    # Fiscal bound (priority 10).
    if a["kind"] == "LINE_DRAWDOWN":
        line = store.lines[a["line_id"]]
        if a["estimated_proceeds_cents"] > line["borrowing_power_cents"]:
            raise ApiError(
                ERR_INSUFFICIENT_BORROWING_POWER, 409,
                "estimated_proceeds_cents exceeds borrowing_power_cents.")

    a["executed_at"] = fmt_dt(store.clock)
    a["status"] = "EXECUTING"
    if a["kind"] == "ASSET_SALE":
        asset = store.assets[a["asset_id"]]
        asset["encumbrance_status"] = "SOLD"
        touch(asset)
    else:
        line = store.lines[a["line_id"]]
        line["drawn_cents"] += a["estimated_proceeds_cents"]
        recompute_line(line)
        touch(line)
    if pb["status"] == "ACTIVATED":
        pb["status"] = "EXECUTING"
        touch(pb)
    touch(a)
    return ok(pub(a))


@bp.post("/liquidity/playbook-actions/<action_id>/settle")
@require_roles("TreasuryOps")
def settle_action(action_id):
    a = _get_or_404(store.actions, action_id, "PlaybookAction")
    if a["status"] != "EXECUTING":
        raise ApiError(ERR_INVALID_STATE, 409, "PlaybookAction is not EXECUTING.")
    from helpers import parse_dt
    executed_dt = parse_dt(a["executed_at"])
    if store.clock < executed_dt + timedelta(days=a["settlement_lag_days"]):
        raise ApiError(
            ERR_SETTLEMENT_NOT_DUE, 409,
            "Logical clock has not reached executed_at + settlement_lag_days.")
    a["status"] = "SETTLED"
    touch(a)
    return ok(pub(a))


@bp.post("/liquidity/playbook-actions/<action_id>/fail")
@require_roles("TreasuryOps")
def fail_action(action_id):
    a = _get_or_404(store.actions, action_id, "PlaybookAction")
    if a["status"] != "EXECUTING":
        raise ApiError(ERR_INVALID_STATE, 409, "PlaybookAction is not EXECUTING.")
    a["status"] = "FAILED"
    if a["kind"] == "LINE_DRAWDOWN":
        line = store.lines.get(a["line_id"])
        if line is not None:
            line["drawn_cents"] -= a["estimated_proceeds_cents"]
            recompute_line(line)
            touch(line)
    touch(a)
    return ok(pub(a))


# ---------------------------------------------------------------------------
# Borrowing lines
# ---------------------------------------------------------------------------
@bp.post("/liquidity/borrowing-lines")
@require_roles("TreasuryOps")
def create_line():
    body = get_json_body(required=True)
    provider = req_str(body, "provider_name")
    line_type = req_enum(body, "line_type", LINE_TYPES)
    capacity = req_int(body, "total_capacity_cents", min_v=1)
    rate = req_int(body, "advance_rate_bps", 1, 10000)
    ent = new_entity({
        "id": mint_id(),
        "provider_name": provider,
        "line_type": line_type,
        "total_capacity_cents": capacity,
        "advance_rate_bps": rate,
        "pledged_value_cents": 0,
        "drawn_cents": 0,
        "borrowing_power_cents": 0,
        "status": "ACTIVE",
    })
    store.lines[ent["id"]] = ent
    return ok(pub(ent), status=201)


@bp.get("/liquidity/borrowing-lines/<line_id>")
@require_roles(*BIZ4)
def get_line(line_id):
    return ok(pub(_get_or_404(store.lines, line_id, "BorrowingLine")))


@bp.post("/liquidity/borrowing-lines/<line_id>/suspend")
@require_roles("RiskOfficer")
def suspend_line(line_id):
    line = _get_or_404(store.lines, line_id, "BorrowingLine")
    if line["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "BorrowingLine is not ACTIVE.")
    line["status"] = "SUSPENDED"
    block_line_actions(line)
    touch(line)
    return ok(pub(line))


@bp.post("/liquidity/borrowing-lines/<line_id>/reinstate")
@require_roles("RiskOfficer")
def reinstate_line(line_id):
    line = _get_or_404(store.lines, line_id, "BorrowingLine")
    if line["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "BorrowingLine is not SUSPENDED.")
    collateral_cap = line["pledged_value_cents"] * line["advance_rate_bps"] // 10000
    if line["drawn_cents"] > min(line["total_capacity_cents"], collateral_cap):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "drawn_cents exceeds min(total_capacity_cents, collateral cap).")
    line["status"] = "ACTIVE"
    wake_line_actions(line)
    touch(line)
    return ok(pub(line))


@bp.post("/liquidity/borrowing-lines/<line_id>/draw")
@require_roles("TreasuryOps")
def draw_line(line_id):
    line = _get_or_404(store.lines, line_id, "BorrowingLine")
    body = get_json_body(required=True)
    amount = req_int(body, "amount_cents")
    if line["status"] != "ACTIVE":
        raise ApiError(ERR_LINE_SUSPENDED, 409, "BorrowingLine is SUSPENDED.")
    if amount <= 0 or amount > line["borrowing_power_cents"]:
        raise ApiError(
            ERR_INSUFFICIENT_BORROWING_POWER, 409,
            "amount_cents must be > 0 and <= borrowing_power_cents.")
    line["drawn_cents"] += amount
    recompute_line(line)
    touch(line)
    return ok(pub(line))


@bp.post("/liquidity/borrowing-lines/<line_id>/repay")
@require_roles("TreasuryOps")
def repay_line(line_id):
    line = _get_or_404(store.lines, line_id, "BorrowingLine")
    body = get_json_body(required=True)
    amount = req_int(body, "amount_cents")
    if amount <= 0 or amount > line["drawn_cents"]:
        raise ApiError(
            ERR_REPAY_EXCEEDS_DRAWN, 409,
            "amount_cents must be > 0 and <= drawn_cents.")
    line["drawn_cents"] -= amount
    recompute_line(line)
    touch(line)
    return ok(pub(line))


# ---------------------------------------------------------------------------
# Collateral pledges
# ---------------------------------------------------------------------------
@bp.post("/liquidity/collateral-pledges")
@require_roles("TreasuryOps")
def create_pledge():
    body = get_json_body(required=True)
    raw_asset = body.get("asset_id")
    raw_line = body.get("line_id")
    if isinstance(raw_asset, str) and raw_asset not in store.assets:
        raise ApiError(ERR_NOT_FOUND, 404, f"LiquidAsset not found: {raw_asset}")
    if isinstance(raw_line, str) and raw_line not in store.lines:
        raise ApiError(ERR_NOT_FOUND, 404, f"BorrowingLine not found: {raw_line}")
    asset_id = req_str(body, "asset_id")
    line_id = req_str(body, "line_id")
    asset = store.assets[asset_id]
    line = store.lines[line_id]
    if line["status"] != "ACTIVE":
        raise ApiError(ERR_LINE_SUSPENDED, 409, "Referenced line is SUSPENDED.")
    if asset["encumbrance_status"] != "UNENCUMBERED":
        raise ApiError(
            ERR_ASSET_NOT_PLEDGEABLE, 409,
            "Referenced asset is not UNENCUMBERED.")
    # Pin pledged value at BASELINE haircut (add-on 0); never re-priced.
    pinned = asset["market_value_cents"] * (10000 - asset["haircut_bps"]) // 10000
    ent = new_entity({
        "id": mint_id(),
        "asset_id": asset_id,
        "line_id": line_id,
        "pledged_value_cents": pinned,
        "status": "ACTIVE",
    })
    store.pledges[ent["id"]] = ent
    asset["encumbrance_status"] = "PLEDGED"
    touch(asset)
    recompute_line(line)
    touch(line)
    return ok(pub(ent), status=201)


@bp.get("/liquidity/collateral-pledges")
@require_roles(*BIZ4)
def list_pledges():
    items = list(store.pledges.values())
    for param in ("asset_id", "line_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[param] == v]
    page, pagination = paginate(sorted_by_created(items))
    return ok_list([pub(p) for p in page], pagination)


@bp.get("/liquidity/collateral-pledges/<pledge_id>")
@require_roles(*BIZ4)
def get_pledge(pledge_id):
    return ok(pub(_get_or_404(store.pledges, pledge_id, "CollateralPledge")))


@bp.post("/liquidity/collateral-pledges/<pledge_id>/release")
@require_roles("TreasuryOps")
def release_pledge(pledge_id):
    pledge = _get_or_404(store.pledges, pledge_id, "CollateralPledge")
    if pledge["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "CollateralPledge is not ACTIVE.")
    pledge["status"] = "RELEASED"
    touch(pledge)
    asset = store.assets.get(pledge["asset_id"])
    if asset is not None and asset["encumbrance_status"] == "PLEDGED":
        asset["encumbrance_status"] = "UNENCUMBERED"
        touch(asset)
    line = store.lines.get(pledge["line_id"])
    if line is not None:
        recompute_line(line)  # may auto-suspend and block actions
        touch(line)
    return ok(pub(pledge))
