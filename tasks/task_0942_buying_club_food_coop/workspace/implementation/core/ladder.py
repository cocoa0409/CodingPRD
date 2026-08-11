"""The single global validation ladder (PRD §2.9), rung by rung.

Every handler calls these helpers in ascending rung order.  The first one that
fails raises ApiError and the request ends there, with no side effect performed.
"""

from functools import wraps

from flask import request

from . import clock
from .constants import (COORDINATOR_MIN_TIER_RANK, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX,
                        PAGE_LIMIT_MIN, PAGE_OFFSET_DEFAULT, ROLES)
from .errors import ApiError
from .store import DB

# ---------------------------------------------------------------------------
# §2.8 reference resolution maps
# ---------------------------------------------------------------------------

PATH_SEGMENTS = {
    "member_id": ("Member", "ERR_MEMBER_NOT_FOUND"),
    "drop_point_id": ("DropPoint", "ERR_DROP_POINT_NOT_FOUND"),
    "item_id": ("Item", "ERR_ITEM_NOT_FOUND"),
    "price_version_id": ("PriceVersion", "ERR_PRICE_VERSION_NOT_FOUND"),
    "cycle_id": ("Cycle", "ERR_CYCLE_NOT_FOUND"),
    "route_run_id": ("RouteRun", "ERR_ROUTE_RUN_NOT_FOUND"),
    "drop_run_id": ("DropRun", "ERR_DROP_RUN_NOT_FOUND"),
    "member_order_id": ("MemberOrder", "ERR_MEMBER_ORDER_NOT_FOUND"),
    "order_line_id": ("OrderLine", "ERR_ORDER_LINE_NOT_FOUND"),
    "case_aggregate_id": ("CaseAggregate", "ERR_CASE_AGGREGATE_NOT_FOUND"),
    "receipt_line_id": ("ReceiptLine", "ERR_RECEIPT_LINE_NOT_FOUND"),
    "substitution_offer_id": ("SubstitutionOffer", "ERR_SUBSTITUTION_OFFER_NOT_FOUND"),
    "pallet_id": ("Pallet", "ERR_PALLET_NOT_FOUND"),
    "payment_id": ("Payment", "ERR_PAYMENT_NOT_FOUND"),
    "drop_reconciliation_id": ("DropReconciliation", "ERR_RECONCILIATION_NOT_FOUND"),
    "commission_accrual_id": ("CommissionAccrual", "ERR_COMMISSION_ACCRUAL_NOT_FOUND"),
    "volunteer_shift_id": ("VolunteerShift", "ERR_VOLUNTEER_SHIFT_NOT_FOUND"),
    "credit_grant_id": ("CreditGrant", "ERR_CREDIT_GRANT_NOT_FOUND"),
}

BODY_KEYS = dict(PATH_SEGMENTS)
BODY_KEYS.update({
    "route_id": ("Route", "ERR_ROUTE_NOT_FOUND"),
    "home_drop_point_id": ("DropPoint", "ERR_DROP_POINT_NOT_FOUND"),
    "coordinator_member_id": ("Member", "ERR_MEMBER_NOT_FOUND"),
    "substitute_item_id": ("Item", "ERR_ITEM_NOT_FOUND"),
    "target_cycle_id": ("Cycle", "ERR_CYCLE_NOT_FOUND"),
    "target_drop_run_id": ("DropRun", "ERR_DROP_RUN_NOT_FOUND"),
})


# ---------------------------------------------------------------------------
# request context and rungs 1-3
# ---------------------------------------------------------------------------

class Ctx(object):
    __slots__ = ("role", "user_id", "body", "args")

    def __init__(self, role, user_id, body, args):
        self.role = role
        self.user_id = user_id
        self.body = body
        self.args = args

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_coordinator(self):
        return self.role == "DropCoordinator"


def _read_body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def endpoint(roles):
    """Rungs 1-3: headers present, role known, role authorised for this route."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(**path_params):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip() or not role or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")
            ctx = Ctx(role, user_id, _read_body(), request.args)
            return fn(ctx, **path_params)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# rung 4 — path ids, left to right
# ---------------------------------------------------------------------------

def path_row(segment, value):
    kind, err = PATH_SEGMENTS[segment]
    row = DB.get(kind, value)
    if row is None:
        raise ApiError(err)
    return row


# ---------------------------------------------------------------------------
# rung 5 — body foreign keys, in declared input order
# ---------------------------------------------------------------------------

def body_fk(ctx, key, required=True):
    """Resolve a body foreign key.  Absent + optional -> None; absent + required
    -> None too (rung 7 reports the missing field later)."""
    if key not in ctx.body or ctx.body[key] is None:
        return None
    kind, err = BODY_KEYS[key]
    row = DB.get(kind, ctx.body[key])
    if row is None:
        raise ApiError(err)
    return row


# ---------------------------------------------------------------------------
# rung 6 — pagination
# ---------------------------------------------------------------------------

def pagination(ctx):
    raw_limit = ctx.args.get("limit")
    raw_offset = ctx.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw_limit).strip() != str(limit):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(raw_offset).strip() != str(offset):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


# ---------------------------------------------------------------------------
# rung 7 — required fields and declared types
# ---------------------------------------------------------------------------

def _fail_validation(message):
    raise ApiError("ERR_VALIDATION", message)


def req_str(ctx, key, non_empty=True):
    value = ctx.body.get(key)
    if not isinstance(value, str):
        _fail_validation("%s is required and must be a string." % key)
    if non_empty and not value.strip():
        _fail_validation("%s must be non-empty." % key)
    return value


def opt_str(ctx, key, non_empty=True, default=None):
    if key not in ctx.body or ctx.body[key] is None:
        return default
    return req_str(ctx, key, non_empty)


def req_int(ctx, key, minimum=None, maximum=None):
    value = ctx.body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail_validation("%s is required and must be an integer." % key)
    if minimum is not None and value < minimum:
        _fail_validation("%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _fail_validation("%s must be at most %s." % (key, maximum))
    return value


def opt_int(ctx, key, minimum=None, maximum=None, default=None):
    if key not in ctx.body or ctx.body[key] is None:
        return default
    return req_int(ctx, key, minimum, maximum)


def req_number(ctx, key, minimum_exclusive=None):
    value = ctx.body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail_validation("%s is required and must be a number." % key)
    if minimum_exclusive is not None and not value > minimum_exclusive:
        _fail_validation("%s must be greater than %s." % (key, minimum_exclusive))
    return value


def req_bool(ctx, key):
    value = ctx.body.get(key)
    if not isinstance(value, bool):
        _fail_validation("%s is required and must be a boolean." % key)
    return value


def opt_bool(ctx, key, default=None):
    if key not in ctx.body or ctx.body[key] is None:
        return default
    return req_bool(ctx, key)


def req_instant(ctx, key):
    """A required timestamp field.  The caller's exact string is preserved."""
    raw = ctx.body.get(key)
    if not isinstance(raw, str) or not raw.strip():
        _fail_validation("%s is required and must be an ISO 8601 instant." % key)
    parsed = clock.parse(raw)
    if parsed is None:
        _fail_validation("%s must be an ISO 8601 instant." % key)
    return raw, parsed


def req_id(ctx, key):
    """A required foreign-key field: present and a string."""
    value = ctx.body.get(key)
    if not isinstance(value, str) or not value.strip():
        _fail_validation("%s is required." % key)
    return value


# ---------------------------------------------------------------------------
# rung 8 — enum membership
#
# CLOSED IFF-LIST.  Exactly these fields route an out-of-range value to
# ERR_INVALID_ENUM: the body enums tier, new_tier, temp_class, remainder_policy,
# substitution_pref, payout_mode, destination and simulated_outcome, and the
# enum-valued list filters status, payment_status, kind, temp_class, tier and
# source.  NO OTHER FIELD ROUTES HERE — every other membership-shaped failure
# lands on the rung the ladder assigns it (rung 7 ERR_VALIDATION for shape,
# rung 33 ERR_INVALID_QUANTITY for quantity, and so on), and free-form filters
# (ids, code, sku) never error at all: an unmatched value yields an empty page.
# ---------------------------------------------------------------------------

def enum_body(ctx, key, members, required=False, default=None):
    if key not in ctx.body or ctx.body[key] is None:
        if required:
            _fail_validation("%s is required." % key)
        return default
    value = ctx.body[key]
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_ENUM", "%s must be one of %s." % (key, ", ".join(members)))
    if value not in members:
        raise ApiError("ERR_INVALID_ENUM", "%s must be one of %s." % (key, ", ".join(members)))
    return value


def enum_filter(ctx, key, members):
    value = ctx.args.get(key)
    if value is None:
        return None
    if value not in members:
        raise ApiError("ERR_INVALID_ENUM", "%s must be one of %s." % (key, ", ".join(members)))
    return value


def free_filter(ctx, key):
    """A free-form filter: never validated, never an error, just a match."""
    return ctx.args.get(key)


# ---------------------------------------------------------------------------
# cycle resolution, used by the global write gate
# ---------------------------------------------------------------------------

def cycle_of(row):
    if row is None:
        return None
    kind = row["_kind"]
    if kind == "Cycle":
        return row
    if kind in ("RouteRun", "DropRun"):
        return DB.get("Cycle", row["cycle_id"])
    if kind == "MemberOrder":
        return cycle_of(DB.get("DropRun", row["drop_run_id"]))
    if kind == "OrderLine":
        return cycle_of(DB.get("MemberOrder", row["member_order_id"]))
    if kind in ("CaseAggregate", "ReceiptLine", "Pallet"):
        return cycle_of(DB.get("RouteRun", row["route_run_id"]))
    if kind == "SubstitutionOffer":
        return cycle_of(DB.get("OrderLine", row["order_line_id"]))
    if kind == "Payment":
        return cycle_of(DB.get("MemberOrder", row["member_order_id"]))
    if kind in ("DropReconciliation", "CommissionAccrual", "VolunteerShift"):
        return cycle_of(DB.get("DropRun", row["drop_run_id"]))
    return None


def drop_run_of(row):
    if row is None:
        return None
    kind = row["_kind"]
    if kind == "DropRun":
        return row
    if kind == "MemberOrder":
        return DB.get("DropRun", row["drop_run_id"])
    if kind == "OrderLine":
        return drop_run_of(DB.get("MemberOrder", row["member_order_id"]))
    if kind == "SubstitutionOffer":
        return drop_run_of(DB.get("OrderLine", row["order_line_id"]))
    if kind in ("DropReconciliation", "CommissionAccrual", "VolunteerShift"):
        return DB.get("DropRun", row["drop_run_id"])
    return None


# ---------------------------------------------------------------------------
# rungs 9-13 — the ordered write gates
# ---------------------------------------------------------------------------

def gate_cycle_closed(*targets):
    """Rung 9 — GLOBAL WRITE GATE."""
    for target in targets:
        cyc = cycle_of(target)
        if cyc is not None and cyc["status"] == "CLOSED":
            raise ApiError("ERR_CYCLE_CLOSED")


def gate_membership(member):
    """Rung 10 — MEMBERSHIP GATE."""
    if member is not None and member["status"] == "LAPSED":
        raise ApiError("ERR_MEMBERSHIP_LAPSED")


def gate_coordinator(ctx):
    """Rung 11 — COORDINATOR GATE."""
    if not ctx.is_coordinator:
        return
    member = DB.get("Member", ctx.user_id)
    if member is None or member["tier_rank"] < COORDINATOR_MIN_TIER_RANK:
        raise ApiError("ERR_COORDINATOR_INELIGIBLE")


def posted_reconciliation(drop_run):
    if drop_run is None:
        return None
    for recon in DB.drop_reconciliations.values():
        if recon["drop_run_id"] == drop_run["id"] and recon["status"] == "POSTED":
            return recon
    return None


def gate_posted_ledger(*drop_runs):
    """Rung 12 — POSTED LEDGER GATE."""
    for drop_run in drop_runs:
        if posted_reconciliation(drop_run) is not None:
            raise ApiError("ERR_RECONCILIATION_POSTED")


def gate_cycle_lock(cycle):
    """Rung 13 — CYCLE LOCK GATE (member order and order-line writes)."""
    if cycle is None or cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_LOCKED")


# ---------------------------------------------------------------------------
# rung 14 — the cutoff
# ---------------------------------------------------------------------------

def rung_cutoff(cycle):
    if cycle["status"] != "OPEN":
        return
    if clock.now() >= clock.parse(cycle["cutoff_at"]):
        raise ApiError("ERR_CUTOFF_PASSED")


# ---------------------------------------------------------------------------
# rung 25 — optimistic concurrency
# ---------------------------------------------------------------------------

def rung_occ(ctx, key, parent):
    expected = ctx.body.get(key)
    if parent["version"] != expected:
        raise ApiError("ERR_STALE_VERSION")


# ---------------------------------------------------------------------------
# rungs 26-27 — ownership, checked after state and OCC
# ---------------------------------------------------------------------------

def rung_order_owner(ctx, order):
    if ctx.is_member and order["member_id"] != ctx.user_id:
        raise ApiError("ERR_NOT_ORDER_OWNER")


def rung_drop_coordinator(ctx, drop_run):
    if ctx.is_coordinator and drop_run.get("coordinator_member_id") != ctx.user_id:
        raise ApiError("ERR_NOT_DROP_COORDINATOR")
