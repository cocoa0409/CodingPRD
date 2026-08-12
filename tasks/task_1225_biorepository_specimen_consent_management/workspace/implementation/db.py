"""In-memory data store. Fresh on every process boot; nothing is seeded."""
import uuid

# Entity collections, keyed by id.
donors = {}
consent_records = {}
collection_kits = {}
custody_events = {}
specimens = {}
aliquots = {}
storage_units = {}
temperature_readings = {}
storage_slots = {}
slot_reservations = {}
sample_requests = {}
review_votes = {}
sharing_agreements = {}
deidentification_keys = {}
key_access_grants = {}
destruction_orders = {}


def new_id():
    return str(uuid.uuid4())
