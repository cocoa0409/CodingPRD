"""ForceAccountResource and Contract endpoints."""
from flask import Blueprint

from db import new_row, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.calc import procurement_compliance_review
from services.constants import CONTRACT_TYPES, EMPLOYEE_TYPES, RESOURCE_KINDS
from validate import body, present, v_bool, v_enum, v_id, v_instant, v_int, v_num, v_str

bp = Blueprint("resources", __name__)


# ---------------------------------------------------------------------------
# ForceAccountResource
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/force-account-resources", methods=["POST"])
def create_resource():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)

    applicant_id = v_id(payload, "applicant_id")
    resource_kind = v_enum(payload, "resource_kind", RESOURCE_KINDS)
    label = v_str(payload, "label")
    employee_type = v_enum(payload, "employee_type", EMPLOYEE_TYPES,
                           required=False, default=None)
    if resource_kind == "LABOR" and employee_type is None:
        fail("ERR_INVALID_REQUEST", "employee_type is required for LABOR resources")
    if resource_kind != "LABOR" and employee_type is not None:
        fail("ERR_INVALID_REQUEST", "employee_type must be null for EQUIPMENT resources")
    base_rate = v_int(payload, "base_hourly_rate_cents", required=False, default=0,
                      minimum=0)
    fringe = v_num(payload, "fringe_benefit_pct", required=False, default=0,
                   minimum=0, maximum=1)
    equipment_code = v_str(payload, "equipment_code", required=False, non_empty=False,
                           default=None)
    published = v_int(payload, "published_hourly_rate_cents", required=False,
                      default=0, minimum=0)
    schedule = v_int(payload, "schedule_hourly_rate_cents", required=False,
                     default=0, minimum=0)

    require("applicants", applicant_id)

    row = new_row("force_account_resources", {
        "applicant_id": applicant_id,
        "resource_kind": resource_kind,
        "label": label,
        "employee_type": employee_type,
        "base_hourly_rate_cents": base_rate,
        "fringe_benefit_pct": fringe,
        "equipment_code": equipment_code,
        "published_hourly_rate_cents": published,
        "schedule_hourly_rate_cents": schedule,
        "charged_hours_total": 0,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/force-account-resources", methods=["GET"])
def list_resources():
    authenticate(ALL_ROLES)
    return render_list("force_account_resources", {
        "applicant_id": "applicant_id",
        "resource_kind": "resource_kind",
    })


@bp.route(PREFIX + "/force-account-resources/<force_account_resource_id>",
          methods=["GET"])
def get_resource(force_account_resource_id):
    actor = authenticate(ALL_ROLES)
    row = find("force_account_resources", force_account_resource_id)
    if row is not None:
        check_scope(actor, row["applicant_id"])
    row = require("force_account_resources", force_account_resource_id)
    return respond(row)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@bp.route(PREFIX + "/contracts", methods=["POST"])
def create_contract():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_owner = payload.get("applicant_id")
    if isinstance(raw_owner, str):
        check_scope(actor, raw_owner)

    applicant_id = v_id(payload, "applicant_id")
    vendor_name = v_str(payload, "vendor_name")
    contract_type = v_enum(payload, "contract_type", CONTRACT_TYPES)
    award_amount_cents = v_int(payload, "award_amount_cents", minimum=0)
    awarded_at = v_instant(payload, "awarded_at")
    bids_received = v_int(payload, "bids_received", required=False, default=0, minimum=0)
    advertised = v_bool(payload, "advertised", required=False, default=False)
    sole_source = v_bool(payload, "sole_source_justification_on_file", required=False,
                         default=False)
    debarment = v_bool(payload, "debarment_check_completed", required=False,
                       default=False)

    require("applicants", applicant_id)

    row = new_row("contracts", {
        "applicant_id": applicant_id,
        "vendor_name": vendor_name,
        "contract_type": contract_type,
        "award_amount_cents": award_amount_cents,
        "bids_received": bids_received,
        "advertised": advertised,
        "sole_source_justification_on_file": sole_source,
        "debarment_check_completed": debarment,
        "awarded_at": awarded_at,
        "procurement_status": "PENDING_REVIEW",
        "noncompliance_reason": None,
        "allowed_cost_total_cents": 0,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/contracts", methods=["GET"])
def list_contracts():
    authenticate(ALL_ROLES)
    return render_list("contracts", {
        "applicant_id": "applicant_id",
        "procurement_status": "procurement_status",
        "contract_type": "contract_type",
    })


@bp.route(PREFIX + "/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    actor = authenticate(ALL_ROLES)
    row = find("contracts", contract_id)
    if row is not None:
        check_scope(actor, row["applicant_id"])
    row = require("contracts", contract_id)
    return respond(row)


@bp.route(PREFIX + "/contracts/<contract_id>/procurement-review", methods=["POST"])
def review_procurement(contract_id):
    authenticate(("ProgramSpecialist",))
    contract = require("contracts", contract_id)

    if contract["procurement_status"] != "PENDING_REVIEW":
        fail("ERR_CONTRACT_ALREADY_REVIEWED",
             "this contract has already been reviewed")

    status, reason = procurement_compliance_review(contract)
    setf(contract, "procurement_status", status)
    setf(contract, "noncompliance_reason", reason)
    touch(contract)
    return respond(contract)
