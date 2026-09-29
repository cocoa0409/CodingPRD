"""The single fixed ladder of PRD section 2.6.

Rung 1 authentication, rung 2 authorization / identity / segregation of
duties, rung 3 existence resolved left to right along the URL and then over
body identifiers in the declared family order, rung 4 project scope, rung 5
request shape then pagination then uniqueness, rung 6 optimistic concurrency,
rung 7 posture gates then state preconditions then cross-record readiness,
rung 8 the business rules in their declared domain order.

Route modules call these helpers in exactly that order; the first failure
raises and no later rung is evaluated.
"""

from datetime import datetime
from decimal import Decimal

from flask import request

import clock
import store
from errors import ApiError
from rounding import D

ROLES = [
    "ConverterSponsor", "LicensedEngineer", "PeerReviewEngineer",
    "StateRegulator", "EscrowAgent", "LenderUnderwriter", "PlatformAdmin",
    "TenantOccupant", "Purchaser",
]

SECTION_CODES = [
    "UNIT_BOUNDARIES", "COMMON_ELEMENTS", "PERCENTAGE_INTERESTS", "BUDGET",
    "RESERVES", "ENGINEERING_CONDITION", "TENANT_RIGHTS", "WARRANTY",
    "RESCISSION_RIGHTS",
]


# --- rung 1: authentication ------------------------------------------------

def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if not role or not str(role).strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    return user_id, role


# --- rung 2: authorization, identity binding, segregation of duties --------

def authorize(allowed_roles):
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_identity(user_id, role, entity_role, path_id):
    """An entity-backed role must be acting on its own record.  The check is
    made against the raw path identifier, so it precedes rung 3."""
    if role == entity_role and user_id != path_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")


def require_separation(user_id, submitted_by_user_id):
    if submitted_by_user_id is not None and user_id == submitted_by_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


# --- rung 3: existence, in the declared family order ----------------------

def _find(store_map, record_id, error_id):
    if not isinstance(record_id, str) or not record_id:
        raise ApiError(error_id)
    rec = store_map.get(record_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_project(project_id):
    return _find(store.projects, project_id, "ERR_PROJECT_NOT_FOUND")


def get_report(report_id):
    return _find(store.engineering_reports, report_id,
                 "ERR_ENGINEERING_ARTIFACT_NOT_FOUND")


def get_component(component_id):
    return _find(store.major_components, component_id,
                 "ERR_ENGINEERING_ARTIFACT_NOT_FOUND")


def get_assessment(assessment_id):
    return _find(store.suitability_assessments, assessment_id,
                 "ERR_ENGINEERING_ARTIFACT_NOT_FOUND")


def get_package(package_id):
    return _find(store.declaration_packages, package_id,
                 "ERR_DECLARATION_ARTIFACT_NOT_FOUND")


def get_unit(unit_id):
    return _find(store.units, unit_id, "ERR_DECLARATION_ARTIFACT_NOT_FOUND")


def get_statement(statement_id):
    return _find(store.public_offering_statements, statement_id,
                 "ERR_DISCLOSURE_ARTIFACT_NOT_FOUND")


def get_section(statement_id, section_code):
    if section_code not in SECTION_CODES:
        raise ApiError("ERR_DISCLOSURE_ARTIFACT_NOT_FOUND")
    for section in store.statement_sections(statement_id):
        if section["section_code"] == section_code:
            return section
    raise ApiError("ERR_DISCLOSURE_ARTIFACT_NOT_FOUND")


def get_household(household_id):
    return _find(store.tenant_households, household_id, "ERR_TENANT_NOT_FOUND")


def get_study(study_id):
    return _find(store.reserve_studies, study_id,
                 "ERR_FINANCIAL_ARTIFACT_NOT_FOUND")


def get_budget(budget_id):
    return _find(store.initial_budgets, budget_id,
                 "ERR_FINANCIAL_ARTIFACT_NOT_FOUND")


def get_agreement(agreement_id):
    return _find(store.purchase_agreements, agreement_id,
                 "ERR_SALES_ARTIFACT_NOT_FOUND")


def get_batch(batch_id):
    return _find(store.closing_batches, batch_id,
                 "ERR_SALES_ARTIFACT_NOT_FOUND")


def get_claim(claim_id):
    return _find(store.warranty_claims, claim_id, "ERR_CLAIM_NOT_FOUND")


def body_ref(body, field, getter):
    """Resolve a body identifier on rung 3.  A missing or non-string value is
    left to rung 5's shape check, which reports ERR_INVALID_REQUEST."""
    if not isinstance(body, dict):
        return None
    value = body.get(field)
    if not isinstance(value, str) or not value:
        return None
    return getter(value)


# --- rung 4: project scope -------------------------------------------------

def require_scope(project_id, *records):
    for rec in records:
        if rec is None:
            continue
        if rec.get("conversion_project_id") != project_id:
            raise ApiError("ERR_PROJECT_SCOPE_MISMATCH")


# --- rung 5: request shape, pagination, uniqueness -------------------------

MISSING = object()


def field(name, kind, required=True, default=MISSING, minimum=None,
          maximum=None, max_len=None, values=None, nullable=False):
    return {"name": name, "kind": kind, "required": required,
            "default": default, "minimum": minimum, "maximum": maximum,
            "max_len": max_len, "values": values, "nullable": nullable}


def _bad_request():
    raise ApiError("ERR_INVALID_REQUEST")


def raw_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        _bad_request()
    if not isinstance(body, dict):
        _bad_request()
    return body


def _coerce(spec, value):
    kind = spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad_request()
        if not value.strip() and spec["minimum"] != 0:
            _bad_request()
        if spec["max_len"] is not None and len(value) > spec["max_len"]:
            _bad_request()
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad_request()
        if spec["minimum"] is not None and value < spec["minimum"]:
            _bad_request()
        if spec["maximum"] is not None and value > spec["maximum"]:
            _bad_request()
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad_request()
        parsed = D(str(value))
        if spec["minimum"] is not None and parsed < D(str(spec["minimum"])):
            _bad_request()
        if spec["maximum"] is not None and parsed > D(str(spec["maximum"])):
            _bad_request()
        return parsed
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad_request()
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in spec["values"]:
            _bad_request()
        return value
    if kind == "datetime":
        if not isinstance(value, str):
            _bad_request()
        parsed = clock.parse_instant(value)
        if parsed is None:
            _bad_request()
        return parsed
    if kind == "id":
        if not isinstance(value, str) or not value:
            _bad_request()
        return value
    raise AssertionError(kind)


def parse(specs):
    """Validate the request body against a field specification.  Required
    fields, types, enum membership, integer ranges and ISO 8601 datetimes are
    all rung 5 concerns reported as ERR_INVALID_REQUEST."""
    body = raw_body()
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in body or (body[name] is None and spec["nullable"]):
            if spec["required"] and name not in body:
                _bad_request()
            if spec["default"] is not MISSING:
                out[name] = spec["default"]
            elif name in body:
                out[name] = None
            continue
        out[name] = _coerce(spec, body[name])
    return out


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        try:
            limit_value = int(str(limit), 10)
        except ValueError:
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit_value < 1 or limit_value > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(str(offset), 10)
        except ValueError:
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset_value < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit_value, offset_value


def require_unique(records, **pairs):
    for rec in records:
        if all(rec.get(key) == value for key, value in pairs.items()):
            raise ApiError("ERR_DUPLICATE_KEY")


# --- rung 6: optimistic concurrency ---------------------------------------

def require_version(supplied, rec, error_id):
    if supplied != rec["version"]:
        raise ApiError(error_id)


# --- rung 7: posture gates, state preconditions, readiness gates ----------

def gate_not_frozen(project):
    if project["posture"] == "FROZEN":
        raise ApiError("ERR_PROJECT_FROZEN")


def gate_posture_open(project):
    if project["posture"] != "OPEN":
        raise ApiError("ERR_PROJECT_RESTRICTED")


def require_state(rec, state_field, allowed):
    if rec.get(state_field) not in allowed:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_bool(name):
    value = filter_value(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def matches(rec, **filters):
    for key, value in filters.items():
        if value is None:
            continue
        if rec.get(key) != value:
            return False
    return True
