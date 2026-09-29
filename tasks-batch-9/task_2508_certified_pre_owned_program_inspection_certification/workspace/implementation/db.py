"""In-memory data store and the logical programme clock.

Nothing here is seeded except the single ProgramConfig row (PRD 2.6: "The
programme's tunables live in a single programme configuration row that the
server seeds at startup with the documented defaults").  No entity data is
ever preloaded.
"""
import itertools
import uuid
from datetime import datetime

# PRD 2.5 — before any request moves it the clock reads exactly this instant.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0)

# PRD 2.6 — the documented defaults of the programme rulebook.
CONFIG_DEFAULTS = {
    "max_age_days": 2190,
    "max_odometer_miles": 80000,
    "ineligible_title_brands": ["SALVAGE", "FLOOD", "LEMON", "REBUILT", "ODOMETER_DISCREPANCY"],
    "ineligible_prior_uses": ["RENTAL", "TAXI", "DRIVING_SCHOOL", "POLICE"],
    "base_fee_cents": 89900,
    "age_surcharge_free_years": 3,
    "age_surcharge_cents_per_year": 12500,
    "mileage_surcharge_free_miles": 40000,
    "mileage_surcharge_cents_per_10k": 9000,
    "surcharge_cap_pct": 0.35,
    "volume_discount_tiers": [
        {"min_count": 0, "pct": 0.0},
        {"min_count": 10, "pct": 0.05},
        {"min_count": 50, "pct": 0.10},
    ],
    "recon_reimbursement_share": 0.6,
    "recon_reimbursement_cap_cents": 150000,
    "factory_basic_months": 36,
    "factory_basic_miles": 36000,
    "warranty_extension_months": 12,
    "warranty_extension_miles": 12000,
    "warranty_total_cap_months": 84,
    "warranty_total_cap_miles": 100000,
    "claim_per_claim_cap_cents": 250000,
    "claim_window_days": 365,
    "claim_variant_volume_floor": 20,
    "claim_ratio_probation_threshold": 0.25,
    "claim_ratio_suspension_threshold": 0.40,
    "probation_claim_share": 0.8,
    "audit_sample_pct": 0.2,
    "audit_sample_min_per_run": 1,
    "audit_fail_suspension_count": 2,
    "doc_retention_years": 7,
    "required_doc_types": [
        "TITLE_HISTORY_REPORT",
        "INSPECTION_WORKSHEET",
        "RECONDITIONING_INVOICE",
        "CUSTOMER_DISCLOSURE",
    ],
    "listing_required_disclosure_fields": [
        "CERTIFIED_BADGE",
        "WARRANTY_END_DATE",
        "INSPECTION_DATE",
        "CERTIFICATION_NUMBER",
    ],
    "listing_removal_sla_hours": 48,
    "inspection_slot_minutes": 120,
    "technician_buffer_minutes": 30,
}

CONFIG_FIELDS = list(CONFIG_DEFAULTS.keys())


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._seq = itertools.count(1)
        self.dealers = {}
        self.technicians = {}
        self.vehicles = {}
        self.templates = {}
        self.checklist_items = {}
        self.inspections = {}
        self.inspection_results = {}
        self.recon_items = {}
        self.certifications = {}
        self.documents = {}
        self.audit_samples = {}
        self.claims = {}
        self.listings = {}
        self.complaints = {}
        self.audit_run_count = 0
        self.program_config = None
        self._seed_config()

    def _seed_config(self):
        cfg = {
            "id": str(uuid.uuid4()),
            "created_at": self.clock,
            "updated_at": self.clock,
            "version": 1,
            "_seq": self.next_seq(),
        }
        for key, value in CONFIG_DEFAULTS.items():
            cfg[key] = _copy_value(value)
        self.program_config = cfg

    def next_seq(self):
        return next(self._seq)


def _copy_value(value):
    if isinstance(value, list):
        return [_copy_value(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _copy_value(v)) for k, v in value.items())
    return value


db = Store()


def new_id():
    return str(uuid.uuid4())


def cfg():
    return db.program_config


def now():
    return db.clock
