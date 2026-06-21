"""Enrollment lifecycle: single-course enroll, bundle enroll, get/list, refund,
reverse-reach reads (PRD §3.4, §3.6, §3.7-3.9)."""
from flask import Blueprint, request

import clock
import response
from db import db, new_id, iso
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str, as_int,
                             paginate, parse_dt, add_days)
from services.ledger import write_entry, recompute_balances
from services.pricing import (single_course_gross, instructor_share, allocate_bundle)
from services.course_derived import recompute_enrollment_count
from services.enrollment_logic import maybe_expire
from services.serialize import view, view_list

bp = Blueprint("enrollments", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _new_enrollment(course, learner_id, bundle_id, coupon_id, gross, inst_share):
    course_id = course["id"]
    enrolled_at = clock.now()
    refund_deadline = add_days(enrolled_at, course["refund_window_days"])
    rec = {
        "id": new_id(),
        "course_id": course_id,
        "learner_id": learner_id,
        "bundle_id": bundle_id,
        "coupon_id": coupon_id,
        "status": "ACTIVE",
        "list_price_cents": course["list_price_cents"],
        "gross_price_cents": gross,
        "platform_fee_cents": gross - inst_share,
        "instructor_share_cents": inst_share,
        "enrolled_at": iso(enrolled_at),
        "refund_deadline": iso(refund_deadline),
        "completed_lesson_count": 0,
        "progress_pct": 0.0,
        "weighted_score_pct": 0.0,
        "ceu_awarded": 0.0,
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    return rec


def _has_blocking_enrollment(learner_id, course_id):
    """True if learner already holds an enrollment in {ACTIVE, COMPLETED,
    EXPIRED} for this course (REFUNDED does not block)."""
    for e in db.enrollments.values():
        if (e["learner_id"] == learner_id and e["course_id"] == course_id
                and e["status"] in ("ACTIVE", "COMPLETED", "EXPIRED")):
            return True
    return False


# --------------------------------------------------------------------------
# Single-course enroll
# --------------------------------------------------------------------------

@bp.route("/courses/<course_id>/enroll", methods=["POST"])
def enroll_course(course_id):
    principal = authenticate()
    require_roles(principal, "Learner")
    body = _body()
    learner_id = as_str(require_field(body, "learner_id"), "learner_id")
    coupon_code = body.get("coupon_code")
    if coupon_code is not None and not isinstance(coupon_code, str):
        raise err("ERR_INVALID_REQUEST", "coupon_code must be a string.")

    # ownership: a Learner enrolls itself
    if principal.user_id != learner_id:
        raise err("ERR_FORBIDDEN")

    # existence: course, then learner
    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND")
    if learner_id not in db.learners:
        raise err("ERR_NOT_FOUND")

    # state: course must be PUBLISHED to enroll (DRAFT/UNPUBLISHED/RETIRED block)
    if course["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE", "Course is not enrollable.")

    # requires >= 1 published lesson to be enrollable
    if course["published_lesson_count"] < 1 and not any(
            l for l in db.lessons.values()
            if l["course_id"] == course_id and l.get("is_published")):
        # recompute defensively
        published = [l for l in db.lessons.values()
                     if l["course_id"] == course_id and l.get("is_published")]
        if len(published) < 1:
            raise err("ERR_INVALID_STATE", "Course has no published lessons.")

    # Resolve coupon (if supplied) and run coupon validations in PRD order.
    coupon = None
    if coupon_code is not None:
        coupon = _resolve_coupon(course, coupon_code)

    # duplicate-enrollment guard
    if _has_blocking_enrollment(learner_id, course_id):
        raise err("ERR_ALREADY_ENROLLED")

    # coupon exhausted check (priority 8)
    if coupon is not None and coupon["redeemed_count"] >= coupon["max_redemptions"]:
        raise err("ERR_COUPON_EXHAUSTED")

    # ---- pricing ----
    gross = single_course_gross(course["list_price_cents"], coupon)
    inst = db.instructors[course["instructor_id"]]
    inst_share = instructor_share(gross, inst["revenue_share_pct"])

    coupon_id = coupon["id"] if coupon is not None else None
    enrollment = _new_enrollment(course, learner_id, None, coupon_id, gross, inst_share)

    # SALE ledger entry PENDING + recompute balances
    write_entry(course["instructor_id"], "SALE", inst_share, "PENDING",
                enrollment_id=enrollment["id"])
    recompute_balances(course["instructor_id"])

    # coupon redeemed_count++ and maybe EXHAUSTED
    if coupon is not None:
        coupon["redeemed_count"] += 1
        if coupon["redeemed_count"] == coupon["max_redemptions"]:
            coupon["status"] = "EXHAUSTED"
        touch(coupon)

    # course enrollment_count++
    recompute_enrollment_count(course)
    touch(course)

    return response.success(view(enrollment), status=201)


def _resolve_coupon(course, coupon_code):
    """Resolve a coupon by code for the course's instructor and run redemption
    validations (PRD §3.5): not-redeemable (window/status), course mismatch."""
    # Resolve case-insensitively among the course's instructor's coupons.
    matched = None
    for c in db.coupons.values():
        if (c["instructor_id"] == course["instructor_id"]
                and c["code"].lower() == coupon_code.lower()):
            matched = c
            break
    if matched is None:
        # A coupon code that resolves to nothing on this course -> mismatch.
        raise err("ERR_COUPON_COURSE_MISMATCH", "Coupon does not apply to this course.")

    now = clock.now()
    vf = parse_dt(matched["valid_from"])
    vu = parse_dt(matched["valid_until"])
    # redeemable only when ACTIVE and valid_from <= now < valid_until
    if matched["status"] != "ACTIVE" or not (vf <= now < vu):
        raise err("ERR_COUPON_NOT_REDEEMABLE")

    # course mismatch / owner mismatch
    if matched["course_id"] != course["id"] or matched["instructor_id"] != course["instructor_id"]:
        raise err("ERR_COUPON_COURSE_MISMATCH")

    return matched


# --------------------------------------------------------------------------
# Bundle enroll (OCC on bundle)
# --------------------------------------------------------------------------

@bp.route("/bundles/<bundle_id>/enroll", methods=["POST"])
def enroll_bundle(bundle_id):
    principal = authenticate()
    require_roles(principal, "Learner")
    body = _body()
    learner_id = as_str(require_field(body, "learner_id"), "learner_id")
    expected_version = as_int(require_field(body, "expected_bundle_version"),
                              "expected_bundle_version")

    if principal.user_id != learner_id:
        raise err("ERR_FORBIDDEN")

    bundle = db.bundles.get(bundle_id)
    if bundle is None:
        raise err("ERR_NOT_FOUND")
    if learner_id not in db.learners:
        raise err("ERR_NOT_FOUND")

    # state: bundle must be ACTIVE
    if bundle["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Bundle is not active.")

    # OCC (evaluated after existence + state)
    if expected_version != bundle["version"]:
        raise err("ERR_STALE_VERSION")

    distinct = bundle["course_ids"]
    members = [db.courses[cid] for cid in distinct]

    # Atomicity: check duplicate-enrollment guard for EVERY member first.
    for c in members:
        if _has_blocking_enrollment(learner_id, c["id"]):
            raise err("ERR_ALREADY_ENROLLED")

    # allocate bundle price across members (largest-remainder)
    allocations = allocate_bundle(bundle["bundle_price_cents"], members)

    created = []
    for c in members:
        gross = allocations[c["id"]]
        inst = db.instructors[c["instructor_id"]]
        inst_share = instructor_share(gross, inst["revenue_share_pct"])
        enrollment = _new_enrollment(c, learner_id, bundle_id, None, gross, inst_share)
        write_entry(c["instructor_id"], "SALE", inst_share, "PENDING",
                    enrollment_id=enrollment["id"])
        recompute_balances(c["instructor_id"])
        recompute_enrollment_count(c)
        touch(c)
        created.append(enrollment)

    # bundle version++
    touch(bundle)

    return response.success(view_list(created), status=201)


# --------------------------------------------------------------------------
# Get / list enrollment
# --------------------------------------------------------------------------

def _refresh_enrollment(enrollment):
    """Lazy-expire then recompute progress/score against the current course."""
    maybe_expire(enrollment)
    course = db.courses.get(enrollment["course_id"])
    if course is not None:
        from services.enrollment_logic import recompute_progress
        recompute_progress(enrollment, course)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment(enrollment_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    _check_enrollment_read_access(principal, enrollment)
    _refresh_enrollment(enrollment)
    return response.success(view(enrollment), status=200)


def _check_enrollment_read_access(principal, enrollment):
    if principal.role == "Learner":
        if enrollment["learner_id"] != principal.user_id:
            raise err("ERR_FORBIDDEN")
    elif principal.role == "Instructor":
        course = db.courses.get(enrollment["course_id"])
        if course is None or course["instructor_id"] != principal.user_id:
            raise err("ERR_FORBIDDEN")
    # PlatformAdmin: any


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.enrollments.values())
    for key in ("course_id", "learner_id", "coupon_id", "bundle_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    # scope by role
    if principal.role == "Learner":
        items = [e for e in items if e["learner_id"] == principal.user_id]
    elif principal.role == "Instructor":
        owned = {c["id"] for c in db.courses.values()
                 if c["instructor_id"] == principal.user_id}
        items = [e for e in items if e["course_id"] in owned]
    # refresh derived/expiry for each
    for e in items:
        _refresh_enrollment(e)
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)


# --------------------------------------------------------------------------
# Refund (ACTIVE -> REFUNDED)
# --------------------------------------------------------------------------

@bp.route("/enrollments/<enrollment_id>/refund", methods=["POST"])
def refund_enrollment(enrollment_id):
    principal = authenticate()
    require_roles(principal, "Learner")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    # ownership
    if enrollment["learner_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN")

    # NOTE: a refund must NOT lazily expire first — the refund-window check
    # below produces the correct ERR_REFUND_WINDOW_CLOSED for a past-deadline
    # enrollment. We evaluate state on the stored status.
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE")

    # refund window: allowed only while now < refund_deadline (strict)
    deadline = parse_dt(enrollment["refund_deadline"])
    if clock.now() >= deadline:
        raise err("ERR_REFUND_WINDOW_CLOSED")

    course = db.courses.get(enrollment["course_id"])

    # 1. credit learner wallet by gross_price_cents
    learner = db.learners[enrollment["learner_id"]]
    learner["wallet_credit_cents"] = learner.get("wallet_credit_cents", 0) + enrollment["gross_price_cents"]
    touch(learner)

    # 2. SALE entry PENDING -> CLAWED_BACK, then write REFUND entry of
    #    -instructor_share; recompute instructor balances.
    instructor_id = course["instructor_id"]
    for e in db.ledger_entries.values():
        if e["enrollment_id"] == enrollment_id and e["entry_type"] == "SALE":
            e["status"] = "CLAWED_BACK"
            break
    write_entry(instructor_id, "REFUND", -enrollment["instructor_share_cents"],
                "AVAILABLE", enrollment_id=enrollment_id)
    recompute_balances(instructor_id)

    # 3. coupon redeemed_count-- and maybe EXHAUSTED -> ACTIVE
    if enrollment.get("coupon_id"):
        coupon = db.coupons.get(enrollment["coupon_id"])
        if coupon is not None:
            coupon["redeemed_count"] = max(coupon["redeemed_count"] - 1, 0)
            if coupon["status"] == "EXHAUSTED" and coupon["redeemed_count"] < coupon["max_redemptions"]:
                coupon["status"] = "ACTIVE"
            touch(coupon)

    # 4. enrollment status
    enrollment["status"] = "REFUNDED"
    touch(enrollment)

    # 5. course enrollment_count-- (recompute, then mutation)
    if course is not None:
        recompute_enrollment_count(course)
        touch(course)

    return response.success(view(enrollment), status=200)


# --------------------------------------------------------------------------
# Reverse-reach reads: lesson-completions and certificate for an enrollment
# --------------------------------------------------------------------------

@bp.route("/enrollments/<enrollment_id>/lesson-completions", methods=["GET"])
def list_enrollment_completions(enrollment_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    _check_enrollment_read_access(principal, enrollment)
    items = [c for c in db.lesson_completions.values()
             if c["enrollment_id"] == enrollment_id]
    page, meta = paginate(items, request.args)
    return response.success(view_list(page), status=200, pagination=meta)


@bp.route("/enrollments/<enrollment_id>/certificate", methods=["GET"])
def get_enrollment_certificate(enrollment_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    _check_enrollment_read_access(principal, enrollment)
    items = [c for c in db.certificates.values()
             if c["enrollment_id"] == enrollment_id]
    page, meta = paginate(items, request.args)
    return response.success(view_list(page), status=200, pagination=meta)
