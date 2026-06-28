"""In-memory data store. All state is module-level dicts keyed by id.

The store starts EMPTY on every boot. Nothing is seeded here. Tests build all
state via the declared API surface.
"""

modalities = {}
therapists = {}
certifications = {}
tables = {}
clients = {}
intakes = {}
consent_records = {}
membership_plans = {}
packages = {}
ledger_entries = {}
commission_tiers = {}
appointments = {}
soap_notes = {}
superbills = {}

# Monotonic counter to provide a stable secondary sort by creation order
# (created_at timestamps can be identical because they read the logical clock).
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def all_stores():
    return [
        modalities, therapists, certifications, tables, clients, intakes,
        consent_records, membership_plans, packages, ledger_entries,
        commission_tiers, appointments, soap_notes, superbills,
    ]
