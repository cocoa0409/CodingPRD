"""Production lot scheduling, process steps, testing, disposition and release
(PRD 3.6, 3.7)."""

from datetime import timedelta

from flask import Blueprint

import clock
import constants as C
import errors
import lookups
import response
import validation
from auth import require_auth
from db import all_sorted, db, new_record, sort_created, touch
from serializers import view, views
from services import cascades, ledger
from util import D, money, parse_iso_dt, rhu

bp = Blueprint("lots", __name__)

_READ_ROLES = (
    "ProcessEngineer",
    "QualityEngineer",
    "ShippingClerk",
    "CertificationOfficer",
    "PlantAdmin",
)

_BUFFER = timedelta(minutes=C.CHANGEOVER_BUFFER_MINUTES)


def _tests_for(lot_id):
    return [t for t in db.cable_tests.values() if t["lot_id"] == lot_id]


def _test_rank(row):
    return (row["tested_at"], row["created_at"], row["_seq"])


def _latest_test(lot_id, test_type):
    rows = [t for t in _tests_for(lot_id) if t["test_type"] == test_type]
    if not rows:
        return None
    rows.sort(key=_test_rank)
    return rows[-1]


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------
@bp.route("/production-lots", methods=["POST"])
def create_lot():
    require_auth("ProcessEngineer", "PlantAdmin")
    b = validation.body()
    product_id = validation.f_str(b, "product_id")
    rod_lot_id = validation.f_str(b, "rod_lot_id")
    order_id = validation.f_str(b, "order_id", required=False, default=None)
    lot_code = validation.f_str(b, "lot_code")
    planned_length_ft = validation.f_num(b, "planned_length_ft", gt=0)
    line_code = validation.f_str(b, "line_code")
    start_raw, start_dt = validation.f_datetime(b, "scheduled_start_at")
    end_raw, end_dt = validation.f_datetime(b, "scheduled_end_at")
    expected_version = validation.f_int(b, "expected_rod_lot_version")
    if not end_dt > start_dt:
        validation.bad("scheduled_end_at must be strictly after scheduled_start_at")

    # PRD 2.10: rod_lot_id, then product_id, then order_id.
    rod_lot = lookups.rod_lot(rod_lot_id)
    product = lookups.product(product_id)
    order = lookups.order(order_id) if order_id is not None else None

    if expected_version != rod_lot["version"]:
        errors.fail(
            errors.ERR_STALE_ROD_LOT_VERSION,
            "expected_rod_lot_version %s does not match the rod lot's current version %s"
            % (expected_version, rod_lot["version"]),
        )

    consumed = rhu(
        D(planned_length_ft) / D("1000") * D(product["conductor_lbs_per_kft"]), 2
    )

    # Rung 17: the extrusion line and its changeover buffer, before the rod check.
    for other in db.production_lots.values():
        if other["line_code"] != line_code:
            continue
        if other["process_state"] in ("SHIPPED", "SCRAP_CLOSED"):
            continue
        other_start = other["_scheduled_start_dt"]
        other_end = other["_scheduled_end_dt"]
        if start_dt < other_end + _BUFFER and other_start < end_dt + _BUFFER:
            errors.fail(
                errors.ERR_LINE_SCHEDULE_CONFLICT,
                "Line %s is already occupied within the changeover buffer" % line_code,
            )

    # Rung 24: the uncommitted bucket may never go negative.
    if D(rod_lot["remaining_lbs"]) < consumed:
        errors.fail(
            errors.ERR_INSUFFICIENT_ROD_QUANTITY,
            "Rod lot has %s lbs uncommitted but the lot would draw %s lbs"
            % (rod_lot["remaining_lbs"], consumed),
        )

    rec = new_record()
    rec.update({
        "product_id": product_id,
        "rod_lot_id": rod_lot_id,
        "order_id": order["id"] if order is not None else None,
        "lot_code": lot_code,
        "planned_length_ft": planned_length_ft,
        "line_code": line_code,
        "scheduled_start_at": start_raw,
        "scheduled_end_at": end_raw,
        "_scheduled_start_dt": start_dt,
        "_scheduled_end_dt": end_dt,
        "consumed_rod_lbs": consumed,
        "measured_min_wall_mils": None,
        "measured_max_wall_mils": None,
        "measured_avg_od_mm": None,
        "concentricity_pct": None,
        "surface_marking_text": None,
        "traceability_code": "%s-%s" % (rod_lot["heat_number"], lot_code),
        "packaged_length_ft": 0,
        "rework_count": 0,
        "released_by_user_id": None,
        "process_state": "QUEUED",
        "quality_state": "PENDING",
    })
    db.production_lots[rec["id"]] = rec
    ledger.commit_mass(rod_lot, consumed)
    return response.created(view("production_lot", rec))


@bp.route("/production-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    require_auth(*_READ_ROLES)
    rec = lookups.lot(lot_id)
    return response.ok(view("production_lot", rec))


@bp.route("/production-lots", methods=["GET"])
def list_lots():
    require_auth(*_READ_ROLES)
    limit, offset = validation.pagination()
    product_id = validation.q_str("product_id")
    rod_lot_id = validation.q_str("rod_lot_id")
    order_id = validation.q_str("order_id")
    line_code = validation.q_str("line_code")
    process_state = validation.q_enum("process_state", C.PROCESS_STATES)
    quality_state = validation.q_enum("quality_state", C.QUALITY_STATES)

    rows = all_sorted(db.production_lots)
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if rod_lot_id is not None:
        rows = [r for r in rows if r["rod_lot_id"] == rod_lot_id]
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if line_code is not None:
        rows = [r for r in rows if r["line_code"] == line_code]
    if process_state is not None:
        rows = [r for r in rows if r["process_state"] == process_state]
    if quality_state is not None:
        rows = [r for r in rows if r["quality_state"] == quality_state]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("production_lot", page), limit, offset, total)


# --------------------------------------------------------------------------
# Process steps
# --------------------------------------------------------------------------
@bp.route("/production-lots/<lot_id>/process-steps", methods=["POST"])
def record_process_step(lot_id):
    require_auth("ProcessEngineer", "PlantAdmin")
    b = validation.body()
    step = validation.f_enum(b, "step", C.PROCESS_STEPS)
    min_wall = validation.f_num(b, "measured_min_wall_mils", required=False, default=None, gt=0)
    max_wall = validation.f_num(b, "measured_max_wall_mils", required=False, default=None, gt=0)
    avg_od = validation.f_num(b, "measured_avg_od_mm", required=False, default=None, gt=0)
    marking = validation.f_str(
        b, "surface_marking_text", required=False, default=None, allow_empty=True
    )

    lot = lookups.lot(lot_id)
    product = db.catalog_products[lot["product_id"]]
    process = lot["process_state"]
    solid = product["conductor_construction"] == "SOLID"

    if step == "DRAWING":
        if process != "QUEUED" or lot["quality_state"] not in ("PENDING", "REWORK"):
            errors.fail(
                errors.ERR_INVALID_LOT_STATE,
                "Drawing requires a QUEUED lot whose quality state is PENDING or REWORK",
            )
        if product["status"] != "RELEASED":
            errors.fail(
                errors.ERR_INVALID_PRODUCT_STATE,
                "The lot's SKU must be RELEASED to start drawing (it is %s)" % product["status"],
            )
        lot["process_state"] = "DRAWN"
        touch(lot)
        return response.ok(view("production_lot", lot))

    if step == "STRANDING":
        if process != "DRAWN" or solid:
            errors.fail(
                errors.ERR_INVALID_LOT_STATE,
                "Stranding requires a DRAWN lot on a non-SOLID construction",
            )
        lot["process_state"] = "STRANDED"
        touch(lot)
        return response.ok(view("production_lot", lot))

    # EXTRUSION
    admissible = (process == "STRANDED") or (process == "DRAWN" and solid)
    if not admissible:
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Extrusion is admissible from STRANDED, or from DRAWN for a SOLID construction",
        )

    # Rung 11: traceability marking on building wire is not negotiable and is
    # checked before the measurements are even considered.
    if product["marking_required"]:
        if marking != product["required_marking_text"]:
            errors.fail(
                errors.ERR_MARKING_MISMATCH,
                "surface_marking_text must equal the SKU's required_marking_text exactly",
            )

    if min_wall is None or max_wall is None or avg_od is None:
        validation.bad(
            "The EXTRUSION step requires measured_min_wall_mils, "
            "measured_max_wall_mils and measured_avg_od_mm"
        )

    lot["measured_min_wall_mils"] = min_wall
    lot["measured_max_wall_mils"] = max_wall
    lot["measured_avg_od_mm"] = avg_od
    lot["surface_marking_text"] = marking
    concentricity = rhu(D("100") * D(min_wall) / D(max_wall), 2)
    lot["concentricity_pct"] = concentricity
    lot["process_state"] = "EXTRUDED"
    # The in-line gate applies concentricity only; the minimum-wall gate is
    # deferred to release.
    if lot["quality_state"] == "PENDING" and concentricity < D(product["concentricity_min_pct"]):
        lot["quality_state"] = "NONCONFORMING"
    touch(lot)
    return response.ok(view("production_lot", lot))


# --------------------------------------------------------------------------
# Electrical testing
# --------------------------------------------------------------------------
@bp.route("/production-lots/<lot_id>/tests", methods=["POST"])
def record_test(lot_id):
    actor = require_auth("QualityEngineer", "PlantAdmin")
    b = validation.body()
    test_type = validation.f_enum(b, "test_type", C.TEST_TYPES)
    duration_sec = validation.f_int(b, "duration_sec", gt=0)
    test_voltage_kv = validation.f_num(b, "test_voltage_kv", required=False, default=None, gt=0)
    faults = validation.f_int(b, "faults_detected", required=False, default=0, ge=0)
    breakdown = validation.f_bool(b, "breakdown_detected", default=False)
    pd_level = validation.f_num(b, "pd_level_pc", required=False, default=None)
    if test_type == "HIPOT" and test_voltage_kv is None:
        validation.bad("test_voltage_kv is mandatory on a HIPOT test")
    if test_type == "PARTIAL_DISCHARGE" and pd_level is None:
        validation.bad("pd_level_pc is mandatory on a PARTIAL_DISCHARGE test")

    lot = lookups.lot(lot_id)
    # In-line testing happens on an EXTRUDED lot. Partial discharge is the
    # off-line laboratory test whose result routinely lags the line, so it is
    # also accepted against a lot the in-line pair has already promoted to
    # TESTED (PRD 3.7: "an MV lot sitting at TESTED without a PD result").
    admissible = ("EXTRUDED", "TESTED") if test_type == "PARTIAL_DISCHARGE" else ("EXTRUDED",)
    if lot["process_state"] not in admissible:
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Tests may only be recorded against an EXTRUDED lot (this one is %s)"
            % lot["process_state"],
        )
    product = db.catalog_products[lot["product_id"]]
    voltage_class = product["voltage_class"]

    if test_type == "SPARK":
        result = "PASS" if faults <= C.SPARK_MAX_FAULTS else "FAIL"
    elif test_type == "HIPOT":
        if breakdown:
            result = "FAIL"
        else:
            required_kv = C.HIPOT_REQUIRED_KV[voltage_class]
            result = "PASS" if D(test_voltage_kv) >= required_kv else "FAIL"
    else:
        limit_pc = C.PD_LIMIT_PC.get(voltage_class, D("5.0"))
        result = "PASS" if rhu(pd_level, 1) <= limit_pc else "FAIL"

    row = new_record(common_fields=False)
    row.update({
        "lot_id": lot["id"],
        "test_type": test_type,
        "operator_user_id": actor.user_id,
        "test_voltage_kv": test_voltage_kv,
        "faults_detected": faults,
        "breakdown_detected": breakdown,
        "pd_level_pc": pd_level,
        "duration_sec": duration_sec,
        "tested_at": clock.now_iso(),
        "result": result,
    })
    db.cable_tests[row["id"]] = row

    if result == "FAIL":
        if lot["quality_state"] == "PENDING":
            lot["quality_state"] = "NONCONFORMING"
            touch(lot)
    else:
        spark = _latest_test(lot["id"], "SPARK")
        hipot = _latest_test(lot["id"], "HIPOT")
        promoted = (
            spark is not None and spark["result"] == "PASS"
            and hipot is not None and hipot["result"] == "PASS"
        )
        if promoted and lot["process_state"] == "EXTRUDED":
            lot["process_state"] = "TESTED"
            touch(lot)

    return response.created(view("cable_test", row))


@bp.route("/production-lots/<lot_id>/tests", methods=["GET"])
def list_tests(lot_id):
    require_auth("QualityEngineer", "ProcessEngineer", "CertificationOfficer", "PlantAdmin")
    limit, offset = validation.pagination()
    test_type = validation.q_enum("test_type", C.TEST_TYPES)
    result = validation.q_enum("result", ("PASS", "FAIL"))
    lot = lookups.lot(lot_id)

    rows = sort_created(_tests_for(lot["id"]))
    if test_type is not None:
        rows = [r for r in rows if r["test_type"] == test_type]
    if result is not None:
        rows = [r for r in rows if r["result"] == result]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("cable_test", page), limit, offset, total)


# --------------------------------------------------------------------------
# Disposition
# --------------------------------------------------------------------------
@bp.route("/production-lots/<lot_id>/disposition", methods=["POST"])
def disposition_lot(lot_id):
    require_auth("QualityEngineer", "PlantAdmin")
    b = validation.body()
    disposition = validation.f_enum(b, "disposition", C.DISPOSITIONS)
    validation.f_str(b, "rewind_to", required=False, default=None, allow_empty=True)
    validation.f_str(b, "reason", required=False, default=None, allow_empty=True)

    lot = lookups.lot(lot_id)
    if lot["quality_state"] != "NONCONFORMING":
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Only a NONCONFORMING lot may be dispositioned (this one is %s)"
            % lot["quality_state"],
        )
    product = db.catalog_products[lot["product_id"]]

    if disposition == "REWORK":
        if lot["process_state"] != "EXTRUDED":
            errors.fail(
                errors.ERR_INVALID_LOT_STATE,
                "A REWORK disposition is available from EXTRUDED only",
            )
        if lot["rework_count"] >= C.REWORK_LIMIT:
            errors.fail(
                errors.ERR_REWORK_LIMIT_EXCEEDED,
                "The lot has already been reworked %d times and must be scrapped"
                % lot["rework_count"],
            )
        lot["measured_min_wall_mils"] = None
        lot["measured_max_wall_mils"] = None
        lot["measured_avg_od_mm"] = None
        lot["concentricity_pct"] = None
        lot["surface_marking_text"] = None
        lot["rework_count"] = lot["rework_count"] + 1
        lot["process_state"] = (
            "DRAWN" if product["conductor_construction"] == "SOLID" else "STRANDED"
        )
        # The quality dimension passes through REWORK and ends at PENDING; the
        # transient is observable only in this response.
        lot["quality_state"] = "PENDING"
        touch(lot)
        payload = view("production_lot", lot)
        payload["quality_state"] = "REWORK"
        return response.ok(payload)

    # SCRAPPED
    if lot["process_state"] not in ("DRAWN", "STRANDED", "EXTRUDED", "TESTED"):
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "A SCRAPPED disposition is available from DRAWN, STRANDED, EXTRUDED or TESTED",
        )
    lot["process_state"] = "SCRAP_CLOSED"
    lot["quality_state"] = "SCRAPPED"
    touch(lot)
    cascades.lot_scrapped(lot)
    return response.ok(view("production_lot", lot))


# --------------------------------------------------------------------------
# Release to packaging
# --------------------------------------------------------------------------
@bp.route("/production-lots/<lot_id>/release", methods=["POST"])
def release_lot(lot_id):
    actor = require_auth("QualityEngineer", "PlantAdmin")
    b = validation.body()
    packaged_length_ft = validation.f_num(b, "packaged_length_ft", ge=0)

    lot = lookups.lot(lot_id)
    if lot["process_state"] != "TESTED" or lot["quality_state"] != "PENDING":
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Release requires a TESTED lot whose quality state is PENDING",
        )
    product = db.catalog_products[lot["product_id"]]

    # Rung 11: marking.
    if product["marking_required"] and lot["surface_marking_text"] != product["required_marking_text"]:
        errors.fail(
            errors.ERR_MARKING_MISMATCH,
            "The lot's stored surface marking no longer matches the SKU's required print",
        )

    # Rung 12: dimensional conformance (both comparisons inclusive).
    required_min_wall = rhu(
        D(product["insulation_thickness_mils"]) * D(product["min_wall_pct"]) / D("100"), 2
    )
    concentricity = lot["concentricity_pct"]
    min_wall = lot["measured_min_wall_mils"]
    if (
        concentricity is None
        or min_wall is None
        or D(concentricity) < D(product["concentricity_min_pct"])
        or D(min_wall) < required_min_wall
    ):
        errors.fail(
            errors.ERR_DIMENSIONAL_NONCONFORMANCE,
            "The lot's concentricity or minimum wall falls short of the SKU tolerance",
        )

    # Rung 13: the required test set, by latest row per type.
    required_types = ["SPARK", "HIPOT"]
    if product["pd_test_required"]:
        required_types.append("PARTIAL_DISCHARGE")
    for test_type in required_types:
        latest = _latest_test(lot["id"], test_type)
        if latest is None or latest["result"] != "PASS":
            errors.fail(
                errors.ERR_REQUIRED_TESTS_INCOMPLETE,
                "The latest %s result is missing or not a PASS" % test_type,
            )

    # Rung 14: any failed row at all, superseded or not.
    rows = _tests_for(lot["id"])
    for row in rows:
        if row["result"] == "FAIL":
            errors.fail(
                errors.ERR_LOT_TEST_FAILED,
                "The lot carries a failed test row and can only be reworked or scrapped",
            )

    # Rung 15: segregation of duties.
    for row in rows:
        if row["operator_user_id"] == actor.user_id:
            errors.fail(
                errors.ERR_SEGREGATION_OF_DUTIES,
                "A quality engineer who tested the lot may not release it",
            )

    # Rung 21: the listing file.
    cert = db.listing_certifications.get(product["listing_certification_id"])
    if cert is None or cert["status"] != "ACTIVE":
        errors.fail(
            errors.ERR_CERTIFICATION_NOT_ACTIVE,
            "The SKU's listing file must be ACTIVE to release the lot",
        )

    lot["released_by_user_id"] = actor.user_id
    lot["packaged_length_ft"] = packaged_length_ft
    lot["quality_state"] = "CONFORMING"
    touch(lot)
    return response.ok(view("production_lot", lot))
