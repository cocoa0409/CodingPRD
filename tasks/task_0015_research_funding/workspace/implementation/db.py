"""In-memory data store."""

import threading
import uuid


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.projects = {}             # id -> project
        self.peer_reviews = {}         # id -> peer review
        self.budget_items = {}         # id -> budget item
        self.budget_adjustments = {}   # id -> budget adjustment
        self.reimbursements = {}       # id -> reimbursement
        self.closing_audits = {}       # id -> closing audit
        self.compliance_rules = {}     # id -> compliance rule
        self.indirect_allocations = {} # id -> allocation row
        self.allocation_runs = {}      # run_id -> list of allocation row ids
        self.audit_logs = []           # list of audit log entries

        # Per-(year, source) sequence counter for project_code minting
        self.project_code_counter = {}  # (year, source) -> last seq

    def new_id(self) -> str:
        return str(uuid.uuid4())


db = DB()
