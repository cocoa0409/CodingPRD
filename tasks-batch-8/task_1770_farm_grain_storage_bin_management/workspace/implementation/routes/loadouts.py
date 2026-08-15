"""Load-out endpoints (PRD 3.5, 3.6): scheduling with contract OCC, dispatch,
scale-ticket delivery with per-ticket settlement shrink, settlement
confirmation with the allocation waterfall and tiered money, and voiding as a
compensating reversal."""
from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services import core
from util import (as_bu, as_dt, as_moisture, as_str, body, paginate_sorted,
                  present, query_enum, query_str, required, resolve_body_fk,
                  resolve_path)

bp = Blueprint("loadouts", __name__)


def _get_loadout(lid):
    return resolve_path(db.loadouts, lid, "loadout")


def _recompute_bin(bin_id):
    bin_rec = db.bins.get(bin_id)
    if bin_rec is not None:
        snap = core.bin_snap(bin_rec)
        core.recompute_inventory(bin_rec)
        core.recompute_posture(bin_rec)
        core.finalize_bin(bin_rec, snap)


@bp.route("/grain/loadouts", methods=["POST"])
def create_loadout():
    require_roles("SiteManager")
    data = body()
    # existence (4): body FKs left to right: contract_id, bin_id
    contract = resolve_body_fk(db.contracts, data, "contract_id", "contract")
    bin_rec = resolve_body_fk(db.bins, data, "bin_id", "bin")
    # OCC (5): expected_contract_version vs contract.version — fires before
    # request-shape validation, so a stale version masks a defective payload.
    if present(data, "expected_contract_version"):
        v = data["expected_contract_version"]
        if isinstance(v, int) and not isinstance(v, bool) and contract is not None:
            if v != contract["version"]:
                raise ApiError("ERR_STALE_CONTRACT_VERSION", 412,
                               "expected_contract_version does not match the contract")
    # shape (6)
    as_str(required(data, "contract_id"), "contract_id")
    bin_id = as_str(required(data, "bin_id"), "bin_id")
    start = as_dt(required(data, "scheduled_start"), "scheduled_start")
    end = as_dt(required(data, "scheduled_end"), "scheduled_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400,
                       "scheduled_end must be strictly after scheduled_start")
    planned = as_bu(required(data, "planned_bu"), "planned_bu")
    if planned <= 0:
        raise ApiError("ERR_VALIDATION", 400, "planned_bu must be > 0")
    raw_ver = required(data, "expected_contract_version")
    if not isinstance(raw_ver, int) or isinstance(raw_ver, bool):
        raise ApiError("ERR_VALIDATION", 400,
                       "expected_contract_version must be an integer")
    if contract is None or bin_rec is None:
        # unreachable: present FKs resolved above; absent FKs raised in required()
        raise ApiError("ERR_NOT_FOUND", 404, "related resource not found")
    # posture (15)
    if bin_rec["posture"] not in ("SOUND", "WATCH"):
        raise ApiError("ERR_BIN_POSTURE_BLOCKED", 409,
                       "bin posture blocks load-out scheduling")
    # window containment (20): within the contract window, both bounds inclusive
    if start < contract["window_start"] or end > contract["window_end"]:
        raise ApiError("ERR_OUTSIDE_DELIVERY_WINDOW", 409,
                       "load-out window must lie within the contract window")
    # overlap (21): HALF-OPEN [start, end) over live load-outs on the bin;
    # touching end-to-start is permitted.
    for other in db.loadouts.values():
        if other["bin_id"] != bin_id:
            continue
        if other["transport_status"] not in ("SCHEDULED", "HELD", "DISPATCHED"):
            continue
        if start < other["scheduled_end"] and end > other["scheduled_start"]:
            raise ApiError("ERR_WINDOW_OVERLAP", 409,
                           "load-out window overlaps another live load-out on the bin")
    # crop consistency (25)
    if bin_rec["crop"] != contract["crop"]:
        raise ApiError("ERR_CROP_MIX", 409,
                       "bin crop must equal contract crop")
    # referential state (29)
    if contract["status"] not in ("OPEN", "DELIVERING"):
        raise ApiError("ERR_CONTRACT_NOT_OPEN", 409,
                       "contract is not OPEN or DELIVERING")
    # fiscal (31): planned <= contracted - committed - delivered
    remaining = (contract["contracted_bu"] - core.committed_bu(contract)
                 - core.delivered_bu(contract))
    if planned > remaining:
        raise ApiError("ERR_CONTRACT_REMAINING_EXCEEDED", 409,
                       "planned_bu exceeds the contract's remaining bushels")

    rec = core.new_common()
    rec.update({
        "contract_id": contract["id"],
        "bin_id": bin_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "planned_bu": planned,
        "transport_status": "SCHEDULED",
        "settlement_status": "UNSETTLED",
        "scale_tickets": None,
        "delivered_at": None,
        "gross_bu": None,
        "ticket_shrink_bu": None,
        "settled_net_bu": None,
        "grain_value_cents": None,
        "service_fee_cents": None,
        "early_bonus_cents": None,
        "settlement_net_cents": None,
        "draws": [],
        "held_reason": None,
    })
    db.loadouts[rec["id"]] = rec

    # contract: committed_bu (derived) gains planned_bu; OPEN -> DELIVERING on
    # the first non-expired load-out; version increments by one.
    if contract["status"] == "OPEN":
        contract["status"] = "DELIVERING"
    core.touch(contract)
    return ok(core.loadout_view(rec), 201)


@bp.route("/grain/loadouts/<lid>", methods=["GET"])
def get_loadout(lid):
    require_roles(*ALL_ROLES)
    return ok(core.loadout_view(_get_loadout(lid)))


@bp.route("/grain/loadouts", methods=["GET"])
def list_loadouts():
    require_roles(*ALL_ROLES)
    f_contract = query_str("contract_id")
    f_bin = query_str("bin_id")
    f_transport = query_enum("transport_status", core.TRANSPORT_STATUSES)
    f_settlement = query_enum("settlement_status", core.SETTLEMENT_STATUSES)
    items = list(db.loadouts.values())
    if f_contract is not None:
        items = [l for l in items if l["contract_id"] == f_contract]
    if f_bin is not None:
        items = [l for l in items if l["bin_id"] == f_bin]
    if f_transport is not None:
        items = [l for l in items if l["transport_status"] == f_transport]
    if f_settlement is not None:
        items = [l for l in items if l["settlement_status"] == f_settlement]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([core.loadout_view(l) for l in page], total, limit, offset)


@bp.route("/grain/loadouts/<lid>/dispatch", methods=["POST"])
def dispatch_loadout(lid):
    require_roles("SiteManager")
    lo = _get_loadout(lid)
    # state (13)
    if lo["transport_status"] != "SCHEDULED":
        raise ApiError("ERR_LOADOUT_STATE", 409,
                       "dispatch requires transport_status SCHEDULED")
    # posture (15): re-checked at dispatch
    bin_rec = db.bins.get(lo["bin_id"])
    if bin_rec is None or bin_rec["posture"] not in ("SOUND", "WATCH"):
        raise ApiError("ERR_BIN_POSTURE_BLOCKED", 409,
                       "bin posture blocks dispatch")
    # contract (29)
    contract = db.contracts.get(lo["contract_id"])
    if contract is None or contract["status"] not in ("OPEN", "DELIVERING"):
        raise ApiError("ERR_CONTRACT_NOT_OPEN", 409,
                       "contract is not OPEN or DELIVERING")
    lo["transport_status"] = "DISPATCHED"
    core.touch(lo)
    return ok(core.loadout_view(lo))


@bp.route("/grain/loadouts/<lid>/deliver", methods=["POST"])
def deliver_loadout(lid):
    require_roles("SiteManager")
    lo = _get_loadout(lid)
    # shape (6) fires before the transport state check
    data = body()
    delivered_at = as_dt(required(data, "delivered_at"), "delivered_at")
    raw_tickets = required(data, "scale_tickets")
    if not isinstance(raw_tickets, list):
        raise ApiError("ERR_VALIDATION", 400, "scale_tickets must be an array")
    if len(raw_tickets) < 1:
        raise ApiError("ERR_VALIDATION", 400, "scale_tickets must be non-empty")
    seen = set()
    tickets = []
    for t in raw_tickets:
        if not isinstance(t, dict):
            raise ApiError("ERR_VALIDATION", 400, "each scale ticket must be an object")
        ticket_no = required(t, "ticket_no")
        if isinstance(ticket_no, bool) or not isinstance(ticket_no, (str, int)):
            raise ApiError("ERR_VALIDATION", 400, "ticket_no must be a string or integer")
        if ticket_no in seen:
            raise ApiError("ERR_VALIDATION", 400,
                           "ticket_no must be unique within the load-out")
        seen.add(ticket_no)
        gross = as_bu(required(t, "gross_bu"), "gross_bu")
        if gross <= 0:
            raise ApiError("ERR_VALIDATION", 400, "gross_bu must be > 0")
        moisture = as_moisture(required(t, "moisture_pct"), "moisture_pct")
        tickets.append({"ticket_no": ticket_no, "gross_bu": gross,
                        "moisture_pct": moisture})
    # state (13)
    if lo["transport_status"] != "DISPATCHED":
        raise ApiError("ERR_LOADOUT_STATE", 409,
                       "deliver requires transport_status DISPATCHED")

    # settlement_shrink: round per ticket, then sum (pinned rounding order).
    contract = db.contracts[lo["contract_id"]]
    total_gross = Decimal("0.00")
    total_shrink = Decimal("0.00")
    total_net = Decimal("0.00")
    for t in tickets:
        shrink = core.settlement_shrink_per_ticket(
            contract["crop"], t["gross_bu"], t["moisture_pct"])
        net = core.q2(t["gross_bu"] - shrink)
        total_gross += t["gross_bu"]
        total_shrink += shrink
        total_net += net

    lo["scale_tickets"] = tickets
    lo["delivered_at"] = delivered_at
    lo["gross_bu"] = core.q2(total_gross)
    lo["ticket_shrink_bu"] = core.q2(total_shrink)
    lo["settled_net_bu"] = core.q2(total_net)
    lo["transport_status"] = "DELIVERED"
    core.touch(lo)
    return ok(core.loadout_view(lo))


@bp.route("/grain/loadouts/<lid>/confirm-settlement", methods=["POST"])
def confirm_settlement(lid):
    require_roles("SiteManager")
    lo = _get_loadout(lid)
    # state (13) then settlement dimension (14), in that order
    if lo["transport_status"] != "DELIVERED":
        raise ApiError("ERR_LOADOUT_STATE", 409,
                       "confirm-settlement requires transport_status DELIVERED")
    if lo["settlement_status"] != "UNSETTLED":
        raise ApiError("ERR_SETTLEMENT_STATE", 409,
                       "confirm-settlement requires settlement_status UNSETTLED")
    # contract (29)
    contract = db.contracts.get(lo["contract_id"])
    if contract is None or contract["status"] not in ("OPEN", "DELIVERING"):
        raise ApiError("ERR_CONTRACT_NOT_OPEN", 409,
                       "contract is not OPEN or DELIVERING")

    # waterfall eligibility (30): check coverage before debiting anything
    eligible = [l for l in db.lots.values()
                if l["bin_id"] == lo["bin_id"]
                and l["status"] in ("STORED", "PARTIALLY_DRAWN")
                and l["current_bu"] > 0]
    eligible.sort(key=lambda l: (l["fill_date"], l["created_at"], l["seq"]))
    coverage = Decimal("0.00")
    for l in eligible:
        coverage += l["current_bu"]
    if core.q2(coverage) < lo["settled_net_bu"]:
        raise ApiError("ERR_LOTS_INSUFFICIENT", 409,
                       "eligible lot bushels cannot cover settled_net_bu")

    # settlement_charges (pinned evaluation order, tier keyed on pre-fee value)
    grain_value = core.q0(lo["settled_net_bu"] * contract["contract_unit_price_cents"])
    if grain_value < core.TIER1_FLOOR_CENTS:
        fee_bps = 150
    elif grain_value < core.TIER2_FLOOR_CENTS:
        fee_bps = 100
    else:
        fee_bps = 75
    service_fee = core.q0(Decimal(grain_value) * Decimal(fee_bps) / Decimal("10000"))
    if (contract["early_cutoff"] is not None
            and lo["delivered_at"] <= contract["early_cutoff"]):
        early_bonus = core.q0(lo["settled_net_bu"]
                              * contract["early_bonus_cents_per_bu"])
    else:
        early_bonus = 0
    settlement_net = grain_value - service_fee + early_bonus

    # allocation_waterfall: FIFO by fill_date, created_at tie-break
    remaining = lo["settled_net_bu"]
    draws = []
    for l in eligible:
        if remaining <= 0:
            break
        take = min(l["current_bu"], remaining)
        l["current_bu"] = core.q2(l["current_bu"] - take)
        l["drawn_bu"] = core.q2(l["drawn_bu"] + take)
        draws.append({"lot_id": l["id"], "bu": take})
        remaining = core.q2(remaining - take)
        if l["current_bu"] == 0:
            l["status"] = "DEPLETED"
        elif take > 0:
            l["status"] = "PARTIALLY_DRAWN"
        core.touch(l)

    lo["draws"] = draws
    lo["grain_value_cents"] = grain_value
    lo["service_fee_cents"] = service_fee
    lo["early_bonus_cents"] = early_bonus
    lo["settlement_net_cents"] = settlement_net
    lo["settlement_status"] = "SETTLED"
    core.touch(lo)

    # contract accumulation: delivered/value are derived from SETTLED
    # loadouts; version increments once; fulfillment judged in bushels.
    core.touch(contract)
    if contract["status"] in ("OPEN", "DELIVERING") and core.is_fulfilled(contract):
        contract["status"] = "FULFILLED"

    _recompute_bin(lo["bin_id"])
    return ok(core.loadout_view(lo))


@bp.route("/grain/loadouts/<lid>/void-settlement", methods=["POST"])
def void_settlement(lid):
    require_roles("SiteManager")
    lo = _get_loadout(lid)
    # settlement dimension (14)
    if lo["settlement_status"] != "SETTLED":
        raise ApiError("ERR_SETTLEMENT_STATE", 409,
                       "void-settlement requires settlement_status SETTLED")

    bin_rec = db.bins.get(lo["bin_id"])
    gated = bin_rec is not None and bin_rec["posture"] in ("ALERT", "FUMIGATION_LOCKOUT")
    # compensating reversal: credit each draw back to its lot
    for d in lo["draws"]:
        lot = db.lots.get(d["lot_id"])
        if lot is None:
            continue
        lot["current_bu"] = core.q2(lot["current_bu"] + d["bu"])
        lot["drawn_bu"] = core.q2(lot["drawn_bu"] - d["bu"])
        if gated:
            # A gated bin keeps its lots SUSPENDED; balances still reconcile.
            if lot["status"] != "SUSPENDED":
                lot["status"] = "SUSPENDED"
        elif lot["current_bu"] <= 0:
            lot["status"] = "DEPLETED"
        elif lot["drawn_bu"] > 0:
            lot["status"] = "PARTIALLY_DRAWN"
        else:
            lot["status"] = "STORED"
        core.touch(lot)

    lo["settlement_status"] = "VOIDED"
    core.touch(lo)

    contract = db.contracts.get(lo["contract_id"])
    if contract is not None:
        core.touch(contract)
        # FULFILLED falls back to DELIVERING when the reversal drops the
        # delivered bushels below the 98% threshold (revert transition).
        if contract["status"] == "FULFILLED" and not core.is_fulfilled(contract):
            contract["status"] = "DELIVERING"

    _recompute_bin(lo["bin_id"])
    return ok(core.loadout_view(lo))
