"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
import itertools
from clock import LogicalClock


class DB:
    def __init__(self):
        self.organizations = {}
        self.subscriptions = {}
        self.sites = {}
        self.scans = {}
        self.findings = {}
        self.remediation_tasks = {}
        self.retest_runs = {}
        self.vpat_reports = {}
        self.legal_demands = {}
        self.monitoring_checks = {}
        self.training_enrollments = {}
        self.certifications = {}
        self.clock = LogicalClock()
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        """Monotonic creation sequence to make created_at ordering deterministic
        when multiple entities share the same logical-clock timestamp."""
        return next(self._seq)


db = DB()
