"""In-memory data store. Each table is a dict keyed by id (UUID string)."""

import threading
import uuid


_lock = threading.RLock()

# Tables — keyed by id (UUID).
enterprises = {}
allocation_cycles = {}
allocations = {}
objections = {}
emission_reports = {}
emission_data_lines = {}
supporting_documents = {}
verification_assignments = {}
trading_orders = {}
trades = {}
compliance_declarations = {}
penalty_orders = {}
annual_settlements = {}
audit_log_entries = []           # ordered list (append-only)

# Idempotency tracking for synthetic external events.
processed_event_ids = set()

# Pending mandatory deductions, keyed by enterprise_id; recorded against next cycle.
# Each entry: { enterprise_id, amount, source_penalty_id, recorded_at }
pending_deductions = []


def new_id():
    return str(uuid.uuid4())


def lock():
    return _lock


def reset_all():
    with _lock:
        enterprises.clear()
        allocation_cycles.clear()
        allocations.clear()
        objections.clear()
        emission_reports.clear()
        emission_data_lines.clear()
        supporting_documents.clear()
        verification_assignments.clear()
        trading_orders.clear()
        trades.clear()
        compliance_declarations.clear()
        penalty_orders.clear()
        annual_settlements.clear()
        audit_log_entries.clear()
        processed_event_ids.clear()
        pending_deductions.clear()
