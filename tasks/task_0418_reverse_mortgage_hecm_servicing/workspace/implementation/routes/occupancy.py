"""OccupancyCertification endpoints (§3.7). Cyclic state machine."""
from datetime import date

from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common
from services.clock import clock_date, parse_ymd

bp = Blueprint("occupancy", __name__)

ALL_READ = {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"}


def _add_years(d, n):
    """Add n whole years to a date, handling Feb-29 by clamping to Feb-28."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def _annual_window(origination_date_str, cert_year):
    """[start, end) for certification_year (1-based): year N window is
    [orig + (N-1) years, orig + N years)."""
    orig = parse_ymd(origination_date_str)
    start = _add_years(orig, cert_year - 1)
    end = _add_years(orig, cert_year)
    return start, end


@bp.route("/occupancy-certifications", methods=["POST"])
def create_cert():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "certification_year"])
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    cy = body["certification_year"]
    if isinstance(cy, bool) or not isinstance(cy, int) or cy < 1:
        raise errors.err(errors.ERR_INVALID_REQUEST, "certification_year must be >= 1")

    orig = loan.get("origination_date")
    if orig is None:
        # cannot compute the annual window before origination
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not yet originated")

    new_start, new_end = _annual_window(orig, cy)
    # at most one cert per (loan, certification_year); annual windows must not overlap
    for c in db.occupancy_certifications.values():
        if c["loan_id"] != loan["id"]:
            continue
        if c["certification_year"] == cy:
            raise errors.err(errors.ERR_CERT_PERIOD_OVERLAP, "Certification already exists for this year")
        c_start, c_end = _annual_window(orig, c["certification_year"])
        if new_start < c_end and c_start < new_end:
            raise errors.err(errors.ERR_CERT_PERIOD_OVERLAP, "Certification window overlaps an existing one")

    due = _add_years(parse_ymd(orig), cy).isoformat()
    rec = {
        "loan_id": loan["id"],
        "certification_year": cy,
        "due_date": due,
        "certified_at": None,
        "status": "PENDING",
    }
    db.stamp_create(rec)
    db.occupancy_certifications[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/occupancy-certifications/<cert_id>", methods=["GET"])
def get_cert(cert_id):
    _, role = get_user_context()
    require_role(role, ALL_READ)
    rec = db.occupancy_certifications.get(cert_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "OccupancyCertification not found")
    return success(public(rec))


@bp.route("/occupancy-certifications", methods=["GET"])
def list_certs():
    _, role = get_user_context()
    require_role(role, ALL_READ)
    limit, offset = common.parse_pagination()
    rows = list(db.occupancy_certifications.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


def _other_delinquent_exists(loan_id, exclude_id):
    for c in db.occupancy_certifications.values():
        if c["id"] == exclude_id:
            continue
        if c["loan_id"] == loan_id and c["status"] == "DELINQUENT":
            return True
    return False


@bp.route("/occupancy-certifications/<cert_id>/certify", methods=["POST"])
def certify(cert_id):
    user_id, role = get_user_context()
    require_role(role, {"Borrower", "ServicerOps"})
    rec = db.occupancy_certifications.get(cert_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "OccupancyCertification not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if role == "Borrower" and loan["borrower_id"] != user_id:
        raise errors.err(errors.ERR_FORBIDDEN_FOR_ROLE, "Borrower may only certify own loan")
    # certify is defined from PENDING and DELINQUENT
    if rec["status"] not in ("PENDING", "DELINQUENT"):
        raise errors.err(errors.ERR_INVALID_STATE, "Certification not in a certifiable state")
    # permitted only while loan not TERMINATED
    if loan["disposition_status"] == "TERMINATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Loan terminated")
    lender = db.lenders[loan["lender_id"]]
    rec["certified_at"] = lender["clock_utc"]
    rec["status"] = "CERTIFIED"
    db.touch(rec)
    # bubble-up: if no other DELINQUENT cert remains, servicing axis back to CURRENT
    if loan["servicing_status"] == "DELINQUENT_OCCUPANCY" and not _other_delinquent_exists(loan["id"], rec["id"]):
        loan["servicing_status"] = "CURRENT"
        db.touch(loan)
    return success(public(rec))


@bp.route("/occupancy-certifications/<cert_id>/mark-delinquent", methods=["POST"])
def mark_delinquent(cert_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps", "System"})
    rec = db.occupancy_certifications.get(cert_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "OccupancyCertification not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if rec["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Certification not PENDING")
    lender = db.lenders[loan["lender_id"]]
    if not (clock_date(lender) > parse_ymd(rec["due_date"])):
        raise errors.err(errors.ERR_INVALID_STATE, "Certification not past due")
    rec["status"] = "DELINQUENT"
    db.touch(rec)
    if loan["servicing_status"] == "CURRENT":
        loan["servicing_status"] = "DELINQUENT_OCCUPANCY"
        db.touch(loan)
    return success(public(rec))
