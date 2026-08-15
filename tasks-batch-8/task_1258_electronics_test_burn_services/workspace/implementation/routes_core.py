"""Routes: clock, customers, test programs, fixtures, chambers, reservations."""
from datetime import timedelta
from fractions import Fraction

from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from db import db
from envelope import success
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_STALE_VERSION, ERR_ESD_CONTAINMENT, ERR_SLOT_CAPACITY_EXCEEDED,
    ERR_PROFILE_NOT_SUPPORTED, ERR_FIXTURE_NOT_AVAILABLE,
    ERR_FIXTURE_PROGRAM_MISMATCH, ERR_CHAMBER_NOT_ONLINE, ERR_NO_AVAILABLE_FIXTURE,
    not_found, bad_request, invalid_state,
)
from services import (
    stamp_new, touch, get_or_404, sorted_by_creation, chamber_available_slots,
    cancel_reservation, esd_area_contained, burn_profile_duration,
    check_overlap, check_purge_buffer,
    ser_customer, ser_program, ser_fixture, ser_chamber, ser_reservation,
)
from util import (
    parse_dt, fmt_like, sec, minutes_between, ratio4, num_or_int,
    json_body, require_fields, check_enum, check_int, check_str, check_bool,
)

bp = Blueprint("core", __name__)

PROFILE_CLASSES = ("A", "B", "C")
BIN_CLASSES = ("PASS", "SOFT_FAIL", "HARD_FAIL")


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def paginate(items):
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise bad_request("limit and offset must be integers")
    if isinstance(raw_limit, str) and raw_limit.strip() == "":
        raise bad_request("limit must be an integer")
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def filter_list(coll, filters):
    """filters: list of (query_param_name, record_field). Exact equality."""
    items = list(coll.values())
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            items = [r for r in items if str(r.get(field)) == val]
    return sorted_by_creation(items)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "to_iso8601")
    dt = parse_dt(data["to_iso8601"], "to_iso8601")
    db.clock_dt = dt
    db.clock_raw = data["to_iso8601"].strip() if isinstance(data["to_iso8601"], str) else fmt_like(dt, None)
    return success({"current_utc": db.clock_raw}, "object", 200)


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------

@bp.route("/api/customers", methods=["POST"])
def create_customer():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "name", "tier")
    name = check_str(data["name"], "name")
    tier = check_enum(data["tier"], ("STANDARD", "STRATEGIC"), "tier")
    req_esd = data.get("requires_esd_certification", False)
    if "requires_esd_certification" in data and data["requires_esd_certification"] is not None:
        req_esd = check_bool(data["requires_esd_certification"], "requires_esd_certification")
    rec = stamp_new({
        "name": name, "tier": tier, "requires_esd_certification": req_esd,
        "account_status": "ACTIVE",
    })
    db.customers[rec["id"]] = rec
    return success(ser_customer(rec), "object", 201)


@bp.route("/api/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.customers, customer_id, "customer")
    return success(ser_customer(rec), "object", 200)


@bp.route("/api/customers/<customer_id>", methods=["PATCH"])
def patch_customer(customer_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.customers, customer_id, "customer")
    data = json_body()
    if "account_status" in data and data["account_status"] is not None:
        rec["account_status"] = check_enum(
            data["account_status"], ("ACTIVE", "SUSPENDED"), "account_status"
        )
    if "tier" in data and data["tier"] is not None:
        rec["tier"] = check_enum(data["tier"], ("STANDARD", "STRATEGIC"), "tier")
    touch(rec)
    return success(ser_customer(rec), "object", 200)


# ---------------------------------------------------------------------------
# test programs
# ---------------------------------------------------------------------------

def _validate_bin_map(bin_map):
    if not isinstance(bin_map, dict) or not bin_map:
        raise bad_request("bin_map must be a non-empty object")
    for k, v in bin_map.items():
        if not isinstance(k, str):
            raise bad_request("bin_map keys must be strings of integers")
        if v not in BIN_CLASSES:
            raise bad_request("bin_map values must be PASS, SOFT_FAIL or HARD_FAIL")
    return bin_map


def _validate_burn_profile(profile):
    if not isinstance(profile, list):
        raise bad_request("burn_profile must be an array")
    for seg in profile:
        if not isinstance(seg, dict):
            raise bad_request("burn_profile segments must be objects")
        for f in ("target_temp_c", "ramp_rate_c_per_min", "soak_minutes"):
            if f not in seg or seg[f] is None:
                raise bad_request(f"burn_profile segment missing {f}")
            if isinstance(seg[f], bool) or not isinstance(seg[f], (int, float)):
                raise bad_request(f"burn_profile {f} must be a number")
        if seg["ramp_rate_c_per_min"] <= 0:
            raise bad_request("ramp_rate_c_per_min must be > 0")
        if seg["soak_minutes"] < 0:
            raise bad_request("soak_minutes must be >= 0")
    return profile


@bp.route("/api/test-programs", methods=["POST"])
def create_program():
    require_roles("TestEngineer")
    data = json_body()
    require_fields(data, "customer_id", "part_number", "bin_map",
                   "max_retests_per_unit", "burn_profile")
    check_str(data["customer_id"], "customer_id")
    part_number = check_str(data["part_number"], "part_number")
    max_retests = check_int(data["max_retests_per_unit"], "max_retests_per_unit", minimum=0)
    bin_map = _validate_bin_map(data["bin_map"])
    burn_profile = _validate_burn_profile(data["burn_profile"])
    get_or_404(db.customers, data["customer_id"], "customer")
    rec = stamp_new({
        "customer_id": data["customer_id"], "part_number": part_number,
        "revision": 1, "supersedes_program_id": None,
        "bin_map": bin_map, "max_retests_per_unit": max_retests,
        "burn_profile": burn_profile, "status": "DRAFT",
    })
    db.programs[rec["id"]] = rec
    return success(ser_program(rec), "object", 201)


@bp.route("/api/test-programs/<program_id>", methods=["GET"])
def get_program(program_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.programs, program_id, "test program")
    return success(ser_program(rec), "object", 200)


@bp.route("/api/test-programs", methods=["GET"])
def list_programs():
    require_roles(*ALL_ROLES)
    items = filter_list(db.programs, [
        ("customer_id", "customer_id"),
        ("supersedes_program_id", "supersedes_program_id"),
        ("status", "status"),
    ])
    page, meta = paginate(items)
    return success([ser_program(p) for p in page], "array", 200, meta)


@bp.route("/api/test-programs/<program_id>/validate", methods=["POST"])
def validate_program(program_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.programs, program_id, "test program")
    if rec["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT program can be validated")
    has_available = any(
        f["program_id"] == rec["id"] and f["status"] == "AVAILABLE"
        for f in db.fixtures.values()
    )
    if not has_available:
        raise ApiError(ERR_NO_AVAILABLE_FIXTURE, 422,
                       "Program validation requires at least one AVAILABLE fixture")
    rec["status"] = "VALIDATED"
    touch(rec)
    return success(ser_program(rec), "object", 200)


@bp.route("/api/test-programs/<program_id>/release", methods=["POST"])
def release_program(program_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.programs, program_id, "test program")
    if rec["status"] != "VALIDATED":
        raise invalid_state("Only a VALIDATED program can be released")
    rec["status"] = "RELEASED"
    touch(rec)
    # Supersession cascade: prior RELEASED program with same customer_id + part_number.
    for old in list(db.programs.values()):
        if (
            old["id"] != rec["id"]
            and old["customer_id"] == rec["customer_id"]
            and old["part_number"] == rec["part_number"]
            and old["status"] == "RELEASED"
        ):
            old["status"] = "OBSOLETE"
            touch(old)
            for fx in list(db.fixtures.values()):
                if fx["program_id"] == old["id"] and fx["status"] in (
                    "COMMISSIONING", "AVAILABLE", "UNDER_MAINTENANCE",
                ):
                    fx["status"] = "DECOMMISSIONED"
                    touch(fx)
                    for r in list(db.reservations.values()):
                        if r["fixture_id"] == fx["id"] and r["status"] == "RESERVED":
                            cancel_reservation(r)
    return success(ser_program(rec), "object", 200)


@bp.route("/api/test-programs/<program_id>/revisions", methods=["POST"])
def mint_revision(program_id):
    require_roles("TestEngineer")
    src = get_or_404(db.programs, program_id, "test program")
    data = json_body()
    require_fields(data, "expected_test_program_version")
    expected = check_int(data["expected_test_program_version"],
                         "expected_test_program_version")
    if src["status"] != "RELEASED":
        raise invalid_state("Revisions can only be minted from a RELEASED program")
    if expected != src["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_test_program_version does not match current version")
    touch(src)  # source version increments even though its status is unchanged
    rec = stamp_new({
        "customer_id": src["customer_id"], "part_number": src["part_number"],
        "revision": src["revision"] + 1, "supersedes_program_id": src["id"],
        "bin_map": dict(src["bin_map"]),
        "max_retests_per_unit": src["max_retests_per_unit"],
        "burn_profile": [dict(s) for s in src["burn_profile"]],
        "status": "DRAFT",
    })
    db.programs[rec["id"]] = rec
    return success(ser_program(rec), "object", 201)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@bp.route("/api/fixtures", methods=["POST"])
def create_fixture():
    require_roles("TestEngineer")
    data = json_body()
    require_fields(data, "program_id", "serial_number", "site_count")
    check_str(data["program_id"], "program_id")
    serial = check_str(data["serial_number"], "serial_number")
    site_count = check_int(data["site_count"], "site_count", minimum=1)
    get_or_404(db.programs, data["program_id"], "test program")
    rec = stamp_new({
        "program_id": data["program_id"], "serial_number": serial,
        "site_count": site_count, "status": "COMMISSIONING",
    })
    db.fixtures[rec["id"]] = rec
    return success(ser_fixture(rec), "object", 201)


@bp.route("/api/fixtures/<fixture_id>", methods=["GET"])
def get_fixture(fixture_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.fixtures, fixture_id, "fixture")
    return success(ser_fixture(rec), "object", 200)


@bp.route("/api/fixtures", methods=["GET"])
def list_fixtures():
    require_roles(*ALL_ROLES)
    items = filter_list(db.fixtures, [("program_id", "program_id"), ("status", "status")])
    page, meta = paginate(items)
    return success([ser_fixture(f) for f in page], "array", 200, meta)


@bp.route("/api/fixtures/<fixture_id>/commission", methods=["POST"])
def commission_fixture(fixture_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.fixtures, fixture_id, "fixture")
    if rec["status"] != "COMMISSIONING":
        raise invalid_state("Only a COMMISSIONING fixture can be commissioned")
    rec["status"] = "AVAILABLE"
    touch(rec)
    return success(ser_fixture(rec), "object", 200)


@bp.route("/api/fixtures/<fixture_id>/maintenance", methods=["POST"])
def fixture_maintenance(fixture_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.fixtures, fixture_id, "fixture")
    if rec["status"] != "AVAILABLE":
        raise invalid_state("Only an AVAILABLE fixture can enter maintenance")
    rec["status"] = "UNDER_MAINTENANCE"
    touch(rec)
    for r in list(db.reservations.values()):
        if r["fixture_id"] == rec["id"] and r["status"] == "RESERVED":
            cancel_reservation(r)
    return success(ser_fixture(rec), "object", 200)


@bp.route("/api/fixtures/<fixture_id>/return-from-maintenance", methods=["POST"])
def fixture_return(fixture_id):
    require_roles("TestEngineer")
    rec = get_or_404(db.fixtures, fixture_id, "fixture")
    if rec["status"] != "UNDER_MAINTENANCE":
        raise invalid_state("Only an UNDER_MAINTENANCE fixture can return to service")
    rec["status"] = "AVAILABLE"
    touch(rec)
    return success(ser_fixture(rec), "object", 200)


# ---------------------------------------------------------------------------
# chambers
# ---------------------------------------------------------------------------

@bp.route("/api/chambers", methods=["POST"])
def create_chamber():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "name", "area_code", "slot_count", "supported_profile_classes")
    name = check_str(data["name"], "name")
    area_code = check_str(data["area_code"], "area_code")
    slot_count = check_int(data["slot_count"], "slot_count", minimum=1)
    classes = data["supported_profile_classes"]
    if not isinstance(classes, list):
        raise bad_request("supported_profile_classes must be an array")
    for c in classes:
        check_enum(c, PROFILE_CLASSES, "supported_profile_classes")
    rec = stamp_new({
        "name": name, "area_code": area_code, "slot_count": slot_count,
        "supported_profile_classes": classes, "status": "ONLINE",
    })
    db.chambers[rec["id"]] = rec
    return success(ser_chamber(rec), "object", 201)


@bp.route("/api/chambers/<chamber_id>", methods=["GET"])
def get_chamber(chamber_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.chambers, chamber_id, "chamber")
    return success(ser_chamber(rec), "object", 200)


@bp.route("/api/chambers/<chamber_id>", methods=["PATCH"])
def patch_chamber(chamber_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.chambers, chamber_id, "chamber")
    data = json_body()
    if "status" in data and data["status"] is not None:
        target = check_enum(data["status"], ("ONLINE", "MAINTENANCE", "OFFLINE"), "status")
        allowed = (
            (rec["status"] == "ONLINE" and target in ("MAINTENANCE", "OFFLINE"))
            or (rec["status"] == "MAINTENANCE" and target == "ONLINE")
        )
        if not allowed:
            raise invalid_state(f"Chamber cannot transition {rec['status']} -> {target}")
        rec["status"] = target
        touch(rec)
        if target == "OFFLINE":
            for r in list(db.reservations.values()):
                if r["chamber_id"] == rec["id"] and r["status"] == "RESERVED":
                    cancel_reservation(r)
    return success(ser_chamber(rec), "object", 200)


@bp.route("/api/chambers/<chamber_id>/utilization", methods=["GET"])
def chamber_utilization(chamber_id):
    require_roles(*ALL_ROLES)
    ch = get_or_404(db.chambers, chamber_id, "chamber")
    args = request.args
    for p in ("window_start", "window_end", "basis"):
        if args.get(p) is None:
            raise bad_request(f"Missing required query parameter: {p}")
    ws = parse_dt(args.get("window_start"), "window_start")
    we = parse_dt(args.get("window_end"), "window_end")
    basis = args.get("basis")
    check_enum(basis, ("SCHEDULED", "ACTUAL"), "basis")

    numerator = Fraction(0, 1)
    for r in db.reservations.values():
        if r["chamber_id"] != ch["id"]:
            continue
        if basis == "SCHEDULED":
            if r["status"] not in ("RESERVED", "IN_PROGRESS", "COMPLETED"):
                continue
        else:  # ACTUAL
            if r["status"] != "COMPLETED":
                continue
        ov_start = max(r["_start_dt"], ws)
        ov_end = min(r["_end_dt"], we)
        ov = minutes_between(ov_start, ov_end)
        if ov < 0:
            ov = Fraction(0, 1)
        numerator += r["slot_count"] * ov

    if basis == "SCHEDULED":
        denominator = ch["slot_count"] * minutes_between(ws, we)
    else:
        eff_end = min(we, db.clock_dt)
        denominator = ch["slot_count"] * minutes_between(ws, eff_end)

    ratio = Fraction(0, 1) if denominator <= 0 else numerator / denominator
    return success({
        "basis": basis,
        "utilization_ratio": ratio4(ratio),
        "numerator_slot_minutes": num_or_int(numerator),
        "denominator_slot_minutes": num_or_int(denominator),
    }, "object", 200)


# ---------------------------------------------------------------------------
# chamber reservations
# ---------------------------------------------------------------------------

def _reservation_business_checks(ch, lot, fx, profile_class, s_dt, e_dt, slot_count,
                                 exclude_id=None, check_lot_queued=True):
    """Validation-ladder rungs 6-9 for reservation create/reschedule."""
    # priority 6: ESD containment
    cust = db.customers[lot["customer_id"]]
    if cust["requires_esd_certification"] and esd_area_contained(ch["area_code"]):
        raise ApiError(ERR_ESD_CONTAINMENT, 409,
                       "Chamber area is under ESD containment for this customer")
    # priority 7: window well-formed (start_at >= clock, end_at > start_at)
    if sec(s_dt) < sec(db.clock_dt) or not (e_dt > s_dt):
        raise bad_request("Reservation window must satisfy start_at >= now and end_at > start_at")
    # priority 7: lot must be QUEUED (creation only)
    if check_lot_queued and lot["status"] != "QUEUED":
        raise invalid_state("Referenced lot must be QUEUED when a reservation is created")
    # priority 7: half-open overlap, then 30-minute purge buffer
    check_overlap(ch["id"], s_dt, e_dt, exclude_id=exclude_id)
    check_purge_buffer(ch["id"], profile_class, s_dt, e_dt, exclude_id=exclude_id)
    # priority 8: fixture AVAILABLE, fixture program lineage, chamber ONLINE
    if fx["status"] != "AVAILABLE":
        raise ApiError(ERR_FIXTURE_NOT_AVAILABLE, 409, "Fixture is not AVAILABLE")
    if fx["program_id"] != lot["program_id"]:
        raise ApiError(ERR_FIXTURE_PROGRAM_MISMATCH, 422,
                       "Fixture does not belong to the lot's program")
    if ch["status"] != "ONLINE":
        raise ApiError(ERR_CHAMBER_NOT_ONLINE, 409, "Chamber is not ONLINE")
    # priority 9: slot capacity (self excluded on reschedule), profile support
    available = chamber_available_slots(ch["id"], exclude_reservation_id=exclude_id)
    if slot_count < 1 or slot_count > available:
        raise ApiError(ERR_SLOT_CAPACITY_EXCEEDED, 422,
                       "slot_count must be >= 1 and <= chamber available_slots")
    if profile_class not in ch["supported_profile_classes"]:
        raise ApiError(ERR_PROFILE_NOT_SUPPORTED, 422,
                       "profile_class is not supported by the chamber")


@bp.route("/api/chamber-reservations", methods=["POST"])
def create_reservation():
    require_roles("OperationsManager")
    data = json_body()
    require_fields(data, "chamber_id", "lot_id", "fixture_id", "profile_class",
                   "start_at", "end_at", "slot_count")
    profile_class = check_enum(data["profile_class"], PROFILE_CLASSES, "profile_class")
    s_dt = parse_dt(data["start_at"], "start_at")
    e_dt = parse_dt(data["end_at"], "end_at")
    if isinstance(data["slot_count"], bool) or not isinstance(data["slot_count"], int):
        raise bad_request("slot_count must be an integer")
    slot_count = data["slot_count"]
    # existence, body field order: chamber_id, lot_id, fixture_id
    ch = get_or_404(db.chambers, data["chamber_id"], "chamber")
    lot = get_or_404(db.lots, data["lot_id"], "lot")
    fx = get_or_404(db.fixtures, data["fixture_id"], "fixture")
    _reservation_business_checks(ch, lot, fx, profile_class, s_dt, e_dt, slot_count)
    program = db.programs[lot["program_id"]]
    rec = stamp_new({
        "chamber_id": ch["id"], "lot_id": lot["id"], "fixture_id": fx["id"],
        "profile_class": profile_class,
        "start_at": data["start_at"], "end_at": data["end_at"],
        "_start_dt": s_dt, "_end_dt": e_dt,
        "slot_count": slot_count,
        "planned_duration_minutes": burn_profile_duration(program["burn_profile"]),
        "status": "RESERVED",
    })
    db.reservations[rec["id"]] = rec
    return success(ser_reservation(rec), "object", 201)


@bp.route("/api/chamber-reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.reservations, reservation_id, "chamber reservation")
    return success(ser_reservation(rec), "object", 200)


@bp.route("/api/chamber-reservations", methods=["GET"])
def list_reservations():
    require_roles(*ALL_ROLES)
    items = filter_list(db.reservations, [
        ("chamber_id", "chamber_id"), ("lot_id", "lot_id"),
        ("fixture_id", "fixture_id"), ("status", "status"),
    ])
    page, meta = paginate(items)
    return success([ser_reservation(r) for r in page], "array", 200, meta)


@bp.route("/api/chamber-reservations/<reservation_id>", methods=["PATCH"])
def reschedule_reservation(reservation_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.reservations, reservation_id, "chamber reservation")
    data = json_body()
    require_fields(data, "expected_chamber_reservation_version")
    expected = check_int(data["expected_chamber_reservation_version"],
                         "expected_chamber_reservation_version")
    # merged new values
    s_raw = data.get("start_at", rec["start_at"])
    e_raw = data.get("end_at", rec["end_at"])
    s_dt = parse_dt(s_raw, "start_at")
    e_dt = parse_dt(e_raw, "end_at")
    slot_count = data.get("slot_count", rec["slot_count"])
    if isinstance(slot_count, bool) or not isinstance(slot_count, int):
        raise bad_request("slot_count must be an integer")
    profile_class = data.get("profile_class", rec["profile_class"])
    check_enum(profile_class, PROFILE_CLASSES, "profile_class")
    # priority 4: lifecycle
    if rec["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED reservation can be rescheduled")
    # priority 5: OCC
    if expected != rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_chamber_reservation_version does not match current version")
    ch = db.chambers[rec["chamber_id"]]
    lot = db.lots[rec["lot_id"]]
    fx = db.fixtures[rec["fixture_id"]]
    _reservation_business_checks(ch, lot, fx, profile_class, s_dt, e_dt, slot_count,
                                 exclude_id=rec["id"], check_lot_queued=False)
    rec["start_at"] = s_raw
    rec["end_at"] = e_raw
    rec["_start_dt"] = s_dt
    rec["_end_dt"] = e_dt
    rec["slot_count"] = slot_count
    rec["profile_class"] = profile_class
    touch(rec)
    return success(ser_reservation(rec), "object", 200)


@bp.route("/api/chamber-reservations/<reservation_id>/start", methods=["POST"])
def start_reservation(reservation_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.reservations, reservation_id, "chamber reservation")
    if rec["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED reservation can be started")
    if not (sec(rec["_start_dt"]) <= sec(db.clock_dt) < sec(rec["_end_dt"])):
        raise invalid_state("Current time is outside the reservation window")
    ch = db.chambers[rec["chamber_id"]]
    if ch["status"] != "ONLINE":
        raise ApiError(ERR_CHAMBER_NOT_ONLINE, 409, "Chamber is not ONLINE")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return success(ser_reservation(rec), "object", 200)


@bp.route("/api/chamber-reservations/<reservation_id>/complete", methods=["POST"])
def complete_reservation(reservation_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.reservations, reservation_id, "chamber reservation")
    if rec["status"] != "IN_PROGRESS":
        raise invalid_state("Only an IN_PROGRESS reservation can be completed")
    if sec(db.clock_dt) < sec(rec["_end_dt"]):
        raise invalid_state("Reservation window has not ended yet")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(ser_reservation(rec), "object", 200)


@bp.route("/api/chamber-reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation_ep(reservation_id):
    require_roles("OperationsManager")
    rec = get_or_404(db.reservations, reservation_id, "chamber reservation")
    if rec["status"] != "RESERVED":
        raise invalid_state("Only a RESERVED reservation can be cancelled")
    cancel_reservation(rec)
    return success(ser_reservation(rec), "object", 200)
