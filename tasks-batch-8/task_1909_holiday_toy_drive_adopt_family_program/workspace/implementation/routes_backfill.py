"""Backfill selector and BackfillPurchase lifecycle."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import clock
import db
from domain import (
    make_row, touch, sort_rows, family_rollup,
    recompute_child_estimate, recompute_adoptions_for_family,
    ser_backfill,
)
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, err_sod,
    err_backfill_budget,
)
from middleware import require_roles
from response import success_object, success_list, success_created
from util import get_body, req_field, as_int, age_years_at

bp = Blueprint("backfill", __name__)

WAIT_DAY_CAP = 30
AGE_BASELINE = 18


def _provisional_remaining(campaign):
    ordered = sum(
        p["quoted_cost_cents"]
        for p in db.backfill_purchases.values()
        if p["campaign_id"] == campaign["id"] and p["status"] == "ORDERED"
    )
    return campaign["backfill_budget_cents"] - campaign["backfill_spent_cents"] - ordered


def _approved_items(child_id):
    return sort_rows([
        w for w in db.wish_items.values()
        if w["child_id"] == child_id and w["status"] == "APPROVED"
    ])


@bp.route("/campaigns/<cid>/backfill/select", methods=["POST"])
@require_roles("PlatformAdmin")
def backfill_select(actor, cid):
    campaign = db.campaigns.get(cid)
    if campaign is None:
        raise err_not_found("Campaign not found")
    body = get_body(required=True)
    limit = as_int(req_field(body, "limit"), "limit")
    if limit < 1:
        raise err_invalid_request("limit must be >= 1")

    now = clock.now()
    candidates = []
    for child in db.children.values():
        if child["status"] != "BACKFILL_ELIGIBLE":
            continue
        fam = db.families.get(child["family_id"])
        if fam is None or fam["campaign_id"] != cid:
            continue
        if fam["status"] not in ("MATCHED", "PARTIALLY_FULFILLED"):
            continue
        approved = _approved_items(child["id"])
        if not approved:
            continue
        min_rank = min(w["priority_rank"] for w in approved)
        priority_weight = Decimal(11 - min_rank) / Decimal(10)
        years = age_years_at(child["_dob"], campaign["distribution_date"])
        age_urgency = (AGE_BASELINE - years) * 2
        if fam["verified_at"] is not None:
            wait = int((now - fam["verified_at"]).total_seconds() // 86400)
        else:
            wait = 0
        wait = max(0, min(WAIT_DAY_CAP, wait))
        score = (Decimal(100) * priority_weight) + Decimal(age_urgency) + Decimal(wait)
        score = score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        candidates.append({
            "child": child,
            "family": fam,
            "approved": approved,
            "score": score,
            "cost": sum(w["estimated_price_cents"] for w in approved),
        })

    candidates.sort(
        key=lambda c: (
            -c["score"],
            c["family"]["verified_at"] or c["family"]["created_at"],
            c["child"]["created_at"],
            c["child"]["_seq"],
        )
    )

    created = []
    remaining = _provisional_remaining(campaign)
    for cand in candidates:
        if len(created) >= limit:
            break
        if cand["cost"] > remaining:
            continue  # budget insufficient for full wish list; skip down the ranking
        child = cand["child"]
        top_item = min(cand["approved"], key=lambda w: (w["priority_rank"], w["created_at"], w["_seq"]))
        row = make_row()
        row.update(
            campaign_id=cid,
            child_id=child["id"],
            wish_item_id=top_item["id"],
            quoted_cost_cents=cand["cost"],
            final_cost_cents=None,
            status="ORDERED",
            purchased_at=None,
            created_by=actor.user_id,
        )
        db.backfill_purchases[row["id"]] = row
        remaining -= cand["cost"]
        created.append(row)

    body_out = [ser_backfill(p) for p in created]
    from response import _meta
    from flask import jsonify
    return jsonify({
        "meta": _meta(),
        "response_type": "array",
        "data": body_out,
    }), 201


@bp.route("/backfill-purchases", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def list_backfill(actor):
    rows = list(db.backfill_purchases.values())
    for param in ("campaign_id", "child_id", "wish_item_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [p for p in rows if str(p.get(param)) == val]
    return success_list(sort_rows(rows), ser_backfill)


@bp.route("/backfill-purchases/<pid>", methods=["GET"])
@require_roles("PlatformAdmin", "CaseWorker", "DistributionVolunteer")
def get_backfill(actor, pid):
    row = db.backfill_purchases.get(pid)
    if row is None:
        raise err_not_found("BackfillPurchase not found")
    return success_object(ser_backfill(row))


@bp.route("/backfill-purchases/<pid>/mark-purchased", methods=["POST"])
@require_roles("PlatformAdmin")
def mark_purchased(actor, pid):
    purchase = db.backfill_purchases.get(pid)
    if purchase is None:
        raise err_not_found("BackfillPurchase not found")
    body = get_body(required=True)
    final_cost = as_int(req_field(body, "final_cost_cents"), "final_cost_cents")
    if final_cost < 0:
        raise err_invalid_request("final_cost_cents must be >= 0")
    if purchase["status"] != "ORDERED":
        raise err_invalid_state("mark-purchased requires purchase in ORDERED")
    if purchase.get("created_by") == actor.user_id:
        raise err_sod("The PlatformAdmin who created a BackfillPurchase may not mark it purchased")
    campaign = db.campaigns[purchase["campaign_id"]]
    if campaign["backfill_spent_cents"] + final_cost > campaign["backfill_budget_cents"]:
        raise err_backfill_budget()

    now = clock.now()
    purchase["status"] = "PURCHASED"
    purchase["final_cost_cents"] = final_cost
    purchase["purchased_at"] = now
    touch(purchase)
    campaign["backfill_spent_cents"] += final_cost
    touch(campaign)

    child = db.children.get(purchase["child_id"])
    family = None
    if child is not None:
        if child["status"] == "BACKFILL_ELIGIBLE":
            child["status"] = "BACKFILL_PURCHASED"
            touch(child)
        family = db.families.get(child["family_id"])

    item = db.wish_items.get(purchase["wish_item_id"])
    if item is not None and item["status"] == "APPROVED":
        item["status"] = "BACKFILL_SOURCED"
        touch(item)
        if child is not None:
            recompute_child_estimate(child)

    for g in db.gifts.values():
        if g.get("wish_item_id") == purchase["wish_item_id"] and g["status"] == "COMMITTED":
            g["status"] = "BACKFILL_REPLACED"
            touch(g)

    if family is not None:
        family_rollup(family, adjust_status=True)
        recompute_adoptions_for_family(family)
    return success_object(ser_backfill(purchase))


@bp.route("/backfill-purchases/<pid>/cancel", methods=["POST"])
@require_roles("PlatformAdmin")
def cancel_backfill(actor, pid):
    purchase = db.backfill_purchases.get(pid)
    if purchase is None:
        raise err_not_found("BackfillPurchase not found")
    get_body()
    if purchase["status"] != "ORDERED":
        raise err_invalid_state("cancel requires purchase in ORDERED")
    purchase["status"] = "CANCELLED"
    touch(purchase)
    return success_object(ser_backfill(purchase))


@bp.route("/backfill-purchases/<pid>/sort", methods=["POST"])
@require_roles("DistributionVolunteer")
def sort_backfill(actor, pid):
    purchase = db.backfill_purchases.get(pid)
    if purchase is None:
        raise err_not_found("BackfillPurchase not found")
    get_body()
    if purchase["status"] != "PURCHASED":
        raise err_invalid_state("sort requires purchase in PURCHASED")
    campaign = db.campaigns[purchase["campaign_id"]]
    if campaign["status"] not in ("DISTRIBUTION_PREP", "DISTRIBUTION"):
        raise err_invalid_state("Campaign must be in DISTRIBUTION_PREP or DISTRIBUTION to sort")
    purchase["status"] = "SORTED"
    touch(purchase)
    return success_object(ser_backfill(purchase))
