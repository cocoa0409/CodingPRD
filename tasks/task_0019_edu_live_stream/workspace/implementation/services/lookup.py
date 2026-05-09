"""Resource lookup helpers — produce the right not-found error per resource."""
from db import store
from errors import raise_api


def get_course(cid):
    obj = store.courses.get(cid)
    if not obj:
        raise_api("ERR_COURSE_NOT_FOUND", f"Course {cid} not found")
    return obj


def get_chapter(chid):
    obj = store.chapters.get(chid)
    if not obj:
        raise_api("ERR_CHAPTER_NOT_FOUND", f"Chapter {chid} not found")
    return obj


def get_instructor(iid):
    obj = store.instructors.get(iid)
    if not obj:
        raise_api("ERR_INSTRUCTOR_NOT_FOUND", f"Instructor {iid} not found")
    return obj


def get_student(sid):
    obj = store.students.get(sid)
    if not obj:
        raise_api("ERR_STUDENT_NOT_FOUND", f"Student {sid} not found")
    return obj


def get_enrollment(eid):
    obj = store.enrollments.get(eid)
    if not obj:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", f"Enrollment {eid} not found")
    return obj


def get_live_class(lid):
    obj = store.live_classes.get(lid)
    if not obj:
        raise_api("ERR_LIVE_CLASS_NOT_FOUND", f"LiveClass {lid} not found")
    return obj


def get_assignment(aid):
    obj = store.assignments.get(aid)
    if not obj:
        raise_api("ERR_ASSIGNMENT_NOT_FOUND", f"Assignment {aid} not found")
    return obj


def get_submission(sid):
    obj = store.submissions.get(sid)
    if not obj:
        raise_api("ERR_SUBMISSION_NOT_FOUND", f"Submission {sid} not found")
    return obj


def get_refund_request(rid):
    obj = store.refund_requests.get(rid)
    if not obj:
        raise_api("ERR_REFUND_NOT_FOUND", f"RefundRequest {rid} not found")
    return obj


def get_leave_request(lid):
    obj = store.leave_requests.get(lid)
    if not obj:
        raise_api("ERR_LEAVE_NOT_FOUND", f"LeaveRequest {lid} not found")
    return obj


def get_class_group(gid):
    obj = store.class_groups.get(gid)
    if not obj:
        raise_api("ERR_CLASS_GROUP_NOT_FOUND", f"ClassGroup {gid} not found")
    return obj
