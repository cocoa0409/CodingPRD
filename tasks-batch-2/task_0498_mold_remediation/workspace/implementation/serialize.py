"""Serialize internal records to API output. Recompute read-time derived fields
(is_cert_current, posture/open_finding_count are stored but reconciled on read)."""
from logic import is_cert_current


def _strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ser_worker(w):
    out = _strip(w)
    out["is_cert_current"] = is_cert_current(w)
    return out


def ser_project(p):
    return _strip(p)


def ser_assessment(a):
    return _strip(a)


def ser_sample(s):
    return _strip(s)


def ser_zone(z):
    return _strip(z)


def ser_pressure_log(pl):
    return _strip(pl)


def ser_order(o):
    return _strip(o)


def ser_manifest(m):
    return _strip(m)


def ser_clearance(c):
    return _strip(c)


def ser_permit(p):
    return _strip(p)


def ser_claim(c):
    return _strip(c)


def ser_assignment(a):
    return _strip(a)
