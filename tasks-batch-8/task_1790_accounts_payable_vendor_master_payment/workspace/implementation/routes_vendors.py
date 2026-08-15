"""Vendor master: create/list/get/patch, lifecycle transitions, merge."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DUPLICATE_TAX_ID,
    ERR_DUPLICATE_VENDOR_HARD_BLOCK,
    ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED,
    ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE,
    ERR_REQUIRED_DOCUMENT_MISSING,
    ERR_VENDOR_HAS_OPEN_CASE,
    ERR_VENDOR_HAS_OPEN_INVOICES,
    ERR_VENDOR_NOT_MERGEABLE,
    raise_err,
)
from middleware import (
    ALL_ROLES,
    require_auth,
    require_role,
    get_body,
    req_str,
    opt_str,
    opt_int,
    opt_number,
    opt_bool,
    req_int,
    get_or_404,
    paginate,
)
from response import ok, ok_list

bp = Blueprint("vendors", __name__)

VENDOR_EDITABLE_FIELDS = [
    "legal_name",
    "dba_name",
    "remit_email",
    "phone",
    "address_line1",
    "city",
    "country",
    "payment_terms_days",
    "early_pay_discount_pct",
    "discount_window_days",
]

VENDOR_EDITABLE_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "DORMANT")
MERGEABLE_SOURCE_STATUSES = ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "DORMANT")


def _check_occ(body, vendor):
    expected = req_int(body, "expected_vendor_version")
    if expected != vendor["version"]:
        raise_err(
            ERR_STALE_VERSION,
            "expected_vendor_version %s does not match the vendor's current version %s."
            % (expected, vendor["version"]),
        )


@bp.route("/vendors", methods=["POST"])
def create_vendor():
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist", "VendorManager"])
    body = get_body()
    legal_name = req_str(body, "legal_name")
    tax_id = req_str(body, "tax_id")
    remit_email = req_str(body, "remit_email")
    phone = req_str(body, "phone")
    address_line1 = req_str(body, "address_line1")
    city = req_str(body, "city")
    country = req_str(body, "country")
    dba_name = opt_str(body, "dba_name")
    payment_terms_days = opt_int(body, "payment_terms_days", 30)
    early_pay_discount_pct = opt_number(body, "early_pay_discount_pct", 0)
    discount_window_days = opt_int(body, "discount_window_days", 0)
    duplicate_acknowledged = opt_bool(body, "duplicate_acknowledged", False)

    # duplicate_vendor_detection: strict tax_id leg, then relaxed trigram band
    if svc.tax_id_collision(tax_id):
        raise_err(ERR_DUPLICATE_TAX_ID, "tax_id already exists on a non-terminal vendor.")
    score = svc.duplicate_score(legal_name)
    if score >= svc.DUP_HARD_BLOCK_THRESHOLD:
        raise_err(ERR_DUPLICATE_VENDOR_HARD_BLOCK,
                  "A vendor with a highly similar name already exists (score %s)." % score)
    duplicate_review_required = False
    if score >= svc.DUP_REVIEW_THRESHOLD:
        if duplicate_acknowledged is not True:
            raise_err(ERR_DUPLICATE_VENDOR_REVIEW_REQUIRED,
                      "A vendor with a similar name already exists (score %s); "
                      "resubmit with duplicate_acknowledged=true to proceed." % score)
        duplicate_review_required = True

    vendor = db.stamp_new({
        "id": db.new_id(),
        "legal_name": legal_name,
        "dba_name": dba_name,
        "tax_id": tax_id,
        "remit_email": remit_email,
        "phone": phone,
        "address_line1": address_line1,
        "city": city,
        "country": country,
        "payment_terms_days": payment_terms_days,
        "early_pay_discount_pct": early_pay_discount_pct,
        "discount_window_days": discount_window_days,
        "status": "DRAFT",
        "created_by_user_id": ctx.user_id,
        "approved_by_user_id": None,
        "first_activated_at": None,
        "last_payment_cleared_at": None,
        "dormant_since_at": None,
        "duplicate_review_required": duplicate_review_required,
        "fraud_hold_reason": None,
        "primary_bank_account_id": None,
        "merged_into_vendor_id": None,
    })
    db.vendors[vendor["id"]] = vendor
    svc.audit("Vendor", vendor["id"], "CREATE", ctx)
    return ok(vendor, status=201)


@bp.route("/vendors", methods=["GET"])
def list_vendors():
    require_auth()
    items = list(db.vendors.values())
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    name_contains = request.args.get("name_contains")
    if name_contains is not None:
        needle = name_contains.lower()
        items = [v for v in items
                 if needle in v["legal_name"].lower()
                 or (v.get("dba_name") and needle in v["dba_name"].lower())]
    merged_into = request.args.get("merged_into_vendor_id")
    if merged_into is not None:
        items = [v for v in items if v.get("merged_into_vendor_id") == merged_into]
    primary = request.args.get("primary_bank_account_id")
    if primary is not None:
        items = [v for v in items if v.get("primary_bank_account_id") == primary]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/vendors/<vendor_id>", methods=["GET"])
def get_vendor(vendor_id):
    require_auth()
    return ok(get_or_404(db.vendors, vendor_id, "Vendor"))


@bp.route("/vendors/<vendor_id>", methods=["PATCH"])
def patch_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist"])
    body = get_body()
    if "tax_id" in body:
        raise_err(ERR_INVALID_REQUEST, "tax_id is immutable and may not appear in a vendor edit.")
    updates = {}
    for field in VENDOR_EDITABLE_FIELDS:
        if field not in body:
            continue
        value = body[field]
        if field in ("legal_name", "dba_name", "remit_email", "phone",
                     "address_line1", "city", "country"):
            if value is not None and not isinstance(value, str):
                raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a string." % field)
        elif field in ("payment_terms_days", "discount_window_days"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise_err(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % field)
        elif field == "early_pay_discount_pct":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise_err(ERR_INVALID_REQUEST, "Field '%s' must be a number." % field)
        updates[field] = value
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    _check_occ(body, vendor)
    if vendor["status"] not in VENDOR_EDITABLE_STATUSES:
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be edited." % vendor["status"])

    name_changed = ("legal_name" in updates and updates["legal_name"] != vendor["legal_name"])
    for field in VENDOR_EDITABLE_FIELDS:
        if field not in updates:
            continue
        old_value = vendor.get(field)
        new_value = updates[field]
        if old_value == new_value:
            continue
        vendor[field] = new_value
        svc.audit("Vendor", vendor["id"], "UPDATE", ctx,
                  field_name=field, old_value=old_value, new_value=new_value)
    db.touch(vendor)

    # legal_name change while ACTIVE|SUSPENDED re-runs setup screening
    if name_changed and vendor["status"] in ("ACTIVE", "SUSPENDED"):
        check = svc.screen_vendor(vendor, "VENDOR")
        if check["result"] == "REVIEW":
            if vendor["status"] == "ACTIVE":
                svc.suspend_vendor(vendor, ctx, screening_check=check,
                                   opened_reason="SETUP_SCREENING")
            else:
                svc.open_case_unless_exists(vendor, check, "SETUP_SCREENING")
        elif check["result"] == "HIT":
            svc.block_cascade(vendor, ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/submit", methods=["POST"])
def submit_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorSpecialist", "VendorManager"])
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be submitted." % vendor["status"])
    if not svc.vendor_has_live_w9(vendor["id"]):
        raise_err(ERR_REQUIRED_DOCUMENT_MISSING,
                  "Vendor has no live-valid W9 document at the current logical date.")
    vendor["status"] = "PENDING_APPROVAL"
    db.touch(vendor)
    svc.audit_status_change("Vendor", vendor["id"], "DRAFT", "PENDING_APPROVAL", ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/approve", methods=["POST"])
def approve_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] != "PENDING_APPROVAL":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be approved." % vendor["status"])
    if ctx.user_id == vendor["created_by_user_id"]:
        raise_err(ERR_SOD_VENDOR_CREATOR_CANNOT_APPROVE,
                  "The vendor's creator may not approve it (SoD-1).")
    check = svc.screen_vendor(vendor, "VENDOR")
    old = vendor["status"]
    if check["result"] == "CLEAR":
        vendor["status"] = "ACTIVE"
        vendor["approved_by_user_id"] = ctx.user_id
        if not vendor.get("first_activated_at"):
            vendor["first_activated_at"] = db.fmt_ts(db.now())
    elif check["result"] == "REVIEW":
        vendor["status"] = "SUSPENDED"
        svc.open_case_unless_exists(vendor, check, "SETUP_SCREENING")
    else:  # HIT
        vendor["status"] = "BLOCKED"
    db.touch(vendor)
    svc.audit_status_change("Vendor", vendor["id"], old, vendor["status"], ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/reject", methods=["POST"])
def reject_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    body = get_body()
    req_str(body, "reason")
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] not in ("DRAFT", "PENDING_APPROVAL"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be rejected." % vendor["status"])
    old = vendor["status"]
    vendor["status"] = "REJECTED"
    db.touch(vendor)
    svc.audit_status_change("Vendor", vendor["id"], old, "REJECTED", ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/suspend", methods=["POST"])
def suspend_vendor_route(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager", "ComplianceOfficer"])
    body = get_body()
    req_str(body, "reason")
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be suspended." % vendor["status"])
    svc.suspend_vendor(vendor, ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/reinstate", methods=["POST"])
def reinstate_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be reinstated." % vendor["status"])
    if svc.open_case_for_vendor(vendor["id"]) is not None:
        raise_err(ERR_VENDOR_HAS_OPEN_CASE,
                  "An OPEN sanctions review case references this vendor.")
    vendor["status"] = "ACTIVE"
    svc.resume_cascade(vendor["id"])
    db.touch(vendor)
    svc.audit_status_change("Vendor", vendor["id"], "SUSPENDED", "ACTIVE", ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/reactivate", methods=["POST"])
def reactivate_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] != "DORMANT":
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be reactivated." % vendor["status"])
    check = svc.screen_vendor(vendor, "VENDOR")
    old = vendor["status"]
    if check["result"] == "CLEAR":
        vendor["status"] = "ACTIVE"
        vendor["dormant_since_at"] = None
        db.touch(vendor)
        svc.audit_status_change("Vendor", vendor["id"], old, "ACTIVE", ctx)
    elif check["result"] == "REVIEW":
        vendor["status"] = "SUSPENDED"
        db.touch(vendor)
        svc.open_case_unless_exists(vendor, check, "SETUP_SCREENING")
        svc.audit_status_change("Vendor", vendor["id"], old, "SUSPENDED", ctx)
    else:  # HIT
        vendor["status"] = "BLOCKED"
        db.touch(vendor)
        svc.audit_status_change("Vendor", vendor["id"], old, "BLOCKED", ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/deactivate", methods=["POST"])
def deactivate_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    vendor = get_or_404(db.vendors, vendor_id, "Vendor")
    if vendor["status"] not in ("ACTIVE", "SUSPENDED", "DORMANT"):
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Vendor in status %s cannot be deactivated." % vendor["status"])
    if svc.vendor_has_open_invoices(vendor["id"]):
        raise_err(ERR_VENDOR_HAS_OPEN_INVOICES,
                  "Vendor has invoices in an open status.")
    if svc.vendor_has_inflight_payments(vendor["id"]):
        raise_err(ERR_VENDOR_HAS_OPEN_INVOICES,
                  "Vendor has payments still in flight.")
    old = vendor["status"]
    vendor["status"] = "DEACTIVATED"
    db.touch(vendor)
    svc.audit_status_change("Vendor", vendor["id"], old, "DEACTIVATED", ctx)
    return ok(vendor)


@bp.route("/vendors/<vendor_id>/merge", methods=["POST"])
def merge_vendor(vendor_id):
    ctx = require_auth()
    require_role(ctx, ["VendorManager"])
    body = get_body()
    duplicate_vendor_id = req_str(body, "duplicate_vendor_id")
    req_int(body, "expected_vendor_version")
    survivor = get_or_404(db.vendors, vendor_id, "Vendor")
    source = get_or_404(db.vendors, duplicate_vendor_id, "Vendor")
    _check_occ(body, survivor)

    # merge gate (ERR_VENDOR_NOT_MERGEABLE)
    def not_mergeable(msg):
        raise_err(ERR_VENDOR_NOT_MERGEABLE, msg)

    if source["id"] == survivor["id"]:
        not_mergeable("Source and survivor must be different vendors.")
    if source["status"] not in MERGEABLE_SOURCE_STATUSES:
        not_mergeable("Source vendor in status %s cannot be merged." % source["status"])
    if survivor["status"] != "ACTIVE":
        not_mergeable("Survivor vendor must be ACTIVE.")
    if svc.vendor_has_inflight_payments(source["id"]) or svc.vendor_has_inflight_payments(survivor["id"]):
        not_mergeable("Neither vendor may have payments in PENDING or RELEASED.")
    if svc.open_case_for_vendor(source["id"]) is not None or svc.open_case_for_vendor(survivor["id"]) is not None:
        not_mergeable("Neither vendor may have an OPEN sanctions review case.")
    survivor_numbers = {
        inv["invoice_number"]
        for inv in db.invoices.values()
        if inv["vendor_id"] == survivor["id"] and inv["status"] != "CANCELLED"
    }
    repoint_candidates = [
        inv for inv in db.invoices.values()
        if inv["vendor_id"] == source["id"] and inv["status"] not in ("PAID", "CANCELLED")
    ]
    for inv in repoint_candidates:
        if inv["invoice_number"] in survivor_numbers:
            not_mergeable("Re-pointing would collide invoice_number '%s' on the survivor."
                          % inv["invoice_number"])

    # side effects
    for inv in repoint_candidates:
        inv["vendor_id"] = survivor["id"]
        db.touch(inv)
    disabled_count = 0
    for acct in db.bank_accounts.values():
        if acct["vendor_id"] == source["id"] and acct["status"] in ("PENDING_VERIFICATION", "VERIFIED"):
            acct["status"] = "DISABLED"
            db.touch(acct)
            disabled_count += 1
            if source.get("primary_bank_account_id") == acct["id"]:
                source["primary_bank_account_id"] = None
    source["status"] = "MERGED"
    source["merged_into_vendor_id"] = survivor["id"]
    db.touch(source)
    db.touch(survivor)

    record = {
        "id": db.new_id(),
        "survivor_vendor_id": survivor["id"],
        "merged_vendor_id": source["id"],
        "match_score": float(svc.name_similarity(source["legal_name"], survivor["legal_name"])),
        "invoices_repointed_count": len(repoint_candidates),
        "bank_accounts_disabled_count": disabled_count,
        "merged_by_user_id": ctx.user_id,
        "created_at": db.fmt_ts(db.now()),
    }
    db.vendor_merge_records[record["id"]] = record
    svc.audit("Vendor", survivor["id"], "MERGE", ctx)
    svc.audit("Vendor", source["id"], "MERGE", ctx)
    return ok(record)


@bp.route("/vendor-merge-records", methods=["GET"])
def list_merge_records():
    require_auth()
    items = list(db.vendor_merge_records.values())
    survivor_id = request.args.get("survivor_vendor_id")
    if survivor_id is not None:
        items = [r for r in items if r["survivor_vendor_id"] == survivor_id]
    merged_id = request.args.get("merged_vendor_id")
    if merged_id is not None:
        items = [r for r in items if r["merged_vendor_id"] == merged_id]
    page, total, limit, offset = paginate(items)
    return ok_list(page, total, limit, offset)


@bp.route("/vendor-merge-records/<record_id>", methods=["GET"])
def get_merge_record(record_id):
    require_auth()
    return ok(get_or_404(db.vendor_merge_records, record_id, "VendorMergeRecord"))
