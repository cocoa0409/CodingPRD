"""FactoryTest endpoints."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc
import services.cascade as cascade

bp = Blueprint("factory_tests", __name__)

# Non-terminal factory test statuses (used for bay-window overlap checks)
_NON_TERMINAL = ("SCHEDULED", "IN_PROGRESS", "PASSED", "FAILED")


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.route("/genset-packaging/factory-tests", methods=["POST"])
def create_factory_test():
    mw.require_roles("TestEngineer")
    body = mw.get_json_body()

    order_id = mw.require_string(body, "order_id")
    configuration_id = mw.require_string(body, "configuration_id")
    bay_id = mw.require_string(body, "bay_id")
    service_date = mw.require_string(body, "service_date")
    start_hour = mw.require_int(body, "start_hour", minimum=0)
    end_hour = mw.require_int(body, "end_hour", maximum=24)
    retest_of_id = body.get("retest_of_id")  # optional

    if start_hour >= end_hour:
        raise errors.invalid_request("start_hour must be strictly before end_hour")

    # Existence checks
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found("Package order not found")
    config = db.configurations.get(configuration_id)
    if config is None:
        raise errors.not_found("Package configuration not found")
    bay = db.test_bays.get(bay_id)
    if bay is None:
        raise errors.not_found("Test bay not found")

    # Config must belong to the named order
    if config["order_id"] != order_id:
        raise errors.not_found("Configuration does not belong to the named order")

    # Config must be LOCKED or RELEASED
    if config["status"] not in ("LOCKED", "RELEASED"):
        raise errors.ApiError(
            errors.ERR_CONFIG_STATE_INVALID, 409,
            "Configuration must be LOCKED or RELEASED to schedule a factory test",
        )

    # retest_of_id must reference a FAILED test of the same order
    if retest_of_id is not None:
        prior = db.factory_tests.get(retest_of_id)
        if prior is None:
            raise errors.invalid_request("retest_of_id references a non-existent test")
        if prior["status"] != "FAILED" or prior["order_id"] != order_id:
            raise errors.invalid_request(
                "retest_of_id must reference a FAILED test of the same order"
            )

    # --- Business rules, PRD §2.8 order: capacity/overlap before referential ---

    # Bay must be ACTIVE
    if bay["status"] != "ACTIVE":
        raise errors.ApiError(
            errors.ERR_TEST_BAY_OVERLAP, 409,
            "Test bay is not ACTIVE",
        )

    # Bay window overlap check (same bay, same date, half-open)
    for existing in db.factory_tests.values():
        if (
            existing["bay_id"] == bay_id
            and existing["service_date"] == service_date
            and existing["status"] in _NON_TERMINAL
            and _windows_overlap(start_hour, end_hour, existing["start_hour"], existing["end_hour"])
        ):
            raise errors.ApiError(
                errors.ERR_TEST_BAY_OVERLAP, 409,
                "Requested window intersects an existing test on the same bay and date",
            )

    # Cross-entity referential: an EmissionsCertificate for the order must be ISSUED
    has_issued_cert = any(
        c["order_id"] == order_id and c["status"] == "ISSUED"
        for c in db.emissions_certificates.values()
    )
    if not has_issued_cert:
        raise errors.ApiError(
            errors.ERR_CERT_NOT_ISSUED, 409,
            "An emissions certificate for the order must be ISSUED before scheduling a test",
        )

    record = {
        "order_id": order_id,
        "configuration_id": configuration_id,
        "bay_id": bay_id,
        "retest_of_id": retest_of_id,
        "service_date": service_date,
        "start_hour": start_hour,
        "end_hour": end_hour,
        "readings": [],
        "total_kwh": 0,
        "measured_avg_pf": 0,
        "invoice_total_cents": 0,
        "verdict": None,
        "recorded_by_user_id": None,
        "accepted_by_user_id": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(record)
    db.factory_tests[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/factory-tests/<testId>", methods=["GET"])
def get_factory_test(testId):
    mw.authenticate()
    record = db.factory_tests.get(testId)
    if record is None:
        raise errors.not_found("Factory test not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/factory-tests", methods=["GET"])
def list_factory_tests():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    items = list(db.factory_tests.values())
    for param in ("order_id", "configuration_id", "bay_id", "retest_of_id"):
        val = mw.request.args.get(param)
        if val:
            items = [t for t in items if t.get(param) == val]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/factory-tests/<testId>/start", methods=["POST"])
def start_factory_test(testId):
    mw.require_roles("TestEngineer")

    test = db.factory_tests.get(testId)
    if test is None:
        raise errors.not_found("Factory test not found")

    if test["status"] != "SCHEDULED":
        raise errors.ApiError(
            errors.ERR_TEST_STATE_INVALID, 409,
            "Test must be SCHEDULED to start",
        )

    test["status"] = "IN_PROGRESS"
    db.touch(test)
    return resp.success_object(test)


@bp.route("/genset-packaging/factory-tests/<testId>/record", methods=["POST"])
def record_factory_test(testId):
    user_id, _ = mw.require_roles("TestEngineer")
    body = mw.get_json_body()

    test = db.factory_tests.get(testId)
    if test is None:
        raise errors.not_found("Factory test not found")

    if test["status"] != "IN_PROGRESS":
        raise errors.ApiError(
            errors.ERR_TEST_STATE_INVALID, 409,
            "Test must be IN_PROGRESS to record",
        )

    readings = mw.require_field(body, "readings")
    if not isinstance(readings, list) or len(readings) == 0:
        raise errors.invalid_request("readings must be a non-empty array")
    for step in readings:
        if not isinstance(step, dict):
            raise errors.invalid_request("Each reading must be an object")
        if "kw" not in step or "hours" not in step or "power_factor" not in step:
            raise errors.invalid_request("Each reading must have kw, hours, and power_factor")
        hours_val = step["hours"]
        if not isinstance(hours_val, (int, float)) or isinstance(hours_val, bool) or hours_val <= 0:
            raise errors.invalid_request("Each reading's hours must be a positive number")

    total_kwh, measured_avg_pf, invoice_total_cents, verdict = calc.compute_test_results(readings)

    test["readings"] = readings
    test["total_kwh"] = total_kwh
    test["measured_avg_pf"] = measured_avg_pf
    test["invoice_total_cents"] = invoice_total_cents
    test["verdict"] = verdict
    test["recorded_by_user_id"] = user_id

    if verdict == "PASS":
        test["status"] = "PASSED"
    else:
        test["status"] = "FAILED"
        # Build regression: TESTING -> CONFIGURING or READY_TO_SHIP -> CONFIGURING
        order = db.orders.get(test["order_id"])
        if order is not None and order["build_status"] in ("TESTING", "READY_TO_SHIP"):
            order["build_status"] = "CONFIGURING"
            db.touch(order)
        # Release all BOOKED shipments for the order
        cascade.release_booked_shipments_for_order(test["order_id"])

    db.touch(test)
    return resp.success_object(test)


@bp.route("/genset-packaging/factory-tests/<testId>/accept", methods=["POST"])
def accept_factory_test(testId):
    user_id, _ = mw.require_roles("TestEngineer")

    test = db.factory_tests.get(testId)
    if test is None:
        raise errors.not_found("Factory test not found")

    if test["status"] != "PASSED":
        raise errors.ApiError(
            errors.ERR_TEST_STATE_INVALID, 409,
            "Test must be PASSED to accept",
        )

    # Segregation of duties: acceptor must differ from recorder
    if user_id == test["recorded_by_user_id"]:
        raise errors.ApiError(
            errors.ERR_SOD_VIOLATION, 403,
            "The engineer who recorded a test may not accept it",
        )

    test["accepted_by_user_id"] = user_id
    test["status"] = "ACCEPTED"
    db.touch(test)

    # Order build: TESTING -> READY_TO_SHIP
    order = db.orders.get(test["order_id"])
    if order is not None and order["build_status"] == "TESTING":
        order["build_status"] = "READY_TO_SHIP"
        db.touch(order)

    # Configuration: LOCKED -> RELEASED
    config = db.configurations.get(test["configuration_id"])
    if config is not None and config["status"] == "LOCKED":
        config["status"] = "RELEASED"
        db.touch(config)

    return resp.success_object(test)
