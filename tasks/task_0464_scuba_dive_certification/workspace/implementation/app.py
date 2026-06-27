"""Scuba Dive Certification API — Flask entry point.

In-memory only. No seeding. Boots clean every process start.
"""
import os

from flask import Flask, request

import auth
import clock
import db
import domain
import errors
import response
import validators as V

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error(errors.ERR_NOT_FOUND, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return response.error(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    return response.error("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sorted_by_created(values):
    """Ascending by creation order (PRD 2.3). _seq is the stable order key."""
    return sorted(values, key=lambda o: o["_seq"])


def get_or_404(store, _id):
    obj = store.get(_id)
    if obj is None:
        raise errors.not_found()
    return obj


def list_response(serializer, items_sorted):
    limit, offset = V.parse_pagination()
    page, total = V.paginate(items_sorted, limit, offset)
    return response.success_list([serializer(o) for o in page], limit, offset, total)


# ===========================================================================
# Logical clock (PRD 2.4 / 3) — the only unauthenticated endpoint
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = V.get_body()
    to_iso = V.require(body, "to_iso8601")
    dt = domain.parse_dt(to_iso)
    clock.set_now(dt)
    return response.success({}, 200)


# ===========================================================================
# Divers (PRD 3.1)
# ===========================================================================
@app.route("/divers", methods=["POST"])
def create_diver():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    email = V.require_str(body, "email")
    d = {
        "full_name": full_name,
        "email": email,
        "cert_level": "NONE",
        "nitrox_certified": False,
        "medical_status": "UNKNOWN",
        "deposit_on_hold_cents": 0,
    }
    db.stamp_create(d)
    db.divers[d["id"]] = d
    return response.success(domain.ser_diver(d), 201)


@app.route("/divers/<id>", methods=["GET"])
def get_diver(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    d = get_or_404(db.divers, id)
    if p.is_diver and p.user_id != d["id"]:
        raise errors.forbidden()
    return response.success(domain.ser_diver(d), 200)


@app.route("/divers", methods=["GET"])
def list_divers():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Instructor"})
    return list_response(domain.ser_diver, sorted_by_created(db.divers.values()))


# ===========================================================================
# Waivers (PRD 3.1)
# ===========================================================================
@app.route("/waivers", methods=["POST"])
def create_waiver():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    body = V.get_body()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    medical_flagged = V.require_bool(body, "medical_flagged")
    # ownership (priority 5)
    if p.is_diver and p.user_id != diver_id:
        raise errors.forbidden()

    now = clock.get_now()
    signed_at = now
    expires_at = domain.waiver_expiry(signed_at)
    w = {
        "diver_id": diver_id,
        "medical_flagged": medical_flagged,
        "signed_at": domain.to_iso(signed_at),
        "expires_at": domain.to_iso(expires_at),
        "_signed_at_dt": signed_at,
        "_expires_at_dt": expires_at,
    }
    db.stamp_create(w, common_fields=False)
    db.waivers[w["id"]] = w
    # recompute medical status from this now-latest waiver
    domain.recompute_medical_status(diver)
    db.touch(diver)
    return response.success(domain.ser_waiver(w), 201)


@app.route("/waivers/<id>", methods=["GET"])
def get_waiver(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    w = get_or_404(db.waivers, id)
    if p.is_diver and p.user_id != w["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_waiver(w), 200)


@app.route("/waivers", methods=["GET"])
def list_waivers():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    diver_id = request.args.get("diver_id")
    items = list(db.waivers.values())
    if diver_id is not None:
        items = [w for w in items if w["diver_id"] == diver_id]
    if p.is_diver:
        items = [w for w in items if w["diver_id"] == p.user_id]
    return list_response(domain.ser_waiver, sorted_by_created(items))


# ===========================================================================
# Certification cards (PRD 3.6) — read only, immutable
# ===========================================================================
@app.route("/certification-cards/<id>", methods=["GET"])
def get_card(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    c = get_or_404(db.certification_cards, id)
    if p.is_diver and p.user_id != c["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_certification_card(c), 200)


@app.route("/certification-cards", methods=["GET"])
def list_cards():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    diver_id = request.args.get("diver_id")
    enrollment_id = request.args.get("enrollment_id")
    items = list(db.certification_cards.values())
    if diver_id is not None:
        items = [c for c in items if c["diver_id"] == diver_id]
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if p.is_diver:
        items = [c for c in items if c["diver_id"] == p.user_id]
    return list_response(domain.ser_certification_card, sorted_by_created(items))


# ===========================================================================
# Instructors (PRD 3.2)
# ===========================================================================
@app.route("/instructors", methods=["POST"])
def create_instructor():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    full_name = V.require_str(body, "full_name")
    rating = V.require_enum(body, "rating", {"DIVEMASTER", "INSTRUCTOR"})
    i = {
        "full_name": full_name,
        "rating": rating,
        "active_session_count": 0,
    }
    db.stamp_create(i)
    db.instructors[i["id"]] = i
    return response.success(domain.ser_instructor(i), 201)


@app.route("/instructors/<id>", methods=["GET"])
def get_instructor(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Instructor"})
    i = get_or_404(db.instructors, id)
    return response.success(domain.ser_instructor(i), 200)


# ===========================================================================
# Courses (PRD 3.2)
# ===========================================================================
@app.route("/courses", methods=["POST"])
def create_course():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    title = V.require_str(body, "title")
    course_type = V.require_enum(body, "course_type", {"OPEN_WATER", "ADVANCED"})
    required_pool = V.require_int(body, "required_pool_sessions")
    if required_pool < 0:
        raise errors.invalid_request("required_pool_sessions must be >= 0")
    required_ow = V.require_int(body, "required_open_water_sessions")
    if required_ow < 1:
        raise errors.invalid_request("required_open_water_sessions must be >= 1")
    price_cents = V.require_int(body, "price_cents")
    if price_cents <= 0:
        raise errors.invalid_request("price_cents must be > 0")
    grants_specialty = V.opt_enum(body, "grants_specialty", {"NONE", "ENRICHED_AIR"}, "NONE")
    c = {
        "title": title,
        "course_type": course_type,
        "required_pool_sessions": required_pool,
        "required_open_water_sessions": required_ow,
        "price_cents": price_cents,
        "grants_specialty": grants_specialty,
    }
    db.stamp_create(c)
    db.courses[c["id"]] = c
    return response.success(domain.ser_course(c), 201)


@app.route("/courses/<id>", methods=["GET"])
def get_course(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    c = get_or_404(db.courses, id)
    return response.success(domain.ser_course(c), 200)


# ===========================================================================
# Enrollments (PRD 3.3)
# ===========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    body = V.get_body()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    course_id = V.require_str_id(body, "course_id")
    course = db.courses.get(course_id)
    if course is None:
        raise errors.not_found()
    if p.is_diver and p.user_id != diver_id:
        raise errors.forbidden()

    e = {
        "diver_id": diver_id,
        "course_id": course_id,
        "status": "ACTIVE",
        "elearning_pct": 0,
        "pool_sessions_attended": 0,
        "open_water_sessions_attended": 0,
        "completion_pct": 0,
        "certification_card_id": None,
    }
    db.stamp_create(e)
    e["completion_pct"] = domain.enrollment_completion_pct(e, course)
    db.enrollments[e["id"]] = e
    return response.success(domain.ser_enrollment(e), 201)


@app.route("/enrollments/<id>", methods=["GET"])
def get_enrollment(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    e = get_or_404(db.enrollments, id)
    if p.is_diver and p.user_id != e["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_enrollment(e), 200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    diver_id = request.args.get("diver_id")
    course_id = request.args.get("course_id")
    items = list(db.enrollments.values())
    if diver_id is not None:
        items = [e for e in items if e["diver_id"] == diver_id]
    if course_id is not None:
        items = [e for e in items if e["course_id"] == course_id]
    if p.is_diver:
        items = [e for e in items if e["diver_id"] == p.user_id]
    return list_response(domain.ser_enrollment, sorted_by_created(items))


@app.route("/enrollments/<id>/elearning-progress", methods=["POST"])
def set_elearning(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    e = get_or_404(db.enrollments, id)
    body = V.get_body()
    pct = V.require_int(body, "elearning_pct")
    if pct < 0 or pct > 100:
        raise errors.invalid_request("elearning_pct must be between 0 and 100")
    if p.is_diver and p.user_id != e["diver_id"]:
        raise errors.forbidden()
    e["elearning_pct"] = pct
    domain.recompute_enrollment(e)
    return response.success(domain.ser_enrollment(e), 200)


@app.route("/enrollments/<id>/recompute-eligibility", methods=["POST"])
def recompute_eligibility(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    e = get_or_404(db.enrollments, id)
    domain.recompute_enrollment(e, raise_on_gate=True)
    return response.success(domain.ser_enrollment(e), 200)


@app.route("/enrollments/<id>/issue-certification", methods=["POST"])
def issue_certification(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    e = get_or_404(db.enrollments, id)
    body = V.get_body()
    expected_version = V.require_int(body, "expected_enrollment_version")
    # state check (priority 6) before OCC (priority 7)
    if e["status"] != "ELIGIBLE":
        raise errors.invalid_state("Enrollment must be ELIGIBLE to issue certification")
    if expected_version != e["version"]:
        raise errors.stale_version("expected_enrollment_version does not match")

    course = db.courses[e["course_id"]]
    diver = db.divers[e["diver_id"]]

    now = clock.get_now()
    card = {
        "diver_id": e["diver_id"],
        "enrollment_id": e["id"],
        "level": course["course_type"],
        "specialty": course["grants_specialty"],
        "issued_at": domain.to_iso(now),
    }
    db.stamp_create(card, common_fields=False)
    db.certification_cards[card["id"]] = card

    e["status"] = "COMPLETED"
    e["certification_card_id"] = card["id"]
    db.touch(e)  # increments version by 1

    # CASCADE onto diver
    if domain.CERT_RANK[course["course_type"]] > domain.CERT_RANK[diver["cert_level"]]:
        diver["cert_level"] = course["course_type"]
    # nitrox recompute: true once any card with specialty ENRICHED_AIR issued
    has_nitrox = any(
        c["diver_id"] == diver["id"] and c["specialty"] == "ENRICHED_AIR"
        for c in db.certification_cards.values()
    )
    diver["nitrox_certified"] = has_nitrox
    db.touch(diver)

    return response.success(domain.ser_enrollment(e), 200)


@app.route("/enrollments/<id>/withdraw", methods=["POST"])
def withdraw_enrollment(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    e = get_or_404(db.enrollments, id)
    if p.is_diver and p.user_id != e["diver_id"]:
        raise errors.forbidden()
    if e["status"] not in ("ACTIVE", "ELIGIBLE"):
        raise errors.invalid_state("Enrollment must be ACTIVE or ELIGIBLE to withdraw")
    e["status"] = "WITHDRAWN"
    # cascade: release BOOKED bookings
    for b in db.session_bookings.values():
        if b["enrollment_id"] == e["id"] and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            db.touch(b)
            sess = db.sessions.get(b["session_id"])
            if sess is not None:
                domain.recompute_session_seats(sess)
                db.touch(sess)
    db.touch(e)
    return response.success(domain.ser_enrollment(e), 200)


# ===========================================================================
# Sessions (PRD 3.4)
# ===========================================================================
@app.route("/sessions", methods=["POST"])
def create_session():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    course_id = V.require_str_id(body, "course_id")
    course = db.courses.get(course_id)
    if course is None:
        raise errors.not_found()
    primary_instructor_id = V.require_str_id(body, "primary_instructor_id")
    instructor = db.instructors.get(primary_instructor_id)
    if instructor is None:
        raise errors.not_found()
    session_type = V.require_enum(body, "session_type", {"POOL", "OPEN_WATER"})
    assistant_count = V.opt_int(body, "assistant_count", 0)
    if assistant_count < 0:
        raise errors.invalid_request("assistant_count must be >= 0")
    starts_at_raw = V.require(body, "starts_at")
    ends_at_raw = V.require(body, "ends_at")
    starts_at = domain.parse_dt(starts_at_raw)
    ends_at = domain.parse_dt(ends_at_raw)
    if not (ends_at > starts_at):
        raise errors.invalid_request("ends_at must be after starts_at")

    # business constraint (priority 10): instructor rating + half-open overlap
    if instructor["rating"] != "INSTRUCTOR":
        raise errors.instructor_conflict("Primary instructor must be rated INSTRUCTOR")
    for s in db.sessions.values():
        if s["primary_instructor_id"] != primary_instructor_id:
            continue
        if s["status"] != "SCHEDULED":
            continue
        s_start = domain.parse_dt(s["starts_at"])
        s_end = domain.parse_dt(s["ends_at"])
        # half-open [start, end): overlap iff start < s_end and s_start < end
        if starts_at < s_end and s_start < ends_at:
            raise errors.instructor_conflict("Instructor has an overlapping scheduled session")

    sess = {
        "course_id": course_id,
        "session_type": session_type,
        "primary_instructor_id": primary_instructor_id,
        "assistant_count": assistant_count,
        "starts_at": domain.to_iso(starts_at),
        "ends_at": domain.to_iso(ends_at),
        "max_students": domain.instructor_ratio_capacity(session_type, assistant_count),
        "confirmed_seats": 0,
        "status": "SCHEDULED",
    }
    db.stamp_create(sess)
    db.sessions[sess["id"]] = sess
    domain.recompute_instructor_active(instructor)
    return response.success(domain.ser_session(sess), 201)


@app.route("/sessions/<id>", methods=["GET"])
def get_session(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    s = get_or_404(db.sessions, id)
    return response.success(domain.ser_session(s), 200)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    course_id = request.args.get("course_id")
    primary_instructor_id = request.args.get("primary_instructor_id")
    items = list(db.sessions.values())
    if course_id is not None:
        items = [s for s in items if s["course_id"] == course_id]
    if primary_instructor_id is not None:
        items = [s for s in items if s["primary_instructor_id"] == primary_instructor_id]
    return list_response(domain.ser_session, sorted_by_created(items))


@app.route("/sessions/<id>/complete", methods=["POST"])
def complete_session(id):
    p = auth.authenticate()
    auth.require_roles(p, {"Instructor"})
    s = get_or_404(db.sessions, id)
    # ownership (priority 5): acting instructor must be the primary instructor
    if p.user_id != s["primary_instructor_id"]:
        raise errors.forbidden()
    # state (priority 6)
    if s["status"] != "SCHEDULED":
        raise errors.invalid_state("Session must be SCHEDULED to complete")
    # temporal: clock >= starts_at
    if clock.get_now() < domain.parse_dt(s["starts_at"]):
        raise errors.invalid_state("Cannot complete a session before its start time")

    s["status"] = "COMPLETED"
    # un-attended BOOKED bookings -> NO_SHOW
    for b in db.session_bookings.values():
        if b["session_id"] == s["id"] and b["status"] == "BOOKED":
            b["status"] = "NO_SHOW"
            db.touch(b)
    domain.recompute_session_seats(s)
    db.touch(s)
    instructor = db.instructors.get(s["primary_instructor_id"])
    if instructor is not None:
        domain.recompute_instructor_active(instructor)
    return response.success(domain.ser_session(s), 200)


@app.route("/sessions/<id>/cancel", methods=["POST"])
def cancel_session(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    s = get_or_404(db.sessions, id)
    if s["status"] != "SCHEDULED":
        raise errors.invalid_state("Session must be SCHEDULED to cancel")

    s["status"] = "CANCELLED"
    # CASCADE depth 3
    for b in db.session_bookings.values():
        if b["session_id"] != s["id"]:
            continue
        if b["status"] in ("BOOKED", "ATTENDED"):
            was_attended = b["status"] == "ATTENDED"
            b["status"] = "CANCELLED"
            db.touch(b)
            if was_attended:
                enr = db.enrollments.get(b["enrollment_id"])
                if enr is not None:
                    if s["session_type"] == "POOL":
                        enr["pool_sessions_attended"] = max(0, enr["pool_sessions_attended"] - 1)
                    else:
                        enr["open_water_sessions_attended"] = max(0, enr["open_water_sessions_attended"] - 1)
                    domain.recompute_enrollment(enr)
    domain.recompute_session_seats(s)
    db.touch(s)
    instructor = db.instructors.get(s["primary_instructor_id"])
    if instructor is not None:
        domain.recompute_instructor_active(instructor)
    return response.success(domain.ser_session(s), 200)


# ===========================================================================
# Session bookings (PRD 3.5)
# ===========================================================================
@app.route("/session-bookings", methods=["POST"])
def create_session_booking():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    body = V.get_body()
    # existence (priority 3) left-to-right: session_id then enrollment_id
    session_id = V.require_str_id(body, "session_id")
    sess = db.sessions.get(session_id)
    if sess is None:
        raise errors.not_found()
    enrollment_id = V.require_str_id(body, "enrollment_id")
    enr = db.enrollments.get(enrollment_id)
    if enr is None:
        raise errors.not_found()
    expected_session_version = V.require_int(body, "expected_session_version")

    # ownership (priority 5): diver acts on own enrollment
    if p.is_diver and p.user_id != enr["diver_id"]:
        raise errors.forbidden()

    # state (priority 6): enrollment ACTIVE and session SCHEDULED
    if enr["status"] != "ACTIVE" or sess["status"] != "SCHEDULED":
        raise errors.invalid_state("Enrollment must be ACTIVE and session SCHEDULED")

    # OCC (priority 7)
    if expected_session_version != sess["version"]:
        raise errors.stale_version("expected_session_version does not match")

    # waiver/medical gate (priority 8)
    diver = db.divers[enr["diver_id"]]
    if not domain.has_active_waiver(diver["id"]) or diver["medical_status"] == "RESTRICTED":
        raise errors.waiver_required()

    # capacity (priority 12)
    if sess["confirmed_seats"] + 1 > sess["max_students"]:
        raise errors.capacity_exceeded("Session is at capacity")

    # duplicate (priority 13): at most one non-terminal booking per (enrollment, session)
    for b in db.session_bookings.values():
        if (b["enrollment_id"] == enrollment_id and b["session_id"] == session_id
                and b["status"] in ("BOOKED", "ATTENDED")):
            raise errors.duplicate_booking("A non-terminal booking already exists for this enrollment and session")

    booking = {
        "session_id": session_id,
        "enrollment_id": enrollment_id,
        "status": "BOOKED",
    }
    db.stamp_create(booking)
    db.session_bookings[booking["id"]] = booking
    domain.recompute_session_seats(sess)
    db.touch(sess)  # increments session.version by 1
    return response.success(domain.ser_session_booking(booking), 201)


@app.route("/session-bookings/<id>", methods=["GET"])
def get_session_booking(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    b = get_or_404(db.session_bookings, id)
    if p.is_diver:
        enr = db.enrollments.get(b["enrollment_id"])
        if enr is None or enr["diver_id"] != p.user_id:
            raise errors.forbidden()
    return response.success(domain.ser_session_booking(b), 200)


@app.route("/session-bookings", methods=["GET"])
def list_session_bookings():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    session_id = request.args.get("session_id")
    enrollment_id = request.args.get("enrollment_id")
    items = list(db.session_bookings.values())
    if session_id is not None:
        items = [b for b in items if b["session_id"] == session_id]
    if enrollment_id is not None:
        items = [b for b in items if b["enrollment_id"] == enrollment_id]
    if p.is_diver:
        own = {e["id"] for e in db.enrollments.values() if e["diver_id"] == p.user_id}
        items = [b for b in items if b["enrollment_id"] in own]
    return list_response(domain.ser_session_booking, sorted_by_created(items))


@app.route("/session-bookings/<id>/attend", methods=["POST"])
def attend_booking(id):
    p = auth.authenticate()
    auth.require_roles(p, {"Instructor"})
    b = get_or_404(db.session_bookings, id)
    sess = db.sessions.get(b["session_id"])
    # ownership (priority 5): instructor must be the session's primary instructor
    if sess is None or p.user_id != sess["primary_instructor_id"]:
        raise errors.forbidden()
    # state (priority 6): booking BOOKED and session SCHEDULED
    if b["status"] != "BOOKED":
        raise errors.invalid_state("Booking must be BOOKED to record attendance")
    if sess["status"] != "SCHEDULED":
        raise errors.invalid_state("Session must be SCHEDULED to record attendance")

    b["status"] = "ATTENDED"
    db.touch(b)
    enr = db.enrollments.get(b["enrollment_id"])
    if enr is not None:
        if sess["session_type"] == "POOL":
            enr["pool_sessions_attended"] += 1
        else:
            enr["open_water_sessions_attended"] += 1
        domain.recompute_enrollment(enr)
    # BOOKED -> ATTENDED removes a BOOKED seat; keep conserved counter in step
    domain.recompute_session_seats(sess)
    db.touch(sess)
    return response.success(domain.ser_session_booking(b), 200)


@app.route("/session-bookings/<id>/cancel", methods=["POST"])
def cancel_session_booking(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    b = get_or_404(db.session_bookings, id)
    if p.is_diver:
        enr = db.enrollments.get(b["enrollment_id"])
        if enr is None or enr["diver_id"] != p.user_id:
            raise errors.forbidden()
    if b["status"] != "BOOKED":
        raise errors.invalid_state("Booking must be BOOKED to cancel")
    b["status"] = "CANCELLED"
    db.touch(b)
    sess = db.sessions.get(b["session_id"])
    if sess is not None:
        domain.recompute_session_seats(sess)
        db.touch(sess)
    return response.success(domain.ser_session_booking(b), 200)


# ===========================================================================
# Boats (PRD 3.2)
# ===========================================================================
@app.route("/boats", methods=["POST"])
def create_boat():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    name = V.require_str(body, "name")
    capacity = V.require_int(body, "capacity")
    if capacity <= 0:
        raise errors.invalid_request("capacity must be > 0")
    turnaround_minutes = V.opt_int(body, "turnaround_minutes", 60)
    if turnaround_minutes < 0:
        raise errors.invalid_request("turnaround_minutes must be >= 0")
    b = {
        "name": name,
        "capacity": capacity,
        "turnaround_minutes": turnaround_minutes,
    }
    db.stamp_create(b)
    db.boats[b["id"]] = b
    return response.success(domain.ser_boat(b), 201)


@app.route("/boats/<id>", methods=["GET"])
def get_boat(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    b = get_or_404(db.boats, id)
    return response.success(domain.ser_boat(b), 200)


# ===========================================================================
# Dive trips (PRD 3.7)
# ===========================================================================
@app.route("/dive-trips", methods=["POST"])
def create_dive_trip():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    boat_id = V.require_str_id(body, "boat_id")
    boat = db.boats.get(boat_id)
    if boat is None:
        raise errors.not_found()
    starts_at = domain.parse_dt(V.require(body, "starts_at"))
    ends_at = domain.parse_dt(V.require(body, "ends_at"))
    if not (ends_at > starts_at):
        raise errors.invalid_request("ends_at must be after starts_at")
    min_cert_level = V.require_enum(body, "min_cert_level", {"OPEN_WATER", "ADVANCED"})
    base_fare_cents = V.require_int(body, "base_fare_cents")
    if base_fare_cents <= 0:
        raise errors.invalid_request("base_fare_cents must be > 0")
    fill_addon_cents = V.require_int(body, "fill_addon_cents")
    if fill_addon_cents < 0:
        raise errors.invalid_request("fill_addon_cents must be >= 0")

    # boat conflict (priority 11): closed-with-buffer overlap on same boat
    from datetime import timedelta
    buffer = timedelta(minutes=boat["turnaround_minutes"])
    for t in db.dive_trips.values():
        if t["boat_id"] != boat_id:
            continue
        if t["status"] == "CANCELLED":
            continue
        t_start = domain.parse_dt(t["starts_at"]) - buffer
        t_end = domain.parse_dt(t["ends_at"]) + buffer
        # closed (inclusive) overlap: starts_at <= t_end and t_start <= ends_at
        if starts_at <= t_end and t_start <= ends_at:
            raise errors.boat_conflict("Boat has a conflicting trip within the turnaround buffer")

    t = {
        "boat_id": boat_id,
        "starts_at": domain.to_iso(starts_at),
        "ends_at": domain.to_iso(ends_at),
        "min_cert_level": min_cert_level,
        "base_fare_cents": base_fare_cents,
        "fill_addon_cents": fill_addon_cents,
        "confirmed_divers": 0,
        "status": "OPEN",
    }
    db.stamp_create(t)
    db.dive_trips[t["id"]] = t
    return response.success(domain.ser_dive_trip(t), 201)


@app.route("/dive-trips/<id>", methods=["GET"])
def get_dive_trip(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    t = get_or_404(db.dive_trips, id)
    return response.success(domain.ser_dive_trip(t), 200)


@app.route("/dive-trips", methods=["GET"])
def list_dive_trips():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver", "Instructor"})
    boat_id = request.args.get("boat_id")
    items = list(db.dive_trips.values())
    if boat_id is not None:
        items = [t for t in items if t["boat_id"] == boat_id]
    return list_response(domain.ser_dive_trip, sorted_by_created(items))


@app.route("/dive-trips/<id>/depart", methods=["POST"])
def depart_trip(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    t = get_or_404(db.dive_trips, id)
    if t["status"] != "OPEN":
        raise errors.invalid_state("Trip must be OPEN to depart")
    if clock.get_now() < domain.parse_dt(t["starts_at"]):
        raise errors.invalid_state("Cannot depart a trip before its start time")
    t["status"] = "DEPARTED"
    for tb in db.trip_bookings.values():
        if tb["trip_id"] == t["id"] and tb["status"] == "CONFIRMED":
            tb["balance_due_cents"] = 0
            tb["status"] = "DEPARTED"
            db.touch(tb)
    db.touch(t)
    return response.success(domain.ser_dive_trip(t), 200)


@app.route("/dive-trips/<id>/cancel", methods=["POST"])
def cancel_trip(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    t = get_or_404(db.dive_trips, id)
    if t["status"] != "OPEN":
        raise errors.invalid_state("Trip must be OPEN to cancel")
    t["status"] = "CANCELLED"
    for tb in db.trip_bookings.values():
        if tb["trip_id"] == t["id"] and tb["status"] == "CONFIRMED":
            tb["status"] = "CANCELLED"
            db.touch(tb)
    domain.recompute_trip_divers(t)
    db.touch(t)
    return response.success(domain.ser_dive_trip(t), 200)


# ===========================================================================
# Trip bookings (PRD 3.7)
# ===========================================================================
@app.route("/trip-bookings", methods=["POST"])
def create_trip_booking():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    body = V.get_body()
    # existence left-to-right: trip_id then diver_id
    trip_id = V.require_str_id(body, "trip_id")
    trip = db.dive_trips.get(trip_id)
    if trip is None:
        raise errors.not_found()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    tanks = V.opt_int(body, "tanks", 0)
    if tanks < 0:
        raise errors.invalid_request("tanks must be >= 0")
    party_size = V.opt_int(body, "party_size", 1)
    if party_size < 1:
        raise errors.invalid_request("party_size must be >= 1")
    expected_trip_version = V.require_int(body, "expected_trip_version")

    # ownership (priority 5)
    if p.is_diver and p.user_id != diver_id:
        raise errors.forbidden()

    # state (priority 6): trip must be OPEN
    if trip["status"] != "OPEN":
        raise errors.invalid_state("Trip must be OPEN to book")

    # OCC (priority 7)
    if expected_trip_version != trip["version"]:
        raise errors.stale_version("expected_trip_version does not match")

    # cert prerequisite (priority 9) — note PRD 3.7 lists OCC, then cert, then waiver
    if domain.CERT_RANK[diver["cert_level"]] < domain.CERT_RANK[trip["min_cert_level"]]:
        raise errors.cert_prerequisite("Diver cert_level below trip minimum")

    # waiver/medical gate (priority 8 in §1.4 ordering; PRD 3.7 narrates cert before
    # waiver, but §2.9 fixes the priority order as waiver(8) before cert(9). We follow
    # §2.9: waiver gate precedence. However PRD 3.7 prose lists cert then waiver.)
    if not domain.has_active_waiver(diver["id"]) or diver["medical_status"] == "RESTRICTED":
        raise errors.waiver_required()

    # capacity (priority 12)
    boat = db.boats[trip["boat_id"]]
    if trip["confirmed_divers"] + 1 > boat["capacity"]:
        raise errors.capacity_exceeded("Trip is at boat capacity")

    # duplicate (priority 13): at most one non-CANCELLED booking per (diver, trip)
    for tb in db.trip_bookings.values():
        if (tb["diver_id"] == diver_id and tb["trip_id"] == trip_id
                and tb["status"] != "CANCELLED"):
            raise errors.duplicate_booking("A non-cancelled booking already exists for this diver and trip")

    total, deposit, balance = domain.trip_booking_total(trip, tanks, party_size)
    tb = {
        "trip_id": trip_id,
        "diver_id": diver_id,
        "tanks": tanks,
        "party_size": party_size,
        "total_cents": total,
        "deposit_cents": deposit,
        "balance_due_cents": balance,
        "status": "CONFIRMED",
    }
    db.stamp_create(tb)
    db.trip_bookings[tb["id"]] = tb
    domain.recompute_trip_divers(trip)
    db.touch(trip)  # increments trip.version by 1
    return response.success(domain.ser_trip_booking(tb), 201)


@app.route("/trip-bookings/<id>", methods=["GET"])
def get_trip_booking(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    tb = get_or_404(db.trip_bookings, id)
    if p.is_diver and p.user_id != tb["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_trip_booking(tb), 200)


@app.route("/trip-bookings", methods=["GET"])
def list_trip_bookings():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    trip_id = request.args.get("trip_id")
    diver_id = request.args.get("diver_id")
    items = list(db.trip_bookings.values())
    if trip_id is not None:
        items = [tb for tb in items if tb["trip_id"] == trip_id]
    if diver_id is not None:
        items = [tb for tb in items if tb["diver_id"] == diver_id]
    if p.is_diver:
        items = [tb for tb in items if tb["diver_id"] == p.user_id]
    return list_response(domain.ser_trip_booking, sorted_by_created(items))


@app.route("/trip-bookings/<id>/cancel", methods=["POST"])
def cancel_trip_booking(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    tb = get_or_404(db.trip_bookings, id)
    if p.is_diver and p.user_id != tb["diver_id"]:
        raise errors.forbidden()
    if tb["status"] != "CONFIRMED":
        raise errors.invalid_state("Trip booking must be CONFIRMED to cancel")
    tb["status"] = "CANCELLED"
    db.touch(tb)
    trip = db.dive_trips.get(tb["trip_id"])
    if trip is not None:
        domain.recompute_trip_divers(trip)
        db.touch(trip)
    return response.success(domain.ser_trip_booking(tb), 200)


# ===========================================================================
# Rental agreements (PRD 3.8)
# ===========================================================================
@app.route("/rental-agreements", methods=["POST"])
def create_rental():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    item_description = V.require_str(body, "item_description")
    daily_rate_cents = V.require_int(body, "daily_rate_cents")
    if daily_rate_cents <= 0:
        raise errors.invalid_request("daily_rate_cents must be > 0")
    deposit_cents = V.require_int(body, "deposit_cents")
    if deposit_cents < 0:
        raise errors.invalid_request("deposit_cents must be >= 0")
    scheduled_return_at = domain.parse_dt(V.require(body, "scheduled_return_at"))

    now = clock.get_now()
    estimated = domain.rental_estimated_cost(now, scheduled_return_at, daily_rate_cents)
    r = {
        "diver_id": diver_id,
        "item_description": item_description,
        "daily_rate_cents": daily_rate_cents,
        "deposit_cents": deposit_cents,
        "checkout_at": domain.to_iso(now),
        "scheduled_return_at": domain.to_iso(scheduled_return_at),
        "actual_return_at": None,
        "damage_fee_cents": 0,
        "estimated_cost_cents": estimated,
        "actual_cost_cents": None,
        "deposit_refund_cents": None,
        "status": "ACTIVE",
        "_checkout_at_dt": now,
        "_scheduled_return_at_dt": scheduled_return_at,
    }
    db.stamp_create(r)
    db.rental_agreements[r["id"]] = r
    domain.recompute_diver_deposit(diver)
    return response.success(domain.ser_rental(r), 201)


@app.route("/rental-agreements/<id>", methods=["GET"])
def get_rental(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    r = get_or_404(db.rental_agreements, id)
    if p.is_diver and p.user_id != r["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_rental(r), 200)


@app.route("/rental-agreements", methods=["GET"])
def list_rentals():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    diver_id = request.args.get("diver_id")
    items = list(db.rental_agreements.values())
    if diver_id is not None:
        items = [r for r in items if r["diver_id"] == diver_id]
    if p.is_diver:
        items = [r for r in items if r["diver_id"] == p.user_id]
    return list_response(domain.ser_rental, sorted_by_created(items))


@app.route("/rental-agreements/<id>/checkin", methods=["POST"])
def checkin_rental(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    r = get_or_404(db.rental_agreements, id)
    body = V.get_body()
    damage_fee_cents = V.opt_int(body, "damage_fee_cents", 0)
    if damage_fee_cents < 0:
        raise errors.invalid_request("damage_fee_cents must be >= 0")
    if r["status"] != "ACTIVE":
        raise errors.invalid_state("Rental must be ACTIVE to check in")

    now = clock.get_now()
    r["actual_return_at"] = domain.to_iso(now)
    r["damage_fee_cents"] = damage_fee_cents
    actual = domain.rental_actual_cost(
        r["_checkout_at_dt"], r["_scheduled_return_at_dt"], now,
        r["daily_rate_cents"], damage_fee_cents)
    r["actual_cost_cents"] = actual
    r["deposit_refund_cents"] = domain.rental_settlement(
        actual, r["estimated_cost_cents"], r["deposit_cents"])
    r["status"] = "RETURNED"
    db.touch(r)
    diver = db.divers.get(r["diver_id"])
    if diver is not None:
        domain.recompute_diver_deposit(diver)
    return response.success(domain.ser_rental(r), 200)


@app.route("/rental-agreements/<id>/void", methods=["POST"])
def void_rental(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    r = get_or_404(db.rental_agreements, id)
    if r["status"] != "ACTIVE":
        raise errors.invalid_state("Rental must be ACTIVE to void")
    # void only when no time has elapsed since checkout (PRD 3.8)
    if clock.get_now() != r["_checkout_at_dt"]:
        raise errors.invalid_state("Void permitted only when no time has elapsed since checkout")
    r["status"] = "VOIDED"
    r["actual_cost_cents"] = 0
    r["deposit_refund_cents"] = r["deposit_cents"]
    db.touch(r)
    diver = db.divers.get(r["diver_id"])
    if diver is not None:
        domain.recompute_diver_deposit(diver)
    return response.success(domain.ser_rental(r), 200)


# ===========================================================================
# Fill services (PRD 3.9)
# ===========================================================================
@app.route("/fill-services", methods=["POST"])
def create_fill():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    gas = V.require_enum(body, "gas", {"AIR", "NITROX"})
    o2_pct = V.require_int(body, "o2_pct")
    tank_capacity_liters = V.require_int(body, "tank_capacity_liters")
    if tank_capacity_liters <= 0:
        raise errors.invalid_request("tank_capacity_liters must be > 0")
    # o2 band per gas (priority 4 well-formedness)
    if gas == "AIR":
        if o2_pct != 21:
            raise errors.invalid_request("o2_pct must be exactly 21 for AIR")
    else:  # NITROX
        if o2_pct < 22 or o2_pct > 40:
            raise errors.invalid_request("o2_pct must be between 22 and 40 for NITROX")

    # cert prerequisite (priority 9): NITROX requires nitrox_certified
    if gas == "NITROX" and not diver["nitrox_certified"]:
        raise errors.cert_prerequisite("NITROX fill requires a nitrox-certified diver")

    price = domain.fill_price(gas, o2_pct, tank_capacity_liters)
    f = {
        "diver_id": diver_id,
        "gas": gas,
        "o2_pct": o2_pct,
        "tank_capacity_liters": tank_capacity_liters,
        "price_cents": price,
    }
    db.stamp_create(f)
    db.fill_services[f["id"]] = f
    return response.success(domain.ser_fill(f), 201)


@app.route("/fill-services/<id>", methods=["GET"])
def get_fill(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    f = get_or_404(db.fill_services, id)
    if p.is_diver and p.user_id != f["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_fill(f), 200)


@app.route("/fill-services", methods=["GET"])
def list_fills():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    diver_id = request.args.get("diver_id")
    items = list(db.fill_services.values())
    if diver_id is not None:
        items = [f for f in items if f["diver_id"] == diver_id]
    if p.is_diver:
        items = [f for f in items if f["diver_id"] == p.user_id]
    return list_response(domain.ser_fill, sorted_by_created(items))


# ===========================================================================
# Gear service orders (PRD 3.9)
# ===========================================================================
@app.route("/gear-service-orders", methods=["POST"])
def create_gear_order():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    body = V.get_body()
    diver_id = V.require_str_id(body, "diver_id")
    diver = db.divers.get(diver_id)
    if diver is None:
        raise errors.not_found()
    service_type = V.require_enum(body, "service_type", {"VIP", "HYDRO"})
    g = {
        "diver_id": diver_id,
        "service_type": service_type,
        "serviced_at": None,
        "next_due_at": None,
        "status": "OPEN",
    }
    db.stamp_create(g)
    db.gear_service_orders[g["id"]] = g
    return response.success(domain.ser_gear_order(g), 201)


@app.route("/gear-service-orders/<id>", methods=["GET"])
def get_gear_order(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    g = get_or_404(db.gear_service_orders, id)
    if p.is_diver and p.user_id != g["diver_id"]:
        raise errors.forbidden()
    return response.success(domain.ser_gear_order(g), 200)


@app.route("/gear-service-orders", methods=["GET"])
def list_gear_orders():
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin", "Diver"})
    diver_id = request.args.get("diver_id")
    items = list(db.gear_service_orders.values())
    if diver_id is not None:
        items = [g for g in items if g["diver_id"] == diver_id]
    if p.is_diver:
        items = [g for g in items if g["diver_id"] == p.user_id]
    return list_response(domain.ser_gear_order, sorted_by_created(items))


@app.route("/gear-service-orders/<id>/complete", methods=["POST"])
def complete_gear_order(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    g = get_or_404(db.gear_service_orders, id)
    if g["status"] != "OPEN":
        raise errors.invalid_state("Order must be OPEN to complete")
    now = clock.get_now()
    g["serviced_at"] = domain.to_iso(now)
    g["next_due_at"] = domain.to_iso(domain.gear_service_due(now, g["service_type"]))
    g["status"] = "COMPLETED"
    db.touch(g)
    return response.success(domain.ser_gear_order(g), 200)


@app.route("/gear-service-orders/<id>/cancel", methods=["POST"])
def cancel_gear_order(id):
    p = auth.authenticate()
    auth.require_roles(p, {"ShopAdmin"})
    g = get_or_404(db.gear_service_orders, id)
    if g["status"] != "OPEN":
        raise errors.invalid_state("Order must be OPEN to cancel")
    g["status"] = "CANCELLED"
    db.touch(g)
    return response.success(domain.ser_gear_order(g), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
