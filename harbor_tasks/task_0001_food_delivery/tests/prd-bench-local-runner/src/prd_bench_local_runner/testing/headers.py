"""Generic auth header builder."""

from typing import Dict


def build_user_headers(user_id: str, role: str) -> Dict[str, str]:
    """
    Construct auth headers for a given user/role.

    The header names (X-User-ID, X-User-Role) are the standard convention
    for role-based API testing. Callers typically build pre-configured
    header dicts for each role at import time.
    """
    return {
        "X-User-ID": user_id,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }
