"""In-memory data store. Starts empty on every boot."""
import secrets
import uuid


# Each table is keyed by entity id (uuid string).
employers = {}
employees = {}
providers = {}
leave_cases = {}
certifications = {}
intervals = {}
ledgers = {}
notices = {}


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    # alpha-numeric tail (20 chars) prefixed with "req_"
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    tail = "".join(secrets.choice(alphabet) for _ in range(20))
    return "req_" + tail


def reset():
    """For sanity; not invoked at startup."""
    employers.clear()
    employees.clear()
    providers.clear()
    leave_cases.clear()
    certifications.clear()
    intervals.clear()
    ledgers.clear()
    notices.clear()
