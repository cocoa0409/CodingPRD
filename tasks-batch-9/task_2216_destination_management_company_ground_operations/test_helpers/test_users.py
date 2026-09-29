"""Pre-built role headers for every role named in PRD §2.1.

Two role identities are entity-backed and therefore need per-instance builders:

- `OperationsCoordinator` — `X-User-ID` is the `id` of the acting `StaffMember`.
- `Supplier` — `X-User-ID` is the `id` of the acting `Supplier`.

Ownership-gated calls MUST use the matching `make_*_headers(entity_id)` builder;
the shared constants below are only safe where ownership is not exercised.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identifiers.
    "program_director_headers": build_user_headers("pd-1", "ProgramDirector"),
    "supplier_manager_headers": build_user_headers("sm-1", "SupplierManager"),
    "controller_headers": build_user_headers("ctrl-1", "Controller"),
    "permit_officer_headers": build_user_headers("po-1", "PermitOfficer"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "operations_coordinator_headers": build_user_headers("oc-1", "OperationsCoordinator"),
    "supplier_headers": build_user_headers("sup-1", "Supplier"),
}


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector acting under an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ProgramDirector")


def make_supplier_manager_headers(user_id: str) -> dict:
    """SupplierManager acting under an explicit opaque operator identifier.

    Used to satisfy the segregation-of-duties comparison between the sender of a
    contract and its countersigner.
    """
    return build_user_headers(user_id, "SupplierManager")


def make_controller_headers(user_id: str) -> dict:
    """Controller acting under an explicit opaque operator identifier.

    Used to satisfy the segregation-of-duties comparison between the approver and
    the releaser of a settlement payment.
    """
    return build_user_headers(user_id, "Controller")


def make_permit_officer_headers(user_id: str) -> dict:
    """PermitOfficer acting under an explicit opaque operator identifier."""
    return build_user_headers(user_id, "PermitOfficer")


def make_operations_coordinator_headers(staff_member_id: str) -> dict:
    """OperationsCoordinator whose `X-User-ID` is the acting StaffMember's `id`.

    Mandatory for on-site staff check-in, where `X-User-ID` must equal the
    assignment's `staff_id`.
    """
    return build_user_headers(staff_member_id, "OperationsCoordinator")


def make_supplier_headers(supplier_id: str) -> dict:
    """Supplier whose `X-User-ID` is the acting Supplier's `id`.

    Mandatory for the counter-offer, where `X-User-ID` must equal the contract's
    `supplier_id`.
    """
    return build_user_headers(supplier_id, "Supplier")
