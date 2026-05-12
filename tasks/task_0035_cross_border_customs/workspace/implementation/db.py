"""In-memory data store with a global lock for serialization."""

import threading
import uuid


# A single coarse-grained lock keeps every mutating endpoint serialized,
# which is sufficient for the concurrency guarantees described in PRD §2.7
# (cascades) and §2.8 (idempotency) and the concurrency_rules section.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.hs_codes = {}                # id -> dict
        self.tariff_rules = {}            # id -> dict
        self.exchange_rates = {}          # id -> dict
        self.importers = {}               # id -> dict
        self.declarants = {}              # id -> dict
        self.orders = {}                  # id -> dict
        self.declarations = {}            # id -> dict
        self.declaration_lines = {}       # id -> dict
        self.queries = {}                 # id -> dict
        self.inspections = {}             # id -> dict
        self.payment_notices = {}         # id -> dict
        self.refunds = {}                 # id -> dict
        self.audit_events = []            # list of dicts (append-only)

        # Idempotency tracking: notice_id -> {key -> {"hash": str, "result": dict}}
        self.idempotency = {}

    def reset(self):
        self.__init__()


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())
