"""Routes: substitution requests (cyclic negotiation + approval cascade)."""

from flask import Blueprint, request

from calc import lead_time_delta, line_extended_cost, recompute_sccr, reevaluate_job_posture
from core import (
    bump,
    envelope_object,
    err_credit_hold,
    err_downrated,
    err_inactive,
    err_invalid_request,
    err_invalid_state,
    err_not_owner,
    err_ref_not_found,
    err_sod,
    err_unauthorized,
    get_body,
    paginate,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_panel, get_subreq, job_of_panel
from serializers import ser_substitution_request
from store import db

bp = Blueprint("substitutions", __name__)


def _owning_job(subreq):
    panel = db.panels[subreq["panel_id"]]
    return db.jobs[panel["job_id"]]


@bp.route("/panel-shop/panels/<panel_id>/substitution-requests", methods=["POST"])
def create_substitution(panel_id):
    user_id, _ = require_roles("DesignEngineer")
    get_panel(panel_id)
    body = get_body()
    original_line_id = body.get("original_line_id")
    proposed_component_id = body.get("proposed_component_id")
    # priority 5: body-referenced FKs
    if not isinstance(original_line_id, str) or not original_line_id:
        raise err_invalid_request("Missing or invalid required field: original_line_id")
    line = db.panel_components.get(original_line_id)
    if line is None or line["panel_id"] != panel_id:
        raise err_ref_not_found("original_line_id does not reference a BOM line of this panel.")
    if not isinstance(proposed_component_id, str) or not proposed_component_id:
        raise err_invalid_request("Missing or invalid required field: proposed_component_id")
    proposed = db.components.get(proposed_component_id)
    if proposed is None:
        raise err_ref_not_found("proposed_component_id does not reference an existing Component.")
    # priority 15: inactive proposed component
    if not proposed["active"]:
        raise err_inactive("Proposed component is inactive.")
    reason = req_str(body, "reason")
    s = stamp_new(
        {
            "panel_id": panel_id,
            "original_line_id": original_line_id,
            "proposed_component_id": proposed_component_id,
            "status": "REQUESTED",
            "reason": reason,
            "requested_by_id": user_id,
            "lead_time_delta_days": None,
            "sccr_impact_ka": None,
        }
    )
    db.substitution_requests[s["id"]] = s
    return envelope_object(ser_substitution_request(s), 201)


@bp.route("/panel-shop/substitution-requests/<sub_id>", methods=["GET"])
def fetch_substitution(sub_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "Customer")
    return envelope_object(ser_substitution_request(get_subreq(sub_id)))


@bp.route("/panel-shop/panels/<panel_id>/substitution-requests", methods=["GET"])
def list_panel_substitutions(panel_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "Customer")
    get_panel(panel_id)
    subs = [s for s in db.substitution_requests.values() if s["panel_id"] == panel_id]
    if "status" in request.args:
        subs = [s for s in subs if s["status"] == request.args.get("status")]
    return paginate(sorted_by_created(subs), ser_substitution_request)


@bp.route("/panel-shop/substitution-requests", methods=["GET"])
def list_substitutions():
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "Customer")
    subs = list(db.substitution_requests.values())
    args = request.args
    if "panel_id" in args:
        subs = [s for s in subs if s["panel_id"] == args.get("panel_id")]
    if "original_line_id" in args:
        subs = [s for s in subs if s["original_line_id"] == args.get("original_line_id")]
    if "proposed_component_id" in args:
        subs = [s for s in subs if s["proposed_component_id"] == args.get("proposed_component_id")]
    if "status" in args:
        subs = [s for s in subs if s["status"] == args.get("status")]
    return paginate(sorted_by_created(subs), ser_substitution_request)


@bp.route("/panel-shop/substitution-requests/<sub_id>/counter", methods=["POST"])
def counter_substitution(sub_id):
    user_id, _ = require_roles("Customer")
    s = get_subreq(sub_id)
    # priority 3: entity_backed Customer ownership of the owning chain
    if _owning_job(s)["customer_id"] != user_id:
        raise err_not_owner("Customer does not own this substitution request.")
    if s["status"] != "REQUESTED":
        raise err_invalid_state("SubstitutionRequest is not REQUESTED.")
    s["status"] = "COUNTERED"
    bump(s)
    return envelope_object(ser_substitution_request(s))


@bp.route("/panel-shop/substitution-requests/<sub_id>/resubmit", methods=["POST"])
def resubmit_substitution(sub_id):
    require_roles("DesignEngineer")
    s = get_subreq(sub_id)
    if s["status"] != "COUNTERED":
        raise err_invalid_state("SubstitutionRequest is not COUNTERED.")
    s["status"] = "REQUESTED"
    bump(s)
    return envelope_object(ser_substitution_request(s))


@bp.route("/panel-shop/substitution-requests/<sub_id>/approve", methods=["POST"])
def approve_substitution(sub_id):
    user_id, _ = require_roles("QAManager")
    s = get_subreq(sub_id)
    if s["status"] not in ("REQUESTED", "COUNTERED"):
        raise err_invalid_state("SubstitutionRequest is not in REQUESTED or COUNTERED.")
    # priority 8: approver must differ from requester
    if user_id == s["requested_by_id"]:
        raise err_sod("Approver must differ from the requester.")
    proposed = db.components[s["proposed_component_id"]]
    original_line = db.panel_components[s["original_line_id"]]
    original = db.components[original_line["component_id"]]
    # priority 10: SCCR downgrade guard (when both carry a rating)
    if proposed.get("sccr_ka") is not None and original.get("sccr_ka") is not None:
        if proposed["sccr_ka"] < original["sccr_ka"]:
            raise err_downrated("Proposed component would lower the SCCR chain.")
    # priority 15: proposed component must be active (PRD 3.3)
    if not proposed["active"]:
        raise err_inactive("Proposed component is inactive.")
    # priority 17: credit hold on the owning job's customer
    job = _owning_job(s)
    customer = db.customers[job["customer_id"]]
    if customer["credit_hold"]:
        raise err_credit_hold("Customer is on credit hold.")

    # --- approval cascade -------------------------------------------------
    panel = db.panels[s["panel_id"]]
    new_line = stamp_new(
        {
            "panel_id": panel["id"],
            "component_id": proposed["id"],
            "quantity": original_line["quantity"],
            "line_status": "SUBSTITUTED",
            "substituted_for_id": original_line["id"],
            "unit_cost_snapshot_cents": proposed["unit_cost_cents"],
            "extended_cost_cents": 0,
        }
    )
    new_line["extended_cost_cents"] = line_extended_cost(new_line)
    db.panel_components[new_line["id"]] = new_line
    # retire the original line from the active BOM
    if original_line["line_status"] in ("PENDING", "ORDERED"):
        original_line["line_status"] = "SUBSTITUTED"
        bump(original_line)
    # (RECEIVED originals stay RECEIVED for receipt audit but are excluded
    # from the rollup/SCCR input sets via the substituted_for_id rule)
    recompute_sccr(panel)
    s["sccr_impact_ka"] = panel["sccr_rating_ka"]
    s["lead_time_delta_days"] = lead_time_delta(proposed, original, job["status"])
    s["status"] = "APPROVED"
    bump(s)
    reevaluate_job_posture(job)
    return envelope_object(ser_substitution_request(s))


@bp.route("/panel-shop/substitution-requests/<sub_id>/reject", methods=["POST"])
def reject_substitution(sub_id):
    require_roles("QAManager")
    s = get_subreq(sub_id)
    if s["status"] != "REQUESTED":
        raise err_invalid_state("SubstitutionRequest is not REQUESTED.")
    s["status"] = "REJECTED"
    bump(s)
    return envelope_object(ser_substitution_request(s))


@bp.route("/panel-shop/substitution-requests/<sub_id>/withdraw", methods=["POST"])
def withdraw_substitution(sub_id):
    user_id, _ = require_roles("DesignEngineer")
    s = get_subreq(sub_id)
    if s["status"] != "REQUESTED":
        raise err_invalid_state("SubstitutionRequest is not REQUESTED.")
    # only the requester may withdraw
    if user_id != s["requested_by_id"]:
        raise err_unauthorized("Only the requesting DesignEngineer may withdraw this request.")
    s["status"] = "WITHDRAWN"
    bump(s)
    return envelope_object(ser_substitution_request(s))
