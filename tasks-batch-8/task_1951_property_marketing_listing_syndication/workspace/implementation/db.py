"""In-memory data store. Starts empty on every boot — no seeding."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.agents = {}
        self.listings = {}
        self.media_assets = {}
        self.reviews = {}
        self.portals = {}
        self.blackouts = {}
        self.subscriptions = {}
        self.jobs = {}
        self.events = {}
        self.windows = {}
        self.feedbacks = {}
        self.relist_requests = {}
        self.event_seq = {}       # listing_id -> last event seq
        self.insert_counter = 0   # global tiebreak for equal created_at


store = Store()
