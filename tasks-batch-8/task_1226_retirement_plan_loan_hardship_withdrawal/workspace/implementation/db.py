"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. No seeding is permitted.
"""

# Entity stores, keyed by id
plans = {}
participants = {}
contribution_elections = {}       # keyed by election id; also indexed by participant
loans = {}
loan_installments = {}            # keyed by installment id
payroll_remittances = {}
hardship_requests = {}
hardship_documents = {}
approval_tasks = {}
suspension_records = {}
tax_events = {}
audit_events = {}

# Secondary index: participant_id -> election_id (at most one election per participant)
election_by_participant = {}


def reset_all():
    """Clear every store. Used only for safety; never called automatically."""
    for d in (plans, participants, contribution_elections, loans, loan_installments,
              payroll_remittances, hardship_requests, hardship_documents,
              approval_tasks, suspension_records, tax_events, audit_events,
              election_by_participant):
        d.clear()
