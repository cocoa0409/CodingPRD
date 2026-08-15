"""Invoice endpoints: create (frozen billing, auto make-good on shortfall),
get, list, ISSUE / DISPUTE / MARK_PAID transitions."""

from flask import Blueprint, request

import db
from errors import (
    err_not_found,
    err_invalid,
    err_conflict,
    ERR_CAMPAIGN_NOT_ENDED,
    ERR_MEASUREMENT_PENDING,
    ERR_INVOICE_STATE,
    ERR_MAKE_GOOD_OUTSTANDING,
)
from helpers import body_of, new_id, now_timestamp, require_string
from middleware import require_roles
from response import success_object, list_response, serialize
from services import (
    Changes,
    billing_breakdown,
    commission_and_net,
    maybe_reconcile,
)

bp = Blueprint("invoices", __name__)

READ_ROLES = {"AdOps", "Advertiser", "Agency", "Finance"}


def get_invoice_or_404(invoice_id):
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        raise err_not_found(f"Invoice '{invoice_id}' not found")
    return invoice


@bp.route("/adnet/invoices", methods=["POST"])
def create_invoice():
    require_roles({"Finance"})
    body = body_of(request)

    campaign_id = body.get("campaign_id")
    campaign = None
    if isinstance(campaign_id, str):
        campaign = db.campaigns.get(campaign_id)
        if campaign is None:
            raise err_not_found(f"Campaign '{campaign_id}' not found")

    # State: the campaign must be ENDED.
    if campaign is not None and campaign["status"] != "ENDED":
        raise err_conflict(
            ERR_CAMPAIGN_NOT_ENDED,
            f"Campaign is {campaign['status']}; invoices require ENDED",
        )

    # Temporal: every impression-producing episode of the campaign must be
    # MEASURED (vacuously true when nothing served).
    if campaign is not None:
        episode_ids = set()
        for imp in db.impressions.values():
            if imp["campaign_id"] == campaign["id"]:
                download = db.downloads.get(imp["download_id"])
                if download is not None:
                    episode_ids.add(download["episode_id"])
        for ep_id in episode_ids:
            ep = db.episodes.get(ep_id)
            if ep is not None and ep["status"] != "MEASURED":
                raise err_conflict(
                    ERR_MEASUREMENT_PENDING,
                    "An impression-producing episode is not MEASURED yet",
                )

    # Field shape (catch-all): campaign_id required; one invoice per campaign.
    campaign_id = require_string(body, "campaign_id")
    if campaign is None:
        raise err_not_found(f"Campaign '{campaign_id}' not found")
    if any(inv["campaign_id"] == campaign_id for inv in db.invoices.values()):
        raise err_invalid("An invoice already exists for this campaign")

    lines, delivered_billed, shortfall, gross = billing_breakdown(campaign)
    commission, net = commission_and_net(campaign, gross, shortfall, 0)

    ts = now_timestamp()
    invoice = {
        "id": new_id(),
        "campaign_id": campaign_id,
        "billing_model": campaign["billing_model"],
        "delivered_impressions_billed": delivered_billed,
        "lines": lines,
        "gross_cents": gross,
        "shortfall_impressions": shortfall,
        "make_good_credit_cents": 0,
        "agency_commission_cents": commission,
        "net_cents": net,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.invoices[invoice["id"]] = invoice

    # Auto-create exactly one OFFERED MakeGood when the flight fell short.
    if shortfall > 0:
        make_good = {
            "id": new_id(),
            "campaign_id": campaign_id,
            "invoice_id": invoice["id"],
            "granted_impressions": shortfall,
            "baseline_delivered_impressions": None,
            "status": "OFFERED",
            "created_at": now_timestamp(),
            "updated_at": now_timestamp(),
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.make_goods[make_good["id"]] = make_good

    return success_object(serialize(invoice), 201)


@bp.route("/adnet/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    require_roles(READ_ROLES)
    return success_object(serialize(get_invoice_or_404(invoice_id)))


@bp.route("/adnet/invoices", methods=["GET"])
def list_invoices():
    require_roles(READ_ROLES)
    items = list(db.invoices.values())
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    if campaign_id is not None:
        items = [i for i in items if i["campaign_id"] == campaign_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_response(items, request.args)


@bp.route("/adnet/invoices/<invoice_id>/transition", methods=["POST"])
def transition_invoice(invoice_id):
    require_roles({"Finance"})
    invoice = get_invoice_or_404(invoice_id)
    body = body_of(request)
    action = body.get("action")
    if action not in ("ISSUE", "DISPUTE", "MARK_PAID"):
        raise err_invalid("Field 'action' must be one of ISSUE, DISPUTE, MARK_PAID")

    allowed = {
        "ISSUE": {"DRAFT", "DISPUTED"},
        "DISPUTE": {"ISSUED"},
        "MARK_PAID": {"ISSUED"},
    }[action]
    if invoice["status"] not in allowed:
        raise err_conflict(
            ERR_INVOICE_STATE,
            f"Invoice is {invoice['status']}; {action} is not permitted from this state",
        )

    if action == "ISSUE":
        # Issuance is blocked while a make-good of the campaign is OFFERED.
        outstanding = any(
            mg["campaign_id"] == invoice["campaign_id"] and mg["status"] == "OFFERED"
            for mg in db.make_goods.values()
        )
        if outstanding:
            raise err_conflict(
                ERR_MAKE_GOOD_OUTSTANDING,
                "A MakeGood of this campaign is still OFFERED",
            )
        # Re-issuing a disputed invoice never recomputes the frozen amounts.
        ch = Changes()
        ch.update(invoice, status="ISSUED")
        ch.commit()
    elif action == "DISPUTE":
        ch = Changes()
        ch.update(invoice, status="DISPUTED")
        ch.commit()
    else:  # MARK_PAID
        ch = Changes()
        ch.update(invoice, status="PAID")
        campaign = db.campaigns.get(invoice["campaign_id"])
        if campaign is not None:
            maybe_reconcile(campaign, ch)
        ch.commit()
    return success_object(serialize(invoice))
