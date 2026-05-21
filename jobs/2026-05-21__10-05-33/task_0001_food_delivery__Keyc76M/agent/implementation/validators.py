"""Lightweight body-shape validators.

Each function returns (ok, error_envelope) or (ok, value). The caller is
expected to be holding the state lock and to invoke validators after
header/role checks.
"""

import envelope


def is_str(v):
    return isinstance(v, str)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, int) or isinstance(v, float)) and not isinstance(v, bool)


def require_body(payload):
    if payload is None or not isinstance(payload, dict):
        return envelope.validation("Request body must be a JSON object.")
    return None


def require_field(payload, field, predicate, msg):
    if field not in payload:
        return envelope.validation(f"Missing required field '{field}'.")
    if not predicate(payload[field]):
        return envelope.validation(msg)
    return None


def opt_field(payload, field, predicate, msg):
    if field in payload and payload[field] is not None:
        if not predicate(payload[field]):
            return envelope.validation(msg)
    return None


def pagination_params(args):
    """Parse limit/offset from request.args. Returns (limit, offset) or error response."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        return None, envelope.validation("limit must be an integer.")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        return None, envelope.validation("offset must be an integer.")
    if limit < 1 or limit > 100:
        return None, envelope.validation("limit must be in [1, 100].")
    if offset < 0:
        return None, envelope.validation("offset must be >= 0.")
    return (limit, offset), None
