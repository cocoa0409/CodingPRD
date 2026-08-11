"""Entity serializers: internal datetime/date objects -> ISO strings; drops
internal bookkeeping keys. Field sets mirror SCAFFOLD.yaml entity tables plus
common fields (id, created_at, updated_at, version)."""
from datetime import datetime, date

from helpers import fmt_dt, fmt_date

_DT = datetime
_D = date


def _ser(entity, dt_fields=(), date_fields=()):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if k in dt_fields:
            out[k] = fmt_dt(v) if v is not None else None
        elif k in date_fields:
            out[k] = fmt_date(v) if v is not None else None
        else:
            out[k] = v
    return out


COMMON_DT = ("created_at", "updated_at")


def ser_student(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_policy(e):
    return _ser(e, dt_fields=COMMON_DT + ("coverage_start", "coverage_end", "verified_at"))


def ser_requirement(e):
    return _ser(e, dt_fields=COMMON_DT, date_fields=("deadline_date",))


def ser_record(e):
    out = _ser(e, dt_fields=COMMON_DT)
    out["dose_dates"] = [fmt_date(d) for d in e["dose_dates"]]
    return out


def ser_provider(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_shift(e):
    return _ser(e, dt_fields=COMMON_DT + ("shift_start", "shift_end"))


def ser_appointment(e):
    return _ser(e, dt_fields=COMMON_DT + ("scheduled_start", "scheduled_end"))


def ser_encounter(e):
    return _ser(e, dt_fields=COMMON_DT + ("opened_at", "closed_at"))


def ser_prescription(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_stock(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_lab_order(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_case(e):
    return _ser(e, dt_fields=COMMON_DT + ("confirmed_at", "reported_at"))


def ser_investigation(e):
    return _ser(e, dt_fields=COMMON_DT + ("opened_at",))


def ser_invoice(e):
    return _ser(e, dt_fields=COMMON_DT + ("issued_at",), date_fields=("due_date",))


def ser_payment(e):
    return _ser(e, dt_fields=COMMON_DT + ("voided_at",))


def ser_referral(e):
    return _ser(e, dt_fields=COMMON_DT)


def ser_pool(e):
    return _ser(e, dt_fields=COMMON_DT, date_fields=("term_end_date",))
