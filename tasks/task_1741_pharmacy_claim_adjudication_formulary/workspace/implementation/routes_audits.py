from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import services
from errors import ApiError
from middleware import require_roles
from response import ok, ok_list
from validation import body, is_int, paginate, parse_date, req_date, req_enum, req_str

bp = Blueprint("audits", __name__)

AUDIT_ROLES = ("PbmAdmin", "Pharmacist", "Auditor")
OPEN_STATUSES = ("OPEN", "FINDINGS_RECORDED", "DISPUTED")


def _d(s):
    return date.fromisoformat(s)


def get_audit_or_404(audit_id):
    audit = db.audits.get(audit_id)
    if audit is None:
        raise ApiError("ERR_AUDIT_NOT_FOUND", "Audit not found", 404)
    return audit


@bp.route("/audits", methods=["POST"])
def create_audit():
    require_roles("Auditor")
    b = body()
    # Stage 4: body FK existence.
    pharmacy_id = b.get("pharmacy_id")
    if pharmacy_id is not None and pharmacy_id not in db.pharmacies:
        raise ApiError("ERR_PHARMACY_NOT_FOUND", "Pharmacy not found", 404)
    # Stage 7: request shape — closed window, valid enum.
    if not isinstance(pharmacy_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'pharmacy_id' is required and must be a string", 400)
    start = req_date(b, "window_start_date")
    end = req_date(b, "window_end_date")
    if _d(end) < _d(start):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "window_end_date must be on or after window_start_date",
            400,
        )
    method = req_enum(b, "extrapolation_method", ("CLAIM_LEVEL", "EXTRAPOLATED"))
    # Stage 9: no overlapping open-window audit on the same pharmacy; both
    # window bounds are inclusive, so merely touching boundaries overlaps.
    for other in db.audits.values():
        if other["pharmacy_id"] != pharmacy_id or other["status"] not in OPEN_STATUSES:
            continue
        if _d(start) <= _d(other["window_end_date"]) and _d(other["window_start_date"]) <= _d(end):
            raise ApiError(
                "ERR_AUDIT_WINDOW_OVERLAP",
                "An open audit window on this pharmacy already overlaps this window",
                422,
            )
    rec = db.base_record()
    rec.update(
        {
            "pharmacy_id": pharmacy_id,
            "window_start_date": start,
            "window_end_date": end,
            "extrapolation_method": method,
            "status": "OPEN",
            "findings": [],
            "sample_size": 0,
            "universe_paid_claims": 0,
            "total_clawback_cents": 0,
            "dispute_reason": None,
        }
    )
    db.audits[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.route("/audits", methods=["GET"])
def list_audits():
    require_roles(*AUDIT_ROLES)
    rows = list(db.audits.values())
    pharmacy_id = request.args.get("pharmacy_id")
    status = request.args.get("status")
    if pharmacy_id is not None:
        rows = [r for r in rows if r["pharmacy_id"] == pharmacy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.route("/audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    require_roles(*AUDIT_ROLES)
    return ok(db.public(get_audit_or_404(audit_id)), 200)


@bp.route("/audits/<audit_id>/findings", methods=["POST"])
def record_findings(audit_id):
    require_roles("Auditor")
    audit = get_audit_or_404(audit_id)
    b = body()
    findings = b.get("findings")
    # Stage 4: every referenced claim_id must resolve (best effort extraction).
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict):
                cid = item.get("claim_id")
                if cid is not None and cid not in db.claims:
                    raise ApiError("ERR_CLAIM_NOT_FOUND", "Findings reference an unknown claim", 404)
    # Stage 5: findings may be recorded from OPEN, FINDINGS_RECORDED, DISPUTED.
    if audit["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Findings cannot be recorded in the audit's current state", 409)
    # Stage 7: findings non-empty; each pairs a claim_id with clawback_cents > 0.
    if not isinstance(findings, list) or not findings:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'findings' must be a non-empty list", 400)
    for item in findings:
        if not isinstance(item, dict) or not isinstance(item.get("claim_id"), str):
            raise ApiError("ERR_INVALID_REQUEST", "Each finding needs a claim_id", 400)
        if not is_int(item.get("clawback_cents")) or item["clawback_cents"] <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "Each finding's clawback_cents must be a positive integer", 400)
    # Stage 10: every referenced claim must be auditable. Claims already
    # FLAGGED by this audit's current finding set remain referenceable on
    # revision; any other non-UNAUDITED claim is rejected.
    current_ids = {f["claim_id"] for f in audit["findings"]}
    for item in findings:
        claim = db.claims[item["claim_id"]]
        if (
            claim["pharmacy_id"] != audit["pharmacy_id"]
            or claim["status"] != "PAID"
            or not (_d(audit["window_start_date"]) <= _d(claim["fill_date"]) <= _d(audit["window_end_date"]))
            or (claim["audit_status"] != "UNAUDITED" and claim["id"] not in current_ids)
        ):
            raise ApiError(
                "ERR_CLAIM_NOT_AUDITABLE",
                "A findings claim belongs to another pharmacy, is not PAID, lies outside the audit window, or is not UNAUDITED",
                422,
            )
    # Wholesale replacement: dropped claims return to UNAUDITED, newly
    # referenced claims become FLAGGED.
    new_ids = {item["claim_id"] for item in findings}
    old_ids = {item["claim_id"] for item in audit["findings"]}
    for cid in old_ids - new_ids:
        claim = db.claims[cid]
        if claim["audit_status"] == "FLAGGED":
            claim["audit_status"] = "UNAUDITED"
            db.touch(claim)
    for cid in new_ids - old_ids:
        claim = db.claims[cid]
        claim["audit_status"] = "FLAGGED"
        db.touch(claim)
    audit["findings"] = [{"claim_id": i["claim_id"], "clawback_cents": i["clawback_cents"]} for i in findings]
    audit["sample_size"] = len(findings)
    audit["status"] = "FINDINGS_RECORDED"
    db.touch(audit)
    return ok(db.public(audit), 200)


@bp.route("/audits/<audit_id>/dispute", methods=["POST"])
def dispute_audit(audit_id):
    uid, _ = require_roles("Pharmacist")
    audit = get_audit_or_404(audit_id)
    pharmacy = db.pharmacies.get(uid)
    if pharmacy is None:
        raise ApiError("ERR_PHARMACY_NOT_FOUND", "Pharmacist X-User-ID does not resolve to a pharmacy", 404)
    if audit["pharmacy_id"] != pharmacy["id"]:
        raise ApiError("ERR_PHARMACY_MISMATCH", "Audit belongs to another pharmacy", 403)
    if audit["status"] != "FINDINGS_RECORDED":
        raise ApiError("ERR_AUDIT_INVALID_STATE", "Only an audit with recorded findings can be disputed", 409)
    b = body()
    audit["dispute_reason"] = req_str(b, "dispute_reason")
    audit["status"] = "DISPUTED"
    db.touch(audit)
    return ok(db.public(audit), 200)


@bp.route("/audits/<audit_id>/close", methods=["POST"])
def close_audit(audit_id):
    require_roles("Auditor")
    audit = get_audit_or_404(audit_id)
    if audit["status"] == "OPEN":
        audit["status"] = "CLOSED_NO_FINDINGS"
        audit["total_clawback_cents"] = 0
        db.touch(audit)
        return ok(db.public(audit), 200)
    if audit["status"] != "FINDINGS_RECORDED":
        raise ApiError(
            "ERR_AUDIT_INVALID_STATE",
            "An audit must be OPEN or FINDINGS_RECORDED to close; DISPUTED must be resolved by revised findings first",
            409,
        )
    # Clawback cascade. Universe measured at close time over the closed window.
    pharmacy = db.pharmacies[audit["pharmacy_id"]]
    universe = sum(
        1
        for c in db.claims.values()
        if c["pharmacy_id"] == pharmacy["id"]
        and c["status"] == "PAID"
        and _d(audit["window_start_date"]) <= _d(c["fill_date"]) <= _d(audit["window_end_date"])
    )
    audit["universe_paid_claims"] = universe
    findings = audit["findings"]
    sample = len(findings)
    if audit["extrapolation_method"] == "CLAIM_LEVEL":
        total = sum(f["clawback_cents"] for f in findings)
    else:
        # EXTRAPOLATED: round each per-claim extrapolated clawback half-up to
        # whole cents FIRST, then sum (sum-then-round is forbidden).
        total = 0
        for f in findings:
            scaled = Decimal(f["clawback_cents"]) * Decimal(universe) / Decimal(sample)
            total += int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    audit["total_clawback_cents"] = total
    for f in findings:
        claim = db.claims[f["claim_id"]]
        claim["audit_status"] = "CLAWED_BACK"
        if claim["rebate_tag"] == "REBATE_ELIGIBLE":
            claim["rebate_tag"] = "REBATE_VOID"
        db.touch(claim)
    pharmacy["balance_cents"] -= total
    db.touch(pharmacy)
    services.maybe_suspend(pharmacy)
    audit["status"] = "CLOSED_WITH_FINDINGS"
    db.touch(audit)
    return ok(db.public(audit), 200)
