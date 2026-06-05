"""AnnualReport routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required, parse_pagination, sort_by_created
from services import access, calculations, core, serialize

bp = Blueprint("annual_reports", __name__)


@bp.route("/business-entities/<be_id>/annual-reports", methods=["POST"])
def create_annual_report(be_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    be = access.get_business_entity_or_404(be_id)
    access.require_filer_owns(role, user_id, be["id"])

    if be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    body = parse_json_body_required()
    period_year = body.get("period_year")
    if isinstance(period_year, bool) or not isinstance(period_year, int):
        raise errors.err_invalid_request("period_year must be an integer.")
    if period_year < 2020 or period_year > 2099:
        raise errors.err_invalid_request("period_year must be in 2020..2099.")

    # Priority 70: uniqueness per (business_entity_id, period_year)
    for ar in core.children_annual_reports(be["id"]):
        if ar["period_year"] == period_year:
            raise errors.err_report_period_taken()

    # Provisional franchise tax
    provisional = calculations.franchise_tax_cents(
        be["formation_state_code"], be["entity_type"], be["revenue_band"]
    )

    ar = {
        "business_entity_id": be["id"],
        "period_year": period_year,
        "status": "DRAFT",
        "franchise_tax_amount_cents": provisional,
        "late_fee_cents": 0,
        "filed_at": None,
        "voided_at": None,
    }
    core.stamp_create_common(ar)
    db.annual_reports[ar["id"]] = ar
    return response.success_object(serialize.annual_report(ar), status=201)


@bp.route("/business-entities/<be_id>/annual-reports", methods=["GET"])
def list_annual_reports(be_id: str):
    middleware.require_auth(["Filer", "StateAdmin", "ComplianceOfficer"])
    be = access.get_business_entity_or_404(be_id)

    limit, offset = parse_pagination()
    st = request.args.get("status")
    py = request.args.get("period_year")
    items = core.children_annual_reports(be["id"])
    if st is not None:
        items = [x for x in items if x["status"] == st]
    if py is not None:
        try:
            py_int = int(py)
        except ValueError:
            raise errors.err_invalid_request("period_year filter must be an integer.")
        items = [x for x in items if x["period_year"] == py_int]
    items = sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_array([serialize.annual_report(x) for x in page],
                                  limit=limit, offset=offset, total_count=total)


@bp.route("/annual-reports/<ar_id>/file", methods=["POST"])
def file_annual_report(ar_id: str):
    role, user_id = middleware.require_auth(["Filer"])
    ar = access.get_annual_report_or_404(ar_id)
    access.require_filer_owns(role, user_id, ar["business_entity_id"])
    be = db.business_entities.get(ar["business_entity_id"])

    # Priority 40: state
    if ar["status"] not in ("DRAFT", "DELINQUENT"):
        raise errors.err_invalid_state(f"AnnualReport is in {ar['status']}; cannot file.")

    # Priority 45: dissolved parent
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    # Per §1.2 preconditions:
    # - compliance_posture != FROZEN OR status == SUSPENDED (cure path).
    # PRD §3.7: "Filing is permitted on a SUSPENDED parent because filing the
    # delinquent reports is the prerequisite cure for reinstatement."
    # So FROZEN is OK only when status == SUSPENDED.
    if be is not None:
        if be["compliance_posture"] == "FROZEN" and be["status"] != "SUSPENDED":
            raise errors.err_invalid_state("Cannot file against a FROZEN business entity.")

    # Exactly one ACTIVE RegisteredAgent (cross-entity gate)
    if be is not None and core.active_registered_agent_count(be["id"]) != 1:
        raise errors.err_invalid_state("Filing requires exactly one ACTIVE RegisteredAgent.")

    # Calculations
    now = db.now_utc()
    assessed = calculations.franchise_tax_cents(
        be["formation_state_code"], be["entity_type"], be["revenue_band"]
    )
    late_fee = calculations.late_fee_cents(be["formation_state_code"], ar["period_year"], now)

    # Priority 90: cumulative cap check (assessed + late_fee + existing < cap)
    prospective_total = be["cumulative_franchise_tax_paid_cents"] + assessed + late_fee
    if prospective_total >= calculations.CUMULATIVE_CAP_CENTS:
        raise errors.err_franchise_tax_cap_exceeded()

    ar["franchise_tax_amount_cents"] = assessed
    ar["late_fee_cents"] = late_fee
    ar["status"] = "FILED"
    ar["filed_at"] = db.iso_format(now)
    ar["_filed_at_dt"] = now
    core.stamp_update_common(ar)

    core.emit_event(be["id"], "REPORT_FILED", {
        "annual_report_id": ar["id"],
        "period_year": ar["period_year"],
        "franchise_tax_amount_cents": assessed,
        "late_fee_cents": late_fee,
    })

    # Cascade: recompute fiscal, possibly DELINQUENT -> ACTIVE.
    core.cascade_after_child_change(be)

    return response.success_object(serialize.annual_report(ar))


@bp.route("/annual-reports/<ar_id>/void", methods=["POST"])
def void_annual_report(ar_id: str):
    role, user_id = middleware.require_auth(["ComplianceOfficer"])
    ar = access.get_annual_report_or_404(ar_id)
    be = db.business_entities.get(ar["business_entity_id"])

    if ar["status"] != "FILED":
        raise errors.err_invalid_state(f"AnnualReport is in {ar['status']}; cannot void.")
    if be is not None and be["status"] == "DISSOLVED":
        raise errors.err_entity_dissolved()

    now = db.now_utc()
    ar["status"] = "VOIDED"
    ar["voided_at"] = db.iso_format(now)
    ar["_voided_at_dt"] = now
    core.stamp_update_common(ar)

    core.emit_event(be["id"], "REPORT_VOIDED", {
        "annual_report_id": ar["id"],
        "period_year": ar["period_year"],
    })

    # Recompute fiscal fields (Rule 9 invariant).
    if be is not None:
        core.recompute_be_fiscal_fields(be)
        core.recompute_be_posture(be)

    return response.success_object(serialize.annual_report(ar))
