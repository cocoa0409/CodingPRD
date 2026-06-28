"""Offering + Form C + lifecycle + escrow/cap-table read endpoints
(PRD 3.2, 3.3, 3.5, 3.6, 3.7)."""
from flask import Blueprint, request

from clock import clock, parse_iso
from calculations import ISSUER_CAP_CENTS
from db import db, new_id, now_iso
from derive import (
    touch,
    recompute_issuer_trailing,
    get_escrow_for_offering,
)
from errors import err
from middleware import get_auth, get_auth_optional, require_role
from offering_service import close_batch, sweep_batch, refund_all_unswept
from pagination import paginate
from response import success
from serializers import offering_out, escrow_out, cap_table_entry_out
from validation import (
    require_body,
    require_str,
    require_enum,
    require_int,
    opt_int,
)

bp = Blueprint("offerings", __name__)

REGULATIONS = {"REG_CF", "REG_A_TIER_1", "REG_A_TIER_2"}
SECURITY_TYPES = {"EQUITY", "SAFE"}


def _get_offering_or_404(id):
    rec = db.offerings.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Offering not found")
    return rec


def _check_owner(offering, uid):
    if offering["issuer_id"] != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller does not own this offering")


# --------------------------------------------------------------------------
# Create / read
# --------------------------------------------------------------------------
@bp.post("/offerings")
def create_offering():
    uid, role = get_auth()
    require_role(role, {"Issuer"})

    body = require_body()
    issuer_id = require_str(body, "issuer_id")
    regulation = require_enum(body, "regulation", REGULATIONS)
    security_type = require_enum(body, "security_type", SECURITY_TYPES)
    min_target = require_int(body, "min_target_cents")
    max_target = require_int(body, "max_target_cents")
    deadline_at_raw = require_str(body, "deadline_at")
    try:
        parse_iso(deadline_at_raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "deadline_at must be an ISO 8601 instant")

    price = body.get("price_per_security_cents")
    if price is not None and (isinstance(price, bool) or not isinstance(price, int)):
        raise err("ERR_INVALID_REQUEST", "price_per_security_cents must be an integer")
    per_investor_cap = body.get("per_investor_cap_cents")
    if per_investor_cap is not None and (isinstance(per_investor_cap, bool) or not isinstance(per_investor_cap, int)):
        raise err("ERR_INVALID_REQUEST", "per_investor_cap_cents must be an integer")

    # Ownership: an Issuer creates offerings only for itself.
    issuer = db.issuers.get(issuer_id)
    if issuer is None:
        raise err("ERR_NOT_FOUND", "Issuer not found")
    if issuer_id != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller may only create offerings for itself")

    # Offering-terms validity (priority 15).
    if min_target <= 0 or max_target < min_target:
        raise err("ERR_INVALID_OFFERING_TERMS", "max_target_cents must be >= min_target_cents > 0")
    if security_type == "EQUITY":
        if price is None or price <= 0:
            raise err("ERR_INVALID_OFFERING_TERMS", "EQUITY offerings require price_per_security_cents > 0")
    else:  # SAFE
        if price is not None:
            raise err("ERR_INVALID_OFFERING_TERMS", "SAFE offerings must omit price_per_security_cents")

    # Issuer per-12mo proceeds cap, REG_CF only (priority 14).
    if regulation == "REG_CF":
        recompute_issuer_trailing(issuer)
        if issuer["total_raised_trailing_12mo_cents"] + max_target > ISSUER_CAP_CENTS:
            raise err("ERR_ISSUER_CAP_EXCEEDED", "Offering would exceed the $5,000,000 per-issuer 12-month cap")

    ts = now_iso()
    oid = new_id()
    rec = {
        "id": oid,
        "issuer_id": issuer_id,
        "regulation": regulation,
        "security_type": security_type,
        "price_per_security_cents": price if security_type == "EQUITY" else None,
        "min_target_cents": min_target,
        "max_target_cents": max_target,
        "per_investor_cap_cents": per_investor_cap,
        "deadline_at": deadline_at_raw,
        "live_at": None,
        "form_c_status": "DRAFT",
        "status": "DRAFT",
        "committed_amount_cents": 0,
        "swept_amount_cents": 0,
        "secondary_listing_enabled": False,
        "close_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.offerings[oid] = rec
    return success(offering_out(rec), status=201)


@bp.get("/offerings/<id>")
def get_offering(id):
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "Issuer", "Investor", "ComplianceOfficer"})
    rec = _get_offering_or_404(id)
    return success(offering_out(rec))


@bp.get("/offerings")
def list_offerings():
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "Issuer", "Investor", "ComplianceOfficer"})
    rows = list(db.offerings.values())
    for field in ("issuer_id", "regulation", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = paginate(rows)
    return success([offering_out(r) for r in page], pagination=meta)


# --------------------------------------------------------------------------
# Form C sub-dimension
# --------------------------------------------------------------------------
@bp.post("/offerings/<id>/form-c/submit")
def form_c_submit(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["form_c_status"] not in ("DRAFT", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Form C is not in DRAFT or REJECTED")
    # DRAFT submit additionally requires primary status DRAFT.
    if off["form_c_status"] == "DRAFT" and off["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Form C may be submitted from DRAFT only while the offering is DRAFT")
    off["form_c_status"] = "SUBMITTED"
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/form-c/qualify")
def form_c_qualify(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    off = _get_offering_or_404(id)
    # Segregation of duties: officer must not be the offering's issuer.
    if uid == off["issuer_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "The issuer cannot self-qualify its own Form C")
    if off["form_c_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Form C is not SUBMITTED")
    off["form_c_status"] = "QUALIFIED"
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/form-c/reject")
def form_c_reject(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    off = _get_offering_or_404(id)
    if uid == off["issuer_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "The issuer cannot self-reject its own Form C")
    if off["form_c_status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Form C is not SUBMITTED")
    off["form_c_status"] = "REJECTED"
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/form-c/amend")
def form_c_amend(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["form_c_status"] != "QUALIFIED" or off["status"] not in ("DRAFT", "LIVE"):
        raise err("ERR_INVALID_STATE", "Material amendment requires QUALIFIED Form C on a DRAFT/LIVE offering")
    off["form_c_status"] = "SUBMITTED"
    # Cascade: flag all COMMITTED investments for reconfirmation.
    for inv in db.investments.values():
        if inv["offering_id"] == off["id"] and inv["status"] == "COMMITTED":
            inv["reconfirm_required"] = True
            touch(inv)
    touch(off)
    return success(offering_out(off))


# --------------------------------------------------------------------------
# Primary lifecycle
# --------------------------------------------------------------------------
@bp.post("/offerings/<id>/go-live")
def go_live(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Offering is not in DRAFT")
    if off["form_c_status"] != "QUALIFIED":
        raise err("ERR_INVALID_STATE", "Form C must be QUALIFIED before going live")
    issuer = db.issuers.get(off["issuer_id"])
    if issuer is None or issuer["status"] != "VERIFIED":
        raise err("ERR_ISSUER_NOT_VERIFIED", "The parent issuer must be VERIFIED before go-live")
    now = clock.now()
    deadline = parse_iso(off["deadline_at"])
    if not (now < deadline):
        raise err("ERR_OFFERING_DEADLINE_PASSED", "The offering deadline has passed")

    # Campaign-window overlap guard for concurrent REG_CF raises (priority 9.1).
    if off["regulation"] == "REG_CF":
        for other in db.offerings.values():
            if other["id"] == off["id"]:
                continue
            if other["issuer_id"] != off["issuer_id"]:
                continue
            if other["regulation"] != "REG_CF":
                continue
            if other["status"] != "LIVE":
                continue
            if other.get("live_at") is None:
                continue
            other_live = parse_iso(other["live_at"])
            other_deadline = parse_iso(other["deadline_at"])
            # Closed intervals overlap iff a1 < b2 and b1 < a2 (strict).
            if other_live < deadline and now < other_deadline:
                raise err("ERR_CAMPAIGN_WINDOW_OVERLAP", "Overlapping concurrent REG_CF campaign window")

    # Provision escrow (held=0) if not already present.
    if get_escrow_for_offering(off["id"]) is None:
        ts = now_iso()
        eid = new_id()
        escrow = {
            "id": eid,
            "offering_id": off["id"],
            "held_amount_cents": 0,
            "disbursed_amount_cents": 0,
            "refunded_amount_cents": 0,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": db.next_seq(),
        }
        db.escrow_accounts[eid] = escrow
        db.escrow_by_offering[off["id"]] = eid

    off["status"] = "LIVE"
    off["live_at"] = clock.now_iso()
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/rolling-close")
def rolling_close(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["status"] != "LIVE" or off["form_c_status"] != "QUALIFIED":
        raise err("ERR_INVALID_STATE", "Rolling close requires a LIVE offering with QUALIFIED Form C")
    batch = close_batch(off)
    batch_gross = sum(i["amount_cents"] for i in batch)
    if off["swept_amount_cents"] + batch_gross < off["min_target_cents"]:
        raise err("ERR_MINIMUM_NOT_MET", "Cumulative swept total cannot reach the minimum target")
    sweep_batch(off, batch)
    issuer = db.issuers.get(off["issuer_id"])
    if issuer is not None:
        recompute_issuer_trailing(issuer)
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/close")
def final_close(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["status"] != "LIVE":
        raise err("ERR_INVALID_STATE", "Final close requires a LIVE offering")

    # Determine whether the minimum can be met after sweeping the eligible batch.
    batch = close_batch(off)
    batch_gross = sum(i["amount_cents"] for i in batch)
    can_fund = (off["swept_amount_cents"] + batch_gross) >= off["min_target_cents"]

    if can_fund:
        # FUNDED path requires QUALIFIED Form C (not pending a re-qualification).
        if off["form_c_status"] != "QUALIFIED":
            raise err("ERR_INVALID_STATE", "Final close requires QUALIFIED Form C")
        sweep_batch(off, batch)
        off["close_at"] = clock.now_iso()
        off["status"] = "FUNDED"
        issuer = db.issuers.get(off["issuer_id"])
        if issuer is not None:
            recompute_issuer_trailing(issuer)
        touch(off)
        return success(offering_out(off))

    # FAILED path: minimum not met -> auto-refund all un-swept commitments.
    # Failure is judged on swept + committed < min_target (PRD 3.5).
    if off["swept_amount_cents"] + off["committed_amount_cents"] >= off["min_target_cents"]:
        # Reconfirmation-blocked commitments keep the minimum from being met by
        # the batch even though committed >= min; this is still ERR_MINIMUM_NOT_MET.
        raise err("ERR_MINIMUM_NOT_MET", "Eligible close batch cannot reach the minimum target")
    refund_all_unswept(off, "REFUNDED")
    off["close_at"] = clock.now_iso()
    off["status"] = "FAILED"
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/cancel")
def cancel_offering(id):
    uid, role = get_auth()
    require_role(role, {"Issuer"})
    off = _get_offering_or_404(id)
    _check_owner(off, uid)
    if off["status"] not in ("DRAFT", "LIVE"):
        raise err("ERR_INVALID_STATE", "Only a DRAFT or LIVE offering may be cancelled")
    if off["status"] == "LIVE":
        refund_all_unswept(off, "CANCELLED")
    off["status"] = "CANCELLED"
    touch(off)
    return success(offering_out(off))


@bp.post("/offerings/<id>/enable-secondary")
def enable_secondary(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    off = _get_offering_or_404(id)
    if off["status"] != "FUNDED" or off["secondary_listing_enabled"]:
        raise err("ERR_INVALID_STATE", "Secondary listing requires a FUNDED offering not already enabled")
    if off["regulation"] != "REG_A_TIER_2":
        raise err("ERR_SECONDARY_NOT_PERMITTED", "Secondary listing is only permitted for REG_A_TIER_2")
    off["secondary_listing_enabled"] = True
    touch(off)
    return success(offering_out(off))


# --------------------------------------------------------------------------
# Escrow + cap-table reads scoped to an offering
# --------------------------------------------------------------------------
@bp.get("/offerings/<id>/escrow")
def get_offering_escrow(id):
    uid, role = get_auth()
    require_role(role, {"Issuer", "ComplianceOfficer"})
    off = _get_offering_or_404(id)
    escrow = get_escrow_for_offering(off["id"])
    rows = [escrow] if escrow is not None else []
    page, meta = paginate(rows)
    return success([escrow_out(r) for r in page], pagination=meta)


@bp.get("/offerings/<id>/cap-table")
def get_offering_cap_table(id):
    uid, role = get_auth()
    require_role(role, {"Issuer", "Investor", "ComplianceOfficer"})
    off = _get_offering_or_404(id)
    rows = [c for c in db.cap_table_entries.values() if c["offering_id"] == off["id"]]
    page, meta = paginate(rows)
    return success([cap_table_entry_out(r) for r in page], pagination=meta)
