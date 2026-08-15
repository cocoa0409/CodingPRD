"""CustomerComplaint endpoints (PRD 3.5): parallel status/regulatory axes."""
from flask import Blueprint, request

from errors import (
    raise_error,
    ERR_COMPLAINT_NOT_RESOLVABLE,
    ERR_REPORT_NOT_REQUIRED,
    ERR_VALIDATION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.cascade import complaint_award_cascade
from services.core import new_record, public, touch
from util import add_days, parse_date, round_half_up_int, today
from validate import (
    get_body, opt_str, req_date, req_enum, req_int, require_path_resource, require_ref,
)

bp = Blueprint("complaints", __name__)

ALLEGATION_TYPES = ("FORGERY", "THEFT", "MISREPRESENTATION", "SUITABILITY",
                    "UNAUTHORIZED_TRADING", "OTHER")
# Allegation rates as exact fractions (numer, denom) for whole-cent round-half-up
ALLEGATION_RATE = {
    "FORGERY": (1, 1),
    "THEFT": (1, 1),
    "MISREPRESENTATION": (3, 5),        # 0.60
    "UNAUTHORIZED_TRADING": (1, 2),     # 0.50
    "SUITABILITY": (2, 5),              # 0.40
    "OTHER": (1, 4),                    # 0.25
}
REPORT_THRESHOLD_CENTS = 500000
AWARD_DISCLOSURE_THRESHOLD_CENTS = 150000
CAP_MULTIPLE = (5, 4)  # 1.25x claimed


def _provisional_reserve(allegation_type, damages_claimed_cents):
    numer, denom = ALLEGATION_RATE[allegation_type]
    return round_half_up_int(damages_claimed_cents * numer, denom)


def _reportable(allegation_type, damages_claimed_cents):
    return (damages_claimed_cents >= REPORT_THRESHOLD_CENTS
            or allegation_type in ("FORGERY", "THEFT"))


@bp.post("/complaints")
def create_complaint():
    authorized(["ComplianceAnalyst"])
    body = get_body()
    # Priority 3: FK existence
    rep = require_ref("representatives", body.get("rep_id"), "rep_id")
    # Priority 8: schema
    allegation_type = req_enum(body, "allegation_type", ALLEGATION_TYPES)
    damages = req_int(body, "damages_claimed_cents", non_negative=True)
    received_date = req_date(body, "received_date")
    description = opt_str(body, "description", default="")
    if rep is None:
        raise_error(ERR_VALIDATION, "missing or invalid field: rep_id")

    reportable = _reportable(allegation_type, damages)
    rec = new_record("complaints", {
        "rep_id": rep["id"],
        "allegation_type": allegation_type,
        "damages_claimed_cents": damages,
        "received_date": received_date,
        "description": description,
        "reportable": reportable,
        "report_deadline": add_days(parse_date(received_date), 30).isoformat(),
        "provisional_reserve_cents": _provisional_reserve(allegation_type, damages),
        "final_reserve_cents": None,
        "damages_paid_cents": None,
        "legal_cost_cents": None,
        "reported_at": None,
        "is_late_report": None,
        "status": "RECEIVED",
        "regulatory_status": "REQUIRED" if reportable else "NOT_REQUIRED",
    })
    return success_object(public(rec), status=201)


@bp.get("/complaints")
def list_complaints():
    return list_response("complaints", filters={
        "rep_id": request.args.get("rep_id"),
        "status": request.args.get("status"),
        "regulatory_status": request.args.get("regulatory_status"),
    })


@bp.get("/complaints/<rid>")
def get_complaint(rid):
    return get_one("complaints", rid)


@bp.patch("/complaints/<rid>")
def amend_complaint(rid):
    authorized(["ComplianceAnalyst"])
    complaint = require_path_resource("complaints", rid)
    if complaint["status"] != "RECEIVED":
        raise_error(ERR_COMPLAINT_NOT_RESOLVABLE,
                    "amendment is allowed only while the complaint is RECEIVED")
    body = get_body()
    damages = req_int(body, "damages_claimed_cents", non_negative=True)

    complaint["damages_claimed_cents"] = damages
    complaint["reportable"] = _reportable(complaint["allegation_type"], damages)
    complaint["provisional_reserve_cents"] = _provisional_reserve(
        complaint["allegation_type"], damages)
    # Regulatory axis recompute on every amendment while RECEIVED; FILED is
    # terminal for the regulatory axis and never flips back.
    if complaint["regulatory_status"] != "FILED":
        complaint["regulatory_status"] = ("REQUIRED" if complaint["reportable"]
                                          else "NOT_REQUIRED")
    touch(complaint)
    return success_object(public(complaint))


@bp.post("/complaints/<rid>/resolve")
def resolve_complaint(rid):
    authorized(["CompliancePrincipal"])
    complaint = require_path_resource("complaints", rid)
    if complaint["status"] != "RECEIVED":
        raise_error(ERR_COMPLAINT_NOT_RESOLVABLE,
                    "resolve requires a RECEIVED complaint")
    body = get_body()
    paid = req_int(body, "damages_paid_cents", non_negative=True)
    legal = req_int(body, "legal_cost_cents", non_negative=True)

    # Final variant: actual paid + legal, capped at 1.25x claimed (round-half-up)
    cap = round_half_up_int(complaint["damages_claimed_cents"] * CAP_MULTIPLE[0],
                            CAP_MULTIPLE[1])
    complaint["damages_paid_cents"] = paid
    complaint["legal_cost_cents"] = legal
    complaint["final_reserve_cents"] = min(paid + legal, cap)
    complaint["status"] = "RESOLVED"
    touch(complaint)

    if paid >= AWARD_DISCLOSURE_THRESHOLD_CENTS:
        complaint_award_cascade(complaint)
    return success_object(public(complaint))


@bp.post("/complaints/<rid>/report")
def report_complaint(rid):
    authorized(["CompliancePrincipal"])
    complaint = require_path_resource("complaints", rid)
    if complaint["regulatory_status"] != "REQUIRED":
        raise_error(ERR_REPORT_NOT_REQUIRED,
                    "report requires regulatory_status == REQUIRED")
    filed_date = today()
    complaint["reported_at"] = filed_date.isoformat()
    complaint["is_late_report"] = filed_date > parse_date(complaint["report_deadline"])
    complaint["regulatory_status"] = "FILED"
    touch(complaint)
    return success_object(public(complaint))
