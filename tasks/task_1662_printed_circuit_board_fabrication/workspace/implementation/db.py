"""In-memory data store. All state lives here and is wiped on restart."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.quick_turn_lanes = {}
        self.laminate_lots = {}
        self.fab_orders = {}
        self.stackups = {}
        self.impedance_spec_lines = {}
        self.panel_arrays = {}
        self.drill_programs = {}
        self.laminate_reservations = {}
        self.lane_slot_commitments = {}
        self.impedance_coupons = {}
        self.coupon_measurements = {}
        self.lab_slot_bookings = {}
        self.elec_test_runs = {}
        self.defect_records = {}
        self.invoices = {}
        # logical clock
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # sequential order number counter
        self.order_number_seq = 0


store = Store()


def new_store():
    global store
    store = Store()
    return store
