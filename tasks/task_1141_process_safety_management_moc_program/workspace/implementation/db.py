"""In-memory data store. Starts completely empty on every boot — no seeding."""
from datetime import date


class Store:
    def __init__(self):
        # Logical clock: startup default exactly 2026-05-01 (UTC midnight),
        # never falls back to wall-clock.
        self.clock = date(2026, 5, 1)
        self.seq = 0  # monotonic creation sequence for stable created_at ordering

        self.units = {}            # PlantUnit
        self.personnel = {}        # Personnel
        self.mocs = {}             # MocRequest
        self.reviews = {}          # TechnicalReview
        self.studies = {}          # PhaStudy
        self.revalidations = {}    # PhaRevalidation
        self.pssrs = {}            # Pssr
        self.action_items = {}     # ActionItem
        self.evidence = {}         # EvidenceItem
        self.incidents = {}        # IncidentInvestigation
        self.audits = {}           # Audit
        self.findings = {}         # AuditFinding
        self.procedures = {}       # ProcedureUpdate
        self.trainings = {}        # TrainingAssignment
        self.extensions = {}       # ExtensionRequest


store = Store()
