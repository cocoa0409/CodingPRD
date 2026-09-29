"""Loan facility endpoints (PRD 3.3)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("loans", __name__)

REPRICE_TRUST_STATUSES = ("FORMING", "FUNDING")


def _ratios(trust, principal_cents, rate_bps):
    """Rungs 58 and 59, computed together so the reported figures are stored."""
    prop = db.properties[trust["property_id"]]
    ltv_pct, ltv_ok = calc.loan_ltv(principal_cents, prop["appraised_value_cents"])
    dscr, dscr_ok = calc.loan_dscr(principal_cents, rate_bps, prop["annual_noi_cents"])
    if not ltv_ok:
        raise ApiError("ERR_LTV_LIMIT_EXCEEDED")
    if not dscr_ok:
        raise ApiError("ERR_DSCR_BELOW_MINIMUM")
    return ltv_pct, dscr


@bp.post("/loan-facilities")
def create_loan():
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    lender_name = middleware.req_str(payload, "lender_name")
    principal_cents = middleware.req_int(payload, "principal_cents", 1)
    rate_bps = middleware.req_int(payload, "rate_bps", 0)
    recourse_type = middleware.req_enum(payload, "recourse_type", C.RECOURSE_TYPES)
    maturity_on = middleware.req_dt(payload, "maturity_on")

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    if recourse_type != "NON_RECOURSE":
        raise ApiError("ERR_RECOURSE_DEBT_PROHIBITED")
    if domain.live_loan(trust) is not None:
        raise ApiError("ERR_MULTIPLE_LOANS_PROHIBITED")
    ltv_pct, dscr = _ratios(trust, principal_cents, rate_bps)

    row = db.new_row(db.loans, {
        "trust_id": trust["id"],
        "lender_name": lender_name,
        "principal_cents": principal_cents,
        "rate_bps": rate_bps,
        "recourse_type": recourse_type,
        "maturity_on": maturity_on,
        "ltv_pct": ltv_pct,
        "dscr": dscr,
        "repriced_count": 0,
        "funded_at": None,
        "status": "COMMITTED",
    })
    return created_response(db.serialize(row))


@bp.get("/loan-facilities/<loan_id>")
def get_loan(loan_id):
    return read_one("loan", C.READ_TRUST_SIDE, loan_id)


@bp.get("/loan-facilities")
def list_loans():
    return listing(db.loans, C.READ_TRUST_SIDE,
                   str_filters=("trust_id", "status", "recourse_type"))


@bp.post("/loan-facilities/<loan_id>/reprice")
def reprice_loan(loan_id):
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    principal_cents = middleware.req_int(payload, "principal_cents", 1)
    rate_bps = middleware.req_int(payload, "rate_bps", 0)
    recourse_type = middleware.req_enum(payload, "recourse_type", C.RECOURSE_TYPES)

    loan = domain.require("loan", loan_id)
    trust = db.trusts[loan["trust_id"]]
    domain.check_frozen(trust)

    if loan["status"] not in ("COMMITTED", "FUNDED"):
        raise ApiError("ERR_LOAN_INVALID_STATE")
    if loan["status"] == "FUNDED" or trust["status"] not in REPRICE_TRUST_STATUSES:
        raise ApiError("ERR_REFINANCING_PROHIBITED")
    if recourse_type != "NON_RECOURSE":
        raise ApiError("ERR_RECOURSE_DEBT_PROHIBITED")
    ltv_pct, dscr = _ratios(trust, principal_cents, rate_bps)

    # hop 1 — the facility itself
    loan["principal_cents"] = principal_cents
    loan["rate_bps"] = rate_bps
    loan["recourse_type"] = recourse_type
    loan["repriced_count"] = (loan["repriced_count"] or 0) + 1
    loan["ltv_pct"] = ltv_pct
    loan["dscr"] = dscr
    db.touch(loan)

    # hop 2 — the effective offering falls back to DRAFT and re-cuts its stack
    offering = domain.effective_offering(trust)
    if offering is not None:
        offering["status"] = "DRAFT"
        offering["ppm_version"] = offering["ppm_version"] + 1
        domain.pin_stack(offering)
        db.touch(offering)

        # hop 3 — reserved subscriptions need revising
        for sub in domain.subscriptions_of_offering(offering):
            if sub["status"] == "RESERVED":
                sub["status"] = "REVISION_REQUIRED"
                db.touch(sub)
        domain.recompute_offering_totals(offering)
        domain.recompute_boots(offering)
    return object_response(db.serialize(loan))


@bp.post("/loan-facilities/<loan_id>/fund")
def fund_loan(loan_id):
    middleware.actor([C.TRUSTEE])
    loan = domain.require("loan", loan_id)
    trust = db.trusts[loan["trust_id"]]

    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("FUNDING",))
    prop = db.properties[trust["property_id"]]
    if prop["status"] != "ACQUIRED":
        raise ApiError("ERR_PROPERTY_NOT_ACQUIRED")
    if loan["status"] != "COMMITTED":
        raise ApiError("ERR_LOAN_INVALID_STATE")
    if loan["recourse_type"] != "NON_RECOURSE":
        raise ApiError("ERR_RECOURSE_DEBT_PROHIBITED")
    _ratios(trust, loan["principal_cents"], loan["rate_bps"])

    loan["status"] = "FUNDED"
    loan["funded_at"] = clock.now()
    db.touch(loan)
    domain.book(trust, "LOAN_PROCEEDS", "OPERATING", loan["principal_cents"],
                "LOAN_FUNDING", memo="loan proceeds drawn at closing")
    domain.recompute_trust(trust, force=True)
    return object_response(db.serialize(loan))
