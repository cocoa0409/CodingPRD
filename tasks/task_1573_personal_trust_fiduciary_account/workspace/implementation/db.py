"""In-memory data store. Starts EMPTY on every boot — no seeding ever."""

import itertools
import uuid

trusts = {}
documents = {}
beneficiaries = {}
committee_members = {}
distribution_requests = {}
votes = {}
policies = {}
holdings = {}
reviews = {}
ledger_entries = {}
fee_assessments = {}
statements = {}
filings = {}
termination_cases = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)
