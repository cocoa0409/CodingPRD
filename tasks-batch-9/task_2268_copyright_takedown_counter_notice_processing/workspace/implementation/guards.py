"""Rejection-ladder rungs 1-5: authentication, role authorisation, request shape,
path existence and body foreign keys (PRD section 2.6)."""
import re

from flask import request

from errors import fail
import store

ROLES = (
    "ComplianceOfficer",
    "TakedownAgent",
    "AbuseInvestigator",
    "RightsHolderRep",
    "Subscriber",
)

FINGERPRINT_RE = re.compile(r"^[0-9a-f]{32}$")


# --------------------------------------------------------------------------
# rungs 1 and 2
# --------------------------------------------------------------------------
def authorize(*allowed):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header must name one of the five roles.")
    if allowed and role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


# --------------------------------------------------------------------------
# rung 3: request shape
# --------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None or not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def bad(name, detail="is invalid"):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def req_string(payload, name):
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        bad(name, "is required and must be a non-empty string")
    return value


def opt_string(payload, name, default=None):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    return value


def opt_bool(payload, name, default=False):
    if name not in payload or payload[name] is None:
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def _as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    return None


def req_int(payload, name, low=None, high=None):
    if name not in payload or payload[name] is None:
        bad(name, "is required")
    number = _as_int(payload[name])
    if number is None:
        bad(name, "must be an integer")
    if low is not None and number < low:
        bad(name, "must be at least %d" % low)
    if high is not None and number > high:
        bad(name, "must be at most %d" % high)
    return number


def opt_int(payload, name, default, low=None, high=None):
    if name not in payload or payload[name] is None:
        return default
    number = _as_int(payload[name])
    if number is None:
        bad(name, "must be an integer")
    if low is not None and number < low:
        bad(name, "must be at least %d" % low)
    if high is not None and number > high:
        bad(name, "must be at most %d" % high)
    return number


def req_enum(payload, name, allowed):
    value = payload.get(name)
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def req_fingerprint(payload, name="fingerprint_hash"):
    value = payload.get(name)
    if not isinstance(value, str) or not FINGERPRINT_RE.match(value):
        bad(name, "must be exactly 32 lowercase hexadecimal characters")
    return value


def req_claimed_urls(payload, name="claimed_urls"):
    value = payload.get(name)
    if not isinstance(value, list) or isinstance(value, (str, bytes)):
        bad(name, "must be an array of 1 to 25 non-empty strings")
    if len(value) < 1 or len(value) > 25:
        bad(name, "must hold between 1 and 25 entries")
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            bad(name, "entries must all be non-empty strings")
    return list(value)


def req_id(payload, name, table, error_id):
    """Required body foreign key: shape at rung 3, existence at rung 5."""
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        bad(name, "is required and must be a string identifier")
    return value


def resolve_fk(value, table, error_id):
    record = table.get(value)
    if record is None:
        fail(error_id, "No such record: %s" % value)
    return record


# --------------------------------------------------------------------------
# rung 3: pagination and filters
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            bad("limit", "must be an integer between 1 and 100")
    if "offset" in request.args:
        raw = request.args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("offset", "must be a non-negative integer")
        if offset < 0:
            bad("offset", "must be a non-negative integer")
    return limit, offset


def enum_filter(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def id_filter(name, table, error_id):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or not value.strip() or value not in table:
        fail(error_id, "No such record: %s" % value)
    return value


def page(rows, limit, offset):
    """Order by created_at ASC (ties broken by created_at alone), then slice."""
    ordered = sorted(rows, key=lambda record: record["created_at"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return window, meta


def listing(rows, filters=None):
    """Validate pagination, apply predicates, order and slice in one step."""
    limit, offset = pagination()
    selected = list(rows)
    if filters:
        for predicate in filters:
            selected = [row for row in selected if predicate(row)]
    return page(selected, limit, offset)


# --------------------------------------------------------------------------
# rung 4: path existence
# --------------------------------------------------------------------------
def path_provider(provider_id):
    return resolve_fk(provider_id, store.db.providers, "ERR_PROVIDER_NOT_FOUND")


def path_agent(agent_id):
    return resolve_fk(agent_id, store.db.agents, "ERR_DESIGNATED_AGENT_NOT_FOUND")


def path_policy(policy_id):
    return resolve_fk(policy_id, store.db.policies, "ERR_POLICY_NOT_FOUND")


def path_account(account_id):
    return resolve_fk(account_id, store.db.accounts, "ERR_ACCOUNT_NOT_FOUND")


def path_item(item_id):
    return resolve_fk(item_id, store.db.content_items, "ERR_CONTENT_ITEM_NOT_FOUND")


def path_holder(holder_id):
    return resolve_fk(holder_id, store.db.rights_holders, "ERR_RIGHTS_HOLDER_NOT_FOUND")


def path_notice(notice_id):
    return resolve_fk(notice_id, store.db.notices, "ERR_NOTICE_NOT_FOUND")


def path_claim(claim_id):
    return resolve_fk(claim_id, store.db.claims, "ERR_CLAIM_NOT_FOUND")


def path_counter(counter_id):
    return resolve_fk(counter_id, store.db.counter_notices, "ERR_COUNTER_NOTICE_NOT_FOUND")


def path_strike(strike_id):
    return resolve_fk(strike_id, store.db.strikes, "ERR_STRIKE_NOT_FOUND")


def path_termination(case_id):
    return resolve_fk(case_id, store.db.termination_cases, "ERR_TERMINATION_CASE_NOT_FOUND")


def path_misrep(case_id):
    return resolve_fk(case_id, store.db.misrep_cases, "ERR_MISREPRESENTATION_CASE_NOT_FOUND")


def path_reference(file_id):
    return resolve_fk(file_id, store.db.reference_files, "ERR_REFERENCE_FILE_NOT_FOUND")


def path_batch(batch_id):
    return resolve_fk(batch_id, store.db.batches, "ERR_INGESTION_BATCH_NOT_FOUND")


def path_audit(audit_id):
    return resolve_fk(audit_id, store.db.audits, "ERR_AUDIT_NOT_FOUND")


# --------------------------------------------------------------------------
# rung 6: resource ownership for the entity-backed roles
# --------------------------------------------------------------------------
def own_account(role, user_id, account_id):
    if role == "Subscriber" and user_id != account_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting subscriber does not own this account.")


def own_holder(role, user_id, holder_id):
    if role == "RightsHolderRep" and user_id != holder_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting rights holder does not own this resource.")
