"""In-memory data store. Every dict starts empty on process boot; the test
harness relaunches the server before every test, so no state carries over.
NO seeding, preloading, or hardcoded entities anywhere."""
import uuid

# One dict per entity type, keyed by id.
licenses = {}
plant_batches = {}
harvests = {}
packages = {}
lab_results = {}
manifests = {}
manifest_lines = {}
customers = {}
sales = {}
sale_lines = {}
reconciliation_counts = {}
waste_events = {}


def new_id():
    return str(uuid.uuid4())
