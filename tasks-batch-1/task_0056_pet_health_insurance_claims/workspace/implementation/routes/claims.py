"""Claim / ClaimLine / InvoiceDocument routes and adjudication (PRD §3.4–3.7)."""
from __future__ import annotations

from flask import Blueprint, request, g

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_CLAIM_NOT_READY,
    ERR_WITHIN_WAITING_PERIOD,
    ERR_PRE_EXISTING_EXCLUDED,
    ERR_POLICY_YEAR_CLOSED,
    ERR_STALE_POLICY_YEAR_VERSION,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.common import (
    get_or_404,
    require_str,
    require_int,
    optional_int,
    optional_bool,
    require_enum,
    sorted_by_creation,
)
from services import calculations, ledger

bp = Blueprint("claims", __name__)

ALL_ROLES = ["PolicyHolder", "Underwriter", "ClaimsAdjuster"]


def _account_for_claim(claim: dict):
    pol = db.policies.get(claim.get("policy_id"))
    if pol is None:
        return None, None
    acct = db.accounts.get(pol.get("account_id"))
    return pol, acct


def _enforce_claim_owner(claim: dict):
    """PolicyHolder acting on a claim must own the owning account (priority 6)."""
    if g.user_role == "PolicyHolder":
        _, acct = _account_for_claim(claim)
        if acct is None or g.user_id != acct["id"]:
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Not the owner of this claim")


# ---------------------------------------------------------------------------
# Claim reads
# ---------------------------------------------------------------------------
@bp.get("/claims")
def list_claims():
    require_auth(ALL_ROLES)()
    limit, offset = paginate_params(request.args)
    policy_id = request.args.get("policy_id")
    condition_id = request.args.get("condition_id")
    status = request.args.get("status")
    items = list(db.claims.values())
    if policy_id is not None:
        items = [c for c in items if c.get("policy_id") == policy_id]
    if condition_id is not None:
        items = [c for c in items if c.get("condition_id") == condition_id]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.get("/claims/<cid>")
def get_claim(cid):
    require_auth(ALL_ROLES)()
    claim = get_or_404(db.claims, cid, "Claim")
    return ok_object(claim, 200)


# ---------------------------------------------------------------------------
# Claim lines
# ---------------------------------------------------------------------------
@bp.post("/claims/<cid>/lines")
def add_line(cid):
    require_auth(["PolicyHolder"])()
    claim = get_or_404(db.claims, cid, "Claim")
    _enforce_claim_owner(claim)
    if claim["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Lines may only be added to a DRAFT claim")
    body = get_json_body()
    description = require_str(body, "description")
    billed = require_int(body, "billed_amount_cents")
    if billed < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "billed_amount_cents must be >= 0")

    line = db.stamp_common(
        {
            "claim_id": claim["id"],
            "description": description,
            "billed_amount_cents": billed,
            "allowed_amount_cents": 0,
            "excluded": False,
        }
    )
    db.claim_lines[line["id"]] = line
    return ok_object(line, 201)


@bp.get("/claims/<cid>/lines")
def list_lines(cid):
    require_auth(ALL_ROLES)()
    claim = get_or_404(db.claims, cid, "Claim")
    limit, offset = paginate_params(request.args)
    items = [l for l in db.claim_lines.values() if l.get("claim_id") == claim["id"]]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.patch("/claims/<cid>/lines/<lid>")
def adjust_line(cid, lid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_or_404(db.claims, cid, "Claim")
    line = get_or_404(db.claim_lines, lid, "ClaimLine")
    if line.get("claim_id") != claim["id"]:
        raise APIError(ERR_NOT_FOUND, 404, "ClaimLine not found under claim")
    if claim["status"] != "IN_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Lines may only be adjusted while IN_REVIEW")

    body = get_json_body()
    billed = optional_int(body, "billed_amount_cents", None)
    excluded = optional_bool(body, "excluded", None)
    if billed is not None:
        if billed < 0:
            raise APIError(ERR_INVALID_REQUEST, 400, "billed_amount_cents must be >= 0")
        line["billed_amount_cents"] = billed
    if excluded is not None:
        line["excluded"] = excluded

    calculations.recompute_eligible_amount(claim)
    db.bump(claim)
    return ok_object(line, 200)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@bp.post("/claims/<cid>/invoices")
def upload_invoice(cid):
    require_auth(["PolicyHolder"])()
    claim = get_or_404(db.claims, cid, "Claim")
    _enforce_claim_owner(claim)
    if claim["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Invoices may only be uploaded to a DRAFT claim")
    body = get_json_body()
    file_uri = require_str(body, "file_uri")

    inv = db.stamp_common(
        {
            "claim_id": claim["id"],
            "file_uri": file_uri,
            "ocr_total_cents": None,
            "ocr_status": "PENDING_OCR",
            "ocr_mismatch_bps": None,
        }
    )
    db.invoices[inv["id"]] = inv
    return ok_object(inv, 201)


@bp.get("/claims/<cid>/invoices")
def list_invoices(cid):
    require_auth(ALL_ROLES)()
    claim = get_or_404(db.claims, cid, "Claim")
    limit, offset = paginate_params(request.args)
    items = [i for i in db.invoices.values() if i.get("claim_id") == claim["id"]]
    items = sorted_by_creation(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


def _resolve_invoice(cid, iid):
    claim = get_or_404(db.claims, cid, "Claim")
    inv = get_or_404(db.invoices, iid, "InvoiceDocument")
    if inv.get("claim_id") != claim["id"]:
        raise APIError(ERR_NOT_FOUND, 404, "InvoiceDocument not found under claim")
    return claim, inv


@bp.post("/claims/<cid>/invoices/<iid>/run-ocr")
def run_ocr(cid, iid):
    require_auth(["ClaimsAdjuster"])()
    claim, inv = _resolve_invoice(cid, iid)
    if inv["ocr_status"] != "PENDING_OCR":
        raise APIError(ERR_INVALID_STATE, 409, "run-ocr only valid from PENDING_OCR")
    body = get_json_body()
    ocr_total = require_int(body, "ocr_total_cents")
    if ocr_total < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "ocr_total_cents must be >= 0")

    inv["ocr_total_cents"] = ocr_total
    mismatch = calculations.ocr_mismatch_bps(ocr_total, claim.get("submitted_amount_cents") or 0)
    inv["ocr_mismatch_bps"] = mismatch
    if mismatch > calculations.OCR_MISMATCH_TOLERANCE_BPS:
        inv["ocr_status"] = "REVIEW_NEEDED"
    else:
        inv["ocr_status"] = "OCR_DONE"
    db.bump(inv)
    return ok_object(inv, 200)


@bp.post("/claims/<cid>/invoices/<iid>/accept")
def accept_invoice(cid, iid):
    require_auth(["ClaimsAdjuster"])()
    _, inv = _resolve_invoice(cid, iid)
    if inv["ocr_status"] not in ("OCR_DONE", "REVIEW_NEEDED"):
        raise APIError(ERR_INVALID_STATE, 409, "accept only valid from OCR_DONE or REVIEW_NEEDED")
    inv["ocr_status"] = "ACCEPTED"
    db.bump(inv)
    return ok_object(inv, 200)


@bp.post("/claims/<cid>/invoices/<iid>/reject")
def reject_invoice(cid, iid):
    require_auth(["ClaimsAdjuster"])()
    _, inv = _resolve_invoice(cid, iid)
    if inv["ocr_status"] != "REVIEW_NEEDED":
        raise APIError(ERR_INVALID_STATE, 409, "reject only valid from REVIEW_NEEDED")
    inv["ocr_status"] = "REJECTED"
    db.bump(inv)
    return ok_object(inv, 200)


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------
@bp.post("/claims/<cid>/submit")
def submit_claim(cid):
    require_auth(["PolicyHolder"])()
    claim = get_or_404(db.claims, cid, "Claim")
    _enforce_claim_owner(claim)

    if claim["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Submit only valid from DRAFT")

    pol = db.policies.get(claim["policy_id"])
    lines = [l for l in db.claim_lines.values() if l.get("claim_id") == claim["id"]]
    has_accepted_invoice = any(
        i.get("claim_id") == claim["id"] and i.get("ocr_status") == "ACCEPTED"
        for i in db.invoices.values()
    )
    if pol is None or pol.get("status") != "ACTIVE" or len(lines) < 1 or not has_accepted_invoice:
        raise APIError(
            ERR_CLAIM_NOT_READY,
            422,
            "Claim requires ACTIVE policy, >=1 line, and an ACCEPTED invoice",
        )

    claim["submitted_amount_cents"] = sum(l["billed_amount_cents"] for l in lines)
    claim["status"] = "SUBMITTED"
    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<cid>/begin-review")
def begin_review(cid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "begin-review only valid from SUBMITTED")
    calculations.recompute_eligible_amount(claim)
    claim["status"] = "IN_REVIEW"
    db.bump(claim)
    return ok_object(claim, 200)


# ---------------------------------------------------------------------------
# Adjudicate (approve / deny)
# ---------------------------------------------------------------------------
@bp.post("/claims/<cid>/adjudicate")
def adjudicate(cid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_or_404(db.claims, cid, "Claim")
    body = get_json_body()
    decision = require_enum(body, "decision", {"APPROVE", "DENY"})

    # priority 5: state
    if claim["status"] != "IN_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "adjudicate only valid from IN_REVIEW")

    pol = db.policies.get(claim["policy_id"])

    if decision == "DENY":
        claim["denial_reason"] = body.get("reason")
        claim["deductible_applied_cents"] = 0
        claim["reimbursed_cents"] = 0
        claim["wellness_paid_cents"] = 0
        claim["status"] = "DENIED"
        db.bump(claim)
        return ok_object(claim, 200)

    # ---- APPROVE branch, ordered checks ----
    is_wellness = claim.get("claim_type") == "WELLNESS"

    # priority 7: waiting period (non-WELLNESS only)
    if not is_wellness:
        eff = db.parse_iso_dt(pol["effective_date"])
        coverage_start = db.add_days(eff, int(pol.get("waiting_period_days", 0)))
        incident = db.parse_iso_dt(claim["incident_date"])
        if incident < coverage_start:
            raise APIError(
                ERR_WITHIN_WAITING_PERIOD, 422, "incident_date within the waiting period"
            )

    # priority 8: pre-existing exclusion (non-WELLNESS only)
    if not is_wellness:
        cond = db.conditions.get(claim.get("condition_id"))
        if cond is not None:
            status = calculations.compute_exclusion_status(cond, pol)
            if status != "COVERED":
                raise APIError(
                    ERR_PRE_EXISTING_EXCLUDED, 422, "Referenced condition is PRE_EXISTING"
                )

    # priority 9: open policy-year covering incident_date
    py = ledger.find_covering_policy_year(pol["id"], claim["incident_date"])
    if py is None or py.get("status") != "OPEN":
        raise APIError(ERR_POLICY_YEAR_CLOSED, 422, "No OPEN PolicyYear covers incident_date")

    # priority 12: OCC on PolicyYear version
    expected = optional_int(body, "expected_policy_year_version", None)
    if expected is not None and expected != py.get("version"):
        raise APIError(
            ERR_STALE_POLICY_YEAR_VERSION, 412, "expected_policy_year_version is stale"
        )

    # run the coverage-year ledger
    claim["status"] = "APPROVED"
    ledger.reattribute(pol, py, claim)
    db.bump(claim)
    db.bump(py)
    return ok_object(claim, 200)


@bp.post("/claims/<cid>/pay")
def pay_claim(cid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "pay only valid from APPROVED")
    claim["status"] = "PAID"
    db.bump(claim)
    return ok_object(claim, 200)


@bp.post("/claims/<cid>/reverse")
def reverse_claim(cid):
    require_auth(["ClaimsAdjuster"])()
    claim = get_or_404(db.claims, cid, "Claim")
    if claim["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, 409, "reverse only valid from APPROVED")

    pol = db.policies.get(claim["policy_id"])
    py = ledger.find_covering_policy_year(pol["id"], claim["incident_date"])
    if py is None:
        raise APIError(ERR_POLICY_YEAR_CLOSED, 422, "No PolicyYear covers incident_date")

    body = get_json_body()
    expected = require_int(body, "expected_policy_year_version")
    if expected != py.get("version"):
        raise APIError(
            ERR_STALE_POLICY_YEAR_VERSION, 412, "expected_policy_year_version is stale"
        )

    # Compensation: move to DENIED, zero payable fields, then reconcile the year
    # from the remaining APPROVED/PAID claims (restoring pre-approval values).
    claim["status"] = "DENIED"
    claim["deductible_applied_cents"] = 0
    claim["reimbursed_cents"] = 0
    claim["wellness_paid_cents"] = 0
    claim["denial_reason"] = "ERR_CLAIM_REVERSED"
    ledger.reconcile_policy_year(pol, py)
    db.bump(claim)
    db.bump(py)
    return ok_object(claim, 200)
