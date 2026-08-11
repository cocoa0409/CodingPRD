"""Shared helpers for the route modules.

Every helper commits this request's pending version bumps BEFORE it projects,
so a response can never show a resource one version behind the mutation that
produced it.
"""
import store
from envelope import object_response, paginate
from serialize import project


def created(rec):
    store.commit()
    return object_response(project(rec), 201)


def ok(rec):
    store.commit()
    return object_response(project(rec), 200)


def ok_raw(data):
    store.commit()
    return object_response(data, 200)


def listing(kind, args, predicate=None):
    store.commit()
    rows = store.ordered(kind, predicate)
    return paginate(rows, project, args)


def filter_eq(args, name, value_of, current):
    """Build up an additive exact-match filter chain (PRD 2.3)."""
    wanted = args.get(name)
    if wanted is None or wanted == "":
        return current

    def combined(rec):
        return current(rec) and str(value_of(rec)) == str(wanted)
    return combined


def always(_rec):
    return True
