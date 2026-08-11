"""In-memory data store. Plain dicts keyed by id; module-level state only.

Nothing here is seeded: the store starts empty on every boot and all entities
are constructed through the declared API surface.
"""
from __future__ import annotations

captives = {}
filings = {}
programs = {}
frontings = {}
collaterals = {}
units = {}
allocations = {}
claims = {}
tpas = {}
reserves = {}
statements = {}
meetings = {}
tax_positions = {}
audit_logs = {}

# claim_number sequence: {"CLM-YYYYMMDD": last NNNN}
claim_seq = {}
