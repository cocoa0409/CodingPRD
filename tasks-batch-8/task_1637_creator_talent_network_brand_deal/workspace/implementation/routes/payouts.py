"""Payout endpoints: list, get, release (SETTLEMENT commission), hold,
unhold."""

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import calc, helpers as H

bp = Blueprint("payouts", __name__)


@bp.route("/payouts", methods=["GET"])
@require_roles("FinanceAdmin", "Creator", "BrandManager")
def list_payouts(actor):
    items = list(db.payouts.values())
    if actor.role == "Creator":
        items = [p for p in items if p["creator_id"] == actor.user_id]
    invoice_id = request.args.get("invoice_id")
    deal_id = request.args.get("deal_id")
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    if invoice_id is not None:
        items = [p for p in items if p["invoice_id"] == invoice_id]
    if deal_id is not None:
        items = [p for p in items if p["deal_id"] == deal_id]
    if creator_id is not None:
        items = [p for p in items if p["creator_id"] == creator_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/payouts/<pid>", methods=["GET"])
@require_roles("FinanceAdmin", "Creator", "BrandManager")
def get_payout(actor, pid):
    payout = H.get_or_404(db.payouts, pid, "payout")
    if actor.role == "Creator":
        require_owner(actor, payout["creator_id"], "payout")
    return resp.ok(payout)


@bp.route("/payouts/<pid>/release", methods=["POST"])
@require_roles("FinanceAdmin")
def release_payout(actor, pid):
    payout = H.get_or_404(db.payouts, pid, "payout")
    H.body()

    if payout["status"] in ("PAID", "VOIDED", "CLAWED_BACK"):
        raise err.already_terminal(f"Payout is {payout['status']}")
    if payout["status"] != "PAYABLE":
        raise err.invalid_state("Release requires payout PAYABLE")

    # Priority 9: segregation of duties vs the invoice issuer.
    invoice = db.invoices.get(payout["invoice_id"])
    if (invoice is not None and invoice.get("issued_by_user_id") is not None
            and actor.user_id == invoice["issued_by_user_id"]):
        raise err.ApiError(err.ERR_SEGREGATION_OF_DUTIES,
                           "Payout releaser must differ from the invoice "
                           "issuer", 403)

    # Priority 11: no QUEUED/FAILED disclosure check on the deal's
    # deliverables.
    for chk in db.disclosure_checks.values():
        if chk["status"] not in ("QUEUED", "FAILED"):
            continue
        d = db.deliverables.get(chk["deliverable_id"])
        if d is not None and d["deal_id"] == payout["deal_id"]:
            raise err.ApiError(err.ERR_DISCLOSURE_NOT_PASSED,
                               "A disclosure check on this deal is still "
                               "QUEUED or FAILED", 409)

    # Priority 25: payout timing (exactly equal allowed).
    now = db.get_clock()
    due_at = db.parse_iso(payout["payout_due_at"]) if payout.get(
        "payout_due_at") else None
    if due_at is None or now < due_at:
        raise err.ApiError(err.ERR_PAYOUT_NOT_DUE,
                           "Payout is not yet due", 422)

    # SETTLEMENT variant: tier reads lifetime_billed_cents INCLUDING this
    # invoice's fee line (already added at record-payment).
    creator = db.creators.get(payout["creator_id"])
    lifetime = int(creator.get("lifetime_billed_cents", 0)) if creator else 0
    rate_bps, commission_cents, net_cents = calc.commission(
        lifetime, int(payout["gross_cents"]))
    payout["commission_rate_bps"] = rate_bps
    payout["commission_cents"] = commission_cents
    payout["net_cents"] = net_cents
    payout["released_by_user_id"] = actor.user_id
    payout["released_at"] = db.now_iso()
    payout["status"] = "PAID"
    H.touch(payout)
    return resp.ok(payout)


@bp.route("/payouts/<pid>/hold", methods=["POST"])
@require_roles("FinanceAdmin")
def hold_payout(actor, pid):
    payout = H.get_or_404(db.payouts, pid, "payout")
    H.body()
    if payout["status"] in ("PAID", "VOIDED", "CLAWED_BACK"):
        raise err.already_terminal(f"Payout is {payout['status']}")
    if payout["status"] not in ("ACCRUED", "PAYABLE"):
        raise err.invalid_state("Hold requires payout ACCRUED or PAYABLE")
    payout["status"] = "HELD"
    H.touch(payout)
    return resp.ok(payout)


@bp.route("/payouts/<pid>/unhold", methods=["POST"])
@require_roles("FinanceAdmin")
def unhold_payout(actor, pid):
    payout = H.get_or_404(db.payouts, pid, "payout")
    H.body()
    if payout["status"] in ("PAID", "VOIDED", "CLAWED_BACK"):
        raise err.already_terminal(f"Payout is {payout['status']}")
    if payout["status"] != "HELD":
        raise err.invalid_state("Unhold requires payout HELD")
    payout["status"] = "PAYABLE" if payout.get("payout_due_at") else "ACCRUED"
    H.touch(payout)
    return resp.ok(payout)
