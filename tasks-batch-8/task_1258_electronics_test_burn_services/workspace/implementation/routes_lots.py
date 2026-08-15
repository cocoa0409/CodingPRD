"""Routes: lots, units, test results, retest authorizations."""
from datetime import timedelta

from flask import Blueprint

from auth import require_roles, ALL_ROLES
from db import db
from envelope import success
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_FORBIDDEN_OWNERSHIP, ERR_CUSTOMER_SUSPENDED,
    ERR_PROGRAM_NOT_RELEASED, ERR_PROGRAM_SUPERSEDED, ERR_FIXTURE_NOT_AVAILABLE,
    ERR_FIXTURE_PROGRAM_MISMATCH, ERR_EQUIPMENT_NOT_IN_SERVICE, ERR_BIN_NOT_MAPPED,
    ERR_RESULT_IMMUTABLE, ERR_NO_ACTIVE_AUTHORIZATION, ERR_AUTHORIZATION_EXPIRED,
    ERR_RETEST_SEGREGATION, ERR_HARD_FAIL_NO_RETEST, ERR_RETEST_LIMIT_REACHED,
    ERR_DUPLICATE_SERIAL, ERR_QUANTITY_EXCEEDED, ERR_UNITS_INCOMPLETE,
    ERR_DISPOSITION_REVIEW_REQUIRED,
    bad_request, invalid_state,
)
from services import (
    stamp_new, touch, get_or_404, sorted_by_creation, lot_units, lot_tallies,
    lot_yields, compute_suggestion, bin_counts, unit_effective_results, unit_state,
    equipment_effective_status, auth_effective_status,
    ser_lot, ser_unit, ser_result, ser_authorization,
)
from util import (
    fmt_ms, sec, ratio4, json_body, require_fields, check_int, check_str,
)
from routes_core import paginate, filter_list

bp = Blueprint("lots", __name__)


def _create_pending_review(lot):
    rec = stamp_new({
        "lot_id": lot["id"], "suggested_disposition": lot["suggested_disposition"],
        "decision": None, "rationale": None, "decided_by_user_id": None,
        "status": "PENDING",
    })
    db.reviews[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# lots
# ---------------------------------------------------------------------------

@bp.route("/api/lots", methods=["POST"])
def create_lot():
    uid, role = require_roles("CustomerRep")
    data = json_body()
    require_fields(data, "customer_id", "part_number", "quantity", "program_id")
    check_str(data["customer_id"], "customer_id")
    part_number = check_str(data["part_number"], "part_number")
    quantity = check_int(data["quantity"], "quantity", minimum=1)
    check_str(data["program_id"], "program_id")
    # ownership: CustomerRep may only act within their own customer scope
    if data["customer_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "customer_id must equal the acting CustomerRep's id")
    # existence, body field order: customer_id then program_id
    cust = get_or_404(db.customers, data["customer_id"], "customer")
    program = get_or_404(db.programs, data["program_id"], "test program")
    # business safety: account standing
    if cust["account_status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, 409, "Customer account is suspended")
    # business referential: program must be RELEASED
    if program["status"] != "RELEASED":
        raise ApiError(ERR_PROGRAM_NOT_RELEASED, 422, "Program is not RELEASED")
    # business constraint: part number must agree with the program
    if part_number != program["part_number"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "part_number does not match the program's part_number")
    rec = stamp_new({
        "customer_id": cust["id"], "program_id": program["id"],
        "part_number": part_number, "quantity": quantity,
        "status": "RECEIVED", "suggested_disposition": None,
    })
    db.lots[rec["id"]] = rec
    return success(ser_lot(rec), "object", 201)


@bp.route("/api/lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.lots, lot_id, "lot")
    return success(ser_lot(rec), "object", 200)


@bp.route("/api/lots", methods=["GET"])
def list_lots():
    require_roles(*ALL_ROLES)
    items = filter_list(db.lots, [
        ("customer_id", "customer_id"), ("program_id", "program_id"),
        ("status", "status"),
    ])
    page, meta = paginate(items)
    return success([ser_lot(l) for l in page], "array", 200, meta)


@bp.route("/api/lots/<lot_id>/enqueue", methods=["POST"])
def enqueue_lot(lot_id):
    require_roles("OperationsManager")
    lot = get_or_404(db.lots, lot_id, "lot")
    if lot["status"] != "RECEIVED":
        raise invalid_state("Only a RECEIVED lot can be enqueued")
    program = db.programs[lot["program_id"]]
    if program["status"] != "RELEASED":
        raise ApiError(ERR_PROGRAM_NOT_RELEASED, 422, "Program is not RELEASED")
    t = lot_tallies(lot)
    if t["units_registered"] != lot["quantity"]:
        raise ApiError(ERR_UNITS_INCOMPLETE, 409,
                       "All units must be registered before enqueue")
    lot["status"] = "QUEUED"
    touch(lot)
    return success(ser_lot(lot), "object", 200)


@bp.route("/api/lots/<lot_id>/start-test", methods=["POST"])
def start_test_lot(lot_id):
    require_roles("OperationsManager")
    lot = get_or_404(db.lots, lot_id, "lot")
    if lot["status"] != "QUEUED":
        raise invalid_state("Only a QUEUED lot can start test")
    lot["status"] = "IN_TEST"
    touch(lot)
    return success(ser_lot(lot), "object", 200)


@bp.route("/api/lots/<lot_id>/complete-test", methods=["POST"])
def complete_test_lot(lot_id):
    require_roles("OperationsManager")
    lot = get_or_404(db.lots, lot_id, "lot")
    if lot["status"] != "IN_TEST":
        raise invalid_state("Only an IN_TEST lot can complete test")
    t = lot_tallies(lot)
    if t["units_untested"] != 0:
        raise ApiError(ERR_UNITS_INCOMPLETE, 409,
                       "All units must be tested before completing test")
    lot["status"] = "AWAITING_DISPOSITION"
    lot["suggested_disposition"] = compute_suggestion(lot)
    touch(lot)
    if lot["suggested_disposition"] != "SHIP":
        _create_pending_review(lot)
    return success(ser_lot(lot), "object", 200)


@bp.route("/api/lots/<lot_id>/ship", methods=["POST"])
def ship_lot(lot_id):
    require_roles("OperationsManager")
    lot = get_or_404(db.lots, lot_id, "lot")
    if lot["status"] != "AWAITING_DISPOSITION":
        raise invalid_state("Only an AWAITING_DISPOSITION lot can be shipped")
    pending = any(
        rv["lot_id"] == lot["id"] and rv["status"] == "PENDING"
        for rv in db.reviews.values()
    )
    if lot["suggested_disposition"] != "SHIP" or pending:
        raise ApiError(ERR_DISPOSITION_REVIEW_REQUIRED, 409,
                       "Direct ship requires suggestion SHIP and no PENDING review")
    lot["status"] = "SHIPPED"
    touch(lot)
    return success(ser_lot(lot), "object", 200)


@bp.route("/api/lots/<lot_id>/yield-report", methods=["GET"])
def lot_yield_report(lot_id):
    require_roles(*ALL_ROLES)
    lot = get_or_404(db.lots, lot_id, "lot")
    t = lot_tallies(lot)
    fpy, final = lot_yields(lot)
    return success({
        "lot_id": lot["id"],
        "first_pass_yield": ratio4(fpy),
        "final_yield": ratio4(final),
        "units_registered": t["units_registered"],
        "units_passed": t["units_passed"],
        "units_failed": t["units_failed"],
        "units_untested": t["units_untested"],
        "retested_unit_count": t["retested_unit_count"],
        "escape_count": t["escape_count"],
        "bin_counts": bin_counts(lot["id"]),
        "suggested_disposition": lot["suggested_disposition"],
    }, "object", 200)


# ---------------------------------------------------------------------------
# units
# ---------------------------------------------------------------------------

@bp.route("/api/units", methods=["POST"])
def create_unit():
    uid, role = require_roles("OperationsManager", "CustomerRep")
    data = json_body()
    require_fields(data, "lot_id", "serial_number")
    check_str(data["lot_id"], "lot_id")
    serial = check_str(data["serial_number"], "serial_number")
    lot = get_or_404(db.lots, data["lot_id"], "lot")
    if role == "CustomerRep" and lot["customer_id"] != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403,
                       "CustomerRep may only register units on their own lots")
    if lot["status"] != "RECEIVED":
        raise invalid_state("Units may only be registered on a RECEIVED lot")
    for u in lot_units(lot["id"]):
        if u["serial_number"] == serial:
            raise ApiError(ERR_DUPLICATE_SERIAL, 409,
                           "serial_number already registered within the lot")
    if len(lot_units(lot["id"])) >= lot["quantity"]:
        raise ApiError(ERR_QUANTITY_EXCEEDED, 422,
                       "Unit registration would exceed the lot quantity")
    rec = stamp_new({
        "lot_id": lot["id"], "serial_number": serial,
        "retest_count": 0, "force_failed": False,
    })
    db.units[rec["id"]] = rec
    return success(ser_unit(rec), "object", 201)


@bp.route("/api/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.units, unit_id, "unit")
    return success(ser_unit(rec), "object", 200)


@bp.route("/api/units", methods=["GET"])
def list_units():
    require_roles(*ALL_ROLES)
    items = filter_list(db.units, [("lot_id", "lot_id")])
    status_filter = None
    from flask import request as _req
    if _req.args.get("test_status") is not None:
        status_filter = _req.args.get("test_status")
        items = [u for u in items if unit_state(u)[0] == status_filter]
    page, meta = paginate(items)
    return success([ser_unit(u) for u in page], "array", 200, meta)


# ---------------------------------------------------------------------------
# test results
# ---------------------------------------------------------------------------

@bp.route("/api/test-results", methods=["POST"])
def create_test_result():
    uid, role = require_roles("TestEngineer")
    data = json_body()
    require_fields(data, "unit_id", "fixture_id", "bin_code")
    check_str(data["unit_id"], "unit_id")
    check_str(data["fixture_id"], "fixture_id")
    bin_code = data["bin_code"]
    if isinstance(bin_code, bool) or not isinstance(bin_code, int):
        if isinstance(bin_code, str) and bin_code.lstrip("-").isdigit():
            bin_code = int(bin_code)
        else:
            raise bad_request("bin_code must be an integer")
    equipment_id = data.get("equipment_id")
    # existence, body field order: unit_id, fixture_id, equipment_id
    unit = get_or_404(db.units, data["unit_id"], "unit")
    fixture = get_or_404(db.fixtures, data["fixture_id"], "fixture")
    equip = None
    if equipment_id is not None:
        equip = get_or_404(db.equipment, equipment_id, "customer equipment")
    lot = db.lots[unit["lot_id"]]
    program = db.programs[lot["program_id"]]
    # priority 4: lot IN_TEST
    if lot["status"] != "IN_TEST":
        raise invalid_state("Results can only be recorded while the lot is IN_TEST")
    # priority 8: program not OBSOLETE; fixture AVAILABLE + lineage; equipment in service
    if program["status"] == "OBSOLETE":
        raise ApiError(ERR_PROGRAM_SUPERSEDED, 409,
                       "The lot's pinned program revision is OBSOLETE")
    if fixture["status"] != "AVAILABLE":
        raise ApiError(ERR_FIXTURE_NOT_AVAILABLE, 409, "Fixture is not AVAILABLE")
    if fixture["program_id"] != lot["program_id"]:
        raise ApiError(ERR_FIXTURE_PROGRAM_MISMATCH, 422,
                       "Fixture does not belong to the lot's program")
    if equip is not None and equipment_effective_status(equip) != "IN_SERVICE":
        raise ApiError(ERR_EQUIPMENT_NOT_IN_SERVICE, 409,
                       "Equipment is not effectively IN_SERVICE")
    # priority 9: bin mapped
    bin_class = program["bin_map"].get(str(bin_code))
    if bin_class is None:
        raise ApiError(ERR_BIN_NOT_MAPPED, 422, "bin_code is not mapped in the program")
    status, _ = unit_state(unit)
    if status == "PASSED":
        raise ApiError(ERR_RESULT_IMMUTABLE, 409,
                       "A PASSED unit accepts no further insertions")
    consumed = None
    if status == "FAILED":
        auths = [
            a for a in db.authorizations.values()
            if a["unit_id"] == unit["id"] and a["status"] == "ACTIVE"
        ]
        if not auths:
            raise ApiError(ERR_NO_ACTIVE_AUTHORIZATION, 409,
                           "A retest insertion requires an ACTIVE authorization")
        auths.sort(key=lambda a: a["_seq"])
        live = [a for a in auths if sec(a["_expires_dt"]) > sec(db.clock_dt)]
        if not live:
            raise ApiError(ERR_AUTHORIZATION_EXPIRED, 409,
                           "The retest authorization has expired")
        consumed = live[0]
    effective = unit_effective_results(unit["id"])
    rec = {
        "id": None, "unit_id": unit["id"], "lot_id": lot["id"],
        "program_id": program["id"], "fixture_id": fixture["id"],
        "equipment_id": equipment_id, "bin_code": bin_code,
        "passed": bin_class == "PASS",
        "insertion_index": len(effective) + 1,
        "recorded_by_user_id": uid,
        "consumed_authorization_id": None,
        "voided": False, "void_reason": None, "excluded_from_tally": False,
    }
    # TestResult carries only id + created_at (immutable event record).
    import uuid as _uuid
    rec["id"] = str(_uuid.uuid4())
    from services import now_str
    rec["created_at"] = now_str()
    rec["_seq"] = db.next_seq()
    if consumed is not None:
        consumed["status"] = "CONSUMED"
        touch(consumed)
        rec["consumed_authorization_id"] = consumed["id"]
        unit["retest_count"] += 1
        touch(unit)
    db.results[rec["id"]] = rec
    return success(ser_result(rec), "object", 201)


@bp.route("/api/test-results/<result_id>", methods=["GET"])
def get_test_result(result_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.results, result_id, "test result")
    return success(ser_result(rec), "object", 200)


@bp.route("/api/test-results", methods=["GET"])
def list_test_results():
    require_roles(*ALL_ROLES)
    items = filter_list(db.results, [
        ("unit_id", "unit_id"), ("lot_id", "lot_id"), ("fixture_id", "fixture_id"),
        ("equipment_id", "equipment_id"), ("program_id", "program_id"),
    ])
    page, meta = paginate(items)
    return success([ser_result(r) for r in page], "array", 200, meta)


@bp.route("/api/test-results/<result_id>/void", methods=["POST"])
def void_test_result(result_id):
    require_roles("QualityEngineer")
    rec = get_or_404(db.results, result_id, "test result")
    data = json_body()
    require_fields(data, "reason")
    reason = check_str(data["reason"], "reason")
    unit = db.units[rec["unit_id"]]
    lot = db.lots[rec["lot_id"]]
    if lot["status"] == "SHIPPED":
        raise invalid_state("Results cannot be voided on a SHIPPED lot")
    if rec["voided"]:
        raise ApiError(ERR_RESULT_IMMUTABLE, 409, "Result is already voided")
    effective = unit_effective_results(unit["id"])
    if not effective or effective[-1]["id"] != rec["id"]:
        raise invalid_state("Only the unit's latest tally-effective result may be voided")
    rec["voided"] = True
    rec["void_reason"] = reason
    return success(ser_result(rec), "object", 200)


# ---------------------------------------------------------------------------
# retest authorizations
# ---------------------------------------------------------------------------

@bp.route("/api/retest-authorizations", methods=["POST"])
def create_authorization():
    uid, role = require_roles("TestEngineer")
    data = json_body()
    require_fields(data, "unit_id", "reason")
    check_str(data["unit_id"], "unit_id")
    reason = check_str(data["reason"], "reason")
    unit = get_or_404(db.units, data["unit_id"], "unit")
    status, current_bin = unit_state(unit)
    if status != "FAILED":
        raise invalid_state("Retest authorization requires a FAILED unit")
    effective = unit_effective_results(unit["id"])
    latest = effective[-1]
    if latest["recorded_by_user_id"] == uid:
        raise ApiError(ERR_RETEST_SEGREGATION, 403,
                       "The recorder of the latest result may not authorize its retest")
    lot = db.lots[unit["lot_id"]]
    program = db.programs[lot["program_id"]]
    bin_class = program["bin_map"].get(str(current_bin))
    if bin_class != "SOFT_FAIL":
        raise ApiError(ERR_HARD_FAIL_NO_RETEST, 422,
                       "Only SOFT_FAIL units may be retested")
    if unit["retest_count"] >= program["max_retests_per_unit"]:
        raise ApiError(ERR_RETEST_LIMIT_REACHED, 422,
                       "Retest count has reached the program ceiling")
    expires_dt = db.clock_dt + timedelta(hours=48)
    rec = stamp_new({
        "unit_id": unit["id"], "reason": reason, "authorized_by_user_id": uid,
        "expires_at": fmt_ms(expires_dt), "_expires_dt": expires_dt,
        "status": "ACTIVE",
    })
    db.authorizations[rec["id"]] = rec
    return success(ser_authorization(rec), "object", 201)


@bp.route("/api/retest-authorizations/<authorization_id>", methods=["GET"])
def get_authorization(authorization_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.authorizations, authorization_id, "retest authorization")
    return success(ser_authorization(rec), "object", 200)


@bp.route("/api/retest-authorizations", methods=["GET"])
def list_authorizations():
    require_roles(*ALL_ROLES)
    items = filter_list(db.authorizations, [("unit_id", "unit_id")])
    from flask import request as _req
    if _req.args.get("status") is not None:
        sf = _req.args.get("status")
        items = [a for a in items if auth_effective_status(a) == sf]
    page, meta = paginate(items)
    return success([ser_authorization(a) for a in page], "array", 200, meta)


@bp.route("/api/retest-authorizations/<authorization_id>/revoke", methods=["POST"])
def revoke_authorization(authorization_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.authorizations, authorization_id, "retest authorization")
    if auth_effective_status(rec) != "ACTIVE":
        raise invalid_state("Only an ACTIVE authorization can be revoked")
    rec["status"] = "REVOKED"
    touch(rec)
    return success(ser_authorization(rec), "object", 200)
