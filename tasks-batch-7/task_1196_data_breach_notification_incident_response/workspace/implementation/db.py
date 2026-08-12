"""In-memory data store. All dicts start empty; no seeding at startup."""
import uuid


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.incidents = {}
        self.forensic_scopes = {}
        self.evidence_items = {}
        self.custody_logs = {}
        self.affected_subjects = {}
        self.jurisdiction_evaluations = {}
        self.notices = {}
        self.mailing_batches = {}
        self.credit_monitoring_offers = {}
        self.call_center_plans = {}
        self.regulator_submissions = {}
        self.remediation_actions = {}


store = Store()
