"""Endpoint registry and rungs 1-12 of the validation ladder (PRD 2.9).

Rungs are evaluated in strictly ascending order and the first failure decides
the response.  Rungs 1-12 are uniform across the surface and live here; rungs
13-42 live in the handlers, always in ascending rung order -- which is exactly
what every one of the nine declared gate-precedence blocks of PRD 2.9.1 spells
out, so no block needs a special case.
"""

from flask import request

import envelope
import lookup
from constants import ROLES
from errors import ApiError
from store import DB
from validation import Body

ROUTES = []

# rung 4..11: the {id} segment directly under these path prefixes
PATH_RESOURCES = (
    ("/clients/", "clients", "ERR_CLIENT_NOT_FOUND"),
    ("/legal-entities/", "legal_entities", "ERR_LEGAL_ENTITY_NOT_FOUND"),
    ("/registrations/", "registrations", "ERR_REGISTRATION_NOT_FOUND"),
    ("/compliance-obligations/", "obligations", "ERR_OBLIGATION_NOT_FOUND"),
    ("/filings/", "filings", "ERR_FILING_NOT_FOUND"),
    ("/payments/", "payments", "ERR_PAYMENT_NOT_FOUND"),
    ("/sop-documents/", "sop_documents", "ERR_SOP_NOT_FOUND"),
    ("/beneficial-owners/", "beneficial_owners", "ERR_RECORD_NOT_FOUND"),
    ("/agent-appointments/", "appointments", "ERR_RECORD_NOT_FOUND"),
    ("/boi-reports/", "boi_reports", "ERR_RECORD_NOT_FOUND"),
    ("/name-clearances/", "name_clearances", "ERR_RECORD_NOT_FOUND"),
    ("/reinstatement-cases/", "reinstatement_cases", "ERR_RECORD_NOT_FOUND"),
)

# rung 11, second half: body-supplied references
BODY_REFERENCES = (
    ("name_clearance_id", "name_clearances"),
    ("good_standing_certificate_id", "certificates"),
    ("reinstatement_case_id", "reinstatement_cases"),
    ("target_filing_id", "filings"),
)


class EndpointSpec:
    def __init__(self, method, path, roles, success_code, handler):
        self.method = method
        self.path = path
        self.roles = tuple(roles)
        self.success_code = success_code
        self.handler = handler
        self.resource = None
        self.not_found = None
        for prefix, collection, error_id in PATH_RESOURCES:
            if path.startswith(prefix):
                self.resource = collection
                self.not_found = error_id
                break

    @property
    def flask_rule(self):
        return self.path.replace("{id}", "<string:resource_id>")


class Context:
    """Everything a handler needs after rungs 1-12 have passed."""

    def __init__(self, spec, role, user_id, row, body, raw_payload):
        self.spec = spec
        self.role = role
        self.user_id = user_id
        self.row = row
        self.body = body
        self.raw_payload = raw_payload
        self.refs = {}

    @property
    def is_client_contact(self):
        return self.role == "ClientContact"


def endpoint(method, path, roles, success_code=200):
    def decorator(fn):
        ROUTES.append(EndpointSpec(method, path, roles, success_code, fn))
        return fn

    return decorator


def _read_payload():
    """Returns (payload_dict, malformed_flag)."""
    raw = request.get_data(cache=True)
    if not raw:
        return {}, False
    payload = request.get_json(silent=True)
    if payload is None:
        return {}, True
    if not isinstance(payload, dict):
        return {}, True
    return payload, False


def build_context(spec, resource_id):
    # ---- rung 1: both headers present and non-blank -----------------------
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or not role.strip() or user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = role.strip()
    user_id = user_id.strip()

    # ---- rung 2: the role is one of the five declared roles ---------------
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")

    # ---- rung 3: the role is permitted on this endpoint -------------------
    if role not in spec.roles:
        raise ApiError("ERR_UNAUTHORIZED")

    # ---- rungs 4..11 (path segment) ---------------------------------------
    row = None
    if spec.resource is not None:
        collection = getattr(DB, spec.resource)
        row = collection.get(resource_id)
        if row is None:
            raise ApiError(spec.not_found)

    payload, malformed = _read_payload()

    # ---- rung 11 (body-supplied references) -------------------------------
    refs = {}
    if not malformed:
        for field, collection_name in BODY_REFERENCES:
            value = payload.get(field)
            if value is None:
                continue
            collection = getattr(DB, collection_name)
            found = collection.get(value) if isinstance(value, str) else None
            if found is None:
                raise ApiError("ERR_RECORD_NOT_FOUND")
            refs[field] = found

    # ---- rung 12: cross-client access -------------------------------------
    if role == "ClientContact" and "ClientContact" in spec.roles and row is not None:
        owner = lookup.owning_client_id(spec.resource, row)
        if owner != user_id:
            raise ApiError("ERR_CROSS_CLIENT_ACCESS")

    body = Body({} if malformed else payload)
    context = Context(spec, role, user_id, row, body, payload)
    context.refs = refs
    context.malformed_body = malformed
    return context


def make_view(spec):
    def view(resource_id=None):
        from store import lock

        with lock():
            context = build_context(spec, resource_id)
            if getattr(context, "malformed_body", False):
                raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
            return spec.handler(context)

    view.__name__ = "view_%d" % len(ROUTES)
    return view


# ---------------------------------------------------------------------------
# query-string helpers (rung 13 covers limit / offset)
# ---------------------------------------------------------------------------
def page_params():
    limit = envelope.PAGE_LIMIT_DEFAULT
    offset = envelope.PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < envelope.PAGE_LIMIT_MIN or limit > envelope.PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def query_filter(name):
    """Filters are exact-match narrowing; an unrecognised value simply matches
    nothing (PRD 2.3).  Never routed to ERR_INVALID_ENUM."""
    value = request.args.get(name)
    if value is None:
        return None
    return value
