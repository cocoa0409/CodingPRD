"""In-memory data store."""
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.tenants = {}         # tenant_id -> Tenant dict
        self.members = {}         # member_id -> Member dict
        self.leases = {}          # lease_id -> Lease dict
        self.resources = {}       # resource_id -> Resource dict
        self.reservations = {}    # reservation_id -> Reservation dict
        self.visitors = {}        # visitor_id -> Visitor dict
        self.badges = {}          # badge_id -> AccessBadge dict
        self.bills = {}           # bill_id -> Bill dict
        self.bill_lines = {}      # bill_line_id -> BillLine dict


db = DB()
