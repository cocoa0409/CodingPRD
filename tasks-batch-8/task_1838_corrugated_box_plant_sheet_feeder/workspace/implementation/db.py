"""In-memory data store. Empty at boot; tests build all state via API."""
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customer_accounts = {}
        self.board_grades = {}
        self.work_shifts = {}
        self.corrugator_runs = {}
        self.box_orders = {}
        self.price_quotes = {}
        self.converting_bookings = {}
        self.inventory_programs = {}
        self.release_orders = {}
        self.quality_claims = {}
        # Track outs per (run_id, order_id) attach
        self.run_outs = {}  # {run_id: {order_id: outs}}


db = Store()
