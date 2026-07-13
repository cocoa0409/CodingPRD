"""Online Course Creator Platform API — Flask entry point.

In-memory only. Fresh empty store on every boot. No seeded data.
"""
import os
from flask import Flask, request, jsonify

import store
from store import (
    now, set_clock, fmt_dt, parse_dt, add_days, new_request_id, new_serial,
    base, touch, bump_creator_version,
    creators, students, courses, lessons, price_plans, coupons, affiliates,
    enrollments, invoices, payouts, quiz_attempts,
)
from errors import ApiError
import serialize as S

app = Flask(__name__)

ROLES = ("PlatformAdmin", "Creator", "Student")
TERMINAL_BILLING = {"CANCELLED", "REFUNDED"}

# ==========================================================================
# Envelope helpers
# ==========================================================================
def make_meta(extra=None):
    m = {"api_request_id": new_request_id(),
         "api_request_timestamp": fmt_dt(now())}
    if extra:
        m.update(extra)
    return m


def obj_response(data, status=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), status


def array_response(data, meta_extra, status=200):
    return jsonify({"meta": make_meta(meta_extra), "response_type": "array", "data": data}), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": err.error_id, "message": err.message}}
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"}}
    return jsonify(body), 405


# ==========================================================================
# Auth / role / field helpers
# ==========================================================================
def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER", "Missing or invalid auth headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation")


def body_json():
    raw = request.get_data()
    if raw and raw.strip():
        data = request.get_json(silent=True, force=True)
        if not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
        return data
    return {}


def f_str(body, name, required=True, default=None, allow_empty=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing field: " + name)
        return default
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", name + " must be a string")
    if not allow_empty and v == "":
        raise ApiError("ERR_INVALID_REQUEST", name + " must not be empty")
    return v


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing field: " + name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", name + " must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", name + " below minimum")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_INVALID_REQUEST", name + " above maximum")
    return v


def f_bool(body, name, required=False, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing field: " + name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", name + " must be a boolean")
    return v


def f_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing field: " + name)
        return default
    v = body[name]
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", name + " has an invalid value")
    return v


def f_dt(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Missing field: " + name)
        return default
    try:
        return parse_dt(body[name])
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", name + " is not a valid datetime")


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items, serializer):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    data = [serializer(e) for e in page]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return array_response(data, meta_extra)


# ==========================================================================
# Lookup helpers
# ==========================================================================
def must(collection, key, err):
    v = collection.get(key)
    if v is None:
        raise ApiError(err)
    return v


def course_creator_id(course):
    return course["creator_id"]


def invoice_course(inv):
    enr = enrollments.get(inv["enrollment_id"])
    if enr is None:
        return None
    return courses.get(enr["course_id"])


# ==========================================================================
# Creators
# ==========================================================================
@app.route("/creators", methods=["POST"])
def create_creator():
    uid, role = auth()
    body = body_json()
    email = f_str(body, "email")
    display_name = f_str(body, "display_name")
    require_role(role, ["PlatformAdmin"])
    c = base()
    c.update({"email": email, "display_name": display_name, "status": "ACTIVE"})
    creators[c["id"]] = c
    return obj_response(S.ser_creator(c), 201)


@app.route("/creators/<cid>", methods=["GET"])
def get_creator(cid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    c = must(creators, cid, "ERR_CREATOR_NOT_FOUND")
    return obj_response(S.ser_creator(c))


@app.route("/creators/<cid>/set-status", methods=["POST"])
def set_creator_status(cid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["PlatformAdmin"])
    c = must(creators, cid, "ERR_CREATOR_NOT_FOUND")
    if status_val not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid creator status")
    c["status"] = status_val
    c["_updated_dt"] = now()  # creator.version only advances on payout events
    return obj_response(S.ser_creator(c))


# ==========================================================================
# Students
# ==========================================================================
@app.route("/students", methods=["POST"])
def create_student():
    uid, role = auth()
    body = body_json()
    email = f_str(body, "email")
    full_name = f_str(body, "full_name")
    require_role(role, ["PlatformAdmin"])
    s = base()
    s.update({"email": email, "full_name": full_name})
    students[s["id"]] = s
    return obj_response(S.ser_student(s), 201)


# ==========================================================================
# Courses
# ==========================================================================
@app.route("/courses", methods=["POST"])
def create_course():
    uid, role = auth()
    body = body_json()
    creator_id = f_str(body, "creator_id")
    title = f_str(body, "title")
    refund_window_days = f_int(body, "refund_window_days", required=False, default=14, minimum=0)
    community_enabled = f_bool(body, "community_enabled", default=False)
    welcome_email_subject = f_str(body, "welcome_email_subject", required=False,
                                  default="Welcome!", allow_empty=True)
    require_role(role, ["Creator"])
    creator = must(creators, creator_id, "ERR_CREATOR_NOT_FOUND")
    if role == "Creator" and creator["id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Cannot create a course for another creator")
    c = base()
    c.update({
        "creator_id": creator_id,
        "title": title,
        "status": "DRAFT",
        "refund_window_days": refund_window_days,
        "community_enabled": bool(community_enabled),
        "welcome_email_subject": welcome_email_subject,
    })
    courses[c["id"]] = c
    return obj_response(S.ser_course(c), 201)


@app.route("/courses/<cid>", methods=["GET"])
def get_course(cid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    c = must(courses, cid, "ERR_COURSE_NOT_FOUND")
    return obj_response(S.ser_course(c))


@app.route("/courses", methods=["GET"])
def list_courses():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    creator_id = request.args.get("creator_id")
    status = request.args.get("status")
    items = [c for c in courses.values()
             if (creator_id is None or c["creator_id"] == creator_id)
             and (status is None or c["status"] == status)]
    return list_response(items, S.ser_course)


@app.route("/courses/<cid>/set-status", methods=["POST"])
def set_course_status(cid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["Creator"])
    c = must(courses, cid, "ERR_COURSE_NOT_FOUND")
    if role == "Creator" and c["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the course owner")
    if status_val not in ("DRAFT", "PUBLISHED", "UNPUBLISHED", "ARCHIVED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid course status")

    current = c["status"]
    allowed = {
        "DRAFT": {"PUBLISHED", "ARCHIVED"},
        "PUBLISHED": {"UNPUBLISHED", "ARCHIVED"},
        "UNPUBLISHED": {"PUBLISHED", "ARCHIVED"},
        "ARCHIVED": set(),
    }
    if status_val not in allowed.get(current, set()):
        raise ApiError("ERR_COURSE_INVALID_STATUS_TRANSITION",
                       "Transition not allowed from " + current)
    if status_val == "PUBLISHED":
        if S.course_published_lesson_count(cid) < 1:
            raise ApiError("ERR_COURSE_INVALID_STATUS_TRANSITION",
                           "Course needs at least one published lesson")
        active_plans = [p for p in price_plans.values()
                        if p["course_id"] == cid and p["status"] == "ACTIVE"]
        if len(active_plans) < 1:
            raise ApiError("ERR_COURSE_INVALID_STATUS_TRANSITION",
                           "Course needs at least one active price plan")
    c["status"] = status_val
    touch(c)
    return obj_response(S.ser_course(c))


# ==========================================================================
# Lessons
# ==========================================================================
@app.route("/lessons", methods=["POST"])
def create_lesson():
    uid, role = auth()
    body = body_json()
    course_id = f_str(body, "course_id")
    title = f_str(body, "title")
    position = f_int(body, "position", minimum=1)
    is_published = f_bool(body, "is_published", default=True)
    drip_offset_days = f_int(body, "drip_offset_days", required=False, default=0, minimum=0)
    is_quiz_required = f_bool(body, "is_quiz_required", default=False)
    quiz_passing_score = f_int(body, "quiz_passing_score", required=False, default=70,
                               minimum=0, maximum=100)
    require_role(role, ["Creator"])
    course = must(courses, course_id, "ERR_COURSE_NOT_FOUND")
    if role == "Creator" and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the course owner")
    l = base()
    l.update({
        "course_id": course_id,
        "title": title,
        "position": position,
        "is_published": bool(is_published),
        "drip_offset_days": drip_offset_days,
        "is_quiz_required": bool(is_quiz_required),
        "quiz_passing_score": quiz_passing_score,
    })
    lessons[l["id"]] = l
    return obj_response(S.ser_lesson(l), 201)


@app.route("/lessons/<lid>", methods=["GET"])
def get_lesson(lid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    l = must(lessons, lid, "ERR_LESSON_NOT_FOUND")
    return obj_response(S.ser_lesson(l))


@app.route("/lessons", methods=["GET"])
def list_lessons():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    course_id = request.args.get("course_id")
    items = [l for l in lessons.values()
             if course_id is None or l["course_id"] == course_id]
    return list_response(items, S.ser_lesson)


# ==========================================================================
# Price Plans
# ==========================================================================
@app.route("/price-plans", methods=["POST"])
def create_price_plan():
    uid, role = auth()
    body = body_json()
    course_id = f_str(body, "course_id")
    plan_type = f_enum(body, "plan_type", ("ONE_TIME", "SUBSCRIPTION", "PAYMENT_PLAN"))
    amount_cents = f_int(body, "amount_cents", minimum=1)
    billing_interval_days = f_int(body, "billing_interval_days", required=False, default=None, minimum=1)
    num_installments = f_int(body, "num_installments", required=False, default=None)
    grants_community = f_bool(body, "grants_community", default=False)
    if plan_type == "PAYMENT_PLAN":
        if num_installments is None or num_installments < 2:
            raise ApiError("ERR_INVALID_REQUEST", "num_installments must be >= 2 for PAYMENT_PLAN")
    require_role(role, ["Creator"])
    course = must(courses, course_id, "ERR_COURSE_NOT_FOUND")
    if role == "Creator" and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the course owner")
    p = base()
    p.update({
        "course_id": course_id,
        "plan_type": plan_type,
        "amount_cents": amount_cents,
        "billing_interval_days": billing_interval_days,
        "num_installments": num_installments,
        "grants_community": bool(grants_community),
        "status": "ACTIVE",
    })
    price_plans[p["id"]] = p
    return obj_response(S.ser_price_plan(p), 201)


@app.route("/price-plans/<pid>", methods=["GET"])
def get_price_plan(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    p = must(price_plans, pid, "ERR_PRICE_PLAN_NOT_FOUND")
    return obj_response(S.ser_price_plan(p))


@app.route("/price-plans", methods=["GET"])
def list_price_plans():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    course_id = request.args.get("course_id")
    items = [p for p in price_plans.values()
             if course_id is None or p["course_id"] == course_id]
    return list_response(items, S.ser_price_plan)


@app.route("/price-plans/<pid>/set-status", methods=["POST"])
def set_price_plan_status(pid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["Creator"])
    p = must(price_plans, pid, "ERR_PRICE_PLAN_NOT_FOUND")
    course = courses.get(p["course_id"])
    if role == "Creator" and course and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the plan owner")
    if status_val not in ("ACTIVE", "ARCHIVED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid price plan status")
    p["status"] = status_val
    touch(p)
    return obj_response(S.ser_price_plan(p))


# ==========================================================================
# Coupons
# ==========================================================================
@app.route("/coupons", methods=["POST"])
def create_coupon():
    uid, role = auth()
    body = body_json()
    course_id = f_str(body, "course_id")
    code = f_str(body, "code")
    discount_type = f_enum(body, "discount_type", ("PERCENT", "FIXED"))
    discount_value = f_int(body, "discount_value", minimum=1)
    max_redemptions = f_int(body, "max_redemptions", minimum=1)
    starts_at = f_dt(body, "starts_at")
    expires_at = f_dt(body, "expires_at")
    min_purchase_cents = f_int(body, "min_purchase_cents", required=False, default=0, minimum=0)
    if discount_type == "PERCENT" and (discount_value < 1 or discount_value > 100):
        raise ApiError("ERR_INVALID_REQUEST", "PERCENT discount_value must be 1..100")
    require_role(role, ["Creator"])
    course = must(courses, course_id, "ERR_COURSE_NOT_FOUND")
    if role == "Creator" and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the course owner")
    # closed-interval overlap with an existing ACTIVE same-code coupon on this course
    for other in coupons.values():
        if (other["course_id"] == course_id and other["code"] == code
                and other["status"] == "ACTIVE"):
            if starts_at <= other["expires_at"] and other["starts_at"] <= expires_at:
                raise ApiError("ERR_COUPON_WINDOW_OVERLAP",
                               "Overlaps an existing active coupon of the same code")
    cp = base()
    cp.update({
        "course_id": course_id,
        "code": code,
        "discount_type": discount_type,
        "discount_value": discount_value,
        "min_purchase_cents": min_purchase_cents,
        "max_redemptions": max_redemptions,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "status": "ACTIVE",
    })
    coupons[cp["id"]] = cp
    return obj_response(S.ser_coupon(cp), 201)


@app.route("/coupons/<cid>", methods=["GET"])
def get_coupon(cid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    cp = must(coupons, cid, "ERR_COUPON_NOT_FOUND")
    return obj_response(S.ser_coupon(cp))


@app.route("/coupons", methods=["GET"])
def list_coupons():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    course_id = request.args.get("course_id")
    items = [c for c in coupons.values()
             if course_id is None or c["course_id"] == course_id]
    return list_response(items, S.ser_coupon)


@app.route("/coupons/<cid>/set-status", methods=["POST"])
def set_coupon_status(cid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["Creator"])
    cp = must(coupons, cid, "ERR_COUPON_NOT_FOUND")
    course = courses.get(cp["course_id"])
    if role == "Creator" and course and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the coupon owner")
    if status_val not in ("ACTIVE", "DISABLED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid coupon status")
    cp["status"] = status_val
    touch(cp)
    return obj_response(S.ser_coupon(cp))


# ==========================================================================
# Affiliates
# ==========================================================================
@app.route("/affiliates", methods=["POST"])
def create_affiliate():
    uid, role = auth()
    body = body_json()
    creator_id = f_str(body, "creator_id")
    code = f_str(body, "code")
    commission_pct = f_int(body, "commission_pct", minimum=0, maximum=100)
    require_role(role, ["Creator"])
    creator = must(creators, creator_id, "ERR_CREATOR_NOT_FOUND")
    if role == "Creator" and creator["id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Cannot create an affiliate for another creator")
    a = base()
    a.update({
        "creator_id": creator_id,
        "code": code,
        "commission_pct": commission_pct,
        "status": "ACTIVE",
    })
    affiliates[a["id"]] = a
    return obj_response(S.ser_affiliate(a), 201)


@app.route("/affiliates/<aid>", methods=["GET"])
def get_affiliate(aid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    a = must(affiliates, aid, "ERR_AFFILIATE_NOT_FOUND")
    return obj_response(S.ser_affiliate(a))


@app.route("/affiliates", methods=["GET"])
def list_affiliates():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    creator_id = request.args.get("creator_id")
    items = [a for a in affiliates.values()
             if creator_id is None or a["creator_id"] == creator_id]
    return list_response(items, S.ser_affiliate)


@app.route("/affiliates/<aid>/set-status", methods=["POST"])
def set_affiliate_status(aid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["Creator"])
    a = must(affiliates, aid, "ERR_AFFILIATE_NOT_FOUND")
    if role == "Creator" and a["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the affiliate owner")
    if status_val not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid affiliate status")
    a["status"] = status_val
    touch(a)
    return obj_response(S.ser_affiliate(a))


# ==========================================================================
# Enrollment checkout helpers
# ==========================================================================
def installment_amount(total, n, index):
    per = -(-total // n)  # ceil
    if index < n:
        return per
    return total - per * (n - 1)


def resolve_by_code(collection, code):
    for e in collection.values():
        if e["code"] == code:
            return e
    return None


# ==========================================================================
# Enrollments
# ==========================================================================
@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    uid, role = auth()
    body = body_json()
    student_id = f_str(body, "student_id")
    course_id = f_str(body, "course_id")
    price_plan_id = f_str(body, "price_plan_id")
    coupon_code = f_str(body, "coupon_code", required=False, default=None)
    affiliate_code = f_str(body, "affiliate_code", required=False, default=None)
    require_role(role, ["Student"])

    # (4) existence
    student = must(students, student_id, "ERR_STUDENT_NOT_FOUND")
    course = must(courses, course_id, "ERR_COURSE_NOT_FOUND")
    plan = must(price_plans, price_plan_id, "ERR_PRICE_PLAN_NOT_FOUND")
    coupon = None
    if coupon_code is not None:
        coupon = resolve_by_code(coupons, coupon_code)
        if coupon is None:
            raise ApiError("ERR_COUPON_NOT_FOUND", "Unknown coupon code")
    affiliate = None
    if affiliate_code is not None:
        affiliate = resolve_by_code(affiliates, affiliate_code)
        if affiliate is None:
            raise ApiError("ERR_AFFILIATE_NOT_FOUND", "Unknown affiliate code")

    # (5) ownership: enroll self
    if role == "Student" and student["id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Students may only enroll themselves")

    # (7) cross-reference
    if plan["course_id"] != course_id:
        raise ApiError("ERR_PRICE_PLAN_COURSE_MISMATCH", "Plan does not belong to course")
    if coupon is not None and coupon["course_id"] != course_id:
        raise ApiError("ERR_COUPON_COURSE_MISMATCH", "Coupon does not belong to course")
    if affiliate is not None and affiliate["creator_id"] != course["creator_id"]:
        raise ApiError("ERR_AFFILIATE_CREATOR_MISMATCH", "Affiliate does not belong to creator")

    # (8) cross-entity state gates
    if course["status"] != "PUBLISHED":
        raise ApiError("ERR_COURSE_NOT_PUBLISHED", "Course is not published")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PRICE_PLAN_INACTIVE", "Price plan is archived")
    if coupon is not None and coupon["status"] == "DISABLED":
        raise ApiError("ERR_COUPON_INACTIVE", "Coupon is disabled")
    if affiliate is not None and affiliate["status"] == "SUSPENDED":
        raise ApiError("ERR_AFFILIATE_INACTIVE", "Affiliate is suspended")

    # (9) time-window gate: coupon validity
    if coupon is not None:
        if not (coupon["starts_at"] <= now() <= coupon["expires_at"]):
            raise ApiError("ERR_COUPON_WINDOW_EXPIRED", "Coupon is outside its validity window")

    # (10) uniqueness: one non-terminal enrollment per student+course
    for e in enrollments.values():
        if (e["student_id"] == student_id and e["course_id"] == course_id
                and e["billing_status"] not in TERMINAL_BILLING):
            raise ApiError("ERR_DUPLICATE_ENROLLMENT", "Student already enrolled in this course")

    # list price
    list_price = plan["amount_cents"]

    # (11) fiscal gates for coupon
    if coupon is not None:
        if list_price < coupon["min_purchase_cents"]:
            raise ApiError("ERR_COUPON_MIN_PURCHASE_NOT_MET", "List price below coupon minimum")
        if S.coupon_redeemed_count(coupon["id"]) >= coupon["max_redemptions"]:
            raise ApiError("ERR_COUPON_REDEMPTION_LIMIT", "Coupon redemption limit reached")

    # discount
    discount = 0
    if coupon is not None:
        if coupon["discount_type"] == "PERCENT":
            discount = (list_price * coupon["discount_value"]) // 100
        else:  # FIXED
            discount = min(coupon["discount_value"], list_price)
    discounted_total = list_price - discount

    plan_type = plan["plan_type"]
    if plan_type == "PAYMENT_PLAN":
        n = plan["num_installments"]
        initial_charge = installment_amount(discounted_total, n, 1)
        scheduled_total = discounted_total
    else:
        initial_charge = discounted_total
        scheduled_total = discounted_total

    enr = base()
    enr.update({
        "student_id": student_id,
        "course_id": course_id,
        "price_plan_id": price_plan_id,
        "coupon_id": coupon["id"] if coupon is not None else None,
        "affiliate_id": affiliate["id"] if affiliate is not None else None,
        "access_status": "LOCKED",
        "billing_status": "PENDING",
        "activated_at": None,
        "list_price_cents": list_price,
        "discount_cents": discount,
        "initial_charge_cents": initial_charge,
        "scheduled_total_cents": scheduled_total,
        "certificate_serial": None,
        "certificate_issued_at": None,
        "_completed": set(),
    })
    enrollments[enr["id"]] = enr

    # lay down invoices
    def new_invoice(seq, kind, amount):
        inv = base()
        inv.update({
            "enrollment_id": enr["id"],
            "sequence_index": seq,
            "kind": kind,
            "amount_cents": amount,
            "cycle_start": None,
            "cycle_end": None,
            "status": "PENDING",
            "paid_at": None,
            "refunded_at": None,
            "platform_fee_cents": None,
            "affiliate_commission_cents": None,
            "creator_net_cents": None,
        })
        invoices[inv["id"]] = inv
        return inv

    if plan_type == "PAYMENT_PLAN":
        n = plan["num_installments"]
        for i in range(1, n + 1):
            amt = installment_amount(discounted_total, n, i)
            new_invoice(i, "INITIAL" if i == 1 else "INSTALLMENT", amt)
    else:
        new_invoice(1, "INITIAL", initial_charge)

    return obj_response(S.ser_enrollment(enr), 201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    e = must(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    return obj_response(S.ser_enrollment(e))


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    a = request.args
    student_id = a.get("student_id")
    course_id = a.get("course_id")
    price_plan_id = a.get("price_plan_id")
    coupon_id = a.get("coupon_id")
    affiliate_id = a.get("affiliate_id")
    status = a.get("status")

    def keep(e):
        if student_id is not None and e["student_id"] != student_id:
            return False
        if course_id is not None and e["course_id"] != course_id:
            return False
        if price_plan_id is not None and e["price_plan_id"] != price_plan_id:
            return False
        if coupon_id is not None and e.get("coupon_id") != coupon_id:
            return False
        if affiliate_id is not None and e.get("affiliate_id") != affiliate_id:
            return False
        if status is not None and e["access_status"] != status and e["billing_status"] != status:
            return False
        return True

    items = [e for e in enrollments.values() if keep(e)]
    return list_response(items, S.ser_enrollment)


@app.route("/enrollments/<eid>/complete-lesson", methods=["POST"])
def complete_lesson(eid):
    uid, role = auth()
    body = body_json()
    lesson_id = f_str(body, "lesson_id")
    require_role(role, ["Student"])
    enr = must(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    if role == "Student" and enr["student_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the enrollment owner")
    lesson = must(lessons, lesson_id, "ERR_LESSON_NOT_FOUND")
    if lesson["course_id"] != enr["course_id"]:
        raise ApiError("ERR_LESSON_COURSE_MISMATCH", "Lesson not in the enrollment's course")
    if not lesson["is_published"]:
        raise ApiError("ERR_LESSON_NOT_PUBLISHED", "Lesson is not published")
    if enr["access_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "Enrollment cannot progress")
    # drip lock
    if enr["activated_at"] is not None:
        unlock = add_days(enr["activated_at"], lesson["drip_offset_days"])
        if now() < unlock:
            raise ApiError("ERR_LESSON_LOCKED", "Lesson is still drip-locked")

    enr["_completed"].add(lesson_id)
    if S.enrollment_is_mastery_complete(enr) and enr["access_status"] == "ACTIVE":
        enr["access_status"] = "COMPLETED"
        enr["certificate_serial"] = new_serial()
        enr["certificate_issued_at"] = now()
    touch(enr)
    return obj_response(S.ser_enrollment(enr))


@app.route("/enrollments/<eid>/cancel", methods=["POST"])
def cancel_enrollment(eid):
    uid, role = auth()
    body_json()
    require_role(role, ["Student"])
    enr = must(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    if role == "Student" and enr["student_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the enrollment owner")
    if enr["billing_status"] in TERMINAL_BILLING:
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "Enrollment already terminal")
    enr_invoices = [inv for inv in invoices.values() if inv["enrollment_id"] == eid]
    if any(inv["status"] == "PAID" for inv in enr_invoices):
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "Cannot cancel after payment")
    enr["billing_status"] = "CANCELLED"
    enr["access_status"] = "REVOKED"
    for inv in enr_invoices:
        if inv["status"] == "PENDING":
            inv["status"] = "VOID"
            touch(inv)
    touch(enr)
    return obj_response(S.ser_enrollment(enr))


@app.route("/enrollments/<eid>/quiz-attempts", methods=["POST"])
def create_quiz_attempt(eid):
    uid, role = auth()
    body = body_json()
    lesson_id = f_str(body, "lesson_id")
    score = f_int(body, "score", minimum=0, maximum=100)
    require_role(role, ["Student"])
    enr = must(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    if role == "Student" and enr["student_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the enrollment owner")
    lesson = must(lessons, lesson_id, "ERR_LESSON_NOT_FOUND")
    if lesson["course_id"] != enr["course_id"]:
        raise ApiError("ERR_LESSON_COURSE_MISMATCH", "Lesson not in the enrollment's course")
    if not lesson["is_published"]:
        raise ApiError("ERR_LESSON_NOT_PUBLISHED", "Lesson is not published")
    if not lesson["is_quiz_required"]:
        raise ApiError("ERR_QUIZ_NOT_REQUIRED", "Lesson does not require a quiz")
    if enr["access_status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_INVALID_STATE", "Enrollment cannot progress")
    qa = base(with_version=False, with_updated=False)
    qa.update({
        "enrollment_id": eid,
        "lesson_id": lesson_id,
        "score": score,
        "passed": score >= lesson["quiz_passing_score"],
    })
    quiz_attempts[qa["id"]] = qa
    return obj_response(S.ser_quiz(qa), 201)


@app.route("/enrollments/<eid>/invoices", methods=["POST"])
def create_cycle_invoice(eid):
    uid, role = auth()
    body = body_json()
    cycle_start = f_dt(body, "cycle_start")
    cycle_end = f_dt(body, "cycle_end")
    require_role(role, ["Creator", "PlatformAdmin"])
    enr = must(enrollments, eid, "ERR_ENROLLMENT_NOT_FOUND")
    course = courses.get(enr["course_id"])
    if role == "Creator" and course and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the course owner")
    plan = price_plans.get(enr["price_plan_id"])

    enr_invoices = [inv for inv in invoices.values() if inv["enrollment_id"] == eid]
    # half-open overlap against non-refunded CYCLE invoices
    for inv in enr_invoices:
        if inv["kind"] == "CYCLE" and inv["status"] != "REFUNDED":
            if cycle_start < inv["cycle_end"] and inv["cycle_start"] < cycle_end:
                raise ApiError("ERR_CYCLE_OVERLAP", "Cycle interval overlaps an existing invoice")

    seq = max([inv["sequence_index"] for inv in enr_invoices], default=0) + 1
    inv = base()
    inv.update({
        "enrollment_id": eid,
        "sequence_index": seq,
        "kind": "CYCLE",
        "amount_cents": plan["amount_cents"],
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
        "status": "PENDING",
        "paid_at": None,
        "refunded_at": None,
        "platform_fee_cents": None,
        "affiliate_commission_cents": None,
        "creator_net_cents": None,
    })
    invoices[inv["id"]] = inv
    return obj_response(S.ser_invoice(inv), 201)


# ==========================================================================
# Quiz Attempts (reads)
# ==========================================================================
@app.route("/quiz-attempts/<qid>", methods=["GET"])
def get_quiz_attempt(qid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    qa = must(quiz_attempts, qid, "ERR_QUIZ_ATTEMPT_NOT_FOUND")
    return obj_response(S.ser_quiz(qa))


@app.route("/quiz-attempts", methods=["GET"])
def list_quiz_attempts():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    enrollment_id = request.args.get("enrollment_id")
    lesson_id = request.args.get("lesson_id")
    items = [qa for qa in quiz_attempts.values()
             if (enrollment_id is None or qa["enrollment_id"] == enrollment_id)
             and (lesson_id is None or qa["lesson_id"] == lesson_id)]
    return list_response(items, S.ser_quiz)


# ==========================================================================
# Invoices
# ==========================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    inv = must(invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return obj_response(S.ser_invoice(inv))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator", "Student"])
    enrollment_id = request.args.get("enrollment_id")
    items = [inv for inv in invoices.values()
             if enrollment_id is None or inv["enrollment_id"] == enrollment_id]
    return list_response(items, S.ser_invoice)


@app.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    uid, role = auth()
    body_json()
    require_role(role, ["Student", "PlatformAdmin"])
    inv = must(invoices, iid, "ERR_INVOICE_NOT_FOUND")
    enr = enrollments.get(inv["enrollment_id"])
    course = courses.get(enr["course_id"]) if enr else None
    if role == "Student" and enr and enr["student_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the invoice owner")
    if inv["status"] != "PENDING":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Invoice is not payable")
    if course is not None and course["status"] == "ARCHIVED":
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Course is archived")

    amount = inv["amount_cents"]
    platform_fee = (amount * 10) // 100
    commission = 0
    if enr and enr.get("affiliate_id"):
        aff = affiliates.get(enr["affiliate_id"])
        if aff is not None and aff["status"] == "ACTIVE":
            commission = (amount * aff["commission_pct"]) // 100
    inv["status"] = "PAID"
    inv["paid_at"] = now()
    inv["platform_fee_cents"] = platform_fee
    inv["affiliate_commission_cents"] = commission
    inv["creator_net_cents"] = amount - platform_fee - commission
    touch(inv)

    if inv["kind"] == "INITIAL":
        if enr["access_status"] == "LOCKED":
            enr["access_status"] = "ACTIVE"
        if enr["billing_status"] == "PENDING":
            enr["billing_status"] = "CURRENT"
        enr["activated_at"] = now()
        touch(enr)
    return obj_response(S.ser_invoice(inv))


@app.route("/invoices/<iid>/refund", methods=["POST"])
def refund_invoice(iid):
    uid, role = auth()
    body_json()
    require_role(role, ["Creator", "PlatformAdmin"])
    inv = must(invoices, iid, "ERR_INVOICE_NOT_FOUND")
    enr = enrollments.get(inv["enrollment_id"])
    course = courses.get(enr["course_id"]) if enr else None
    if role == "Creator" and course and course["creator_id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Not the invoice owner")
    if inv["status"] != "PAID":
        raise ApiError("ERR_INVOICE_NOT_REFUNDABLE", "Invoice is not refundable")
    window_end = add_days(inv["paid_at"], course["refund_window_days"])
    if now() > window_end:
        raise ApiError("ERR_REFUND_WINDOW_EXPIRED", "Refund window has closed")

    inv["status"] = "REFUNDED"
    inv["refunded_at"] = now()
    touch(inv)

    if inv["kind"] == "INITIAL":
        enr["access_status"] = "REVOKED"
        enr["billing_status"] = "REFUNDED"
        enr["certificate_serial"] = None
        enr["certificate_issued_at"] = None
        enr["_completed"] = set()
        touch(enr)
    return obj_response(S.ser_invoice(inv))


# ==========================================================================
# Payouts
# ==========================================================================
@app.route("/creators/<cid>/payouts", methods=["POST"])
def create_payout(cid):
    uid, role = auth()
    body = body_json()
    amount_cents = f_int(body, "amount_cents", minimum=1)
    expected_version = f_int(body, "expected_creator_version")
    require_role(role, ["Creator"])
    creator = must(creators, cid, "ERR_CREATOR_NOT_FOUND")
    if role == "Creator" and creator["id"] != uid:
        raise ApiError("ERR_NOT_OWNER", "Cannot request a payout for another creator")
    # (8) creator active
    if creator["status"] != "ACTIVE":
        raise ApiError("ERR_CREATOR_SUSPENDED", "Creator is suspended")
    # (11) fiscal: sufficient balance
    available = S.creator_available_balance(creator)
    if amount_cents > available:
        raise ApiError("ERR_INSUFFICIENT_BALANCE", "Amount exceeds available balance")
    # (12) OCC last
    if expected_version != creator["version"]:
        raise ApiError("ERR_STALE_CREATOR_VERSION", "Creator version is stale")

    p = base()
    p.update({"creator_id": cid, "amount_cents": amount_cents, "status": "REQUESTED"})
    payouts[p["id"]] = p
    bump_creator_version(creator)
    return obj_response(S.ser_payout(p), 201)


@app.route("/payouts/<pid>", methods=["GET"])
def get_payout(pid):
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    p = must(payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    return obj_response(S.ser_payout(p))


@app.route("/payouts", methods=["GET"])
def list_payouts():
    uid, role = auth()
    require_role(role, ["PlatformAdmin", "Creator"])
    creator_id = request.args.get("creator_id")
    items = [p for p in payouts.values()
             if creator_id is None or p["creator_id"] == creator_id]
    return list_response(items, S.ser_payout)


@app.route("/payouts/<pid>/set-status", methods=["POST"])
def set_payout_status(pid):
    uid, role = auth()
    body = body_json()
    status_val = f_str(body, "status")
    require_role(role, ["PlatformAdmin"])
    p = must(payouts, pid, "ERR_PAYOUT_NOT_FOUND")
    if status_val not in ("REQUESTED", "PROCESSING", "PAID", "FAILED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATUS_VALUE", "Invalid payout status")

    current = p["status"]
    legal = {
        "REQUESTED": {"PROCESSING", "CANCELLED"},
        "PROCESSING": {"PAID", "FAILED", "CANCELLED"},
        "PAID": set(),
        "FAILED": set(),
        "CANCELLED": set(),
    }
    if status_val not in legal.get(current, set()):
        raise ApiError("ERR_PAYOUT_INVALID_STATUS_TRANSITION",
                       "Transition not allowed from " + current)
    p["status"] = status_val
    touch(p)
    creator = creators.get(p["creator_id"])
    if creator is not None and status_val in ("PAID", "FAILED", "CANCELLED"):
        bump_creator_version(creator)
    return obj_response(S.ser_payout(p))


# ==========================================================================
# Logical clock
# ==========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    uid, role = auth()
    body = body_json()
    to_iso = f_dt(body, "to_iso8601")
    require_role(role, ["PlatformAdmin"])
    set_clock(to_iso)
    return obj_response({})


# ==========================================================================
# Main
# ==========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
