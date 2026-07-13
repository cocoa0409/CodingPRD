"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints — the server database is empty at the start of every test. Setup calls
use the lenient get_success_data() validator so setup failures surface clearly.

Identity threading: Creator/Student are entity_backed roles; ownership-gated calls
use make_creator_headers(creator["id"]) / make_student_headers(student["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS, make_creator_headers, make_student_headers,
)
from . import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# Atomic helpers — one API call each, returning the created/updated resource.
# --------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api.set_clock(f.set_clock_payload(to_iso8601), ADMIN))


def create_creator(**overrides):
    return get_success_data(api.create_creator(f.create_creator_payload(**overrides), ADMIN))


def suspend_creator(creator_id):
    return get_success_data(
        api.set_creator_status(creator_id, {"status": "SUSPENDED"}, ADMIN))


def get_creator(creator_id):
    return get_success_data(api.get_creator(creator_id, make_creator_headers(creator_id)))


def create_student(**overrides):
    return get_success_data(api.create_student(f.create_student_payload(**overrides), ADMIN))


def create_course(creator_id, **overrides):
    return get_success_data(
        api.create_course(f.create_course_payload(creator_id, **overrides),
                          make_creator_headers(creator_id)))


def create_lesson(course_id, creator_id, **overrides):
    return get_success_data(
        api.create_lesson(f.create_lesson_payload(course_id, **overrides),
                         make_creator_headers(creator_id)))


def create_price_plan(course_id, creator_id, **overrides):
    return get_success_data(
        api.create_price_plan(f.create_price_plan_payload(course_id, **overrides),
                             make_creator_headers(creator_id)))


def archive_price_plan(plan_id, creator_id):
    return get_success_data(
        api.set_price_plan_status(plan_id, {"status": "ARCHIVED"},
                                 make_creator_headers(creator_id)))


def create_coupon(course_id, creator_id, **overrides):
    return get_success_data(
        api.create_coupon(f.create_coupon_payload(course_id, **overrides),
                         make_creator_headers(creator_id)))


def create_affiliate(creator_id, **overrides):
    return get_success_data(
        api.create_affiliate(f.create_affiliate_payload(creator_id, **overrides),
                            make_creator_headers(creator_id)))


def set_course_status(course_id, creator_id, status):
    return get_success_data(
        api.set_course_status(course_id, {"status": status},
                             make_creator_headers(creator_id)))


def publish_course(course_id, creator_id):
    return set_course_status(course_id, creator_id, "PUBLISHED")


def create_enrollment(student_id, course_id, price_plan_id, **overrides):
    payload = f.create_enrollment_payload(student_id, course_id, price_plan_id, **overrides)
    return get_success_data(api.create_enrollment(payload, make_student_headers(student_id)))


def list_invoices(enrollment_id, student_id):
    resp = api.list_invoices(make_student_headers(student_id),
                             params={"enrollment_id": enrollment_id})
    return get_success_data(resp)


def pay_invoice_as_student(invoice_id, student_id):
    return get_success_data(api.pay_invoice(invoice_id, {}, make_student_headers(student_id)))


def refund_invoice_as_creator(invoice_id, creator_id):
    return get_success_data(api.refund_invoice(invoice_id, {}, make_creator_headers(creator_id)))


def complete_lesson(enrollment_id, lesson_id, student_id):
    return get_success_data(
        api.complete_lesson(enrollment_id, {"lesson_id": lesson_id},
                           make_student_headers(student_id)))


def submit_quiz(enrollment_id, lesson_id, score, student_id):
    return get_success_data(
        api.create_quiz_attempt(enrollment_id, {"lesson_id": lesson_id, "score": score},
                               make_student_headers(student_id)))


def create_cycle_invoice(enrollment_id, creator_id, cycle_start, cycle_end):
    return get_success_data(
        api.create_cycle_invoice(enrollment_id,
                                {"cycle_start": cycle_start, "cycle_end": cycle_end},
                                make_creator_headers(creator_id)))


def request_payout(creator_id, amount_cents, expected_version):
    return get_success_data(
        api.create_payout(creator_id,
                         f.create_payout_payload(amount_cents, expected_version),
                         make_creator_headers(creator_id)))


def advance_payout(payout_id, status):
    return get_success_data(
        api.set_payout_status(payout_id, {"status": status}, ADMIN))


# --------------------------------------------------------------------------
# Composite scenarios.
# --------------------------------------------------------------------------

def setup_published_course(
    *,
    plan_type="ONE_TIME",
    amount_cents=20000,
    num_installments=None,
    billing_interval_days=None,
    refund_window_days=14,
    community_enabled=False,
    grants_community=False,
    lesson_overrides=None,
    coupon=None,
    affiliate_pct=None,
    affiliate_code="AFF",
):
    """Creator + student + a PUBLISHED course with one lesson and one ACTIVE plan.

    Optionally creates a coupon (pass a dict of coupon payload overrides, must
    include a `code`) and/or an affiliate (pass affiliate_pct). Returns a context
    dict of all created resources.
    """
    creator = create_creator()
    student = create_student()
    course = create_course(
        creator["id"],
        refund_window_days=refund_window_days,
        community_enabled=community_enabled,
    )
    plan_kwargs = {"plan_type": plan_type, "amount_cents": amount_cents,
                   "grants_community": grants_community}
    if num_installments is not None:
        plan_kwargs["num_installments"] = num_installments
    if billing_interval_days is not None:
        plan_kwargs["billing_interval_days"] = billing_interval_days
    plan = create_price_plan(course["id"], creator["id"], **plan_kwargs)
    lesson = create_lesson(course["id"], creator["id"], **(lesson_overrides or {}))

    coupon_obj = None
    if coupon is not None:
        coupon_obj = create_coupon(course["id"], creator["id"], **coupon)

    affiliate = None
    if affiliate_pct is not None:
        affiliate = create_affiliate(creator["id"], code=affiliate_code,
                                     commission_pct=affiliate_pct)

    publish_course(course["id"], creator["id"])

    return {
        "creator": creator,
        "student": student,
        "course": course,
        "plan": plan,
        "lesson": lesson,
        "coupon": coupon_obj,
        "affiliate": affiliate,
    }


def setup_enrollment(*, coupon_code=None, affiliate_code=None, **course_kwargs):
    """Published course + a fresh (unpaid) enrollment. Returns context extended
    with `enrollment` and `invoices` (ordered ascending by created_at)."""
    # When the enrollment attributes an affiliate code AND this setup is asked to
    # create that affiliate (affiliate_pct present), the affiliate must be created
    # under the SAME code the enrollment attributes, so forward it to the course
    # setup (which builds the affiliate) rather than letting it default to "AFF".
    if affiliate_code is not None and "affiliate_pct" in course_kwargs:
        course_kwargs.setdefault("affiliate_code", affiliate_code)
    ctx = setup_published_course(**course_kwargs)
    enrollment = create_enrollment(
        ctx["student"]["id"], ctx["course"]["id"], ctx["plan"]["id"],
        **({"coupon_code": coupon_code} if coupon_code else {}),
        **({"affiliate_code": affiliate_code} if affiliate_code else {}),
    )
    invoices = list_invoices(enrollment["id"], ctx["student"]["id"])
    ctx["enrollment"] = enrollment
    ctx["invoices"] = invoices
    return ctx


def setup_paid_enrollment(*, coupon_code=None, affiliate_code=None, **course_kwargs):
    """Published course + enrollment with its INITIAL invoice PAID (enrollment
    ACTIVE / CURRENT). Returns context with `enrollment`, `invoices`, and the
    paid `invoice` (the INITIAL, sequence 1)."""
    ctx = setup_enrollment(coupon_code=coupon_code, affiliate_code=affiliate_code,
                           **course_kwargs)
    initial = ctx["invoices"][0]
    ctx["invoice"] = pay_invoice_as_student(initial["id"], ctx["student"]["id"])
    return ctx


def setup_settled_balance(*, amount_cents=20000, refund_window_days=14,
                          settle_to="2026-03-16T00:00:00Z"):
    """Creator whose paid ONE_TIME invoice has passed its refund window, so the
    net is settled and available for payout. Returns context plus the current
    creator `version` (captured after settling) under key `version`.

    ONE_TIME 20000 -> platform fee 2000 -> creator_net 18000 -> settled_net 18000.
    """
    ctx = setup_paid_enrollment(amount_cents=amount_cents,
                                refund_window_days=refund_window_days)
    set_clock(settle_to)
    creator = get_creator(ctx["creator"]["id"])
    ctx["creator"] = creator
    ctx["version"] = creator["version"]
    return ctx
