"""Shared route helpers: lookups, list plumbing and enum vocabularies."""
from errors import fail
from middleware import check_scope, scope_filter
from response import ok, ok_list
from store import db, ordered, public
from validation import pagination

# ---- enum vocabularies (from the entity constraints) -----------------------
DISABILITY_CATEGORIES = (
    "AUTISM",
    "EMOTIONAL_DISABILITY",
    "INTELLECTUAL_DISABILITY",
    "MULTIPLE_DISABILITIES",
    "SPECIFIC_LEARNING_DISABILITY",
    "OTHER_HEALTH_IMPAIRMENT",
)
LRE_SETTINGS = (
    "GENERAL_ED_80_PLUS",
    "RESOURCE_40_79",
    "SEPARATE_CLASS_UNDER_40",
    "SEPARATE_DAY_SCHOOL",
    "RESIDENTIAL_FACILITY",
)
APPROVAL_STATUSES = ("APPROVED", "PROVISIONAL", "REVOKED")
CLIENT_APPROVAL_STATES = ("DRAFT", "STATE_APPROVED")
PLACEMENT_TYPES = ("DAY", "RESIDENTIAL")
SERVICE_TYPES = ("SPEECH", "OT", "PT", "COUNSELING", "BCBA")
DECISION_STATUSES = ("DRAFT", "TEAM_REVIEW", "RETURNED_FOR_REVISION", "APPROVED")
PLACEMENT_STATUSES = (
    "PROPOSED",
    "CONTRACTED",
    "ACTIVE",
    "TERMINATED",
    "RETURNED_TO_DISTRICT",
    "EXPIRED",
)
CLAIM_TYPES = ("HIGH_COST_FUND", "MEDICAID")
AWARD_BASES = ("strict_statutory", "equitable_actual_cost")
ACCEPT_DECISIONS = ("ACCEPT", "DISPUTE")
REPORT_DECISIONS = ("ACCEPT", "REJECT")
VERIFICATION_BASES = ("ENROLLMENT", "ATTENDANCE")

CLOSED_PLACEMENT_STATES = ("ACTIVE", "TERMINATED", "RETURNED_TO_DISTRICT")


# ---- existence ------------------------------------------------------------

def get_row(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row


def student_or_404(student_id):
    return get_row(db.students, student_id, "ERR_STUDENT_NOT_FOUND")


def school_or_404(school_id):
    return get_row(db.schools, school_id, "ERR_SCHOOL_NOT_FOUND")


def schedule_or_404(schedule_id):
    return get_row(db.rate_schedules, schedule_id, "ERR_RATE_SCHEDULE_NOT_FOUND")


def decision_or_404(decision_id):
    return get_row(db.decisions, decision_id, "ERR_DECISION_NOT_FOUND")


def placement_or_404(placement_id):
    return get_row(db.placements, placement_id, "ERR_PLACEMENT_NOT_FOUND")


def addendum_or_404(addendum_id):
    return get_row(db.addenda, addendum_id, "ERR_ADDENDUM_NOT_FOUND")


def route_or_404(route_id):
    return get_row(db.routes, route_id, "ERR_ROUTE_NOT_FOUND")


def assignment_or_404(assignment_id):
    return get_row(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")


def attendance_or_404(record_id):
    return get_row(db.attendance, record_id, "ERR_ATTENDANCE_RECORD_NOT_FOUND")


def invoice_or_404(invoice_id):
    return get_row(db.invoices, invoice_id, "ERR_INVOICE_NOT_FOUND")


def reimbursement_or_404(claim_id):
    return get_row(db.reimbursements, claim_id, "ERR_CLAIM_NOT_FOUND")


def report_or_404(report_id):
    return get_row(db.progress, report_id, "ERR_PROGRESS_REPORT_NOT_FOUND")


def plan_or_404(plan_id):
    return get_row(db.plans, plan_id, "ERR_TRANSITION_PLAN_NOT_FOUND")


def funding_or_404(claim_id):
    return get_row(db.funding, claim_id, "ERR_FUNDING_CLAIM_NOT_FOUND")


def account_or_404(account_id):
    return get_row(db.accounts, account_id, "ERR_FISCAL_ACCOUNT_NOT_FOUND")


# ---- read plumbing --------------------------------------------------------

def single(row):
    check_scope(row)
    return ok(public(row))


def collection(rows, filters=None):
    """rows: iterable of stored rows. filters: list of (field, value) pairs."""
    limit, offset = pagination()
    selected = list(rows)
    if filters:
        for field, value in filters:
            if value is None:
                continue
            selected = [r for r in selected if _matches(r, field, value)]
    selected = scope_filter(selected)
    selected = ordered(selected)
    total = len(selected)
    return ok_list(selected[offset:offset + limit], total, limit, offset)


def _matches(row, field, value):
    current = row.get(field)
    if isinstance(value, bool):
        return current is value
    return current == value
