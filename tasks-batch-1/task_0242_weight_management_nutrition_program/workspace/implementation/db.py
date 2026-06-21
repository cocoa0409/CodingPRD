"""In-memory data store. All state lives in process memory and resets on boot.

NEVER seed any entity here. Tests construct all state via the API.
"""
import threading
import uuid


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.programs = {}
        self.plans = {}
        self.members = {}
        self.coaches = {}
        self.intake_assessments = {}
        self.enrollments = {}
        self.goals = {}
        self.milestones = {}
        self.weigh_ins = {}
        self.coach_assignments = {}
        self.message_threads = {}
        self.messages = {}
        self.invoices = {}
        self.eligibility_determinations = {}
        self.rx_authorizations = {}


db = Store()


def new_id():
    return str(uuid.uuid4())
