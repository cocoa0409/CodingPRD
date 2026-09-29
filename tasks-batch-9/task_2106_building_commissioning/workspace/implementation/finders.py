"""Existence lookups mapped to the scaffold's not-found error ids."""
from core import db, fail

_MAP = [
    ("project", "projects", "ERR_PROJECT_NOT_FOUND"),
    ("requirement", "requirements", "ERR_REQUIREMENT_NOT_FOUND"),
    ("plan", "plans", "ERR_PLAN_NOT_FOUND"),
    ("submittal", "submittals", "ERR_SUBMITTAL_NOT_FOUND"),
    ("equipment", "equipment", "ERR_EQUIPMENT_NOT_FOUND"),
    ("checklist", "checklists", "ERR_CHECKLIST_NOT_FOUND"),
    ("test", "tests", "ERR_TEST_NOT_FOUND"),
    ("issue", "issues", "ERR_ISSUE_NOT_FOUND"),
    ("deferred_test", "deferred_tests", "ERR_DEFERRED_TEST_NOT_FOUND"),
    ("deliverable", "deliverables", "ERR_DELIVERABLE_NOT_FOUND"),
    ("credit", "credits", "ERR_CREDIT_NOT_FOUND"),
    ("baseline", "baselines", "ERR_BASELINE_NOT_FOUND"),
]


def _make(collection_name, error_id):
    def finder(row_id):
        collection = getattr(db, collection_name)
        row = collection.get(row_id) if isinstance(row_id, str) else None
        if row is None:
            fail(error_id, "Referenced resource '%s' was not found." % row_id)
        return row
    return finder


get_project = _make("projects", "ERR_PROJECT_NOT_FOUND")
get_requirement = _make("requirements", "ERR_REQUIREMENT_NOT_FOUND")
get_plan = _make("plans", "ERR_PLAN_NOT_FOUND")
get_submittal = _make("submittals", "ERR_SUBMITTAL_NOT_FOUND")
get_equipment = _make("equipment", "ERR_EQUIPMENT_NOT_FOUND")
get_checklist = _make("checklists", "ERR_CHECKLIST_NOT_FOUND")
get_test = _make("tests", "ERR_TEST_NOT_FOUND")
get_issue = _make("issues", "ERR_ISSUE_NOT_FOUND")
get_deferred_test = _make("deferred_tests", "ERR_DEFERRED_TEST_NOT_FOUND")
get_deliverable = _make("deliverables", "ERR_DELIVERABLE_NOT_FOUND")
get_credit = _make("credits", "ERR_CREDIT_NOT_FOUND")
get_baseline = _make("baselines", "ERR_BASELINE_NOT_FOUND")
