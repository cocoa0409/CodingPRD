"""Small helpers shared by the route modules."""

from flask import request

import auth as authmod
from errors import ApiError
from resp import paginate
from store import db, table_rows


def listed(rows, spec=None, actor=None, owner_field="patient_id"):
    """Apply declared query filters, owner scoping for Patients, then paginate."""
    if actor is not None and actor.is_patient and owner_field is not None:
        rows = [r for r in rows if r.get(owner_field) == actor.user_id]
    if spec:
        for key, getter in spec.items():
            raw = request.args.get(key)
            if raw is None:
                continue
            rows = [r for r in rows if _matches(getter(r), raw)]
    return paginate(rows)


def _matches(value, raw):
    if isinstance(value, bool):
        return value == (str(raw).strip().lower() in ("true", "1", "yes"))
    if value is None:
        return str(raw).strip().lower() in ("null", "none", "")
    if isinstance(value, (list, tuple)):
        return raw in value
    if isinstance(value, int):
        try:
            return value == int(str(raw).strip())
        except ValueError:
            return False
    return str(value) == str(raw)


def field(name):
    return lambda row: row.get(name)


def patient_of_order(order_id):
    order = db.device_orders.get(order_id)
    return order.get("patient_id") if order else None


def patient_of_trial(trial_id):
    trial = db.trial_periods.get(trial_id)
    return trial.get("patient_id") if trial else None


def patient_of_device(device_id):
    device = db.devices.get(device_id)
    if device is None:
        return None
    return patient_of_order(device.get("device_order_id"))


def owner_rows(table, actor, resolver):
    rows = table_rows(table)
    if actor.is_patient:
        rows = [r for r in rows if resolver(r) == actor.user_id]
    return rows


def deny_unknown_enum(value, allowed):
    if value is not None and value not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE")


ROLE = authmod
