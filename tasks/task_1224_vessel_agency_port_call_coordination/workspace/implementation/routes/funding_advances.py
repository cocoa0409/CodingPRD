"""FundingAdvance endpoints."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import is_int, paginate, pagination_args, sort_created, touch

bp = Blueprint("funding_advances", __name__)


def _get_or_404(aid):
    ent = domain.get("funding_advances", aid)
    if ent is None:
        not_found("funding advance")
    return ent


@bp.get("/funding-advances")
def list_funding_advances():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("funding_advances"))
    for param in ("da_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/funding-advances/<aid>")
def get_funding_advance(aid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(aid)))


@bp.post("/funding-advances/<aid>/apply")
def apply_funding_advance(aid):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(aid)
    da = domain.get("disbursement_accounts", ent["da_id"])
    if ent["status"] != "RECEIVED":
        invalid_state("Only a RECEIVED advance can be applied")
    if da is None or da["status"] not in ("FUNDED", "FINAL", "DISPUTED"):
        invalid_state("The account must be FUNDED, FINAL or DISPUTED to apply an advance")
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if is_int(amount):
        remaining = ent["amount_cents"] - ent["applied_cents"] - ent["refunded_cents"]
        if amount <= 0 or amount > remaining:
            raise_err("ERR_APPLY_EXCEEDS_REMAINING",
                      "The amount must be positive and within the remaining balance")
    if not is_int(amount):
        invalid_request("amount_cents must be a positive integer")
    ent["applied_cents"] += amount
    if ent["applied_cents"] == ent["amount_cents"]:
        ent["status"] = "APPLIED"
    touch(ent)
    domain.recompute_da_totals(da)
    return ok_object(serialize(ent))


@bp.post("/funding-advances/<aid>/refund")
def refund_funding_advance(aid):
    require_roles(["AgencyFinance"])
    ent = _get_or_404(aid)
    da = domain.get("disbursement_accounts", ent["da_id"])
    if ent["status"] != "RECEIVED":
        invalid_state("Only a RECEIVED advance can be refunded")
    if da is None or da["status"] not in ("SENT_TO_PRINCIPAL", "FUNDED", "FINAL", "DISPUTED"):
        invalid_state("The account status does not permit refunds")
    ent["refunded_cents"] = ent["amount_cents"] - ent["applied_cents"]
    ent["status"] = "REFUNDED"
    touch(ent)
    domain.recompute_da_totals(da)
    return ok_object(serialize(ent))
