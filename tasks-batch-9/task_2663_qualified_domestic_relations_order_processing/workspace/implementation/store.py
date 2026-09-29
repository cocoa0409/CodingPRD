"""In-memory store (PRD 2.4).

The store starts EMPTY on every boot; nothing is seeded, preloaded or hardcoded.
Every row is a plain dict. Keys beginning with an underscore are private
bookkeeping and are stripped before a row is serialised.
"""
import uuid

from timeutil import fmt_domain_instant, fmt_instant, parse_instant

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# The eleven resource types that carry updated_at + version (PRD 2.4).
VERSIONED = {
    "Plan", "Participant", "PlanAccount", "MoneySource", "QdroCase", "DraftOrder",
    "DeficiencyNotice", "SegregationHold", "AttorneyAuthorization",
    "AlternatePayeeAccount", "Distribution",
}


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.plans = {}
        self.participants = {}
        self.plan_accounts = {}
        self.money_sources = {}
        self.valuation_snapshots = {}
        self.qdro_cases = {}
        self.draft_orders = {}
        self.deficiency_notices = {}
        self.segregation_holds = {}
        self.attorney_authorizations = {}
        self.ap_accounts = {}
        self.distributions = {}
        self.tax_reports = {}
        self.communications = {}
        self._seq = 0
        self.clock_raw = DEFAULT_CLOCK
        self.clock_dt = parse_instant(DEFAULT_CLOCK)

    # --- logical clock ------------------------------------------------------
    def now(self):
        """The logical clock as an aware UTC datetime. Never the wall clock."""
        return self.clock_dt

    def now_iso(self):
        """A domain stamp taken from the logical clock (PRD 2.4)."""
        return fmt_domain_instant(self.clock_dt)

    def row_stamp(self):
        """created_at / updated_at: three fractional digits (PRD 2.4)."""
        return fmt_instant(self.clock_dt)

    def today(self):
        return self.clock_dt.date()

    def set_clock(self, raw, dt):
        previous = self.clock_raw
        self.clock_raw = raw
        self.clock_dt = dt
        return previous

    # --- identity / ordering ------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    # --- row construction ---------------------------------------------------
    def new_row(self, kind, fields):
        row = {"id": self.new_id()}
        row.update(fields)
        row["created_at"] = self.row_stamp()
        if kind in VERSIONED:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_kind"] = kind
        row["_seq"] = self.next_seq()
        return row

    def touch(self, row):
        """Refresh updated_at and bump version by exactly 1 (PRD 2.10)."""
        row["updated_at"] = self.row_stamp()
        if "version" in row:
            row["version"] = row["version"] + 1
        return row


db = Store()


def public(row):
    """Strip private bookkeeping keys before serialisation."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


def order_by(rows, *keys):
    """Sort rows by the given keys, always tie-breaking on insertion order.

    Tie-breaking on `_seq` reproduces `created_at ascending` while remaining
    stable when a whole cascade shares one logical-clock instant.
    """
    def sort_key(row):
        out = []
        for key in keys:
            value = row.get(key)
            out.append((value is None, value if value is not None else ""))
        out.append((False, row["_seq"]))
        return tuple(out)

    return sorted(rows, key=sort_key)


def by_created(rows):
    return order_by(rows, "created_at")
