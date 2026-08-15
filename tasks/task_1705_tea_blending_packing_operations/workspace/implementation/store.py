"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

suppliers = {}
leaf_lots = {}
grade_assessments = {}
residue_tests = {}
flavorings = {}
recipes = {}
batches = {}
allocations = {}
flavoring_applications = {}
packaging_lines = {}
production_runs = {}
contracts = {}
certificates = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
