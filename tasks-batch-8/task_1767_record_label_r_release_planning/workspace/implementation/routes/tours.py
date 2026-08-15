"""Tour supports and tour expenses."""

from flask import Blueprint

from db import db
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, v_str, v_int, v_enum, v_date,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import recompute_account_totals
from services.domain import account_of_contract, artist_of_contract

bp = Blueprint("tours", __name__)

EXPENSE_CATEGORIES = ["TRAVEL", "LODGING", "PRODUCTION", "MISC"]


def _artist_of_tour(tour):
    contract = db.contracts.get(tour["contract_id"])
    return artist_of_contract(contract) if contract else None


def _label_of_tour(tour):
    artist = _artist_of_tour(tour)
    return db.labels.get(artist["label_id"]) if artist else None


# ---------------------------------------------------------------------------
# Tour supports
# ---------------------------------------------------------------------------

@bp.post("/api/contracts/<cid>/tour-supports")
def create_tour_support(cid):
    auth(["AnRManager"])
    contract = get_or_404(db.contracts, cid)
    body = get_body()
    tour_name = v_str(body, "tour_name")
    requested = v_int(body, "requested_amount_cents", min_v=1)
    artist = artist_of_contract(contract)
    if artist["status"] not in ("SIGNED", "ACTIVE"):
        raise_err("ERR_ARTIST_NOT_SIGNABLE", "Artist status %s does not permit tour support" % artist["status"])
    tour = make_entity({
        "contract_id": cid,
        "tour_name": tour_name,
        "requested_amount_cents": requested,
        "approved_budget_cents": None,
        "advanced_amount_cents": None,
        "approved_expense_total_cents": 0,
        "unspent_returned_cents": None,
        "approved_by_user_id": None,
        "funded_by_user_id": None,
        "status": "PROPOSED",
    })
    db.tour_supports[tour["id"]] = tour
    return ok(serialize(tour), code=201)


@bp.get("/api/tour-supports/<tid>")
def get_tour_support(tid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    tour = get_or_404(db.tour_supports, tid)
    artist = _artist_of_tour(tour)
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(tour))


@bp.get("/api/contracts/<cid>/tour-supports")
def list_contract_tours(cid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    contract = get_or_404(db.contracts, cid)
    check_ownership(role, uid, contract["artist_id"])
    items = [t for t in db.tour_supports.values() if t["contract_id"] == cid]
    items = apply_filters(items, [("status", lambda t: t["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/tour-supports/<tid>/approve")
def approve_tour(tid):
    uid, _role = auth(["LabelAdmin"])
    tour = get_or_404(db.tour_supports, tid)
    body = get_body()
    approved_budget = v_int(body, "approved_budget_cents", min_v=1)
    if tour["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", "Only a PROPOSED tour support may be approved")
    if approved_budget > tour["requested_amount_cents"]:
        raise_err("ERR_APPROVED_EXCEEDS_REQUESTED",
                  "approved_budget_cents exceeds requested_amount_cents")
    tour["approved_budget_cents"] = approved_budget
    tour["approved_by_user_id"] = uid
    tour["status"] = "APPROVED"
    touch(tour)
    return ok(serialize(tour))


@bp.post("/api/tour-supports/<tid>/decline")
def decline_tour(tid):
    auth(["LabelAdmin"])
    tour = get_or_404(db.tour_supports, tid)
    get_body()
    if tour["status"] != "PROPOSED":
        raise_err("ERR_INVALID_STATE", "Only a PROPOSED tour support may be declined")
    tour["status"] = "DECLINED"
    touch(tour)
    return ok(serialize(tour))


@bp.post("/api/tour-supports/<tid>/advance-funds")
def advance_funds(tid):
    uid, _role = auth(["FinanceController"])
    tour = get_or_404(db.tour_supports, tid)
    body = get_body()
    amount = v_int(body, "amount_cents", min_v=1)
    if tour["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED tour support may be funded")
    if amount > tour["approved_budget_cents"]:
        raise_err("ERR_INVALID_REQUEST", "amount_cents exceeds approved_budget_cents")
    if uid == tour["approved_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The approver may not also advance funds")
    tour["advanced_amount_cents"] = amount
    tour["funded_by_user_id"] = uid
    tour["status"] = "ADVANCED"
    touch(tour)
    return ok(serialize(tour))


@bp.post("/api/tour-supports/<tid>/reconcile")
def reconcile_tour(tid):
    auth(["FinanceController"])
    tour = get_or_404(db.tour_supports, tid)
    get_body()
    if tour["status"] != "ADVANCED":
        raise_err("ERR_INVALID_STATE", "Only an ADVANCED tour support may be reconciled")
    tour["unspent_returned_cents"] = max(
        0, tour["advanced_amount_cents"] - tour["approved_expense_total_cents"]
    )
    tour["status"] = "RECONCILED"
    touch(tour)
    return ok(serialize(tour))


@bp.post("/api/tour-supports/<tid>/close")
def close_tour(tid):
    auth(["FinanceController"])
    tour = get_or_404(db.tour_supports, tid)
    get_body()
    if tour["status"] != "RECONCILED":
        raise_err("ERR_INVALID_STATE", "Only a RECONCILED tour support may be closed")
    tour["status"] = "CLOSED"
    touch(tour)
    return ok(serialize(tour))


@bp.post("/api/tour-supports/<tid>/cancel")
def cancel_tour(tid):
    auth(["AnRManager"])
    tour = get_or_404(db.tour_supports, tid)
    get_body()
    if tour["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED tour support may be cancelled")
    tour["status"] = "CANCELLED"
    touch(tour)
    return ok(serialize(tour))


# ---------------------------------------------------------------------------
# Tour expenses
# ---------------------------------------------------------------------------

@bp.post("/api/tour-supports/<tid>/expenses")
def create_expense(tid):
    uid, role = auth(["ArtistPortal"])
    tour = get_or_404(db.tour_supports, tid)
    artist = _artist_of_tour(tour)
    check_ownership(role, uid, artist["id"] if artist else None)
    body = get_body()
    category = v_enum(body, "category", EXPENSE_CATEGORIES)
    amount = v_int(body, "amount_cents", min_v=1)
    expense_date = v_date(body, "expense_date")
    if tour["status"] != "ADVANCED":
        raise_err("ERR_INVALID_STATE", "Expenses require an ADVANCED tour support")
    expense = make_entity({
        "tour_support_id": tid,
        "category": category,
        "amount_cents": amount,
        "expense_date": expense_date,
        "status": "SUBMITTED",
    })
    db.tour_expenses[expense["id"]] = expense
    return ok(serialize(expense), code=201)


@bp.get("/api/tour-expenses/<eid>")
def get_expense(eid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    expense = get_or_404(db.tour_expenses, eid)
    tour = db.tour_supports.get(expense["tour_support_id"])
    artist = _artist_of_tour(tour) if tour else None
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(expense))


@bp.get("/api/tour-supports/<tid>/expenses")
def list_tour_expenses(tid):
    uid, role = auth(["LabelAdmin", "AnRManager", "FinanceController", "ArtistPortal"])
    tour = get_or_404(db.tour_supports, tid)
    artist = _artist_of_tour(tour)
    check_ownership(role, uid, artist["id"] if artist else None)
    items = [e for e in db.tour_expenses.values() if e["tour_support_id"] == tid]
    items = apply_filters(items, [
        ("status", lambda e: e["status"]),
        ("category", lambda e: e["category"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/tour-expenses/<eid>/approve")
def approve_expense(eid):
    auth(["FinanceController"])
    expense = get_or_404(db.tour_expenses, eid)
    get_body()
    if expense["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED expense may be approved")
    tour = db.tour_supports.get(expense["tour_support_id"])
    if tour["status"] != "ADVANCED":
        raise_err("ERR_INVALID_STATE", "Tour support must be ADVANCED to approve expenses")
    label = _label_of_tour(tour)
    cap_bps = label["tour_category_caps_bps"].get(expense["category"], 0)
    category_cap = (cap_bps * tour["approved_budget_cents"]) // 10000
    category_approved = sum(
        e["amount_cents"] for e in db.tour_expenses.values()
        if e["tour_support_id"] == tour["id"]
        and e["category"] == expense["category"]
        and e["status"] == "APPROVED"
    )
    if category_approved + expense["amount_cents"] > category_cap:
        raise_err("ERR_CATEGORY_CAP_EXCEEDED", "Expense would exceed its category cap")
    if tour["approved_expense_total_cents"] + expense["amount_cents"] > tour["approved_budget_cents"]:
        raise_err("ERR_TOUR_BUDGET_EXCEEDED", "Expense would exceed the approved tour budget")
    expense["status"] = "APPROVED"
    touch(expense)
    tour["approved_expense_total_cents"] += expense["amount_cents"]
    touch(tour)
    account = account_of_contract(tour["contract_id"])
    if account is not None:
        account["tour_support_balance_cents"] += expense["amount_cents"]
        recompute_account_totals(account)
        touch(account)
    return ok(serialize(expense))


@bp.post("/api/tour-expenses/<eid>/reject")
def reject_expense(eid):
    auth(["FinanceController"])
    expense = get_or_404(db.tour_expenses, eid)
    get_body()
    if expense["status"] != "SUBMITTED":
        raise_err("ERR_INVALID_STATE", "Only a SUBMITTED expense may be rejected")
    expense["status"] = "REJECTED"
    touch(expense)
    return ok(serialize(expense))


@bp.post("/api/tour-expenses/<eid>/void")
def void_expense(eid):
    auth(["FinanceController"])
    expense = get_or_404(db.tour_expenses, eid)
    get_body()
    if expense["status"] != "APPROVED":
        raise_err("ERR_INVALID_STATE", "Only an APPROVED expense may be voided")
    tour = db.tour_supports.get(expense["tour_support_id"])
    if tour["status"] == "CLOSED":
        raise_err("ERR_INVALID_STATE", "Expenses of a CLOSED tour support cannot be voided")
    expense["status"] = "VOIDED"
    touch(expense)
    tour["approved_expense_total_cents"] -= expense["amount_cents"]
    touch(tour)
    account = account_of_contract(tour["contract_id"])
    if account is not None:
        account["tour_support_balance_cents"] -= expense["amount_cents"]
        recompute_account_totals(account)
        touch(account)
    return ok(serialize(expense))
