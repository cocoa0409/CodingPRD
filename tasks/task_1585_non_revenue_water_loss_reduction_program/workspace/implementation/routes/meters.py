"""CustomerMeter and MeterAccuracyTest endpoints."""

import db
import errors
from errors import ApiError
from middleware import get_body, require_roles
from response import success_list, success_object
from routes import make_bp
from services import calc
from util import D, canon, paginate, sort_created, v_dt, v_enum, v_int, v_num, v_str

bp = make_bp("meters")

MT = {"MeterTechnician"}
READ_ROLES = {"ProgramDirector", "MeterTechnician", "UtilityAnalyst"}
SIZES = (15, 20, 25, 40, 50, 100, 150)
POLICIES = ("AGE_BASED", "ACCURACY_BASED", "HYBRID")


def _get_meter_or_404(meter_id):
    rec = db.store["customer_meters"].get(meter_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "customer meter not found")
    return rec


def _get_test_or_404(test_id):
    rec = db.store["meter_accuracy_tests"].get(test_id)
    if rec is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "meter accuracy test not found")
    return rec


def _serial_taken(serial):
    return any(m["serial_number"] == serial for m in db.store["customer_meters"].values())


@bp.route("/nrw/customer-meters", methods=["POST"])
def create_meter():
    uid, role = require_roles(MT)
    body = get_body()
    # priority 3: existence of body FK
    dma_id = body.get("dma_id")
    dma = db.store["dmas"].get(dma_id) if isinstance(dma_id, str) else None
    if dma is None:
        if not isinstance(dma_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "dma_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "DMA not found")
    # priority 4: uniqueness
    serial = body.get("serial_number")
    if isinstance(serial, str) and _serial_taken(serial):
        raise ApiError(errors.ERR_DUPLICATE, 409,
                       "a meter with this serial_number already exists")
    # priority 9: scalar constraints
    serial = v_str(body, "serial_number")
    size = v_int(body, "size_mm")
    if size not in SIZES:
        raise ApiError(errors.ERR_VALIDATION, 422,
                       "size_mm must be one of 15, 20, 25, 40, 50, 100, 150")
    installed = v_dt(body, "installed_at")
    policy = v_enum(body, "replacement_policy", POLICIES, required=False,
                    default="ACCURACY_BASED")

    rec = db.new_record()
    rec.update({
        "dma_id": dma_id,
        "serial_number": serial,
        "size_mm": size,
        "installed_at": canon(installed),
        "replacement_policy": policy,
        "status": "IN_SERVICE",
        "last_test_accuracy_pct": None,
        "replacement_due": False,
    })
    rec["replacement_due"] = calc.compute_replacement_due(rec)
    db.store["customer_meters"][rec["id"]] = rec
    db.append_audit("CustomerMeter", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/customer-meters/<meter_id>", methods=["GET"])
def get_meter(meter_id):
    require_roles(READ_ROLES)
    return success_object(db.serialize(_get_meter_or_404(meter_id)))


@bp.route("/nrw/customer-meters/<meter_id>/accuracy-tests", methods=["GET"])
def meter_tests(meter_id):
    require_roles(READ_ROLES)
    _get_meter_or_404(meter_id)
    from flask import request
    items = [t for t in db.store["meter_accuracy_tests"].values()
             if t["meter_id"] == meter_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sort_created(items)
    page, meta = paginate(items)
    return success_list([db.serialize(t) for t in page], meta)


@bp.route("/nrw/customer-meters/<meter_id>/flag-replacement", methods=["POST"])
def flag_replacement(meter_id):
    uid, role = require_roles(MT)
    rec = _get_meter_or_404(meter_id)
    if rec["status"] != "IN_SERVICE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an IN_SERVICE meter can be flagged for replacement")
    rec["status"] = "FLAGGED_FOR_REPLACEMENT"
    db.touch(rec)
    db.append_audit("CustomerMeter", rec["id"], "FLAG_REPLACEMENT", uid, role,
                    {"before": {"status": "IN_SERVICE"},
                     "after": {"status": "FLAGGED_FOR_REPLACEMENT"}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/customer-meters/<meter_id>/replace", methods=["POST"])
def replace_meter(meter_id):
    uid, role = require_roles(MT)
    rec = _get_meter_or_404(meter_id)
    body = get_body()
    # priority 4: uniqueness of the replacement serial (before state, priority 5)
    serial = body.get("serial_number")
    if isinstance(serial, str) and _serial_taken(serial):
        raise ApiError(errors.ERR_DUPLICATE, 409,
                       "a meter with this serial_number already exists")
    # priority 5: state-machine validity
    if rec["status"] != "FLAGGED_FOR_REPLACEMENT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a FLAGGED_FOR_REPLACEMENT meter can be replaced")
    # priority 9: scalar
    serial = v_str(body, "serial_number")

    rec["status"] = "REPLACED"
    db.touch(rec)
    db.append_audit("CustomerMeter", rec["id"], "REPLACE", uid, role,
                    {"before": {"status": "FLAGGED_FOR_REPLACEMENT"},
                     "after": {"status": "REPLACED"}})

    new = db.new_record()
    new.update({
        "dma_id": rec["dma_id"],
        "serial_number": serial,
        "size_mm": rec["size_mm"],
        "installed_at": db.fmt_dt(db.logical_now()),
        "replacement_policy": rec["replacement_policy"],
        "status": "IN_SERVICE",
        "last_test_accuracy_pct": None,
        "replacement_due": False,
    })
    new["replacement_due"] = calc.compute_replacement_due(new)
    db.store["customer_meters"][new["id"]] = new
    db.append_audit("CustomerMeter", new["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(new)})
    return success_object(db.serialize(new))


@bp.route("/nrw/customer-meters/<meter_id>/retire", methods=["POST"])
def retire_meter(meter_id):
    uid, role = require_roles(MT)
    rec = _get_meter_or_404(meter_id)
    if rec["status"] != "IN_SERVICE":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only an IN_SERVICE meter can be retired")
    if any(t["meter_id"] == meter_id and t["status"] == "SCHEDULED"
           for t in db.store["meter_accuracy_tests"].values()):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "a meter with a SCHEDULED accuracy test cannot be retired")
    rec["status"] = "RETIRED"
    db.touch(rec)
    db.append_audit("CustomerMeter", rec["id"], "RETIRE", uid, role,
                    {"before": {"status": "IN_SERVICE"},
                     "after": {"status": "RETIRED"}})
    return success_object(db.serialize(rec))


# ---------------------------------------------------------------------------
# MeterAccuracyTest
# ---------------------------------------------------------------------------

@bp.route("/nrw/meter-accuracy-tests", methods=["POST"])
def create_test():
    uid, role = require_roles(MT)
    body = get_body()
    # priority 3: existence of body FK
    meter_id = body.get("meter_id")
    meter = db.store["customer_meters"].get(meter_id) if isinstance(meter_id, str) else None
    if meter is None:
        if not isinstance(meter_id, str):
            raise ApiError(errors.ERR_VALIDATION, 422, "meter_id must be a string")
        raise ApiError(errors.ERR_NOT_FOUND, 404, "customer meter not found")
    # priority 9: scalar constraints
    tested = v_dt(body, "tested_at")
    flow = v_num(body, "flow_rate_lps", gt=0)
    if tested < db.parse_dt(meter["installed_at"]):
        raise ApiError(errors.ERR_VALIDATION, 422,
                       "tested_at must not precede the meter's installed_at")

    rec = db.new_record()
    rec.update({
        "meter_id": meter_id,
        "tested_at": canon(tested),
        "flow_rate_lps": flow,
        "registered_volume_m3": None,
        "reference_volume_m3": None,
        "status": "SCHEDULED",
        "accuracy_pct": None,
        "result": None,
    })
    db.store["meter_accuracy_tests"][rec["id"]] = rec
    db.append_audit("MeterAccuracyTest", rec["id"], "CREATE", uid, role,
                    {"before": None, "after": db.serialize(rec)})
    return success_object(db.serialize(rec), status=201)


@bp.route("/nrw/meter-accuracy-tests/<test_id>", methods=["GET"])
def get_test(test_id):
    require_roles(READ_ROLES)
    return success_object(db.serialize(_get_test_or_404(test_id)))


@bp.route("/nrw/meter-accuracy-tests/<test_id>/complete", methods=["POST"])
def complete_test(test_id):
    uid, role = require_roles(MT)
    rec = _get_test_or_404(test_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SCHEDULED test can be completed")
    meter = _get_meter_or_404(rec["meter_id"])
    if meter["status"] not in ("IN_SERVICE", "FLAGGED_FOR_REPLACEMENT"):
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "the parent meter is not in service")
    body = get_body()
    registered = v_num(body, "registered_volume_m3", gt=0)
    reference = v_num(body, "reference_volume_m3", gt=0)

    acc = calc.r2(D(registered) / D(reference) * D(100))
    result = "PASS" if calc.ACCURACY_PASS_THRESHOLD <= acc <= calc.ACCURACY_OVER_CEILING else "FAIL"
    rec["registered_volume_m3"] = registered
    rec["reference_volume_m3"] = reference
    rec["accuracy_pct"] = float(acc)
    rec["result"] = result
    rec["status"] = "COMPLETED"
    db.touch(rec)
    db.append_audit("MeterAccuracyTest", rec["id"], "COMPLETE", uid, role,
                    {"before": {"status": "SCHEDULED"},
                     "after": {"status": "COMPLETED", "accuracy_pct": float(acc),
                               "result": result}})

    # Cross-entity cascade onto the meter.
    before_meter = {"status": meter["status"],
                    "last_test_accuracy_pct": meter["last_test_accuracy_pct"],
                    "replacement_due": meter["replacement_due"]}
    meter["last_test_accuracy_pct"] = float(acc)
    if (result == "FAIL" and meter["status"] == "IN_SERVICE"
            and meter["replacement_policy"] in ("ACCURACY_BASED", "HYBRID")):
        meter["status"] = "FLAGGED_FOR_REPLACEMENT"
    meter["replacement_due"] = calc.compute_replacement_due(meter)
    db.touch(meter)
    db.append_audit("CustomerMeter", meter["id"], "UPDATE", uid, role,
                    {"before": before_meter,
                     "after": {"status": meter["status"],
                               "last_test_accuracy_pct": meter["last_test_accuracy_pct"],
                               "replacement_due": meter["replacement_due"]}})
    return success_object(db.serialize(rec))


@bp.route("/nrw/meter-accuracy-tests/<test_id>/cancel", methods=["POST"])
def cancel_test(test_id):
    uid, role = require_roles(MT)
    rec = _get_test_or_404(test_id)
    if rec["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "only a SCHEDULED test can be cancelled")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    db.append_audit("MeterAccuracyTest", rec["id"], "CANCEL", uid, role,
                    {"before": {"status": "SCHEDULED"},
                     "after": {"status": "CANCELLED"}})
    return success_object(db.serialize(rec))
