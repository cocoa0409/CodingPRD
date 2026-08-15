from datetime import date

from flask import Blueprint, request

import db
import services
from errors import ApiError
from middleware import require_roles
from response import err, ok, ok_list
from validation import body, is_int, paginate, parse_date, req_date, req_int, req_str

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = ("PbmAdmin", "Pharmacist", "Member", "Auditor")
OVERRIDE_CODES = ("PROFESSIONAL_CONSULT", "PRESCRIBER_CONFIRMED", "PATIENT_EDUCATED")


def _resolve_pharmacist(uid):
    """A Pharmacist X-User-ID that matches no pharmacy is an unresolvable reference."""
    pharmacy = db.pharmacies.get(uid)
    if pharmacy is None:
        raise ApiError("ERR_PHARMACY_NOT_FOUND", "Pharmacist X-User-ID does not resolve to a pharmacy", 404)
    return pharmacy


def _get_claim_or_404(claim_id):
    claim = db.claims.get(claim_id)
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", "Claim not found", 404)
    return claim


def _reject(claim, reasons):
    """Persist the failed adjudication and answer with the first failed edit."""
    claim["status"] = "REJECTED"
    claim["reject_reasons"] = reasons
    services.zero_financials(claim)
    return err(reasons[0], "Claim adjudication failed", 422)


# ---------------------------------------------------------------------------
# POST /claims — point-of-sale submission
# ---------------------------------------------------------------------------

@bp.route("/claims", methods=["POST"])
def create_claim():
    uid, _ = require_roles("Pharmacist")
    # Stage 4: the dispensing pharmacy is the caller's identity; then body FKs.
    pharmacy = _resolve_pharmacist(uid)
    b = body()
    member_id = b.get("member_id")
    if member_id is not None and member_id not in db.members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "Member not found", 404)
    drug_id = b.get("drug_id")
    if drug_id is not None and drug_id not in db.drugs:
        raise ApiError("ERR_DRUG_NOT_FOUND", "Drug not found", 404)
    # Stage 5: claim writes require an ACTIVE dispensing pharmacy.
    if pharmacy["status"] != "ACTIVE":
        raise ApiError("ERR_PHARMACY_SUSPENDED", "Dispensing pharmacy is suspended", 409)
    # Stage 7: request shape.
    if not isinstance(member_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'member_id' is required and must be a string", 400)
    if not isinstance(drug_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'drug_id' is required and must be a string", 400)
    prescription_number = req_str(b, "prescription_number")
    fill_date_s = req_date(b, "fill_date")
    quantity = req_int(b, "quantity", minimum=1)
    days_supply = req_int(b, "days_supply", minimum=1)

    member = db.members[member_id]
    plan = db.plans[member["plan_id"]]
    drug = db.drugs[drug_id]

    # The claim is always persisted, whatever the adjudication outcome.
    claim = db.base_record()
    claim.update(
        {
            "member_id": member_id,
            "pharmacy_id": pharmacy["id"],
            "drug_id": drug_id,
            "prescription_number": prescription_number,
            "fill_date": fill_date_s,
            "quantity": quantity,
            "days_supply": days_supply,
            "status": "REJECTED",
            "reject_reasons": [],
            "allowed_cents": 0,
            "copay_base_cents": 0,
            "deductible_applied_cents": 0,
            "card_applied_cents": 0,
            "member_pays_cents": 0,
            "plan_paid_cents": 0,
            "pa_id": None,
            "resubmit_count": 0,
            "audit_status": "UNAUDITED",
            "rebate_tag": "REBATE_INELIGIBLE",
        }
    )
    db.claims[claim["id"]] = claim

    reasons, entry, pa = services.adjudicate(
        claim["id"], member, plan, drug, pharmacy, quantity, days_supply, parse_date(fill_date_s)
    )
    if reasons:
        claim["reject_reasons"] = reasons
        return err(reasons[0], "Claim adjudication failed", 422)
    services.pay_claim(claim, member, plan, drug, pharmacy, entry, pa)
    return ok(db.public(claim), 201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.route("/claims", methods=["GET"])
def list_claims():
    uid, role = require_roles(*CLAIM_READ_ROLES)
    rows = list(db.claims.values())
    if role == "Pharmacist":
        pharmacy = _resolve_pharmacist(uid)
        rows = [r for r in rows if r["pharmacy_id"] == pharmacy["id"]]
    elif role == "Member":
        rows = [r for r in rows if r["member_id"] == uid]
    member_id = request.args.get("member_id")
    pharmacy_id = request.args.get("pharmacy_id")
    drug_id = request.args.get("drug_id")
    pa_id = request.args.get("pa_id")
    status = request.args.get("status")
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if pharmacy_id is not None:
        rows = [r for r in rows if r["pharmacy_id"] == pharmacy_id]
    if drug_id is not None:
        rows = [r for r in rows if r["drug_id"] == drug_id]
    if pa_id is not None:
        rows = [r for r in rows if r.get("pa_id") == pa_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    uid, role = require_roles(*CLAIM_READ_ROLES)
    claim = _get_claim_or_404(claim_id)
    if role == "Pharmacist":
        pharmacy = _resolve_pharmacist(uid)
        if claim["pharmacy_id"] != pharmacy["id"]:
            raise ApiError("ERR_PHARMACY_MISMATCH", "Claim belongs to another pharmacy", 403)
    elif role == "Member":
        if claim["member_id"] != uid:
            raise ApiError("ERR_MEMBER_MISMATCH", "Claim belongs to another member", 403)
    return ok(db.public(claim), 200)


@bp.route("/claims/<claim_id>/dur-alerts", methods=["GET"])
def list_dur_alerts(claim_id):
    uid, role = require_roles("PbmAdmin", "Pharmacist", "Auditor")
    claim = _get_claim_or_404(claim_id)
    if role == "Pharmacist":
        pharmacy = _resolve_pharmacist(uid)
        if claim["pharmacy_id"] != pharmacy["id"]:
            raise ApiError("ERR_PHARMACY_MISMATCH", "Claim belongs to another pharmacy", 403)
    rows = [a for a in db.dur_alerts.values() if a["claim_id"] == claim["id"]]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Claim lifecycle actions (owning, non-suspended pharmacist only)
# ---------------------------------------------------------------------------

def _owned_claim_context(claim_id, uid):
    """Resolve claim + caller pharmacy and enforce entity-backed ownership."""
    claim = _get_claim_or_404(claim_id)
    pharmacy = _resolve_pharmacist(uid)
    if claim["pharmacy_id"] != pharmacy["id"]:
        raise ApiError("ERR_PHARMACY_MISMATCH", "Claim belongs to another pharmacy", 403)
    return claim, pharmacy


def _validate_overrides(claim, overrides):
    for item in overrides:
        if not isinstance(item, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Each dur_overrides entry must be an object", 400)
        alert_id = item.get("alert_id")
        code = item.get("override_code")
        if not isinstance(alert_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "Each dur_overrides entry needs an alert_id", 400)
        alert = db.dur_alerts.get(alert_id)
        if alert is None or alert["claim_id"] != claim["id"]:
            raise ApiError("ERR_INVALID_REQUEST", "dur_overrides must reference alerts of this claim", 400)
        if code not in OVERRIDE_CODES:
            raise ApiError("ERR_INVALID_REQUEST", "override_code is not a valid enumeration value", 400)


def _apply_overrides(claim, overrides):
    """Overrides naming this claim's OPEN alerts move them to OVERRIDDEN."""
    for item in overrides:
        alert = db.dur_alerts[item["alert_id"]]
        if alert["status"] == "OPEN":
            alert["status"] = "OVERRIDDEN"
            alert["override_code"] = item["override_code"]


@bp.route("/claims/<claim_id>/resubmit", methods=["POST"])
def resubmit_claim(claim_id):
    uid, _ = require_roles("Pharmacist")
    claim, pharmacy = _owned_claim_context(claim_id, uid)
    # Stage 5 (PRD order): claim state first, then pharmacy suspension.
    if claim["status"] != "REJECTED":
        raise ApiError("ERR_CLAIM_NOT_REJECTED", "Only a REJECTED claim can be resubmitted", 409)
    if pharmacy["status"] != "ACTIVE":
        raise ApiError("ERR_PHARMACY_SUSPENDED", "Dispensing pharmacy is suspended", 409)
    b = body()
    overrides = b.get("dur_overrides", [])
    if overrides is None:
        overrides = []
    if not isinstance(overrides, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'dur_overrides' must be a list", 400)
    _validate_overrides(claim, overrides)

    _apply_overrides(claim, overrides)
    claim["resubmit_count"] += 1

    member = db.members[claim["member_id"]]
    plan = db.plans[member["plan_id"]]
    drug = db.drugs[claim["drug_id"]]
    reasons, entry, pa = services.adjudicate(
        claim["id"], member, plan, drug, pharmacy,
        claim["quantity"], claim["days_supply"], parse_date(claim["fill_date"]),
    )
    if reasons:
        response = _reject(claim, reasons)
        db.touch(claim)
        return response
    services.pay_claim(claim, member, plan, drug, pharmacy, entry, pa)
    db.touch(claim)
    return ok(db.public(claim), 200)


@bp.route("/claims/<claim_id>/reverse", methods=["POST"])
def reverse_claim(claim_id):
    uid, _ = require_roles("Pharmacist")
    claim, pharmacy = _owned_claim_context(claim_id, uid)
    if claim["status"] != "PAID":
        raise ApiError("ERR_CLAIM_NOT_PAID", "Only a PAID claim can be reversed", 409)
    if pharmacy["status"] != "ACTIVE":
        raise ApiError("ERR_PHARMACY_SUSPENDED", "Dispensing pharmacy is suspended", 409)
    b = body()
    req_str(b, "reversal_reason")

    member = db.members[claim["member_id"]]
    plan = db.plans[member["plan_id"]]
    services.compensate_payment(claim, member, plan, pharmacy)
    claim["status"] = "REVERSED"
    db.touch(claim)
    return ok(db.public(claim), 200)


@bp.route("/claims/<claim_id>/reprocess", methods=["POST"])
def reprocess_claim(claim_id):
    uid, _ = require_roles("Pharmacist")
    claim, pharmacy = _owned_claim_context(claim_id, uid)
    if claim["status"] != "REVERSED":
        raise ApiError("ERR_CLAIM_NOT_REVERSED", "Only a REVERSED claim can be reprocessed", 409)
    if pharmacy["status"] != "ACTIVE":
        raise ApiError("ERR_PHARMACY_SUSPENDED", "Dispensing pharmacy is suspended", 409)
    b = body()
    # Stage 7: corrected values, each optional; omitted fields keep stored values.
    if "quantity" in b and b["quantity"] is not None:
        if not is_int(b["quantity"]) or b["quantity"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'quantity' must be a positive integer", 400)
        claim["quantity"] = b["quantity"]
    if "days_supply" in b and b["days_supply"] is not None:
        if not is_int(b["days_supply"]) or b["days_supply"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'days_supply' must be a positive integer", 400)
        claim["days_supply"] = b["days_supply"]
    if "fill_date" in b and b["fill_date"] is not None:
        d = parse_date(b["fill_date"])
        if d is None:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'fill_date' must be a valid ISO date", 400)
        claim["fill_date"] = d.isoformat()

    # Reprocessing regenerates screening entirely: OPEN alerts are SUPERSEDED.
    for alert in db.dur_alerts.values():
        if alert["claim_id"] == claim["id"] and alert["status"] == "OPEN":
            alert["status"] = "SUPERSEDED"

    member = db.members[claim["member_id"]]
    plan = db.plans[member["plan_id"]]
    drug = db.drugs[claim["drug_id"]]
    reasons, entry, pa = services.adjudicate(
        claim["id"], member, plan, drug, pharmacy,
        claim["quantity"], claim["days_supply"], parse_date(claim["fill_date"]),
    )
    if reasons:
        response = _reject(claim, reasons)
        db.touch(claim)
        return response
    services.pay_claim(claim, member, plan, drug, pharmacy, entry, pa)
    db.touch(claim)
    return ok(db.public(claim), 200)
