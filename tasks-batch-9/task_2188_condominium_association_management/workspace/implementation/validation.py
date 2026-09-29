"""Validation ladder rungs 4-9 plus reusable field checks (PRD 2.5-2.9)."""
from flask import g, request

import clock
import db
from errors import ApiError

# ---------------------------------------------------------------- rung 4: paths

PATH_ERRORS = {
    "association_id": ("associations", "ERR_ASSOCIATION_NOT_FOUND"),
    "owner_id": ("owners", "ERR_OWNER_NOT_FOUND"),
    "unit_id": ("units", "ERR_UNIT_NOT_FOUND"),
    "ledger_entry_id": ("ledger_entries", "ERR_LEDGER_ENTRY_NOT_FOUND"),
    "budget_id": ("budgets", "ERR_BUDGET_NOT_FOUND"),
    "board_meeting_id": ("board_meetings", "ERR_MEETING_NOT_FOUND"),
    "special_assessment_id": ("special_assessments", "ERR_ASSESSMENT_NOT_FOUND"),
    "common_element_id": ("common_elements", "ERR_ELEMENT_NOT_FOUND"),
    "vendor_contract_id": ("vendor_contracts", "ERR_CONTRACT_NOT_FOUND"),
    "work_order_id": ("work_orders", "ERR_WORK_ORDER_NOT_FOUND"),
    "insurance_claim_id": ("insurance_claims", "ERR_CLAIM_NOT_FOUND"),
    "violation_case_id": ("violation_cases", "ERR_CASE_NOT_FOUND"),
    "resale_certificate_id": ("resale_certificates", "ERR_CERTIFICATE_NOT_FOUND"),
}


def resolve_path(**params):
    """Rung 4.  Resolve path params strictly left to right in the given order."""
    out = {}
    for key, value in params.items():
        collection, err = PATH_ERRORS[key]
        row = db.get(collection, value)
        if row is None:
            raise ApiError(err)
        out[key] = row
    return out


# ------------------------------------------------------------ rung 5: body FKs

BODY_FK_COLLECTIONS = {
    "current_owner_id": "owners",
    "new_owner_id": "owners",
    "voter_owner_id": "owners",
    "reported_by_owner_id": "owners",
    "source_budget_id": "budgets",
    "ratification_meeting_id": "board_meetings",
    "meeting_id": "board_meetings",
    "contract_id": "vendor_contracts",
    "element_id": "common_elements",
    "claim_id": "insurance_claims",
    "funding_claim_id": "insurance_claims",
    "unit_id": "units",
    "certificate_id": "resale_certificates",
}


def resolve_body_fk(body, *names):
    """Rung 5.  Every named body FK that is present and non-null must resolve."""
    out = {}
    for name in names:
        value = body.get(name)
        if value is None:
            out[name] = None
            continue
        if name == "affected_unit_ids":
            rows = []
            for uid in value if isinstance(value, list) else []:
                row = db.get("units", uid)
                if row is None:
                    raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
                rows.append(row)
            out[name] = rows
            continue
        collection = BODY_FK_COLLECTIONS[name]
        row = db.get(collection, value)
        if row is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        out[name] = row
    return out


# --------------------------------------------------- rung 6: fields and ranges


def body_of(req=None):
    r = req or request
    if not r.data:
        return {}
    try:
        data = r.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def fail(msg="Request payload failed validation."):
    raise ApiError("ERR_VALIDATION", msg)


def require_int(body, name, minimum=None, maximum=None, required=True, default=None,
                allow_zero=True):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("Field '%s' must be <= %d." % (name, maximum))
    if not allow_zero and value == 0:
        fail("Field '%s' must be non-zero." % name)
    return value


def require_str(body, name, required=True, default=None, min_len=None, max_len=None):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("Field '%s' is too long." % name)
    return value


def require_enum(body, name, allowed, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def require_bool(body, name, required=False, default=None):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("Field '%s' must be a boolean." % name)
    return value


def require_dt(body, name, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("Field '%s' must be an ISO-8601 timestamp string." % name)
    parsed = clock.parse(value)
    if parsed is None:
        fail("Field '%s' is not a valid ISO-8601 timestamp." % name)
    return parsed


def require_id(body, name, required=True, default=None):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not value:
        fail("Field '%s' must be an id string." % name)
    return value


_PERIOD_OK = "0123456789"


def require_period(body, name, required=True, default=None):
    value = require_str(body, name, required=required, default=default)
    if value is None:
        return None
    if len(value) != 7 or value[4] != "-":
        fail("Field '%s' must be formatted YYYY-MM." % name)
    y, m = value[:4], value[5:]
    if not (all(c in _PERIOD_OK for c in y) and all(c in _PERIOD_OK for c in m)):
        fail("Field '%s' must be formatted YYYY-MM." % name)
    if not (1 <= int(m) <= 12):
        fail("Field '%s' must name a real month." % name)
    return value


def require_str_list(body, name, allowed=None, required=True, default=None,
                     non_empty=False):
    if name not in body or body.get(name) is None:
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        fail("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            fail("Field '%s' must be an array of strings." % name)
        if allowed is not None and item not in allowed:
            fail("Field '%s' contains an unrecognized value." % name)
    if non_empty and not value:
        fail("Field '%s' must be non-empty." % name)
    return value


def pagination():
    """Rung 6 for list endpoints: limit 1..100 (default 10), offset >= 0 (default 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# ------------------------------------------------- rung 7: owner scoping

def owner_scope(unit):
    """Rung 7.  Only meaningful for the UnitOwner role."""
    if g.get("role") == "UnitOwner":
        if unit.get("current_owner_id") != g.get("user_id"):
            raise ApiError("ERR_NOT_UNIT_OWNER")


# ------------------------------------------- rung 8: association scope match

def scope_match(association_id, *rows):
    """Rung 8.  Every referenced row must live in the target association."""
    for row in rows:
        if row is None:
            continue
        if isinstance(row, list):
            scope_match(association_id, *row)
            continue
        aid = row.get("association_id")
        if aid is None and "unit_id" in row:
            unit = db.get("units", row.get("unit_id"))
            aid = unit.get("association_id") if unit else None
        if aid is not None and aid != association_id:
            raise ApiError("ERR_ASSOCIATION_SCOPE_MISMATCH")


# --------------------------------------------------------- rung 9: OCC guards

def occ(body, field, parent, error_id):
    """Rung 9.  The version field is a NON-OPTIONAL input; omitting it is a rung-6
    field-level validation failure, which has therefore already been checked."""
    expected = body.get(field)
    if expected != parent.get("version"):
        raise ApiError(error_id)
