"""Certification, ReimbursementClaim, CertificationBonus endpoints."""

from flask import Blueprint, request

from clock import clock, fiscal_year_of
from db import db
from errors import (err_budget_exceeded, err_certification_date_order,
                    err_certification_overlap, err_claim_exceeds_fee,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_not_owner, err_reimbursement_cap_exhausted,
                    err_renewal_mismatch, err_segregation, err_stale_reference)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from serializers import certification_view, claim_view, bonus_view
from services.budget import budget_guard, recompute_budget_for_unit_fy, recompute_budgets_for_unit
from services.calculations import (calc_certification_bonus, calc_reimbursement_cap,
                                   record_risk_event, recompute_risk, subtract_years)
from util import parse_datetime, require_fields, require_int, require_enum, require_string, optional_string

bp = Blueprint("certifications", __name__)

CERT_TRACKS_INPUT = {"BASIC", "SPECIALTY", "ADVANCED"}


def _get_nurse_or_404(nid):
    nurse = db.nurses.get(nid)
    if nurse is None:
        raise err_not_found("Nurse not found")
    return nurse


def _get_cert_or_404(cid):
    cert = db.certifications.get(cid)
    if cert is None:
        raise err_not_found("Certification not found")
    return cert


def _get_claim_or_404(cid):
    claim = db.reimbursement_claims.get(cid)
    if claim is None:
        raise err_not_found("ReimbursementClaim not found")
    return claim


def _get_bonus_or_404(bid):
    bonus = db.certification_bonuses.get(bid)
    if bonus is None:
        raise err_not_found("CertificationBonus not found")
    return bonus


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------

@bp.route("/clinical-ladder/certifications", methods=["POST"])
def create_certification():
    require_roles("ProgramAdmin")
    payload = request.get_json(silent=True)
    require_fields(payload, ["nurse_id", "track", "certifying_body", "exam_fee_cents",
                             "obtained_on", "expires_on"])
    nurse_id = payload.get("nurse_id")
    if not isinstance(nurse_id, str):
        raise err_invalid_request("nurse_id must be a string")
    track = require_enum(payload, "track", CERT_TRACKS_INPUT)
    certifying_body = require_string(payload, "certifying_body")
    exam_fee_cents = require_int(payload, "exam_fee_cents")
    obtained_on = parse_datetime(payload.get("obtained_on"), "obtained_on")
    expires_on = parse_datetime(payload.get("expires_on"), "expires_on")
    renewal_of_id = payload.get("renewal_of_id")
    if renewal_of_id is not None and not isinstance(renewal_of_id, str):
        raise err_invalid_request("renewal_of_id must be a string")

    nurse = _get_nurse_or_404(nurse_id)
    if exam_fee_cents <= 0:
        raise err_invalid_request("exam_fee_cents must be > 0")

    # Rule order pinned: date order, then renewal matching, then currency overlap
    if expires_on <= obtained_on:
        raise err_certification_date_order()

    if renewal_of_id is not None:
        target = db.certifications.get(renewal_of_id)
        if target is None or target["nurse_id"] != nurse_id or target["track"] != track:
            raise err_renewal_mismatch()

    for c in db.certifications.values():
        if c["nurse_id"] != nurse_id or c["track"] != track or c["status"] != "CURRENT":
            continue
        # Half-open interval overlap; adjacency (old expiry == new grant) is NOT overlap
        if c["expires_on"] <= obtained_on:
            continue
        if expires_on <= c["obtained_on"]:
            continue
        raise err_certification_overlap()

    now = clock.now()
    cert = {
        "id": db.new_id(),
        "nurse_id": nurse_id,
        "track": track,
        "certifying_body": certifying_body,
        "exam_fee_cents": exam_fee_cents,
        "obtained_on": obtained_on,
        "expires_on": expires_on,
        "status": "CURRENT",
        "renewal_of_id": renewal_of_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.certifications[cert["id"]] = cert

    # Side effect: accrue CertificationBonus (server-computed amount)
    bonus = {
        "id": db.new_id(),
        "certification_id": cert["id"],
        "bonus_amount_cents": calc_certification_bonus(cert, nurse),
        "status": "ACCRUED",
        "clawback_reason": None,
        "paid_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.certification_bonuses[bonus["id"]] = bonus

    # Side effect: recompute unit budget commitment (accrual commits budget)
    recompute_budget_for_unit_fy(nurse["home_unit"], fiscal_year_of(now))

    return success_object(certification_view(cert), status=201)


@bp.route("/clinical-ladder/certifications", methods=["GET"])
def list_certifications():
    require_roles("ProgramAdmin", "Nurse")
    limit, offset = parse_pagination(request.args)
    nurse_id = request.args.get("nurse_id")
    renewal_of_id = request.args.get("renewal_of_id")
    track = request.args.get("track")
    status = request.args.get("status")
    rows = sorted(db.certifications.values(), key=lambda c: c["created_at"])
    if nurse_id is not None:
        rows = [c for c in rows if c["nurse_id"] == nurse_id]
    if renewal_of_id is not None:
        rows = [c for c in rows if c["renewal_of_id"] == renewal_of_id]
    if track is not None:
        rows = [c for c in rows if c["track"] == track]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([certification_view(c) for c in page], limit, offset, total)


@bp.route("/clinical-ladder/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    require_roles("ProgramAdmin", "Nurse")
    cert = _get_cert_or_404(cid)
    return success_object(certification_view(cert))


@bp.route("/clinical-ladder/certifications/<cid>/reimbursement-claims", methods=["GET"])
def cert_claims(cid):
    require_roles("ProgramAdmin", "PayrollOfficer", "Nurse")
    cert = _get_cert_or_404(cid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([c for c in db.reimbursement_claims.values() if c["certification_id"] == cert["id"]],
                  key=lambda c: c["created_at"])
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([claim_view(c) for c in page], limit, offset, total)


@bp.route("/clinical-ladder/certifications/<cid>/certification-bonuses", methods=["GET"])
def cert_bonuses(cid):
    require_roles("ProgramAdmin", "PayrollOfficer", "Nurse")
    cert = _get_cert_or_404(cid)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = sorted([b for b in db.certification_bonuses.values() if b["certification_id"] == cert["id"]],
                  key=lambda b: b["created_at"])
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([bonus_view(b) for b in page], limit, offset, total)


@bp.route("/clinical-ladder/certifications/<cid>/revoke", methods=["POST"])
def revoke_certification(cid):
    require_roles("ProgramAdmin")
    cert = _get_cert_or_404(cid)
    if cert["status"] != "CURRENT":
        raise err_invalid_state("Certification is not CURRENT")
    now = clock.now()
    cert["status"] = "REVOKED"
    cert["updated_at"] = now
    cert["version"] += 1

    nurse = _get_nurse_or_404(cert["nurse_id"])

    # Clawback cascade: PAID bonuses paid within trailing 12 months flip to CLAWED_BACK.
    # Upper bound inclusive: a bonus paid at the current instant is within the window.
    window_start = subtract_years(now, 1)
    clawed = False
    for bonus in db.certification_bonuses.values():
        if bonus["certification_id"] != cert["id"] or bonus["status"] != "PAID":
            continue
        paid_at = bonus.get("paid_at")
        if paid_at is not None and window_start <= paid_at <= now:
            bonus["status"] = "CLAWED_BACK"
            bonus["updated_at"] = now
            bonus["version"] += 1
            record_risk_event(nurse["id"], "bonus_clawback")
            clawed = True

    # Clawback releases commitment; recompute the unit line(s)
    recompute_budgets_for_unit(nurse["home_unit"])
    recompute_risk(nurse["id"])
    return success_object(certification_view(cert))


# ---------------------------------------------------------------------------
# Reimbursement claims
# ---------------------------------------------------------------------------

@bp.route("/clinical-ladder/reimbursement-claims", methods=["POST"])
def create_claim():
    user_id, _ = require_roles("Nurse")
    payload = request.get_json(silent=True)
    require_fields(payload, ["certification_id", "claimed_amount_cents"])
    cert_id = payload.get("certification_id")
    if not isinstance(cert_id, str):
        raise err_invalid_request("certification_id must be a string")
    claimed = require_int(payload, "claimed_amount_cents")

    cert = _get_cert_or_404(cert_id)
    nurse = _get_nurse_or_404(cert["nurse_id"])

    # Ownership: only the holding nurse may file a claim on the certification
    if user_id != cert["nurse_id"]:
        raise err_not_owner()

    if claimed <= 0:
        raise err_claim_exceeds_fee("claimed_amount_cents must be positive")

    already = 0
    for c in db.reimbursement_claims.values():
        if c["certification_id"] == cert["id"] and c["status"] in ("APPROVED", "PAID"):
            already += c["approved_amount_cents"] or 0
    if claimed > cert["exam_fee_cents"] - already:
        raise err_claim_exceeds_fee()

    now = clock.now()
    claim = {
        "id": db.new_id(),
        "certification_id": cert["id"],
        "claimed_amount_cents": claimed,
        "approved_amount_cents": None,
        "status": "SUBMITTED",
        "denial_reason": None,
        "fiscal_year": fiscal_year_of(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.reimbursement_claims[claim["id"]] = claim
    return success_object(claim_view(claim), status=201)


@bp.route("/clinical-ladder/reimbursement-claims/<cid>", methods=["GET"])
def get_claim(cid):
    require_roles("ProgramAdmin", "PayrollOfficer", "Nurse")
    claim = _get_claim_or_404(cid)
    return success_object(claim_view(claim))


@bp.route("/clinical-ladder/reimbursement-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    user_id, _ = require_roles("ProgramAdmin")
    claim = _get_claim_or_404(cid)
    if claim["status"] != "SUBMITTED":
        raise err_invalid_state("Claim is not SUBMITTED")
    cert = _get_cert_or_404(claim["certification_id"])
    nurse = _get_nurse_or_404(cert["nurse_id"])

    # Approval order pinned: segregation of duties, then FY ceiling, then cert staleness
    if user_id == cert["nurse_id"]:
        raise err_segregation("Approver may not be the claiming nurse")

    cap = calc_reimbursement_cap(nurse["id"], claim["fiscal_year"], claim["claimed_amount_cents"])
    if cap <= 0:
        raise err_reimbursement_cap_exhausted()

    if cert["status"] != "CURRENT":
        raise err_stale_reference("Certification is no longer CURRENT at decision time")

    now = clock.now()
    claim["approved_amount_cents"] = cap
    claim["status"] = "APPROVED"
    claim["updated_at"] = now
    claim["version"] += 1

    recompute_budget_for_unit_fy(nurse["home_unit"], claim["fiscal_year"])
    return success_object(claim_view(claim))


@bp.route("/clinical-ladder/reimbursement-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    require_roles("ProgramAdmin")
    claim = _get_claim_or_404(cid)
    payload = request.get_json(silent=True) or {}
    denial_reason = payload.get("denial_reason")
    if not isinstance(denial_reason, str) or not denial_reason:
        raise err_invalid_request("denial_reason is required")
    if claim["status"] != "SUBMITTED":
        raise err_invalid_state("Claim is not SUBMITTED")
    now = clock.now()
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    claim["updated_at"] = now
    claim["version"] += 1
    return success_object(claim_view(claim))


@bp.route("/clinical-ladder/reimbursement-claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    require_roles("PayrollOfficer")
    claim = _get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise err_invalid_state("Claim is not APPROVED")
    cert = _get_cert_or_404(claim["certification_id"])
    nurse = _get_nurse_or_404(cert["nurse_id"])

    ok, _line = budget_guard(nurse["home_unit"], claim["fiscal_year"], claim["approved_amount_cents"])
    if not ok:
        raise err_budget_exceeded()

    now = clock.now()
    claim["status"] = "PAID"
    claim["updated_at"] = now
    claim["version"] += 1
    recompute_budget_for_unit_fy(nurse["home_unit"], claim["fiscal_year"])
    return success_object(claim_view(claim))


# ---------------------------------------------------------------------------
# Certification bonuses
# ---------------------------------------------------------------------------

@bp.route("/clinical-ladder/certification-bonuses/<bid>/pay", methods=["POST"])
def pay_bonus(bid):
    require_roles("PayrollOfficer")
    bonus = _get_bonus_or_404(bid)
    if bonus["status"] != "ACCRUED":
        raise err_invalid_state("Bonus is not ACCRUED")
    cert = _get_cert_or_404(bonus["certification_id"])
    if cert["status"] != "CURRENT":
        raise err_invalid_state("Parent certification is not CURRENT")
    nurse = _get_nurse_or_404(cert["nurse_id"])
    now = clock.now()
    fy = fiscal_year_of(now)

    ok, _line = budget_guard(nurse["home_unit"], fy, bonus["bonus_amount_cents"])
    if not ok:
        raise err_budget_exceeded()

    bonus["status"] = "PAID"
    bonus["paid_at"] = now
    bonus["updated_at"] = now
    bonus["version"] += 1
    recompute_budget_for_unit_fy(nurse["home_unit"], fy)
    return success_object(bonus_view(bonus))


@bp.route("/clinical-ladder/certification-bonuses/<bid>/claw-back", methods=["POST"])
def claw_back_bonus(bid):
    require_roles("ProgramAdmin")
    bonus = _get_bonus_or_404(bid)
    payload = request.get_json(silent=True) or {}
    reason = payload.get("clawback_reason")
    if not isinstance(reason, str) or not reason:
        raise err_invalid_request("clawback_reason is required")
    if bonus["status"] not in ("ACCRUED", "PAID"):
        raise err_invalid_state("Bonus is not in a clawback-eligible state")

    cert = _get_cert_or_404(bonus["certification_id"])
    nurse = _get_nurse_or_404(cert["nurse_id"])
    now = clock.now()

    was_paid = bonus["status"] == "PAID"
    if was_paid:
        paid_at = bonus.get("paid_at")
        within_12m = paid_at is not None and subtract_years(now, 1) <= paid_at <= now
        if not (within_12m or cert["status"] == "REVOKED"):
            raise err_invalid_state("Paid bonus is outside the 12-month clawback window")

    bonus["status"] = "CLAWED_BACK"
    bonus["clawback_reason"] = reason
    bonus["updated_at"] = now
    bonus["version"] += 1

    recompute_budgets_for_unit(nurse["home_unit"])
    if was_paid:
        # Clawback from PAID raises the holder's retention risk
        record_risk_event(nurse["id"], "bonus_clawback")
        recompute_risk(nurse["id"])
    return success_object(bonus_view(bonus))
