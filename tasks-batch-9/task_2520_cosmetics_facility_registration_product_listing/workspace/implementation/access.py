"""Authentication, RBAC, ownership and the shared rejection-precedence pipeline.

PRD §2.8 fixes one normative order in which rejections are evaluated.  Every
handler registers its checks with the rank the PRD assigns them and the pipeline
runs them in that order, so precedence is a property of this module rather than
of the order in which any individual handler happens to be written.
"""

from flask import request

import domain
import store
from errors import ApiError

# ------------------------------------------------------------ precedence ranks
R_HEADERS = 1
R_ROLE = 2
R_FACILITY = 3
R_RESPONSIBLE_PERSON = 4
R_LISTING = 5
R_SUBSTANTIATION = 6
R_EVENT = 7
R_INSPECTION = 8
R_RECALL = 9
R_WITHDRAWAL = 10
R_OWNERSHIP_CHANGE = 11
R_RECORD = 12
R_OWNER = 13
R_INVALID = 14
R_CATEGORY = 15
R_WINDOW_BOUNDS = 16
R_STALE_FACILITY = 17
R_STALE_LISTING = 18
R_STALE_RECALL = 19
R_NOT_REGISTERED = 20
R_FROZEN = 21
R_STATE_FACILITY = 22
R_STATE_OWNERSHIP = 23
R_STATE_LISTING = 24
R_STATE_SUBSTANTIATION = 25
R_STATE_EVENT = 26
R_STATE_INSPECTION = 27
R_STATE_RECALL = 28
R_STATE_WITHDRAWAL = 29
R_SEGREGATION = 30
R_NOT_ADEQUATE = 31
R_ALLERGEN = 32
R_PROFESSIONAL_USE = 33
R_LABEL_CONTACT = 34
R_NO_REVIEW_ITEMS = 35
R_FULL_REVIEW_REQUIRED = 36
R_RENEWAL_WINDOW = 37
R_GRACE = 38
R_RECEIVED_FUTURE = 39
R_INSPECTION_PERIOD = 40
R_RESPONSE_WINDOW = 41
R_BUFFER = 42
R_OVERLAP = 43
R_LOT_WINDOW = 44
R_DUPLICATE_INGREDIENT = 45
R_ABBREVIATED = 46
R_PLAN_ROUNDS = 47
R_OPEN_RECALL = 48
R_SAME_PERSON = 49
R_RECORD_MISMATCH = 50
R_RECORD_NOT_IN_WITHDRAWAL = 51
R_NO_RECORDS = 52
R_DESIGNATION_CAP = 53
R_LOT_CAPACITY = 54
R_RECOVERY_OUTSTANDING = 55
R_REVERSAL = 56

OWNERSHIP_ROLES = ("FacilityRegistrant", "ResponsiblePersonAgent")


class Auth(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """PRD §2.1 rank 1 — both identity headers must be present and non-blank."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return Auth(user_id.strip(), role.strip())


def authorize(*roles):
    """Ranks 1 then 2 — unknown role and unauthorized role are both 403."""
    auth = authenticate()
    if auth.role not in domain.ROLES:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Unknown role '%s'." % auth.role)
    allowed = roles[0] if len(roles) == 1 and isinstance(roles[0], (list, tuple)) else roles
    if auth.role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return auth


class Ctx(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value

    def set(self, key, value):
        self[key] = value
        return value


class Checks(object):
    """Collects checks with their PRD §2.8 rank and runs them in that order."""

    def __init__(self):
        self._items = []

    def add(self, rank, fn):
        self._items.append((rank, len(self._items), fn))
        return self

    def run(self):
        for _rank, _index, fn in sorted(self._items, key=lambda t: (t[0], t[1])):
            fn()


# ------------------------------------------------------------------ resolvers
def need(kind, rid, error_id):
    record = store.get(kind, rid)
    if record is None:
        raise ApiError(error_id)
    return record


def need_facility(fid):
    return need("facilities", fid, "ERR_FACILITY_NOT_FOUND")


def need_responsible_person(rid):
    return need("responsible_persons", rid, "ERR_RESPONSIBLE_PERSON_NOT_FOUND")


def need_listing(lid):
    return need("listings", lid, "ERR_LISTING_NOT_FOUND")


def need_substantiation(sid):
    return need("substantiations", sid, "ERR_SUBSTANTIATION_NOT_FOUND")


def need_event(eid):
    return need("adverse_events", eid, "ERR_ADVERSE_EVENT_NOT_FOUND")


def need_inspection(iid, facility_id=None):
    engagement = need("inspections", iid, "ERR_INSPECTION_NOT_FOUND")
    if facility_id is not None and engagement["facility_id"] != facility_id:
        # PRD §2.9: a child that does not resolve within its parent is not found.
        raise ApiError("ERR_INSPECTION_NOT_FOUND")
    return engagement


def need_recall(rid):
    return need("recalls", rid, "ERR_RECALL_ACTION_NOT_FOUND")


def need_withdrawal(wid):
    return need("withdrawals", wid, "ERR_WITHDRAWAL_NOT_FOUND")


def need_ownership_change(oid):
    return need("ownership_changes", oid, "ERR_OWNERSHIP_CHANGE_NOT_FOUND")


def need_record(rid):
    return need("distribution_records", rid, "ERR_DISTRIBUTION_RECORD_NOT_FOUND")


# ------------------------------------------------------------------ ownership
def check_owner(auth, facility_id=None, responsible_person_id=None):
    """PRD §2.1 rank 13.  Opaque roles are never ownership-checked; each
    entity-backed role is compared against the reference its ancestry exposes."""
    if auth.role == "FacilityRegistrant" and facility_id is not None:
        if auth.user_id != facility_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    elif auth.role == "ResponsiblePersonAgent" and responsible_person_id is not None:
        if auth.user_id != responsible_person_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")


def owner_of_listing(auth, listing):
    check_owner(auth, facility_id=listing["facility_id"],
                responsible_person_id=listing["responsible_person_id"])


def state_error(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)
