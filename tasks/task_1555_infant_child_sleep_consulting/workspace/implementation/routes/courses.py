from flask import Blueprint, request

from auth import user_context, require_role, forbidden
from db import store, base_fields, register, touch, now
from domain import ser_course, ser_enrollment, course_enrolled_count
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_str, req_int, req_date

bp = Blueprint('courses', __name__)


def load_course(course_id):
    c = store.courses.get(course_id)
    if c is None:
        raise ApiError('ERR_COURSE_NOT_FOUND', 404, 'Course not found')
    return c


@bp.post('/group-courses')
def create_course():
    _, role = user_context()
    require_role(role, 'PracticeAdmin')
    data = body()
    consultant_id = req_str(data, 'consultant_id')
    title = req_str(data, 'title')
    starts_on = req_date(data, 'starts_on')
    capacity = req_int(data, 'capacity', min_v=1)
    price_cents = req_int(data, 'price_cents', min_v=0)
    if consultant_id not in store.consultants:
        raise ApiError('ERR_CONSULTANT_NOT_FOUND', 404,
                       'consultant_id does not exist')
    c = base_fields()
    c.update({
        'consultant_id': consultant_id,
        'title': title,
        'starts_on': starts_on,
        'capacity': capacity,
        'price_cents': price_cents,
    })
    register(store.courses, c)
    return ok(ser_course(c), status=201)


@bp.get('/group-courses')
def list_courses():
    _, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    rows = list(store.courses.values())
    consultant_id = request.args.get('consultant_id')
    if consultant_id is not None:
        rows = [c for c in rows if c['consultant_id'] == consultant_id]
    return paginate(rows, ser_course)


@bp.get('/group-courses/<courseId>')
def get_course(courseId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    return ok(ser_course(load_course(courseId)))


@bp.post('/group-courses/<courseId>/enrollments')
def enroll(courseId):
    uid, role = user_context()
    require_role(role, 'Parent')
    data = body()
    case_id = req_str(data, 'case_id')
    course = load_course(courseId)
    case = store.cases.get(case_id)
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'case_id does not exist')
    if case['family_id'] != uid:
        forbidden('Parent may enroll only their own cases')
    # Temporal (stage 7): enrollment closes at 00:00:00Z on starts_on.
    if now().date() >= course['starts_on']:
        raise ApiError('ERR_ENROLLMENT_CLOSED', 422,
                       'Enrollment is closed on or after the course start date')
    # Uniqueness (stage 8): a live (ENROLLED/WAITLISTED) enrollment blocks.
    if any(e['course_id'] == course['id'] and e['case_id'] == case['id']
           and e['status'] in ('ENROLLED', 'WAITLISTED')
           for e in store.enrollments.values()):
        raise ApiError('ERR_ALREADY_ENROLLED', 409,
                       'A live enrollment already exists for this course and case')
    # Delivery-mode match (stage 10).
    if case['delivery_mode'] != 'GROUP_COURSE':
        raise ApiError('ERR_DELIVERY_MODE_MISMATCH', 422,
                       'Course enrollment requires delivery_mode GROUP_COURSE')
    status = ('ENROLLED' if course_enrolled_count(course['id']) < course['capacity']
              else 'WAITLISTED')
    e = base_fields()
    e.update({
        'course_id': course['id'],
        'case_id': case['id'],
        'status': status,
        'promoted_at': None,
    })
    register(store.enrollments, e)
    return ok(ser_enrollment(e), status=201)


@bp.get('/group-courses/<courseId>/enrollments')
def list_course_enrollments(courseId):
    _, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    course = load_course(courseId)
    rows = [e for e in store.enrollments.values() if e['course_id'] == course['id']]
    status = request.args.get('status')
    if status is not None:
        rows = [e for e in rows if e['status'] == status]
    return paginate(rows, ser_enrollment)


@bp.post('/enrollments/<enrollmentId>/cancel')
def cancel_enrollment(enrollmentId):
    uid, role = user_context()
    require_role(role, 'Parent', 'PracticeAdmin')
    e = store.enrollments.get(enrollmentId)
    if e is None:
        raise ApiError('ERR_ENROLLMENT_NOT_FOUND', 404, 'Enrollment not found')
    case = store.cases.get(e['case_id'])
    if case is None:
        raise ApiError('ERR_CASE_NOT_FOUND', 404, 'Case not found')
    if role == 'Parent' and case['family_id'] != uid:
        forbidden('Parent may cancel only their own enrollments')
    if e['status'] not in ('ENROLLED', 'WAITLISTED'):
        raise ApiError('ERR_ENROLLMENT_INVALID_STATE', 409,
                       'Cancellation requires the enrollment to be ENROLLED or '
                       'WAITLISTED')
    if e['status'] == 'ENROLLED':
        e['status'] = 'CANCELLED'
        touch(e)
        # Waitlist promotion: exactly one earliest-created WAITLISTED row is
        # promoted; when none is waiting, the seat simply stays open.
        waiting = [w for w in store.enrollments.values()
                   if w['course_id'] == e['course_id'] and w['status'] == 'WAITLISTED']
        if waiting:
            waiting.sort(key=lambda w: (w['created_at'], w['_seq']))
            promoted = waiting[0]
            promoted['status'] = 'ENROLLED'
            promoted['promoted_at'] = now()
            touch(promoted)
    else:
        e['status'] = 'WITHDRAWN'
        touch(e)
    return ok(ser_enrollment(e))
