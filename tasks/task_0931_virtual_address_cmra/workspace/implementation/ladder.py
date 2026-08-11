"""
The 36-rung request validation ladder (PRD 2.9).

Every rung below is numbered with the rung it implements.  Endpoint handlers
call these helpers in strictly ascending rung order; the first failure decides
the response.
"""

import functools

from flask import g, request

import store
from errors import NOT_FOUND_FOR, ApiError
from serializers import release_gate_state
from util import CLOCK, ENUMS, ROLES

# ---------------------------------------------------------------- rung 1 & 2
def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.role = role
    g.user_id = uid


def authorize(roles):
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------- rung 3
_LOOKUP = {
    "box": lambda i: store.DB.boxes.get(i),
    "recipient": lambda i: store.DB.recipients.get(i),
    "form1583": lambda i: store.DB.form1583s.get(i),
    "id_document": lambda i: store.DB.id_documents.get(i),
    "mail_item": lambda i: store.DB.mail_items.get(i),
    "scan_job": lambda i: store.DB.scan_jobs.get(i),
    "disposition": lambda i: store.DB.dispositions.get(i),
    "forward_shipment": lambda i: store.DB.forward_shipments.get(i),
    "deposit_batch": lambda i: store.DB.deposit_batches.get(i),
    "check_deposit": lambda i: store.DB.check_deposits.get(i),
    "compliance_review": lambda i: store.DB.compliance_reviews.get(i),
    "billing_cycle": lambda i: store.DB.billing_cycles.get(i),
}


def resolve_primary(kind, ident):
    obj = _LOOKUP[kind](ident)
    if obj is None:
        raise ApiError(NOT_FOUND_FOR[kind])
    return obj


def box_for(kind, obj):
    """The mailbox a resource hangs off, for the global gates and scope checks."""
    if kind == "box":
        return obj
    if kind == "recipient":
        return store.box_of_recipient(obj)
    if kind == "form1583":
        return store.box_of_form(obj)
    if kind == "id_document":
        return store.box_of_doc(obj)
    if kind == "mail_item":
        return store.box_of_item(obj)
    if kind == "scan_job":
        return store.box_of_scan_job(obj)
    if kind == "disposition":
        return store.box_of_disposition(obj)
    if kind == "check_deposit":
        return store.box_of_check(obj)
    if kind in ("forward_shipment", "deposit_batch", "compliance_review", "billing_cycle"):
        return store.DB.boxes.get(obj["box_id"])
    return None


def _scope_recipient(kind, obj):
    if kind == "recipient":
        return obj["id"]
    if kind == "mail_item":
        return obj["matched_recipient_id"]
    return None


# ---------------------------------------------------------------- rung 8
def scope_check(kind, obj):
    if g.role == "BoxHolder":
        b = box_for(kind, obj)
        if b is None or b["id"] != g.user_id:
            raise ApiError("ERR_UNAUTHORIZED")
    elif g.role == "Recipient":
        rid = _scope_recipient(kind, obj)
        if rid is None or rid != g.user_id:
            raise ApiError("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------- rung 9 helpers
def body():
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return data


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def req_present(b, field):
    if field not in b or b[field] is None:
        _bad(field, "is required")
    return b[field]


def req_str(b, field, nonempty=True):
    v = req_present(b, field)
    if not isinstance(v, str):
        _bad(field, "must be a string")
    if nonempty and not v.strip():
        _bad(field, "must be non-empty")
    return v


def opt_str(b, field, default=None, nonempty=True):
    if field not in b or b[field] is None:
        return default
    return req_str(b, field, nonempty)


def req_int(b, field, minimum=None, maximum=None):
    v = req_present(b, field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and v > maximum:
        _bad(field, "must be <= %d" % maximum)
    return v


def opt_int(b, field, default, minimum=None, maximum=None):
    if field not in b or b[field] is None:
        return default
    return req_int(b, field, minimum, maximum)


def req_num(b, field, minimum=None, exclusive_min=None):
    v = req_present(b, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad(field, "must be a number")
    if minimum is not None and v < minimum:
        _bad(field, "must be >= %s" % minimum)
    if exclusive_min is not None and v <= exclusive_min:
        _bad(field, "must be > %s" % exclusive_min)
    return v


def req_bool(b, field, default=None):
    if field not in b or b[field] is None:
        if default is None:
            _bad(field, "is required")
        return default
    v = b[field]
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_list(b, field, item_type=str):
    v = req_present(b, field)
    if not isinstance(v, list):
        _bad(field, "must be an array")
    for x in v:
        if not isinstance(x, item_type):
            _bad(field, "must contain only strings")
    return v


def opt_list(b, field, default):
    if field not in b or b[field] is None:
        return list(default)
    return req_list(b, field)


# ---------------------------------------------------------------- rung 10
def check_enum(field, value, members):
    """
    Rung 10 applies to EXACTLY the fields enumerated in PRD 2.9 and no others; a
    non-enum field carrying a bad value routes to ERR_VALIDATION at rung 9.
    """
    if value not in members:
        raise ApiError("ERR_INVALID_ENUM",
                       "Field '%s' carries a value outside its declared member set." % field)
    return value


def enum_body(b, field, enum_name, required=True, default=None):
    if field not in b or b[field] is None:
        if required:
            _bad(field, "is required")
        return default
    return check_enum(field, b[field], ENUMS[enum_name])


def enum_query(field, enum_name=None, members=None):
    v = request.args.get(field)
    if v is None:
        return None
    return check_enum(field, v, members if members is not None else ENUMS[enum_name])


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


# ---------------------------------------------------------------- rungs 11 & 12
GATE_A_OPERATIONS = {
    "scan_jobs_create", "dispositions_create", "disposition_execute",
    "forward_shipment_create", "forward_shipment_ship", "check_create",
    "recipient_create", "plan_change",
}
GATE_B_EXEMPT = {"box_activate", "recipient_create"}


def gate_a(op, box, mail_item=None, scan_tier=None):
    """Rung 11 -- the suspension gate, with the service-of-process carve-out."""
    if box is None or op not in GATE_A_OPERATIONS:
        return
    if box["service_status"] != "SUSPENDED":
        return
    if (op == "scan_jobs_create" and mail_item is not None
            and mail_item["item_class"] == "SOP"
            and scan_tier in ("COVER", "INTERIOR")
            and store.active_ra(box["id"]) is not None):
        return  # carve-out; it does not extend to OCR
    raise ApiError("ERR_BOX_SUSPENDED")


def gate_b(op, box):
    """Rung 12 -- the lifecycle gate."""
    if box is None or op in GATE_B_EXEMPT:
        return
    if release_gate_state(box) == "GATED_LIFECYCLE":
        raise ApiError("ERR_INVALID_STATE",
                       "The mailbox is %s and this operation requires an in-service mailbox."
                       % box["service_status"])


# ---------------------------------------------------------------- rung 13
def occ(b, field, parent):
    """Presence and type were already checked at rung 9; this rung only compares."""
    if b.get(field) != parent["version"]:
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------- rungs 17-19
def gate_c_for_recipient(r):
    """
    Rungs 17/18/19 decompose the Form 1583 gate so the caller learns which
    clause failed.  Each rung is evaluated against its LITERALLY declared
    condition (PRD 2.9), in ascending order, and a rung whose condition does not
    hold is skipped without effect.  The derivation's clauses 4 (guarantor) and
    5 (roster) own no rung and no error id, so a member blocked only on those
    passes this gate -- the ladder as written has no rung left to fail on.  In
    practice that member's mailbox is suspended, and Gate A at rung 11 already
    pre-empted every one of Gate C's five blocked operations.
    """
    import domain
    if r is None:
        return
    if r["release_eligibility"] == "RELEASABLE":
        return
    if not any(f["status"] == "ACCEPTED" for f in store.forms_of_recipient(r["id"])):
        raise ApiError("ERR_FORM_1583_INCOMPLETE")                  # rung 17
    photo = domain.governing(r["id"], "PHOTO")
    address = domain.governing(r["id"], "ADDRESS")
    if photo is None or address is None:
        raise ApiError("ERR_ID_DOCUMENT_SET_INCOMPLETE")            # rung 18
    if photo["status"] != "VERIFIED" or address["status"] != "VERIFIED":
        raise ApiError("ERR_ID_DOCUMENT_EXPIRED")                   # rung 19


def gate_c_item(item):
    if item is None or not item["matched_recipient_id"]:
        return
    gate_c_for_recipient(store.recipient(item["matched_recipient_id"]))


# ---------------------------------------------------------------- listing
def paginate(rows_list, serializer):
    limit, offset = pagination()
    total = len(rows_list)
    page = rows_list[offset:offset + limit]
    return [serializer(r) for r in page], total, limit, offset


# ---------------------------------------------------------------- decorator
def endpoint(roles, primary=None, scope=False):
    """Runs rungs 1, 2, 3 and (when the endpoint has no body references) rung 8."""

    def wrapper(fn):
        @functools.wraps(fn)
        def inner(**kwargs):
            authenticate()
            authorize(roles)
            if primary is not None:
                ident = kwargs.pop("ident")
                obj = resolve_primary(primary, ident)
                if scope:
                    scope_check(primary, obj)
                return fn(obj, **kwargs)
            return fn(**kwargs)

        return inner

    return wrapper


def clock_hour_cutoff():
    from util import BATCH_CUTOFF_HOUR_UTC
    if CLOCK.hour() >= BATCH_CUTOFF_HOUR_UTC:
        raise ApiError("ERR_BATCH_CUTOFF_PASSED")
