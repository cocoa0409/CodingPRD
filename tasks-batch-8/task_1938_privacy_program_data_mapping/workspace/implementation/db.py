"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

retention_policies = {}
data_elements = {}
data_systems = {}
notices = {}
state_law_rules = {}
vendors = {}
contracts = {}
activities = {}
purposes = {}
assessments = {}
consumers = {}
rights_requests = {}
tasks = {}
transfers = {}
evaluations = {}

# Monotonic sequence used to break created_at ties for "latest evaluation".
evaluation_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())
