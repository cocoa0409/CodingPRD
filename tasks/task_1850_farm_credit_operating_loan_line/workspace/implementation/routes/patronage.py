"""PatronageDistribution endpoints (PRD 3.9) and MarginCallNotice endpoints."""
from datetime import datetime, timezone
from fractions import Fraction

from flask import Blueprint

from db import STORE, get_clock
from errors import raise_err
from middleware import ALL_ROLES, auth, require_role
from response import ok_list, ok_object
from serialize import list_response, ser_distribution, ser_notice
from services.core import (loans_of_borrower, notices_of_loan,
                           reevaluate_borrower, stamp_new, touch)
from util import as_int, as_pos_int, as_str, body, need, new_id

bp = Blueprint("patronage", __name__)

CAP_BP = 2500


def get_distribution_or_404(did):
    d = STORE.distributions.get(did)
    if d is None:
        raise_err("ERR_NOT_FOUND", "Patronage distribution not found")
    return d


@bp.route("/patronage-distributions", methods=["POST"])
def create_distribution():
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    b = body()
    association_id = as_str(need(b, "association_id"), "association_id")
    fiscal_year = as_int(need(b, "fiscal_year"), "fiscal_year")
    pool = as_pos_int(need(b, "pool_cents"), "pool_cents")
    assoc = STORE.associations.get(association_id)
    if assoc is None:
        raise_err("ERR_NOT_FOUND", "Association not found")
    if fiscal_year != get_clock().year - 1:
        raise_err("ERR_INVALID_FISCAL_YEAR",
                  "fiscal_year must equal current_fiscal_year - 1")
    for d in STORE.distributions.values():
        if d["association_id"] == association_id and d["fiscal_year"] == fiscal_year:
            raise_err("ERR_DISTRIBUTION_EXISTS",
                      "A distribution already exists for this association and fiscal year")
    dist = stamp_new({
        "id": new_id(),
        "association_id": association_id,
        "fiscal_year": fiscal_year,
        "pool_cents": pool,
        "allocated_cents": 0,
        "undistributed_cents": pool,
        "allocation_lines": [],
        "status": "DECLARED",
    })
    STORE.distributions[dist["id"]] = dist
    return ok_object(ser_distribution(dist), code=201)


@bp.route("/patronage-distributions/<did>", methods=["GET"])
def get_distribution(did):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return ok_object(ser_distribution(get_distribution_or_404(did)))


@bp.route("/patronage-distributions", methods=["GET"])
def list_distributions():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.distributions.values(), ser_distribution,
        [("association_id", lambda e: e["association_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


def fiscal_window(fiscal_year):
    start = datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


@bp.route("/patronage-distributions/<did>/allocate", methods=["POST"])
def allocate_distribution(did):
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    dist = get_distribution_or_404(did)
    if dist["status"] != "DECLARED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only a DECLARED distribution can be allocated")
    fy_start, fy_end = fiscal_window(dist["fiscal_year"])
    # Step 1: weights = APPLIED-repayment interest paid inside the FY window.
    weights = []  # (borrower, weight)
    for borrower in STORE.borrowers.values():
        if borrower["association_id"] != dist["association_id"]:
            continue
        if not borrower["patronage_eligible"] or borrower["status"] == "TERMINATED":
            continue
        loan_ids = {l["id"] for l in loans_of_borrower(borrower["id"])}
        w = sum(r["applied_interest_cents"] for r in STORE.repayments.values()
                if r["loan_account_id"] in loan_ids and r["status"] == "APPLIED"
                and fy_start <= r["created_at"] < fy_end)
        if w > 0:
            weights.append((borrower, w))
    total_weight = sum(w for _, w in weights)
    if total_weight == 0:
        raise_err("ERR_NO_ELIGIBLE_PATRONAGE_BASE",
                  "Total eligible interest weight is zero")
    pool = dist["pool_cents"]
    # Steps 2-3: exact rational raw shares, cap binds first (25% of interest paid).
    lines = []
    for borrower, w in weights:
        raw = Fraction(pool * w, total_weight)
        cap = Fraction(CAP_BP * w, 10000)
        binds = raw > cap
        capped = min(raw, cap)
        floor_i = capped.numerator // capped.denominator
        lines.append({
            "borrower_id": borrower["id"],
            "interest_paid_cents": w,
            "raw_share_cents": raw.numerator // raw.denominator,
            "final_share_cents": floor_i,
            "clawed_back": False,
            "_frac": raw - (raw.numerator // raw.denominator),
            "_binds": binds,
            "_seq": borrower["_seq"],
        })
    # Step 4: leftover cents go one at a time to uncapped lines ranked by
    # fractional part of the raw share DESC, tie-break borrower created_at ASC.
    leftover = pool - sum(l["final_share_cents"] for l in lines)
    uncapped = [l for l in lines if not l["_binds"] and l["_frac"] > 0]
    uncapped.sort(key=lambda l: (-l["_frac"], l["_seq"]))
    for l in uncapped:
        if leftover <= 0:
            break
        l["final_share_cents"] += 1
        leftover -= 1
    for l in lines:
        l.pop("_frac")
        l.pop("_binds")
        l.pop("_seq")
    dist["allocation_lines"] = lines
    dist["allocated_cents"] = sum(l["final_share_cents"] for l in lines)
    dist["undistributed_cents"] = pool - dist["allocated_cents"]
    dist["status"] = "ALLOCATED"
    touch(dist)
    return ok_object(ser_distribution(dist))


@bp.route("/patronage-distributions/<did>/pay", methods=["POST"])
def pay_distribution(did):
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    dist = get_distribution_or_404(did)
    if dist["status"] != "ALLOCATED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an ALLOCATED distribution can be paid")
    dist["status"] = "PAID"
    touch(dist)
    return ok_object(ser_distribution(dist))


@bp.route("/patronage-distributions/<did>/clawback", methods=["POST"])
def clawback_distribution(did):
    auth_uid, role = auth()
    require_role(role, ["AssociationBoard"])
    b = body()
    borrower_id = as_str(need(b, "borrower_id"), "borrower_id")
    dist = get_distribution_or_404(did)
    if STORE.borrowers.get(borrower_id) is None:
        raise_err("ERR_NOT_FOUND", "Borrower not found")
    if dist["status"] != "PAID":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Clawback applies only after payment")
    line = None
    for l in dist["allocation_lines"]:
        if l["borrower_id"] == borrower_id:
            line = l
            break
    if line is None:
        raise_err("ERR_NOT_FOUND", "No allocation line for this borrower")
    if line["clawed_back"]:
        raise_err("ERR_INVALID_STATE_TRANSITION", "Line already clawed back")
    line["clawed_back"] = True
    dist["allocated_cents"] -= line["final_share_cents"]
    dist["undistributed_cents"] += line["final_share_cents"]
    touch(dist)
    return ok_object(ser_distribution(dist))


# ---------------------------------------------------------------------------
# Margin call notices (system-created; only reads + escalate)
# ---------------------------------------------------------------------------

@bp.route("/margin-call-notices/<nid>", methods=["GET"])
def get_notice(nid):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    n = STORE.notices.get(nid)
    if n is None:
        raise_err("ERR_NOT_FOUND", "Margin call notice not found")
    return ok_object(ser_notice(n))


@bp.route("/margin-call-notices", methods=["GET"])
def list_notices():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    page, total, limit, offset, ser = list_response(
        STORE.notices.values(), ser_notice,
        [("loan_account_id", lambda e: e["loan_account_id"]),
         ("status", lambda e: e["status"])])
    return ok_list([ser(e) for e in page], limit, offset, total)


@bp.route("/margin-call-notices/<nid>/escalate", methods=["POST"])
def escalate_notice(nid):
    auth_uid, role = auth()
    require_role(role, ["CreditCommittee"])
    n = STORE.notices.get(nid)
    if n is None:
        raise_err("ERR_NOT_FOUND", "Margin call notice not found")
    if n["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only an ISSUED notice can be escalated")
    n["status"] = "ESCALATED"
    touch(n)
    loan = STORE.loans.get(n["loan_account_id"])
    if loan is not None and loan["status"] not in ("PAID_OFF", "CHARGED_OFF", "FORECLOSED"):
        loan["payment_posture"] = "DEFAULT"
        loan["consecutive_delinquent_reviews"] = 2
        reevaluate_borrower(loan["borrower_id"])
    return ok_object(ser_notice(n))
