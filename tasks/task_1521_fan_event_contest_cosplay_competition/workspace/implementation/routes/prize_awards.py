"""PrizeAward routes: create/approve/disburse/mark-tax-reported/revoke."""

from flask import Blueprint, request

from db import DB, new_id, now_ts
from errors import (
    err_not_found, err_invalid_state, err_category_not_tabulated,
    err_placement_not_found, err_prize_budget_exceeded,
    err_segregation_of_duties, err_tax_form_required,
)
from middleware import require_roles
from response import success
from services.calculations import (
    TAX_THRESHOLD_CENTS, budget_reserved, payout_net,
)
from services.helpers import body_json, req_str, req_int, req_bool
from services.serializers import prize_award_view, paginate

bp = Blueprint("prize_awards", __name__)


@bp.route("/prize-awards", methods=["POST"])
def create_award():
    user_id, _ = require_roles("Treasurer")
    body = body_json()
    category_id = req_str(body, "category_id")
    rank = req_int(body, "rank", minimum=1, maximum=3)

    category = DB.categories.get(category_id)
    if category is None:
        raise err_not_found("Category not found")

    if category["status"] != "TABULATED":
        raise err_category_not_tabulated()

    # Selector: the PLACED entry of this category with placement_rank == rank.
    entry = None
    for e in DB.entries.values():
        if (
            e["category_id"] == category_id
            and e["status"] == "PLACED"
            and e["placement_rank"] == rank
        ):
            entry = e
            break
    if entry is None:
        raise err_placement_not_found()

    value_cents = category[f"prize_rank{rank}_cents"]
    contest_id = category["contest_id"]
    contest = DB.contest_events.get(contest_id)
    if contest is None:
        raise err_not_found("ContestEvent not found")

    # Fiscal: budget reservation must not exceed the budget.
    if budget_reserved(contest_id) + value_cents > contest["prize_budget_cents"]:
        raise err_prize_budget_exceeded()

    ts = now_ts()
    award = {
        "id": new_id(),
        "category_id": category_id,
        "contest_id": contest_id,
        "rank": rank,
        "entry_id": entry["id"],
        "value_cents": value_cents,
        "tax_reportable": value_cents >= TAX_THRESHOLD_CENTS,
        "tax_form_received": False,
        "withheld_cents": None,
        "net_payout_cents": None,
        "status": "PENDING",
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.prize_awards[award["id"]] = award
    return success(prize_award_view(award), status=201)


@bp.route("/prize-awards", methods=["GET"])
def list_awards():
    require_roles("Treasurer", "ContestLead")
    items = list(DB.prize_awards.values())
    category_id = request.args.get("category_id")
    entry_id = request.args.get("entry_id")
    contest_id = request.args.get("contest_id")
    status = request.args.get("status")
    if category_id is not None:
        items = [a for a in items if a["category_id"] == category_id]
    if entry_id is not None:
        items = [a for a in items if a["entry_id"] == entry_id]
    if contest_id is not None:
        items = [a for a in items if a["contest_id"] == contest_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    page, pag = paginate([prize_award_view(a) for a in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/prize-awards/<aid>", methods=["GET"])
def get_award(aid):
    require_roles("Treasurer", "ContestLead")
    award = DB.prize_awards.get(aid)
    if award is None:
        raise err_not_found("PrizeAward not found")
    return success(prize_award_view(award))


@bp.route("/prize-awards/<aid>/approve", methods=["POST"])
def approve_award(aid):
    user_id, _ = require_roles("Treasurer")
    award = DB.prize_awards.get(aid)
    if award is None:
        raise err_not_found("PrizeAward not found")
    if award["status"] != "PENDING":
        raise err_invalid_state("Only PENDING awards can be approved")
    if user_id == award["created_by_user_id"]:
        raise err_segregation_of_duties()
    award["status"] = "APPROVED"
    award["approved_by_user_id"] = user_id
    award["updated_at"] = now_ts()
    award["version"] += 1
    return success(prize_award_view(award))


@bp.route("/prize-awards/<aid>/disburse", methods=["POST"])
def disburse_award(aid):
    require_roles("Treasurer")
    body = body_json()
    tax_form_received = req_bool(body, "tax_form_received")
    award = DB.prize_awards.get(aid)
    if award is None:
        raise err_not_found("PrizeAward not found")
    if award["status"] != "APPROVED":
        raise err_invalid_state("Only APPROVED awards can be disbursed")

    withheld, net = payout_net(award["value_cents"], tax_form_received)
    award["tax_form_received"] = tax_form_received
    award["withheld_cents"] = withheld
    award["net_payout_cents"] = net
    award["status"] = "DISBURSED"
    award["updated_at"] = now_ts()
    award["version"] += 1
    return success(prize_award_view(award))


@bp.route("/prize-awards/<aid>/mark-tax-reported", methods=["POST"])
def mark_tax_reported(aid):
    require_roles("Treasurer")
    award = DB.prize_awards.get(aid)
    if award is None:
        raise err_not_found("PrizeAward not found")
    if award["status"] != "DISBURSED":
        raise err_invalid_state("Only DISBURSED awards can be marked tax-reported")
    if not award["tax_reportable"]:
        raise err_invalid_state("Sub-threshold prizes are never tax reported")
    if not award["tax_form_received"]:
        raise err_tax_form_required()
    award["status"] = "TAX_REPORTED"
    award["updated_at"] = now_ts()
    award["version"] += 1
    return success(prize_award_view(award))


@bp.route("/prize-awards/<aid>/revoke", methods=["POST"])
def revoke_award(aid):
    require_roles("ContestLead")
    award = DB.prize_awards.get(aid)
    if award is None:
        raise err_not_found("PrizeAward not found")
    if award["status"] not in ("PENDING", "APPROVED"):
        raise err_invalid_state("Only PENDING or APPROVED awards can be revoked")
    award["status"] = "REVOKED"
    award["updated_at"] = now_ts()
    award["version"] += 1
    return success(prize_award_view(award))
