"""Serialization of stored records into API output shapes."""
from core import (DB, to_jsonable, carrier_active_bond, carrier_standing,
                  structure_available, structure_posture)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def serialize_carrier(c):
    out = _public(c)
    out["active_bond_amount_cents"] = carrier_active_bond(c["id"])
    out["compliance_standing"] = carrier_standing(c["id"])
    return to_jsonable(out)


def serialize_structure(s):
    out = _public(s)
    out["available_tonnage"] = structure_available(s)
    out["posture"] = structure_posture(s)
    return to_jsonable(out)


def serialize_permit(p):
    return to_jsonable(_public(p))


def serialize_route_segment(r):
    return to_jsonable(_public(r))


def serialize_bridge_analysis(b):
    return to_jsonable(_public(b))


def serialize_pilot_car(pc):
    return to_jsonable(_public(pc))


def serialize_escort(e):
    return to_jsonable(_public(e))


def serialize_bond(b):
    return to_jsonable(_public(b))


def serialize_violation(v):
    return to_jsonable(_public(v))


def serialize_travel_restriction(t):
    return to_jsonable(_public(t))
