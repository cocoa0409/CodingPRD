import uuid

from clock import clock
from response import iso_ms


class DB:
    """In-memory store. Starts empty on every boot; no seeding, no persistence."""

    def __init__(self):
        self.securities = {}        # Security
        self.model_portfolios = {}  # ModelPortfolio
        self.accounts = {}          # Account
        self.questionnaires = {}    # RiskQuestionnaire
        self.tax_lots = {}          # TaxLot
        self.harvest_events = {}    # HarvestEvent
        self.rebalance_events = {}  # RebalanceEvent
        self.tax_forms = {}         # TaxForm1099B
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_common(with_version=True):
    """System-managed common fields.

    created_at/updated_at carry millisecond precision (PRD §2.4). version starts
    at 1 and increments on every mutation. RiskQuestionnaire is the sole entity
    with with_version=False — it carries only id + created_at (PRD §2.4).
    """
    now = clock.now()
    fields = {
        "id": db.new_id(),
        "created_at": iso_ms(now),
        "_created_dt": now,             # internal: stable creation instant for sorting
        "_created_seq": db.next_seq(),  # internal: monotonic creation order tie-break
    }
    if with_version:
        fields["updated_at"] = iso_ms(now)
        fields["version"] = 1
    return fields


def touch(entity):
    """Refresh updated_at and bump version by one on a mutation."""
    entity["updated_at"] = iso_ms(clock.now())
    entity["version"] = entity.get("version", 1) + 1
