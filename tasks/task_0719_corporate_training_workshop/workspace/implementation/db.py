import uuid
import random
import string
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        self.programs = {}
        self.program_versions = {}
        self.facilitators = {}
        self.cohorts = {}
        self.sessions = {}
        self.session_assignments = {}
        self.registrations = {}
        self.assessments = {}
        self.certificates = {}
        self.contracts = {}
        self.invoices = {}
        self.evaluations = {}
        self.logical_clock = CLOCK_DEFAULT

    def reset(self):
        self.__init__()


db = Store()
