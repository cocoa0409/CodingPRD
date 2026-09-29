"""Header authentication (PRD 2.1), RBAC, path resolution (PRD 2.6) and scope."""

from flask import request

from errors import ApiError, fail
from store import store

ROLES = ["ProgramAdmin", "Employee", "OrderDesk", "ComplianceReviewer", "PayrollProcessor"]

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Principal(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_employee(self):
        return self.role == "Employee"


def authenticate(allowed_roles):
    """Ladder steps 1 and 2: header presence / role validity, then endpoint RBAC."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Both X-User-ID and X-User-Role headers are required, and "
                       "X-User-Role must name one of the five defined roles.")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403,
                       "Role %s is not permitted to call this operation." % role)
    return Principal(user_id, role)


# ------------------------------------------------------- entity resolution 404
_COLLECTIONS = {
    "employer": ("employers", "ERR_EMPLOYER_NOT_FOUND", "Employer"),
    "employee": ("employees", "ERR_EMPLOYEE_NOT_FOUND", "Employee"),
    "window": ("election_windows", "ERR_ELECTION_WINDOW_NOT_FOUND", "ElectionWindow"),
    "category": ("benefit_categories", "ERR_BENEFIT_CATEGORY_NOT_FOUND", "BenefitCategory"),
    "account": ("benefit_accounts", "ERR_BENEFIT_ACCOUNT_NOT_FOUND", "BenefitAccount"),
    "election": ("elections", "ERR_ELECTION_NOT_FOUND", "Election"),
    "media": ("transit_media", "ERR_TRANSIT_MEDIA_NOT_FOUND", "TransitMedia"),
    "batch": ("order_batches", "ERR_ORDER_BATCH_NOT_FOUND", "OrderBatch"),
    "order": ("media_orders", "ERR_MEDIA_ORDER_NOT_FOUND", "MediaOrder"),
    "transaction": ("card_transactions", "ERR_CARD_TRANSACTION_NOT_FOUND", "CardTransaction"),
    "claim": ("substantiation_claims", "ERR_SUBSTANTIATION_CLAIM_NOT_FOUND",
              "SubstantiationClaim"),
    "file": ("payroll_files", "ERR_PAYROLL_FILE_NOT_FOUND", "PayrollFile"),
    "entry": ("ledger_entries", "ERR_LEDGER_ENTRY_NOT_FOUND", "LedgerEntry"),
    "assessment": ("compliance_assessments", "ERR_COMPLIANCE_ASSESSMENT_NOT_FOUND",
                   "ComplianceAssessment"),
}


def resolve(kind, row_id):
    """Resolve one identifier to its row, or raise that entity's 404 code."""
    attr, error_id, label = _COLLECTIONS[kind]
    table = getattr(store, attr)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(error_id, "%s %s was not found." % (label, row_id))
    return row


def resolve_employer(row_id):
    return resolve("employer", row_id)


def resolve_employee(row_id):
    return resolve("employee", row_id)


def resolve_window(row_id):
    return resolve("window", row_id)


def resolve_category(row_id):
    return resolve("category", row_id)


def resolve_account(row_id):
    return resolve("account", row_id)


def resolve_election(row_id):
    return resolve("election", row_id)


def resolve_media(row_id):
    return resolve("media", row_id)


def resolve_batch(row_id):
    return resolve("batch", row_id)


def resolve_order(row_id):
    return resolve("order", row_id)


def resolve_transaction(row_id):
    return resolve("transaction", row_id)


def resolve_claim(row_id):
    return resolve("claim", row_id)


def resolve_file(row_id):
    return resolve("file", row_id)


def resolve_entry(row_id):
    return resolve("entry", row_id)


def resolve_assessment(row_id):
    return resolve("assessment", row_id)


# --------------------------------------------------------- employee ownership
def require_employee_scope(principal, owner_employee_id):
    """Ladder step 8: an Employee caller may only act on their own records."""
    if not principal.is_employee:
        return
    if principal.user_id != owner_employee_id:
        fail("ERR_EMPLOYEE_SCOPE_VIOLATION",
             "The acting employee does not own the target resource.")
