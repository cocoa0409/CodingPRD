from flask import Blueprint, request
from datetime import timedelta
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_enum, require_datetime,
                             optional_int, optional_number, require_number,
                             parse_pagination, occ_check)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK, add_days, parse_iso
from services.serialize import serialize
from services.core import generate_installments, recompute_landlord_totals

bp = Blueprint("leases", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
PAYMENT_PATTERNS = {"MAR_NOV_50_50", "QUARTERLY", "FULL_MAR", "NONE"}
ESCALATION_TYPES = {"NONE", "FIXED_PCT"}
PRACTICE_TYPES = {"COVER_CROP", "NO_TILL", "BUFFER_STRIP", "NUTRIENT_PLAN"}
ACTIVE_LEASE_STATES = ("ACTIVE", "TERMINATION_PENDING")


def _validate_practices(raw):
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ApiError("ERR_VALIDATION", 400, "conservation_practices must be an array")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", 400, "practice entry must be an object")
        pt = entry.get("practice_type")
        if pt not in PRACTICE_TYPES:
            raise ApiError("ERR_VALIDATION", 400, f"practice_type must be one of {sorted(PRACTICE_TYPES)}")
        dd = entry.get("due_date")
        if not isinstance(dd, str):
            raise ApiError("ERR_VALIDATION", 400, "practice due_date must be an ISO8601 string")
        try:
            dd_parsed = parse_iso(dd)
        except Exception:
            raise ApiError("ERR_VALIDATION", 400, "practice due_date is not valid ISO8601")
        out.append({"practice_type": pt, "due_date": dd_parsed})
    return out


def _validate_escalation(body, partial=False):
    """escalation_pct required iff escalation_type=FIXED_PCT (when either is being set)."""
    et = body.get("escalation_type")
    ep = body.get("escalation_pct")
    if partial:
        # PATCH: validate the resulting combination after patch is applied
        return
    if et == "FIXED_PCT":
        if ep is None:
            raise ApiError("ERR_VALIDATION", 400,
                           "escalation_pct is required when escalation_type=FIXED_PCT")
        require_number(body, "escalation_pct", minimum=0, maximum=0.25)
    else:  # NONE
        if ep is not None:
            raise ApiError("ERR_VALIDATION", 400,
                           "escalation_pct must be absent when escalation_type=NONE")


def _field_overlap(field_id, start, end, exclude_lease_id=None):
    """Half-open [start, end) overlap with any ACTIVE/TERMINATION_PENDING lease on field."""
    for lease in db.leases.values():
        if lease["field_id"] != field_id:
            continue
        if exclude_lease_id is not None and lease["id"] == exclude_lease_id:
            continue
        if lease["status"] not in ACTIVE_LEASE_STATES:
            continue
        # half-open overlap: start < other.end AND other.start < end
        if start < lease["term_end_date"] and lease["term_start_date"] < end:
            return True
    return False


@bp.route("/leases", methods=["POST"])
def create_lease():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    bid_id = require_string(body, "bid_id")
    term_start = require_datetime(body, "term_start_date")
    term_end = require_datetime(body, "term_end_date")
    if term_end <= term_start:
        raise ApiError("ERR_VALIDATION", 400, "term_end_date must be later than term_start_date")
    payment_pattern = require_enum(body, "payment_pattern", PAYMENT_PATTERNS)
    escalation_type = require_enum(body, "escalation_type", ESCALATION_TYPES) \
        if "escalation_type" in body else "NONE"
    _validate_escalation(body, partial=False)
    escalation_pct = body.get("escalation_pct")
    notice_lead_days = optional_int(body, "notice_lead_days", minimum=1, default=180)
    practices = _validate_practices(body.get("conservation_practices"))

    # Existence
    bid = db.bids.get(bid_id)
    if bid is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Bid {bid_id} not found")

    # State: bid must be ACCEPTED
    if bid["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, f"Bid in state {bid['status']} cannot originate a lease")

    # Window: clock <= accepted_at + 30 days
    if bid.get("accepted_at") is None or CLOCK.get() > add_days(bid["accepted_at"], 30):
        raise ApiError("ERR_BID_ACCEPTANCE_EXPIRED", 409,
                       "Bid acceptance window (30 days) has expired")

    # Referential: bid not already linked to a lease
    for l in db.leases.values():
        if l["bid_id"] == bid_id:
            raise ApiError("ERR_BID_ALREADY_LEASED", 409,
                           "Bid is already linked to an existing lease")

    # Chain of ownership
    offering = db.offerings.get(bid["offering_id"])
    field = db.fields.get(offering["field_id"]) if offering else None
    if offering is None or field is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Bid's offering/field chain is broken")
    landlord_id = field["landlord_id"]

    # Field overlap at creation
    if _field_overlap(field["id"], term_start, term_end):
        raise ApiError("ERR_FIELD_LEASE_OVERLAP", 409,
                       "Overlapping ACTIVE/TERMINATION_PENDING lease on this field")

    # Copy commercial identity from bid
    lease_type = bid["lease_type"]
    if lease_type == "CASH":
        base_rent = bid["cash_bid_per_acre_cents"]
    elif lease_type == "FLEX":
        base_rent = bid["flex_base_per_acre_cents"]
    else:  # SHARE
        base_rent = 0

    rec = new_common()
    rec.update({
        "bid_id": bid_id,
        "field_id": field["id"],
        "landlord_id": landlord_id,
        "tenant_id": bid["tenant_id"],
        "lease_type": lease_type,
        "term_start_date": term_start,
        "term_end_date": term_end,
        "term_index": 1,
        "base_rent_cents_per_acre": base_rent,
        "revenue_trigger_cents": bid.get("revenue_trigger_cents") if lease_type == "FLEX" else None,
        "landlord_bonus_pct": bid.get("flex_bonus_pct") if lease_type == "FLEX" else None,
        "flex_cap_cents": bid.get("flex_cap_cents") if lease_type == "FLEX" else None,
        "landlord_share_pct": bid.get("landlord_share_pct") if lease_type == "SHARE" else None,
        "input_share_pct": bid.get("input_share_pct") if lease_type in ("FLEX", "SHARE") else None,
        "escalation_type": escalation_type,
        "escalation_pct": escalation_pct if escalation_type == "FIXED_PCT" else None,
        "payment_pattern": payment_pattern,
        "notice_lead_days": notice_lead_days,
        "conservation_practices": practices if practices is not None else [],
        "current_notice_deadline": add_days(term_end, -notice_lead_days),
        "landlord_credit_cents": 0,
        "status": "DRAFT",
    })
    db.leases[rec["id"]] = rec
    return success_object(serialize("lease", rec), status=201)


@bp.route("/leases/<leaseId>", methods=["GET"])
def get_lease(leaseId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.leases.get(leaseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {leaseId} not found")
    return success_object(serialize("lease", rec))


@bp.route("/leases", methods=["GET"])
def list_leases():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.leases.values(), key=lambda r: r["created_at"])
    for param, field in (("field_id", "field_id"), ("landlord_id", "landlord_id"),
                         ("tenant_id", "tenant_id"), ("bid_id", "bid_id"),
                         ("status", "status")):
        q = request.args.get(param)
        if q is not None:
            items = [r for r in items if r[field] == q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("lease", r) for r in page], limit, offset, total)


@bp.route("/leases/<leaseId>", methods=["PATCH"])
def amend_lease(leaseId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    rec = db.leases.get(leaseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {leaseId} not found")

    # conservation_practices editable only while DRAFT
    if "conservation_practices" in body and rec["status"] != "DRAFT":
        raise ApiError("ERR_VALIDATION", 400,
                       "conservation_practices editable only while DRAFT")

    # OCC
    occ_check(body, "expected_lease_version", rec["version"])

    # State: must be DRAFT or ACTIVE to amend (others terminal/pending)
    if rec["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Lease in state {rec['status']} cannot be amended")

    # Validate incoming fields
    if "escalation_type" in body:
        require_enum(body, "escalation_type", ESCALATION_TYPES)
    if "escalation_pct" in body and body["escalation_pct"] is not None:
        require_number(body, "escalation_pct", minimum=0, maximum=0.25)
    if "notice_lead_days" in body and body["notice_lead_days"] is not None:
        optional_int(body, "notice_lead_days", minimum=1)
    if "base_rent_cents_per_acre" in body and body["base_rent_cents_per_acre"] is not None:
        v = body["base_rent_cents_per_acre"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ApiError("ERR_VALIDATION", 400, "base_rent_cents_per_acre must be a non-negative integer")

    # Combined escalation invariant after patch
    new_et = body.get("escalation_type", rec["escalation_type"])
    new_ep = body.get("escalation_pct", rec.get("escalation_pct"))
    if new_et == "FIXED_PCT":
        if new_ep is None:
            raise ApiError("ERR_VALIDATION", 400,
                           "escalation_pct is required when escalation_type=FIXED_PCT")
    else:
        if new_ep is not None:
            raise ApiError("ERR_VALIDATION", 400,
                           "escalation_pct must be absent when escalation_type=NONE")

    # Apply
    if "base_rent_cents_per_acre" in body and body["base_rent_cents_per_acre"] is not None:
        rec["base_rent_cents_per_acre"] = body["base_rent_cents_per_acre"]
    if "escalation_type" in body:
        rec["escalation_type"] = body["escalation_type"]
    if new_et == "FIXED_PCT":
        rec["escalation_pct"] = new_ep
    else:
        rec["escalation_pct"] = None
    if "notice_lead_days" in body and body["notice_lead_days"] is not None:
        rec["notice_lead_days"] = body["notice_lead_days"]
        rec["current_notice_deadline"] = add_days(rec["term_end_date"], -rec["notice_lead_days"])
    if "conservation_practices" in body:
        rec["conservation_practices"] = _validate_practices(body["conservation_practices"]) or []

    touch(rec)
    return success_object(serialize("lease", rec))


@bp.route("/leases/<leaseId>/activate", methods=["POST"])
def activate_lease(leaseId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.leases.get(leaseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {leaseId} not found")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Lease in state {rec['status']} cannot be activated")

    # Precondition order per PRD 3.4: tenant approved -> noncompliant -> overlap
    tenant = db.tenants.get(rec["tenant_id"])
    if tenant is None or tenant["status"] != "APPROVED":
        raise ApiError("ERR_TENANT_NOT_APPROVED", 409, "Tenant is not APPROVED")

    for cr in db.compliance_records.values():
        cr_lease = db.leases.get(cr["lease_id"])
        if cr_lease is not None and cr_lease["tenant_id"] == rec["tenant_id"] \
                and cr["status"] == "NON_COMPLIANT":
            raise ApiError("ERR_TENANT_NONCOMPLIANT", 409,
                           "Tenant has an unresolved NON_COMPLIANT compliance record")

    if _field_overlap(rec["field_id"], rec["term_start_date"], rec["term_end_date"],
                      exclude_lease_id=rec["id"]):
        raise ApiError("ERR_FIELD_LEASE_OVERLAP", 409,
                       "Overlapping ACTIVE/TERMINATION_PENDING lease on this field")

    # Side effects
    rec["status"] = "ACTIVE"
    touch(rec)
    field = db.fields.get(rec["field_id"])
    if field is not None:
        field["status"] = "LEASED"
        touch(field)
    generate_installments(rec)
    # Compliance records per practice
    from datetime import timedelta as _td
    for p in rec.get("conservation_practices") or []:
        cr = new_common()
        cr.update({
            "lease_id": rec["id"],
            "practice_type": p["practice_type"],
            "due_date": p["due_date"],
            "cure_deadline": p["due_date"] + _td(days=30),
            "evidence_note": None,
            "noncompliant_at": None,
            "verified_by": None,
            "status": "PENDING",
        })
        db.compliance_records[cr["id"]] = cr
    recompute_landlord_totals(rec["landlord_id"])
    return success_object(serialize("lease", rec))


@bp.route("/leases/<leaseId>/cancel", methods=["POST"])
def cancel_lease(leaseId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.leases.get(leaseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {leaseId} not found")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Lease in state {rec['status']} cannot be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize("lease", rec))
