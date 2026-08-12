"""Settlements: PER_UNIT_PERIOD sweeps and LUMP_MILESTONE installments."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_enum, f_date, bad_request, err, paginate, get_contract,
    get_settlement, sale_of_contract, prescription_of_sale,
    tract_of_contract, settlement_out, check_transition, today,
    parse_date_str, D, rhu,
)

bp = Blueprint("settlements", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

SETTLEMENT_TERMINAL = {"PAID", "REFUNDED", "VOID"}
KINDS = {"PER_UNIT_PERIOD", "LUMP_MILESTONE"}
MILESTONES = {"MOBILIZATION", "MIDPOINT", "COMPLETION"}
MILESTONE_ORDER = ["MOBILIZATION", "MIDPOINT", "COMPLETION"]

HOLDBACK_PCT = Decimal("10")
FEE_TIER1_MAX = 5000000
FEE_TIER2_MAX = 20000000
PAYMENT_TERMS_DAYS = 30


def consulting_fee(billed_before, gross):
    tentative = billed_before + gross
    if tentative <= FEE_TIER1_MAX:
        pct = Decimal("0.08")
    elif tentative <= FEE_TIER2_MAX:
        pct = Decimal("0.065")
    else:
        pct = Decimal("0.05")
    return rhu(D(gross) * pct)


def _winning_bid_rates(contract):
    sale = sale_of_contract(contract)
    if sale is None or not sale.get("winning_bid_id"):
        return {}
    bid = db["bids"].get(sale["winning_bid_id"])
    if not bid or not bid.get("species_rates"):
        return {}
    return {e["species"]: e["rate_cents_per_mbf"]
            for e in bid["species_rates"]}


def _certified_total(contract):
    sale = sale_of_contract(contract)
    prescription = prescription_of_sale(sale)
    cruise = db["cruises"].get(prescription["cruise_id"])
    return cruise.get("certified_volume_bf") if cruise else None


def _contract_verified_bf(contract_id):
    total = 0
    for t in db["tickets"].values():
        if t["contract_id"] == contract_id and t["status"] == "VERIFIED":
            total += t["bf_governing"]
    return total


@bp.route("/forestry/settlements", methods=["POST"])
@require_roles("Forester")
def create_settlement():
    body = get_body()
    c_ref = body.get("contract_id")
    if isinstance(c_ref, str):
        get_contract(c_ref)
    check_known(body, {"contract_id", "kind", "period_start", "period_end",
                       "milestone"})
    contract_id = f_str(body, "contract_id")
    contract = get_contract(contract_id)
    kind = f_enum(body, "kind", KINDS)
    sale = sale_of_contract(contract)
    expected_kind = ("PER_UNIT_PERIOD" if sale["sale_type"] == "PER_UNIT"
                     else "LUMP_MILESTONE")
    if kind != expected_kind:
        bad_request("settlement kind does not match the contract sale type")
    period_start = f_date(body, "period_start", required=False)
    period_end = f_date(body, "period_end", required=False)
    milestone = f_enum(body, "milestone", MILESTONES, required=False)

    ticket_ids = []
    if kind == "PER_UNIT_PERIOD":
        if period_start is None or period_end is None or milestone is not None:
            bad_request("PER_UNIT_PERIOD requires period_start/period_end "
                        "and no milestone")
        ps = parse_date_str(period_start)
        pe = parse_date_str(period_end)
        if pe <= ps:
            bad_request("period_end must be after period_start")
        # half-open period non-overlap vs existing non-VOID period settlements
        for s in db["settlements"].values():
            if (s["contract_id"] == contract["id"]
                    and s["kind"] == "PER_UNIT_PERIOD"
                    and s["status"] != "VOID"):
                os_ = parse_date_str(s["period_start"])
                oe = parse_date_str(s["period_end"])
                if ps < oe and os_ < pe:
                    err("ERR_SETTLEMENT_PERIOD_OVERLAP", 422,
                        "period overlaps an existing settlement period")
        # sweep eligible VERIFIED tickets
        settled_ids = set()
        for s in db["settlements"].values():
            if s["contract_id"] == contract["id"] and s["status"] != "VOID":
                settled_ids.update(s.get("ticket_ids") or [])
        eligible = []
        for t in db["tickets"].values():
            if (t["contract_id"] == contract["id"]
                    and t["status"] == "VERIFIED"
                    and t["id"] not in settled_ids):
                sd = parse_date_str(t["scaled_date"])
                if ps <= sd < pe:
                    eligible.append(t)
        eligible.sort(key=lambda t: (t["created_at"], t["_seq"]))
        if not eligible:
            err("ERR_SETTLEMENT_PERIOD_EMPTY", 422,
                "period contains no eligible VERIFIED tickets")
        rates = _winning_bid_rates(contract)
        gross = 0
        for t in eligible:
            rate = rates.get(t["species"], 0)
            gross += rhu(D(rate) * D(t["bf_governing"]) / D(1000))
            ticket_ids.append(t["id"])
        holdback = rhu(D(gross) * HOLDBACK_PCT / 100)
    else:  # LUMP_MILESTONE
        if milestone is None or period_start is not None or period_end is not None:
            bad_request("LUMP_MILESTONE requires milestone and no period dates")
        used = [s["milestone"] for s in db["settlements"].values()
                if s["contract_id"] == contract["id"]
                and s["kind"] == "LUMP_MILESTONE" and s["status"] != "VOID"]
        expected_next = MILESTONE_ORDER[len(used)] if len(used) < 3 else None
        if milestone in used or milestone != expected_next:
            err("ERR_INVALID_TRANSITION", 409,
                "milestone %s is not next in sequence" % milestone)
        awarded = contract["awarded_value_cents"]
        if milestone == "MOBILIZATION":
            if contract["status"] != "HARVESTING":
                err("ERR_INVALID_TRANSITION", 409,
                    "MOBILIZATION requires a HARVESTING contract")
            gross = rhu(D(awarded) * Decimal("0.40"))
        elif milestone == "MIDPOINT":
            certified_total = _certified_total(contract) or 0
            threshold = rhu(D(certified_total) * Decimal("0.50"))
            if _contract_verified_bf(contract["id"]) < threshold:
                err("ERR_INVALID_TRANSITION", 409,
                    "verified volume below the midpoint threshold")
            gross = rhu(D(awarded) * Decimal("0.40"))
        else:  # COMPLETION
            if contract["status"] != "HARVEST_COMPLETE":
                err("ERR_INVALID_TRANSITION", 409,
                    "COMPLETION requires a HARVEST_COMPLETE contract")
            prior = sum(s["gross_cents"] for s in db["settlements"].values()
                        if s["contract_id"] == contract["id"]
                        and s["kind"] == "LUMP_MILESTONE"
                        and s["status"] != "VOID")
            gross = awarded - prior
        holdback = 0

    fee = consulting_fee(contract["billed_total_cents"], gross)
    net = gross - holdback - fee
    ent = new_common({
        "contract_id": contract["id"],
        "kind": kind,
        "period_start": period_start,
        "period_end": period_end,
        "milestone": milestone,
        "ticket_ids": ticket_ids,
        "gross_cents": gross,
        "holdback_cents": holdback,
        "fee_cents": fee,
        "net_cents": net,
        "status": "DRAFT",
        "due_date": None,
        "accrued_interest_cents": 0,
    })
    db["settlements"][ent["id"]] = ent
    contract["billed_total_cents"] += gross
    contract["holdback_balance_cents"] += holdback
    contract["consulting_fee_total_cents"] += fee
    return success(settlement_out(ent), 201)


@bp.route("/forestry/settlements/<sid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_settlement_ep(sid):
    return success(settlement_out(get_settlement(sid)), 200)


@bp.route("/forestry/settlements", methods=["GET"])
@require_roles(*READ_ROLES)
def list_settlements():
    page, meta = paginate(db["settlements"].values(), {
        "contract_id": "contract_id",
        "status": "status",
    })
    return success([settlement_out(s) for s in page], 200, is_array=True,
                   page_meta=meta)


@bp.route("/forestry/settlements/<sid>/approve", methods=["POST"])
@require_roles("Landowner")
def approve_settlement(sid):
    s = get_settlement(sid)
    body = get_body()
    check_known(body, set())
    contract = get_contract(s["contract_id"])
    tract = tract_of_contract(contract)
    if tract is None or tract["landowner_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "landowner does not own this tract")
    check_transition(s, {"DRAFT"}, SETTLEMENT_TERMINAL, "settlement")
    s["due_date"] = (today() + timedelta(days=PAYMENT_TERMS_DAYS)).isoformat()
    s["status"] = "APPROVED"
    bump(s)
    return success(settlement_out(s), 200)


@bp.route("/forestry/settlements/<sid>/disburse", methods=["POST"])
@require_roles("Forester")
def disburse_settlement(sid):
    s = get_settlement(sid)
    body = get_body()
    check_known(body, set())
    check_transition(s, {"APPROVED"}, SETTLEMENT_TERMINAL, "settlement")
    contract = get_contract(s["contract_id"])
    contract["disbursed_total_cents"] += s["net_cents"]
    s["status"] = "PAID"
    bump(s)
    bump(contract)
    return success(settlement_out(s), 200)


@bp.route("/forestry/settlements/<sid>/refund", methods=["POST"])
@require_roles("Forester")
def refund_settlement(sid):
    s = get_settlement(sid)
    body = get_body()
    check_known(body, set())
    check_transition(s, {"PAID"}, SETTLEMENT_TERMINAL, "settlement")
    contract = get_contract(s["contract_id"])
    contract["disbursed_total_cents"] -= s["net_cents"]
    contract["refunded_total_cents"] += s["net_cents"]
    s["status"] = "REFUNDED"
    bump(s)
    bump(contract)
    return success(settlement_out(s), 200)


@bp.route("/forestry/settlements/<sid>/void", methods=["POST"])
@require_roles("Forester")
def void_settlement(sid):
    s = get_settlement(sid)
    body = get_body()
    check_known(body, set())
    check_transition(s, {"DRAFT"}, SETTLEMENT_TERMINAL, "settlement")
    contract = get_contract(s["contract_id"])
    from routes_contracts import void_settlement_reversal
    void_settlement_reversal(s, contract)
    return success(settlement_out(s), 200)
