"""The validation ladder (PRD §2.6) as reusable rung helpers.

Route handlers invoke these strictly in ascending rung order; the ladder is the
single arbiter of error precedence across the whole API.
"""

import constants as K
import derive
from clock import CLOCK, parse_instant
from errors import NOT_FOUND_FOR, ApiError
from store import DB, FAMILY_COLLECTION

MISSING = object()


class Ctx:
    """Per-request context carrying the caller identity and rung state."""

    def __init__(self, request, roles):
        self.request = request
        self.roles = tuple(roles)
        self.body = None
        self._run_auth_rungs()

    # --- rungs 1-4 ---------------------------------------------------------
    def _run_auth_rungs(self):
        req = self.request
        user_id = req.headers.get("X-User-ID")
        role = req.headers.get("X-User-Role")
        # Rung 1: both headers present and non-empty.
        if not user_id or not user_id.strip() or not role or not role.strip():
            raise ApiError("ERR_UNAUTHENTICATED")
        # Rung 2: the role is one of the five declared roles.
        if role not in K.ALL_ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")
        self.user_id = user_id
        self.role = role
        # Rung 3: the endpoint's authorized-roles list contains the role.
        if role not in self.roles:
            raise ApiError("ERR_ROLE_NOT_PERMITTED")
        # Rung 4: entity-backed identity resolution.
        self.caller_member = None
        if role in (K.ROLE_MEMBER, K.ROLE_ACCOUNT_OWNER):
            member = DB.members.get(user_id)
            if member is None:
                raise ApiError("ERR_IDENTITY_UNRESOLVED")
            if role == K.ROLE_ACCOUNT_OWNER and not member["is_primary"]:
                raise ApiError("ERR_IDENTITY_UNRESOLVED")
            self.caller_member = member

    @property
    def is_scoped_caller(self):
        return self.role in (K.ROLE_MEMBER, K.ROLE_ACCOUNT_OWNER)

    @property
    def is_non_primary_member(self):
        return self.role == K.ROLE_MEMBER

    # --- rung 5 ------------------------------------------------------------
    def path(self, family, row_id):
        row = DB.get(FAMILY_COLLECTION[family], row_id)
        if row is None:
            raise ApiError(NOT_FOUND_FOR[family])
        return row

    # --- rungs 6-10 --------------------------------------------------------
    def load_body(self):
        raw = self.request.get_json(silent=True)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
        self.body = raw
        return raw

    def validate(self, spec):
        """Run body rungs 6, 7, 8, 9 and 10 in that order over the whole body.

        `spec` is an ordered list of field descriptors:
            {"name", "type", "required", "enum", "min", "max", "min_len",
             "max_len", "default", "item_type", "item_enum", "non_empty"}
        """
        body = self.body if self.body is not None else self.load_body()

        # Rung 6 -- every declared-required field is present.
        for field in spec:
            if field.get("required") and field["name"] not in body:
                raise ApiError(
                    "ERR_VALIDATION", f"Required field '{field['name']}' is missing."
                )

        # Rung 7 -- every supplied field carries its declared JSON type.
        for field in spec:
            name = field["name"]
            if name not in body:
                continue
            value = body[name]
            if value is None:
                if field.get("required") or not field.get("nullable"):
                    raise ApiError("ERR_VALIDATION", f"Field '{name}' must not be null.")
                continue
            _check_type(name, value, field)

        # Rung 8 -- enum membership, over rung 8's exhaustive closed list only.
        for field in spec:
            name = field["name"]
            if name not in body or body[name] is None:
                continue
            value = body[name]
            if field.get("enum") is not None and value not in field["enum"]:
                raise ApiError(
                    "ERR_INVALID_ENUM", f"Field '{name}' carries an undeclared value."
                )
            if field.get("item_enum") is not None:
                for item in value:
                    if item not in field["item_enum"]:
                        raise ApiError(
                            "ERR_INVALID_ENUM",
                            f"Field '{name}' contains an undeclared member.",
                        )

        # Rung 9 -- numeric range constraints.
        for field in spec:
            name = field["name"]
            if name not in body or body[name] is None:
                continue
            value = body[name]
            if field.get("min") is not None and value < field["min"]:
                raise ApiError("ERR_VALUE_OUT_OF_RANGE", f"Field '{name}' is below its minimum.")
            if field.get("max") is not None and value > field["max"]:
                raise ApiError("ERR_VALUE_OUT_OF_RANGE", f"Field '{name}' is above its maximum.")

        out = {}
        for field in spec:
            name = field["name"]
            out[name] = body.get(name, field.get("default"))
        return out

    # --- rung 12 -----------------------------------------------------------
    def own(self, account_id, member_id=MISSING):
        """Ownership scope. `member_id` MISSING marks an account-level read."""
        if not self.is_scoped_caller:
            return
        if self.caller_member["account_id"] != account_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
        if member_id is MISSING:
            return
        if self.is_non_primary_member and member_id != self.caller_member["id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # --- rungs 13-15 -------------------------------------------------------
    def write_gates(self, account, skip_suspended=False):
        if account is None:
            return
        if account["legal_hold"]:
            raise ApiError("ERR_ACCOUNT_LEGAL_HOLD")
        if account["status"] == "CANCELLED":
            raise ApiError("ERR_ACCOUNT_CANCELLED")
        if not skip_suspended and account["status"] == "SUSPENDED":
            raise ApiError("ERR_ACCOUNT_SUSPENDED")


def _check_type(name, value, field):
    declared = field["type"]
    if declared == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be an integer.")
    elif declared == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be a number.")
    elif declared == "boolean":
        if not isinstance(value, bool):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be a boolean.")
    elif declared == "string":
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be a string.")
        if field.get("min_len") is not None and len(value) < field["min_len"]:
            raise ApiError("ERR_VALIDATION", f"Field '{name}' is shorter than allowed.")
        if field.get("max_len") is not None and len(value) > field["max_len"]:
            raise ApiError("ERR_VALIDATION", f"Field '{name}' is longer than allowed.")
        if field.get("must_contain") and field["must_contain"] not in value:
            raise ApiError("ERR_VALIDATION", f"Field '{name}' is malformed.")
    elif declared == "datetime":
        if not isinstance(value, str):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be a string.")
        if parse_instant(value) is None:
            raise ApiError("ERR_VALIDATION", f"Field '{name}' is not a valid instant.")
    elif declared == "array":
        if not isinstance(value, list):
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must be an array.")
        if field.get("non_empty") and len(value) == 0:
            raise ApiError("ERR_VALIDATION", f"Field '{name}' must not be empty.")
        item_type = field.get("item_type")
        if item_type == "string":
            for item in value:
                if not isinstance(item, str):
                    raise ApiError(
                        "ERR_VALIDATION", f"Field '{name}' must contain only strings."
                    )


# --- query-parameter validation (rungs 8 and 9 on list endpoints) -----------

# ADJUDICATION -- enum error routing (recurring bug D2).
# PRD rung 8 names an exhaustive, CLOSED iff-list of fields that route to
# ERR_INVALID_ENUM. For list filters that list is exactly `status`, `severity`,
# `resource_type` and `entry_type`. NO OTHER FIELD ROUTES HERE. Deliberately
# excluded filters (`kind`, `finding_type`, `identifier_type`, `scope` is a body
# -level/query enum that IS named, ...) are handled where they are read.
ENUM_FILTERS = ("status", "severity", "resource_type", "entry_type")


def pagination(request):
    """Rung 9 on `limit` / `offset` (PRD §2.3)."""
    limit = _int_param(request, "limit", K.PAGE_LIMIT_DEFAULT)
    offset = _int_param(request, "offset", K.PAGE_OFFSET_DEFAULT)
    if limit < K.PAGE_LIMIT_MIN or limit > K.PAGE_LIMIT_MAX:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "offset must be at least 0.")
    return limit, offset


def _int_param(request, name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", f"{name} must be an integer.")


def enum_filter(request, name, members):
    """A list filter on rung 8's closed list -> ERR_INVALID_ENUM when unknown."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in members:
        raise ApiError("ERR_INVALID_ENUM", f"Filter '{name}' carries an undeclared value.")
    return raw


def plain_filter(request, name):
    """A filter NOT on rung 8's closed list: never routes to ERR_INVALID_ENUM."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def window(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total


def account_for_member(member):
    return DB.accounts.get(member["account_id"])


def account_for_profile(profile):
    return derive.account_of_profile(profile)
