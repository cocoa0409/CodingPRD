"""The single 32-rung validation ladder of PRD section 2.6.

The ladder is an explicit ordered check sequence.  ``RUNG_ORDER`` below is the
one and only place precedence is decided; every route registers declarative
data (path ids, body ids, a body schema) plus per-rung hooks, and ``Op.run``
walks the rungs in order and stops at the first failure.

Rung 17.5 is not a PRD rung.  PRD section 3.5 requires the site's program
posture to still be ACTIVE when an encounter is begun, but rung 14's scope list
is exhaustive and does not name ``POST /sbhc/visits/{id}/start``.  The check is
therefore run immediately after state legality (rung 17) and immediately before
the consent re-check (rung 18), which is the order PRD section 3.5 states the
three requirements in.
"""

from flask import request

import config
import fields as F
import store
from errors import ApiError

RUNG_ORDER = [
    1,     # headers present               -> ERR_UNAUTHENTICATED
    2,     # role recognised               -> ERR_UNAUTHENTICATED
    3,     # role permitted                -> ERR_ROLE_NOT_PERMITTED
    4,     # path identifiers resolve      -> 404 family
    5,     # body identifiers resolve      -> 404 family
    6,     # body well formed              -> ERR_VALIDATION
    7,     # pagination well formed        -> ERR_VALIDATION
    8,     # reporting period ordered      -> ERR_INVALID_REPORT_PERIOD
    9,     # session window well formed    -> ERR_INVALID_SESSION_WINDOW
    10,    # optimistic concurrency        -> ERR_STALE_VERSION
    11,    # ownership                     -> ERR_OWNERSHIP_VIOLATION
    12,    # self-consent permitted        -> ERR_SELF_CONSENT_NOT_PERMITTED
    13,    # segregation of duties         -> ERR_SEGREGATION_OF_DUTIES
    14,    # site posture                  -> ERR_SCHOOL_SUSPENDED
    15,    # enrollment posture            -> ERR_ENROLLMENT_NOT_ACTIVE
    16,    # exhausted-attempt guards      -> ERR_OUTREACH_LIMIT_EXCEEDED / ERR_DELIVERY_ATTEMPTS_EXHAUSTED
    17,    # state legality                -> ERR_INVALID_STATE
    17.5,  # site posture on visit start   -> ERR_SCHOOL_SUSPENDED  (PRD 3.5)
    18,    # consent on file               -> ERR_CONSENT_REQUIRED
    19,    # telehealth consent on file    -> ERR_TELEHEALTH_CONSENT_REQUIRED
    20,    # discipline match              -> ERR_DISCIPLINE_MISMATCH
    21,    # immunization posture          -> ERR_IMMUNIZATION_NON_COMPLIANT
    22,    # dose sequence                 -> ERR_DOSE_SEQUENCE
    23,    # dose uniqueness               -> ERR_DUPLICATE_DOSE
    24,    # dates not in the future       -> ERR_VALIDATION
    25,    # no-show grace elapsed         -> ERR_NO_SHOW_TOO_EARLY
    26,    # clinician slot free           -> ERR_CLINICIAN_SLOT_CONFLICT
    27,    # site capacity free            -> ERR_SCHOOL_CAPACITY_EXCEEDED
    28,    # reinstatement cap             -> ERR_REINSTATEMENT_LIMIT_EXCEEDED
    29,    # re-evaluation cap             -> ERR_REEVALUATION_LIMIT_EXCEEDED
    30,    # reschedule cap                -> ERR_RESCHEDULE_LIMIT_EXCEEDED
    31,    # acknowledgement window open   -> ERR_ACK_WINDOW_EXPIRED
    32,    # claim routing and money rules -> ERR_CLAIM_* / ERR_PAYMENT_AMOUNT_MISMATCH
]


class Op(object):
    """One API operation and everything the ladder needs to judge it."""

    def __init__(self, endpoint, roles):
        self.endpoint = endpoint
        self.roles = roles
        self.role = request.headers.get("X-User-Role")
        self.user_id = request.headers.get("X-User-ID")
        self.body = _json_body()
        self.args = request.args
        self._path_ids = []
        self._body_ids = []
        self._schema = None
        self._customs = []
        self._paginated = False
        self._hooks = {}
        self.rows = {}
        self.limit = config.PAGINATION_DEFAULT_LIMIT
        self.offset = config.PAGINATION_DEFAULT_OFFSET

    # -- declaration -------------------------------------------------------
    def path_id(self, key, collection, value, error_id, belongs_to=None):
        self._path_ids.append((key, collection, value, error_id, belongs_to))
        return self

    def body_id(self, key, collection, field_name, error_id):
        self._body_ids.append((key, collection, field_name, error_id))
        return self

    def schema(self, schema):
        self._schema = schema
        return self

    def custom(self, fn):
        self._customs.append(fn)
        return self

    def paginated(self):
        self._paginated = True
        return self

    def hook(self, rung, fn):
        self._hooks.setdefault(rung, []).append(fn)
        return self

    # -- access ------------------------------------------------------------
    def get(self, key):
        return self.rows.get(key)

    def field(self, name, default=None):
        return F.opt(self.body, name, default)

    # -- execution ---------------------------------------------------------
    def run(self):
        for rung in RUNG_ORDER:
            builtin = _BUILTINS.get(rung)
            if builtin is not None:
                builtin(self)
            for fn in self._hooks.get(rung, ()):
                fn(self)
        return self


def _json_body():
    try:
        body = request.get_json(silent=True, force=True)
    except Exception:  # pragma: no cover - defensive
        body = None
    if not isinstance(body, dict):
        return {}
    return body


# --------------------------------------------------------------------------
# Built-in rungs 1-7
# --------------------------------------------------------------------------
def _rung1_headers(op):
    if not op.user_id or not op.role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")


def _rung2_role_recognised(op):
    if op.role not in config.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")


def _rung3_role_permitted(op):
    if op.role not in op.roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not invoke %s." % (op.role, op.endpoint),
        )


def _rung4_path_ids(op):
    for key, collection, value, error_id, belongs_to in op._path_ids:
        row = store.get(collection, value)
        if row is None:
            raise ApiError(error_id, "No such %s: %s." % (key, value))
        if belongs_to is not None and not belongs_to(op, row):
            raise ApiError(error_id, "No such %s: %s." % (key, value))
        op.rows[key] = row


def _rung5_body_ids(op):
    for key, collection, field_name, error_id in op._body_ids:
        if field_name not in op.body or op.body[field_name] is None:
            continue
        row = store.get(collection, op.body[field_name])
        if row is None:
            raise ApiError(error_id, "No such %s: %s." % (key, op.body[field_name]))
        op.rows[key] = row


def _rung6_body(op):
    if op._schema is not None:
        F.check_body(op.body, op._schema)
    for fn in op._customs:
        fn(op)


def _rung7_pagination(op):
    if op._paginated:
        op.limit, op.offset = F.parse_pagination(op.args)


_BUILTINS = {
    1: _rung1_headers,
    2: _rung2_role_recognised,
    3: _rung3_role_permitted,
    4: _rung4_path_ids,
    5: _rung5_body_ids,
    6: _rung6_body,
    7: _rung7_pagination,
}
