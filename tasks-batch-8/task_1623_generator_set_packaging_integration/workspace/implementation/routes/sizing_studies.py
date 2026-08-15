"""SizingStudy endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc

bp = Blueprint("sizing_studies", __name__)

VALID_STARTING_METHODS = {"DOL", "SOFT_START"}
VALID_METHODS = {"NAMEPLATE_SUM", "DERATED_STOCHASTIC"}
VALID_DUTIES = {"CONTINUOUS", "STANDBY_START"}


@bp.route("/genset-packaging/sizing-studies", methods=["POST"])
def create_sizing_study():
    mw.require_roles("ApplicationEngineer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    engine_model_id = mw.require_string(body, "engine_model_id")
    alternator_model_id = mw.require_string(body, "alternator_model_id")
    load_steps = mw.require_field(body, "load_steps")
    largest_motor_kva = mw.require_number(body, "largest_motor_kva", minimum=0, exclusive_minimum=True)
    starting_method = mw.require_enum(body, "starting_method", VALID_STARTING_METHODS)
    altitude_m = mw.require_int(body, "altitude_m", minimum=0)
    ambient_c = mw.require_int(body, "ambient_c", minimum=-40, maximum=60)
    method = mw.require_enum(body, "method", VALID_METHODS)
    expected_order_version = mw.require_int(body, "expected_order_version", minimum=1)

    # Validate load_steps structure
    if not isinstance(load_steps, list):
        raise errors.invalid_request("load_steps must be an array")
    for step in load_steps:
        if not isinstance(step, dict):
            raise errors.invalid_request("Each load step must be an object")
        if "kva" not in step:
            raise errors.invalid_request("Each load step must have a kva field")
        if not isinstance(step["kva"], (int, float)) or isinstance(step["kva"], bool):
            raise errors.invalid_request("Load step kva must be a number")
        duty = step.get("duty")
        if duty is not None and duty not in VALID_DUTIES:
            raise errors.invalid_request(
                f"Load step duty must be one of {sorted(VALID_DUTIES)}"
            )

    # Existence checks (left-to-right per body FK ordering)
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    engine = db.engine_models.get(engine_model_id)
    if engine is None:
        raise errors.not_found("Engine model not found")
    alternator = db.alternator_models.get(alternator_model_id)
    if alternator is None:
        raise errors.not_found("Alternator model not found")

    # OCC check
    if order["version"] != expected_order_version:
        raise errors.ApiError(
            errors.ERR_STALE_ORDER_VERSION, 412,
            "expected_order_version does not match the order's current version",
        )

    # Compute required_kva
    required_kva = calc.compute_required_kva(
        load_steps, largest_motor_kva, starting_method,
        altitude_m, ambient_c, method,
    )

    record = {
        "order_id": order_id,
        "engine_model_id": engine_model_id,
        "alternator_model_id": alternator_model_id,
        "load_steps": load_steps,
        "largest_motor_kva": largest_motor_kva,
        "starting_method": starting_method,
        "altitude_m": altitude_m,
        "ambient_c": ambient_c,
        "method": method,
        "required_kva": required_kva,
        "superseded_by_id": None,
        "rejection_reason": None,
        "status": "DRAFT",
    }
    db.stamp_new(record)
    db.sizing_studies[record["id"]] = record

    # Side effect: increment order version
    db.touch(order)

    return resp.success_created(record)


@bp.route("/genset-packaging/sizing-studies/<studyId>", methods=["GET"])
def get_sizing_study(studyId):
    mw.authenticate()
    record = db.sizing_studies.get(studyId)
    if record is None:
        raise errors.not_found("Sizing study not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/sizing-studies", methods=["GET"])
def list_sizing_studies():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.sizing_studies.values())
    for param in ("order_id", "engine_model_id", "alternator_model_id", "superseded_by_id"):
        val = mw.request.args.get(param)
        if val:
            items = [s for s in items if s.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/sizing-studies/<studyId>/submit", methods=["POST"])
def submit_sizing_study(studyId):
    mw.require_roles("ApplicationEngineer")

    study = db.sizing_studies.get(studyId)
    if study is None:
        raise errors.not_found("Sizing study not found")

    # From-state: DRAFT or REJECTED
    if study["status"] not in ("DRAFT", "REJECTED"):
        raise errors.ApiError(
            errors.ERR_STUDY_STATE_INVALID, 409,
            "Study must be in DRAFT or REJECTED to submit",
        )

    # Gate: order build_status not CANCELLED
    order = db.orders.get(study["order_id"])
    if order is None:
        raise errors.not_found("Package order not found")
    if order["build_status"] == "CANCELLED":
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Order build_status is CANCELLED",
        )

    study["status"] = "SUBMITTED"
    study["rejection_reason"] = None
    db.touch(study)
    return resp.success_object(study)


@bp.route("/genset-packaging/sizing-studies/<studyId>/approve", methods=["POST"])
def approve_sizing_study(studyId):
    mw.require_roles("SalesEngineer")

    study = db.sizing_studies.get(studyId)
    if study is None:
        raise errors.not_found("Sizing study not found")

    if study["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_STUDY_STATE_INVALID, 409,
            "Study must be SUBMITTED to approve",
        )

    # Capacity gate: engine.rated_kw / 0.8 >= required_kva
    engine = db.engine_models.get(study["engine_model_id"])
    if engine is None:
        raise errors.not_found("Engine model not found")
    alternator = db.alternator_models.get(study["alternator_model_id"])
    if alternator is None:
        raise errors.not_found("Alternator model not found")

    from decimal import Decimal
    engine_capacity = Decimal(str(engine["rated_kw"])) / Decimal("0.8")
    required = Decimal(str(study["required_kva"]))
    if engine_capacity < required:
        raise errors.ApiError(
            errors.ERR_CAPACITY_UNDERSIZED, 409,
            "Engine rated_kw / 0.8 is below required_kva",
        )
    if Decimal(str(alternator["rated_kva"])) < required:
        raise errors.ApiError(
            errors.ERR_CAPACITY_UNDERSIZED, 409,
            "Alternator rated_kva is below required_kva",
        )

    # Supersede any other APPROVED study for this order
    for other in db.sizing_studies.values():
        if (
            other["order_id"] == study["order_id"]
            and other["id"] != study["id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = study["id"]
            db.touch(other)

    # First approval -> order build SPEC -> SIZING
    order = db.orders.get(study["order_id"])
    if order is not None and order["build_status"] == "SPEC":
        order["build_status"] = "SIZING"
        db.touch(order)

    study["status"] = "APPROVED"
    db.touch(study)
    return resp.success_object(study)


@bp.route("/genset-packaging/sizing-studies/<studyId>/reject", methods=["POST"])
def reject_sizing_study(studyId):
    mw.require_roles("SalesEngineer")
    body = mw.get_json_body()

    study = db.sizing_studies.get(studyId)
    if study is None:
        raise errors.not_found("Sizing study not found")

    if study["status"] != "SUBMITTED":
        raise errors.ApiError(
            errors.ERR_STUDY_STATE_INVALID, 409,
            "Study must be SUBMITTED to reject",
        )

    reason = mw.require_string(body, "reason")
    study["status"] = "REJECTED"
    study["rejection_reason"] = reason
    db.touch(study)
    return resp.success_object(study)
