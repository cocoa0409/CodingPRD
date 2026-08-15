"""Core plumbing: envelope, errors, auth, shape validation, pagination, store."""
import datetime
import uuid
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# --- Domain constants (from SCAFFOLD.yaml / PRD.md) ---
ROLES = ("VenueAdmin", "SponsorshipSales", "ActivationManager", "FinanceManager", "SponsorContact")
CATEGORIES = ("BEVERAGE", "BANKING", "AUTO", "AIRLINE", "TECH")
ASSET_CLASSES = ("SIGNAGE", "DIGITAL", "HOSPITALITY")
HOLDERS = ("TEAM", "VENUE", "LEAGUE")
UNIT_KINDS = ("GAME_DISPLAY", "IMPRESSION_BLOCK", "SUITE_NIGHT")
ESCALATOR_MODES = ("COMPOUND", "SIMPLE")


# --- Timestamps / ids ---
def now_iso():
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_uuid():
    return str(uuid.uuid4())


def _req_meta():
    return {"api_request_id": "req_" + uuid.uuid4().hex,
            "api_request_timestamp": now_iso()}


# --- Errors ---
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def e_unauthenticated(m="Missing or unknown X-User-Role or X-User-ID header"):
    return ApiError("ERR_UNAUTHENTICATED", 401, m)


def e_forbidden(m="Role not permitted on endpoint, or resource outside sponsor scope"):
    return ApiError("ERR_FORBIDDEN", 403, m)


def e_sod(m="Evidence reviewer must differ from the submitter"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, m)


def e_not_found(m="Path id or referenced body FK does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, m)


def e_invalid_request(m="Missing required field, unknown field, or invalid value"):
    return ApiError("ERR_INVALID_REQUEST", 400, m)


def e_invalid_state(m="Target entity's state machine forbids the action"):
    return ApiError("ERR_INVALID_STATE", 409, m)


def e_rights_conflict(m="An ACTIVE LEAGUE rights window overlaps the grant's venue/category/seasons"):
    return ApiError("ERR_RIGHTS_CONFLICT", 409, m)


def e_contested(m="Contract rights_status is CONTESTED"):
    return ApiError("ERR_CONTRACT_RIGHTS_CONTESTED", 409, m)


def e_season_window(m="Season window malformed or SUITE_NIGHT checkin after checkout"):
    return ApiError("ERR_SEASON_WINDOW_INVALID", 422, m)


def e_season_out_of_term(m="Season outside the contract term"):
    return ApiError("ERR_SEASON_OUT_OF_TERM", 422, m)


def e_season_closed(m="Season is already closed"):
    return ApiError("ERR_SEASON_CLOSED", 422, m)


def e_season_not_closed(m="Report season must be closed"):
    return ApiError("ERR_SEASON_NOT_CLOSED", 422, m)


def e_grant_outside_term(m="Grant window not contained in contract term"):
    return ApiError("ERR_GRANT_OUTSIDE_TERM", 422, m)


def e_category_conflict(m="Another ACTIVE grant on the same venue+category overlaps"):
    return ApiError("ERR_CATEGORY_EXCLUSIVITY_CONFLICT", 409, m)


def e_duplicate_grant(m="Contract already holds a PENDING/ACTIVE grant for this category"):
    return ApiError("ERR_DUPLICATE_GRANT", 409, m)


def e_suite_conflict(m="SUITE_NIGHT buffered date span intersects an existing booking"):
    return ApiError("ERR_SUITE_DATE_CONFLICT", 409, m)


def e_over_delivery(m="Approval would push approved_units beyond contracted_units"):
    return ApiError("ERR_OVER_DELIVERY", 422, m)


def e_dup_opportunity(m="Contract already has an open renewal opportunity"):
    return ApiError("ERR_DUPLICATE_OPEN_OPPORTUNITY", 409, m)


def e_sponsor_not_active(m="Sponsor must be ACTIVE for this operation"):
    return ApiError("ERR_SPONSOR_NOT_ACTIVE", 409, m)


def e_asset_not_available(m="Asset is RETIRED"):
    return ApiError("ERR_ASSET_NOT_AVAILABLE", 409, m)


def e_contract_not_active(m="Contract must be ACTIVE for this operation"):
    return ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, m)


def e_deliverable_not_open(m="Deliverable must be IN_PROGRESS"):
    return ApiError("ERR_DELIVERABLE_NOT_OPEN", 409, m)


def e_renewal_state(m="Renewal source contract must be ACTIVE or EXPIRED"):
    return ApiError("ERR_RENEWAL_CONTRACT_STATE", 409, m)


def e_invalid_amount(m="Amount/quantity/fee field must be a positive integer (pct >= 0)"):
    return ApiError("ERR_INVALID_AMOUNT", 422, m)


def e_credit_cap(m="approved_amount_cents exceeds the make-good cap"):
    return ApiError("ERR_CREDIT_EXCEEDS_CAP", 422, m)


def e_credit_balance(m="Credit exceeds the selected invoice's remaining balance"):
    return ApiError("ERR_CREDIT_EXCEEDS_INVOICE_BALANCE", 422, m)


def e_payment_balance(m="Payment exceeds invoice remaining balance"):
    return ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422, m)


def e_invoice_not_payable(m="Invoice must be ISSUED or PARTIALLY_PAID"):
    return ApiError("ERR_INVOICE_NOT_PAYABLE", 409, m)


def e_no_payable(m="No ISSUED/PARTIALLY_PAID invoice on the contract"):
    return ApiError("ERR_NO_PAYABLE_INVOICE", 409, m)


def e_stale_contract(m="expected_contract_version does not match the contract version"):
    return ApiError("ERR_STALE_CONTRACT_VERSION", 412, m)


def e_stale_opportunity(m="expected_opportunity_version does not match the opportunity version"):
    return ApiError("ERR_STALE_OPPORTUNITY_VERSION", 412, m)


# --- Responses ---
def ok(data, status=200):
    return jsonify({"meta": _req_meta(), "response_type": "object", "data": data}), status


def ok_list(items, total, limit, offset):
    meta = _req_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_resp(e):
    return jsonify({"meta": _req_meta(), "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


# --- In-memory store ---
class Store:
    def __init__(self):
        self.seq = 0
        self.venues = {}
        self.sponsors = {}
        self.assets = {}
        self.rights_windows = {}
        self.contracts = {}
        self.grants = {}
        self.deliverables = {}
        self.evidence = {}
        self.credits = {}
        self.invoices = {}
        self.reports = {}
        self.opportunities = {}


db = Store()


def create_record(coll, fields):
    db.seq += 1
    rec = dict(fields)
    rec["id"] = new_uuid()
    rec["created_at"] = now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = db.seq
    coll[rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# --- Request helpers ---
def authn():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise e_unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise e_forbidden()


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise e_invalid_request("Request body must be a JSON object")
    return data


def check_shape(body, spec):
    """spec: {field: (type_tag, required)}. type_tag: 'str' | 'int' | 'num' | 'date' | 'enum:A|B'."""
    for k in body:
        if k not in spec:
            raise e_invalid_request(f"Unknown field: {k}")
    for name, (tag, required) in spec.items():
        v = body.get(name)
        if v is None:
            if required:
                raise e_invalid_request(f"Missing required field: {name}")
            continue
        if tag == "str":
            if not isinstance(v, str):
                raise e_invalid_request(f"Field {name} must be a string")
        elif tag == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                raise e_invalid_request(f"Field {name} must be an integer")
        elif tag == "num":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise e_invalid_request(f"Field {name} must be a number")
        elif tag == "date":
            if not isinstance(v, str):
                raise e_invalid_request(f"Field {name} must be an ISO date string")
            try:
                datetime.date.fromisoformat(v)
            except ValueError:
                raise e_invalid_request(f"Field {name} must be an ISO date string")
        elif tag.startswith("enum:"):
            if v not in tag[5:].split("|"):
                raise e_invalid_request(f"Field {name} has an invalid value")


def pagination_params():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise e_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise e_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise e_invalid_request("limit out of range [1, 100]")
    if offset < 0:
        raise e_invalid_request("offset must be >= 0")
    return limit, offset


def do_list(records, predicates, limit, offset):
    items = sorted(records, key=lambda r: r["_seq"])
    for p in predicates:
        if p is not None:
            items = [r for r in items if p(r)]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


def qfilter(field):
    """Equality filter from query string; None when the param is absent."""
    qv = request.args.get(field)
    if qv is None:
        return None
    return lambda r: str(r.get(field)) == qv


def rhu(value):
    """Round half-up to whole cents (integer)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
