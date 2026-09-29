"""Authentication, RBAC and ownership-scope helpers (PRD 2.1 and ladder rungs 1-5)."""
from flask import request

from db import db
from errors import ApiError

ROLE_STUDENT = "Student"
ROLE_COORDINATOR = "PlaCoordinator"
ROLE_ASSESSOR = "FacultyAssessor"
ROLE_REVIEWER = "AppealReviewer"
ROLE_OFFICER = "ArticulationOfficer"
ROLE_REGISTRAR = "Registrar"

ALL_ROLES = [ROLE_STUDENT, ROLE_COORDINATOR, ROLE_ASSESSOR, ROLE_REVIEWER, ROLE_OFFICER, ROLE_REGISTRAR]

# Roles whose X-User-ID must resolve to a stored row.
ENTITY_BACKED = {
    ROLE_STUDENT: "students",
    ROLE_ASSESSOR: "assessors",
    ROLE_REVIEWER: "assessors",
}


class Ctx(object):
    def __init__(self, user_id, role, actor):
        self.user_id = user_id
        self.role = role
        self.actor = actor

    @property
    def is_student(self):
        return self.role == ROLE_STUDENT

    @property
    def is_assessor_role(self):
        return self.role in (ROLE_ASSESSOR, ROLE_REVIEWER)


def authenticate(allowed_roles):
    """Rung 1 then rung 2 of the validation ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required")
    actor = None
    collection = ENTITY_BACKED.get(role)
    if collection is not None:
        actor = getattr(db, collection).get(user_id)
        if actor is None:
            raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to a known identity")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Ctx(user_id, role, actor)


# ---------------------------------------------------------------- scope (rungs 3-5)
def enforce_student_scope(ctx, student_id):
    if ctx.is_student and student_id != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_STUDENT_SCOPE")


def enforce_assessor_scope(ctx, assessor_id):
    if ctx.is_assessor_role and assessor_id != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_ASSESSOR_SCOPE")


def enforce_panel_member(ctx):
    actor = ctx.actor
    if actor is None or not actor.get("appeal_panel_member"):
        raise ApiError("ERR_NOT_APPEAL_PANEL_MEMBER")


# ---------------------------------------------------------------- path resolution
def find_or_404(collection, row_id, error_id):
    row = getattr(db, collection).get(row_id) if row_id else None
    if row is None:
        raise ApiError(error_id)
    return row


def scoped_claim(ctx, claim_id):
    """Rung 3 outranks rung 6, but ownership can only be judged on an existing row."""
    claim = db.claims.get(claim_id)
    if claim is not None:
        enforce_student_scope(ctx, claim["student_id"])
    if claim is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return claim


def scoped_portfolio(ctx, portfolio_id):
    portfolio = db.portfolios.get(portfolio_id)
    if portfolio is not None:
        claim = db.claims.get(portfolio["claim_id"])
        if claim is not None:
            enforce_student_scope(ctx, claim["student_id"])
    if portfolio is None:
        raise ApiError("ERR_PORTFOLIO_NOT_FOUND")
    return portfolio


def scoped_artifact(ctx, artifact_id):
    """S2.1: "an artifact's grandparent claim's `student_id` ... must equal `X-User-ID`"."""
    artifact = db.artifacts.get(artifact_id)
    if artifact is not None:
        portfolio = db.portfolios.get(artifact["portfolio_id"])
        claim = db.claims.get(portfolio["claim_id"]) if portfolio is not None else None
        if claim is not None:
            enforce_student_scope(ctx, claim["student_id"])
    if artifact is None:
        raise ApiError("ERR_ARTIFACT_NOT_FOUND")
    return artifact


def scoped_invoice(ctx, invoice_id):
    invoice = db.invoices.get(invoice_id)
    if invoice is not None:
        enforce_student_scope(ctx, invoice["student_id"])
    if invoice is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return invoice


def scoped_assignment(ctx, assignment_id):
    assignment = db.assignments.get(assignment_id)
    if assignment is not None:
        enforce_assessor_scope(ctx, assignment["assessor_id"])
    if assignment is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")
    return assignment
