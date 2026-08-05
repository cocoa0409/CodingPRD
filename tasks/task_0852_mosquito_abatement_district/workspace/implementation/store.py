"""In-memory data store. Starts EMPTY on every boot — nothing is seeded."""
import itertools

from common import ApiError, logical_now, new_id

_SEQ = itertools.count(1)

SERVICE_AREAS = {}
SENSITIVE_SITES = {}
TRAP_SITES = {}
TRAP_COLLECTIONS = {}
LAB_POOLS = {}
LARVAL_INSPECTIONS = {}
WEATHER_OBSERVATIONS = {}
RISK_ASSESSMENTS = {}
PESTICIDE_PRODUCTS = {}
APPLICATORS = {}
TREATMENT_PLANS = {}
TREATMENT_ROUTES = {}
NOTIFICATIONS = {}
SERVICE_REQUESTS = {}

_NOT_FOUND = {
    "ServiceArea": ("ERR_SERVICE_AREA_NOT_FOUND", 404),
    "SensitiveSite": ("ERR_SENSITIVE_SITE_NOT_FOUND", 404),
    "TrapSite": ("ERR_TRAP_SITE_NOT_FOUND", 404),
    "TrapCollection": ("ERR_TRAP_COLLECTION_NOT_FOUND", 404),
    "LabPool": ("ERR_LAB_POOL_NOT_FOUND", 404),
    "RiskAssessment": ("ERR_RISK_ASSESSMENT_NOT_FOUND", 404),
    "PesticideProduct": ("ERR_PRODUCT_NOT_FOUND", 404),
    "Applicator": ("ERR_APPLICATOR_NOT_FOUND", 404),
    "TreatmentPlan": ("ERR_TREATMENT_PLAN_NOT_FOUND", 404),
    "TreatmentRoute": ("ERR_TREATMENT_ROUTE_NOT_FOUND", 404),
    "Notification": ("ERR_NOTIFICATION_NOT_FOUND", 404),
    "ServiceRequest": ("ERR_SERVICE_REQUEST_NOT_FOUND", 404),
}

_TABLES = {
    "ServiceArea": SERVICE_AREAS,
    "SensitiveSite": SENSITIVE_SITES,
    "TrapSite": TRAP_SITES,
    "TrapCollection": TRAP_COLLECTIONS,
    "LabPool": LAB_POOLS,
    "RiskAssessment": RISK_ASSESSMENTS,
    "PesticideProduct": PESTICIDE_PRODUCTS,
    "Applicator": APPLICATORS,
    "TreatmentPlan": TREATMENT_PLANS,
    "TreatmentRoute": TREATMENT_ROUTES,
    "Notification": NOTIFICATIONS,
    "ServiceRequest": SERVICE_REQUESTS,
}


def not_found(kind):
    error_id, status = _NOT_FOUND[kind]
    return ApiError(error_id, status, "%s not found." % kind)


def fetch(kind, resource_id):
    """Resolve an id, raising the kind-specific 404 when it does not resolve."""
    table = _TABLES[kind]
    if not isinstance(resource_id, str) or resource_id not in table:
        raise not_found(kind)
    return table[resource_id]


def maybe(kind, resource_id):
    table = _TABLES[kind]
    if not isinstance(resource_id, str):
        return None
    return table.get(resource_id)


def new_record(with_version=True):
    """Common system fields. created_at/updated_at read the logical clock."""
    now = logical_now()
    record = {
        "id": new_id(),
        "created_at": now,
        "_seq": next(_SEQ),
    }
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation."""
    if "version" in record:
        record["updated_at"] = logical_now()
        record["version"] = record["version"] + 1
    return record


def ordered(rows):
    """List ordering: created_at ascending, stable by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
