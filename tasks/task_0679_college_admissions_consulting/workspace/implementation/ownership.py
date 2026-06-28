"""Ownership resolution per PRD §2.1.

A Counselor owns students whose counselor_id == caller id, plus every resource
transitively belonging to those students. A Student owns resources whose owning
student's id == caller id. PlatformAdmin never owns business resources but may
use the operations the RBAC matrix grants.

Each check resolves a resource to its owning (student_id, counselor_id) and
compares against the caller identity. Raises ERR_FORBIDDEN on mismatch.
"""
from db import store
from errors import err, ERR_FORBIDDEN


def _student_owner(student):
    return student["id"], student.get("counselor_id")


def owner_of_student(student):
    return student["id"], student.get("counselor_id")


def owner_of_contract(contract):
    return contract.get("student_id"), contract.get("counselor_id")


def owner_of_billing_entry(entry):
    contract = store.contracts.get(entry.get("contract_id"))
    if contract is None:
        return None, None
    return owner_of_contract(contract)


def owner_of_school_item(item):
    student = store.students.get(item.get("student_id"))
    if student is None:
        return item.get("student_id"), None
    return _student_owner(student)


def owner_of_application(app):
    student = store.students.get(app.get("student_id"))
    if student is None:
        return app.get("student_id"), None
    return _student_owner(student)


def owner_of_task(task):
    app = store.applications.get(task.get("application_id"))
    if app is None:
        return None, None
    return owner_of_application(app)


def owner_of_essay(essay):
    student = store.students.get(essay.get("student_id"))
    if student is None:
        return essay.get("student_id"), None
    return _student_owner(student)


def owner_of_essay_version(version):
    essay = store.essays.get(version.get("essay_id"))
    if essay is None:
        return None, None
    return owner_of_essay(essay)


def owner_of_recommendation(rec):
    student = store.students.get(rec.get("student_id"))
    if student is None:
        return rec.get("student_id"), None
    return _student_owner(student)


def owner_of_activity(act):
    student = store.students.get(act.get("student_id"))
    if student is None:
        return act.get("student_id"), None
    return _student_owner(student)


def owner_of_scholarship(award):
    student = store.students.get(award.get("student_id"))
    if student is None:
        return award.get("student_id"), None
    return _student_owner(student)


def owner_of_appointment(appt):
    return appt.get("student_id"), appt.get("counselor_id")


def assert_owns(caller, student_id, counselor_id):
    """Enforce ownership. PlatformAdmin asserts no business ownership and so is
    not granted access through this path (callers that allow admin handle it
    before calling)."""
    if caller.is_counselor:
        if counselor_id != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this resource")
    elif caller.is_student:
        if student_id != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this resource")
    else:
        raise err(ERR_FORBIDDEN, "Role may not own business resources")
