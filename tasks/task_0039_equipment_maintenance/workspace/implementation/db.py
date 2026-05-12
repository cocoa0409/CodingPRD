"""In-memory data store for the Equipment Maintenance API."""
import uuid
from datetime import datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 datetime string. Supports 'Z' suffix.

    Returns a timezone-aware datetime (UTC).
    """
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Initial site clock per scaffold default.
SITE_CLOCK_INIT = "2026-01-01T00:00:00.000Z"


class DB:
    def __init__(self):
        # By-id lookup tables.
        self.sites = {}
        self.equipment = {}
        self.templates = {}
        self.plans = {}
        self.spare_parts = {}
        self.technicians = {}
        self.work_orders = {}
        self.requisitions = {}
        self.repair_records = {}
        self.alarm_events = {}
        self.audit_entries = []  # ordered list

    # ---- helpers --------------------------------------------------------
    def reset(self):
        self.__init__()

    def site_clock(self, site_id: str) -> datetime:
        return self.sites[site_id]["clock_now"]

    def advance_clock(self, site_id: str, seconds: int):
        self.sites[site_id]["clock_now"] = self.sites[site_id]["clock_now"] + timedelta(seconds=seconds)

    # Find by parent helpers
    def equipment_for_site(self, site_id):
        return [e for e in self.equipment.values() if e["site_id"] == site_id]

    def templates_for_site(self, site_id):
        return [t for t in self.templates.values() if t["site_id"] == site_id]

    def plans_for_site(self, site_id):
        return [p for p in self.plans.values() if p["site_id"] == site_id]

    def plans_for_equipment(self, equipment_id):
        return [p for p in self.plans.values() if p["equipment_id"] == equipment_id]

    def spare_parts_for_site(self, site_id):
        return [sp for sp in self.spare_parts.values() if sp["site_id"] == site_id]

    def technicians_for_site(self, site_id):
        return [t for t in self.technicians.values() if t["site_id"] == site_id]

    def work_orders_for_site(self, site_id):
        return [w for w in self.work_orders.values() if w["site_id"] == site_id]

    def work_orders_for_equipment(self, equipment_id):
        return [w for w in self.work_orders.values() if w["equipment_id"] == equipment_id]

    def requisitions_for_work_order(self, wo_id):
        return [r for r in self.requisitions.values() if r["work_order_id"] == wo_id]

    def audit_for_site(self, site_id):
        return [a for a in self.audit_entries if a["site_id"] == site_id]


db = DB()
