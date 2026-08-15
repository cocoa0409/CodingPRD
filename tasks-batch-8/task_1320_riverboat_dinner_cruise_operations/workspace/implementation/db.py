"""In-memory data store. Plain dicts keyed by id; starts empty on every boot.
No seeding, no persistence, no cross-process state."""
import uuid

TABLES = [
    "vessels", "docks", "menu_tiers", "cruises", "customers", "bookings",
    "passengers", "manifests", "staff_members", "assignments",
    "provision_orders", "inquiries", "weather_events", "credits",
    "dock_slots", "parking_passes",
]

vessels = {}
docks = {}
menu_tiers = {}
cruises = {}
customers = {}
bookings = {}
passengers = {}
manifests = {}
staff_members = {}
assignments = {}
provision_orders = {}
inquiries = {}
weather_events = {}
credits = {}
dock_slots = {}
parking_passes = {}

STORES = {name: globals()[name] for name in TABLES}


def new_id():
    return str(uuid.uuid4())


def insert(store, record):
    store[record["id"]] = record
    return record
