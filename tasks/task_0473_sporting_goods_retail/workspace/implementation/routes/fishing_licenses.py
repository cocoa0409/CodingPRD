"""Fishing-license routes: issue, get, list/filter (PRD §3.4).

A FishingLicense is immutable after issuance: only POST and GET exist and it
carries only id + created_at (no version / updated_at, PRD §2.4).
"""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_str
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404
from services import serializers, pricing
from clock import clock, format_iso8601_ms, add_days

bp = Blueprint("fishing_licenses", __name__)


def _valid_state_code(code):
    return isinstance(code, str) and len(code) == 2 and code.isalpha() and code.isupper()


@bp.route("/fishing-licenses", methods=["POST"])
@require_roles("StoreAssociate")
def issue_fishing_license():
    body = get_body()
    customer_id = as_str(body, "customer_id", required=True)
    issuing_store_id = as_str(body, "issuing_store_id", required=True)
    customer = get_or_404(db.customers, customer_id)
    store = get_or_404(db.stores, issuing_store_id)

    # Jurisdiction: issuing store's state_code must be a valid 2-letter code (§3.4).
    if not _valid_state_code(store["state_code"]):
        raise errors.ApiError(errors.ERR_INVALID_JURISDICTION, 422,
                              "Issuing store has an invalid jurisdiction")

    residency = "RESIDENT" if customer["home_state_code"] == store["state_code"] else "NONRESIDENT"
    fee = pricing.license_fee(residency)

    valid_from_dt = clock.now()
    valid_until_dt = add_days(valid_from_dt, 365)

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "_seq": db.next_seq(),
        "customer_id": customer_id,
        "issuing_store_id": issuing_store_id,
        "residency": residency,
        "valid_from": format_iso8601_ms(valid_from_dt),
        "valid_until": format_iso8601_ms(valid_until_dt),
        "fee_cents": fee,
        "status": "ACTIVE",
    }
    db.fishing_licenses[rid] = rec
    return success(serializers.fishing_license(rec), 201)


@bp.route("/fishing-licenses/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def get_fishing_license(rid):
    rec = get_or_404(db.fishing_licenses, rid)
    return success(serializers.fishing_license(rec), 200)


@bp.route("/fishing-licenses", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "Customer")
def list_fishing_licenses():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    issuing_store_id = request.args.get("issuing_store_id")
    items = list(db.fishing_licenses.values())
    if customer_id is not None:
        items = [l for l in items if l["customer_id"] == customer_id]
    if issuing_store_id is not None:
        items = [l for l in items if l["issuing_store_id"] == issuing_store_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.fishing_license(l) for l in page], limit, offset, total)
