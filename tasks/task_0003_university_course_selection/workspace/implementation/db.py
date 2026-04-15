"""In-memory data store for all entities."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(dt.microsecond // 1000)


# Primary stores keyed by id
semesters = {}
departments = {}
courses = {}
sections = {}
instructors = {}
students = {}
enrollments = {}
cross_dept_permissions = {}
schedule_conflicts = {}
waitlist_promotions = {}


def reset():
    """Clear all data (useful for testing)."""
    for store in [semesters, departments, courses, sections, instructors,
                  students, enrollments, cross_dept_permissions,
                  schedule_conflicts, waitlist_promotions]:
        store.clear()
