"""In-memory data store. Empty at boot; tests build all state via API."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.distributors = {}
        self.films = {}
        self.theatres = {}
        self.screens = {}
        self.markets = {}
        self.booking_agreements = {}
        self.aggregate_deals = {}
        self.dcp_shipments = {}
        self.kdm_keys = {}
        self.box_office_reports = {}
        self.settlements = {}
        self.holdover_decisions = {}
        self.marketing_commitments = {}
        self.zone_clearances = {}
        self.ancillary_windows = {}


db = Store()
