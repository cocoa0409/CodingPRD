"""In-memory data store. The store starts EMPTY on every boot — no seeding,
no preload, no persistence. All state is built through the API surface."""

import itertools

# Monotonic insertion sequence; ties created_at ordering when the logical
# clock does not advance between writes (PRD §2.3 sorts by created_at ASC).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


accounts = {}          # id -> BusinessAccount
recyclers = {}         # id -> Recycler
policies = {}          # id -> CompliancePolicy
manifests = {}         # id -> Manifest
items = {}             # id -> Item
sanitizations = {}     # id -> DataSanitization
listings = {}          # id -> ResaleListing
batches = {}           # id -> RecycleBatch
certificates = {}      # id -> Certificate
settlements = {}       # id -> Settlement
ledger_entries = {}    # id -> LedgerEntry
custody_events = {}    # id -> CustodyEvent
