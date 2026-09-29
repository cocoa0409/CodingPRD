"""Acting-principal headers (PRD §2.1).

Every request carries `X-User-ID` and `X-User-Role`.

`SystemAdmin` and `ProductionStaff` are opaque roles: their `X-User-ID` is an
operator identifier not tied to any persisted entity, so a fixed constant is
correct for them.

`EditorInChief`, `HandlingEditor`, `Reviewer` and `Author` are entity-backed:
their `X-User-ID` must resolve to a persisted `Editor`, `Reviewer` or `Author`
row. Tests must therefore build those headers per-row with the `make_*_headers`
builders below, never with a fixed constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identities (PRD §2.1).
SYSTEM_ADMIN_ID = "ops-editorial-office-01"
PRODUCTION_STAFF_ID = "ops-production-desk-01"

TEST_USERS = {
    "system_admin": build_user_headers(SYSTEM_ADMIN_ID, UserRole.SYSTEM_ADMIN.value),
    "production_staff": build_user_headers(
        PRODUCTION_STAFF_ID, UserRole.PRODUCTION_STAFF.value
    ),
}

SYSTEM_ADMIN_HEADERS = TEST_USERS["system_admin"]
PRODUCTION_STAFF_HEADERS = TEST_USERS["production_staff"]


def make_system_admin_headers(user_id=SYSTEM_ADMIN_ID):
    """Headers for an opaque editorial-office operator."""
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def make_production_staff_headers(user_id=PRODUCTION_STAFF_ID):
    """Headers for an opaque production-desk operator."""
    return build_user_headers(user_id, UserRole.PRODUCTION_STAFF.value)


def make_editor_in_chief_headers(editor_id):
    """Headers for an `EditorInChief`; `X-User-ID` is the acting `Editor` id."""
    return build_user_headers(editor_id, UserRole.EDITOR_IN_CHIEF.value)


def make_handling_editor_headers(editor_id):
    """Headers for a `HandlingEditor`; `X-User-ID` is the acting `Editor` id."""
    return build_user_headers(editor_id, UserRole.HANDLING_EDITOR.value)


def make_reviewer_headers(reviewer_id):
    """Headers for a `Reviewer`; `X-User-ID` is the acting `Reviewer` id."""
    return build_user_headers(reviewer_id, UserRole.REVIEWER.value)


def make_author_headers(author_id):
    """Headers for an `Author`; `X-User-ID` is the acting `Author` id."""
    return build_user_headers(author_id, UserRole.AUTHOR.value)


def make_headers(role, user_id):
    """Headers for an arbitrary role string and principal identifier."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id=SYSTEM_ADMIN_ID):
    """Headers omitting `X-User-Role` entirely (PRD §2.1)."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role):
    """Headers omitting `X-User-ID` entirely (PRD §2.1)."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
