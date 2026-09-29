"""Pre-built role headers for the five roles of PRD §2.1.

Three roles carry **opaque** identity: a `ProgramAdministrator`, a
`ProgramAuditor` and a `CustomerAdvocate` supply an operator identifier the
server never compares to any row's `id`, so shared constants are the canonical
form. The administrator's identifier is nonetheless persisted as
`closed_by_user_id` on a waived reconditioning item, and the auditor's as
`reviewer_user_id` on the sample it rules on, which is why named builders exist
for them too.

Two roles are **entity backed**. `DealerPrincipal` must carry the acting
`Dealer.id` in `X-User-ID` and `InspectionTechnician` must carry the acting
`Technician.id`; an unresolvable identifier is rejected with
`ERR_IDENTITY_NOT_RECOGNIZED` and a resolvable identifier belonging to another
dealership with `ERR_DEALER_SCOPE_VIOLATION`. Every ownership-gated call must
therefore use `make_dealer_principal_headers(dealer_id)` or
`make_inspection_technician_headers(technician_id)`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CUSTOMER_ADVOCATE,
    ROLE_DEALER_PRINCIPAL,
    ROLE_INSPECTION_TECHNICIAN,
    ROLE_PROGRAM_ADMINISTRATOR,
    ROLE_PROGRAM_AUDITOR,
)

ADMIN_USER_ID = "admin-1"
AUDITOR_USER_ID = "auditor-1"
ADVOCATE_USER_ID = "advocate-1"

# A syntactically valid UUID that resolves to no row at all, for the identity
# resolution rung of the ladder.
UNRESOLVABLE_ENTITY_ID = "00000000-0000-4000-8000-000000000061"

TEST_USERS = {
    # Opaque identities — safe to share across every test.
    "admin_headers": build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMINISTRATOR),
    "admin_2_headers": build_user_headers("admin-2", ROLE_PROGRAM_ADMINISTRATOR),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, ROLE_PROGRAM_AUDITOR),
    "auditor_2_headers": build_user_headers("auditor-2", ROLE_PROGRAM_AUDITOR),
    "advocate_headers": build_user_headers(ADVOCATE_USER_ID, ROLE_CUSTOMER_ADVOCATE),
    # Entity-backed fallbacks. These identifiers resolve to nothing, so they are
    # safe ONLY for calls that are refused before identity resolution matters
    # (authentication, role authorisation) or that deliberately exercise
    # ERR_IDENTITY_NOT_RECOGNIZED.
    "unresolvable_dealer_headers": build_user_headers(
        UNRESOLVABLE_ENTITY_ID, ROLE_DEALER_PRINCIPAL
    ),
    "unresolvable_technician_headers": build_user_headers(
        UNRESOLVABLE_ENTITY_ID, ROLE_INSPECTION_TECHNICIAN
    ),
}


def make_program_administrator_headers(user_id: str) -> dict:
    """ProgramAdministrator headers for a named opaque operator identifier.

    The identifier is stamped as `closed_by_user_id` when the administrator
    excuses a reconditioning item by waiver.
    """
    return build_user_headers(user_id, ROLE_PROGRAM_ADMINISTRATOR)


def make_program_auditor_headers(user_id: str) -> dict:
    """ProgramAuditor headers for a named opaque operator identifier.

    The identifier is stamped as `reviewer_user_id` on the audit sample it rules on.
    """
    return build_user_headers(user_id, ROLE_PROGRAM_AUDITOR)


def make_customer_advocate_headers(user_id: str) -> dict:
    """CustomerAdvocate headers for a named opaque operator identifier.

    This identifier is not persisted on any row.
    """
    return build_user_headers(user_id, ROLE_CUSTOMER_ADVOCATE)


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """DealerPrincipal headers. `dealer_id` MUST be the acting `Dealer.id`."""
    return build_user_headers(dealer_id, ROLE_DEALER_PRINCIPAL)


def make_inspection_technician_headers(technician_id: str) -> dict:
    """InspectionTechnician headers. `technician_id` MUST be the acting `Technician.id`."""
    return build_user_headers(technician_id, ROLE_INSPECTION_TECHNICIAN)


ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
ADVOCATE = TEST_USERS["advocate_headers"]
