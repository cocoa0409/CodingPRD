"""Shared ladder guards: terminality, transition existence, employer posture,
the order cutoff comparison and the employee ownership resolution helpers.

PRD 2.7 fixes the evaluation order; each guard here raises the single catalogued
error for its rung so the callers can simply run them in ladder order.
"""

from errors import already_terminal, bad_state, fail
from store import store

# ------------------------------------------------------- terminal state tables
TERMINAL_EMPLOYER = ("SUSPENDED",)
TERMINAL_CATEGORY = ("RETIRED",)
TERMINAL_EMPLOYEE = ("TERMINATED",)
TERMINAL_MEDIA = ("DISCONTINUED",)
TERMINAL_WINDOW = ("CLOSED",)
TERMINAL_ELECTION_FUNDING = ("REVERSED", "CANCELLED", "SETTLED")
TERMINAL_BATCH = ("RECONCILED",)
TERMINAL_MEDIA_ORDER = ("CANCELLED",)
TERMINAL_CLAIM = ("APPROVED", "REJECTED")
TERMINAL_PAYROLL_FILE = ("ACKNOWLEDGED", "REJECTED")


def require_not_terminal(row, field, terminal_states, label):
    """PRD 2.7 check 14.  A row already parked in a terminal state is refused
    with ERR_ALREADY_TERMINAL, ahead of the transition-existence test, because
    a terminal state has no outgoing transition for any trigger at all."""
    if row[field] in terminal_states:
        already_terminal(
            "%s %s is already in terminal state %s." % (label, row["id"], row[field]))


def require_transition(condition, message):
    """PRD 2.7 check 12: no declared outgoing transition for this trigger."""
    if not condition:
        bad_state(message)


# --------------------------------------------------------------- employer gate
def require_employer_active(employer):
    """PRD 2.7 check 9."""
    if employer is None or employer["program_status"] != "ACTIVE":
        fail("ERR_EMPLOYER_PROGRAM_NOT_ACTIVE",
             "The employer program that owns this resource is not ACTIVE.")


def require_ordinance_ok(employer):
    """PRD 2.7 check 15."""
    if employer["ordinance_mandate_status"] == "MANDATED_NONCOMPLIANT":
        fail("ERR_ORDINANCE_MANDATE_UNMET",
             "The employer has been found deficient under its local commuter "
             "benefit ordinance and may not take on new or amended elections "
             "until the deficiency is cured and re-assessed.")


def require_no_hold(employee):
    """PRD 2.7 check 17."""
    if employee["substantiation_hold"]:
        fail("ERR_SUBSTANTIATION_HOLD_ACTIVE",
             "The employee carries an unresolved repayment receivable and may "
             "not file or amend an election.")


def require_category_active(category):
    """PRD 2.7 check 18."""
    if category["status"] != "ACTIVE":
        fail("ERR_BENEFIT_CATEGORY_RETIRED",
             "Benefit category %s has been retired." % category["id"])


def require_media_eligible(media, category, employee):
    """PRD 2.7 check 19."""
    if media["eligible_category_type"] != category["category_type"] or \
            media["region_code"] != employee["work_region_code"]:
        fail("ERR_MEDIA_REGION_INELIGIBLE",
             "Transit media %s is not eligible for this benefit category or "
             "for the employee's work region." % media["id"])


def require_media_active(media):
    """PRD 2.7 check 20."""
    if media["status"] != "ACTIVE":
        fail("ERR_TRANSIT_MEDIA_DISCONTINUED",
             "Transit media %s has been discontinued." % media["id"])


def require_allocation_allowed(category, pretax_cents, posttax_cents):
    """PRD 2.7 check 22."""
    if pretax_cents > 0 and not category["pretax_allowed"]:
        fail("ERR_ALLOCATION_TYPE_NOT_ALLOWED",
             "Benefit category %s does not accept a pre-tax allocation."
             % category["id"])
    if posttax_cents > 0 and not category["posttax_allowed"]:
        fail("ERR_ALLOCATION_TYPE_NOT_ALLOWED",
             "Benefit category %s does not accept a post-tax allocation."
             % category["id"])


def require_before_cutoff(window):
    """PRD 2.7 check 23: the occupation interval is half-open, so the cutoff
    instant itself is already past."""
    if store.clock_now() >= window["_cutoff_at"]:
        fail("ERR_ORDER_CUTOFF_PASSED",
             "The order cutoff for election window %s has passed." % window["id"])


def require_balance(account, amount_cents):
    """PRD 2.7 check 33 and the same guard on any other debit."""
    if amount_cents > account["available_balance_cents"]:
        fail("ERR_INSUFFICIENT_BENEFIT_BALANCE",
             "The benefit account does not hold enough available balance for "
             "this movement.")


def require_distinct_operator(acting_user_id, recorded_user_id, message):
    """PRD 2.7 check 16."""
    if recorded_user_id is not None and acting_user_id == recorded_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", message)


# ----------------------------------------------------- ownership resolution
def owner_of_election(election):
    return election["employee_id"]


def owner_of_media_order(order):
    election = store.elections.get(order["election_id"])
    return None if election is None else election["employee_id"]


def owner_of_transaction(transaction):
    election = store.elections.get(transaction["election_id"])
    return None if election is None else election["employee_id"]


def owner_of_claim(claim):
    transaction = store.card_transactions.get(claim["card_transaction_id"])
    if transaction is None:
        return None
    return owner_of_transaction(transaction)


def window_of_election(election):
    return store.election_windows.get(election["election_window_id"])


def category_of_election(election):
    return store.benefit_categories.get(election["benefit_category_id"])


def account_of_election(election):
    return store.benefit_accounts.get(election["benefit_account_id"])


def employee_of_election(election):
    return store.employees.get(election["employee_id"])
