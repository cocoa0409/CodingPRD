"""Shared route helpers: resource resolution and scope checks."""

from core import db, err

NOT_FOUND = {
    "departments": "ERR_DEPARTMENT_NOT_FOUND",
    "licenses": "ERR_LICENSE_NOT_FOUND",
    "runners": "ERR_RUNNER_NOT_FOUND",
    "datasets": "ERR_DATASET_NOT_FOUND",
    "metadata_records": "ERR_METADATA_NOT_FOUND",
    "assessments": "ERR_ASSESSMENT_NOT_FOUND",
    "pipelines": "ERR_PIPELINE_NOT_FOUND",
    "runs": "ERR_RUN_NOT_FOUND",
    "versions": "ERR_VERSION_NOT_FOUND",
    "issues": "ERR_ISSUE_NOT_FOUND",
    "members": "ERR_MEMBER_NOT_FOUND",
    "requests": "ERR_REQUEST_NOT_FOUND",
}


def find(collection_name, row_id):
    collection = getattr(db, collection_name)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        err(NOT_FOUND[collection_name], "No such resource: %s." % row_id)
    return row


def dept_scope(user_id, department_id):
    if user_id != department_id:
        err(
            "ERR_DEPARTMENT_SCOPE_VIOLATION",
            "The acting department does not own this resource.",
        )


def member_scope(user_id, member_id):
    if user_id != member_id:
        err(
            "ERR_MEMBER_SCOPE_VIOLATION",
            "A community member may only act on their own behalf.",
        )


def bad_state(message="The resource is not in a state that allows this transition."):
    err("ERR_INVALID_STATE_TRANSITION", message)
