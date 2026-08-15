"""TaxForm1099Filing endpoints."""

from flask import Blueprint, request

from db import store, new_id, parse_date
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_FILING, ERR_FILING_NOT_SUBMITTABLE,
    ERR_CORRECTION_REQUIRES_ACCEPTED, ERR_CONTRACTOR_NOT_VERIFIED,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_contractor_or_404,
    compute_reportable, compute_late_penalty, reconcile_lifetime,
)

bp = Blueprint("filings", __name__)

LINE_KINDS = {"SERVICE_FEE", "EXPENSE_REIMBURSEMENT"}


@bp.route("/api/filings", methods=["POST"])
def create_filing():
    require_auth(["TaxReportingSpecialist"])
    body = request.get_json(silent=True) or {}
    contractor_id = body.get("contractor_id")
    state_jurisdiction_id = body.get("state_jurisdiction_id")
    tax_year = body.get("tax_year")
    kind = body.get("kind", "ORIGINAL")
    corrects_filing_id = body.get("corrects_filing_id")
    payment_line_items = body.get("payment_line_items")

    if not isinstance(contractor_id, str) or not contractor_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "contractor_id is required")
    if not isinstance(state_jurisdiction_id, str) or not state_jurisdiction_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "state_jurisdiction_id is required")
    if (tax_year is None or not isinstance(tax_year, int) or isinstance(tax_year, bool)
            or tax_year < 2020 or tax_year > store.clock.year):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid tax_year")
    if kind not in ("ORIGINAL", "CORRECTION"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid kind")
    if kind == "CORRECTION" and not corrects_filing_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "corrects_filing_id required for CORRECTION")
    if kind == "ORIGINAL" and corrects_filing_id is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "corrects_filing_id must be null for ORIGINAL")
    if not isinstance(payment_line_items, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "payment_line_items must be a list")
    for item in payment_line_items:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid line item")
        amt = item.get("amount_cents")
        if not isinstance(amt, int) or isinstance(amt, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer")
        if item.get("kind") not in LINE_KINDS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid line item kind")
        if parse_date(item.get("payment_date")) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "payment_date must be an ISO date")

    get_contractor_or_404(contractor_id)
    jur = store.jurisdictions.get(state_jurisdiction_id)
    if jur is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Jurisdiction not found")
    if corrects_filing_id is not None and corrects_filing_id not in store.filings:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "corrects_filing_id filing not found")

    # uniqueness: one non-VOID, non-SUPERSEDED ORIGINAL per (contractor, year)
    if kind == "ORIGINAL":
        for f in store.filings.values():
            if (f["contractor_id"] == contractor_id and f["tax_year"] == tax_year
                    and f["kind"] == "ORIGINAL" and f["status"] not in ("VOID", "SUPERSEDED")):
                raise ApiError(ERR_DUPLICATE_FILING, 409,
                               "An ORIGINAL filing already exists for this contractor and year")

    reportable, federal, state = compute_reportable(
        tax_year, payment_line_items, jur["state_filing_threshold_cents"])

    filing = {
        "id": new_id(),
        "contractor_id": contractor_id,
        "state_jurisdiction_id": state_jurisdiction_id,
        "tax_year": tax_year,
        "kind": kind,
        "corrects_filing_id": corrects_filing_id,
        "payment_line_items": payment_line_items,
        "reportable_amount_cents": reportable,
        "federal_filing_required": federal,
        "state_filing_required": state,
        "signed_amount_cents": reportable,
        "filed_at": None,
        "days_late": 0,
        "penalty_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(filing)
    store.filings[filing["id"]] = filing
    return success(filing, status=201)


@bp.route("/api/filings", methods=["GET"])
def list_filings():
    require_auth(ALL_ROLES)
    items = list(store.filings.values())
    for key in ("contractor_id", "state_jurisdiction_id", "corrects_filing_id", "status"):
        v = request.args.get(key)
        if v:
            items = [f for f in items if f.get(key) == v]
    ty = request.args.get("tax_year")
    if ty is not None:
        try:
            tyi = int(ty)
            items = [f for f in items if f["tax_year"] == tyi]
        except ValueError:
            items = []
    items.sort(key=lambda f: f["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/filings/<fid>", methods=["GET"])
def get_filing(fid):
    require_auth(ALL_ROLES)
    f = store.filings.get(fid)
    if f is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Filing not found")
    return success(f)


@bp.route("/api/filings/<fid>/submit", methods=["POST"])
def submit_filing(fid):
    require_auth(["TaxReportingSpecialist"])
    f = store.filings.get(fid)
    if f is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Filing not found")
    if f["status"] not in ("DRAFT", "REJECTED_AGENCY"):
        raise ApiError(ERR_FILING_NOT_SUBMITTABLE, 409, "Filing is not submittable")

    contractor = store.contractors.get(f["contractor_id"])
    if contractor is None or contractor["verification_status"] != "VERIFIED":
        raise ApiError(ERR_CONTRACTOR_NOT_VERIFIED, 422, "Contractor is not VERIFIED")

    if f["kind"] == "CORRECTION":
        target = store.filings.get(f["corrects_filing_id"])
        if target is None or target["status"] != "ACCEPTED":
            raise ApiError(ERR_CORRECTION_REQUIRES_ACCEPTED, 409,
                           "Correction target must be ACCEPTED")

    f["status"] = "SUBMITTED"
    from db import now_iso
    if f["filed_at"] is None:
        f["filed_at"] = now_iso()
    days_late, penalty = compute_late_penalty(f["tax_year"], store.clock)
    f["days_late"] = days_late
    f["penalty_cents"] = penalty
    touch(f)

    if f["kind"] == "CORRECTION":
        target = store.filings.get(f["corrects_filing_id"])
        if target is not None and target["status"] == "ACCEPTED":
            target["status"] = "SUPERSEDED"
            touch(target)

    reconcile_lifetime(f["contractor_id"])
    return success(f)


@bp.route("/api/filings/<fid>/agency-response", methods=["POST"])
def agency_response(fid):
    require_auth(["TaxReportingSpecialist"])
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    if outcome not in ("ACCEPTED", "REJECTED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be ACCEPTED or REJECTED")
    f = store.filings.get(fid)
    if f is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Filing not found")
    if f["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "agency-response requires SUBMITTED")
    f["status"] = "ACCEPTED" if outcome == "ACCEPTED" else "REJECTED_AGENCY"
    touch(f)
    reconcile_lifetime(f["contractor_id"])
    return success(f)


@bp.route("/api/filings/<fid>/correct", methods=["POST"])
def correct_filing(fid):
    require_auth(["TaxReportingSpecialist"])
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    reason = body.get("reason")
    if mode != "VOID":
        raise ApiError(ERR_INVALID_REQUEST, 400, "mode must be VOID")
    if not reason or not isinstance(reason, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason is required")
    f = store.filings.get(fid)
    if f is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Filing not found")
    if f["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "VOID requires SUBMITTED or ACCEPTED")
    f["status"] = "VOID"
    touch(f)
    reconcile_lifetime(f["contractor_id"])
    return success(f)
