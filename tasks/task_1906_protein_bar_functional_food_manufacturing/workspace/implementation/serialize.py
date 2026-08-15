"""Record -> public JSON serializers. Internal keys (``_``-prefixed parsed
datetimes and sequence numbers) never leave the server."""
from decimal import Decimal

from db import fmt_dt, STORES
from services import calc


def _emit(rec, dt_fields=(), nested_dec=()):
    out = {}
    for k, v in rec.items():
        if k.startswith("_") or k.endswith("_dt"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif k in nested_dec and isinstance(v, list):
            out[k] = [
                {ik: (float(iv) if isinstance(iv, Decimal) else iv)
                 for ik, iv in item.items()}
                for item in v
            ]
        else:
            out[k] = v
    for k in dt_fields:
        out[k] = fmt_dt(rec[k + "_dt"]) if rec.get(k + "_dt") is not None else None
    return out


def supplier(r):
    return _emit(r)


def ingredient(r):
    return _emit(r)


def lot(r):
    out = _emit(r, dt_fields=("received_at",))
    out["available_qty_kg"] = float(
        Decimal(str(r["received_qty_kg"])) - Decimal(str(r["reserved_qty_kg"]))
        - Decimal(str(r["consumed_qty_kg"])))
    out["reserved_qty_kg"] = float(Decimal(str(r["reserved_qty_kg"])))
    out["consumed_qty_kg"] = float(Decimal(str(r["consumed_qty_kg"])))
    out["received_qty_kg"] = float(Decimal(str(r["received_qty_kg"])))
    return out


def customer(r):
    return _emit(r)


def agreement(r):
    out = _emit(r, dt_fields=("quarter_start",))
    produced, shortfall = calc.agreement_rollup(r)
    out["produced_cases_current_quarter"] = produced
    out["shortfall_cases"] = shortfall
    return out


def formula(r):
    out = _emit(r)
    approved = None
    for rev in STORES["revisions"].values():
        if rev["formula_id"] == r["id"] and rev["status"] == "APPROVED":
            approved = rev["id"]
            break
    out["approved_revision_id"] = approved
    return out


def revision(r):
    return _emit(r, nested_dec=("ingredient_lines",))


def line(r):
    return _emit(r, dt_fields=("last_wet_clean_utc",))


def slot(r):
    return _emit(r, dt_fields=("start_utc", "end_utc"))


def run(r):
    return _emit(r, dt_fields=("completed_utc",),
                 nested_dec=("reserved_lot_allocations",))


def changeover(r):
    return _emit(r)


def study(r):
    return _emit(r, dt_fields=("start_utc", "expiry_utc"))


def pull(r):
    return _emit(r, dt_fields=("due_utc", "recorded_utc"))


def release(r):
    return _emit(r)


def retain(r):
    return _emit(r, dt_fields=("retain_until_utc",))


def claim(r):
    return _emit(r)
