"""Make-good credits and invoices (PRD 3.8)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth, client_owner_guard
from response import ok, ok_list
from services import (
    apply_make_good_credits,
    cancellation_penalty,
    flight_subtotal,
    get_campaign,
    get_credit,
    get_invoice,
    maybe_complete_campaign,
    new_record,
    pub,
    recompute_campaign,
    recompute_client_balance,
    sorted_created,
    touch,
)
from util import as_month, body, pagination_args, required

bp = Blueprint("billing", __name__, url_prefix="/btaa")

CREDIT_READ = ["PlatformAdmin", "FinanceOfficer", "ComplianceOfficer", "Client"]


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Make-good credits
# ---------------------------------------------------------------------------
@bp.get("/campaigns/<cid>/make_good_credits")
def list_campaign_credits(cid):
    user_id, role = auth(CREDIT_READ)
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    recs = [c for c in DB["make_good_credits"].values() if c["campaign_id"] == camp["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/make_good_credits/<mid>")
def get_one_credit(mid):
    user_id, role = auth(CREDIT_READ)
    c = get_credit(mid)
    camp = DB["campaigns"].get(c["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(c))


@bp.get("/make_good_credits")
def list_credits_system():
    user_id, role = auth(CREDIT_READ)
    recs = list(DB["make_good_credits"].values())
    if role == "Client":
        own = {c["id"] for c in DB["campaigns"].values() if c["client_id"] == user_id}
        recs = [c for c in recs if c["campaign_id"] in own]
    return _list(
        recs,
        {
            "source_slot_id": request.args.get("source_slot_id"),
            "campaign_id": request.args.get("campaign_id"),
            "status": request.args.get("status"),
        },
    )


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.post("/campaigns/<cid>/invoices")
def issue_invoice(cid):
    auth(["FinanceOfficer"])
    camp = get_campaign(cid)
    data = body()
    period = as_month(required(data, "period_yyyy_mm"), "period_yyyy_mm")

    # Pinned computation order (PRD 3.8): flight subtotal, then penalties,
    # then the make-good credit waterfall, then the floored total.
    subtotal = flight_subtotal(camp["id"], period, provisional=False)
    penalty = cancellation_penalty(camp["id"], period)
    available = subtotal + penalty
    applied, applications = apply_make_good_credits(camp, period, available)
    total = max(0, available - applied)

    rec = new_record()
    rec.update(
        {
            "campaign_id": camp["id"],
            "period_yyyy_mm": period,
            "flight_subtotal_cents": subtotal,
            "cancellation_penalty_cents": penalty,
            "make_good_applied_cents": applied,
            "total_cents": total,
            "balance_due_cents": total,
            "status": "ISSUED",
            "_applications": applications,
        }
    )
    DB["invoices"][rec["id"]] = rec
    recompute_campaign(camp)
    client = DB["clients"].get(camp["client_id"])
    if client is not None:
        recompute_client_balance(client)
    return ok(pub(rec), status=201)


@bp.get("/campaigns/<cid>/invoices")
def list_campaign_invoices(cid):
    user_id, role = auth(CREDIT_READ)
    camp = get_campaign(cid)
    client_owner_guard(role, user_id, camp["client_id"])
    recs = [i for i in DB["invoices"].values() if i["campaign_id"] == camp["id"]]
    return _list(
        recs,
        {
            "status": request.args.get("status"),
            "period_yyyy_mm": request.args.get("period_yyyy_mm"),
        },
    )


@bp.get("/invoices/<iid>")
def get_one_invoice(iid):
    user_id, role = auth(CREDIT_READ)
    inv = get_invoice(iid)
    camp = DB["campaigns"].get(inv["campaign_id"])
    if camp:
        client_owner_guard(role, user_id, camp["client_id"])
    return ok(pub(inv))


@bp.post("/invoices/<iid>/mark_paid")
def mark_paid_invoice(iid):
    auth(["FinanceOfficer"])
    inv = get_invoice(iid)
    if inv["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Invoice is not in a state permitting mark_paid",
        )
    inv["status"] = "PAID"
    touch(inv)
    camp = DB["campaigns"].get(inv["campaign_id"])
    if camp is not None:
        client = DB["clients"].get(camp["client_id"])
        if client is not None:
            recompute_client_balance(client)
        maybe_complete_campaign(camp)
    return ok(pub(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    auth(["FinanceOfficer"])
    inv = get_invoice(iid)
    if inv["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Invoice is not in a state permitting void",
        )
    inv["status"] = "VOID"
    touch(inv)
    # Compensating action: every applied MakeGoodCredit reverts — remaining
    # restored; status OPEN when fully restored else PARTIALLY_APPLIED.
    affected_campaigns = set()
    for app in inv.get("_applications", []):
        credit = DB["make_good_credits"].get(app["credit_id"])
        if credit is None:
            continue
        credit["remaining_cents"] = min(
            credit["original_cents"], credit["remaining_cents"] + app["applied_cents"]
        )
        credit["status"] = (
            "OPEN"
            if credit["remaining_cents"] == credit["original_cents"]
            else "PARTIALLY_APPLIED"
        )
        touch(credit)
        affected_campaigns.add(credit["campaign_id"])
    camp = DB["campaigns"].get(inv["campaign_id"])
    if camp is not None:
        affected_campaigns.add(camp["id"])
        client = DB["clients"].get(camp["client_id"])
        if client is not None:
            recompute_client_balance(client)
    for camp_id in affected_campaigns:
        c2 = DB["campaigns"].get(camp_id)
        if c2 is not None:
            recompute_campaign(c2)
            maybe_complete_campaign(c2)
    return ok(pub(inv))
