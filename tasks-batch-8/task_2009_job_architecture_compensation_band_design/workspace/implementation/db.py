"""In-memory data store. Store starts empty on every boot; nothing is seeded."""
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class Store:
    def __init__(self):
        self.programs = {}
        self.job_families = {}
        self.job_levels = {}
        self.geo_zones = {}
        self.job_profiles = {}
        self.market_surveys = {}
        self.market_cuts = {}
        self.progression_policies = {}
        self.pay_bands = {}
        self.departments = {}
        self.employees = {}
        self.mapping_decisions = {}
        self.exception_requests = {}
        self.refresh_cycles = {}


store = Store()
