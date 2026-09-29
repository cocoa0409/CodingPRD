"""
Role headers.

"Every request to this API carries an `X-Role` header naming the operational
capacity of the caller."  "Requests also carry an `X-User-ID` header identifying
the individual operator behind the role."  "When `X-Role` is `Exhibitor`, the
request must additionally carry `X-Role-Id`, and that value is the `id` of the
acting `Exhibitor` row."

Operator identifiers are opaque for ShowDirector, SalesRep, FloorManager and
Registrant: "it is not tied to any persisted entity, and the server never
compares it to any row's `id`."  Distinct operator ids matter only where a
separation-of-duties rule compares them.
"""

from typing import Dict, Optional

from .types import Role

# Opaque operator identifiers.  Distinct values are needed wherever a
# segregation-of-duties rule compares a request's X-User-ID to a recorded one.
DIRECTOR_1 = "u_sd_1"
DIRECTOR_2 = "u_sd_2"
DIRECTOR_3 = "u_sd_3"
DIRECTOR_9 = "u_sd_9"
SALES_REP_1 = "u_sr_1"
SALES_REP_2 = "u_sr_2"
FLOOR_MANAGER_1 = "u_fm_1"
FLOOR_MANAGER_2 = "u_fm_2"
REGISTRANT_1 = "u_reg_1"


def _headers(role: str, user_id: Optional[str] = None,
             role_id: Optional[str] = None) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if role is not None:
        headers["X-Role"] = role
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role_id is not None:
        headers["X-Role-Id"] = role_id
    return headers


def make_director_headers(user_id: str = DIRECTOR_1) -> Dict[str, str]:
    return _headers(Role.SHOW_DIRECTOR, user_id)


def make_sales_rep_headers(user_id: str = SALES_REP_1) -> Dict[str, str]:
    return _headers(Role.SALES_REP, user_id)


def make_floor_manager_headers(user_id: str = FLOOR_MANAGER_1) -> Dict[str, str]:
    return _headers(Role.FLOOR_MANAGER, user_id)


def make_registrant_headers(user_id: str = REGISTRANT_1) -> Dict[str, str]:
    return _headers(Role.REGISTRANT, user_id)


def make_exhibitor_headers(exhibitor_id: str,
                           user_id: str = "u_ex_1") -> Dict[str, str]:
    """An Exhibitor caller: X-Role-Id must be the id of the acting Exhibitor row."""
    return _headers(Role.EXHIBITOR, user_id, role_id=exhibitor_id)


def make_exhibitor_headers_without_identity(user_id: str = "u_ex_1") -> Dict[str, str]:
    """X-Role Exhibitor with no X-Role-Id at all."""
    return _headers(Role.EXHIBITOR, user_id)


def make_headers_without_role(user_id: str = "u_anon_1") -> Dict[str, str]:
    """No X-Role header at all."""
    return _headers(None, user_id)  # type: ignore[arg-type]


def make_unknown_role_headers(role: str = "Auditor",
                              user_id: str = "u_unknown_1") -> Dict[str, str]:
    """An X-Role value that is not one of the five recognised strings."""
    return _headers(role, user_id)


# Pre-built headers for the common single-operator cases.
DIRECTOR_HEADERS = make_director_headers()
SALES_REP_HEADERS = make_sales_rep_headers()
FLOOR_MANAGER_HEADERS = make_floor_manager_headers()
REGISTRANT_HEADERS = make_registrant_headers()
NO_ROLE_HEADERS = make_headers_without_role()
UNKNOWN_ROLE_HEADERS = make_unknown_role_headers()
