"""Certificate routes (PRD 3.8)."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from services import workflows as wf

bp = Blueprint("certificates", __name__)

READ = mw.ALL_ROLES


@bp.get("/certificates/<rid>")
def get_certificate(rid):
    mw.require_auth(READ)
    return response.success_object(mw.serialize(mw.get_or_404("certificates", rid)))


@bp.post("/certificates/<rid>/redeem")
def redeem_certificate(rid):
    user_id, _ = mw.require_auth(["Bidder"])
    cert = mw.get_or_404("certificates", rid)
    invoice = stores["invoices"][cert["invoice_id"]]
    # Ownership (priority 3): only the winning bidder redeems.
    if invoice["bidder_id"] != user_id:
        raise errors.err_ownership("Only the winning bidder may redeem the certificate")
    body = mw.get_json_body()
    scheduled_start = mw.require_datetime(body, "scheduled_start")
    scheduled_end = mw.require_datetime(body, "scheduled_end")
    if not scheduled_start < scheduled_end:
        raise errors.err_invalid_request("scheduled_start must be earlier than scheduled_end")
    if cert["status"] != "ISSUED":
        raise errors.err_certificate_not_redeemable()
    # Closed containment: valid_from <= scheduled_start, scheduled_end <= grace_end_at.
    if scheduled_start < cert["valid_from"] or scheduled_end > cert["grace_end_at"]:
        raise errors.err_redemption_window_invalid()
    # Half-open blackout intersection; adjacency at either edge is allowed.
    bundle = stores["bundles"].get(invoice["bundle_id"])
    if bundle is not None:
        for item in wf.member_items(bundle):
            if item["kind"] != "EXPERIENCE":
                continue
            for bw in stores["blackout_windows"].values():
                if bw["item_id"] != item["id"]:
                    continue
                if scheduled_start < bw["ends_at"] and bw["starts_at"] < scheduled_end:
                    raise errors.err_blackout_conflict()
    cert["status"] = "REDEEMED"
    cert["redeemed_at"] = clock.now()
    cert["scheduled_start"] = scheduled_start
    cert["scheduled_end"] = scheduled_end
    mw.touch(cert)
    if invoice["fulfillment_status"] == "READY":
        invoice["fulfillment_status"] = "FULFILLED"
        mw.touch(invoice)
    wf.settle_bundle_bubble(invoice)
    return response.success_object(mw.serialize(cert))
