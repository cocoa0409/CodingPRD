"""In-memory data store. Starts completely empty on every boot -- no seeding."""
import itertools
import uuid


class Store:
    def __init__(self):
        self.projects = {}
        self.work_areas = {}
        self.delivery_zones = {}
        self.work_items = {}
        self.daily_reports = {}
        self.crew_entries = {}
        self.equipment_entries = {}
        self.weather_observations = {}
        self.delay_events = {}
        self.safety_observations = {}
        self.incidents = {}
        self.media_attachments = {}
        self.material_deliveries = {}
        self.quantity_entries = {}
        self.tm_tickets = {}
        self.distribution_records = {}
        # idempotency: (path, user_id, key) -> {"fingerprint", "entity", "entity_id", "status"}
        self.idempotency = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())
