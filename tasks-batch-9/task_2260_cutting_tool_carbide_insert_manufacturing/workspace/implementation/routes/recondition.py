"""Reconditioning jobs and the tool life extension programme (PRD 3.9)."""

from flask import Blueprint

import calculations as calc
import db
import validation as v
from errors import ApiError
from middleware import authenticate
from response import object_response
from routes import common as c
from services import derive, serialize

bp = Blueprint("recondition", __name__)

INTAKE_ROLES = ["Customer", "ProductionPlanner"]
INSPECTORS = ["ProductionPlanner", "QualityApprover"]
OWNER = ["ProductionPlanner"]
READ_ROLES = ["Customer", "ProductionPlanner", "QualityApprover", "ApplicationEngineer"]

MIN_UNITS = 1
MAX_UNITS = 500


def _scope(role, user_id, customer_id):
    if role == "Customer" and customer_id != user_id:
        raise ApiError(
            "ERR_CUSTOMER_SCOPE_VIOLATION",
            "A Customer caller may act only on its own reconditioning jobs.",
        )


@bp.route("/tooling/recondition-jobs", methods=["POST"])
def create():
    user_id, role = authenticate(INTAKE_ROLES)
    payload = v.body(
        required=(
            "customer_id",
            "product_id",
            "job_code",
            "units_received",
            "expected_customer_version",
        ),
        optional=("predecessor_job_id",),
    )
    customer_id = v.as_id(payload, "customer_id")
    product_id = v.as_id(payload, "product_id")
    job_code = v.as_string(payload, "job_code")
    units = v.as_int(payload, "units_received", minimum=MIN_UNITS, maximum=MAX_UNITS)
    predecessor_id = v.as_id(payload, "predecessor_job_id", nullable=True)
    expected_version = v.as_int(payload, "expected_customer_version", minimum=1)

    customer = derive.must_exist("customers", customer_id)
    product = derive.must_exist("products", product_id)
    predecessor = derive.must_exist("jobs", predecessor_id) if predecessor_id else None

    _scope(role, user_id, customer["id"])

    if expected_version != customer["version"]:
        raise ApiError(
            "ERR_STALE_CUSTOMER_VERSION",
            "The customer is at version %d, not %d."
            % (customer["version"], expected_version),
        )

    derive.require_unique("jobs", "job_code", job_code)

    if product["tool_type"] == "INSERT" or calc.D(product["min_regrind_length_mm"]) >= calc.D(
        product["nominal_length_mm"]
    ):
        raise ApiError(
            "ERR_PRODUCT_NOT_REGRINDABLE", "This product cannot be reconditioned."
        )

    if predecessor is not None:
        if (
            predecessor["status"] != "RETURNED"
            or predecessor["customer_id"] != customer["id"]
            or predecessor["product_id"] != product["id"]
            or derive.predecessor_already_used(predecessor["id"])
        ):
            raise ApiError(
                "ERR_INVALID_PREDECESSOR_CHAIN",
                "The named predecessor job cannot carry another regrind pass.",
            )

    if customer["account_status"] == "CREDIT_HOLD":
        raise ApiError("ERR_CUSTOMER_CREDIT_HOLD", "The customer account is on credit hold.")
    if customer["account_status"] == "CLOSED":
        raise ApiError("ERR_CUSTOMER_CLOSED", "The customer account is closed.")

    reservation = units * calc.RECONDITION_COST_CENTS_PER_TOOL
    if reservation > customer["regrind_credit_cents"]:
        raise ApiError(
            "ERR_INSUFFICIENT_REGRIND_CREDIT",
            "The intake reserves %d cents against a balance of %d."
            % (reservation, customer["regrind_credit_cents"]),
        )

    row = db.new_row(
        {
            "customer_id": customer["id"],
            "product_id": product["id"],
            "predecessor_job_id": predecessor["id"] if predecessor else None,
            "job_code": job_code,
            "units_received": units,
            "reserved_credit_cents": reservation,
            "regrind_pass_no": derive.job_chain_length(
                predecessor["id"] if predecessor else None
            )
            + 1,
            "wheel_id": None,
            "units_inspected": None,
            "measured_length_mm": None,
            "measured_corner_wear_um": None,
            "remaining_regrinds": None,
            "life_extension_pct": None,
            "warranted_life_extension_pct": None,
            "scrap_recommended": False,
            "recoat_applied": False,
            "units_returned": None,
            "rebate_cents": None,
            "status": "RECEIVED",
        }
    )
    db.jobs[row["id"]] = row

    customer["regrind_credit_cents"] = customer["regrind_credit_cents"] - reservation
    db.touch(customer)
    return object_response(serialize.job(row), 201)


@bp.route("/tooling/recondition-jobs", methods=["GET"])
def index():
    user_id, role = authenticate(READ_ROLES)
    limit, offset = v.pagination()
    filters = {}
    for key in ("customer_id", "product_id", "predecessor_job_id", "wheel_id"):
        value = v.query_value(key)
        if value is not None:
            filters[key] = value
    status = v.query_enum("status", c.JOB_STATUSES)
    if status is not None:
        filters["status"] = status
    if role == "Customer":
        filters["customer_id"] = user_id
    rows = derive.where("jobs", **filters)
    return c.list_response("jobs", rows, limit, offset)


@bp.route("/tooling/recondition-jobs/<job_id>", methods=["GET"])
def read(job_id):
    user_id, role = authenticate(READ_ROLES)
    v.pagination()
    job = derive.must_exist("jobs", job_id)
    _scope(role, user_id, job["customer_id"])
    return object_response(serialize.job(job))


@bp.route("/tooling/recondition-jobs/<job_id>/inspect", methods=["POST"])
def inspect(job_id):
    authenticate(INSPECTORS)
    payload = v.body(
        required=("units_inspected", "measured_length_mm", "measured_corner_wear_um")
    )
    units_inspected = v.as_int(payload, "units_inspected", minimum=0)
    length = v.as_number(payload, "measured_length_mm", minimum=0)
    corner_wear = v.as_number(payload, "measured_corner_wear_um", minimum=0)

    job = derive.must_exist("jobs", job_id)
    if job["status"] != "RECEIVED":
        raise ApiError(
            "ERR_INVALID_JOB_STATE",
            "Only a RECEIVED job may be inspected (currently %s)." % job["status"],
        )
    if units_inspected != job["units_received"]:
        raise ApiError(
            "ERR_UNIT_COUNT_MISMATCH",
            "units_inspected must equal units_received (%d)." % job["units_received"],
        )

    product = db.products.get(job["product_id"])
    remaining, extension, warranted, scrap = calc.recondition_life_extension(
        length,
        product["min_regrind_length_mm"],
        product["regrind_step_mm"],
        product["nominal_length_mm"],
        job["regrind_pass_no"],
    )

    job["units_inspected"] = units_inspected
    job["measured_length_mm"] = length
    job["measured_corner_wear_um"] = corner_wear
    job["remaining_regrinds"] = remaining
    job["life_extension_pct"] = float(extension)
    job["warranted_life_extension_pct"] = float(warranted)
    job["scrap_recommended"] = bool(scrap)
    job["status"] = "INSPECTED"
    db.touch(job)
    return object_response(serialize.job(job))


@bp.route("/tooling/recondition-jobs/<job_id>/refurbish", methods=["POST"])
def refurbish(job_id):
    authenticate(OWNER)
    payload = v.body(required=("wheel_id",), optional=("recoat_applied",))
    wheel_id = v.as_id(payload, "wheel_id")
    recoat = v.as_bool(payload, "recoat_applied", default=False)

    job = derive.must_exist("jobs", job_id)
    wheel = derive.must_exist("wheels", wheel_id)

    if job["status"] != "INSPECTED":
        raise ApiError(
            "ERR_INVALID_JOB_STATE",
            "Only an INSPECTED job may be refurbished (currently %s)." % job["status"],
        )

    product = db.products.get(job["product_id"])
    charge = (job["units_inspected"] or 0) * product["grind_units_per_tool"]

    if wheel["status"] == "EXPIRED":
        raise ApiError("ERR_WHEEL_EXPIRED", "An EXPIRED wheel cannot take work.")
    if wheel["status"] == "DRESSING":
        raise ApiError(
            "ERR_WHEEL_REQUIRES_DRESSING", "The wheel must be dressed before it takes work."
        )
    if derive.wheel_remaining(wheel) < charge:
        raise ApiError(
            "ERR_WHEEL_REQUIRES_DRESSING",
            "The wheel has %d life unit(s) left but the job needs %d."
            % (derive.wheel_remaining(wheel), charge),
        )
    if job["scrap_recommended"] or (job["remaining_regrinds"] or 0) < 1:
        raise ApiError(
            "ERR_NO_REGRINDS_REMAINING",
            "The tools have no regrinds left and must be scrapped instead.",
        )
    if recoat:
        recipe = (
            db.recipes.get(product["coating_recipe_id"])
            if product["coating_recipe_id"]
            else None
        )
        if recipe is None or not derive.recipe_is_validated(recipe):
            raise ApiError(
                "ERR_COATING_NOT_VALIDATED",
                "A recoat requires the product to carry a validated coating recipe.",
            )

    job["wheel_id"] = wheel["id"]
    job["recoat_applied"] = recoat
    job["status"] = "REFURBISHED"
    db.touch(job)
    derive.wheel_charge(wheel, charge)
    return object_response(serialize.job(job))


@bp.route("/tooling/recondition-jobs/<job_id>/return", methods=["POST"])
def return_tools(job_id):
    authenticate(OWNER)
    payload = v.body(required=("units_returned",))
    units_returned = v.as_int(payload, "units_returned", minimum=0)

    job = derive.must_exist("jobs", job_id)
    if job["status"] != "REFURBISHED":
        raise ApiError(
            "ERR_INVALID_JOB_STATE",
            "Only a REFURBISHED job may be returned (currently %s)." % job["status"],
        )
    if units_returned > (job["units_inspected"] or 0):
        raise ApiError(
            "ERR_UNIT_COUNT_MISMATCH",
            "units_returned must not exceed units_inspected (%s)." % job["units_inspected"],
        )

    persisted_units = job["units_inspected"]
    rebate = calc.recondition_rebate(job["life_extension_pct"], persisted_units)

    job["units_returned"] = persisted_units
    job["rebate_cents"] = rebate
    job["reserved_credit_cents"] = 0
    job["status"] = "RETURNED"
    db.touch(job)

    customer = db.customers.get(job["customer_id"])
    if customer is not None:
        derive.apply_credit_movement(customer, rebate, allow_resume=True)
        db.touch(customer)
    return object_response(serialize.job(job))


@bp.route("/tooling/recondition-jobs/<job_id>/scrap", methods=["POST"])
def scrap(job_id):
    authenticate(INSPECTORS)
    payload = v.body(required=("scrap_reason",))
    v.as_string(payload, "scrap_reason")

    job = derive.must_exist("jobs", job_id)
    if job["status"] not in ("RECEIVED", "INSPECTED"):
        raise ApiError(
            "ERR_INVALID_JOB_STATE",
            "A job is scrapped from RECEIVED or INSPECTED (currently %s)." % job["status"],
        )

    refund = job["reserved_credit_cents"]
    job["reserved_credit_cents"] = 0
    job["units_returned"] = 0
    job["rebate_cents"] = 0
    job["status"] = "SCRAPPED"
    db.touch(job)

    customer = db.customers.get(job["customer_id"])
    if customer is not None:
        # A refund merely returns money the customer already paid in, so it can
        # never lift a credit hold on its own (PRD 3.9).
        derive.apply_credit_movement(customer, refund, allow_resume=False)
        db.touch(customer)
    return object_response(serialize.job(job))
