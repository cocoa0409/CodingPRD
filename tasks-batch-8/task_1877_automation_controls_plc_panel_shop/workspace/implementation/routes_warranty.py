"""Routes: warranty claims (provisional-to-final liability ledger)."""

from flask import Blueprint, request

from calc import warranty_liability
from core import (
    bump,
    envelope_object,
    err_inadmissible,
    err_invalid_request,
    err_invalid_state,
    err_not_owner,
    err_ref_not_found,
    err_warranty_expired,
    get_body,
    now_dt,
    now_iso,
    paginate,
    parse_iso,
    req_num,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_claim, get_job
from serializers import ser_warranty_claim
from store import db

bp = Blueprint("warranty", __name__)


def _check_warranty_window(job, filed_dt):
    """priority 12: filed_at <= warranty_expires_at; expiry must be non-null."""
    if job["warranty_expires_at"] is None:
        raise err_warranty_expired("Job is not yet commissioned (no warranty expiry).")
    if filed_dt > parse_iso(job["warranty_expires_at"]):
        raise err_warranty_expired("Claim is past the warranty window.")


@bp.route("/panel-shop/jobs/<job_id>/warranty-claims", methods=["POST"])
def file_claim(job_id):
    user_id, _ = require_roles("Customer")
    j = get_job(job_id)
    # priority 3: entity_backed Customer ownership
    if j["customer_id"] != user_id:
        raise err_not_owner("Customer does not own this job.")
    body = get_body()
    panel_id = body.get("panel_id")
    claimed_labor_hours = body.get("claimed_labor_hours")
    defect_description = body.get("defect_description")
    # priority 5: body-referenced FK
    if not isinstance(panel_id, str) or not panel_id:
        raise err_invalid_request("Missing or invalid required field: panel_id")
    panel = db.panels.get(panel_id)
    if panel is None:
        raise err_ref_not_found("panel_id does not reference an existing Panel.")
    filed_dt = now_dt()
    # priority 12: warranty window
    _check_warranty_window(j, filed_dt)
    # priority 19: admissibility
    has_commissioned = any(
        p["job_id"] == job_id and p["status"] == "COMMISSIONED" for p in db.panels.values()
    )
    if not has_commissioned:
        raise err_inadmissible("Job has no COMMISSIONED panel.")
    if isinstance(claimed_labor_hours, (int, float)) and not isinstance(claimed_labor_hours, bool):
        if claimed_labor_hours < 0:
            raise err_inadmissible("claimed_labor_hours must be >= 0.")
    # priority 22: shape
    if not isinstance(claimed_labor_hours, (int, float)) or isinstance(claimed_labor_hours, bool):
        raise err_invalid_request("claimed_labor_hours is required and must be numeric.")
    if not isinstance(defect_description, str) or not defect_description:
        raise err_invalid_request("Missing or invalid required field: defect_description")
    w = stamp_new(
        {
            "job_id": job_id,
            "panel_id": panel_id,
            "status": "FILED",
            "defect_description": defect_description,
            "filed_at": now_iso(),
            "_filed_dt": filed_dt,
            "claimed_labor_hours": claimed_labor_hours,
            "provisional_liability_cents": None,
            "final_liability_cents": None,
            "liability_delta_cents": None,
        }
    )
    db.warranty_claims[w["id"]] = w
    return envelope_object(ser_warranty_claim(w), 201)


@bp.route("/panel-shop/warranty-claims/<wc_id>", methods=["GET"])
def fetch_claim(wc_id):
    require_roles("ProjectManager", "QAManager", "Customer")
    return envelope_object(ser_warranty_claim(get_claim(wc_id)))


@bp.route("/panel-shop/warranty-claims", methods=["GET"])
def list_claims():
    require_roles("ProjectManager", "QAManager", "Customer")
    claims = list(db.warranty_claims.values())
    args = request.args
    if "job_id" in args:
        claims = [w for w in claims if w["job_id"] == args.get("job_id")]
    if "panel_id" in args:
        claims = [w for w in claims if w["panel_id"] == args.get("panel_id")]
    if "status" in args:
        claims = [w for w in claims if w["status"] == args.get("status")]
    return paginate(sorted_by_created(claims), ser_warranty_claim)


@bp.route("/panel-shop/warranty-claims/<wc_id>/triage", methods=["POST"])
def triage_claim(wc_id):
    require_roles("QAManager")
    w = get_claim(wc_id)
    if w["status"] != "FILED":
        raise err_invalid_state("WarrantyClaim is not FILED.")
    j = db.jobs[w["job_id"]]
    # triage re-checks the admissibility window at triage time (PRD §3.9: a
    # claim filed in-window but triaged after expiry is rejected)
    _check_warranty_window(j, now_dt())
    w["provisional_liability_cents"] = warranty_liability(w, "provisional")
    w["status"] = "TRIAGED"
    bump(w)
    return envelope_object(ser_warranty_claim(w))


@bp.route("/panel-shop/warranty-claims/<wc_id>/accept", methods=["POST"])
def accept_claim(wc_id):
    require_roles("QAManager")
    w = get_claim(wc_id)
    if w["status"] != "TRIAGED":
        raise err_invalid_state("WarrantyClaim is not TRIAGED.")
    w["final_liability_cents"] = warranty_liability(w, "final")
    w["liability_delta_cents"] = w["final_liability_cents"] - w["provisional_liability_cents"]
    w["status"] = "ACCEPTED"
    bump(w)
    return envelope_object(ser_warranty_claim(w))


@bp.route("/panel-shop/warranty-claims/<wc_id>/deny", methods=["POST"])
def deny_claim(wc_id):
    require_roles("QAManager")
    w = get_claim(wc_id)
    if w["status"] != "TRIAGED":
        raise err_invalid_state("WarrantyClaim is not TRIAGED.")
    w["final_liability_cents"] = 0
    w["liability_delta_cents"] = -w["provisional_liability_cents"]
    w["status"] = "DENIED"
    bump(w)
    return envelope_object(ser_warranty_claim(w))


@bp.route("/panel-shop/warranty-claims/<wc_id>/settle", methods=["POST"])
def settle_claim(wc_id):
    require_roles("ProjectManager")
    w = get_claim(wc_id)
    if w["status"] != "ACCEPTED":
        raise err_invalid_state("WarrantyClaim is not ACCEPTED.")
    w["status"] = "SETTLED"
    bump(w)
    return envelope_object(ser_warranty_claim(w))


@bp.route("/panel-shop/warranty-claims/<wc_id>/close", methods=["POST"])
def close_claim(wc_id):
    require_roles("ProjectManager")
    w = get_claim(wc_id)
    if w["status"] != "DENIED":
        raise err_invalid_state("WarrantyClaim is not DENIED.")
    w["status"] = "CLOSED"
    bump(w)
    return envelope_object(ser_warranty_claim(w))
