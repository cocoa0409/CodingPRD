"""In-memory store: dicts keyed by id. Empty at every boot. No seeding."""
import uuid


def new_id():
    return str(uuid.uuid4())


# Entity tables — plain dicts keyed by id. Each record is a plain dict.
plans = {}
participants = {}
election_windows = {}
deferral_elections = {}
notional_funds = {}
accounts = {}
ledger_entries = {}
crediting_runs = {}
rabbi_trusts = {}
separation_cases = {}
specified_employee_lists = {}
distribution_requests = {}
change_in_control_events = {}
operational_failures = {}
document_findings = {}
