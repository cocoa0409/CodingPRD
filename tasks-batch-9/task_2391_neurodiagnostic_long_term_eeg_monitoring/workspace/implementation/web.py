"""Endpoint plumbing: the shared blueprint, the request wrapper and lookups."""
import functools
import threading

from flask import Blueprint

import auth
import cascade
import derive
import response
from db import db
from errors import ApiError

bp = Blueprint("neurodiagnostics", __name__)

# The store is a plain dict graph and the cascade bookkeeping is per-request
# global state, so requests are serialized: the server may be threaded for
# connection handling, but only one request mutates the graph at a time.
_request_lock = threading.RLock()


class ObjectResult(object):
    def __init__(self, record, status=200, renderer=None):
        self.record = record
        self.status = status
        self.renderer = renderer

    def body(self):
        data = self.renderer(self.record) if self.renderer else derive.render(self.record)
        return response.object_body(data), self.status


class RawResult(object):
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    def body(self):
        return response.object_body(self.data), self.status


class ListResult(object):
    def __init__(self, records, limit, offset):
        self.records = records
        self.limit = limit
        self.offset = offset

    def body(self):
        page, total = response.paginate(self.records, self.limit, self.offset)
        return response.array_body(derive.render_all(page), self.limit, self.offset, total), 200


def endpoint(roles, mutating=False):
    """Wrap a handler with auth (rungs 1-2), cascades and envelope rendering."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(**kwargs):
            with _request_lock:
                user_id, role = auth.authenticate()
                auth.authorize(role, roles)
                if mutating:
                    cascade.begin_request()
                try:
                    result = handler(user_id=user_id, role=role, **kwargs)
                except Exception:
                    if mutating:
                        cascade.abort_request()
                    raise
                if mutating:
                    cascade.finalize()
                body, status = result.body()
                return response.send(body, status)

        return wrapper

    return decorator


# --- path / body identifier resolution -----------------------------------

def _lookup(collection, identifier, error_id):
    record = getattr(db, collection).get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record


def get_unit(identifier):
    return _lookup("units", identifier, "ERR_UNIT_NOT_FOUND")


def get_bed(identifier):
    return _lookup("beds", identifier, "ERR_BED_NOT_FOUND")


def get_shift(identifier):
    return _lookup("shifts", identifier, "ERR_SHIFT_NOT_FOUND")


def get_patient(identifier):
    return _lookup("patients", identifier, "ERR_PATIENT_NOT_FOUND")


def get_authorization(identifier):
    return _lookup("authorizations", identifier, "ERR_AUTHORIZATION_NOT_FOUND")


def get_admission(identifier):
    return _lookup("admissions", identifier, "ERR_ADMISSION_NOT_FOUND")


def get_taper_plan(identifier):
    return _lookup("taper_plans", identifier, "ERR_TAPER_PLAN_NOT_FOUND")


def get_study(identifier):
    return _lookup("studies", identifier, "ERR_STUDY_NOT_FOUND")


def get_alert(identifier):
    return _lookup("alerts", identifier, "ERR_ALERT_NOT_FOUND")


def get_marking(identifier):
    return _lookup("markings", identifier, "ERR_MARKING_NOT_FOUND")


def get_report(identifier):
    return _lookup("reports", identifier, "ERR_REPORT_NOT_FOUND")


def get_export(identifier):
    return _lookup("exports", identifier, "ERR_EXPORT_NOT_FOUND")


def get_case(identifier):
    return _lookup("cases", identifier, "ERR_CASE_NOT_FOUND")
