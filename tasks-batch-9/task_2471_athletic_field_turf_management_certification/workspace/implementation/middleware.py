"""Authentication, identity resolution and endpoint authorisation (PRD 2.1, 2.10)."""

from flask import request

import calc
import errors
from db import db

ALL_ROLES = tuple(calc.ROLE_NAMES)


def authenticate(allowed_roles, exempt_identity=False):
    """The four ordered auth steps of PRD 2.10. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID", None)
    role = request.headers.get("X-User-Role", None)

    # step 1 - header presence
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise errors.missing_auth()

    # step 2 - role recognition
    if role not in calc.ROLE_NAMES:
        raise errors.unknown_role(role)

    # step 3 - identity resolution against an ACTIVE staff member holding the role
    if not exempt_identity:
        staff = db.staff_members.get(user_id)
        if (staff is None or role not in staff["roles"]
                or staff["employment_status"] != "ACTIVE"):
            raise errors.role_identity_mismatch()

    # step 4 - endpoint authorisation
    if role not in allowed_roles:
        raise errors.unauthorized(role, request.path)

    return user_id, role


# ------------------------------------------------------- path-parameter lookups
def _resolve(collection, entity_id, error_id, what):
    row = collection.get(entity_id)
    if row is None:
        raise errors.not_found(error_id, what)
    return row


def field_or_404(field_id):
    return _resolve(db.fields, field_id, "ERR_FIELD_NOT_FOUND", "Field")


def staff_or_404(staff_id):
    return _resolve(db.staff_members, staff_id, "ERR_STAFF_MEMBER_NOT_FOUND",
                    "StaffMember")


def task_or_404(task_id):
    return _resolve(db.maintenance_tasks, task_id, "ERR_MAINTENANCE_TASK_NOT_FOUND",
                    "MaintenanceTask")


def assessment_or_404(assessment_id):
    return _resolve(db.safety_assessments, assessment_id,
                    "ERR_SAFETY_ASSESSMENT_NOT_FOUND", "SafetyAssessment")


def order_or_404(order_id):
    return _resolve(db.remediation_orders, order_id,
                    "ERR_REMEDIATION_ORDER_NOT_FOUND", "RemediationOrder")


def booking_or_404(booking_id):
    return _resolve(db.usage_bookings, booking_id, "ERR_USAGE_BOOKING_NOT_FOUND",
                    "UsageBooking")


def ledger_or_404(entry_id):
    return _resolve(db.ledger_entries, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND",
                    "UsageLedgerEntry")


def packet_or_404(packet_id):
    return _resolve(db.certification_packets, packet_id,
                    "ERR_CERTIFICATION_PACKET_NOT_FOUND", "CertificationPacket")


def budget_or_404(budget_id):
    return _resolve(db.capital_budgets, budget_id, "ERR_CAPITAL_BUDGET_NOT_FOUND",
                    "CapitalBudget")


def plan_or_404(plan_id):
    return _resolve(db.replacement_plans, plan_id, "ERR_REPLACEMENT_PLAN_NOT_FOUND",
                    "ReplacementPlan")


# ---------------------------------------------------------- body foreign keys
def body_field(field_id):
    row = db.fields.get(field_id) if isinstance(field_id, str) else None
    if row is None:
        raise errors.not_found("ERR_FIELD_NOT_FOUND", "Field")
    return row


def body_staff(staff_id):
    row = db.staff_members.get(staff_id) if isinstance(staff_id, str) else None
    if row is None:
        raise errors.not_found("ERR_STAFF_MEMBER_NOT_FOUND", "StaffMember")
    return row


def body_assessment(assessment_id):
    row = (db.safety_assessments.get(assessment_id)
           if isinstance(assessment_id, str) else None)
    if row is None:
        raise errors.not_found("ERR_SAFETY_ASSESSMENT_NOT_FOUND", "SafetyAssessment")
    return row


def body_budget(budget_id):
    row = db.capital_budgets.get(budget_id) if isinstance(budget_id, str) else None
    if row is None:
        raise errors.not_found("ERR_CAPITAL_BUDGET_NOT_FOUND", "CapitalBudget")
    return row


# ------------------------------------------------------- segregation of duties
def deny_self(acting_user_id, other_id):
    """PRD 2.10: a match on a decision or verification endpoint is a control breach."""
    if other_id is not None and acting_user_id == other_id:
        raise errors.ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "The acting user may not decide or verify their own submission.")
