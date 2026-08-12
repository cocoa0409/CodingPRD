"""Driver pipeline endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CREDENTIAL_EXPIRED,
    ERR_ENDORSEMENT_MISSING,
    ERR_INVALID_STATE,
    ERR_TRAINING_HOURS_INSUFFICIENT,
    raise_err,
)
from middleware import (
    authenticate,
    get_or_404,
    read_scoping,
    require_roles,
)
from services.coverage import suspend_driver, terminate_driver_cascade
from services.pricing import (
    REQUIRED_BEHIND_WHEEL_MINUTES,
    REQUIRED_CLASSROOM_MINUTES,
    weekly_assigned_minutes_current,
)
from validation import (
    get_body,
    opt_str,
    paginate,
    pagination_params,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("drivers", __name__)

LIST_ROLES = {
    "SystemAdmin",
    "DistrictAdmin",
    "ContractorOps",
    "HRRecruiter",
    "FleetManager",
    "FinanceClerk",
}
GET_ROLES = LIST_ROLES | {"Driver"}

EVENT_TRANSITIONS = {
    "SCREEN": ("APPLICANT", "SCREENING"),
    "ENROLL": ("SCREENING", "TRAINING"),
    "SCHEDULE_TEST": ("TRAINING", "TESTING"),
    "TEST_FAIL": ("TESTING", "TRAINING"),
    "TEST_PASS": ("TESTING", "CERTIFIED"),
    "ACTIVATE": ("CERTIFIED", "ACTIVE"),
}


def serialize(driver):
    out = db.public(driver)
    out["weekly_assigned_minutes"] = weekly_assigned_minutes_current(driver["id"])
    return out


def active_credential(driver_id, kind):
    for c in db.all_of("credentials"):
        if (
            c["driver_id"] == driver_id
            and c["kind"] == kind
            and c["status"] == "ACTIVE"
        ):
            return c
    return None


def check_driver_transition(driver, allowed_from):
    if driver["status"] == "TERMINATED":
        raise_err(ERR_ALREADY_TERMINAL, "Driver is TERMINATED (terminal)")
    if driver["status"] not in allowed_from:
        raise_err(
            ERR_INVALID_STATE,
            "Driver in state %s cannot perform this transition" % driver["status"],
        )


@bp.route("/busops/drivers", methods=["POST"])
def create_driver():
    body = get_body()
    district_id = req_str(body, "primary_district_id")
    full_name = req_str(body, "full_name")
    license_number = req_str(body, "license_number")
    license_class = req_enum(body, "license_class", ("A", "B"))
    wage = req_int(body, "hourly_wage_cents", minimum=0)
    actor = authenticate()
    require_roles(actor, {"HRRecruiter"})
    get_or_404("districts", district_id, "District")

    rec = {
        "id": db.new_id(),
        "primary_district_id": district_id,
        "full_name": full_name,
        "license_number": license_number,
        "license_class": license_class,
        "hourly_wage_cents": wage,
        "hired_on": None,
        "status": "APPLICANT",
        "suspension_reason": None,
        "behind_wheel_minutes": 0,
        "classroom_minutes": 0,
        "test_fail_count": 0,
        "_driver_ref": None,  # replaced below: own id
    }
    rec["_driver_ref"] = rec["id"]
    db.stamp_new(rec)
    db.STORES["drivers"][rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/busops/drivers", methods=["GET"])
def list_drivers():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, LIST_ROLES)
    items = list(db.all_of("drivers"))
    district_id = request.args.get("primary_district_id")
    status = request.args.get("status")
    if district_id is not None:
        items = [d for d in items if d["primary_district_id"] == district_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, info = paginate(items, limit, offset)
    page = [serialize(db.find("drivers", item["id"])) for item in page]
    return success_list(page, info)


@bp.route("/busops/drivers/<rid>", methods=["GET"])
def get_driver(rid):
    actor = authenticate()
    require_roles(actor, GET_ROLES)
    rec = get_or_404("drivers", rid, "Driver")
    err = read_scoping(actor, rec)
    if err:
        raise err
    return success_object(serialize(rec))


@bp.route("/busops/drivers/<rid>/events", methods=["POST"])
def driver_events(rid):
    body = get_body()
    event_type = req_enum(
        body,
        "event_type",
        (
            "SCREEN",
            "ENROLL",
            "SCHEDULE_TEST",
            "TEST_PASS",
            "TEST_FAIL",
            "ACTIVATE",
            "TERMINATE",
        ),
    )
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"HRRecruiter"})
    driver = get_or_404("drivers", rid, "Driver")

    if event_type == "TERMINATE":
        if driver["status"] == "TERMINATED":
            raise_err(ERR_ALREADY_TERMINAL, "Driver is TERMINATED (terminal)")
        driver["status"] = "TERMINATED"
        db.touch(driver)
        terminate_driver_cascade(driver)
        return success_object(serialize(driver))

    from_state, to_state = EVENT_TRANSITIONS[event_type]
    check_driver_transition(driver, (from_state,))

    if event_type == "SCHEDULE_TEST":
        if (
            driver["behind_wheel_minutes"] < REQUIRED_BEHIND_WHEEL_MINUTES
            or driver["classroom_minutes"] < REQUIRED_CLASSROOM_MINUTES
        ):
            raise_err(
                ERR_TRAINING_HOURS_INSUFFICIENT,
                "SCHEDULE_TEST requires behind_wheel_minutes >= 2400 and "
                "classroom_minutes >= 1200",
            )
    elif event_type == "TEST_FAIL":
        driver["test_fail_count"] += 1
    elif event_type == "TEST_PASS":
        if active_credential(driver["id"], "CDL_B") is None:
            raise_err(
                ERR_CREDENTIAL_EXPIRED,
                "TEST_PASS requires an ACTIVE CDL_B credential",
            )
    elif event_type == "ACTIVATE":
        if active_credential(driver["id"], "S_ENDORSEMENT") is None:
            raise_err(
                ERR_ENDORSEMENT_MISSING,
                "ACTIVATE requires an ACTIVE S_ENDORSEMENT credential",
            )
        driver["hired_on"] = db.clock_date().isoformat()

    driver["status"] = to_state
    db.touch(driver)
    return success_object(serialize(driver))


@bp.route("/busops/drivers/<rid>/discipline", methods=["POST"])
def driver_discipline(rid):
    body = get_body()
    action = req_enum(body, "action", ("SUSPEND", "REINSTATE"))
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"ContractorOps"})
    driver = get_or_404("drivers", rid, "Driver")

    if action == "SUSPEND":
        check_driver_transition(driver, ("ACTIVE",))
        suspend_driver(driver, "DISCIPLINE")
    else:  # REINSTATE
        check_driver_transition(driver, ("SUSPENDED",))
        if active_credential(driver["id"], "CDL_B") is None:
            raise_err(
                ERR_CREDENTIAL_EXPIRED,
                "REINSTATE requires an ACTIVE CDL_B credential",
            )
        if active_credential(driver["id"], "S_ENDORSEMENT") is None:
            raise_err(
                ERR_ENDORSEMENT_MISSING,
                "REINSTATE requires an ACTIVE S_ENDORSEMENT credential",
            )
        driver["status"] = "ACTIVE"
        driver["suspension_reason"] = None
        db.touch(driver)
    return success_object(serialize(driver))
