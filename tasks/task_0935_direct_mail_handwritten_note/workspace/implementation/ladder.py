"""The single ordered validation pipeline — PRD 2.6's forty-one rungs.

Every endpoint declares which rungs apply to it; `Ctx.run()` then evaluates
rungs 1..41 in strict ascending order so that when several conditions are
violated at once the FIRST rung always wins.
"""
from flask import request

import store
from errors import ApiError
from store import db

# kind -> (store attribute, not-found error id)
KINDS = {
    "account": ("accounts", "ERR_ACCOUNT_NOT_FOUND"),
    "campaign": ("campaigns", "ERR_CAMPAIGN_NOT_FOUND"),
    "mail_job": ("mail_jobs", "ERR_MAIL_JOB_NOT_FOUND"),
    "handwriting_style": ("handwriting_styles", "ERR_RESOURCE_NOT_FOUND"),
    "template": ("templates", "ERR_RESOURCE_NOT_FOUND"),
    "mailing_list": ("mailing_lists", "ERR_RESOURCE_NOT_FOUND"),
    "list_record": ("list_records", "ERR_RESOURCE_NOT_FOUND"),
    "eddm_route": ("eddm_routes", "ERR_RESOURCE_NOT_FOUND"),
    "proof": ("proofs", "ERR_RESOURCE_NOT_FOUND"),
    "machine": ("machines", "ERR_RESOURCE_NOT_FOUND"),
    "ink_lot": ("ink_lots", "ERR_RESOURCE_NOT_FOUND"),
    "production_run": ("production_runs", "ERR_RESOURCE_NOT_FOUND"),
    "drip_schedule": ("drip_schedules", "ERR_RESOURCE_NOT_FOUND"),
    "drip_step": ("drip_steps", "ERR_RESOURCE_NOT_FOUND"),
    "ledger_entry": ("ledger_entries", "ERR_RESOURCE_NOT_FOUND"),
    "return_event": ("return_events", "ERR_RESOURCE_NOT_FOUND"),
    "reprint_request": ("reprint_requests", "ERR_RESOURCE_NOT_FOUND"),
    "blackout_date": ("blackout_dates", "ERR_RESOURCE_NOT_FOUND"),
}


def _collection(kind):
    return getattr(db, KINDS[kind][0])


class Ctx(object):
    def __init__(self, roles):
        self.allowed_roles = list(roles)
        self.role = request.headers.get("X-User-Role")
        self.user_id = request.headers.get("X-User-ID")
        self.body = {}
        self.body_malformed = False
        raw = request.get_json(silent=True)
        if raw is None:
            self.body = {}
        elif isinstance(raw, dict):
            self.body = raw
        else:
            self.body_malformed = True
        self.lookups = []
        self.resolved = {}
        self.required = []
        self.optional = []
        self.enum_specs = []
        self.range_specs = []
        self._gate_fn = None
        self._gate_exempt_compliance = False
        self._occ = None
        self._scope_fn = None
        self.checks = {}
        self.derived = {}

    # ---------------------------------------------------------- declaration
    def path(self, kind, value, alias=None):
        self.lookups.append((kind, alias or kind, "path", value))
        return self

    def fk(self, kind, field, alias=None, required=True):
        self.lookups.append((kind, alias or kind, "body:" + field, field))
        if not required:
            self.lookups[-1] = (kind, alias or kind, "obody:" + field, field)
        return self

    def fields(self, required=None, optional=None):
        self.required.extend(required or [])
        self.optional.extend(optional or [])
        return self

    def enums(self, specs):
        self.enum_specs.extend(specs)
        return self

    def ranges(self, specs):
        self.range_specs.extend(specs)
        return self

    def gate(self, fn, exempt_compliance=False):
        self._gate_fn = fn
        self._gate_exempt_compliance = exempt_compliance
        return self

    def occ(self, field, parent_getter):
        self._occ = (field, parent_getter)
        return self

    def scope(self, fn):
        self._scope_fn = fn
        return self

    def at(self, rung, fn):
        self.checks.setdefault(rung, []).append(fn)
        return self

    def get(self, alias):
        return self.resolved.get(alias)

    # ------------------------------------------------------------- evaluation
    def run(self):
        self._rung_1_2()
        self._extra(1)
        self._extra(2)
        self._rung_3()
        self._extra(3)
        self._rung_4()
        self._extra(4)
        self._rung_5()
        self._extra(5)
        self._rung_6()
        self._extra(6)
        self._rung_7()
        self._extra(7)
        self._rung_8()
        self._extra(8)
        self._rung_9_10()
        self._rung_11()
        for rung in range(11, 42):
            self._extra(rung)
        return self

    def _extra(self, rung):
        for fn in self.checks.get(rung, []):
            fn()

    # rungs 1-2 : authentication
    def _rung_1_2(self):
        if self.role is None or self.role not in store.ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")
        if self.role == "AccountOwner" and not self.user_id:
            raise ApiError("ERR_UNAUTHENTICATED")

    # rung 3 : role authorization
    def _rung_3(self):
        if self.role not in self.allowed_roles:
            raise ApiError("ERR_FORBIDDEN_ROLE")

    # rung 4 : existence — path params left to right, then body FKs in order
    def _rung_4(self):
        for kind, alias, source, value in self.lookups:
            if source == "path":
                key = value
            else:
                field = source.split(":", 1)[1]
                if field not in self.body:
                    continue          # absence is reported at rung 6
                key = self.body.get(field)
                if key is None or not isinstance(key, str):
                    continue          # wrong type is reported at rung 6
            row = _collection(kind).get(key)
            if row is None:
                raise ApiError(KINDS[kind][1])
            self.resolved[alias] = row

    # rung 5 : account scope for the one entity-backed role
    def _rung_5(self):
        if self.role != "AccountOwner" or self._scope_fn is None:
            return
        owner = self._scope_fn()
        if owner is None:
            return
        if owner != self.user_id:
            raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION")

    # rung 6 : request shape
    def _rung_6(self):
        if self.body_malformed:
            raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
        for field, kind in self.required:
            if field not in self.body:
                raise ApiError("ERR_VALIDATION", "Missing required field '%s'." % field)
            self._check_type(field, self.body[field], kind, nullable=kind.endswith("?"))
        for field, kind in self.optional:
            if field not in self.body:
                continue
            value = self.body[field]
            if value is None:
                continue
            self._check_type(field, value, kind, nullable=False)

    def _check_type(self, field, value, kind, nullable):
        base = kind[:-1] if kind.endswith("?") else kind
        if value is None:
            if nullable:
                return
            raise ApiError("ERR_VALIDATION", "Field '%s' may not be null." % field)
        if base == "str":
            if not isinstance(value, str):
                raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
        elif base == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ApiError("ERR_VALIDATION", "Field '%s' must be an integer." % field)
        elif base == "num":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ApiError("ERR_VALIDATION", "Field '%s' must be a number." % field)
        elif base == "date":
            if not isinstance(value, str) or store.parse_date(value) is None:
                raise ApiError("ERR_VALIDATION",
                               "Field '%s' must be an ISO 8601 calendar date." % field)
        elif base == "datetime":
            if not isinstance(value, str) or store.parse_instant(value) is None:
                raise ApiError("ERR_VALIDATION",
                               "Field '%s' must be an ISO 8601 datetime." % field)

    # rung 7 : enum membership (closed list, PRD 2.6)
    def _rung_7(self):
        for field, allowed in self.enum_specs:
            if field not in self.body:
                continue
            value = self.body[field]
            if value is None:
                continue
            if value not in allowed:
                raise ApiError("ERR_INVALID_ENUM",
                               "Field '%s' carries a value outside its declared set." % field)

    # rung 8 : numeric ranges (closed list, PRD 2.6)
    def _rung_8(self):
        for spec in self.range_specs:
            field, minimum, maximum, exclusive_min = spec
            if field not in self.body:
                continue
            value = self.body[field]
            if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if minimum is not None:
                if exclusive_min and not value > minimum:
                    raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                                   "Field '%s' is outside its declared range." % field)
                if not exclusive_min and value < minimum:
                    raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                                   "Field '%s' is outside its declared range." % field)
            if maximum is not None and value > maximum:
                raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                               "Field '%s' is outside its declared range." % field)

    # rungs 9-10 : the two global write gates
    def _rung_9_10(self):
        if self._gate_fn is None:
            self._extra(9)
            self._extra(10)
            return
        campaigns = self._gate_fn()
        if campaigns is None:
            campaigns = []
        elif isinstance(campaigns, dict):
            campaigns = [campaigns]
        campaigns = [c for c in campaigns if c is not None]
        if not self._gate_exempt_compliance:
            for campaign in campaigns:
                if campaign["compliance_status"] == "HOLD":
                    raise ApiError("ERR_CAMPAIGN_COMPLIANCE_HOLD")
        self._extra(9)
        for campaign in campaigns:
            if campaign["billing_status"] == "CLOSED":
                raise ApiError("ERR_CAMPAIGN_BILLING_CLOSED")
        self._extra(10)

    # rung 11 : optimistic concurrency on the parent's version
    def _rung_11(self):
        if self._occ is None:
            return
        field, parent_getter = self._occ
        parent = parent_getter()
        supplied = self.body.get(field)
        if parent is None:
            return
        if supplied != parent["version"]:
            raise ApiError("ERR_STALE_VERSION")


# --------------------------------------------------------------------------
# Shared gate resolvers — the traversal paths enumerated by PRD 2.5.
# --------------------------------------------------------------------------
def campaign_of_job(job):
    return db.campaigns.get(job["campaign_id"]) if job else None


def campaign_of_proof(proof):
    job = db.mail_jobs.get(proof["mail_job_id"]) if proof else None
    return campaign_of_job(job)


def campaign_of_run(run):
    job = db.mail_jobs.get(run["mail_job_id"]) if run else None
    return campaign_of_job(job)


def campaign_of_schedule(schedule):
    return db.campaigns.get(schedule["campaign_id"]) if schedule else None


def campaign_of_step(step):
    job = db.mail_jobs.get(step["mail_job_id"]) if step else None
    return campaign_of_job(job)


def campaign_of_record(record):
    if not record or not record.get("last_mail_job_id"):
        return None
    job = db.mail_jobs.get(record["last_mail_job_id"])
    return campaign_of_job(job)


def job_of_record(record):
    if not record or not record.get("last_mail_job_id"):
        return None
    return db.mail_jobs.get(record["last_mail_job_id"])


def account_of_record(record):
    lst = db.mailing_lists.get(record["mailing_list_id"]) if record else None
    return lst["account_id"] if lst else None
