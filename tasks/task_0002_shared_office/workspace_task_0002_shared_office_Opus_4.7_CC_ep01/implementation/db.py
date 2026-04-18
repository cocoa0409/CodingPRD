import uuid
from datetime import datetime, timezone
from threading import RLock


class DB:
    def __init__(self):
        self.lock = RLock()
        self.tenants: dict = {}
        self.members: dict = {}
        self.leases: dict = {}
        self.resources: dict = {}
        self.reservations: dict = {}
        self.visitors: dict = {}
        self.access_badges: dict = {}
        self.bills: dict = {}
        self.bill_lines: dict = {}
        self.clock = datetime.now(timezone.utc)

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def now(self) -> datetime:
        return self.clock

    def set_clock(self, dt: datetime):
        self.clock = dt

    # Indexed lookups
    def member_by_email(self, email: str):
        for m in self.members.values():
            if m["email"].lower() == email.lower():
                return m
        return None

    def resource_by_code(self, code: str):
        for r in self.resources.values():
            if r["code"] == code:
                return r
        return None

    def badge_by_serial(self, serial: str):
        for b in self.access_badges.values():
            if b["badge_serial"] == serial:
                return b
        return None

    def badges_for_member(self, member_id: str):
        return [b for b in self.access_badges.values() if b["member_id"] == member_id]

    def active_lease_for_tenant(self, tenant_id: str):
        """Returns the tenant's active lease with latest term_start_date.
        Ties broken by greatest Lease.id lexicographic.
        """
        active = [l for l in self.leases.values() if l["tenant_id"] == tenant_id and l["status"] == "ACTIVE"]
        if not active:
            return None
        return sorted(active, key=lambda l: (l["term_start_date"], l["id"]), reverse=True)[0]


db = DB()
