"""In-memory data store (PRD §2.4).

All state lives in module-level dicts keyed by bare-UUID id. Nothing is seeded
at startup; every entity is created via the API. The store is wiped on each
fresh process boot because it is plain process memory.

Version-bearing entities (Account, EquipmentUnit, ServiceOrder, InstallSlot,
Technician, InstallAppointment, BillingCycle, OutageEvent, TransferRequest)
carry id, created_at, updated_at, version. The four lean entities
(ServiceAddress, ServicePlan, UsageRecord, AccountCredit) carry only id and
created_at.
"""
import uuid

from clock import get_clock
from timeutil import format_iso

# One dict per entity collection, keyed by id.
service_addresses = {}
service_plans = {}
accounts = {}
equipment_units = {}
service_orders = {}
install_slots = {}
technicians = {}
install_appointments = {}
billing_cycles = {}
usage_records = {}
outage_events = {}
account_credits = {}
transfer_requests = {}

# Entities that carry updated_at + version (PRD §2.4).
VERSIONED = True
LEAN = False


def new_id():
    return str(uuid.uuid4())


def _now_iso():
    return format_iso(get_clock().now())


def make_record(fields, versioned):
    """Build a fresh record dict with common fields stamped.

    `fields` is the entity-specific payload. Common fields (PRD §2.4) are added:
    id, created_at always; updated_at, version when versioned.
    """
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = _now_iso()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh a versioned record's updated_at and bump its version (PRD §2.7)."""
    rec["updated_at"] = _now_iso()
    rec["version"] = rec.get("version", 1) + 1
