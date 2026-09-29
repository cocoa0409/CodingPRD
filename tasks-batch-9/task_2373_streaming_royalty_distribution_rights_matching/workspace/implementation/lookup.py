"""Referenced-record resolution (§2.11) and list filtering (§2.3)."""

from flask import request

from db import db
from errors import ApiError


def _resolve(collection, identifier, error_id):
    record = collection.get(identifier) if isinstance(identifier, str) else None
    if record is None:
        raise ApiError(error_id)
    return record


def holder(identifier):
    return _resolve(db.rights_holders, identifier, "ERR_RIGHTS_HOLDER_NOT_FOUND")


def work(identifier):
    return _resolve(db.works, identifier, "ERR_WORK_NOT_FOUND")


def period(identifier):
    return _resolve(db.periods, identifier, "ERR_PERIOD_NOT_FOUND")


def batch(identifier):
    return _resolve(db.batches, identifier, "ERR_USAGE_BATCH_NOT_FOUND")


def usage_line(identifier):
    return _resolve(db.usage_lines, identifier, "ERR_USAGE_LINE_NOT_FOUND")


def registration(identifier):
    return _resolve(db.registrations, identifier, "ERR_REGISTRATION_NOT_FOUND")


def pool(identifier):
    return _resolve(db.pools, identifier, "ERR_POOL_NOT_FOUND")


def statement(identifier):
    return _resolve(db.statements, identifier, "ERR_STATEMENT_NOT_FOUND")


def statement_line(identifier):
    return _resolve(db.statement_lines, identifier, "ERR_STATEMENT_LINE_NOT_FOUND")


def engagement(identifier):
    return _resolve(db.engagements, identifier, "ERR_ENGAGEMENT_NOT_FOUND")


def rate_schedule(identifier):
    return _resolve(db.rate_schedules, identifier, "ERR_RATE_SCHEDULE_NOT_FOUND")


# --------------------------------------------------------------------------
# list filters
# --------------------------------------------------------------------------

def apply_filters(records, spec):
    """spec maps a query-parameter name to a getter over the record.

    Filters are equality comparisons on the string form of the field and
    combine conjunctively; an omitted parameter constrains nothing.
    """
    result = list(records)
    for name, getter in spec.items():
        raw = request.args.get(name)
        if raw is None:
            continue
        kept = []
        for record in result:
            value = getter(record)
            if value is None:
                continue
            if str(value) == raw:
                kept.append(record)
        result = kept
    return result


def field(name):
    return lambda record: record.get(name)
