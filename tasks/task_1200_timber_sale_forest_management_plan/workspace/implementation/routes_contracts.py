"""Harvest contracts and performance bonds."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_int, f_enum, bad_request, err, paginate, get_contract, get_bond,
    party_or_404, bond_of_contract, obligation_of_contract, sale_of_contract,
    tract_of_sale, stand_of_sale, prescription_of_sale, tract_of_contract,
    open_major_findings, contract_out, check_transition, now, today,
    parse_date_str, parse_iso_datetime, rhu, D,
)

bp = Blueprint("contracts", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

CONTRACT_TERMINAL = {"TERMINATED", "CLOSED"}
BOND_TERMINAL = {"RELEASED", "FORFEITED"}

REFORESTATION_HOLD_PER_ACRE_CENTS = 35000
CURE_PERIOD_DAYS = 14
ADMIN_FEE_CENTS = 250000


def reforestation_hold(amount_cents, acres, per_acre):
    return min(amount_cents, rhu(D(acres) * D(per_acre)))


def void_settlement_reversal(s, contract):
    """DRAFT -> VOID with billed/holdback/fee reversal (also used by the
    stop-work cascade)."""
    contract["billed_total_cents"] -= s["gross_cents"]
    contract["holdback_balance_cents"] -= s["holdback_cents"]
    contract["consulting_fee_total_cents"] -= s["fee_cents"]
    s["status"] = "VOID"
    bump(s)
    bump(contract)


def suspend_contract(contract):
    """HARVESTING -> SUSPENDED plus the three-link stop-work cascade."""
    contract["status"] = "SUSPENDED"
    bump(contract)
    # link 2: flag DRAFT and VERIFIED tickets
    flagged_ids = set()
    for t in db["tickets"].values():
        if (t["contract_id"] == contract["id"]
                and t["status"] in ("DRAFT", "VERIFIED")):
            t["flagged_for_review"] = True
            flagged_ids.add(t["id"])
    # link 3: void affected DRAFT settlements
    for s in db["settlements"].values():
        if (s["contract_id"] == contract["id"] and s["status"] == "DRAFT"
                and flagged_ids.intersection(s.get("ticket_ids") or [])):
            void_settlement_reversal(s, contract)


# ----------------------------- contracts --------------------------

@bp.route("/forestry/contracts/<cid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_contract_ep(cid):
    return success(contract_out(get_contract(cid)), 200)


@bp.route("/forestry/contracts", methods=["GET"])
@require_roles(*READ_ROLES)
def list_contracts():
    page, meta = paginate(db["contracts"].values(), {
        "sale_id": "sale_id",
        "buyer_id": "buyer_id",
        "contractor_id": "contractor_id",
        "status": "status",
    })
    return success([contract_out(c) for c in page], 200, is_array=True,
                   page_meta=meta)


@bp.route("/forestry/contracts/<cid>/bond", methods=["POST"])
@require_roles("Buyer")
def post_bond(cid):
    c = get_contract(cid)
    if c["buyer_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "contract does not belong to buyer")
    body = get_body()
    check_known(body, {"amount_cents"})
    amount = f_int(body, "amount_cents", minv=0)
    check_transition(c, {"PENDING_BOND"}, CONTRACT_TERMINAL, "contract")
    if amount != c["required_bond_amount_cents"]:
        err("ERR_BOND_AMOUNT_MISMATCH", 422,
            "posted amount must equal required_bond_amount_cents")
    sale = sale_of_contract(c)
    stand = stand_of_sale(sale)
    bond = new_common({
        "contract_id": c["id"],
        "amount_cents": amount,
        "status": "POSTED",
        "reforestation_hold_cents": reforestation_hold(
            amount, stand["acres"], REFORESTATION_HOLD_PER_ACRE_CENTS),
        "admin_fee_cents": 0,
        "remediation_offset_cents": 0,
        "shortfall_offset_cents": 0,
        "refunded_cents": 0,
        "released_cents": 0,
    })
    db["bonds"][bond["id"]] = bond
    c["status"] = "ACTIVE"
    bump(c)
    return success(pub(bond), 201)


@bp.route("/forestry/contracts/<cid>/assign-contractor", methods=["POST"])
@require_roles("Buyer")
def assign_contractor(cid):
    c = get_contract(cid)
    if c["buyer_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "contract does not belong to buyer")
    body = get_body()
    contractor_ref = body.get("contractor_id")
    if isinstance(contractor_ref, str) and contractor_ref not in db["contractors"]:
        err("ERR_PARTY_NOT_FOUND", 404,
            "contractor not found: %s" % contractor_ref)
    check_known(body, {"contractor_id"})
    contractor_id = f_str(body, "contractor_id")
    if contractor_id not in db["contractors"]:
        err("ERR_PARTY_NOT_FOUND", 404,
            "contractor not found: %s" % contractor_id)
    check_transition(c, {"PENDING_BOND", "ACTIVE"}, CONTRACT_TERMINAL,
                     "contract")
    c["contractor_id"] = contractor_id
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/start-harvest", methods=["POST"])
@require_roles("Contractor")
def start_harvest(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    if c["contractor_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "contract is not assigned to this contractor")
    check_transition(c, {"ACTIVE"}, CONTRACT_TERMINAL, "contract")
    if open_major_findings(c["id"]) != 0:
        err("ERR_OPEN_MAJOR_FINDING", 409,
            "open MAJOR BMP finding blocks harvest start")
    sale = sale_of_contract(c)
    day = today()
    if not (parse_date_str(sale["harvest_window_start"]) <= day
            < parse_date_str(sale["harvest_window_end"])):
        err("ERR_SEASON_WINDOW_VIOLATION", 422,
            "outside the sale harvest window")
    prescription = prescription_of_sale(sale)
    if not (parse_date_str(prescription["window_start"]) <= day
            < parse_date_str(prescription["window_end"])):
        err("ERR_SEASON_WINDOW_VIOLATION", 422,
            "outside the prescription window")
    if prescription["status"] not in ("APPROVED", "ACTIVE"):
        err("ERR_PRESCRIPTION_NOT_APPROVED", 409,
            "prescription is not APPROVED or ACTIVE")
    c["status"] = "HARVESTING"
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/suspend", methods=["POST"])
@require_roles("Forester")
def suspend(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"HARVESTING"}, CONTRACT_TERMINAL, "contract")
    suspend_contract(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/resume", methods=["POST"])
@require_roles("Forester")
def resume(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"SUSPENDED"}, CONTRACT_TERMINAL, "contract")
    if open_major_findings(c["id"]) != 0:
        err("ERR_OPEN_MAJOR_FINDING", 409,
            "open MAJOR BMP finding blocks resume")
    c["status"] = "HARVESTING"
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/complete-harvest", methods=["POST"])
@require_roles("Contractor")
def complete_harvest(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    if c["contractor_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "contract is not assigned to this contractor")
    check_transition(c, {"HARVESTING"}, CONTRACT_TERMINAL, "contract")
    if open_major_findings(c["id"]) != 0:
        err("ERR_OPEN_MAJOR_FINDING", 409,
            "open MAJOR BMP finding blocks harvest completion")
    from core import now_iso
    c["status"] = "HARVEST_COMPLETE"
    c["harvest_completed_at"] = now_iso()
    bump(c)
    obligation = new_common({
        "contract_id": c["id"],
        "status": "IMPOSED",
        "plant_by_date": (today() + timedelta(days=365)).isoformat(),
        "current_planted_count": 0,
        "planted_date": None,
    })
    db["obligations"][obligation["id"]] = obligation
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/declare-default", methods=["POST"])
@require_roles("Forester")
def declare_default(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, {"reason"})
    f_str(body, "reason", required=False)
    check_transition(c, {"ACTIVE", "HARVESTING", "SUSPENDED"},
                     CONTRACT_TERMINAL, "contract")
    from core import now_iso
    c["status"] = "DEFAULTED"
    c["defaulted_at"] = now_iso()
    bump(c)
    bond = bond_of_contract(c["id"])
    if bond is not None and bond["status"] == "POSTED":
        bond["status"] = "FORFEIT_CLAIMED"
        bump(bond)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/cure", methods=["POST"])
@require_roles("Buyer")
def cure(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    if c["buyer_id"] != g.uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "contract does not belong to buyer")
    check_transition(c, {"DEFAULTED"}, CONTRACT_TERMINAL, "contract")
    if now() > parse_iso_datetime(c["defaulted_at"]) + timedelta(
            days=CURE_PERIOD_DAYS):
        err("ERR_CURE_PERIOD_EXPIRED", 422, "cure period has expired")
    bond = bond_of_contract(c["id"])
    if bond is None or bond["status"] != "FORFEIT_CLAIMED":
        err("ERR_INVALID_TRANSITION", 409,
            "no pending forfeiture claim to cure")
    bond["status"] = "POSTED"
    bump(bond)
    c["status"] = "HARVESTING"
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/terminate", methods=["POST"])
@require_roles("Forester")
def terminate(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"DEFAULTED"}, CONTRACT_TERMINAL, "contract")
    bond = bond_of_contract(c["id"])
    if bond is None or bond["status"] != "FORFEITED":
        err("ERR_INVALID_TRANSITION", 409,
            "bond must be FORFEITED before termination")
    buyer = db["buyers"].get(c["buyer_id"])
    if buyer is not None:
        buyer["prior_defaults"] += 1
    c["status"] = "TERMINATED"
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/close", methods=["POST"])
@require_roles("Forester")
def close_contract(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"HARVEST_COMPLETE"}, CONTRACT_TERMINAL, "contract")
    bond = bond_of_contract(c["id"])
    if bond is None or bond["status"] != "RELEASED":
        err("ERR_BOND_HOLD_OUTSTANDING", 409, "bond is not RELEASED")
    for s in db["settlements"].values():
        if (s["contract_id"] == c["id"]
                and s["status"] not in ("PAID", "REFUNDED", "VOID")):
            err("ERR_UNPAID_SETTLEMENTS", 409,
                "contract has unresolved settlements")
    obligation = obligation_of_contract(c["id"])
    if obligation is None or obligation["status"] != "SATISFIED":
        err("ERR_REFORESTATION_UNSATISFIED", 409,
            "reforestation obligation is not SATISFIED")
    c["status"] = "CLOSED"
    bump(c)
    return success(contract_out(c), 200)


@bp.route("/forestry/contracts/<cid>/release-holdback", methods=["POST"])
@require_roles("Forester")
def release_holdback(cid):
    c = get_contract(cid)
    body = get_body()
    check_known(body, set())
    obligation = obligation_of_contract(c["id"])
    if obligation is None or obligation["status"] != "SATISFIED":
        err("ERR_REFORESTATION_UNSATISFIED", 409,
            "reforestation obligation is not SATISFIED")
    c["disbursed_total_cents"] += c["holdback_balance_cents"]
    c["holdback_balance_cents"] = 0
    return success(contract_out(c), 200)


# ------------------------------- bonds ----------------------------

@bp.route("/forestry/bonds/<bid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_bond_ep(bid):
    return success(pub(get_bond(bid)), 200)


@bp.route("/forestry/bonds", methods=["GET"])
@require_roles(*READ_ROLES)
def list_bonds():
    page, meta = paginate(db["bonds"].values(), {
        "contract_id": "contract_id",
        "status": "status",
    })
    return success([pub(b) for b in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/bonds/<bid>/claim-forfeiture", methods=["POST"])
@require_roles("Forester")
def claim_forfeiture(bid):
    b = get_bond(bid)
    body = get_body()
    check_known(body, set())
    check_transition(b, {"POSTED"}, BOND_TERMINAL, "bond")
    b["status"] = "FORFEIT_CLAIMED"
    bump(b)
    return success(pub(b), 200)


@bp.route("/forestry/bonds/<bid>/adjudicate", methods=["POST"])
@require_roles("PlatformAdmin")
def adjudicate(bid):
    b = get_bond(bid)
    body = get_body()
    check_known(body, {"decision", "remediation_cost_cents",
                       "resale_shortfall_cents"})
    decision = f_enum(body, "decision", {"UPHELD", "DENIED"})
    remediation = f_int(body, "remediation_cost_cents", required=False,
                        default=0, minv=0)
    shortfall = f_int(body, "resale_shortfall_cents", required=False,
                      default=0, minv=0)
    check_transition(b, {"FORFEIT_CLAIMED"}, BOND_TERMINAL, "bond")
    if decision == "DENIED":
        b["status"] = "POSTED"
    else:
        remaining = b["amount_cents"]
        admin = min(ADMIN_FEE_CENTS, remaining)
        remaining -= admin
        rem = min(remediation, remaining)
        remaining -= rem
        short = min(shortfall, remaining)
        remaining -= short
        b["admin_fee_cents"] = admin
        b["remediation_offset_cents"] = rem
        b["shortfall_offset_cents"] = short
        b["refunded_cents"] = remaining
        b["status"] = "FORFEITED"
    bump(b)
    return success(pub(b), 200)


@bp.route("/forestry/bonds/<bid>/release", methods=["POST"])
@require_roles("Forester")
def release_bond(bid):
    b = get_bond(bid)
    body = get_body()
    check_known(body, set())
    check_transition(b, {"POSTED"}, BOND_TERMINAL, "bond")
    contract = get_contract(b["contract_id"])
    if contract["status"] not in ("HARVEST_COMPLETE", "CLOSED"):
        err("ERR_INVALID_TRANSITION", 409,
            "contract is not past harvest completion")
    obligation = obligation_of_contract(contract["id"])
    if obligation is None or obligation["status"] != "SATISFIED":
        err("ERR_BOND_HOLD_OUTSTANDING", 409,
            "reforestation obligation is not SATISFIED")
    b["released_cents"] = b["amount_cents"]
    b["status"] = "RELEASED"
    bump(b)
    return success(pub(b), 200)
