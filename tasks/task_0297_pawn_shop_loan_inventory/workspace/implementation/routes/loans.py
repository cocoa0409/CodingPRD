"""Loan routes: origination, payoff, servicing, redemption, forfeiture, void (PRD §3.3-§3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from models import base_record, event_record, touch
from helpers import (
    get_body,
    as_str,
    as_int,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array
from services import calc
from services.domain import (
    schedule_for_state,
    rederive_grace,
    active_hold_on_pawn_item,
    chargeable_tx_exists,
)

bp = Blueprint("loans", __name__)


def _drawer_for_shop(shop_id):
    for d in store.cash_drawers.values():
        if d["shop_id"] == shop_id:
            return d
    return None


def _append_tx(loan, kind, amount_cents, periods_in_charge):
    tx = event_record({
        "loan_id": loan["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "periods_in_charge": periods_in_charge,
    })
    store.finance_transactions[tx["id"]] = tx
    return tx


def _intervals_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Originate a loan (PRD §3.3)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans", methods=["POST"])
def create_loan():
    user_id, _ = require_auth(["LoanOfficer"])
    body = get_body()

    shop_id = as_str(body, "shop_id")
    pawn_item_id = as_str(body, "pawn_item_id")
    storage_bin_id = as_str(body, "storage_bin_id")

    # Existence (priority 3): body FKs in listed order.
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    item = store.pawn_items.get(pawn_item_id)
    if item is None:
        raise err("ERR_NOT_FOUND", "Pawn item not found.")
    bin_rec = store.storage_bins.get(storage_bin_id)
    if bin_rec is None:
        raise err("ERR_NOT_FOUND", "Storage bin not found.")

    # State (priority 5, specialized): item must be APPRAISED (PRD §3.3).
    if item["status"] != "APPRAISED":
        raise err("ERR_ITEM_NOT_APPRAISED", "Item has not been appraised.")

    # Governing schedule pinned by the shop's state_code.
    schedule = schedule_for_state(shop["state_code"])
    if schedule is None:
        # No schedule governs this state; cannot lend (treat as not found FK).
        raise err("ERR_NOT_FOUND", "No state schedule governs this shop's state.")

    customer = store.customers.get(item["customer_id"])

    # Business rules, in order (PRD §3.3):
    # 1) segregation of duties (403).
    if item["appraised_by_user_id"] is not None and item["appraised_by_user_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Appraiser and loan officer must differ.")

    # 2) police-hold on the collateral (409).
    if active_hold_on_pawn_item(pawn_item_id) is not None:
        raise err("ERR_POLICE_HOLD_ACTIVE", "An active police hold names the collateral.")

    # 3) customer-flag (409).
    if customer is not None and customer.get("is_flagged"):
        raise err("ERR_CUSTOMER_FLAGGED", "The customer is flagged by law enforcement.")

    # Compute timestamps for the new occupation interval (needed by capacity check).
    origination_at = store.now()
    term_end_at = origination_at + timedelta(days=schedule["term_days"])
    grace_end_at = term_end_at + timedelta(days=schedule["grace_days"])

    # 4) bin capacity over [origination_at, grace_end_at) half-open (409).
    occupants = [
        l for l in store.loans.values()
        if l["storage_bin_id"] == storage_bin_id
        and l["status"] in ("ACTIVE", "IN_GRACE", "POLICE_HELD")
    ]
    concurrent = 0
    for o in occupants:
        if _intervals_overlap_half_open(
            o["origination_at"], o["grace_end_at"], origination_at, grace_end_at
        ):
            concurrent += 1
    if concurrent + 1 > bin_rec["capacity"]:
        raise err("ERR_BIN_CAPACITY_EXCEEDED", "The storage bin is at capacity for this interval.")

    # 5) principal must be strictly positive (422).
    principal = calc.principal_from_appraisal(
        item["appraised_value_cents"],
        schedule["loan_to_value_bps"],
        schedule["max_principal_cents"],
    )
    if principal <= 0:
        raise err("ERR_PRINCIPAL_NON_POSITIVE", "Computed principal is not positive.")

    # Create the loan.
    loan = base_record({
        "shop_id": shop_id,
        "pawn_item_id": pawn_item_id,
        "storage_bin_id": storage_bin_id,
        "customer_id": item["customer_id"],
        "state_code": shop["state_code"],
        "principal_cents": principal,
        "setup_fee_cents": schedule["setup_fee_cents"],
        "origination_at": origination_at,
        "term_end_at": term_end_at,
        "grace_end_at": grace_end_at,
        "periods_charged": 0,
        "renewal_count": 0,
        "police_hold_flag": False,
        "status": "ACTIVE",
    })
    store.loans[loan["id"]] = loan

    # Item APPRAISED -> PLEDGED; police_report_status unchanged (PRD §3.3).
    item["status"] = "PLEDGED"
    touch(item)

    # Disburse cash: DISBURSEMENT tx amount = -principal; drawer -= principal.
    _append_tx(loan, "DISBURSEMENT", -principal, 0)
    drawer = _drawer_for_shop(shop_id)
    if drawer is not None:
        drawer["balance_cents"] -= principal
        touch(drawer)

    return success_object(serialize(loan), 201)


# ---------------------------------------------------------------------------
# List / fetch loans
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans", methods=["GET"])
def list_loans():
    require_auth(["LoanOfficer", "ShopManager", "Appraiser"])
    limit, offset = parse_pagination()
    pawn_item_id = request.args.get("pawn_item_id")
    customer_id = request.args.get("customer_id")
    storage_bin_id = request.args.get("storage_bin_id")
    shop_id = request.args.get("shop_id")
    items = list(store.loans.values())
    if pawn_item_id is not None:
        items = [l for l in items if l["pawn_item_id"] == pawn_item_id]
    if customer_id is not None:
        items = [l for l in items if l["customer_id"] == customer_id]
    if storage_bin_id is not None:
        items = [l for l in items if l["storage_bin_id"] == storage_bin_id]
    if shop_id is not None:
        items = [l for l in items if l["shop_id"] == shop_id]
    for l in items:
        rederive_grace(l)
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(l) for l in window], limit, offset, total)


@bp.route("/pawn/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    require_auth(["LoanOfficer", "ShopManager", "Appraiser"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    rederive_grace(loan)
    return success_object(serialize(loan))


@bp.route("/pawn/loans/<loan_id>/payoff", methods=["GET"])
def get_payoff(loan_id):
    require_auth(["LoanOfficer", "ShopManager"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    rederive_grace(loan)
    schedule = schedule_for_state(loan["state_code"])
    payoff, total_periods, ppc = calc.redemption_payoff(loan, schedule, store.now())
    return success_object({
        "payoff_cents": payoff,
        "total_periods": total_periods,
        "per_period_charge_cents": ppc,
    })


@bp.route("/pawn/loans/<loan_id>/transactions", methods=["GET"])
def list_transactions(loan_id):
    require_auth(["LoanOfficer", "ShopManager"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")
    limit, offset = parse_pagination()
    items = [t for t in store.finance_transactions.values() if t["loan_id"] == loan_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(t) for t in window], limit, offset, total)


# ---------------------------------------------------------------------------
# Extend (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans/<loan_id>/extend", methods=["POST"])
def extend_loan(loan_id):
    require_auth(["LoanOfficer"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")

    body = get_body()
    expected_version = as_int(body, "expected_loan_version")

    # OCC baseline: the version the client could have observed. The OCC contract
    # (PRD §2.7) catches "another servicing write" advancing the version; the
    # lazy ACTIVE->IN_GRACE re-derive below is not a servicing write and must not
    # spuriously trip OCC, so capture the version BEFORE rederive_grace bumps it.
    occ_baseline_version = loan["version"]

    rederive_grace(loan)
    schedule = schedule_for_state(loan["state_code"])

    # Police hold / POLICE_HELD freeze (PRD §3.5, §3.10): blocked ahead of the
    # generic invalid-state check.
    if loan["police_hold_flag"] or loan["status"] == "POLICE_HELD":
        raise err("ERR_POLICE_HOLD_ACTIVE", "Loan is under an active police hold.")

    # State (priority 5): defined from ACTIVE or IN_GRACE.
    if loan["status"] not in ("ACTIVE", "IN_GRACE"):
        raise err("ERR_INVALID_STATE", "Loan is not in a state that permits extension.")

    # Period cap (priority 11): one more period must not exceed max_periods_total.
    if loan["periods_charged"] + 1 > schedule["max_periods_total"]:
        raise err("ERR_PERIOD_CAP_EXCEEDED", "Extension exceeds the lifetime period cap.")

    # OCC (priority 17).
    if expected_version != occ_baseline_version:
        raise err("ERR_STALE_LOAN_VERSION", "expected_loan_version does not match.")

    # Fee = exactly one per-period charge (PRD §3.5 extension variant).
    fee = calc.per_period_charge(
        loan["principal_cents"],
        schedule["monthly_interest_bps"],
        schedule["monthly_storage_fee_cents"],
    )
    _append_tx(loan, "EXTENSION_FEE", fee, 1)
    drawer = _drawer_for_shop(loan["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += fee
        touch(drawer)

    loan["periods_charged"] += 1
    loan["term_end_at"] = loan["term_end_at"] + timedelta(days=schedule["term_days"])
    loan["grace_end_at"] = loan["grace_end_at"] + timedelta(days=schedule["term_days"])
    # Shift the accrual baseline so the live period restarts (PRD §3.5).
    loan["origination_at"] = loan["origination_at"] + timedelta(days=schedule["term_days"])
    loan["status"] = "ACTIVE"
    touch(loan)
    return success_object(serialize(loan))


# ---------------------------------------------------------------------------
# Renew (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans/<loan_id>/renew", methods=["POST"])
def renew_loan(loan_id):
    require_auth(["LoanOfficer"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")

    body = get_body()
    expected_version = as_int(body, "expected_loan_version")

    # OCC baseline: capture the version BEFORE rederive_grace's lazy
    # ACTIVE->IN_GRACE bump, which is not a "servicing write" (PRD §2.7) and must
    # not spuriously trip OCC.
    occ_baseline_version = loan["version"]

    rederive_grace(loan)
    schedule = schedule_for_state(loan["state_code"])

    # Police hold / POLICE_HELD freeze (PRD §3.5, §3.10): blocked ahead of the
    # generic invalid-state check.
    if loan["police_hold_flag"] or loan["status"] == "POLICE_HELD":
        raise err("ERR_POLICE_HOLD_ACTIVE", "Loan is under an active police hold.")

    # State (priority 5): renewal only while IN_GRACE.
    if loan["status"] != "IN_GRACE":
        raise err("ERR_INVALID_STATE", "Loan is not IN_GRACE.")

    # periods due to date (live periods accrued).
    live = calc.live_periods(
        store.now(),
        loan["origination_at"],
        loan["periods_charged"],
        schedule["max_periods_total"],
    )

    # Period cap (priority 11): periods-due-to-date must not exceed the cap.
    if loan["periods_charged"] + live > schedule["max_periods_total"]:
        raise err("ERR_PERIOD_CAP_EXCEEDED", "Renewal exceeds the lifetime period cap.")

    # OCC (priority 17).
    if expected_version != occ_baseline_version:
        raise err("ERR_STALE_LOAN_VERSION", "expected_loan_version does not match.")

    # Fee = all accrued finance charges to date = live * per_period_charge.
    ppc = calc.per_period_charge(
        loan["principal_cents"],
        schedule["monthly_interest_bps"],
        schedule["monthly_storage_fee_cents"],
    )
    fee = live * ppc
    _append_tx(loan, "RENEWAL_FEE", fee, live)
    drawer = _drawer_for_shop(loan["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += fee
        touch(drawer)

    loan["renewal_count"] += 1
    loan["periods_charged"] += live
    # Reset baseline to now (PRD §3.5 renewal).
    now = store.now()
    loan["origination_at"] = now
    loan["term_end_at"] = now + timedelta(days=schedule["term_days"])
    loan["grace_end_at"] = loan["term_end_at"] + timedelta(days=schedule["grace_days"])
    loan["status"] = "ACTIVE"
    touch(loan)
    return success_object(serialize(loan))


# ---------------------------------------------------------------------------
# Redeem (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans/<loan_id>/redeem", methods=["POST"])
def redeem_loan(loan_id):
    require_auth(["LoanOfficer"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")

    rederive_grace(loan)
    schedule = schedule_for_state(loan["state_code"])

    # Police hold / POLICE_HELD freeze (PRD §3.6, §3.10): a POLICE_HELD loan or
    # a loan whose police_hold_flag is true is blocked with ERR_POLICE_HOLD_ACTIVE
    # ahead of the generic invalid-state check.
    if loan["police_hold_flag"] or loan["status"] == "POLICE_HELD":
        raise err("ERR_POLICE_HOLD_ACTIVE", "Loan is under an active police hold.")

    # State (priority 5): ACTIVE or IN_GRACE.
    if loan["status"] not in ("ACTIVE", "IN_GRACE"):
        raise err("ERR_INVALID_STATE", "Loan is not in a redeemable state.")

    payoff, total_periods, ppc = calc.redemption_payoff(loan, schedule, store.now())
    _append_tx(loan, "REDEMPTION_PAYOFF", payoff, total_periods - loan["periods_charged"])
    drawer = _drawer_for_shop(loan["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += payoff
        touch(drawer)

    loan["status"] = "REDEEMED"
    touch(loan)
    item = store.pawn_items.get(loan["pawn_item_id"])
    if item is not None:
        item["status"] = "REDEEMED"
        touch(item)
    return success_object(serialize(loan))


# ---------------------------------------------------------------------------
# Forfeit (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans/<loan_id>/forfeit", methods=["POST"])
def forfeit_loan(loan_id):
    require_auth(["ShopManager"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")

    rederive_grace(loan)
    schedule = schedule_for_state(loan["state_code"])

    # Police hold / POLICE_HELD freeze (PRD §3.7, §3.10): blocked ahead of the
    # generic invalid-state check.
    if loan["police_hold_flag"] or loan["status"] == "POLICE_HELD":
        raise err("ERR_POLICE_HOLD_ACTIVE", "Loan is under an active police hold.")

    # State (priority 5): must be IN_GRACE.
    if loan["status"] != "IN_GRACE":
        raise err("ERR_INVALID_STATE", "Loan is not IN_GRACE.")

    # Grace elapsed (priority 10).
    if store.now() < loan["grace_end_at"]:
        raise err("ERR_GRACE_NOT_ELAPSED", "Grace window has not elapsed.")

    # Cost basis = redemption payoff at the forfeiture instant (link 1).
    cost_basis, _tp, _ppc = calc.redemption_payoff(loan, schedule, store.now())

    item = store.pawn_items.get(loan["pawn_item_id"])

    loan["status"] = "FORFEITED"
    touch(loan)
    if item is not None:
        item["status"] = "FORFEITED"
        touch(item)

    # Spawn InventoryItem (link 2).
    appraised = item["appraised_value_cents"] if item is not None else 0
    list_price, floor_price = calc.resale_prices(appraised, cost_basis)
    inv = base_record({
        "shop_id": loan["shop_id"],
        "source_loan_id": loan["id"],
        "pawn_item_id": loan["pawn_item_id"],
        "cost_basis_cents": cost_basis,
        "appraised_value_cents": appraised,
        "list_price_cents": list_price,
        "floor_price_cents": floor_price,
        "sold_price_cents": None,
        "last_layaway_end_at": None,
        "status": "AVAILABLE",
    })
    store.inventory_items[inv["id"]] = inv
    # No cash moves at forfeiture (drawer unchanged).
    return success_object(serialize(loan))


# ---------------------------------------------------------------------------
# Void (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/pawn/loans/<loan_id>/void", methods=["POST"])
def void_loan(loan_id):
    require_auth(["LoanOfficer"])
    loan = store.loans.get(loan_id)
    if loan is None:
        raise err("ERR_NOT_FOUND", "Loan not found.")

    rederive_grace(loan)

    # State (priority 5): only while ACTIVE.
    if loan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Loan is not ACTIVE.")

    # Already-serviced (priority 12).
    if chargeable_tx_exists(loan["id"]):
        raise err("ERR_LOAN_ALREADY_SERVICED", "Loan already has a chargeable transaction.")

    principal = loan["principal_cents"]
    _append_tx(loan, "VOID_REVERSAL", principal, 0)
    drawer = _drawer_for_shop(loan["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += principal
        touch(drawer)

    loan["status"] = "VOIDED"
    touch(loan)
    item = store.pawn_items.get(loan["pawn_item_id"])
    if item is not None:
        item["status"] = "APPRAISED"
        touch(item)
    return success_object(serialize(loan))
