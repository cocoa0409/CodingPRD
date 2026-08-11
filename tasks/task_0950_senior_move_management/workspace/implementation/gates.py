"""The one global 73-rung validation ladder, expressed as twelve ordered gates.

Gates 1 and 2 are mechanical and generic and live here in full. Gates 3 to 12
are endpoint-specific; this module exposes them as helpers that each route calls
in ladder order. Read endpoints call gates 1 and 2 only.
"""

from flask import request

import constants as K
import derive
import store
from errors import ApiError
from util import is_datetime_string, is_date_string


# ---------------------------------------------------------------------------
# request context
# ---------------------------------------------------------------------------

class Req(object):
    def __init__(self, role, user_id, body, args):
        self.role = role
        self.user_id = user_id
        self.body = body
        self.args = args


POSITIVE_FIELDS = {
    "quoted_cents", "list_price_cents", "gross_sale_price_cents",
    "truck_capacity_cft", "truck_count", "footprint_linear_inches",
    "volume_cft", "nominal_linear_inches", "nominal_volume_cft",
}

# `resolution` is enum-typed only where an enum is declared for it, namely the
# family-hold resolve action (KEEP / RELEASE). The `resolution` body field of
# POST /invoices/{id}/resolve-dispute is free text and is NOT enum-checked.
ENUM_FIELD_SCOPE_EXCEPTIONS = {"resolution"}


def _json_body():
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "nes":
        return isinstance(value, str) and value.strip() != ""
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "datetime":
        return is_datetime_string(value)
    if kind == "date":
        return is_date_string(value)
    if kind == "list":
        return isinstance(value, list)
    return True


def preflight(roles, required=(), optional=(), is_list=False, enum_fields=None):
    """Gate 1 - ladder rungs 1 through 7."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # rung 1
    if role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER")
    # rung 2
    if role not in K.ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    # rung 3
    if role in K.ENTITY_BACKED_ROLES and (user_id is None or user_id.strip() == ""):
        raise ApiError("ERR_MISSING_USER_ID")
    # rung 4
    if role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    body = _json_body()
    args = request.args

    # rung 5 - required presence and declared type, then domain positivity
    for name, kind in required:
        if name not in body or body[name] is None:
            raise ApiError("ERR_VALIDATION", "Field '%s' is required." % name)
        if not _type_ok(body[name], kind):
            raise ApiError("ERR_VALIDATION", "Field '%s' has the wrong type." % name)
    for name, kind in optional:
        if name in body and body[name] is not None and not _type_ok(body[name], kind):
            raise ApiError("ERR_VALIDATION", "Field '%s' has the wrong type." % name)
    for name in POSITIVE_FIELDS:
        if name in body and isinstance(body[name], (int, float)) and not isinstance(body[name], bool):
            if body[name] <= 0:
                raise ApiError("ERR_VALIDATION", "Field '%s' must be greater than zero." % name)

    # rung 6 - enum membership, restricted to the twenty declared enum fields
    allowed = K.ENUMS if enum_fields is None else {k: K.ENUMS[k] for k in enum_fields}
    for name, members in allowed.items():
        if name in ENUM_FIELD_SCOPE_EXCEPTIONS and (enum_fields is None or name not in enum_fields):
            continue
        if name in body and body[name] is not None and body[name] not in members:
            raise ApiError("ERR_INVALID_ENUM", "Field '%s' is not a declared member." % name)
        if name in args and args.get(name) not in members:
            raise ApiError("ERR_INVALID_ENUM", "Filter '%s' is not a declared member." % name)

    # rung 7 - pagination bounds
    if is_list:
        parse_pagination(args)

    return Req(role, user_id, body, args)


def parse_pagination(args):
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            raise ApiError("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            raise ApiError("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be zero or greater.")
    return limit, offset


# ---------------------------------------------------------------------------
# gate 2 - existence. Path ids first (left to right), then body foreign keys in
# the declared rung order 8 through 21.
# ---------------------------------------------------------------------------

PATH_ERROR = {
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "clients": "ERR_CLIENT_NOT_FOUND",
    "portal_parties": "ERR_PARTY_NOT_FOUND",
    "authority_records": "ERR_AUTHORITY_NOT_FOUND",
    "destination_residences": "ERR_RESIDENCE_NOT_FOUND",
    "destination_rooms": "ERR_ROOM_NOT_FOUND",
    "inventory_items": "ERR_ITEM_NOT_FOUND",
    "family_holds": "ERR_HOLD_NOT_FOUND",
    "sort_plans": "ERR_PLAN_NOT_FOUND",
    "move_day_plans": "ERR_PLAN_NOT_FOUND",
    "crew_members": "ERR_CREW_RECORD_NOT_FOUND",
    "crew_assignments": "ERR_CREW_RECORD_NOT_FOUND",
    "time_entries": "ERR_CREW_RECORD_NOT_FOUND",
    "vendors": "ERR_VENDOR_RECORD_NOT_FOUND",
    "vendor_assignments": "ERR_VENDOR_RECORD_NOT_FOUND",
    "consignment_lots": "ERR_LOT_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "invoice_lines": "ERR_INVOICE_NOT_FOUND",
    "milestones": "ERR_TIMELINE_RECORD_NOT_FOUND",
    "unpack_sessions": "ERR_TIMELINE_RECORD_NOT_FOUND",
    "punch_list_items": "ERR_TIMELINE_RECORD_NOT_FOUND",
}

# ordered by ladder rung
BODY_FK_RUNGS = [
    (8, ["engagement_id"], "engagements", "ERR_ENGAGEMENT_NOT_FOUND"),
    (9, ["client_id"], "clients", "ERR_CLIENT_NOT_FOUND"),
    (10, ["holder_party_id", "approved_by_party_id", "raised_by_party_id",
          "resolved_by_party_id", "signed_off_by_party_id", "completed_by_party_id",
          "acting_party_id"], "portal_parties", "ERR_PARTY_NOT_FOUND"),
    (12, ["destination_residence_id"], "destination_residences", "ERR_RESIDENCE_NOT_FOUND"),
    (13, ["assigned_room_id"], "destination_rooms", "ERR_ROOM_NOT_FOUND"),
    (14, ["inventory_item_id", "item_ids"], "inventory_items", "ERR_ITEM_NOT_FOUND"),
    (16, ["move_day_plan_id"], "move_day_plans", "ERR_PLAN_NOT_FOUND"),
    (17, ["crew_member_id", "crew_assignment_id", "replaces_assignment_id"],
     "crew_assignments", "ERR_CREW_RECORD_NOT_FOUND"),
    (18, ["vendor_id"], "vendors", "ERR_VENDOR_RECORD_NOT_FOUND"),
    (19, ["source_consignment_lot_id"], "consignment_lots", "ERR_LOT_NOT_FOUND"),
    (20, ["invoice_id"], "invoices", "ERR_INVOICE_NOT_FOUND"),
    (21, ["unpack_session_id"], "unpack_sessions", "ERR_TIMELINE_RECORD_NOT_FOUND"),
]

RUNG17_COLLECTION = {
    "crew_member_id": "crew_members",
    "crew_assignment_id": "crew_assignments",
    "replaces_assignment_id": "crew_assignments",
}


def path_record(collection, record_id):
    record = store.get(collection, record_id)
    if record is None:
        raise ApiError(PATH_ERROR[collection])
    return record


def resolve_body_fks(body):
    """Walk rungs 8 through 21 over whatever foreign keys the body carries."""
    resolved = {}
    for _rung, fields, collection, error_id in BODY_FK_RUNGS:
        for field in fields:
            if field not in body or body[field] is None:
                continue
            target = RUNG17_COLLECTION.get(field, collection)
            if field == "item_ids":
                if not isinstance(body[field], list):
                    continue
                rows = []
                for item_id in body[field]:
                    row = store.get("inventory_items", item_id)
                    if row is None:
                        raise ApiError(error_id)
                    rows.append(row)
                resolved[field] = rows
                continue
            row = store.get(target, body[field])
            if row is None:
                raise ApiError(error_id)
            resolved[field] = row
    return resolved


# ---------------------------------------------------------------------------
# gate 3 - engagement lifecycle (rungs 22 to 24)
# ---------------------------------------------------------------------------

def gate3(engagement, on_hold_exempt=False):
    if engagement is None:
        return
    if engagement["status"] == "CLOSED":
        raise ApiError("ERR_ENGAGEMENT_CLOSED")
    if engagement["status"] == "CANCELLED":
        raise ApiError("ERR_ENGAGEMENT_CANCELLED")
    if engagement["status"] == "ON_HOLD" and not on_hold_exempt:
        raise ApiError("ERR_ENGAGEMENT_ON_HOLD")


# ---------------------------------------------------------------------------
# gate 4 - actor authority (rungs 25 to 30)
# ---------------------------------------------------------------------------

def party_of_engagement(engagement_id, party_id):
    party = store.get("portal_parties", party_id)
    if party is None:
        return None
    return party if party["engagement_id"] == engagement_id else None


def gate4_ownership(req, engagement=None, vendor_id=None, client_id=None,
                    crew_member_id=None):
    """Rung 25."""
    role = req.role
    if role == "CLIENT":
        if client_id is not None:
            if req.user_id != client_id:
                raise ApiError("ERR_ACTOR_NOT_OWNER")
        elif engagement is not None:
            if req.user_id != engagement["client_id"]:
                raise ApiError("ERR_ACTOR_NOT_OWNER")
    elif role in ("FAMILY_MEMBER", "POWER_OF_ATTORNEY"):
        if engagement is not None:
            if party_of_engagement(engagement["id"], req.user_id) is None:
                raise ApiError("ERR_ACTOR_NOT_OWNER")
    elif role == "VENDOR":
        if vendor_id is not None and req.user_id != vendor_id:
            raise ApiError("ERR_ACTOR_NOT_OWNER")
    elif role == "CREW_LEAD":
        if crew_member_id is not None:
            if req.user_id != crew_member_id:
                raise ApiError("ERR_ACTOR_NOT_OWNER")
        elif engagement is not None:
            if not _crew_lead_on_engagement(req.user_id, engagement):
                raise ApiError("ERR_ACTOR_NOT_OWNER")


def _crew_lead_on_engagement(user_id, engagement):
    plan = derive.move_day_plan_of(engagement["id"])
    if plan is None:
        return False
    for assignment in derive.assignments_of_plan(plan["id"]):
        if assignment["crew_member_id"] != user_id:
            continue
        if assignment["status"] not in derive.CREW_TERMINAL_STATES:
            return True
    return False


def gate4_party_membership(engagement, party_ids):
    """Rung 26 - every supplied party id belongs to the subject's engagement."""
    if engagement is None:
        return
    for party_id in party_ids:
        if party_id is None:
            continue
        party = store.get("portal_parties", party_id)
        if party is None:
            continue
        if party["engagement_id"] != engagement["id"]:
            raise ApiError("ERR_PARTY_ENGAGEMENT_MISMATCH")


DISPOSITION_FAMILY_SCOPES = ("FULL", "DISPOSITION_ONLY")
BILLING_FAMILY_SCOPES = ("FULL", "BILLING_ONLY")


def gate4_authority(req, family, subject_value=0, high_value_subject=None):
    """Rungs 27 to 30 - the delegated-authority checks, POWER_OF_ATTORNEY only."""
    if req.role != "POWER_OF_ATTORNEY":
        return
    records = derive.active_authorities_of_party(req.user_id)
    # rung 27
    if not records:
        raise ApiError("ERR_NO_ACTIVE_AUTHORITY")
    # rung 28
    wanted = DISPOSITION_FAMILY_SCOPES if family == "DISPOSITION" else BILLING_FAMILY_SCOPES
    if not any(r["authority_scope"] in wanted for r in records):
        raise ApiError("ERR_AUTHORITY_SCOPE_INSUFFICIENT")
    # rung 29
    if high_value_subject is not None and \
            high_value_subject >= K.HIGH_VALUE_DISPOSITION_THRESHOLD_CENTS:
        if not any(r["authority_scope"] == "FULL" for r in records):
            raise ApiError("ERR_HIGH_VALUE_AUTHORITY_REQUIRED")
    # rung 30
    ceiling = max(r["approval_ceiling_cents"] for r in records)
    if ceiling < subject_value:
        raise ApiError("ERR_AUTHORITY_CEILING_EXCEEDED")


# ---------------------------------------------------------------------------
# gate 5 - timeline phase (rung 31)
# ---------------------------------------------------------------------------

def gate5_phase(engagement, permitted):
    if derive.engagement_phase(engagement) not in permitted:
        raise ApiError("ERR_PHASE_NOT_PERMITTED")


# ---------------------------------------------------------------------------
# gate 6 - move-day freeze window (rungs 35, 36)
# ---------------------------------------------------------------------------

def freeze_window_entered(plan):
    if plan is None or plan.get("freeze_at_utc") is None:
        return False
    from util import parse_dt
    return parse_dt(store.now_iso()) >= parse_dt(plan["freeze_at_utc"])


def gate6_roster_frozen(plan):
    if freeze_window_entered(plan):
        raise ApiError("ERR_FREEZE_WINDOW_ENTERED")


def gate6_inventory_frozen(engagement):
    plan = derive.move_day_plan_of(engagement["id"])
    if freeze_window_entered(plan):
        raise ApiError("ERR_FREEZE_WINDOW_ENTERED")


# ---------------------------------------------------------------------------
# gate 7 - disposition lock and family hold (rungs 39 to 42)
# ---------------------------------------------------------------------------

def gate7_not_held(item):
    if derive.item_hold_state(item) != "NONE":
        raise ApiError("ERR_ITEM_UNDER_FAMILY_HOLD")


# ---------------------------------------------------------------------------
# gate 9 - billing finalisation (rungs 46, 47)
# ---------------------------------------------------------------------------

def gate9_not_finalized(engagement, error_id):
    invoice = derive.invoice_of(engagement["id"]) if engagement else None
    if invoice is not None and invoice["status"] == "FINALIZED":
        raise ApiError(error_id)


# ---------------------------------------------------------------------------
# gate 10 - state machine (rungs 48, 49)
# ---------------------------------------------------------------------------

def gate10_state(current, from_states, terminal_states=()):
    if current not in from_states:
        raise ApiError("ERR_INVALID_STATE")
    if current in terminal_states:
        raise ApiError("ERR_ALREADY_TERMINAL")


def require_state(condition):
    """An un-numbered transition precondition; gate 10 reports it as rung 48."""
    if not condition:
        raise ApiError("ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# gate 11 - optimistic concurrency (rungs 64 to 66)
# ---------------------------------------------------------------------------

def gate11_version(supplied, record, error_id):
    if supplied != record["version"]:
        raise ApiError(error_id)
