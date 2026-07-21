"""Entity output shaping."""
from store import public


def variant_out(v):
    out = public(v)
    out["inventory_available"] = v["inventory_on_hand"] - v["inventory_reserved"]
    return out


def order_out(o):
    return public(o)


def line_out(l):
    return public(l)


def generic_out(rec):
    return public(rec)
