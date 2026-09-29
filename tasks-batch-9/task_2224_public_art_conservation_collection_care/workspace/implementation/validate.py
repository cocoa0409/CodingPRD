"""Request body / query-string validation (PRD 2.8 step 4, PRD 2.3)."""

from flask import request

from db import parse_date, parse_instant
from errors import ApiError

# ---------------------------------------------------------------------------
# enumerations
# ---------------------------------------------------------------------------
EXPOSURE_CLASSES = ("COASTAL", "URBAN", "PARK", "INTERIOR")
MATERIAL_CLASSES = ("BRONZE", "PAINTED_STEEL", "STONE", "MURAL_COATING")
SIGNIFICANCE_TIERS = ("LANDMARK", "SIGNIFICANT", "STANDARD")
CUSTODY_STATUSES = ("ON_VIEW", "IN_STORAGE", "IN_TREATMENT", "DEACCESSIONED", "DESTROYED")
CONSERVATION_STATUSES = ("MONITORED", "TREATMENT_REQUIRED", "TREATMENT_IN_PROGRESS", "STABILIZED")
PRIORITY_BASES = ("NONE", "SINGLE_ASSESSMENT", "CYCLE_COHORT")
MORAL_RIGHTS_STATUSES = ("ACTIVE", "WAIVED", "EXPIRED")
PROTOCOL_METHODS = ("WASH", "WAX", "GRAFFITI_REMOVAL", "COATING_RENEWAL", "INSPECTION")
SOLVENT_CLASSES = ("NONE", "MILD", "AGGRESSIVE")
VISIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
ABORT_REASONS = ("NONE", "SUPERSEDED_BY_TREATMENT", "ARTWORK_DEACCESSIONED")
ASSESSMENT_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "FINALIZED", "SUPERSEDED")
RECOMMENDATIONS = ("NONE", "ROUTINE", "PRIORITY", "URGENT")
ACCREDITATIONS = ("AIC_PA", "AIC_ASSOCIATE", "NONE")
CONSERVATOR_STATUSES = ("ACTIVE", "SUSPENDED")
TREATMENT_SCOPES = ("STABILIZATION", "SURFACE", "COATING", "STRUCTURAL", "GRAFFITI")
PROPOSAL_STATUSES = (
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "IN_EXECUTION",
    "COMPLETED", "REJECTED", "WITHDRAWN",
)
WITHDRAW_REASONS = ("NONE", "PROPOSAL_SUPERSEDED", "ARTWORK_DEACCESSIONED")
CONSULTATION_SUBJECTS = ("TREATMENT", "RELOCATION", "REMOVAL", "DEACCESSION")
CONSULTATION_STATUSES = ("PENDING", "CONCURRED", "OBJECTED", "LAPSED", "WAIVED")
CONSULTATION_RESPONSES = ("CONCUR", "OBJECT")
NOTICE_ACTION_TYPES = ("ALTERATION", "RELOCATION", "REMOVAL", "DESTRUCTION")
NOTICE_STATUSES = ("SENT", "ACKNOWLEDGED", "WAIT_ELAPSED", "CONSUMED", "VOID")
DEACCESSION_CRITERIA = (
    "DETERIORATION_BEYOND_REPAIR", "PUBLIC_SAFETY_HAZARD", "SITE_REDEVELOPMENT",
    "DUPLICATE_HOLDING", "LACK_OF_RELEVANCE",
)
DISPOSITIONS = ("SALE", "TRANSFER", "DESTRUCTION", "RETURN_TO_ARTIST")
CASE_STATUSES = ("INITIATED", "PUBLIC_COMMENT", "BOARD_REVIEW", "APPROVED", "DENIED", "EXECUTED")
BALLOTS = ("APPROVE", "DENY", "ABSTAIN", "RECUSE")
POOL_TYPES = ("ENDOWMENT", "PERCENT_FOR_ART")
ALLOCATION_PURPOSES = ("TREATMENT", "MAINTENANCE")
ALLOCATION_STATUSES = ("RESERVED", "COMMITTED", "DISBURSED", "RELEASED")
RELEASE_REASONS = (
    "NONE", "VISIT_ABORTED", "PROPOSAL_WITHDRAWN", "PROPOSAL_REJECTED", "MANUAL_RELEASE",
)
INCIDENT_TYPES = ("GRAFFITI", "VANDALISM", "VEHICLE_IMPACT", "WEATHER", "THEFT")
DAMAGE_STATUSES = ("REPORTED", "TRIAGED", "RESOLVED")
TRIAGE_CLASSES = ("NONE", "ROUTINE_MAINTENANCE", "CONSERVATOR_TREATMENT", "TOTAL_LOSS")
TRIAGE_CHOICES = ("ROUTINE_MAINTENANCE", "CONSERVATOR_TREATMENT", "TOTAL_LOSS")
CLAIM_STATUSES = ("NONE", "FILED", "SETTLED", "DENIED")
CLAIM_BASES = ("ACV", "RESTORATION")
CLAIM_OUTCOMES = ("SETTLE", "DENY")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------------------
# field specs
# ---------------------------------------------------------------------------

def field(kind, required=False, default=None, enum=None, minimum=None, maximum=None):
    return {
        "kind": kind,
        "required": required,
        "default": default,
        "enum": enum,
        "minimum": minimum,
        "maximum": maximum,
    }


def _coerce(name, value, spec):
    kind = spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % name)
        if spec["required"] and not value.strip():
            bad("Field '%s' must not be blank." % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field '%s' must be an integer." % name)
        if spec["minimum"] is not None and value < spec["minimum"]:
            bad("Field '%s' must be >= %s." % (name, spec["minimum"]))
        if spec["maximum"] is not None and value > spec["maximum"]:
            bad("Field '%s' must be <= %s." % (name, spec["maximum"]))
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad("Field '%s' must be a number." % name)
        if spec["minimum"] is not None and value < spec["minimum"]:
            bad("Field '%s' must be >= %s." % (name, spec["minimum"]))
        if spec["maximum"] is not None and value > spec["maximum"]:
            bad("Field '%s' must be <= %s." % (name, spec["maximum"]))
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["enum"]:
            bad("Field '%s' must be one of %s." % (name, ", ".join(spec["enum"])))
        return value
    if kind == "enum_array":
        if not isinstance(value, list) or len(value) == 0:
            bad("Field '%s' must be a non-empty array." % name)
        for item in value:
            if not isinstance(item, str) or item not in spec["enum"]:
                bad("Field '%s' members must be drawn from %s." % (name, ", ".join(spec["enum"])))
        return list(value)
    if kind == "date":
        try:
            parse_date(value)
        except Exception:
            bad("Field '%s' must be an ISO 8601 date." % name)
        return value
    if kind == "datetime":
        try:
            parse_instant(value)
        except Exception:
            bad("Field '%s' must be an ISO 8601 instant." % name)
        return value
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            bad("Field '%s' must be an identifier string." % name)
        return value
    bad("Field '%s' is not understood." % name)


def read_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        import json

        parsed = json.loads(raw)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def parse_input(spec):
    """Validate the request body against a field spec, returning coerced values."""
    body = read_body()
    for key in body.keys():
        if key not in spec:
            bad("Unknown field '%s'." % key)
    out = {}
    for name, fspec in spec.items():
        present = name in body
        value = body.get(name)
        if not present or value is None:
            if fspec["required"]:
                bad("Field '%s' is required." % name)
            out[name] = fspec["default"]
            continue
        out[name] = _coerce(name, value, fspec)
    return out


# ---------------------------------------------------------------------------
# query string helpers
# ---------------------------------------------------------------------------

def paging():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except Exception:
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except Exception:
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def _query_bool(name, raw):
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    bad("Query parameter '%s' must be true or false." % name)


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except Exception:
        bad("Query parameter '%s' must be an integer." % name)


def apply_filters(records, specs):
    """specs: sequence of (query_param, field_name, kind)."""
    out = list(records)
    for param, fname, kind in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            wanted = _query_bool(param, raw)
        elif kind == "int":
            wanted = _query_int(param, raw)
        elif kind == "member":
            out = [r for r in out if raw in (r.get(fname) or [])]
            continue
        else:
            wanted = raw
        out = [r for r in out if r.get(fname) == wanted]
    return out
