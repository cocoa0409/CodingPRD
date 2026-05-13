"""Entity-to-JSON serialization. Mostly identity, but we normalize timestamps."""

from db import db


def _ser_common(entity: dict) -> dict:
    """Copy common fields verbatim. Timestamps are already ISO strings."""
    return dict(entity)


def vehicle(row):
    if row is None:
        return None
    return _ser_common(row)


def driver(row):
    if row is None:
        return None
    return _ser_common(row)


def task_stop(row):
    if row is None:
        return None
    return _ser_common(row)


def task(row, *, include_stops: bool = True):
    if row is None:
        return None
    out = _ser_common(row)
    if include_stops:
        out["stops"] = [task_stop(s) for s in db.stops_for_task(row["id"])]
    return out


def handover(row):
    if row is None:
        return None
    return _ser_common(row)


def reading(row):
    if row is None:
        return None
    return _ser_common(row)


def alert(row):
    if row is None:
        return None
    return _ser_common(row)


def response_action(row):
    if row is None:
        return None
    return _ser_common(row)


def damage_assessment(row):
    if row is None:
        return None
    return _ser_common(row)


def responsibility_decision(row):
    if row is None:
        return None
    return _ser_common(row)


def insurance_claim(row):
    if row is None:
        return None
    return _ser_common(row)


def compliance_report(row):
    if row is None:
        return None
    return _ser_common(row)


def audit_log_entry(row):
    if row is None:
        return None
    return _ser_common(row)
