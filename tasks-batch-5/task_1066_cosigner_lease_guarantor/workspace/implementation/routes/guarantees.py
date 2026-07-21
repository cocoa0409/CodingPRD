"""Guarantee lifecycle, ledger, and claim filing (PRD 3.2, 3.4, 3.5, 3.6)."""
from datetime import timedelta

from flask import Blueprint, request, g

import db
from auth import require, body
from validation import (
    get_or_404, req_str, req_int, req_date, require_after, opt_bool,
)
from responses import success, list_response
from serializers import serialize
from errors import ApiError
from calculations import (
    per_month_coverage, guarantee_fee, rent_to_income_ratio, weighted,
)
from constants import RENT_INCOME_MAX, PROVISIONAL_TIER
from services import recompute_portfolio, terminate_agreements, append_ledger

bp = Blueprint("guarantees", __name__)

COVERAGE_STATUSES = {"ACTIVE", "RENEWAL_PENDING"}


def _windows_overlap(s1, e1, s2, e2):
    """Half-open [start, end) overlap test (PRD 3.4)."""
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.post("/guarantees")
@require("Underwriter")
def create_guarantee():
    b = body()
    # Existence (404) before well-formedness (422), left to right.
    if b.get("portfolio_id") is not None:
        get_or_404(db.portfolios, b["portfolio_id"])
    if b.get("applicant_id") is not None:
        get_or_404(db.applicants, b["applicant_id"])

    portfolio_id = req_str(b, "portfolio_id")
    applicant_id = req_str(b, "applicant_id")
    unit_id = req_str(b, "unit_id")
    monthly_rent = req_int(b, "monthly_rent_cents", positive=True)
    coverage_months = req_int(b, "coverage_months", lo=1, hi=12)
    term_months = req_int(b, "term_months", positive=True)
    start = req_date(b, "lease_start_date")
    end = req_date(b, "lease_end_date")
    require_after(start, end)

    pmc = per_month_coverage(monthly_rent)
    total_coverage = pmc * coverage_months
    provisional = guarantee_fee(total_coverage, term_months, PROVISIONAL_TIER)

    gu = {
        "portfolio_id": portfolio_id,
        "applicant_id": applicant_id,
        "landlord_id": None,
        "unit_id": unit_id,
        "monthly_rent_cents": monthly_rent,
        "coverage_months": coverage_months,
        "term_months": term_months,
        "lease_start_date": b["lease_start_date"],
        "lease_end_date": b["lease_end_date"],
        "per_month_coverage_cents": pmc,
        "total_coverage_cents": total_coverage,
        "remaining_coverage_cents": None,
        "paid_out_cents": 0,
        "risk_tier": None,
        "provisional_fee_cents": provisional,
        "final_fee_cents": None,
        "rent_to_income_ratio": None,
        "fee_paid": False,
        "underwritten_by_user_id": None,
        "renewal_count": 0,
        "status": "QUOTED",
    }
    db.stamp_common(gu)
    db.guarantees[gu["id"]] = gu
    return success(serialize(gu), 201)


@bp.get("/guarantees/<gid>")
@require("Underwriter", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin", "Landlord")
def get_guarantee(gid):
    gu = get_or_404(db.guarantees, gid)
    return success(serialize(gu), 200)


@bp.get("/guarantees")
@require("Underwriter", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin")
def list_guarantees():
    args = request.args
    items = list(db.guarantees.values())
    for key in ("applicant_id", "landlord_id", "portfolio_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return list_response(items, args)


# ---------------------------------------------------------------------------
# Approve / pay-fee / activate
# ---------------------------------------------------------------------------
@bp.post("/guarantees/<gid>/approve")
@require("Underwriter")
def approve_guarantee(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE")
    applicant = db.applicants[gu["applicant_id"]]
    if applicant["status"] != "VERIFIED":
        raise ApiError("ERR_APPLICANT_NOT_VERIFIED")

    ratio = rent_to_income_ratio(gu["monthly_rent_cents"], applicant["annual_income_cents"])
    if ratio >= RENT_INCOME_MAX:
        raise ApiError("ERR_RENT_TO_INCOME_EXCEEDED")

    tier = applicant["risk_tier"]
    portfolio = db.portfolios[gu["portfolio_id"]]
    projected = portfolio["risk_weighted_exposure_cents"] + weighted(gu["total_coverage_cents"], tier)
    if projected > portfolio["exposure_cap_cents"]:
        raise ApiError("ERR_EXPOSURE_CAP_EXCEEDED")

    gu["risk_tier"] = tier
    gu["rent_to_income_ratio"] = float(ratio)
    gu["final_fee_cents"] = guarantee_fee(gu["total_coverage_cents"], gu["term_months"], tier)
    gu["underwritten_by_user_id"] = g.user_id
    gu["status"] = "APPROVED"
    db.touch(gu)
    return success(serialize(gu), 200)


@bp.post("/guarantees/<gid>/pay-fee")
@require("Applicant", "PlatformAdmin")
def pay_fee(gid):
    gu = get_or_404(db.guarantees, gid)
    if g.role == "Applicant" and gu["applicant_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    b = body()
    amount = req_int(b, "amount_cents", positive=True)

    gu["fee_paid"] = True
    db.touch(gu)
    append_ledger(gu["id"], "FEE_CHARGED", amount, "CREDIT", None)
    return success(serialize(gu), 200)


@bp.post("/guarantees/<gid>/activate")
@require("Underwriter")
def activate_guarantee(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")

    # cross-entity referential: an ACTIVE agreement must exist
    has_active_agreement = any(
        ag["guarantee_id"] == gid and ag["status"] == "ACTIVE"
        for ag in db.agreements.values()
    )
    if not has_active_agreement:
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")

    # compliance hold
    open_review = any(
        cr["guarantee_id"] == gid and cr["status"] == "OPEN"
        for cr in db.compliance_reviews.values()
    )
    if open_review:
        raise ApiError("ERR_COMPLIANCE_HOLD")

    # temporal: applicant coverage overlap (half-open windows)
    s2 = db.parse_iso(gu["lease_start_date"])
    e2 = db.parse_iso(gu["lease_end_date"])
    for other in db.guarantees.values():
        if other["id"] == gid:
            continue
        if other["applicant_id"] != gu["applicant_id"]:
            continue
        if other["status"] not in COVERAGE_STATUSES:
            continue
        s1 = db.parse_iso(other["lease_start_date"])
        e1 = db.parse_iso(other["lease_end_date"])
        if _windows_overlap(s1, e1, s2, e2):
            raise ApiError("ERR_APPLICANT_COVERAGE_OVERLAP")

    # fiscal: fee paid
    if not gu["fee_paid"]:
        raise ApiError("ERR_FEE_NOT_PAID")

    gu["remaining_coverage_cents"] = gu["total_coverage_cents"]
    gu["paid_out_cents"] = 0
    gu["status"] = "ACTIVE"
    db.touch(gu)
    recompute_portfolio(db.portfolios[gu["portfolio_id"]])
    return success(serialize(gu), 200)


# ---------------------------------------------------------------------------
# Renew / confirm-renewal / declare-default / cancel
# ---------------------------------------------------------------------------
@bp.post("/guarantees/<gid>/renew")
@require("Underwriter")
def renew_guarantee(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    gu["fee_paid"] = False
    gu["status"] = "RENEWAL_PENDING"
    db.touch(gu)
    return success(serialize(gu), 200)


@bp.post("/guarantees/<gid>/confirm-renewal")
@require("Underwriter")
def confirm_renewal(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] != "RENEWAL_PENDING":
        raise ApiError("ERR_INVALID_STATE")
    if not gu["fee_paid"]:
        raise ApiError("ERR_FEE_NOT_PAID")

    gu["renewal_count"] += 1
    new_end = db.add_months(db.parse_iso(gu["lease_end_date"]), gu["term_months"])
    gu["lease_end_date"] = db.format_iso(new_end)
    gu["remaining_coverage_cents"] = gu["total_coverage_cents"]
    gu["paid_out_cents"] = 0
    gu["status"] = "ACTIVE"
    db.touch(gu)
    append_ledger(gu["id"], "COVERAGE_RESET", gu["total_coverage_cents"], "CREDIT",
                  gu["total_coverage_cents"])
    return success(serialize(gu), 200)


@bp.post("/guarantees/<gid>/declare-default")
@require("Underwriter", "ClaimsAdjuster")
def declare_default(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    gu["status"] = "DEFAULTED"
    db.touch(gu)

    applicant = db.applicants[gu["applicant_id"]]
    applicant["default_count"] += 1
    db.touch(applicant)

    # cascade link 2: applicant now has >= 1 default -> auto compliance review
    cr = {
        "guarantee_id": gid,
        "reason": "AUTO_DEFAULT_TRIGGER",
        "opened_by_user_id": None,
        "resolution_note": None,
        "status": "OPEN",
    }
    db.stamp_common(cr)
    db.compliance_reviews[cr["id"]] = cr

    terminate_agreements(gid, {"ACTIVE"})
    recompute_portfolio(db.portfolios[gu["portfolio_id"]])
    return success(serialize(gu), 200)


@bp.post("/guarantees/<gid>/cancel")
@require("Underwriter")
def cancel_guarantee(gid):
    gu = get_or_404(db.guarantees, gid)
    if gu["status"] not in ("QUOTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE")
    was_approved = gu["status"] == "APPROVED"
    gu["status"] = "CANCELLED"
    db.touch(gu)
    if was_approved:
        terminate_agreements(gid, {"SIGNED", "ACTIVE"})
    return success(serialize(gu), 200)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
@bp.get("/guarantees/<gid>/ledger-entries")
@require("Underwriter", "ClaimsAdjuster", "ComplianceOfficer", "PlatformAdmin")
def list_ledger(gid):
    get_or_404(db.guarantees, gid)
    items = [e for e in db.ledger_entries.values() if e["guarantee_id"] == gid]
    return list_response(items, request.args)


# ---------------------------------------------------------------------------
# File a claim (OCC-guarded) — PRD 3.6
# ---------------------------------------------------------------------------
@bp.post("/guarantees/<gid>/claims")
@require("Landlord")
def file_claim(gid):
    gu = get_or_404(db.guarantees, gid)
    # ownership
    if gu["landlord_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    b = body()
    expected_version = req_int(b, "expected_guarantee_version")
    default_dt = req_date(b, "default_date")
    missed_months = req_int(b, "missed_months", positive=True)
    acceleration = opt_bool(b, "acceleration_requested", False)

    # state
    if gu["status"] != "ACTIVE":
        raise ApiError("ERR_GUARANTEE_NOT_ACTIVE")

    # temporal: within notice_period_days of default_date
    agreement = next(
        (ag for ag in db.agreements.values()
         if ag["guarantee_id"] == gid and ag["status"] == "ACTIVE"),
        None,
    )
    if agreement is not None:
        window = timedelta(days=agreement["notice_period_days"])
        if db.get_clock() - default_dt > window:
            raise ApiError("ERR_CLAIM_WINDOW_CLOSED")

    # OCC
    if expected_version != gu["version"]:
        raise ApiError("ERR_STALE_GUARANTEE_VERSION")

    claim = {
        "guarantee_id": gid,
        "landlord_id": gu["landlord_id"],
        "default_date": b["default_date"],
        "missed_months": missed_months,
        "acceleration_requested": acceleration,
        "payout_variant": None,
        "payout_amount_cents": None,
        "status": "SUBMITTED",
    }
    db.stamp_common(claim)
    db.claims[claim["id"]] = claim

    # filing advances the guarantee's version by one
    db.touch(gu)
    return success(serialize(claim), 201)
