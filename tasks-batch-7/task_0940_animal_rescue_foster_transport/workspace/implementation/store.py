"""In-memory storage.

HARD RULE: the store starts EMPTY on every boot.  Nothing here seeds, preloads,
registers or hardcodes any entity.  Every row any test needs is constructed by
the test itself through the declared API surface, and per-test-server isolation
wipes every byte simply by restarting the process.
"""

import clock
import ids

TABLES = (
    "Organization",
    "Person",
    "Animal",
    "Litter",
    "IntakeRecord",
    "HoldRecord",
    "FosterHome",
    "FosterApplication",
    "FosterPlacement",
    "MedicalRecord",
    "HealthCertificate",
    "TransportRun",
    "TransportLeg",
    "ManifestEntry",
    "AdoptionApplication",
    "Adoption",
    "OutcomeRecord",
    "Contribution",
    "PartnerCommitment",
)


class Store(object):
    def __init__(self):
        self.tables = {name: {} for name in TABLES}

    # -- table access ------------------------------------------------------
    def table(self, entity):
        return self.tables[entity]

    def get(self, entity, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[entity].get(row_id)

    def all(self, entity):
        return list(self.tables[entity].values())

    def where(self, entity, **kw):
        out = []
        for row in self.tables[entity].values():
            if all(row.get(k) == v for k, v in kw.items()):
                out.append(row)
        return out

    def insert(self, entity, fields):
        """Create a row with the four common fields (PRD 2.4)."""
        row = dict(fields)
        row["id"] = ids.new_id()
        row["_entity"] = entity
        stamp = clock.canonical(clock.now())          # (a) server-minted
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["_created_dt"] = clock.now()
        row["version"] = 1
        self.tables[entity][row["id"]] = row
        return row


DB = Store()


def touch(row):
    """PRD 2.4: `version` increases by exactly 1 on each mutation of that row,
    and `updated_at` is refreshed to the clock instant of the mutation whenever
    `version` moves."""
    row["version"] = row["version"] + 1
    row["updated_at"] = clock.canonical(clock.now())   # (a) server-minted
    return row


def order_key(row):
    """PRD 2.3: list results are ordered by `created_at` ascending.  Ids are
    monotonic, so the id tie-break resolves same-instant rows into creation
    order deterministically."""
    return (row["_created_dt"], row["id"])


def ordered(rows):
    return sorted(rows, key=order_key)
