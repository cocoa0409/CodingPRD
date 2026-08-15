"""Warranty registrations and parts claims."""
import uuid
from datetime import timedelta
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_DUPLICATE, ERR_WINDOW_EXPIRED, \
    ERR_WARRANTY_NOT_ACTIVE, ERR_REVISION_LIMIT, invalid_state, invalid_request
from middleware import authenticate, authorize, require_owner
from response import success
from serializers import warranty_registration as ser_reg, parts_claim as ser_claim
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_int, \
    get_datetime, touch, is_int
from routes.common import body, get_path, get_ref, new_common, list_response

bp = Blueprint("warranty", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "WarrantyProcessor"}


@bp.post("/warranty-registrations")
def create_registration():
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"serial_number", "equipment_model_id",
                                "contractor_id", "order_id", "install_date"},
                         struct)
    serial_number = get_str(data, "serial_number", struct)
    equipment_model_id = get_str(data, "equipment_model_id", struct)
    contractor_id = get_str(data, "contractor_id", struct)
    order_id = get_str(data, "order_id", struct)
    install_date = get_datetime(data, "install_date", struct)

    # Body FK existence (priority 4).
    if isinstance(equipment_model_id, str):
        get_ref(db.equipment_models, equipment_model_id, "equipment_model_id")
    if isinstance(contractor_id, str):
        get_ref(db.contractors, contractor_id, "contractor_id")
    order = None
    if isinstance(order_id, str):
        order = get_ref(db.orders, order_id, "order_id")

    if isinstance(contractor_id, str):
        require_owner(contractor_id, role, user_id)

    # The order must be DELIVERED at registration-create time (state, p5).
    if order is not None and order["status"] != "DELIVERED":
        raise invalid_state("The referenced order is not DELIVERED")

    # Uniqueness (priority 14).
    if isinstance(serial_number, str):
        for w in db.warranty_registrations.values():
            if w["serial_number"] == serial_number:
                raise ApiError(ERR_DUPLICATE, 409, "serial_number already exists")

    # install_date may not lie in the future relative to the logical clock
    # (structural family — evaluated after the business checks above).
    if install_date is not None and install_date > clock.now():
        struct.add("install_date may not be in the future")
    struct.raise_if_bad()

    w = new_common()
    w.update({
        "serial_number": serial_number,
        "equipment_model_id": equipment_model_id,
        "contractor_id": contractor_id,
        "order_id": order_id,
        "install_date": install_date,
        "registration_deadline": install_date + timedelta(days=60),
        "registered_at": None,
        "extended_coverage_years": 5,
        "status": "PENDING_REGISTRATION",
    })
    db.warranty_registrations[w["id"]] = w
    return success(ser_reg(w), 201)


@bp.get("/warranty-registrations/<wid>")
def get_registration(wid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    w = get_path(db.warranty_registrations, wid)
    require_owner(w["contractor_id"], role, user_id)
    return success(ser_reg(w))


@bp.get("/warranty-registrations")
def list_registrations():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"contractor_id": request.args.get("contractor_id"),
               "order_id": request.args.get("order_id"),
               "equipment_model_id": request.args.get("equipment_model_id"),
               "status": request.args.get("status")}
    return list_response(db.warranty_registrations.values(), ser_reg, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)


@bp.post("/warranty-registrations/<wid>/register")
def register(wid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    w = get_path(db.warranty_registrations, wid)
    require_owner(w["contractor_id"], role, user_id)
    # A registration attempted after its deadline is WINDOW_EXPIRED — this
    # covers both a still-PENDING record past the deadline and one the lazy
    # sweep already lapsed (LAPSED only ever results from the deadline
    # passing). REGISTERED / VOID remain plain state violations.
    if w["status"] == "LAPSED":
        raise ApiError(ERR_WINDOW_EXPIRED, 422,
                       "Registration deadline has passed")
    if w["status"] != "PENDING_REGISTRATION":
        raise invalid_state("Only a PENDING_REGISTRATION record may register")
    # Inclusive deadline boundary: clock <= registration_deadline succeeds.
    if clock.now() > w["registration_deadline"]:
        # The lapse takes effect and denies open claims.
        w["status"] = "LAPSED"
        touch(w)
        core.deny_open_claims_for_registration(w["id"])
        raise ApiError(ERR_WINDOW_EXPIRED, 422,
                       "Registration deadline has passed")
    w["status"] = "REGISTERED"
    w["registered_at"] = clock.now()
    w["extended_coverage_years"] = 10
    touch(w)
    return success(ser_reg(w))


@bp.post("/warranty-registrations/<wid>/void")
def void_registration(wid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    w = get_path(db.warranty_registrations, wid)
    if w["status"] not in ("PENDING_REGISTRATION", "REGISTERED"):
        raise invalid_state("Registration in state %s cannot be voided"
                            % w["status"])
    w["status"] = "VOID"
    touch(w)
    core.deny_open_claims_for_registration(w["id"])
    return success(ser_reg(w))


# ---------------------------------------------------------------------------
# Parts claims
# ---------------------------------------------------------------------------

@bp.post("/parts-claims")
def create_claim():
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"warranty_registration_id", "contractor_id",
                                "failure_date", "part_cost_cents",
                                "labor_cost_cents"}, struct)
    registration_id = get_str(data, "warranty_registration_id", struct)
    contractor_id = get_str(data, "contractor_id", struct)
    failure_date = get_datetime(data, "failure_date", struct)
    part_cost = get_int(data, "part_cost_cents", struct, minimum=0)
    labor_cost = get_int(data, "labor_cost_cents", struct, minimum=0)

    registration = None
    if isinstance(registration_id, str):
        registration = get_ref(db.warranty_registrations, registration_id,
                               "warranty_registration_id")
    if isinstance(contractor_id, str):
        get_ref(db.contractors, contractor_id, "contractor_id")

    if isinstance(contractor_id, str):
        require_owner(contractor_id, role, user_id)

    # Anchoring (priority 18): claim contractor must equal the registration's.
    if registration is not None and isinstance(contractor_id, str) and \
            registration["contractor_id"] != contractor_id:
        raise ApiError(ERR_WARRANTY_NOT_ACTIVE, 422,
                       "contractor_id does not match the registration's "
                       "contractor")

    # failure_date may not lie in the future (structural family — last).
    if failure_date is not None and failure_date > clock.now():
        struct.add("failure_date may not be in the future")
    struct.raise_if_bad()

    c = new_common()
    c.update({
        "claim_number": "PC-" + uuid.uuid4().hex[:8].upper(),
        "warranty_registration_id": registration_id,
        "contractor_id": contractor_id,
        "failure_date": failure_date,
        "part_cost_cents": part_cost,
        "labor_cost_cents": labor_cost,
        "covered_part_cents": 0,
        "covered_labor_cents": 0,
        "total_award_cents": 0,
        "revision_count": 0,
        "status": "SUBMITTED",
    })
    db.parts_claims[c["id"]] = c
    return success(ser_claim(c), 201)


@bp.get("/parts-claims/<cid>")
def get_claim(cid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    c = get_path(db.parts_claims, cid)
    require_owner(c["contractor_id"], role, user_id)
    return success(ser_claim(c))


@bp.get("/parts-claims")
def list_claims():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"warranty_registration_id": request.args.get("warranty_registration_id"),
               "contractor_id": request.args.get("contractor_id"),
               "status": request.args.get("status")}
    return list_response(db.parts_claims.values(), ser_claim, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)


_PROCESSOR_ACTIONS = {"BEGIN_REVIEW", "APPROVE", "DENY", "REQUEST_INFO"}
_ADMIN_ACTIONS = {"PAY"}


@bp.post("/parts-claims/<cid>/decision")
def claim_decision(cid):
    user_id, role = authenticate()
    authorize({"WarrantyProcessor", "DistributorAdmin"}, role)
    data = body()
    action = data.get("action")
    if not isinstance(action, str) or action not in (
            _PROCESSOR_ACTIONS | _ADMIN_ACTIONS):
        raise invalid_request("action must be one of %s"
                              % sorted(_PROCESSOR_ACTIONS | _ADMIN_ACTIONS))
    # Segregation of duties: adjudication vs payment.
    if action in _PROCESSOR_ACTIONS:
        authorize({"WarrantyProcessor"}, role)
    else:
        authorize({"DistributorAdmin"}, role)

    c = get_path(db.parts_claims, cid)

    if action == "BEGIN_REVIEW":
        if c["status"] != "SUBMITTED":
            raise invalid_state("Only a SUBMITTED claim can begin review")
        registration = db.warranty_registrations.get(
            c["warranty_registration_id"])
        if registration is None or registration["status"] != "REGISTERED":
            raise ApiError(ERR_WARRANTY_NOT_ACTIVE, 422,
                           "Anchored registration is not REGISTERED")
        c["status"] = "UNDER_REVIEW"
    elif action == "APPROVE":
        if c["status"] != "UNDER_REVIEW":
            raise invalid_state("Only an UNDER_REVIEW claim may be approved")
        registration = db.warranty_registrations.get(
            c["warranty_registration_id"])
        part, labor = core.compute_warranty_coverage(c, registration)
        c["covered_part_cents"] = part
        c["covered_labor_cents"] = labor
        c["total_award_cents"] = part + labor
        c["status"] = "APPROVED"
    elif action == "DENY":
        if c["status"] != "UNDER_REVIEW":
            raise invalid_state("Only an UNDER_REVIEW claim may be denied")
        c["status"] = "DENIED"
    elif action == "REQUEST_INFO":
        if c["status"] != "UNDER_REVIEW":
            raise invalid_state("Only an UNDER_REVIEW claim may be sent back "
                                "for more information")
        c["status"] = "MORE_INFO_REQUESTED"
    elif action == "PAY":
        if c["status"] != "APPROVED":
            raise invalid_state("Only an APPROVED claim may be paid")
        c["status"] = "PAID"
    touch(c)
    return success(ser_claim(c))


@bp.post("/parts-claims/<cid>/resubmit")
def resubmit_claim(cid):
    user_id, role = authenticate()
    authorize({"ContractorUser"}, role)
    c = get_path(db.parts_claims, cid)
    require_owner(c["contractor_id"], role, user_id)
    if c["status"] != "MORE_INFO_REQUESTED":
        raise invalid_state("Only a MORE_INFO_REQUESTED claim may be "
                            "resubmitted")
    if c["revision_count"] >= 3:
        raise ApiError(ERR_REVISION_LIMIT, 422,
                       "Maximum of 3 revision cycles reached")
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"part_cost_cents", "labor_cost_cents"}, struct)
    if "part_cost_cents" in data:
        v = data["part_cost_cents"]
        if not is_int(v) or v < 0:
            struct.add("Field part_cost_cents must be a non-negative integer")
        else:
            c["part_cost_cents"] = v
    if "labor_cost_cents" in data:
        v = data["labor_cost_cents"]
        if not is_int(v) or v < 0:
            struct.add("Field labor_cost_cents must be a non-negative integer")
        else:
            c["labor_cost_cents"] = v
    struct.raise_if_bad()
    c["status"] = "SUBMITTED"
    c["revision_count"] += 1
    touch(c)
    return success(ser_claim(c))
