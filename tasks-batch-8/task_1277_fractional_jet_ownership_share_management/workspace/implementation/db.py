"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. No seeding is permitted.
"""
import uuid

# Entity stores, keyed by id
programs = {}
aircraft_classes = {}
aircraft = {}
owners = {}
shares = {}
bookings = {}
flight_legs = {}
invoices = {}
invoice_lines = {}
transfer_listings = {}
maintenance_events = {}
depreciation_schedules = {}
exit_requests = {}


def new_id():
    return str(uuid.uuid4())


def reset_all():
    """Clear every store. Used only for safety; never called automatically."""
    for d in (programs, aircraft_classes, aircraft, owners, shares, bookings,
              flight_legs, invoices, invoice_lines, transfer_listings,
              maintenance_events, depreciation_schedules, exit_requests):
        d.clear()
