"""The single, system-wide fourteen-rung validation priority ladder (PRD 2.5).

Every mutating (and every reading) endpoint registers its checks against this
one engine.  Checks are *registered* declaratively, then executed by `run()` in
strictly ascending (rung, sub, registration-order) order.  The first failure
raises and nothing below it is evaluated -- so when several rules trip on one
request, the LOWEST rung number always wins.

  1  authentication                 ERR_UNAUTHENTICATED           401
  2  role authorization             ERR_FORBIDDEN_ROLE            403
  3  resource ownership             ERR_NOT_RESOURCE_OWNER        403
  4  existence (left to right)      ERR_*_NOT_FOUND               404
  5  clinical-records write gate    ERR_RECORDS_FROZEN            409   <- pre-empts 6..14
  6  custody gate                   ERR_INMATE_NOT_IN_CUSTODY     409
  7  optimistic concurrency         ERR_STALE_*_VERSION           412
  8  payload shape                  ERR_VALIDATION / ERR_INVALID_ENUM
  9  target state                   ERR_INVALID_STATE and siblings
 10  cross-entity state             ERR_ORDER_NOT_ACTIVE, ...
 11  clinical safety                ERR_DOT_*, ERR_KOP_*, ERR_INTAKE_*
 12  segregation of duties          ERR_SEGREGATION_OF_DUTIES     403
 13  temporal windows               ERR_*_WINDOW_*, lead times
 14  caps, uniqueness, fiscal reversibility, interval occupancy
"""

from flask import request

import store
from constants import ROLES
from errors import ApiError
from timeutil import parse_dt, verbatim

# rung 8 sub-order: presence -> type/range -> enum membership
SUB_BODY = -1
SUB_REQUIRED = 0
SUB_TYPE = 1
SUB_ENUM = 2

_MISSING = object()


class Ctx(object):
    def __init__(self, roles, wants_body=False):
        self.allowed_roles = tuple(roles)
        self.role = request.headers.get("X-User-Role")
        self.user_id = request.headers.get("X-User-ID")
        self._checks = []
        self._order = 0
        self._wants_body = wants_body
        self._body_bad = False
        raw = request.get_json(silent=True, force=True)
        if raw is None:
            self.body = {}
            if request.get_data(as_text=True).strip():
                self._body_bad = True
        elif isinstance(raw, dict):
            self.body = raw
        else:
            self.body = {}
            self._body_bad = True

        # resolved rows, filled in as rung 3/4 checks execute
        self.inmate = None
        self.rows = {}

        self.at(1, self._check_auth, sub=0)
        self.at(2, self._check_role, sub=0)

    # -- registration -------------------------------------------------------
    def at(self, rung, fn, sub=0):
        self._order += 1
        self._checks.append((rung, sub, self._order, fn))
        return self

    def run(self):
        for _rung, _sub, _order, fn in sorted(self._checks, key=lambda c: (c[0], c[1], c[2])):
            fn()
        return self

    # -- rung 1 / 2 ---------------------------------------------------------
    def _check_auth(self):
        if not self.user_id or not self.role or self.role not in ROLES:
            raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid authentication headers")

    def _check_role(self):
        if self.role not in self.allowed_roles:
            raise ApiError("ERR_FORBIDDEN_ROLE",
                           "role %s may not call this endpoint" % self.role)

    @property
    def is_inmate_actor(self):
        return self.role == "Inmate"

    # -- rung 3 -------------------------------------------------------------
    def own_id(self, getter):
        """Ownership on an inmate id that may be resolved lazily."""
        def check():
            if not self.is_inmate_actor:
                return
            owner = getter()
            if owner is None:
                return                      # existence (rung 4) will report it
            if owner != self.user_id:
                raise ApiError("ERR_NOT_RESOURCE_OWNER", "resource belongs to another inmate")
        return self.at(3, check)

    # -- rung 4 -------------------------------------------------------------
    def path_inmate(self, inmate_id):
        self.own_id(lambda: inmate_id)

        def check():
            row = store.inmates.get(inmate_id)
            if row is None:
                raise ApiError("ERR_INMATE_NOT_FOUND", "inmate not found")
            self.inmate = row
        return self.at(4, check)

    def body_inmate(self, field="inmate_id"):
        self.own_id(lambda: self.body.get(field) if isinstance(self.body.get(field), str) else None)

        def check():
            value = self.body.get(field)
            if not isinstance(value, str):
                return                       # rung 8 reports missing/typed failures
            row = store.inmates.get(value)
            if row is None:
                raise ApiError("ERR_INMATE_NOT_FOUND", "inmate not found")
            self.inmate = row
        return self.at(4, check)

    def need(self, name, collection, row_id, error_id, on_found=None):
        """Register a rung-4 existence check for a sub-resource."""
        def check():
            row = collection.get(row_id) if isinstance(row_id, str) else None
            if row is None:
                raise ApiError(error_id, "%s not found" % name)
            self.rows[name] = row
            if on_found is not None:
                on_found(row)
        return self.at(4, check)

    def need_body_ref(self, name, collection, field, error_id, required=False):
        def check():
            value = self.body.get(field)
            if value is None:
                return                       # rung 8 reports a missing required ref
            if not isinstance(value, str) or value not in collection:
                raise ApiError(error_id, "%s not found" % name)
            self.rows[name] = collection[value]
        return self.at(4, check)

    def row(self, name):
        return self.rows.get(name)

    # -- rung 5 -------------------------------------------------------------
    def freeze_gate(self):
        def check():
            if self.inmate is not None and self.inmate["records_state"] != "OPEN":
                raise ApiError("ERR_RECORDS_FROZEN", "clinical records are frozen")
        return self.at(5, check)

    # -- rung 6 -------------------------------------------------------------
    def custody_gate(self):
        def check():
            if self.inmate is not None and self.inmate["custody_status"] != "IN_CUSTODY":
                raise ApiError("ERR_INMATE_NOT_IN_CUSTODY", "inmate is no longer in custody")
        return self.at(6, check)

    # -- rung 7 -------------------------------------------------------------
    def occ(self, field, target_getter, error_id):
        def check():
            supplied = self.body.get(field)
            if not isinstance(supplied, int) or isinstance(supplied, bool):
                return                       # absent / wrong type -> rung 8
            target = target_getter()
            if target is None:
                return
            if supplied != target.get("version"):
                raise ApiError(error_id, "stale version")
        return self.at(7, check)

    # -- rung 8 -------------------------------------------------------------
    def body_expected(self):
        if self._wants_body:
            return self
        self._wants_body = True

        def check():
            if self._body_bad:
                raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
        return self.at(8, check, sub=SUB_BODY)

    def require(self, *fields):
        self.body_expected()

        def check():
            for field in fields:
                if self.body.get(field, _MISSING) is _MISSING or self.body.get(field) is None:
                    raise ApiError("ERR_VALIDATION", "%s is required" % field)
        return self.at(8, check, sub=SUB_REQUIRED)

    def check_type(self, field, kind, optional=True):
        self.body_expected()

        def check():
            value = self.body.get(field, _MISSING)
            if value is _MISSING or value is None:
                return
            if kind == "string":
                if not isinstance(value, str):
                    raise ApiError("ERR_VALIDATION", "%s must be a string" % field)
            elif kind == "nonempty_string":
                if not isinstance(value, str) or value.strip() == "":
                    raise ApiError("ERR_VALIDATION", "%s must be a non-empty string" % field)
            elif kind == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ApiError("ERR_VALIDATION", "%s must be an integer" % field)
            elif kind == "boolean":
                if not isinstance(value, bool):
                    raise ApiError("ERR_VALIDATION", "%s must be a boolean" % field)
            elif kind == "datetime":
                if not isinstance(value, str) or parse_dt(value) is None:
                    raise ApiError("ERR_VALIDATION", "%s must be an ISO 8601 instant" % field)
        return self.at(8, check, sub=SUB_TYPE)

    def check_range(self, field, low, high):
        self.body_expected()

        def check():
            value = self.body.get(field, _MISSING)
            if value is _MISSING or value is None or isinstance(value, bool):
                return
            if not isinstance(value, int):
                return
            if value < low or value > high:
                raise ApiError("ERR_VALIDATION",
                               "%s must be between %s and %s inclusive" % (field, low, high))
        return self.at(8, check, sub=SUB_TYPE)

    def custom_type(self, fn):
        self.body_expected()
        return self.at(8, fn, sub=SUB_TYPE)

    def enum(self, field, domain):
        """Enum membership.  ANY enum-typed body field, named in PRD 2.5 or not,
        yields ERR_INVALID_ENUM (422) for an off-domain value."""
        self.body_expected()

        def check():
            value = self.body.get(field, _MISSING)
            if value is _MISSING or value is None:
                return
            if not isinstance(value, str):
                raise ApiError("ERR_VALIDATION", "%s must be a string" % field)
            if value not in domain:
                raise ApiError("ERR_INVALID_ENUM", "%s is not a member of its declared set" % field)
        return self.at(8, check, sub=SUB_ENUM)

    # -- rungs 9..14 --------------------------------------------------------
    def state(self, fn, sub=0):
        return self.at(9, fn, sub=sub)

    def cross_state(self, fn, sub=0):
        return self.at(10, fn, sub=sub)

    def safety(self, fn, sub=0):
        return self.at(11, fn, sub=sub)

    def segregation(self, fn, sub=0):
        return self.at(12, fn, sub=sub)

    def temporal(self, fn, sub=0):
        return self.at(13, fn, sub=sub)

    def caps(self, fn, sub=0):
        return self.at(14, fn, sub=sub)

    # -- convenience --------------------------------------------------------
    def status_in(self, row_getter, allowed, error_id="ERR_INVALID_STATE", field="status", sub=0):
        def check():
            row = row_getter()
            if row is None:
                return
            if row.get(field) not in allowed:
                raise ApiError(error_id, "%s %s does not permit this transition"
                               % (field, row.get(field)))
        return self.state(check, sub=sub)

    def dt_field(self, field):
        """Caller-supplied instant, echoed back verbatim."""
        return verbatim(self.body.get(field))
