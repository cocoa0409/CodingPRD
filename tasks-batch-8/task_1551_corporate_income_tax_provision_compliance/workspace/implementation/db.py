"""In-memory data store (SCAFFOLD §1.1 entities).

The store starts completely empty on every boot — no seeding, no preloaded
reference data. Every record any test needs is constructed through the declared
API surface. Dicts preserve insertion order, which doubles as the
created_at-ascending list order (PRD §2.3).
"""
from util import new_id, now_ts


class Store:
    def __init__(self):
        self.tax_years = {}            # id -> TaxYear
        self.jurisdictions = {}        # id -> Jurisdiction
        self.differences = {}          # id -> BookTaxDifference
        self.deferred_items = {}       # id -> DeferredTaxItem
        self.valuation_allowances = {} # id -> ValuationAllowance
        self.utps = {}                 # id -> UncertainTaxPosition
        self.payments = {}             # id -> EstimatedPayment
        self.filings = {}              # id -> Filing
        self.notices = {}              # id -> TaxNotice
        self.audits = {}               # id -> AuditCase


db = Store()


def new_record(fields: dict) -> dict:
    """Mint the common system fields (PRD §2.4): id, created_at, updated_at, version=1."""
    rec = {"id": new_id()}
    rec.update(fields)
    ts = now_ts()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    return rec


def touch(rec: dict):
    """Generic-entity mutation: refresh updated_at and bump version."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def touch_year(year: dict):
    """TaxYear timestamp refresh WITHOUT a version bump.

    TaxYear.version is load-bearing for optimistic concurrency (PRD §2.8) and
    increments exactly where the state-machine side effects say so — never as a
    side effect of derived-field recomputation (e.g. a difference lock refreshes
    deferred_expense_cents but does not advance the OCC anchor).
    """
    year["updated_at"] = now_ts()


def bump_year(year: dict):
    """Declared 'Increments TaxYear.version by 1' side effect."""
    year["updated_at"] = now_ts()
    year["version"] += 1
