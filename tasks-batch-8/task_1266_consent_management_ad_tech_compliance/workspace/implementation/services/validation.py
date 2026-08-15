"""Validation ladder (PRD §2.8 / SCAFFOLD Table 4) and shared payload helpers.

The ordered ladder — the FIRST failing rung determines the error returned:

  1.  Authentication      — X-User-ID / X-User-Role present, role recognized
                            -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2.  Authorization       — role permitted the operation
                            -> ERR_INSUFFICIENT_PERMISSIONS (403)
  2.5 Visitor ownership   — Visitor caller's X-User-ID == target visitor id
                            -> ERR_FORBIDDEN_OWNERSHIP (403)
  3.  Existence           — path/body referenced ids, left to right
                            -> ERR_*_NOT_FOUND (404)
  4.  Stale version       — publish OCC only -> ERR_STALE_PROPERTY_VERSION (412)
  5.  Posture gate        — property must be NORMAL -> ERR_PROPERTY_FROZEN (409)
  6.  Transition preconditions               -> ERR_*_INVALID_TRANSITION / ...
  7.  Age verification    -> ERR_AGE_UNVERIFIED (409)
  8.  Child protection    -> ERR_CHILD_CONSENT_FORBIDDEN (403)
  9.  Active policy       -> ERR_NO_ACTIVE_POLICY (409)
  10. Same-property linkage -> ERR_CROSS_PROPERTY_REFERENCE (409)
  10.5 Vendor approved    -> ERR_VENDOR_NOT_APPROVED (409)
  11. Coverage window     -> ERR_POLICY_OUTSIDE_COVERAGE_WINDOW (409)
  12. Scan cooldown       -> ERR_SCAN_WINDOW_CONFLICT (409)
  13. Policy window overlap -> ERR_POLICY_WINDOW_OVERLAP (409)
  14. Tag-rule uniqueness -> ERR_DUPLICATE_TAG_RULE (409)
  15. Consent-purpose uniqueness -> ERR_DUPLICATE_CONSENT_PURPOSE (409)
  16. Do-not-sell applicability -> ERR_DNS_NOT_APPLICABLE (409)
  17. Segregation of duties -> ERR_SEGREGATION_OF_DUTIES_VIOLATION (403)

Malformed payloads (missing required field, type mismatch, out-of-set enum)
are rejected with ERR_INVALID_REQUEST (400). Field presence/shape is validated
before body-referenced existence checks (an id must be present and well-formed
to be looked up); path-id existence is checked before body shape.
"""

from flask import request

from clock import parse_iso, get_now
from db import store, new_id, now_iso
from errors import ApiError, ERR_INVALID_REQUEST, ERR_PROPERTY_FROZEN

LADDER_PRIORITIES = (
    "auth",
    "authorization",
    "visitor_ownership",
    "existence",
    "stale_version",
    "posture_gate",
    "transition_preconditions",
    "age_verification",
    "child_protection",
    "active_policy",
    "same_property_linkage",
    "vendor_approved",
    "coverage_window",
    "scan_cooldown",
    "policy_window_overlap",
    "tag_rule_uniqueness",
    "consent_purpose_uniqueness",
    "dns_applicability",
    "segregation_of_duties",
)

_MISSING = object()


def not_found(entity_key, error_id):
    """Raise the resource-specific not-found error (ladder rung 3)."""
    raise ApiError(error_id, f"{entity_key} not found", 404)


def run_lazy_effects():
    """Evaluate lazy time-based effects (PRD §2.4) if the module is available.

    services.expiry is owned by another module set; when absent this is a
    no-op so that this half of the system still boots and serves.
    """
    try:
        from services.expiry import evaluate_time_based_effects
    except ImportError:
        return
    try:
        evaluate_time_based_effects()
    except Exception:
        pass


# --- Property posture ---------------------------------------------------------

def compute_posture(property_id):
    """Property posture: FROZEN while any of its sweeps is ESCALATED (§2.6)."""
    for sweep in store["regulatory_sweeps"].values():
        if sweep.get("property_id") == property_id and sweep.get("status") == "ESCALATED":
            return "FROZEN"
    return "NORMAL"


def check_frozen(property_id):
    """Ladder rung 5: the property must be NORMAL for frozen-gated mutations."""
    if compute_posture(property_id) == "FROZEN":
        raise ApiError(
            ERR_PROPERTY_FROZEN,
            "Property is FROZEN while a regulatory sweep is ESCALATED",
            409,
        )


# --- Policy helpers -----------------------------------------------------------

def active_policies_for(property_id, jurisdiction_code):
    """All ACTIVE policies of the property for the jurisdiction, creation order."""
    return [
        p
        for p in sorted(
            store["jurisdiction_policies"].values(), key=lambda e: e.get("created_at", "")
        )
        if p.get("property_id") == property_id
        and p.get("jurisdiction_code") == jurisdiction_code
        and p.get("status") == "ACTIVE"
    ]


def policy_window_contains(policy, moment):
    """Half-open [effective_from, effective_to) containment; None end = open."""
    start = parse_iso(policy["effective_from"])
    end_raw = policy.get("effective_to")
    if moment < start:
        return False
    if end_raw is None:
        return True
    return moment < parse_iso(end_raw)


def windows_overlap(from_a, to_a, from_b, to_b):
    """Half-open window intersection; adjacency (shared endpoint) is allowed."""
    fa, fb = parse_iso(from_a), parse_iso(from_b)
    left = True if to_b is None else fa < parse_iso(to_b)
    right = True if to_a is None else fb < parse_iso(to_a)
    return left and right


# --- Payload helpers ----------------------------------------------------------

def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def req_str(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' is required and must be a string", 400
        )
    return value


def req_enum(body, name, allowed):
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be one of: {', '.join(sorted(allowed))}",
            400,
        )
    return value


def req_int(body, name, minimum=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, int) or isinstance(value, bool):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' is required and must be an integer", 400
        )
    if minimum is not None and value < minimum:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be at least {minimum}", 400
        )
    return value


def req_bool(body, name):
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, bool):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' is required and must be a boolean", 400
        )
    return value


def req_list(body, name, item_enum=None, item_type=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or not isinstance(value, list):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' is required and must be an array", 400
        )
    for item in value:
        if item_type is not None and (not isinstance(item, item_type) or isinstance(item, bool)):
            raise ApiError(
                ERR_INVALID_REQUEST, f"Field '{name}' contains an item of the wrong type", 400
            )
        if item_enum is not None and item not in item_enum:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"Field '{name}' contains a value outside: {', '.join(sorted(item_enum))}",
                400,
            )
    return value


def req_datetime(body, name):
    """Required caller-supplied instant; validated, echoed verbatim."""
    value = req_str(body, name)
    try:
        parse_iso(value)
    except (ValueError, TypeError):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be an ISO 8601 datetime", 400
        )
    return value


def opt_datetime(body, name):
    """Optional caller-supplied instant (null/absent allowed); echoed verbatim."""
    value = body.get(name, None)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be an ISO 8601 datetime", 400
        )
    try:
        parse_iso(value)
    except (ValueError, TypeError):
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be an ISO 8601 datetime", 400
        )
    return value


def new_entity(fields):
    """Mint a common-fields entity: id/created_at/updated_at/version (§2.5).

    Caller-supplied id/version in creation payloads are ignored — the server
    mints its own.
    """
    ts = now_iso()
    entity = {"id": new_id()}
    entity.update(fields)
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity
