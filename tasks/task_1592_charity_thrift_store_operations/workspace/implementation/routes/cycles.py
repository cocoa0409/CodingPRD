"""WeeklyCycle + MissionTransfer + TaxReceipt endpoints (PRD §3.4, §3.9)."""
from flask import Blueprint

from db import db, new_record, touch, iso_now, parse_ts
from errors import (
    ApiError, not_found, invalid_request,
    ERR_CYCLE_INVALID_STATE, ERR_TILL_SESSIONS_UNCLOSED,
    ERR_STALE_CYCLE_VERSION, ERR_ALLOCATION_SUM_INVALID,
    ERR_TRANSFER_INVALID_STATE, ERR_SOD_APPROVER_IS_PREPARER,
    ERR_RECEIPT_INVALID_STATE, ERR_RECEIPT_LOCKED, ERR_NOT_FOUND,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import get_open_cycle, assign_item_to_bale

bp = Blueprint("cycles", __name__)

ROTATION_COLORS = {1: "RED", 2: "BLUE", 3: "GREEN", 0: "YELLOW"}
PROGRAMS = ["JOB_TRAINING", "YOUTH_SERVICES", "HOUSING_SUPPORT", "GENERAL_FUND"]


def cycle_view(c):
    return dict(c)


def transfer_view(t):
    return dict(t)


def receipt_view(r):
    return dict(r)


def _rotation_for(sequence_number):
    return ROTATION_COLORS[sequence_number % 4]


def _get_cycle(cycle_id):
    c = db.cycles.get(cycle_id)
    if c is None:
        raise not_found("weekly cycle")
    return c


def _get_transfer(transfer_id):
    t = db.transfers.get(transfer_id)
    if t is None:
        raise not_found("mission transfer")
    return t


@bp.route("/api/cycles", methods=["POST"])
def open_cycle():
    require_roles(["StoreManager"])
    get_body()
    if get_open_cycle() is not None:
        raise ApiError(ERR_CYCLE_INVALID_STATE, 409,
                       "At most one WeeklyCycle may be OPEN")
    seq = db.next_cycle_sequence()
    rec = new_record()
    rec.update({
        "sequence_number": seq,
        "rotation_color": _rotation_for(seq),
        "status": "OPEN",
        "opened_at": iso_now(),
        "closed_at": None,
        "markdown_runs_count": 0,
        "gross_sales_cents": None,
        "salvage_revenue_cents": None,
        "net_revenue_cents": None,
        "shrink_value_cents": None,
        "shrink_rate_bp": None,
        "shrink_alert_active": False,
    })
    db.cycles[rec["id"]] = rec
    return success_object(cycle_view(rec), status=201)


@bp.route("/api/cycles", methods=["GET"])
def list_cycles():
    require_roles(ALL_ROLES)
    filters = query_filters(["status"])
    records = apply_filters(list(db.cycles.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([cycle_view(c) for c in page], limit, offset, total)


@bp.route("/api/cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    require_roles(ALL_ROLES)
    return success_object(cycle_view(_get_cycle(cycle_id)))


@bp.route("/api/cycles/<cycle_id>/run-markdown", methods=["POST"])
def run_markdown(cycle_id):
    require_roles(["StoreManager"])
    get_body()
    cycle = _get_cycle(cycle_id)
    if cycle["status"] != "OPEN" or cycle["markdown_runs_count"] != 0:
        raise ApiError(ERR_CYCLE_INVALID_STATE, 409,
                       "run-markdown requires an OPEN cycle that has not yet run")
    now = db.clock.now()
    my_seq = cycle["sequence_number"]

    # step 1: hold auto-release — expired holds back to ON_FLOOR, exempt this run
    released_ids = set()
    for item in db.items.values():
        if item["status"] == "ON_HOLD" and item.get("hold_expires_at"):
            if parse_ts(item["hold_expires_at"]) <= now:
                item["status"] = "ON_FLOOR"
                item["hold_expires_at"] = None
                touch(item)
                released_ids.add(item["id"])

    # helper: floored in an earlier cycle (strict sequence <)
    def floored_earlier(item):
        fc = db.cycles.get(item.get("floor_cycle_id"))
        return fc is not None and fc["sequence_number"] < my_seq

    # Snapshot pre-run eligibility so an item that ENTERS round 3 in this run is
    # not pulled by the same run (corner test markdown_progression_prices:
    # "pull happens only on the NEXT eligible run"; scaffold step 3 pins
    # "markdown_round == 3" as the pre-run precondition).
    pre_run_pull_ids = {
        item["id"] for item in db.items.values()
        if item["status"] == "ON_FLOOR" and item["id"] not in released_ids
        and floored_earlier(item) and item["markdown_round"] == calc.MAX_MARKDOWN_ROUND
    }
    pre_run_markdown_ids = {
        item["id"] for item in db.items.values()
        if item["status"] == "ON_FLOOR" and item["id"] not in released_ids
        and floored_earlier(item) and item["markdown_round"] < calc.MAX_MARKDOWN_ROUND
    }

    # step 2: markdown — ON_FLOOR, earlier cycle, round < 3
    # (auto-released items this run are exempt even though they are ON_FLOOR now)
    for iid in pre_run_markdown_ids:
        item = db.items[iid]
        item["markdown_round"] += 1
        item["current_price_cents"] = calc.calc_markdown_price(
            item["base_price_cents"], item["markdown_round"])
        touch(item)

    # step 3: pull — ON_FLOOR, earlier cycle, already at round 3 -> PULLED_TO_SALVAGE
    for iid in pre_run_pull_ids:
        item = db.items[iid]
        item["salvage_category"] = calc.CATEGORY_TO_SALVAGE[item["category"]]
        if item.get("weight_lbs") is None:
            item["weight_lbs"] = calc.CATEGORY_AVG_WEIGHT_LBS[item["category"]]
        item["status"] = "PULLED_TO_SALVAGE"
        assign_item_to_bale(item, item["salvage_category"])
        touch(item)

    cycle["markdown_runs_count"] = 1
    touch(cycle)
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycle_id>/close", methods=["POST"])
def close_cycle(cycle_id):
    require_roles(["StoreManager"])
    get_body()
    cycle = _get_cycle(cycle_id)
    if cycle["status"] != "OPEN":
        raise ApiError(ERR_CYCLE_INVALID_STATE, 409,
                       "close requires an OPEN cycle")
    # every till session must be CLOSED
    for s in db.till_sessions.values():
        if s["status"] in ("OPEN", "PENDING_APPROVAL", "RECONCILED"):
            raise ApiError(ERR_TILL_SESSIONS_UNCLOSED, 409,
                           "A till session is still OPEN, PENDING_APPROVAL, or RECONCILED")
    # cascade A: dispose SALVAGE items
    for item in db.items.values():
        if item["status"] == "SALVAGE":
            item["status"] = "DISPOSED"
            touch(item)
    cycle["closed_at"] = iso_now()
    closed_dt = parse_ts(cycle["closed_at"])
    opened_dt = parse_ts(cycle["opened_at"])
    # revenue snapshot — half-open window [opened_at, closed_at)
    gross = 0
    for s in db.sales.values():
        if s["status"] != "COMPLETED":
            continue
        created = parse_ts(s["created_at"])
        if opened_dt <= created < closed_dt:
            gross += s["total_cents"]
    salvage_rev = sum(
        b["settled_revenue_cents"] or 0
        for b in db.bales.values()
        if b.get("settled_cycle_id") == cycle["id"])
    cycle["gross_sales_cents"] = gross
    cycle["salvage_revenue_cents"] = salvage_rev
    cycle["net_revenue_cents"] = gross + salvage_rev
    shrink_value = sum(
        i["value_at_shrink_cents"] or 0
        for i in db.items.values()
        if i.get("shrunk_cycle_id") == cycle["id"])
    cycle["shrink_value_cents"] = shrink_value
    cycle["shrink_rate_bp"] = calc.calc_shrink_rate_bp(shrink_value, gross)
    cycle["status"] = "CLOSED"
    touch(cycle)
    # cascade B: spawn the next cycle with the shrink posture copied forward
    seq = db.next_cycle_sequence()
    nxt = new_record()
    nxt.update({
        "sequence_number": seq,
        "rotation_color": _rotation_for(seq),
        "status": "OPEN",
        "opened_at": iso_now(),
        "closed_at": None,
        "markdown_runs_count": 0,
        "gross_sales_cents": None,
        "salvage_revenue_cents": None,
        "net_revenue_cents": None,
        "shrink_value_cents": None,
        "shrink_rate_bp": None,
        "shrink_alert_active": cycle["shrink_rate_bp"] >= calc.SHRINK_ALERT_BP,
    })
    db.cycles[nxt["id"]] = nxt
    return success_object(cycle_view(cycle))


@bp.route("/api/cycles/<cycle_id>/mission-transfers", methods=["POST"])
def create_transfer(cycle_id):
    user_id, role = require_roles(["FinanceClerk"])
    payload = get_body(
        required=[("expected_cycle_version", "integer"), ("allocations", "array")],
    )
    cycle = _get_cycle(cycle_id)
    # priority 6: state
    if cycle["status"] != "CLOSED":
        raise ApiError(ERR_CYCLE_INVALID_STATE, 409,
                       "mission transfer requires a CLOSED cycle")
    # priority 7: OCC
    if payload["expected_cycle_version"] != cycle["version"]:
        raise ApiError(ERR_STALE_CYCLE_VERSION, 412,
                       "expected_cycle_version does not match the cycle version")
    allocations = payload["allocations"]
    if len(allocations) == 0:
        raise invalid_request("allocations must be a non-empty array")
    pct_total = 0.0
    parsed = []
    for line in allocations:
        if not isinstance(line, dict):
            raise invalid_request("allocations entries must be objects")
        for key in line:
            if key not in ("program", "pct"):
                raise invalid_request("Unknown allocation field: %s" % key)
        if line.get("program") not in PROGRAMS:
            raise invalid_request("allocation program is not a declared program")
        pct = line.get("pct")
        if not isinstance(pct, (int, float)) or isinstance(pct, bool):
            raise invalid_request("allocation pct must be a number")
        if not (0 < float(pct) <= 100):
            raise invalid_request("allocation pct must be in (0, 100]")
        # up to three decimal places
        from decimal import Decimal
        dec = Decimal(str(pct))
        if -dec.as_tuple().exponent > 3:
            raise invalid_request("allocation pct allows up to three decimal places")
        pct_total += float(pct)
        parsed.append({"program": line["program"], "pct": pct})
    if abs(pct_total - 100.0) > 1e-9:
        raise ApiError(ERR_ALLOCATION_SUM_INVALID, 422,
                       "Transfer allocation pct values must sum to exactly 100")
    # supersede any existing DRAFT transfer for this cycle
    for t in db.transfers.values():
        if t["cycle_id"] == cycle["id"] and t["status"] == "DRAFT":
            t["status"] = "CANCELLED"
            touch(t)
    gross_pool = cycle["net_revenue_cents"] or 0
    reserve_pct, reserve_cents, net_pool, amounts = calc.calc_mission_pool(
        gross_pool, parsed)
    rec = new_record()
    rec.update({
        "cycle_id": cycle["id"],
        "prepared_by_user_id": user_id,
        "allocations": parsed,
        "gross_pool_cents": gross_pool,
        "reserve_pct": reserve_pct,
        "reserve_cents": reserve_cents,
        "net_pool_cents": net_pool,
        "allocation_amounts": amounts,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "disbursed_at": None,
    })
    db.transfers[rec["id"]] = rec
    touch(cycle)  # creation bumps the cycle's version
    return success_object(transfer_view(rec), status=201)


@bp.route("/api/mission-transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    require_roles(ALL_ROLES)
    return success_object(transfer_view(_get_transfer(transfer_id)))


@bp.route("/api/mission-transfers", methods=["GET"])
def list_transfers():
    require_roles(ALL_ROLES)
    filters = query_filters(["cycle_id", "status"])
    records = apply_filters(list(db.transfers.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([transfer_view(t) for t in page], limit, offset, total)


@bp.route("/api/mission-transfers/<transfer_id>/approve", methods=["POST"])
def approve_transfer(transfer_id):
    user_id, role = require_roles(["StoreManager"])
    get_body()
    t = _get_transfer(transfer_id)
    if t["status"] != "DRAFT":
        raise ApiError(ERR_TRANSFER_INVALID_STATE, 409,
                       "approve requires a DRAFT transfer")
    if user_id == t["prepared_by_user_id"]:
        raise ApiError(ERR_SOD_APPROVER_IS_PREPARER, 422,
                       "Transfer approver must differ from the preparer")
    t["approved_by_user_id"] = user_id
    t["status"] = "APPROVED"
    touch(t)
    return success_object(transfer_view(t))


@bp.route("/api/mission-transfers/<transfer_id>/disburse", methods=["POST"])
def disburse_transfer(transfer_id):
    require_roles(["FinanceClerk"])
    get_body()
    t = _get_transfer(transfer_id)
    if t["status"] != "APPROVED":
        raise ApiError(ERR_TRANSFER_INVALID_STATE, 409,
                       "disburse requires an APPROVED transfer")
    t["status"] = "DISBURSED"
    t["disbursed_at"] = iso_now()
    touch(t)
    return success_object(transfer_view(t))


@bp.route("/api/tax-receipts/<receipt_id>", methods=["GET"])
def get_receipt(receipt_id):
    require_roles(ALL_ROLES)
    r = db.receipts.get(receipt_id)
    if r is None:
        raise not_found("tax receipt")
    return success_object(receipt_view(r))


@bp.route("/api/tax-receipts", methods=["GET"])
def list_receipts():
    require_roles(ALL_ROLES)
    filters = query_filters(["batch_id", "donor_id", "status"])
    records = apply_filters(list(db.receipts.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([receipt_view(r) for r in page], limit, offset, total)


@bp.route("/api/tax-receipts/<receipt_id>/void", methods=["POST"])
def void_receipt(receipt_id):
    require_roles(["StoreManager"])
    get_body()
    r = db.receipts.get(receipt_id)
    if r is None:
        raise not_found("tax receipt")
    if r["status"] != "ISSUED":
        raise ApiError(ERR_RECEIPT_INVALID_STATE, 409,
                       "Only an ISSUED receipt can be voided")
    batch = db.batches.get(r["batch_id"])
    if batch is not None and batch["status"] == "CLOSED":
        raise ApiError(ERR_RECEIPT_LOCKED, 422,
                       "Receipt void after the owning batch reached CLOSED")
    r["status"] = "VOIDED"
    r["voided_at"] = iso_now()
    touch(r)
    return success_object(receipt_view(r))
