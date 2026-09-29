"""Step 3 (body well-formedness) and step 4 (reference existence) helpers."""

from flask import request

from errors import fail
from store import db, parse_iso

_MISSING = object()


def body():
    """Parsed JSON object body; an absent body is treated as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, allow_empty=True):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value


def opt_str(data, name, default=None, allow_empty=True):
    if not _present(data, name):
        return default
    return req_str(data, name, allow_empty=allow_empty)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_bool(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    return req_bool(data, name)


def req_str_array(data, name, non_empty=True):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain only strings." % name)
    return list(value)


def opt_str_array(data, name, default=None, non_empty=False):
    if not _present(data, name):
        return default
    return req_str_array(data, name, non_empty=non_empty)


def req_datetime(data, name):
    raw = req_str(data, name)
    parsed = parse_iso(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime." % name)
    return parsed


def opt_datetime(data, name, default=None):
    if not _present(data, name):
        return default
    return req_datetime(data, name)


def pagination():
    """Step 3 pagination validation (PRD 2.3)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is invalid." % name)
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# --- step 4: reference existence -------------------------------------------

def find_program(program_id):
    rec = db.programs.get(program_id)
    if rec is None:
        fail("ERR_PROGRAM_NOT_FOUND", "No compliance program with id %s." % program_id)
    return rec


def find_jurisdiction(jurisdiction_id):
    rec = db.jurisdictions.get(jurisdiction_id)
    if rec is None:
        fail("ERR_JURISDICTION_NOT_FOUND", "No state statutory profile with id %s." % jurisdiction_id)
    return rec


def find_vendor(vendor_id):
    rec = db.vendors.get(vendor_id)
    if rec is None:
        fail("ERR_VENDOR_NOT_FOUND", "No vendor with id %s." % vendor_id)
    return rec


def find_contract(contract_id):
    rec = db.contracts.get(contract_id)
    if rec is None:
        fail("ERR_CONTRACT_NOT_FOUND", "No vendor contract with id %s." % contract_id)
    return rec


def find_policy(policy_id):
    rec = db.policies.get(policy_id)
    if rec is None:
        fail("ERR_POLICY_NOT_FOUND", "No policy with id %s." % policy_id)
    return rec


def find_notice(notice_id):
    rec = db.notices.get(notice_id)
    if rec is None:
        fail("ERR_NOTICE_NOT_FOUND", "No notice packet with id %s." % notice_id)
    return rec


def find_asset(asset_id):
    rec = db.assets.get(asset_id)
    if rec is None:
        fail("ERR_ASSET_NOT_FOUND", "No collection point with id %s." % asset_id)
    return rec


def find_subject(subject_id):
    rec = db.subjects.get(subject_id)
    if rec is None:
        fail("ERR_SUBJECT_NOT_FOUND", "No data subject with id %s." % subject_id)
    return rec


def find_consent(consent_id):
    rec = db.consents.get(consent_id)
    if rec is None:
        fail("ERR_CONSENT_NOT_FOUND", "No consent record with id %s." % consent_id)
    return rec


def find_accommodation(accommodation_id):
    rec = db.accommodations.get(accommodation_id)
    if rec is None:
        fail("ERR_ACCOMMODATION_NOT_FOUND", "No accommodation with id %s." % accommodation_id)
    return rec


def find_incident(incident_id):
    rec = db.incidents.get(incident_id)
    if rec is None:
        fail("ERR_INCIDENT_NOT_FOUND", "No incident case with id %s." % incident_id)
    return rec


def find_assessment(assessment_id):
    rec = db.assessments.get(assessment_id)
    if rec is None:
        fail("ERR_ASSESSMENT_NOT_FOUND", "No exposure assessment with id %s." % assessment_id)
    return rec
