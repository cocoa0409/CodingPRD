"""Ops endpoints: logical clock and the vendor sweep (ops-run checkpoint)."""
from datetime import timedelta

from flask import Blueprint

import db
import services as svc
from middleware import require_auth, require_role, get_body, req_str, parse_iso_instant
from response import ok

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = require_auth()
    require_role(ctx, ["SystemAdmin"])
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    db.set_clock(parse_iso_instant(to_iso, "to_iso8601"))
    return ok({"current_utc": db.fmt_ts(db.now())})


@bp.route("/vendor-sweeps/run", methods=["POST"])
def run_sweep():
    ctx = require_auth()
    require_role(ctx, ["SystemAdmin"])
    now = db.now()
    today_s = db.today().isoformat()

    vendors_marked_dormant = 0
    vendors_deactivated = 0
    documents_expired = 0
    callbacks_expired = 0

    # Pass 1: dormancy evaluation (ACTIVE -> DORMANT), >= boundary semantics
    for vendor in list(db.vendors.values()):
        if vendor["status"] != "ACTIVE":
            continue
        ref = vendor.get("last_payment_cleared_at") or vendor.get("first_activated_at")
        if not ref:
            continue
        ref_dt = svc.datetime_from_iso(ref)
        if now - ref_dt < timedelta(days=svc.DORMANCY_DAYS):
            continue
        if svc.vendor_has_open_invoices(vendor["id"]):
            continue
        old = vendor["status"]
        vendor["status"] = "DORMANT"
        vendor["dormant_since_at"] = db.fmt_ts(now)
        db.touch(vendor)
        svc.audit_status_change("Vendor", vendor["id"], old, "DORMANT", ctx)
        vendors_marked_dormant += 1

    # Pass 2: DORMANT -> DEACTIVATED past the deactivation horizon
    for vendor in list(db.vendors.values()):
        if vendor["status"] != "DORMANT":
            continue
        since = vendor.get("dormant_since_at")
        if not since:
            continue
        if now - svc.datetime_from_iso(since) < timedelta(days=svc.DORMANT_DEACTIVATE_DAYS):
            continue
        if svc.vendor_has_open_invoices(vendor["id"]):
            continue
        old = vendor["status"]
        vendor["status"] = "DEACTIVATED"
        db.touch(vendor)
        svc.audit_status_change("Vendor", vendor["id"], old, "DEACTIVATED", ctx)
        vendors_deactivated += 1

    # Pass 3: document EXPIRED cache update (valid_until strictly before today)
    for doc in list(db.documents.values()):
        if doc["status"] == "VALID" and doc["valid_until"] < today_s:
            doc["status"] = "EXPIRED"
            db.touch(doc)
            svc.audit_status_change("VendorDocument", doc["id"], "VALID", "EXPIRED", ctx)
            documents_expired += 1

    # Pass 4: callback verification expiry cascade (strict > expires_at)
    for ver in list(db.callback_verifications.values()):
        if ver["status"] != "PENDING":
            continue
        if now <= svc.datetime_from_iso(ver["expires_at"]):
            continue
        ver["status"] = "EXPIRED"
        db.touch(ver)
        svc.audit_status_change("CallbackVerification", ver["id"], "PENDING", "EXPIRED", ctx)
        acct = db.bank_accounts.get(ver["bank_account_id"])
        if acct is not None and acct["status"] == "PENDING_VERIFICATION":
            acct["status"] = "REJECTED"
            db.touch(acct)
            svc.audit_status_change("VendorBankAccount", acct["id"], "PENDING_VERIFICATION", "REJECTED", ctx)
        callbacks_expired += 1

    return ok({
        "vendors_marked_dormant": vendors_marked_dormant,
        "vendors_deactivated": vendors_deactivated,
        "documents_expired": documents_expired,
        "callback_verifications_expired": callbacks_expired,
    })
