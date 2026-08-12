"""Serialize internal records to wire format (strip private keys, normalize
numbers)."""


def _public(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        out[k] = v
    return out


def station(s):
    return _public(s)


def pad(p):
    return _public(p)


def weather_event(e):
    return _public(e)


def fluid_tank(t):
    return _public(t)


def airline(a):
    return _public(a)


def deice_request(r):
    return _public(r)


def deice_operation(o):
    return _public(o)


def inspection(i):
    return _public(i)


def discharge_permit(p):
    return _public(p)


def effluent_reading(r):
    return _public(r)


def spill_report(s):
    return _public(s)


def recycling_contract(c):
    return _public(c)


def invoice(i):
    return _public(i)
