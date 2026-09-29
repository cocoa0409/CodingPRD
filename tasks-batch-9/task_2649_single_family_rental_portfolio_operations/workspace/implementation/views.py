"""Serialization and list filtering helpers."""
from flask import request

import calc
import store
import validation


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def home_view(home):
    """`leasing_posture` is derived at read time so a clock change is visible."""
    data = public(home)
    data["leasing_posture"] = calc.leasing_posture(home)
    return data


def filtered(collection, specs):
    """specs is a list of (query_param, row_field, kind) triples."""
    rows = store.all_rows(collection)
    for param, field, kind in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "bool":
            value = validation.bool_param(raw)
        elif kind == "int":
            try:
                value = int(raw, 10)
            except (TypeError, ValueError):
                validation.fail("ERR_INVALID_REQUEST",
                                "Query parameter '%s' must be an integer." % param)
            rows = [r for r in rows if r.get(field) == value]
            continue
        elif kind == "posture":
            rows = [r for r in rows if calc.leasing_posture(r) == raw]
            continue
        else:
            value = raw
        rows = [r for r in rows if r.get(field) == value]
    return rows
