"""Authentication and role/capability authorization (PRD section 2.1).

Validation order: layer 1 authentication (ERR_UNAUTHENTICATED), then layer 2
schema, then layer 3 authorization (ERR_FORBIDDEN) including the entity-backed
capability gate for the Operator and QualityTech floor roles.
"""
from flask import request

from db import STORE
from errors import ApiError

ROLES = {"MillManager", "Nutritionist", "Operator", "QualityTech", "Customer"}

ALL_ROLES = frozenset(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def authorize(role, uid, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       f"Role {role} is not admitted to this endpoint")
    if role == "Operator":
        emp = STORE["employees"].get(uid)
        if emp is None or emp["capability"] not in ("OPERATOR", "DUAL"):
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Employee capability does not cover the Operator role")
    elif role == "QualityTech":
        emp = STORE["employees"].get(uid)
        if emp is None or emp["capability"] not in ("QUALITY_TECH", "DUAL"):
            raise ApiError("ERR_FORBIDDEN", 403,
                           "Employee capability does not cover the QualityTech role")
