"""In-memory data store. Starts completely empty on every boot — no seeding."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock: startup default exactly 2026-05-01T00:00:00Z,
        # never falls back to wall-clock time.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0       # monotonic creation sequence for stable ordering
        self.lot_seq = 0   # lot number sequence (LOT-000001, ...)

        self.formulations = {}     # Formulation
        self.vessels = {}          # MixingVessel
        self.dry_rooms = {}        # DryRoom
        self.batches = {}          # ProductionBatch
        self.runs = {}             # PackagingRun
        self.events = {}           # MoistureExposureEvent
        self.lots = {}             # ProductionLot
        self.tests = {}            # CureTest
        self.requests = {}         # FormulationRequest
        self.distributors = {}     # Distributor
        self.agreements = {}       # ConsignmentAgreement
        self.stock = {}            # ConsignmentStock
        self.reports = {}          # ConsumptionReport
        self.shipments = {}        # Shipment


store = Store()
