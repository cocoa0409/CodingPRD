"""Shared route helpers: existence checks (screening steps 6-14) and paging."""

import db
from db import store
from errors import ApiError
from response import array_response
from validation import paginate, pagination_args


def get_partnership(partnership_id):
    entity = store.partnerships.get(partnership_id)
    if entity is None:
        raise ApiError("ERR_PARTNERSHIP_NOT_FOUND")
    return entity


def get_program(program_id):
    entity = store.programs.get(program_id)
    if entity is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return entity


def get_course(course_id):
    entity = store.courses.get(course_id)
    if entity is None:
        raise ApiError("ERR_COURSE_NOT_FOUND")
    return entity


def get_counselor(counselor_id):
    entity = store.counselors.get(counselor_id)
    if entity is None:
        raise ApiError("ERR_COUNSELOR_NOT_FOUND")
    return entity


def get_lead(lead_id):
    entity = store.leads.get(lead_id)
    if entity is None:
        raise ApiError("ERR_LEAD_NOT_FOUND")
    return entity


def get_enrollment(enrollment_id):
    entity = store.enrollments.get(enrollment_id)
    if entity is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND")
    return entity


def get_statement(statement_id):
    entity = store.statements.get(statement_id)
    if entity is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND")
    return entity


def get_plan(plan_id):
    entity = store.teach_out_plans.get(plan_id)
    if entity is None:
        raise ApiError("ERR_TEACH_OUT_PLAN_NOT_FOUND")
    return entity


def partnership_of_program_id(program_id):
    program = store.programs.get(program_id)
    if program is None:  # pragma: no cover
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    return get_partnership(program["partnership_id"])


def listing(items, serializer, limit, offset):
    page, total, has_more = paginate(items, limit, offset)
    return array_response([serializer(item) for item in page],
                          limit, offset, total, has_more)


def sorted_all(collection):
    return db.sort_created(list(collection.values()))
