"""In-memory data store. A fresh process boots with an empty store — no seeding."""
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0            # global creation-order tiebreak counter
        self.serial_n = 0       # TLT-<n>
        self.job_n = 0          # job sequence number used in invoice numbers
        self.invoice_n = {}     # job_id -> per-job invoice counter
        self.customers = {}
        self.designs = {}
        self.quotes = {}
        self.jobs = {}
        self.milestones = {}
        self.invoices = {}
        self.payments = {}
        self.samples = {}
        self.ecos = {}
        self.ras = {}
        self.tools = {}
        self.shot_reports = {}
        self.claims = {}
        self.inserts = {}
        self.press_res = {}
        self.machine_res = {}


STORE = Store()


def now():
    return STORE.clock
