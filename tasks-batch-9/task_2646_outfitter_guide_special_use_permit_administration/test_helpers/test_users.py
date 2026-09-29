"""Pre-built role headers for the four roles named in the PRD.

Every request carries `X-User-ID` and `X-User-Role`. For an
`OutfitterRepresentative` the `X-User-ID` value IS the identifier of the
outfitter the caller speaks for, so ownership-gated calls must always be made
with `make_outfitter_representative_headers(outfitter["id"])` rather than a
shared constant. For the other three roles the identifier is opaque and is
merely recorded on whatever row the call writes.
"""
from prd_bench_local_runner.testing import build_user_headers

ROLE_OUTFITTER_REPRESENTATIVE = "OutfitterRepresentative"
ROLE_PERMIT_SPECIALIST = "PermitSpecialist"
ROLE_AUTHORIZED_OFFICER = "AuthorizedOfficer"
ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"

ALL_ROLES = [
    ROLE_OUTFITTER_REPRESENTATIVE,
    ROLE_PERMIT_SPECIALIST,
    ROLE_AUTHORIZED_OFFICER,
    ROLE_PROGRAM_ADMINISTRATOR,
]

# Opaque-role identifiers. Two distinct identifiers per reviewing role so that
# tests can exercise the two separation-of-duties rules.
SPECIALIST_USER_ID = "spec-1"
SPECIALIST_USER_ID_ALT = "spec-2"
OFFICER_USER_ID = "officer-alpha"
OFFICER_USER_ID_ALT = "officer-beta"
ADMIN_USER_ID = "admin-1"

TEST_USERS = {
    # entity_backed role: this shared constant is safe only for calls that do
    # not reach an ownership check (missing-field rejections, unknown-id
    # lookups, role-permission probes).
    "outfitter_representative_headers": build_user_headers(
        "outfitter-rep-unowned", ROLE_OUTFITTER_REPRESENTATIVE
    ),
    "permit_specialist_headers": build_user_headers(
        SPECIALIST_USER_ID, ROLE_PERMIT_SPECIALIST
    ),
    "permit_specialist_alt_headers": build_user_headers(
        SPECIALIST_USER_ID_ALT, ROLE_PERMIT_SPECIALIST
    ),
    "authorized_officer_headers": build_user_headers(
        OFFICER_USER_ID, ROLE_AUTHORIZED_OFFICER
    ),
    "authorized_officer_alt_headers": build_user_headers(
        OFFICER_USER_ID_ALT, ROLE_AUTHORIZED_OFFICER
    ),
    "program_administrator_headers": build_user_headers(
        ADMIN_USER_ID, ROLE_PROGRAM_ADMINISTRATOR
    ),
}


def make_outfitter_representative_headers(outfitter_id: str) -> dict:
    """Headers for the representative of one specific outfitter.

    `X-User-ID` must be the outfitter's own identifier; any other value fails
    the ownership check on holder-scoped writes.
    """
    return build_user_headers(outfitter_id, ROLE_OUTFITTER_REPRESENTATIVE)


def make_permit_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_PERMIT_SPECIALIST)


def make_authorized_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_AUTHORIZED_OFFICER)


def make_program_administrator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_PROGRAM_ADMINISTRATOR)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identifier/role pair — used by role-permission probes."""
    return build_user_headers(user_id, role)
