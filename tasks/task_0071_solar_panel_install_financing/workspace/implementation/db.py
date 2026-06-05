import uuid
import threading
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.homeowners = {}
        self.installers = {}
        self.utilities = {}
        self.brokers = {}
        self.projects = {}
        self.financing_plans = {}
        self.interconnection_applications = {}
        self.srecs = {}
        self.srec_sales = {}
        self.net_meter_periods = {}
        self.warranty_policies = {}
        self.warranty_claims = {}
        # project-level kWh bank accumulator
        self.project_bank = {}  # project_id -> int

    def touch(self, entity, has_version=True):
        entity["updated_at"] = now_iso()
        if has_version:
            entity["version"] = entity.get("version", 0) + 1


db = DB()
