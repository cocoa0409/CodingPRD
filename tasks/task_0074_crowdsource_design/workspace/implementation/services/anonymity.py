"""Anonymity helpers: redact designer identity until Project.AWARDED."""
import secrets
import string

from db import db


def mint_anonymized_alias() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "DSGN-" + "".join(secrets.choice(alphabet) for _ in range(8))


def project_is_unmasked(project: dict) -> bool:
    return project is not None and project.get("anonymity_unmasked_at") is not None


def submission_view_for(submission: dict, role: str) -> dict:
    """Return a copy of the Submission view for a caller of the given role.

    PRD §2.10: until Project.AWARDED, Reviewer and Client see the alias on a
    ReviewAssignment and the underlying Submission.designer_id is redacted
    (null). PlatformOps and Designer keep visibility (Designer only on own work
    is enforced at route level).
    """
    if submission is None:
        return None
    out = dict(submission)
    project = db.projects.get(submission.get("project_id"))
    unmasked = project_is_unmasked(project)
    if not unmasked and role in {"Reviewer", "Client"}:
        out["designer_id"] = None
    return out


def assignment_view_for(assignment: dict, role: str) -> dict:
    if assignment is None:
        return None
    out = dict(assignment)
    submission = db.submissions.get(assignment.get("submission_id"))
    project = db.projects.get(submission.get("project_id")) if submission else None
    unmasked = project_is_unmasked(project)
    if not unmasked and role in {"Reviewer", "Client"}:
        out["submission_designer_id"] = None
    return out
