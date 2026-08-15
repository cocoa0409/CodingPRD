"""RateSheet endpoints."""

from datetime import date

from flask import Blueprint

from db import STORE, today
from errors import (
    ApiError,
    ERR_DISCLOSURE_LEAD_TIME_UNMET,
    ERR_DEPLOYMENT_INCOMPLETE,
    ERR_DRAFT_SHEET_EXISTS,
    ERR_EFFECTIVE_WINDOW_OVERLAP,
    ERR_FUTURE_EFFECTIVE_DATE,
    ERR_MARGIN_BELOW_FLOOR,
    ERR_PRODUCT_NOT_FOUND,
    ERR_RATE_CAP_EXCEEDED,
    ERR_SHEET_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_TIER_STRUCTURE_INVALID,
    bad_request,
    not_found,
)
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import serialize, serialize_many
from services.cascade import activate_sheet, create_channel_rows
from services.funding import sheet_margin
from utils import (
    opt_date,
    opt_int,
    opt_str,
    req_date,
    req_field,
    req_int,
    req_list,
    req_str,
    stamp_new,
    bump,
)

bp = Blueprint("sheets", __name__)

SHEET_STATUSES = (
    "DRAFT", "COMMITTEE_REVIEW", "APPROVED", "SCHEDULED",
    "EFFECTIVE", "SUPERSEDED", "RETIRED",
)
MARGIN_VARIANTS = ("FORWARD_LOOKING", "REALIZED_BOOK")


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_tier_rows(tiers):
    """Schema-level tier row validation (400) — structure checked separately."""
    if not isinstance(tiers, list):
        raise bad_request("tiers must be an array")
    for t in tiers:
        if not isinstance(t, dict):
            raise bad_request("each tier must be an object")
        for f in ("tier_index", "lower_bound_cents", "upper_bound_cents",
                  "rate_bp", "projected_balance_cents"):
            if f not in t:
                raise bad_request(f"tier missing field: {f}")
            if not _is_int(t[f]):
                raise bad_request(f"tier field {f} must be an integer")
        if t["rate_bp"] < 0 or t["projected_balance_cents"] < 0:
            raise bad_request("tier rate_bp and projected_balance_cents must be >= 0")


def validate_tier_structure(tiers):
    """tier_index 0..n-1, first lower bound 0, ascending with no overlaps,
    positive-width bounded tiers, only the final tier unbounded (upper = -1)."""
    if len(tiers) == 0:
        raise ApiError(ERR_TIER_STRUCTURE_INVALID, 422, "tiers must be non-empty")
    n = len(tiers)
    for i, t in enumerate(tiers):
        if t["tier_index"] != i:
            raise ApiError(ERR_TIER_STRUCTURE_INVALID, 422,
                           "tier_index values must run 0..n-1")
    if tiers[0]["lower_bound_cents"] != 0:
        raise ApiError(ERR_TIER_STRUCTURE_INVALID, 422,
                       "first tier lower bound must be 0")
    for i, t in enumerate(tiers):
        lo, hi = t["lower_bound_cents"], t["upper_bound_cents"]
        if i > 0:
            prev_hi = tiers[i - 1]["upper_bound_cents"]
            if prev_hi != -1 and lo != prev_hi:
                raise ApiError(
                    ERR_TIER_STRUCTURE_INVALID, 422,
                    "each tier's lower bound must equal the previous tier's "
                    "upper bound (contiguous tiling, no gaps or overlaps)")
        if i < n - 1:
            if hi == -1 or hi <= lo:
                raise ApiError(ERR_TIER_STRUCTURE_INVALID, 422,
                               "only the final tier may be unbounded")
        else:
            if hi != -1:
                raise ApiError(ERR_TIER_STRUCTURE_INVALID, 422,
                               "final tier must be unbounded (upper_bound_cents = -1)")


def validate_tier_cap(product, tiers):
    for t in tiers:
        if t["rate_bp"] > product["rate_cap_bp"]:
            raise ApiError(ERR_RATE_CAP_EXCEEDED, 422,
                           "tier rate_bp exceeds product.rate_cap_bp")


def get_sheet_or_404(sheet_id):
    sheet = STORE["sheets"].get(sheet_id)
    if sheet is None:
        raise not_found("Rate sheet not found")
    return sheet


@bp.post("/rate-sheets")
@require_roles("PricingAnalyst")
def create_sheet():
    data = get_body()
    product_id = req_str(data, "product_id")
    market_code = req_str(data, "market_code")
    effective_date = req_date(data, "effective_date")
    end_date = opt_date(data, "end_date", "9999-12-31")
    disclosure_lead_days = req_int(data, "disclosure_lead_days", minimum=0)
    margin_floor_bp = req_int(data, "margin_floor_bp", minimum=0)
    source_scan_id = opt_str(data, "source_scan_id", None)
    tiers = req_list(data, "tiers")
    validate_tier_rows(tiers)
    product = STORE["products"].get(product_id)
    if product is None:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 422, "Referenced product_id does not exist")
    # Business order (PRD 2.10): one-draft-per-pair, then tier structure, then cap.
    for s in STORE["sheets"].values():
        if (s["product_id"] == product_id and s["market_code"] == market_code
                and s["status"] == "DRAFT"):
            raise ApiError(ERR_DRAFT_SHEET_EXISTS, 409,
                           "A DRAFT sheet already exists for this product+market")
    validate_tier_structure(tiers)
    validate_tier_cap(product, tiers)
    version_no = sum(
        1 for s in STORE["sheets"].values()
        if s["product_id"] == product_id and s["market_code"] == market_code
    ) + 1
    row = {
        "product_id": product_id,
        "market_code": market_code,
        "sheet_version": version_no,
        "effective_date": effective_date,
        "end_date": end_date,
        "disclosure_lead_days": disclosure_lead_days,
        "margin_floor_bp": margin_floor_bp,
        "source_scan_id": source_scan_id,
        "supersedes_sheet_id": None,
        "tiers": tiers,
        "total_projected_balance_cents": sum(t["projected_balance_cents"] for t in tiers),
        "status": "DRAFT",
    }
    stamp_new(row)
    STORE["sheets"][row["id"]] = row
    # Auto-create the pair's RepricingCycle at the 30-day default cadence.
    if not any(
        c["product_id"] == product_id and c["market_code"] == market_code
        for c in STORE["cycles"].values()
    ):
        cyc = {
            "product_id": product_id,
            "market_code": market_code,
            "cadence_days": 30,
            "last_reviewed_at": None,
        }
        stamp_new(cyc)
        STORE["cycles"][cyc["id"]] = cyc
    return ok_object(serialize("sheets", row), 201)


@bp.get("/rate-sheets")
@require_roles("PricingAnalyst", "PricingCommittee", "BranchBanker", "ComplianceOfficer")
def list_sheets():
    status = query_enum("status", SHEET_STATUSES)
    from flask import request
    product_id = request.args.get("product_id")
    market_code = request.args.get("market_code")
    supersedes = request.args.get("supersedes_sheet_id")
    source_scan = request.args.get("source_scan_id")
    rows = list(STORE["sheets"].values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if market_code is not None:
        rows = [r for r in rows if r["market_code"] == market_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if supersedes is not None:
        rows = [r for r in rows if r["supersedes_sheet_id"] == supersedes]
    if source_scan is not None:
        rows = [r for r in rows if r["source_scan_id"] == source_scan]
    return paginate(serialize_many("sheets", rows))


@bp.get("/rate-sheets/<sheet_id>")
@require_roles("PricingAnalyst", "PricingCommittee", "BranchBanker", "ComplianceOfficer")
def get_sheet(sheet_id):
    return ok_object(serialize("sheets", get_sheet_or_404(sheet_id)))


@bp.patch("/rate-sheets/<sheet_id>")
@require_roles("PricingAnalyst")
def patch_sheet(sheet_id):
    data = get_body()
    expected = req_int(data, "expected_sheet_version")
    disclosure_lead_days = opt_int(data, "disclosure_lead_days", None, minimum=0)
    margin_floor_bp = opt_int(data, "margin_floor_bp", None, minimum=0)
    effective_date = opt_date(data, "effective_date", None)
    end_date = opt_date(data, "end_date", None)
    tiers = data.get("tiers")
    if tiers is not None:
        validate_tier_rows(tiers)
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] != "DRAFT":
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       "Only a DRAFT sheet may be edited")
    if expected != sheet["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_sheet_version does not match the current version")
    if tiers is not None:
        product = STORE["products"][sheet["product_id"]]
        validate_tier_structure(tiers)
        validate_tier_cap(product, tiers)
        sheet["tiers"] = tiers
        sheet["total_projected_balance_cents"] = sum(
            t["projected_balance_cents"] for t in tiers
        )
    if disclosure_lead_days is not None:
        sheet["disclosure_lead_days"] = disclosure_lead_days
    if margin_floor_bp is not None:
        sheet["margin_floor_bp"] = margin_floor_bp
    if effective_date is not None:
        sheet["effective_date"] = effective_date
    if end_date is not None:
        sheet["end_date"] = end_date
    bump(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.post("/rate-sheets/<sheet_id>/submit")
@require_roles("PricingAnalyst")
def submit_sheet(sheet_id):
    get_body()
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] != "DRAFT":
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       "Only a DRAFT sheet may be submitted")
    # Business order (PRD 2.10): tier structure, then funding curve, then floor.
    validate_tier_structure(sheet["tiers"])
    if sheet["margin_floor_bp"] > 0:
        # sheet_margin raises ERR_NO_FUNDING_CURVE when no operative curve covers
        # the product tenor; then the floor check (equality passes).
        result = sheet_margin(sheet, "FORWARD_LOOKING")
        if result["margin_bp"] < sheet["margin_floor_bp"]:
            raise ApiError(ERR_MARGIN_BELOW_FLOOR, 422,
                           "FORWARD_LOOKING margin below margin_floor_bp")
    sheet["status"] = "COMMITTEE_REVIEW"
    bump(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.post("/rate-sheets/<sheet_id>/review-decision")
@require_roles("PricingCommittee")
def review_decision(sheet_id):
    data = get_body()
    decision = req_field(data, "decision")
    if decision not in ("APPROVE", "RETURN"):
        raise bad_request("decision must be APPROVE or RETURN")
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] == "COMMITTEE_REVIEW":
        sheet["status"] = "APPROVED" if decision == "APPROVE" else "DRAFT"
    elif sheet["status"] == "APPROVED":
        if decision != "RETURN":
            raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                           "No APPROVE transition from APPROVED")
        sheet["status"] = "COMMITTEE_REVIEW"
    elif sheet["status"] == "SCHEDULED":
        if decision != "RETURN":
            raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                           "No APPROVE transition from SCHEDULED")
        sheet["status"] = "APPROVED"
        # Unwind scheduling artifacts.
        doomed_d = [d["id"] for d in STORE["deployments"].values()
                    if d["sheet_id"] == sheet["id"] and d["status"] in ("PENDING", "FAILED")]
        for did in doomed_d:
            del STORE["deployments"][did]
        doomed_n = [n["id"] for n in STORE["notices"].values()
                    if n["sheet_id"] == sheet["id"] and n["status"] == "PENDING"]
        for nid in doomed_n:
            del STORE["notices"][nid]
    else:
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       f"No review decision possible from {sheet['status']}")
    bump(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.post("/rate-sheets/<sheet_id>/schedule")
@require_roles("PricingAnalyst")
def schedule_sheet(sheet_id):
    get_body()
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] != "APPROVED":
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       "Only an APPROVED sheet may be scheduled")
    s1 = date.fromisoformat(sheet["effective_date"])
    e1 = date.fromisoformat(sheet["end_date"])
    for other in STORE["sheets"].values():
        if other["id"] == sheet["id"]:
            continue
        if (other["product_id"] != sheet["product_id"]
                or other["market_code"] != sheet["market_code"]):
            continue
        s2 = date.fromisoformat(other["effective_date"])
        e2 = date.fromisoformat(other["end_date"])
        overlaps = s1 < e2 and s2 < e1  # half-open; adjacency never overlaps
        if not overlaps:
            continue
        if other["status"] == "SCHEDULED":
            raise ApiError(ERR_EFFECTIVE_WINDOW_OVERLAP, 409,
                           "Window overlaps a SCHEDULED sheet for the pair")
        if other["status"] == "EFFECTIVE" and not (s1 > s2):
            raise ApiError(ERR_EFFECTIVE_WINDOW_OVERLAP, 409,
                           "Overlap with the EFFECTIVE sheet requires chronological "
                           "succession (effective_date strictly later)")
    create_channel_rows(sheet)
    sheet["status"] = "SCHEDULED"
    bump(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.post("/rate-sheets/<sheet_id>/activate")
@require_roles("PricingAnalyst")
def activate(sheet_id):
    get_body()
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] != "SCHEDULED":
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       "Only a SCHEDULED sheet may be activated")
    # Gate order (PRD 2.10): disclosure, then deployment, then date.
    for n in STORE["notices"].values():
        if n["sheet_id"] != sheet["id"] or n["notice_type"] != "PRE_CHANGE":
            continue
        if n["status"] == "WAIVED":
            continue
        if n["status"] == "SENT" and not n["is_late"]:
            continue
        raise ApiError(ERR_DISCLOSURE_LEAD_TIME_UNMET, 409,
                       "Every PRE_CHANGE notice must be SENT on time or WAIVED")
    deployments = [d for d in STORE["deployments"].values()
                   if d["sheet_id"] == sheet["id"]]
    if len(deployments) < 4 or any(d["status"] != "DEPLOYED" for d in deployments):
        raise ApiError(ERR_DEPLOYMENT_INCOMPLETE, 409,
                       "All 4 channel deployments must be DEPLOYED")
    if today() < date.fromisoformat(sheet["effective_date"]):
        raise ApiError(ERR_FUTURE_EFFECTIVE_DATE, 409,
                       "Logical today is before the sheet's effective_date")
    activate_sheet(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.post("/rate-sheets/<sheet_id>/retire")
@require_roles("PricingCommittee")
def retire_sheet(sheet_id):
    get_body()
    sheet = get_sheet_or_404(sheet_id)
    if sheet["status"] not in ("DRAFT", "EFFECTIVE", "SUPERSEDED"):
        raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                       f"Cannot retire a sheet in {sheet['status']}")
    for a in STORE["accounts"].values():
        if a["sheet_id"] == sheet["id"]:
            raise ApiError(ERR_SHEET_INVALID_STATE, 409,
                           "Accounts still reference this sheet")
    sheet["status"] = "RETIRED"
    bump(sheet)
    return ok_object(serialize("sheets", sheet))


@bp.get("/rate-sheets/<sheet_id>/margin-analysis")
@require_roles("PricingAnalyst", "PricingCommittee", "TreasuryOfficer")
def margin_analysis(sheet_id):
    from flask import request
    variant = request.args.get("variant", "FORWARD_LOOKING")
    if variant not in MARGIN_VARIANTS:
        raise bad_request("variant must be FORWARD_LOOKING or REALIZED_BOOK")
    sheet = get_sheet_or_404(sheet_id)
    return ok_object(sheet_margin(sheet, variant))
