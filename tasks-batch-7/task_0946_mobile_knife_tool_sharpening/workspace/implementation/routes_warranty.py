"""Quality, warranty adjudication and the six-link approval cascade."""

import datetime

from flask import Blueprint

import calcs
import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import CLAIM_STATUSES, WARRANTY_RESUBMIT_CAP, WARRANTY_WINDOW_DAYS
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("warranty", __name__)

CLAIM_SPEC = ladder.Spec(
    required=[("request_item_id", "string"), ("reason", "string")]
)

DENY_SPEC = ladder.Spec(required=[("abuse_finding", "boolean")])


def _warranty_window_open(item):
    if item["delivered_at"] is None:
        return False
    deadline = item["delivered_at"] + datetime.timedelta(days=WARRANTY_WINDOW_DAYS)
    return clockmod.now() <= deadline


@bp.route("/sharpening/warranty-claims", methods=["POST"])
def create_claim():
    ctx = ladder.begin("AccountOwner")
    CLAIM_SPEC.validate(ctx.body)
    # Rung 8 carve-out: the acting AccountOwner IS the scope, so the
    # does-this-item-belong-to-me test is rung 28 below, not this rung.
    services.account_active(db.accounts.get(ctx.user_id))
    item = ladder.must_exist(
        db.request_items, ctx.body["request_item_id"], "RequestItem"
    )
    parent = db.service_requests.get(item["service_request_id"])
    # Rung 28.
    if parent is None or parent["account_id"] != ctx.user_id:
        raise ApiError("ERR_CLAIM_ITEM_ACCOUNT_MISMATCH")
    # Rung 38.
    if not _warranty_window_open(item):
        raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED")

    row = stamp_new(
        {
            "request_item_id": item["id"],
            "account_id": parent["account_id"],
            "rework_service_request_id": None,
            "decided_by_technician_id": None,
            "reason": ctx.body["reason"],
            "abuse_finding": False,
            "resubmit_count": 0,
            "credit_basis_cents": services.credit_basis_for(
                item["id"], parent["account_id"]
            ),
            "status": "SUBMITTED",
        }
    )
    db.warranty_claims[row["id"]] = row
    return envelope.created(ser.warranty_claim(row))


@bp.route("/sharpening/warranty-claims/<id>", methods=["GET"])
def get_claim(id):
    ctx = ladder.begin("AccountOwner", "Technician", "PlatformAdmin", "BillingClerk")
    row = ladder.must_exist(db.warranty_claims, id, "WarrantyClaim")
    services.own_account(ctx, row["account_id"])
    services.acting_technician(ctx)
    return envelope.ok(ser.warranty_claim(row))


@bp.route("/sharpening/warranty-claims", methods=["GET"])
def list_claims():
    ctx = ladder.begin("AccountOwner", "Technician", "PlatformAdmin", "BillingClerk")
    ladder.check_query_enums(ctx.query, {"status": CLAIM_STATUSES})
    limit, offset = ladder.pagination(ctx.query)
    services.acting_technician(ctx)
    rows = list(db.warranty_claims.values())
    for field in (
        "request_item_id",
        "account_id",
        "rework_service_request_id",
        "decided_by_technician_id",
        "status",
    ):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.warranty_claim(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/warranty-claims/{id}/approve -- the six-link cascade
# ---------------------------------------------------------------------------
@bp.route("/sharpening/warranty-claims/<id>/approve", methods=["POST"])
def approve_claim(id):
    ctx = ladder.begin("Technician")
    claim = ladder.must_exist(db.warranty_claims, id, "WarrantyClaim")
    services.acting_technician(ctx)
    account = db.accounts.get(claim["account_id"])
    services.account_active(account)
    if claim["status"] == "APPROVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "The claim is not SUBMITTED.")
    item = db.request_items.get(claim["request_item_id"])
    if item is None or item["service_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", "The claimed item is not DELIVERED.")
    # Rung 23 -- segregation of duties.
    if item["assessed_by_technician_id"] == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    now = clockmod.now()
    # Link one.
    claim["status"] = "APPROVED"
    claim["decided_by_technician_id"] = ctx.user_id
    claim["credit_basis_cents"] = services.credit_basis_for(
        item["id"], claim["account_id"]
    )
    # Link two.
    item["service_status"] = "REWORK_QUEUED"
    item["custody_location"] = "CUSTOMER"
    touch(item)
    # Link three -- the rework order the item is now queued for.
    original_request = db.service_requests.get(item["service_request_id"])
    rework = stamp_new(
        {
            "account_id": claim["account_id"],
            "subscription_id": None,
            "origin_warranty_claim_id": claim["id"],
            "channel": "REWORK",
            "priority": "STANDARD",
            "requested_date": clockmod.today(),
            "locker_site_code": None,
            "locker_high_value_authorized": False,
            "status": "SUBMITTED",
            "billing_status": "UNBILLED",
            "quoted_total_cents": 0,
            "completed_at": None,
            "_invoice_id": None,
        }
    )
    db.service_requests[rework["id"]] = rework
    spec = db.item_class_specs.get(item["item_class_spec_id"])
    declared = item["assessed_damage_tier"] or "ROUTINE_HONE"
    rework_item = stamp_new(
        {
            "service_request_id": rework["id"],
            "item_class_spec_id": item["item_class_spec_id"],
            "bench_day_id": None,
            "rework_of_request_item_id": item["id"],
            "assessed_by_technician_id": ctx.user_id,
            "item_class": item["item_class"],
            "declared_damage_tier": declared,
            "assessed_damage_tier": "ROUTINE_HONE",
            "quoted_gross_cents": calcs.item_gross_cents(
                spec["list_price_cents"], declared
            )
            if spec
            else 0,
            "final_gross_cents": calcs.item_gross_cents(
                spec["list_price_cents"], "ROUTINE_HONE"
            )
            if spec
            else 0,
            "charged_service_cents": 0,
            "part_fee_cents": 0,
            "service_minutes_declared": calcs.item_minutes(
                spec["base_service_minutes"], declared
            )
            if spec
            else 0,
            "service_minutes_assessed": calcs.item_minutes(
                spec["base_service_minutes"], "ROUTINE_HONE"
            )
            if spec
            else 0,
            "requires_reauthorization": False,
            "authorization_status": "NOT_REQUIRED",
            "service_status": "ASSESSED",
            "custody_location": "CUSTOMER",
            "allowance_applied": False,
            "delivered_at": None,
        }
    )
    db.request_items[rework_item["id"]] = rework_item
    rework["quoted_total_cents"] = rework_item["quoted_gross_cents"]
    claim["rework_service_request_id"] = rework["id"]
    # Link four -- the workmanship credit, written even at zero.
    if account is not None:
        invoice = services.draft_invoice_for(account)
        services.append_line(
            invoice,
            "WARRANTY_CREDIT",
            "Warranty workmanship credit",
            -claim["credit_basis_cents"],
            source_warranty_claim_id=claim["id"],
        )
        # Link five.
        services.recompute_invoice(invoice)
        touch(invoice)
    # Link six.
    if original_request is not None and original_request["billing_status"] in (
        "INVOICED",
        "SETTLED",
    ):
        original_request["billing_status"] = "CREDITED"
        touch(original_request)
    touch(claim)
    return envelope.ok(ser.warranty_claim(claim))


@bp.route("/sharpening/warranty-claims/<id>/deny", methods=["POST"])
def deny_claim(id):
    ctx = ladder.begin("Technician")
    claim = ladder.must_exist(db.warranty_claims, id, "WarrantyClaim")
    DENY_SPEC.validate(ctx.body)
    services.acting_technician(ctx)
    services.account_active(db.accounts.get(claim["account_id"]))
    if claim["status"] == "APPROVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "The claim is not SUBMITTED.")
    item = db.request_items.get(claim["request_item_id"])
    # Rung 23.
    if item is not None and item["assessed_by_technician_id"] == ctx.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    claim["decided_by_technician_id"] = ctx.user_id
    claim["abuse_finding"] = bool(ctx.body["abuse_finding"])
    claim["status"] = "DENIED"
    touch(claim)
    return envelope.ok(ser.warranty_claim(claim))


@bp.route("/sharpening/warranty-claims/<id>/resubmit", methods=["POST"])
def resubmit_claim(id):
    ctx = ladder.begin("AccountOwner")
    claim = ladder.must_exist(db.warranty_claims, id, "WarrantyClaim")
    services.own_account(ctx, claim["account_id"])
    services.account_active(db.accounts.get(claim["account_id"]))
    if claim["status"] == "APPROVED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", "The claim is not DENIED.")
    item = db.request_items.get(claim["request_item_id"])
    # Rung 38.
    if item is None or not _warranty_window_open(item):
        raise ApiError("ERR_WARRANTY_WINDOW_EXPIRED")
    # Rung 41.
    if claim["resubmit_count"] >= WARRANTY_RESUBMIT_CAP:
        raise ApiError("ERR_RESUBMIT_CAP_REACHED")

    claim["resubmit_count"] += 1
    claim["decided_by_technician_id"] = None
    claim["abuse_finding"] = False
    claim["status"] = "SUBMITTED"
    touch(claim)
    return envelope.ok(ser.warranty_claim(claim))
