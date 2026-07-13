"""Request-schema validation (priority 3 -> ERR_INVALID_REQUEST 400) and
resource-existence lookups (priorities 4 and 5 -> *_NOT_FOUND 404)."""
from flask import request

import store
from errors import err

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    return err("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def _present(b, field, required):
    if field not in b or b[field] is None:
        if required:
            raise _bad(field, "is required.")
        return False
    return True


# --------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------
def string_field(b, field, required=True, default=None):
    if not _present(b, field, required):
        return default
    value = b[field]
    if not isinstance(value, str) or value == "":
        raise _bad(field, "must be a non-empty string.")
    return value


def enum_field(b, field, allowed, required=True, default=None):
    if not _present(b, field, required):
        return default
    value = b[field]
    if not isinstance(value, str) or value not in allowed:
        raise _bad(field, "must be one of %s." % ", ".join(allowed))
    return value


def int_field(b, field, required=True, default=None, minimum=None):
    if not _present(b, field, required):
        return default
    value = b[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %d." % minimum)
    return value


def number_field(b, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(b, field, required):
        return default
    value = b[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(field, "must be a number.")
    value = float(value)
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %s." % minimum)
    if maximum is not None and value > maximum:
        raise _bad(field, "must be <= %s." % maximum)
    return value


def bool_field(b, field, required=True, default=None):
    if not _present(b, field, required):
        return default
    value = b[field]
    if not isinstance(value, bool):
        raise _bad(field, "must be a boolean.")
    return value


def datetime_field(b, field, required=True, default=None):
    """Returns (raw_string, aware_datetime) so the raw client text is echoed back."""
    if not _present(b, field, required):
        return (default, None)
    value = b[field]
    parsed = store.parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        raise _bad(field, "must be an ISO 8601 datetime string.")
    return (value, parsed)


def list_field(b, field, required=True, default=None):
    if not _present(b, field, required):
        return [] if default is None else list(default)
    value = b[field]
    if not isinstance(value, list):
        raise _bad(field, "must be an array.")
    return value


def string_list_field(b, field, required=True, default=None):
    values = list_field(b, field, required=required, default=default)
    for item in values:
        if not isinstance(item, str) or item == "":
            raise _bad(field, "must be an array of non-empty strings.")
    return values


def object_field(b, field, required=True, default=None):
    if not _present(b, field, required):
        return {} if default is None else dict(default)
    value = b[field]
    if not isinstance(value, dict):
        raise _bad(field, "must be an object.")
    return value


def fee_schedule_field(b, field):
    schedule = object_field(b, field, required=False, default={})
    for code, cap in schedule.items():
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
            raise _bad(field, "values must be non-negative integers.")
    return schedule


def service_lines_field(b, field, required=True):
    lines = list_field(b, field, required=required, default=[])
    normalised = []
    for line in lines:
        if not isinstance(line, dict):
            raise _bad(field, "entries must be objects with code and billed_cents.")
        code = line.get("code")
        billed = line.get("billed_cents")
        if not isinstance(code, str) or code == "":
            raise _bad(field, "entries require a non-empty string code.")
        if isinstance(billed, bool) or not isinstance(billed, int) or billed < 0:
            raise _bad(field, "entries require a non-negative integer billed_cents.")
        normalised.append({"code": code, "billed_cents": billed})
    return normalised


def strictly_after(later_name, later_dt, earlier_name, earlier_dt):
    if not (later_dt > earlier_dt):
        raise _bad(later_name, "must be strictly after %s." % earlier_name)


# --------------------------------------------------------------------------
# Existence lookups
# --------------------------------------------------------------------------
def _lookup(collection, resource_id, error_id):
    rec = collection.get(resource_id)
    if rec is None:
        raise err(error_id)
    return rec


def get_policy(pid):
    return _lookup(store.policies, pid, "ERR_POLICY_NOT_FOUND")


def get_store(sid):
    return _lookup(store.stores, sid, "ERR_STORE_NOT_FOUND")


def get_frame(fid):
    return _lookup(store.frames, fid, "ERR_FRAME_NOT_FOUND")


def get_customer(cid):
    return _lookup(store.customers, cid, "ERR_CUSTOMER_NOT_FOUND")


def get_prescription(pid):
    return _lookup(store.prescriptions, pid, "ERR_PRESCRIPTION_NOT_FOUND")


def get_kit(kid):
    return _lookup(store.kits, kid, "ERR_KIT_NOT_FOUND")


def get_order(oid):
    return _lookup(store.orders, oid, "ERR_ORDER_NOT_FOUND")


def get_lab_order(lid):
    return _lookup(store.lab_orders, lid, "ERR_LAB_ORDER_NOT_FOUND")


def get_claim(cid):
    return _lookup(store.claims, cid, "ERR_CLAIM_NOT_FOUND")


def get_warranty_claim(wid):
    return _lookup(store.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")


def get_appointment(aid):
    return _lookup(store.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")


def get_lens_option(oid, expected_category):
    """A RETIRED option, or one referenced in the wrong slot, is treated as NOT FOUND
    (PRD 2.9 step 5)."""
    opt = store.lens_options.get(oid)
    if opt is None or opt["status"] == "RETIRED" or opt["category"] != expected_category:
        raise err("ERR_LENS_OPTION_NOT_FOUND")
    return opt
