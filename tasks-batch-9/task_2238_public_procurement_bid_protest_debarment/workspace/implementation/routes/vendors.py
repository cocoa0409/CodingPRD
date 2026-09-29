"""Vendor file, protest purse and the debarred-vendor list (PRD §3.1, §3.9)."""

import re

from flask import Blueprint, g

import serializers
import services
import store
import validation as v
from errors import ApiError

bp = Blueprint("vendors", __name__)

TAX_ID_RE = re.compile(r"^\d{9}$")
ELIGIBILITY = ("ELIGIBLE", "SUSPENDED", "DEBARRED")
QUESTION_STATUS = ("PENDING", "ANSWERED", "REJECTED_LATE")


@bp.post("/procurement/vendors")
@v.endpoint(["SystemAdmin"])
def register_vendor():
    data = v.body()
    legal_name = v.req_str(data, "legal_name", min_len=1, max_len=200)
    tax_id = v.req_str(data, "tax_id")
    if not TAX_ID_RE.match(tax_id):
        raise ApiError("ERR_INVALID_REQUEST", "field 'tax_id' must be exactly nine digits")
    contact_email = v.req_str(data, "contact_email")

    for existing in store.values("vendors"):
        if existing["tax_id"] == tax_id:
            raise ApiError("ERR_DUPLICATE_TAX_ID")

    vendor = store.insert("vendors", store.row("vendors", {
        "legal_name": legal_name,
        "tax_id": tax_id,
        "contact_email": contact_email,
        "eligibility_status": "ELIGIBLE",
        "protest_fee_balance_cents": 0,
        "debarment_strike_count": 0,
        "active_debarment_id": None,
        "reinstatement_earliest_petition_utc": None,
        "suspension_reason_code": None,
    }))
    return ("obj", vendor, serializers.vendor, 201)


@bp.get("/procurement/vendors/<vendor_id>")
@v.endpoint(v.ALL_ROLES)
def read_vendor(vendor_id):
    return ("obj", services.must("vendors", vendor_id), serializers.vendor, 200)


@bp.get("/procurement/vendors")
@v.endpoint(v.ALL_ROLES)
def list_vendors():
    limit, offset = v.pagination()
    filters = {
        "eligibility_status": v.query("eligibility_status"),
        "tax_id": v.query("tax_id"),
        "active_debarment_id": v.query("active_debarment_id"),
    }
    rows = [r for r in store.ordered(store.values("vendors")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.vendor, limit, offset, total)


@bp.post("/procurement/vendors/<vendor_id>/fee-deposits")
@v.endpoint(["SystemAdmin", "Vendor"])
def deposit_fee(vendor_id):
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents", minimum=1)
    vendor = services.must("vendors", vendor_id)
    if g.user_role == "Vendor" and g.user_id != vendor["id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")
    vendor["protest_fee_balance_cents"] += amount_cents
    v.touch(vendor)
    return ("obj", vendor, serializers.vendor, 200)


@bp.get("/procurement/vendors/<vendor_id>/questions")
@v.endpoint(v.ALL_ROLES)
def list_vendor_questions(vendor_id):
    limit, offset = v.pagination()
    vendor = services.must("vendors", vendor_id)
    status = v.query("status")
    rows = [
        q for q in store.ordered(store.values("questions"))
        if q["vendor_id"] == vendor["id"] and (status is None or q["status"] == status)
    ]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.question, limit, offset, total)


@bp.get("/procurement/debarred-vendors")
@v.endpoint(v.ALL_ROLES)
def debarred_vendors():
    """Snapshot ordering of PRD §3.9."""
    limit, offset = v.pagination()
    include_suspended = v.query_bool("include_suspended", False)
    as_of = v.query_dt("as_of_utc") or store.now()
    statuses = ("DEBARRED", "SUSPENDED") if include_suspended else ("DEBARRED",)

    rows = []
    for vendor in store.ordered(store.values("vendors")):
        if vendor["eligibility_status"] not in statuses:
            continue
        if vendor["active_debarment_id"] is None:
            continue
        proceeding = store.get("proceedings", vendor["active_debarment_id"])
        if proceeding is None:
            continue
        end = proceeding["debarment_end_utc"]
        if end is not None and not end > as_of:
            continue
        rows.append((vendor, end))

    rows.sort(key=lambda pair: (pair[0]["created_at"], pair[0]["_seq"]))
    rows.sort(key=lambda pair: (1, -pair[1].timestamp()) if pair[1] is not None else (0, 0))
    ordered = [pair[0] for pair in rows]
    page, total = v.paginate(ordered, limit, offset)
    return ("list", page, serializers.vendor, limit, offset, total)
