"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid

# One dict per entity type, keyed by id.
course_packages = {}
students = {}
guardian_consents = {}
enrollments = {}
instructors = {}
vehicles = {}
lessons = {}
no_show_strikes = {}
wallet_entries = {}
certificates = {}


def new_id():
    return str(uuid.uuid4())
