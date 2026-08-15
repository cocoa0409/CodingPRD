"""In-memory data store. Starts completely empty on every boot; no seeding."""
import uuid
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.complainants = {}          # id -> dict
        self.complaints = {}            # id -> dict
        self.flights = {}               # id -> dict
        self.operators = {}             # id -> dict
        self.monitors = {}              # id -> dict
        self.events = {}                # id -> dict
        self.outages = {}               # id -> dict
        self.curfew_rules = {}          # id -> dict
        self.notifications = {}         # id -> dict
        self.studies = {}               # id -> dict
        self.parcels = {}               # id -> dict
        self.applications = {}          # id -> dict
        self.funds = {}                 # id -> dict
        self.outreach_cases = {}        # id -> dict
        self.reports = {}               # id -> dict


db = Store()


def new_id():
    return str(uuid.uuid4())
