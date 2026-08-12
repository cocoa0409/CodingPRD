"""BMP inspections: schedule -> conduct -> close, with stop-work cascade."""
from flask import Blueprint

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_int, f_enum, f_date, bad_request, err, paginate, get_contract,
    get_inspection, check_transition,
)
from routes_contracts import suspend_contract

bp = Blueprint("inspections", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

INSPECTION_TYPES = {"PRE_HARVEST", "ACTIVE_HARVEST", "CLOSEOUT"}
SEVERITIES = {"MINOR", "MAJOR"}
INSPECTION_TERMINAL = {"COMPLIANT", "CORRECTIVE_VERIFIED"}


@bp.route("/forestry/inspections", methods=["POST"])
@require_roles("Forester")
def create_inspection():
    body = get_body()
    c_ref = body.get("contract_id")
    if isinstance(c_ref, str):
        get_contract(c_ref)
    check_known(body, {"contract_id", "inspection_type", "scheduled_date"})
    contract_id = f_str(body, "contract_id")
    get_contract(contract_id)
    itype = f_enum(body, "inspection_type", INSPECTION_TYPES)
    scheduled = f_date(body, "scheduled_date")
    ent = new_common({
        "contract_id": contract_id,
        "inspection_type": itype,
        "scheduled_date": scheduled,
        "status": "SCHEDULED",
        "severity": None,
        "remediation_cost_estimate_cents": 0,
        "findings": "",
    })
    db["inspections"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/inspections/<iid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_inspection_ep(iid):
    return success(pub(get_inspection(iid)), 200)


@bp.route("/forestry/inspections", methods=["GET"])
@require_roles(*READ_ROLES)
def list_inspections():
    page, meta = paginate(db["inspections"].values(), {
        "contract_id": "contract_id",
        "status": "status",
    })
    return success([pub(i) for i in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/inspections/<iid>/conduct", methods=["POST"])
@require_roles("AgencyInspector")
def conduct(iid):
    i = get_inspection(iid)
    body = get_body()
    check_known(body, set())
    check_transition(i, {"SCHEDULED"}, INSPECTION_TERMINAL, "inspection")
    i["status"] = "CONDUCTED"
    bump(i)
    return success(pub(i), 200)


@bp.route("/forestry/inspections/<iid>/close", methods=["POST"])
@require_roles("AgencyInspector")
def close(iid):
    i = get_inspection(iid)
    body = get_body()
    check_known(body, {"outcome", "severity",
                       "remediation_cost_estimate_cents", "findings"})
    outcome = f_enum(body, "outcome", {"COMPLIANT", "NONCOMPLIANT"})
    severity = f_enum(body, "severity", SEVERITIES, required=False)
    remediation = f_int(body, "remediation_cost_estimate_cents",
                        required=False, default=0, minv=0)
    findings = f_str(body, "findings", required=False, default="")
    if outcome == "NONCOMPLIANT" and severity is None:
        bad_request("severity is required when outcome is NONCOMPLIANT")
    if outcome == "COMPLIANT" and severity is not None:
        bad_request("severity must be omitted when outcome is COMPLIANT")
    check_transition(i, {"CONDUCTED"}, INSPECTION_TERMINAL, "inspection")
    i["status"] = outcome
    if outcome == "NONCOMPLIANT":
        i["severity"] = severity
        i["remediation_cost_estimate_cents"] = remediation
        i["findings"] = findings
    bump(i)
    # stop-work cascade: MAJOR finding on a HARVESTING contract
    if outcome == "NONCOMPLIANT" and severity == "MAJOR":
        contract = get_contract(i["contract_id"])
        if contract["status"] == "HARVESTING":
            suspend_contract(contract)
    return success(pub(i), 200)


@bp.route("/forestry/inspections/<iid>/verify-corrective", methods=["POST"])
@require_roles("AgencyInspector")
def verify_corrective(iid):
    i = get_inspection(iid)
    body = get_body()
    check_known(body, set())
    check_transition(i, {"NONCOMPLIANT"}, INSPECTION_TERMINAL, "inspection")
    i["status"] = "CORRECTIVE_VERIFIED"
    bump(i)
    return success(pub(i), 200)
