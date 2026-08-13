"""Partner billing record endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import require_roles
from response import success_object, paginate
from util import new_uuid, stamp_new, touch
from services.billing import post_event, AUTO_RECONCILE_TOLERANCE_CENTS

bp = Blueprint("partner_billing", __name__)


@bp.route("/v1/partner-billing-records", methods=["POST"])
def create_record():
    require_roles("PartnerBillingOps", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    for f in ["partner_code", "account_id", "partner_subscription_ref",
              "expected_amount_cents", "period_start_utc", "period_end_utc"]:
        if f not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"missing field: {f}")
    acct = db.accounts.get(body["account_id"])
    if not acct:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "account not found")
    rec = stamp_new({
        "partner_billing_record_id": new_uuid(),
        "partner_code": body["partner_code"],
        "account_id": body["account_id"],
        "partner_subscription_ref": body["partner_subscription_ref"],
        "report_status": "EXPECTED",
        "expected_amount_cents": body["expected_amount_cents"],
        "received_amount_cents": 0,
        "period_start_utc": body["period_start_utc"],
        "period_end_utc": body["period_end_utc"],
    })
    db.partner_billing_records[rec["partner_billing_record_id"]] = rec
    return success_object(rec, 201)


@bp.route("/v1/partner-billing-records", methods=["GET"])
def list_records():
    require_roles("PartnerBillingOps", "PlatformAdmin", "SupportAgent")
    items = list(db.partner_billing_records.values())
    for f in ["account_id", "partner_code", "report_status"]:
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if str(r.get(f)) == v]
    return paginate(items, request.args)


def _get(rid):
    r = db.partner_billing_records.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "partner billing record not found")
    return r


@bp.route("/v1/partner-billing-records/<rid>", methods=["GET"])
def get_record(rid):
    require_roles("PartnerBillingOps", "PlatformAdmin", "SupportAgent")
    return success_object(_get(rid))


@bp.route("/v1/partner-billing-records/<rid>/report-receipt", methods=["POST"])
def report_receipt(rid):
    require_roles("PartnerBillingOps")
    r = _get(rid)
    body = request.get_json(silent=True) or {}
    if "received_amount_cents" not in body or not isinstance(body["received_amount_cents"], int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "received_amount_cents required (integer)")
    if r["report_status"] != "EXPECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Record not EXPECTED")
    r["received_amount_cents"] = body["received_amount_cents"]
    r["report_status"] = "RECEIVED"
    touch(r)
    return success_object(r)


@bp.route("/v1/partner-billing-records/<rid>/reconcile", methods=["POST"])
def reconcile(rid):
    uid, role = require_roles("PartnerBillingOps", "PlatformAdmin")
    r = _get(rid)
    body = request.get_json(silent=True) or {}
    expected_version = body.get("expected_partner_billing_record_version")
    override = bool(body.get("override", False))
    if r["report_status"] not in ("RECEIVED", "DISCREPANCY"):
        raise ApiError("ERR_INVALID_STATE", 409, "Record not reconcilable")
    # OCC
    if expected_version is not None and expected_version != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale record version")
    delta = r["received_amount_cents"] - r["expected_amount_cents"]
    if r["report_status"] == "RECEIVED":
        if abs(delta) <= AUTO_RECONCILE_TOLERANCE_CENTS:
            r["report_status"] = "RECONCILED"
            touch(r)
            _post_partner_charge(r, None)
        else:
            r["report_status"] = "DISCREPANCY"
            touch(r)
    else:  # DISCREPANCY
        if not override:
            raise ApiError("ERR_RECONCILE_DELTA_EXCEEDS_TOLERANCE", 422,
                           "Delta exceeds tolerance and override not provided")
        if role != "PlatformAdmin":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Override requires PlatformAdmin")
        r["report_status"] = "RECONCILED"
        touch(r)
        _post_partner_charge(r, f"reconciled with override; delta={delta}")
    return success_object(r)


def _post_partner_charge(record, notes):
    sub = None
    acct = db.accounts.get(record["account_id"])
    if acct and acct.get("active_subscription_id"):
        sub = db.subscriptions.get(acct["active_subscription_id"])
    sub_id = sub["subscription_id"] if sub else None
    if sub_id is None:
        # Fall back to any subscription on the account
        for s in db.subscriptions.values():
            if s["account_id"] == record["account_id"]:
                sub_id = s["subscription_id"]
                break
    post_event(record["account_id"], sub_id, "CHARGE", record["received_amount_cents"],
               external_reference=record.get("partner_subscription_ref"), notes=notes)


@bp.route("/v1/partner-billing-records/<rid>/write-off", methods=["POST"])
def write_off(rid):
    require_roles("PlatformAdmin")
    r = _get(rid)
    if r["report_status"] != "DISCREPANCY":
        raise ApiError("ERR_INVALID_STATE", 409, "Record not DISCREPANCY")
    r["report_status"] = "WRITE_OFF"
    touch(r)
    return success_object(r)
