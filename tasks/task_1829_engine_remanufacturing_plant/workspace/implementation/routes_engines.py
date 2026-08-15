"""Remanufactured engines: dyno testing, sealing, and sales (PRD 3.8, 3.9)."""

import datetime

from flask import Blueprint, request

import calcs
import clock as clockmod
import envelope
import serializers
from auth import ALL_READ_ROLES, authorized
from errors import (
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DISTRIBUTOR_CREDIT_HOLD,
    ERR_DYNO_CELL_SCHEDULE_OVERLAP,
    ERR_DYNO_NOT_PASSED,
    ERR_EMISSIONS_TIER_MISMATCH,
    ERR_INVALID_STATE,
    ERR_NO_ELIGIBLE_ENGINE,
    ERR_NOT_FOUND,
    ERR_SEALER_IS_TESTER,
    ERR_STALE_VERSION,
    raise_error,
)
from services import create_deposit, get_or_404, latest_dyno_test, select_sealed_engine
from store import db, stamp_new, sorted_rows, touch
from validate import (
    check_allowed_fields,
    filter_enum,
    get_body,
    pagination,
    req_instant,
    req_int,
    req_number,
    req_str,
)

bp = Blueprint("engines", __name__)

ENGINE_STATUSES = {"BUILT", "DYNO_PASSED", "SEALED", "SOLD", "RETURNED", "SCRAPPED"}

DYNO_CELL_COOLDOWN = datetime.timedelta(minutes=30)


@bp.route("/reman-engines", methods=["GET"])
def list_reman_engines():
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    f_wo = request.args.get("work_order_id")
    f_spec = request.args.get("build_spec_id")
    f_distributor = request.args.get("distributor_id")
    f_status = filter_enum("status", ENGINE_STATUSES)
    rows = list(db.engines.values())
    if f_wo is not None:
        rows = [r for r in rows if r["work_order_id"] == f_wo]
    if f_spec is not None:
        rows = [r for r in rows if r["build_spec_id"] == f_spec]
    if f_distributor is not None:
        rows = [r for r in rows if r["distributor_id"] == f_distributor]
    if f_status is not None:
        rows = [r for r in rows if r["status"] == f_status]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.reman_engine(r) for r in page], limit, offset, total)


@bp.route("/reman-engines/<rid>", methods=["GET"])
def get_reman_engine(rid):
    authorized(ALL_READ_ROLES)
    record = get_or_404("engines", rid)
    return envelope.ok(serializers.reman_engine(record))


@bp.route("/reman-engines/<rid>/dyno-tests", methods=["POST"])
def record_dyno_test(rid):
    caller = authorized(["ShopTechnician"])
    body = get_body()
    check_allowed_fields(
        body,
        [
            "dyno_cell_code",
            "started_at",
            "ended_at",
            "horsepower",
            "oil_pressure_psi",
            "coolant_temp_f",
        ],
    )
    dyno_cell_code = req_str(body, "dyno_cell_code")
    start_raw, start_dt = req_instant(body, "started_at")
    end_raw, end_dt = req_instant(body, "ended_at")
    horsepower = req_int(body, "horsepower")
    oil_pressure_psi = req_number(body, "oil_pressure_psi")
    coolant_temp_f = req_int(body, "coolant_temp_f")
    if not end_dt > start_dt:
        raise_error(ERR_VALIDATION, "ended_at must be strictly after started_at")

    engine = get_or_404("engines", rid)
    # Recording a test requires the engine BUILT and the parent work order in
    # DYNO_TEST.
    work_order = db.work_orders[engine["work_order_id"]]
    if engine["status"] != "BUILT" or work_order["status"] != "DYNO_TEST":
        raise_error(
            ERR_INVALID_STATE,
            "a dyno test requires the engine to be BUILT and the parent work "
            "order to be in DYNO_TEST",
        )

    # Dyno cell occupation carries a 30-minute cooldown buffer: each recorded
    # test occupies [started_at, ended_at + 30min); a conflict is any
    # intersection of the buffer-extended intervals -- a new test starting
    # exactly at a prior test's ended_at still conflicts.
    for other in db.dyno_tests.values():
        if other["dyno_cell_code"] != dyno_cell_code:
            continue
        other_start = other["_start_dt"]
        other_end = other["_end_dt"] + DYNO_CELL_COOLDOWN
        if start_dt < other_end and other_start < end_dt + DYNO_CELL_COOLDOWN:
            raise_error(
                ERR_DYNO_CELL_SCHEDULE_OVERLAP,
                "dyno cell %s is occupied within the requested window" % dyno_cell_code,
            )

    # The result is computed from the build spec thresholds, never supplied.
    spec = db.build_specs[engine["build_spec_id"]]
    passed = (
        horsepower >= spec["dyno_min_horsepower"]
        and oil_pressure_psi >= spec["dyno_min_oil_pressure_psi"]
        and coolant_temp_f <= spec["dyno_max_coolant_temp_f"]
    )
    result = "PASS" if passed else "FAIL"

    attempt = 1 + len(
        [t for t in db.dyno_tests.values() if t["reman_engine_id"] == engine["id"]]
    )
    record = {
        "reman_engine_id": engine["id"],
        "recorded_by": caller.user_id,
        "dyno_cell_code": dyno_cell_code,
        "started_at": start_raw,
        "ended_at": end_raw,
        "horsepower": horsepower,
        "oil_pressure_psi": oil_pressure_psi,
        "coolant_temp_f": coolant_temp_f,
        "result": result,
        "attempt": attempt,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    }
    stamp_new(record, versioned=False)  # dyno records are immutable
    db.dyno_tests[record["id"]] = record

    engine["latest_dyno_result"] = result
    if passed:
        engine["status"] = "DYNO_PASSED"
    touch(engine)
    return envelope.created(serializers.dyno_test(record))


@bp.route("/reman-engines/<rid>/dyno-tests", methods=["GET"])
def list_dyno_tests(rid):
    authorized(ALL_READ_ROLES)
    limit, offset = pagination()
    engine = get_or_404("engines", rid)
    rows = [t for t in db.dyno_tests.values() if t["reman_engine_id"] == engine["id"]]
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return envelope.listing([serializers.dyno_test(r) for r in page], limit, offset, total)


@bp.route("/reman-engines/<rid>/seal", methods=["POST"])
def seal_reman_engine(rid):
    caller = authorized(["QualityInspector"])
    body = get_body()
    check_allowed_fields(body, [])
    engine = get_or_404("engines", rid)

    # Quality gate, which doubles as the seal state gate: any seal attempt on
    # an engine that is BUILT, untested, or whose latest test failed is
    # reported as ERR_DYNO_NOT_PASSED, not ERR_INVALID_STATE.
    if engine["status"] != "DYNO_PASSED":
        if engine["latest_dyno_result"] != "PASS":
            raise_error(
                ERR_DYNO_NOT_PASSED,
                "the engine's latest dyno result is not PASS",
            )
        raise_error(
            ERR_INVALID_STATE,
            "only a DYNO_PASSED engine can be sealed",
        )

    # Segregation of duties: the sealer must differ from the technician who
    # recorded the most recent dyno test.
    latest = latest_dyno_test(engine["id"])
    if latest is not None and latest["recorded_by"] == caller.user_id:
        raise_error(
            ERR_SEALER_IS_TESTER,
            "the sealing inspector must differ from the dyno recorder",
        )

    now = clockmod.now()
    engine["status"] = "SEALED"
    engine["sealed_at"] = now
    engine["sealed_by"] = caller.user_id
    touch(engine)

    # BUBBLE UP: the parent work order moves DYNO_TEST -> CLOSED.
    work_order = db.work_orders.get(engine["work_order_id"])
    if work_order is not None and work_order["status"] == "DYNO_TEST":
        work_order["status"] = "CLOSED"
        touch(work_order)

    return envelope.ok(serializers.reman_engine(engine))


@bp.route("/reman-engines/sell", methods=["POST"])
def sell_reman_engine():
    caller = authorized(["Distributor"])
    body = get_body()
    check_allowed_fields(body, ["build_spec_id", "expected_distributor_version"])
    build_spec_id = req_str(body, "build_spec_id")
    expected_version = req_int(body, "expected_distributor_version")

    spec = get_or_404("build_specs", build_spec_id)
    buyer = db.distributors.get(caller.user_id)
    if buyer is None:
        raise_error(ERR_NOT_FOUND, "the caller is not a registered distributor")

    # Allocation selector: the server, not the buyer, selects the unit from the
    # pool of SEALED engines under the requested spec.
    engine = select_sealed_engine(build_spec_id)
    if engine is None:
        raise_error(
            ERR_NO_ELIGIBLE_ENGINE,
            "no SEALED engine of the requested build spec is available",
        )

    # The gauntlet, in PRD 3.9's fixed order.
    if buyer["status"] != "ACTIVE":
        raise_error(ERR_DISTRIBUTOR_CREDIT_HOLD, "the buyer is on CREDIT_HOLD")
    if (
        buyer["emissions_requirement"] == "CALIFORNIA"
        and spec["emissions_tier"] != "CALIFORNIA"
    ):
        raise_error(
            ERR_EMISSIONS_TIER_MISMATCH,
            "a CALIFORNIA-requirement distributor may only buy CALIFORNIA-tier engines",
        )
    if (
        serializers.deposits_held_cents(buyer["id"]) + spec["core_deposit_cents"]
        > buyer["credit_limit_cents"]
    ):
        raise_error(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "deposits_held_cents plus the new deposit would exceed the credit limit",
        )
    if expected_version != buyer["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_distributor_version does not match the distributor's current version",
        )

    now = clockmod.now()
    engine["status"] = "SOLD"
    engine["distributor_id"] = buyer["id"]
    engine["sold_at"] = now
    engine["sale_price_cents"] = calcs.sale_price_cents(spec, buyer)
    touch(engine)

    # SALE CHAIN: link 1 creates the HELD deposit; link 2 raises the buyer's
    # deposits_held (derived) and bumps the distributor version -- which is
    # what invalidates any other client holding a pre-sale expected version.
    create_deposit(buyer["id"], engine["id"], spec, now)
    touch(buyer)

    return envelope.ok(serializers.reman_engine(engine))
