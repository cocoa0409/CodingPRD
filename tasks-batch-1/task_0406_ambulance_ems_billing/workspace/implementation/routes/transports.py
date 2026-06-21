"""Transport endpoints: import, lifecycle (documentation dimension), void,
charges list (PRD §3.3–§3.5)."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_AGENCY_SUSPENDED,
    ERR_DUPLICATE_RUN_NUMBER,
    ERR_INVALID_DOCUMENTATION_STATE,
    ERR_INVALID_BILLING_STATE,
    ERR_INVALID_ENUM,
    ERR_INVALID_LOADED_MILES,
    ERR_INVALID_REQUEST,
    ERR_PCS_AUTHORITY_REQUIRED,
    err,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
    touch,
)
from services.serialize import serialize, serialize_list
from services.transport import pcs_requirement, synthesize_charges

bp = Blueprint("transports", __name__)

ORIGIN_MODIFIERS = {"S", "H", "N", "R", "E", "P", "I"}
DESTINATION_MODIFIERS = {"H", "N", "R", "E", "P", "I", "X"}
LEVELS_OF_SERVICE = {"BLS", "ALS1", "ALS2", "SCT"}


@bp.route("/transports", methods=["POST"])
def import_transport():
    principal = authenticate()
    require_role(principal, ["Dispatcher"])
    body = get_json_body()

    # priority 4: body FK existence
    if body.get("agency_id") is not None:
        agency = resolve_fk(store.agencies, body["agency_id"])
    else:
        agency = None
    if body.get("patient_id") is not None:
        resolve_fk(store.patients, body["patient_id"])

    # priority 5: required fields present
    require_fields(
        body,
        ["agency_id", "patient_id", "run_number", "dispatch_iso",
         "origin_modifier", "destination_modifier", "loaded_miles"],
    )

    # priority 6: enum validity
    if body["origin_modifier"] not in ORIGIN_MODIFIERS:
        raise err(ERR_INVALID_ENUM, "Invalid origin_modifier")
    if body["destination_modifier"] not in DESTINATION_MODIFIERS:
        raise err(ERR_INVALID_ENUM, "Invalid destination_modifier")

    # priority 7: loaded_miles > 0
    loaded_miles = body["loaded_miles"]
    if not isinstance(loaded_miles, (int, float)) or isinstance(loaded_miles, bool):
        raise err(ERR_INVALID_REQUEST, "loaded_miles must be a number")
    if loaded_miles <= 0:
        raise err(ERR_INVALID_LOADED_MILES, "loaded_miles must be greater than zero")

    # priority 8: run_number unique per agency across non-VOID transports
    for t in store.transports.values():
        if (t["agency_id"] == body["agency_id"]
                and t["run_number"] == body["run_number"]
                and t["billing_status"] != "VOID"):
            raise err(ERR_DUPLICATE_RUN_NUMBER, "run_number already used for this agency")

    # priority 26: agency must be ACTIVE
    if agency["status"] != "ACTIVE":
        raise err(ERR_AGENCY_SUSPENDED, "Agency is suspended")

    rec = {
        "agency_id": body["agency_id"],
        "patient_id": body["patient_id"],
        "run_number": body["run_number"],
        "dispatch_iso": body["dispatch_iso"],
        "origin_modifier": body["origin_modifier"],
        "destination_modifier": body["destination_modifier"],
        "loaded_miles": loaded_miles,
        "is_rural_pickup": bool(body.get("is_rural_pickup", False)),
        "level_of_service": None,
        "emergency_indicator": bool(body.get("emergency_indicator", False)),
        "medical_necessity_met": False,
        "pcs_signed": False,
        "documentation_status": "IMPORTED",
        "billing_status": "UNBILLED",
        "total_billed_cents": 0,
        "total_allowed_cents": 0,
        "total_paid_cents": 0,
        "total_writeoff_cents": 0,
        "patient_responsibility_cents": 0,
        "balance_cents": 0,
    }
    init_common(rec)
    store.transports[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/transports/<transport_id>", methods=["GET"])
def get_transport(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher", "Coder", "Biller", "ComplianceOfficer"])
    rec = get_or_404(store.transports, transport_id)
    return success(serialize(rec), 200)


@bp.route("/transports", methods=["GET"])
def list_transports():
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher", "Coder", "Biller", "ComplianceOfficer"])
    limit, offset = parse_pagination()
    agency_id = request.args.get("agency_id")
    patient_id = request.args.get("patient_id")
    items = list(store.transports.values())
    if agency_id is not None:
        items = [t for t in items if t["agency_id"] == agency_id]
    if patient_id is not None:
        items = [t for t in items if t["patient_id"] == patient_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


# ---- Documentation lifecycle ----
@bp.route("/transports/<transport_id>/code", methods=["POST"])
def code_transport(transport_id):
    principal = authenticate()
    require_role(principal, ["Coder"])
    transport = get_or_404(store.transports, transport_id)
    body = get_json_body()
    require_fields(body, ["level_of_service"])
    if body["level_of_service"] not in LEVELS_OF_SERVICE:
        raise err(ERR_INVALID_ENUM, "Invalid level_of_service")

    # priority 9/10: coding admitted only from IMPORTED and only while UNBILLED.
    # Recode after billing started -> ERR_INVALID_DOCUMENTATION_STATE.
    if transport["billing_status"] != "UNBILLED":
        raise err(ERR_INVALID_DOCUMENTATION_STATE, "Cannot recode once billing has started")
    if transport["documentation_status"] != "IMPORTED":
        raise err(ERR_INVALID_DOCUMENTATION_STATE, "Transport is not in IMPORTED state")

    transport["level_of_service"] = body["level_of_service"]
    transport["documentation_status"] = "CODED"
    # synthesize_charges reconciles the ledger and applies the single version
    # bump for this coding mutation (PRD §2.5).
    synthesize_charges(transport)
    return success(serialize(transport), 200)


@bp.route("/transports/<transport_id>/attest-necessity", methods=["POST"])
def attest_necessity(transport_id):
    principal = authenticate()
    require_role(principal, ["Coder"])
    transport = get_or_404(store.transports, transport_id)
    # admitted from CODED or RETURNED.
    if transport["documentation_status"] not in ("CODED", "RETURNED"):
        raise err(ERR_INVALID_DOCUMENTATION_STATE, "Attestation not admitted from current state")
    transport["medical_necessity_met"] = True
    transport["documentation_status"] = "NECESSITY_REVIEW"
    touch(transport)
    return success(serialize(transport), 200)


@bp.route("/transports/<transport_id>/sign-pcs", methods=["POST"])
def sign_pcs(transport_id):
    principal = authenticate()
    require_role(principal, ["ComplianceOfficer"])
    transport = get_or_404(store.transports, transport_id)
    # priority 9: state admissibility (NECESSITY_REVIEW only)
    if transport["documentation_status"] != "NECESSITY_REVIEW":
        raise err(ERR_INVALID_DOCUMENTATION_STATE, "PCS signing not admitted from current state")
    # priority 12: acting staff must hold pcs_signature_authority
    staff = store.agency_staff.get(principal.user_id)
    if not staff or not staff.get("pcs_signature_authority"):
        raise err(ERR_PCS_AUTHORITY_REQUIRED, "Acting staff lacks PCS signature authority")

    if pcs_requirement(transport) == "REQUIRED":
        transport["pcs_signed"] = True
    transport["documentation_status"] = "DOCUMENTATION_COMPLETE"
    touch(transport)
    return success(serialize(transport), 200)


@bp.route("/transports/<transport_id>/return-documentation", methods=["POST"])
def return_documentation(transport_id):
    principal = authenticate()
    require_role(principal, ["ComplianceOfficer"])
    transport = get_or_404(store.transports, transport_id)
    if transport["documentation_status"] != "NECESSITY_REVIEW":
        raise err(ERR_INVALID_DOCUMENTATION_STATE, "Return not admitted from current state")
    transport["medical_necessity_met"] = False
    transport["documentation_status"] = "RETURNED"
    touch(transport)
    return success(serialize(transport), 200)


@bp.route("/transports/<transport_id>/void", methods=["POST"])
def void_transport(transport_id):
    principal = authenticate()
    require_role(principal, ["Biller"])
    transport = get_or_404(store.transports, transport_id)
    # priority 10: voidable only while UNBILLED.
    if transport["billing_status"] != "UNBILLED":
        raise err(ERR_INVALID_BILLING_STATE, "Transport is not voidable once billing has started")
    # delete synthesized charges; reset total_billed.
    to_delete = [cid for cid, c in store.charges.items() if c["transport_id"] == transport_id]
    for cid in to_delete:
        del store.charges[cid]
    transport["total_billed_cents"] = 0
    transport["balance_cents"] = 0
    transport["billing_status"] = "VOID"
    touch(transport)
    return success(serialize(transport), 200)


@bp.route("/transports/<transport_id>/charges", methods=["GET"])
def list_charges(transport_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Coder", "Biller", "ComplianceOfficer"])
    get_or_404(store.transports, transport_id)
    limit, offset = parse_pagination()
    items = [c for c in store.charges.values() if c["transport_id"] == transport_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
