"""Course publishing lifecycle: the cyclic status machine and its enrollment gate."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers, make_student_headers,
    fixtures as fx,
)


def _draft_course_with_lesson_and_plan():
    creator = fx.create_creator()
    student = fx.create_student()
    course = fx.create_course(creator["id"], title="A")
    fx.create_lesson(course["id"], creator["id"], title="L1", position=1)
    plan = fx.create_price_plan(course["id"], creator["id"],
                                plan_type="ONE_TIME", amount_cents=20000)
    return creator, student, course, plan


def test_course_republish_returns_to_published(api):
    """PRD §3.2: "A published course may be moved to `UNPUBLISHED`, which blocks new
    enrollments while leaving existing enrollments untouched, and an unpublished course
    may be republished back to `PUBLISHED` under the same two preconditions as the first
    publish."

    Design: Difficulty/non_linear_state_machine/course_cyclic_republish_loop
    """
    creator, _, course, _ = _draft_course_with_lesson_and_plan()
    fx.publish_course(course["id"], creator["id"])
    fx.set_course_status(course["id"], creator["id"], "UNPUBLISHED")
    data = fx.set_course_status(course["id"], creator["id"], "PUBLISHED")
    assert data["status"] == "PUBLISHED"


def test_course_publish_unpublish_republish_cycle_statuses(api):
    """PRD §3.2: "A published course may be moved to `UNPUBLISHED`, which blocks new
    enrollments while leaving existing enrollments untouched, and an unpublished course
    may be republished back to `PUBLISHED` under the same two preconditions as the first
    publish."

    Design: Difficulty/non_linear_state_machine/course_cyclic_republish_loop
    """
    creator, _, course, _ = _draft_course_with_lesson_and_plan()
    assert fx.set_course_status(course["id"], creator["id"], "PUBLISHED")["status"] == "PUBLISHED"
    assert fx.set_course_status(course["id"], creator["id"], "UNPUBLISHED")["status"] == "UNPUBLISHED"
    assert fx.set_course_status(course["id"], creator["id"], "PUBLISHED")["status"] == "PUBLISHED"


def test_enroll_on_draft_course_rejected(api):
    """PRD §3.4: "The course must be in `PUBLISHED` status, else `ERR_COURSE_NOT_PUBLISHED`;
    the price plan must be `ACTIVE`, else `ERR_PRICE_PLAN_INACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_published_course
    """
    creator, student, course, plan = _draft_course_with_lesson_and_plan()
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course["id"], "price_plan_id": plan["id"]},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_PUBLISHED.value)


def test_enroll_on_unpublished_course_rejected(api):
    """PRD §3.4: "The course must be in `PUBLISHED` status, else `ERR_COURSE_NOT_PUBLISHED`;
    the price plan must be `ACTIVE`, else `ERR_PRICE_PLAN_INACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_published_course
    """
    creator, student, course, plan = _draft_course_with_lesson_and_plan()
    fx.publish_course(course["id"], creator["id"])
    fx.set_course_status(course["id"], creator["id"], "UNPUBLISHED")
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course["id"], "price_plan_id": plan["id"]},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_PUBLISHED.value)


def test_publish_course_without_published_lesson_rejected(api):
    """PRD §3.2: "From `DRAFT` a creator publishes to `PUBLISHED`, but only when the course
    has at least one published lesson (`published_lesson_count` is one or more) and at
    least one price plan in `ACTIVE` status; if either condition fails the transition is
    rejected with `ERR_COURSE_INVALID_STATUS_TRANSITION`."

    Design: Corner/state_machines/publish_course_without_lesson_returns_409
    """
    creator = fx.create_creator()
    course = fx.create_course(creator["id"], title="A")
    fx.create_price_plan(course["id"], creator["id"], plan_type="ONE_TIME", amount_cents=20000)
    resp = api.set_course_status(course["id"], {"status": "PUBLISHED"},
                                 make_creator_headers(creator["id"]))
    validate_error(resp, ApiErrorId.ERR_COURSE_INVALID_STATUS_TRANSITION.value)
