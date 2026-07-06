import os

from flask import Flask, request

from db import db
from clock import parse_iso, format_iso_ms
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_PORTAL_AUTH_FAILED, ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_DUPLICATE, ERR_PAYMENT_EXISTS,
    ERR_CALIBRATION_LAPSED, ERR_NO_VIOLATION, ERR_OWNER_LOOKUP_FAILED,
    ERR_CONTEST_WINDOW_CLOSED, ERR_HEARING_TIME_INVALID, ERR_INVALID_REDUCTION,
    ERR_NOTHING_OWED, ERR_INVALID_REQUEST,
)
from response import ok_object, ok_array, error_response
from middleware import require_staff_auth, require_portal_auth
from helpers import (
    base_common, base_audit, touch_common, public,
    get_json_body, require_fields, require_int, require_str, require_enum,
    paginate, find_or_404,
)
from calculations import (
    compute_statutory_fine, compute_adjudicated_reduced,
    amount_owed_total, compute_vendor_share,
)
from serializers import (
    serialize_camera, serialize_citation, serialize_program, serialize_owner,
    serialize_calibration, serialize_contest, serialize_hearing,
    serialize_payment, serialize_vendor_contract, serialize_notice,
)

from datetime import timedelta

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #
@app.errorhandler(ApiError)
def handle_api_error(e):
    body = error_response(e.error_id, e.message)
    return body, e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = error_response("ERR_NOT_FOUND", "Resource not found")
    return body, 404


@app.errorhandler(405)
def handle_405(e):
    body = error_response("ERR_NOT_FOUND", "Method not allowed")
    return body, 404


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = error_response("ERR_INVALID_REQUEST", str(e))
    return body, 422


# --------------------------------------------------------------------------- #
# Helpers specific to this domain
# --------------------------------------------------------------------------- #
def clock_now():
    return db.clock.now()


def active_vendor_contract(program_id):
    """Return the authoritative ACTIVE vendor contract for a program.

    A program has one ACTIVE contract; if a stale ACTIVE also exists, the most
    recently created ACTIVE (by created_at ASC, taking the last) is authoritative.
    """
    actives = [
        vc for vc in db.vendor_contracts.values()
        if vc["program_id"] == program_id and vc["status"] == "ACTIVE"
    ]
    if not actives:
        return None
    actives.sort(key=lambda v: v["_seq"])
    return actives[-1]


def cleared_total(citation_id):
    return sum(
        int(p["amount_cents"])
        for p in db.payments.values()
        if p["citation_id"] == citation_id and p["status"] == "CLEARED"
    )


# --------------------------------------------------------------------------- #
# Program endpoints
# --------------------------------------------------------------------------- #
@app.route("/programs", methods=["POST"])
def create_program():
    require_staff_auth({"SystemAdmin"})
    body = get_json_body()
    require_fields(body, [
        "jurisdiction_name", "base_red_light_fine_cents",
        "base_speed_fine_cents", "admin_fee_cents", "late_fee_cents",
    ])
    jurisdiction_name = require_str(body, "jurisdiction_name")
    base_rl = require_int(body, "base_red_light_fine_cents", non_negative=True)
    base_sp = require_int(body, "base_speed_fine_cents", non_negative=True)
    admin_fee = require_int(body, "admin_fee_cents", non_negative=True)
    late_fee = require_int(body, "late_fee_cents", non_negative=True)

    response_window_days = 30
    if "response_window_days" in body and body["response_window_days"] is not None:
        response_window_days = require_int(body, "response_window_days", positive=True)
    repeat_window = 365
    if "repeat_offender_window_days" in body and body["repeat_offender_window_days"] is not None:
        repeat_window = require_int(body, "repeat_offender_window_days", positive=True)
    surcharge_pct = 0.5
    if "repeat_offender_surcharge_pct" in body and body["repeat_offender_surcharge_pct"] is not None:
        v = body["repeat_offender_surcharge_pct"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err(ERR_INVALID_REQUEST, "repeat_offender_surcharge_pct must be a number")
        surcharge_pct = v

    rec = base_common()
    rec.update({
        "jurisdiction_name": jurisdiction_name,
        "base_red_light_fine_cents": base_rl,
        "base_speed_fine_cents": base_sp,
        "admin_fee_cents": admin_fee,
        "late_fee_cents": late_fee,
        "response_window_days": response_window_days,
        "repeat_offender_window_days": repeat_window,
        "repeat_offender_surcharge_pct": surcharge_pct,
    })
    db.programs[rec["id"]] = rec
    return ok_object(serialize_program(db, rec), 201)


@app.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    require_staff_auth({"SystemAdmin", "ProgramAdmin", "ReviewOfficer", "Adjudicator", "Auditor"})
    rec = find_or_404(db.programs, pid)
    return ok_object(serialize_program(db, rec))


@app.route("/programs", methods=["GET"])
def list_programs():
    require_staff_auth({"SystemAdmin", "Auditor"})
    items, meta = paginate(list(db.programs.values()))
    return ok_array(items, meta)


# --------------------------------------------------------------------------- #
# Camera endpoints
# --------------------------------------------------------------------------- #
@app.route("/cameras", methods=["POST"])
def create_camera():
    require_staff_auth({"ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "intersection_code", "camera_type"])
    program_id = require_str(body, "program_id")
    intersection_code = require_str(body, "intersection_code")
    camera_type = require_enum(body, "camera_type", {"RED_LIGHT", "SPEED"})

    program = db.programs.get(program_id)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found")

    speed_limit = body.get("speed_limit_mph")
    if camera_type == "SPEED":
        if speed_limit is None or isinstance(speed_limit, bool) or not isinstance(speed_limit, int) or speed_limit <= 0:
            raise err(ERR_INVALID_REQUEST, "SPEED camera requires speed_limit_mph > 0")
    else:  # RED_LIGHT
        if speed_limit is not None:
            raise err(ERR_INVALID_REQUEST, "RED_LIGHT camera must not carry speed_limit_mph")

    # Duplicate intersection_code within program among non-DECOMMISSIONED
    for c in db.cameras.values():
        if c["program_id"] == program_id and c["status"] != "DECOMMISSIONED" \
                and c["intersection_code"] == intersection_code:
            raise err(ERR_DUPLICATE, "intersection_code already in use in this program")

    rec = base_common()
    rec.update({
        "program_id": program_id,
        "intersection_code": intersection_code,
        "camera_type": camera_type,
        "speed_limit_mph": speed_limit if camera_type == "SPEED" else None,
        "status": "ACTIVE",
    })
    db.cameras[rec["id"]] = rec
    return ok_object(serialize_camera(db, rec), 201)


@app.route("/cameras/<cid>", methods=["GET"])
def get_camera(cid):
    require_staff_auth({"ProgramAdmin", "ReviewOfficer", "Auditor"})
    rec = find_or_404(db.cameras, cid)
    return ok_object(serialize_camera(db, rec))


@app.route("/cameras", methods=["GET"])
def list_cameras():
    require_staff_auth({"ProgramAdmin", "ReviewOfficer", "Auditor"})
    items = list(db.cameras.values())
    program_id = request.args.get("program_id")
    camera_type = request.args.get("camera_type")
    status = request.args.get("status")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    if camera_type is not None:
        items = [c for c in items if c["camera_type"] == camera_type]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    page = [serialize_camera(db, db.cameras[p["id"]]) for p in page]
    return ok_array(page, meta)


def _camera_transition(cid, from_states, to_state):
    require_staff_auth({"ProgramAdmin"})
    rec = find_or_404(db.cameras, cid)
    if rec["status"] not in from_states:
        raise err(ERR_INVALID_STATE, f"Camera not in a valid state for this transition")
    rec["status"] = to_state
    touch_common(rec)
    return ok_object(serialize_camera(db, rec))


@app.route("/cameras/<cid>/suspend", methods=["POST"])
def suspend_camera(cid):
    return _camera_transition(cid, {"ACTIVE"}, "SUSPENDED")


@app.route("/cameras/<cid>/reactivate", methods=["POST"])
def reactivate_camera(cid):
    return _camera_transition(cid, {"SUSPENDED"}, "ACTIVE")


@app.route("/cameras/<cid>/decommission", methods=["POST"])
def decommission_camera(cid):
    return _camera_transition(cid, {"ACTIVE", "SUSPENDED"}, "DECOMMISSIONED")


# --------------------------------------------------------------------------- #
# CalibrationRecord endpoints
# --------------------------------------------------------------------------- #
@app.route("/cameras/<cid>/calibrations", methods=["POST"])
def create_calibration(cid):
    require_staff_auth({"ProgramAdmin"})
    camera = find_or_404(db.cameras, cid)
    body = get_json_body()
    require_fields(body, ["performed_at_utc", "valid_until_utc", "technician_ref", "result"])
    performed_raw = require_str(body, "performed_at_utc")
    valid_raw = require_str(body, "valid_until_utc")
    technician_ref = require_str(body, "technician_ref")
    result = require_enum(body, "result", {"PASS", "FAIL"})
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise err(ERR_INVALID_REQUEST, "notes must be a string")

    try:
        performed_dt = parse_iso(performed_raw)
        valid_dt = parse_iso(valid_raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid datetime format")
    if not (valid_dt > performed_dt):
        raise err(ERR_INVALID_REQUEST, "valid_until_utc must be strictly after performed_at_utc")

    rec = base_audit()
    rec.update({
        "camera_id": cid,
        "performed_at_utc": performed_raw,
        "valid_until_utc": valid_raw,
        "technician_ref": technician_ref,
        "result": result,
        "notes": notes,
    })
    db.calibrations[rec["id"]] = rec
    # camera.certified_until_clock recomputed (computed at serialization). Bump camera version.
    touch_common(camera)
    return ok_object(serialize_calibration(db, rec), 201)


@app.route("/cameras/<cid>/calibrations", methods=["GET"])
def list_calibrations(cid):
    require_staff_auth({"ProgramAdmin", "ReviewOfficer", "Auditor"})
    find_or_404(db.cameras, cid)
    items = [c for c in db.calibrations.values() if c["camera_id"] == cid]
    result = request.args.get("result")
    if result is not None:
        items = [c for c in items if c["result"] == result]
    page, meta = paginate(items)
    return ok_array(page, meta)


# --------------------------------------------------------------------------- #
# RegisteredOwner endpoints
# --------------------------------------------------------------------------- #
@app.route("/owners", methods=["POST"])
def create_owner():
    require_staff_auth({"ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "plate_number", "full_name", "mailing_address"])
    program_id = require_str(body, "program_id")
    plate_number = require_str(body, "plate_number")
    full_name = require_str(body, "full_name")
    mailing_address = require_str(body, "mailing_address")

    program = db.programs.get(program_id)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found")

    for o in db.owners.values():
        if o["program_id"] == program_id and o["plate_number"] == plate_number:
            raise err(ERR_DUPLICATE, "plate_number already registered in this program")

    rec = base_common()
    rec.update({
        "program_id": program_id,
        "plate_number": plate_number,
        "full_name": full_name,
        "mailing_address": mailing_address,
        "portal_access_pin": db.new_id().replace("-", "")[:12],
    })
    db.owners[rec["id"]] = rec
    return ok_object(serialize_owner(db, rec), 201)


@app.route("/owners/<oid>", methods=["GET"])
def get_owner(oid):
    require_staff_auth({"ProgramAdmin", "Auditor"})
    rec = find_or_404(db.owners, oid)
    return ok_object(serialize_owner(db, rec))


@app.route("/owners", methods=["GET"])
def list_owners():
    require_staff_auth({"ProgramAdmin", "Auditor"})
    items = list(db.owners.values())
    program_id = request.args.get("program_id")
    plate_number = request.args.get("plate_number")
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if plate_number is not None:
        items = [o for o in items if o["plate_number"] == plate_number]
    page, meta = paginate(items)
    return ok_array(page, meta)


# --------------------------------------------------------------------------- #
# Citation endpoints
# --------------------------------------------------------------------------- #
@app.route("/citations", methods=["POST"])
def create_citation():
    require_staff_auth({"ReviewOfficer", "ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "camera_id", "captured_plate_number", "event_at_utc"])
    program_id = require_str(body, "program_id")
    camera_id = require_str(body, "camera_id")
    captured_plate = require_str(body, "captured_plate_number")
    event_raw = require_str(body, "event_at_utc")
    try:
        parse_iso(event_raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid event_at_utc")

    # Existence: program then camera, same program
    program = db.programs.get(program_id)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found")
    camera = db.cameras.get(camera_id)
    if camera is None or camera["program_id"] != program_id:
        raise err(ERR_NOT_FOUND, "Camera not found in this program")

    measured_speed = body.get("measured_speed_mph")

    # No-violation: capture only when camera ACTIVE
    if camera["status"] != "ACTIVE":
        raise err(ERR_NO_VIOLATION, "Camera is not ACTIVE")

    if camera["camera_type"] == "SPEED":
        if measured_speed is None or isinstance(measured_speed, bool) or not isinstance(measured_speed, int):
            raise err(ERR_INVALID_REQUEST, "SPEED capture requires measured_speed_mph integer")
        if measured_speed <= camera["speed_limit_mph"]:
            raise err(ERR_NO_VIOLATION, "measured_speed_mph not over the limit")
    else:  # RED_LIGHT carries no measured speed
        measured_speed = None

    rec = base_common()
    rec.update({
        "program_id": program_id,
        "camera_id": camera_id,
        "registered_owner_id": None,
        "captured_plate_number": captured_plate,
        "event_at_utc": event_raw,
        "measured_speed_mph": measured_speed,
        "status": "PENDING_REVIEW",
        "notice_issued_at_utc": None,
        "due_at_utc": None,
        "escalation_stage": None,
        "assessed_amount_cents": None,
        "adjudicated_amount_cents": None,
        "amount_paid_cents": 0,
        "review_officer_ref": None,
    })
    db.citations[rec["id"]] = rec
    return ok_object(serialize_citation(db, rec), 201)


@app.route("/citations/<cid>", methods=["GET"])
def get_citation(cid):
    require_staff_auth({"ProgramAdmin", "ReviewOfficer", "Adjudicator", "Auditor"})
    rec = find_or_404(db.citations, cid)
    return ok_object(serialize_citation(db, rec))


@app.route("/citations", methods=["GET"])
def list_citations():
    require_staff_auth({"ProgramAdmin", "ReviewOfficer", "Adjudicator", "Auditor"})
    items = list(db.citations.values())
    for key in ("program_id", "camera_id", "registered_owner_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, meta = paginate(items)
    page = [serialize_citation(db, db.citations[p["id"]]) for p in page]
    return ok_array(page, meta)


@app.route("/citations/<cid>/review", methods=["POST"])
def review_citation(cid):
    user_id, role = require_staff_auth({"ReviewOfficer"})
    citation = find_or_404(db.citations, cid)
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})

    if citation["status"] != "PENDING_REVIEW":
        raise err(ERR_INVALID_STATE, "Citation is not PENDING_REVIEW")

    program = db.programs[citation["program_id"]]
    camera = db.cameras[citation["camera_id"]]

    if decision == "REJECT":
        citation["review_officer_ref"] = user_id
        citation["status"] = "REJECTED"
        touch_common(citation)
        return ok_object(serialize_citation(db, citation))

    # APPROVE path
    # Calibration coverage: PASS record with performed_at_utc <= event_at_utc < valid_until_utc
    event_dt = parse_iso(citation["event_at_utc"])
    has_coverage = False
    for cr in db.calibrations.values():
        if cr["camera_id"] != camera["id"] or cr["result"] != "PASS":
            continue
        performed = parse_iso(cr["performed_at_utc"])
        valid = parse_iso(cr["valid_until_utc"])
        if performed <= event_dt and valid > event_dt:
            has_coverage = True
            break
    if not has_coverage:
        raise err(ERR_CALIBRATION_LAPSED, "No valid calibration coverage at event time")

    # Owner lookup
    matched_owner = None
    for o in db.owners.values():
        if o["program_id"] == program["id"] and o["plate_number"] == citation["captured_plate_number"]:
            matched_owner = o
            break
    if matched_owner is None:
        raise err(ERR_OWNER_LOOKUP_FAILED, "No registered owner matches the plate")

    now = clock_now()
    now_iso = format_iso_ms(now)
    due = now + timedelta(days=int(program["response_window_days"]))

    citation["review_officer_ref"] = user_id
    citation["registered_owner_id"] = matched_owner["id"]
    citation["notice_issued_at_utc"] = now_iso
    citation["due_at_utc"] = format_iso_ms(due)
    citation["escalation_stage"] = "NONE"

    assessed = compute_statutory_fine(db, program, camera, citation, now)
    citation["assessed_amount_cents"] = assessed
    citation["adjudicated_amount_cents"] = assessed
    citation["status"] = "CITED"
    touch_common(citation)

    # Append INITIAL NoticeRecord
    notice = base_audit()
    notice.update({
        "citation_id": citation["id"],
        "registered_owner_id": matched_owner["id"],
        "notice_type": "INITIAL",
        "issued_at_clock": now_iso,
        "amount_owed_snapshot_cents": assessed,
    })
    db.notices[notice["id"]] = notice

    return ok_object(serialize_citation(db, citation))


@app.route("/citations/<cid>/void", methods=["POST"])
def void_citation(cid):
    require_staff_auth({"ProgramAdmin"})
    citation = find_or_404(db.citations, cid)

    if citation["status"] not in {"PENDING_REVIEW", "CITED", "DELINQUENT"}:
        raise err(ERR_INVALID_STATE, "Citation cannot be voided from its current state")

    # Refuse if a CLEARED payment exists
    for p in db.payments.values():
        if p["citation_id"] == cid and p["status"] == "CLEARED":
            raise err(ERR_PAYMENT_EXISTS, "A cleared payment exists on this citation")

    citation["status"] = "VOID"
    citation["adjudicated_amount_cents"] = 0
    touch_common(citation)

    # Cascade: contests SUBMITTED/SCHEDULED -> WITHDRAWN; hearings SCHEDULED -> ADJOURNED
    for contest in db.contests.values():
        if contest["citation_id"] == cid and contest["status"] in {"SUBMITTED", "SCHEDULED"}:
            contest["status"] = "WITHDRAWN"
            touch_common(contest)
    for hearing in db.hearings.values():
        if hearing["citation_id"] == cid and hearing["status"] == "SCHEDULED":
            hearing["status"] = "ADJOURNED"
            touch_common(hearing)

    return ok_object(serialize_citation(db, citation))


# --------------------------------------------------------------------------- #
# Contest endpoints
# --------------------------------------------------------------------------- #
@app.route("/citations/<cid>/contests", methods=["POST"])
def create_contest(cid):
    body = get_json_body()
    # Portal auth (stands in place of staff headers)
    owner = require_portal_auth(body)

    citation = find_or_404(db.citations, cid)

    require_fields(body, ["ground", "statement", "expected_citation_version"])
    ground = require_enum(body, "ground", {
        "NOT_THE_DRIVER", "PLATE_MISREAD", "SIGNAL_MALFUNCTION",
        "CALIBRATION_LAPSED", "EMERGENCY",
    })
    statement = require_str(body, "statement")
    expected_version = body.get("expected_citation_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_citation_version must be an integer")

    # State check before OCC (per validation ordering)
    if citation["status"] != "CITED":
        raise err(ERR_INVALID_STATE, "Citation is not CITED")

    # OCC
    if expected_version != citation["version"]:
        raise err(ERR_STALE_VERSION, "Citation version is stale")

    # Contest window: clock <= due_at_utc
    now = clock_now()
    due = parse_iso(citation["due_at_utc"])
    if now > due:
        raise err(ERR_CONTEST_WINDOW_CLOSED, "Contest window has closed")

    rec = base_common()
    rec.update({
        "citation_id": cid,
        "submitted_by_owner_id": owner["id"],
        "ground": ground,
        "statement": statement,
        "status": "SUBMITTED",
    })
    db.contests[rec["id"]] = rec

    citation["status"] = "CONTESTED"
    touch_common(citation)

    return ok_object(serialize_contest(db, rec), 201)


@app.route("/citations/<cid>/contests", methods=["GET"])
def list_citation_contests(cid):
    require_staff_auth({"ProgramAdmin", "Adjudicator", "Auditor"})
    find_or_404(db.citations, cid)
    items = [c for c in db.contests.values() if c["citation_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/contests/<coid>", methods=["GET"])
def get_contest(coid):
    require_staff_auth({"ProgramAdmin", "Adjudicator", "Auditor"})
    rec = find_or_404(db.contests, coid)
    return ok_object(serialize_contest(db, rec))


@app.route("/owners/<oid>/contests", methods=["GET"])
def list_owner_contests(oid):
    require_staff_auth({"ProgramAdmin", "Auditor"})
    find_or_404(db.owners, oid)
    items = [c for c in db.contests.values() if c["submitted_by_owner_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


# --------------------------------------------------------------------------- #
# Hearing endpoints
# --------------------------------------------------------------------------- #
@app.route("/contests/<coid>/hearings", methods=["POST"])
def create_hearing(coid):
    require_staff_auth({"ProgramAdmin"})
    contest = find_or_404(db.contests, coid)
    citation = db.citations[contest["citation_id"]]
    body = get_json_body()
    require_fields(body, ["scheduled_at_utc", "adjudicator_ref"])
    scheduled_raw = require_str(body, "scheduled_at_utc")
    adjudicator_ref = require_str(body, "adjudicator_ref")

    # SoD (authz priority): adjudicator must differ from review_officer_ref
    if adjudicator_ref == citation.get("review_officer_ref"):
        raise err(ERR_SEGREGATION_OF_DUTIES, "Adjudicator cannot equal the review officer")

    # State: citation CONTESTED and contest SUBMITTED
    if citation["status"] != "CONTESTED" or contest["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Contest is not in a schedulable state")

    try:
        scheduled_dt = parse_iso(scheduled_raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid scheduled_at_utc")

    now = clock_now()
    if not (scheduled_dt > now):
        raise err(ERR_HEARING_TIME_INVALID, "scheduled_at_utc must be strictly in the future")

    rec = base_common()
    rec.update({
        "contest_id": coid,
        "citation_id": citation["id"],
        "scheduled_at_utc": scheduled_raw,
        "adjudicator_ref": adjudicator_ref,
        "outcome": None,
        "reduced_amount_cents": None,
        "status": "SCHEDULED",
    })
    db.hearings[rec["id"]] = rec

    citation["status"] = "HEARING_SCHEDULED"
    touch_common(citation)
    contest["status"] = "SCHEDULED"
    touch_common(contest)

    return ok_object(serialize_hearing(db, rec), 201)


@app.route("/contests/<coid>/hearings", methods=["GET"])
def list_contest_hearings(coid):
    require_staff_auth({"ProgramAdmin", "Adjudicator", "Auditor"})
    find_or_404(db.contests, coid)
    items = [h for h in db.hearings.values() if h["contest_id"] == coid]
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    require_staff_auth({"ProgramAdmin", "Adjudicator", "Auditor"})
    rec = find_or_404(db.hearings, hid)
    return ok_object(serialize_hearing(db, rec))


@app.route("/citations/<cid>/hearings", methods=["GET"])
def list_citation_hearings(cid):
    require_staff_auth({"ProgramAdmin", "Adjudicator", "Auditor"})
    find_or_404(db.citations, cid)
    items = [h for h in db.hearings.values() if h["citation_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [h for h in items if h["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/hearings/<hid>/rule", methods=["POST"])
def rule_hearing(hid):
    user_id, role = require_staff_auth({"Adjudicator"})
    hearing = find_or_404(db.hearings, hid)
    citation = db.citations[hearing["citation_id"]]
    contest = db.contests[hearing["contest_id"]]
    program = db.programs[citation["program_id"]]
    body = get_json_body()
    require_fields(body, ["outcome", "expected_hearing_version"])
    outcome = require_enum(body, "outcome", {"UPHELD", "REDUCED", "DISMISSED"})
    expected_version = body.get("expected_hearing_version")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_hearing_version must be an integer")

    # SoD (authz priority)
    if user_id == citation.get("review_officer_ref"):
        raise err(ERR_SEGREGATION_OF_DUTIES, "Adjudicator cannot rule a citation they reviewed")

    # State: citation HEARING_SCHEDULED and hearing SCHEDULED
    if citation["status"] != "HEARING_SCHEDULED" or hearing["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Hearing is not in a rulable state")

    # OCC on hearing
    if expected_version != hearing["version"]:
        raise err(ERR_STALE_VERSION, "Hearing version is stale")

    # Hearing must have occurred: clock >= scheduled_at_utc
    now = clock_now()
    scheduled_dt = parse_iso(hearing["scheduled_at_utc"])
    if now < scheduled_dt:
        raise err(ERR_HEARING_TIME_INVALID, "Hearing has not occurred yet")

    if outcome == "REDUCED":
        reduced = body.get("reduced_amount_cents")
        if reduced is None or isinstance(reduced, bool) or not isinstance(reduced, int):
            raise err(ERR_INVALID_REDUCTION, "reduced_amount_cents required for REDUCED")
        upper = citation["assessed_amount_cents"] - program["admin_fee_cents"]
        if not (0 < reduced < upper):
            raise err(ERR_INVALID_REDUCTION, "reduced_amount_cents out of range")

    # Apply ruling
    hearing["status"] = "RULED"
    hearing["outcome"] = outcome

    if outcome == "UPHELD":
        citation["status"] = "ADJUDICATED_UPHELD"
        citation["adjudicated_amount_cents"] = citation["assessed_amount_cents"]
        contest["status"] = "DISMISSED"
    elif outcome == "REDUCED":
        hearing["reduced_amount_cents"] = reduced
        citation["status"] = "ADJUDICATED_UPHELD"
        citation["adjudicated_amount_cents"] = compute_adjudicated_reduced(program, reduced)
        contest["status"] = "DISMISSED"
    else:  # DISMISSED
        citation["status"] = "ADJUDICATED_DISMISSED"
        citation["adjudicated_amount_cents"] = 0
        citation["escalation_stage"] = "NONE"
        contest["status"] = "UPHELD"

    touch_common(hearing)
    touch_common(citation)
    touch_common(contest)

    return ok_object(serialize_hearing(db, hearing))


# --------------------------------------------------------------------------- #
# Payment endpoints
# --------------------------------------------------------------------------- #
@app.route("/citations/<cid>/payments", methods=["POST"])
def create_payment(cid):
    body = get_json_body()
    # Payment may be by ProgramAdmin (staff headers) or RegisteredOwner (portal PIN).
    role = request.headers.get("X-User-Role")
    if role is not None:
        require_staff_auth({"ProgramAdmin", "RegisteredOwner"})
    else:
        require_portal_auth(body)

    citation = find_or_404(db.citations, cid)
    require_fields(body, ["amount_cents", "method"])
    method = require_enum(body, "method", {"CARD", "CHECK", "CASH"})
    amount = body.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise err(ERR_INVALID_REQUEST, "amount_cents must be an integer")

    if amount <= 0:
        raise err(ERR_NOTHING_OWED, "amount_cents must be positive")

    program = db.programs[citation["program_id"]]
    owed = amount_owed_total(program, citation)
    if citation["status"] in {"VOID", "ADJUDICATED_DISMISSED", "PAID"} or owed <= 0:
        raise err(ERR_NOTHING_OWED, "Citation owes nothing")

    rec = base_common()
    rec.update({
        "citation_id": cid,
        "amount_cents": amount,
        "method": method,
        "status": "INITIATED",
    })
    db.payments[rec["id"]] = rec
    return ok_object(serialize_payment(db, rec), 201)


@app.route("/citations/<cid>/payments", methods=["GET"])
def list_payments(cid):
    role = request.headers.get("X-User-Role")
    if role is not None:
        require_staff_auth({"ProgramAdmin", "Auditor", "RegisteredOwner"})
    else:
        require_portal_auth(request.args)
    find_or_404(db.citations, cid)
    items = [p for p in db.payments.values() if p["citation_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    require_staff_auth({"ProgramAdmin"})
    payment = find_or_404(db.payments, pid)
    if payment["status"] != "CLEARED":
        raise err(ERR_INVALID_STATE, "Only a CLEARED payment can be reversed")
    citation = db.citations[payment["citation_id"]]
    program = db.programs[citation["program_id"]]

    payment["status"] = "REVERSED"
    touch_common(payment)

    # Recompute amount_paid_cents
    citation["amount_paid_cents"] = cleared_total(citation["id"])
    touch_common(citation)

    if citation["status"] == "PAID":
        # revert to prior owed state
        had_ruling = any(
            h["citation_id"] == citation["id"] and h["status"] == "RULED"
            and h["outcome"] in {"UPHELD", "REDUCED"}
            for h in db.hearings.values()
        )
        citation["status"] = "ADJUDICATED_UPHELD" if had_ruling else "CITED"
        touch_common(citation)
        # de-accrue vendor share by the exact amount accrued for this citation
        accrued = citation.get("_vendor_share_accrued")
        contract_id = citation.get("_vendor_contract_id")
        if accrued and contract_id and contract_id in db.vendor_contracts:
            vc = db.vendor_contracts[contract_id]
            vc["accrued_vendor_share_cents"] = max(0, int(vc["accrued_vendor_share_cents"]) - int(accrued))
            touch_common(vc)
        citation["_vendor_share_accrued"] = 0
        citation["_vendor_contract_id"] = None

    return ok_object(serialize_payment(db, payment))


# --------------------------------------------------------------------------- #
# VendorContract endpoints
# --------------------------------------------------------------------------- #
@app.route("/vendor-contracts", methods=["POST"])
def create_vendor_contract():
    require_staff_auth({"ProgramAdmin"})
    body = get_json_body()
    require_fields(body, ["program_id", "vendor_name", "revenue_share_pct"])
    program_id = require_str(body, "program_id")
    vendor_name = require_str(body, "vendor_name")
    pct = body.get("revenue_share_pct")
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        raise err(ERR_INVALID_REQUEST, "revenue_share_pct must be a number")
    if not (0 <= pct <= 1):
        raise err(ERR_INVALID_REQUEST, "revenue_share_pct must be between 0 and 1")

    program = db.programs.get(program_id)
    if program is None:
        raise err(ERR_NOT_FOUND, "Program not found")

    monthly_cap = body.get("monthly_cap_cents")
    if monthly_cap is not None:
        if isinstance(monthly_cap, bool) or not isinstance(monthly_cap, int) or monthly_cap < 0:
            raise err(ERR_INVALID_REQUEST, "monthly_cap_cents must be a non-negative integer")

    rec = base_common()
    rec.update({
        "program_id": program_id,
        "vendor_name": vendor_name,
        "revenue_share_pct": pct,
        "monthly_cap_cents": monthly_cap,
        "accrued_vendor_share_cents": 0,
        "status": "ACTIVE",
    })
    db.vendor_contracts[rec["id"]] = rec
    return ok_object(serialize_vendor_contract(db, rec), 201)


@app.route("/vendor-contracts", methods=["GET"])
def list_vendor_contracts():
    require_staff_auth({"ProgramAdmin", "Auditor"})
    items = list(db.vendor_contracts.values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [v for v in items if v["program_id"] == program_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/vendor-contracts/<vid>", methods=["GET"])
def get_vendor_contract(vid):
    require_staff_auth({"ProgramAdmin", "Auditor"})
    rec = find_or_404(db.vendor_contracts, vid)
    return ok_object(serialize_vendor_contract(db, rec))


@app.route("/vendor-contracts/<vid>/terminate", methods=["POST"])
def terminate_vendor_contract(vid):
    require_staff_auth({"ProgramAdmin"})
    rec = find_or_404(db.vendor_contracts, vid)
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Only an ACTIVE contract can be terminated")
    rec["status"] = "TERMINATED"
    touch_common(rec)
    return ok_object(serialize_vendor_contract(db, rec))


# --------------------------------------------------------------------------- #
# NoticeRecord endpoints
# --------------------------------------------------------------------------- #
@app.route("/citations/<cid>/notices", methods=["GET"])
def list_citation_notices(cid):
    require_staff_auth({"ProgramAdmin", "Auditor"})
    find_or_404(db.citations, cid)
    items = [n for n in db.notices.values() if n["citation_id"] == cid]
    notice_type = request.args.get("notice_type")
    if notice_type is not None:
        items = [n for n in items if n["notice_type"] == notice_type]
    page, meta = paginate(items)
    return ok_array(page, meta)


@app.route("/owners/<oid>/notices", methods=["GET"])
def list_owner_notices(oid):
    require_staff_auth({"ProgramAdmin", "Auditor"})
    find_or_404(db.owners, oid)
    items = [n for n in db.notices.values() if n["registered_owner_id"] == oid]
    notice_type = request.args.get("notice_type")
    if notice_type is not None:
        items = [n for n in items if n["notice_type"] == notice_type]
    page, meta = paginate(items)
    return ok_array(page, meta)


# --------------------------------------------------------------------------- #
# Owner portal reads
# --------------------------------------------------------------------------- #
@app.route("/portal/citations", methods=["GET"])
def portal_citations():
    owner = require_portal_auth(request.args)
    items = [c for c in db.citations.values() if c.get("registered_owner_id") == owner["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    page = [serialize_citation(db, db.citations[p["id"]]) for p in page]
    return ok_array(page, meta)


# --------------------------------------------------------------------------- #
# Test-driving endpoints
# --------------------------------------------------------------------------- #
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_staff_auth({"SystemAdmin"})
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = require_str(body, "to_iso8601")
    try:
        db.clock.set(to_iso)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "Invalid to_iso8601")
    return ok_object({})


@app.route("/_payments/settle", methods=["POST"])
def settle_payment():
    require_staff_auth({"SystemAdmin"})
    body = get_json_body()
    require_fields(body, ["payment_id", "outcome"])
    payment_id = require_str(body, "payment_id")
    outcome = require_enum(body, "outcome", {"CLEARED", "FAILED"})

    payment = db.payments.get(payment_id)
    if payment is None:
        raise err(ERR_NOT_FOUND, "Payment not found")
    if payment["status"] != "INITIATED":
        raise err(ERR_INVALID_STATE, "Payment is not INITIATED")

    citation = db.citations[payment["citation_id"]]
    program = db.programs[citation["program_id"]]

    if outcome == "FAILED":
        payment["status"] = "FAILED"
        touch_common(payment)
        return ok_object(serialize_payment(db, payment))

    # CLEARED
    payment["status"] = "CLEARED"
    touch_common(payment)
    citation["amount_paid_cents"] = cleared_total(citation["id"])
    touch_common(citation)

    owed = amount_owed_total(program, citation)
    if citation["status"] in {"CITED", "ADJUDICATED_UPHELD", "DELINQUENT"} \
            and citation["amount_paid_cents"] >= owed:
        citation["status"] = "PAID"
        touch_common(citation)
        # Accrue vendor share
        contract = active_vendor_contract(citation["program_id"])
        if contract is not None:
            share = compute_vendor_share(program, citation, contract)
            if share > 0:
                contract["accrued_vendor_share_cents"] = int(contract["accrued_vendor_share_cents"]) + share
                touch_common(contract)
            citation["_vendor_share_accrued"] = share
            citation["_vendor_contract_id"] = contract["id"]

    return ok_object(serialize_payment(db, payment))


@app.route("/_escalation/sweep", methods=["POST"])
def escalation_sweep():
    require_staff_auth({"SystemAdmin"})
    body = get_json_body()
    program_id = body.get("program_id")

    now = clock_now()
    for citation in db.citations.values():
        if program_id is not None and citation["program_id"] != program_id:
            continue
        if citation["status"] not in {"CITED", "ADJUDICATED_UPHELD"}:
            continue
        program = db.programs[citation["program_id"]]
        due = parse_iso(citation["due_at_utc"])
        deadline = due + timedelta(days=int(program["response_window_days"]))
        if now > deadline:
            citation["status"] = "DELINQUENT"
            citation["escalation_stage"] = "DELINQUENT"
            touch_common(citation)
            snapshot = amount_owed_total(program, citation)
            notice = base_audit()
            notice.update({
                "citation_id": citation["id"],
                "registered_owner_id": citation["registered_owner_id"],
                "notice_type": "DELINQUENT",
                "issued_at_clock": format_iso_ms(now),
                "amount_owed_snapshot_cents": snapshot,
            })
            db.notices[notice["id"]] = notice

    return ok_object({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
