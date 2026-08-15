"""Collateral and UCCFiling endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from routes.loans import get_loan_or_404
from serialize import list_response, ser_collateral, ser_filing
from services.core import (collaterals_of_loan, compute_borrowing_base,
                           filings_of_collateral, recompute_borrowing_base,
                           standard_cascade, stamp_new, touch)
from util import (add_years, as_dt, as_enum, as_int, as_pos_int, as_str, body,
                  need, new_id, opt_int)

bp = Blueprint("collateral", __name__)

COLLATERAL_TYPES = ["CHATTEL_CROP", "EQUIPMENT", "REAL_ESTATE"]


def get_collateral_or_404(cid):
    c = STORE.collaterals.get(cid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "Collateral not found")
    return c


def get_filing_or_404(fid):
    f = STORE.filings.get(fid)
    if f is None:
        raise_err("ERR_NOT_FOUND", "UCC filing not found")
    return f


# ---------------------------------------------------------------------------
# Collateral
# ---------------------------------------------------------------------------

@bp.route("/collateral", methods=["POST"])
def create_collateral():
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    loan_account_id = as_str(need(b, "loan_account_id"), "loan_account_id")
    collateral_type = as_enum(need(b, "collateral_type"), "collateral_type", COLLATERAL_TYPES)
    description = as_str(need(b, "description"), "description")
    appraised = as_pos_int(need(b, "appraised_value_cents"), "appraised_value_cents")
    prior_lien = opt_int(b, "prior_lien_cents", 0, min_value=0)
    loan = STORE.loans.get(loan_account_id)
    if loan is None:
        raise_err("ERR_NOT_FOUND", "Loan account not found")
    c = stamp_new({
        "id": new_id(),
        "loan_account_id": loan["id"],
        "collateral_type": collateral_type,
        "description": description,
        "appraised_value_cents": appraised,
        "prior_lien_cents": prior_lien,
        "status": "PLEDGED",
    })
    STORE.collaterals[c["id"]] = c
    return ok_object(ser_collateral(c), code=201)


@bp.route("/collateral/<cid>", methods=["GET"])
def get_collateral(cid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_collateral(get_collateral_or_404(cid)))


@bp.route("/collateral", methods=["GET"])
def list_collateral():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.collaterals.values(), ser_collateral,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("collateral_type", lambda e: e["collateral_type"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/collateral/<cid>/appraise", methods=["POST"])
def appraise_collateral(cid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    appraised = as_pos_int(need(b, "appraised_value_cents"), "appraised_value_cents")
    expected = as_int(need(b, "expected_collateral_version"), "expected_collateral_version")
    c = get_collateral_or_404(cid)
    if expected != c["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_collateral_version does not match the collateral version")
    c["appraised_value_cents"] = appraised
    touch(c)
    loan = get_loan_or_404(c["loan_account_id"])
    recompute_borrowing_base(loan)
    standard_cascade(loan)
    return ok_object(ser_collateral(c))


@bp.route("/collateral/<cid>/release", methods=["POST"])
def release_collateral(cid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    c = get_collateral_or_404(cid)
    if c["status"] != "PLEDGED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only PLEDGED collateral can be released")
    loan = get_loan_or_404(c["loan_account_id"])
    recomputed = compute_borrowing_base(loan, exclude_collateral_id=c["id"])
    cap = loan["approved_commitment_cents"]
    headroom = recomputed if cap is None else min(cap, recomputed)
    if loan["outstanding_principal_cents"] > headroom:
        raise_err("ERR_RELEASE_WOULD_CREATE_DEFICIENCY",
                  "Release would push outstanding principal above coverage")
    c["status"] = "RELEASED"
    touch(c)
    for f in filings_of_collateral(c["id"]):
        if f["status"] in ("FILED", "CONTINUED"):
            f["status"] = "TERMINATED"
            touch(f)
    recompute_borrowing_base(loan)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_collateral(c))


# ---------------------------------------------------------------------------
# UCC filings
# ---------------------------------------------------------------------------

@bp.route("/ucc-filings", methods=["POST"])
def create_filing():
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    b = body()
    collateral_id = as_str(need(b, "collateral_id"), "collateral_id")
    filing_number = as_str(need(b, "filing_number"), "filing_number")
    jurisdiction = as_str(need(b, "jurisdiction"), "jurisdiction")
    filed_date = as_dt(need(b, "filed_date"), "filed_date")
    c = STORE.collaterals.get(collateral_id)
    if c is None:
        raise_err("ERR_NOT_FOUND", "Collateral not found")
    loan = get_loan_or_404(c["loan_account_id"])
    # filing_number unique across the association
    for f in STORE.filings.values():
        fc = STORE.collaterals.get(f["collateral_id"])
        if fc is None:
            continue
        floan = STORE.loans.get(fc["loan_account_id"])
        if floan is None:
            continue
        if floan["association_id"] == loan["association_id"] and f["filing_number"] == filing_number:
            raise_err("ERR_FILING_NUMBER_TAKEN",
                      "filing_number already exists within the association")
    f = stamp_new({
        "id": new_id(),
        "collateral_id": c["id"],
        "filing_number": filing_number,
        "jurisdiction": jurisdiction,
        "filed_date": filed_date,
        "lapse_date": add_years(filed_date, 5),
        "status": "FILED",
    })
    STORE.filings[f["id"]] = f
    recompute_borrowing_base(loan)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_filing(f), code=201)


@bp.route("/ucc-filings/<fid>", methods=["GET"])
def get_filing(fid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_filing(get_filing_or_404(fid)))


@bp.route("/ucc-filings", methods=["GET"])
def list_filings():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.filings.values(), ser_filing,
        [("collateral_id", lambda e: e["collateral_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/ucc-filings/<fid>/continue", methods=["POST"])
def continue_filing(fid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    f = get_filing_or_404(fid)
    if f["status"] not in ("FILED", "CONTINUED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a FILED or CONTINUED filing can be continued")
    clock = get_clock()
    window_start = f["lapse_date"] - timedelta(days=180)
    if not (window_start <= clock < f["lapse_date"]):
        raise_err("ERR_CONTINUATION_WINDOW_NOT_OPEN",
                  "Continuation is outside [lapse_date - 180 days, lapse_date)")
    f["status"] = "CONTINUED"
    f["lapse_date"] = add_years(f["lapse_date"], 5)
    touch(f)
    return ok_object(ser_filing(f))


@bp.route("/ucc-filings/<fid>/terminate", methods=["POST"])
def terminate_filing(fid):
    auth_uid, role = auth()
    require_role(role, ["LoanOfficer"])
    f = get_filing_or_404(fid)
    if f["status"] not in ("FILED", "CONTINUED"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a FILED or CONTINUED filing can be terminated")
    f["status"] = "TERMINATED"
    touch(f)
    c = get_collateral_or_404(f["collateral_id"])
    loan = get_loan_or_404(c["loan_account_id"])
    recompute_borrowing_base(loan)
    touch(loan)
    standard_cascade(loan)
    return ok_object(ser_filing(f))
