"""Authentication and role-based access control (PRD §2.1, §2.7, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_claimant,
    create_item_payload,
    create_program_payload,
    make_auction_coordinator_headers,
    make_claimant_headers,
    make_intake_officer_headers,
    validate_error,
    TEST_USERS,
)


def test_claimant_cannot_create_item(api):
    """PRD §4: `POST /items` "Register found property" is authorized for
    `IntakeOfficer` only. PRD §2.1: "an authenticated caller whose role is not
    authorized for the endpoint ... is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." PRD §2.7 orders "Authorization and actor-ownership —
    `ERR_FORBIDDEN`" before "Existence of foreign keys referenced in the
    request body — `ERR_NOT_FOUND`".

    Design: Corner/rbac/claimant_cannot_create_item
    """
    claimant = create_claimant()
    res = api.create_item(
        create_item_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                            declared_value_cents=100),
        make_claimant_headers(claimant["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_intake_officer_cannot_approve_claim(api, intake_officer_headers):
    """PRD §4: `POST /claims/{claim_id}/approve` "Approve a claim (cascades to
    item and competing claims)" is authorized for `ClaimsExaminer` only.
    PRD §2.1: "an authenticated caller whose role is not authorized for the
    endpoint ... is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/intake_officer_cannot_approve_claim
    """
    res = api.approve_claim(NON_EXISTENT_UUID, intake_officer_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_public_user_cannot_list_staff_items(api, public_user_headers):
    """PRD §4: `GET /items` "Staff item list with filters" is authorized for
    "All staff" — the seven-role staff set of `IntakeOfficer`,
    `PropertyCustodian`, `ClaimsExaminer`, `ReleaseOfficer`, `PoliceLiaison`,
    `AuctionCoordinator`, and `ProgramAdmin` — which excludes `PublicUser`.
    PRD §2.1: "an authenticated caller whose role is not authorized for the
    endpoint ... is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/public_user_cannot_list_staff_items
    """
    res = api.list_items(public_user_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_auction_coordinator_cannot_create_program(api):
    """PRD §4: `POST /programs` "Create a lost-and-found program (TRANSIT or
    FACILITY)" is authorized for `ProgramAdmin` only. PRD §2.1: "an
    authenticated caller whose role is not authorized for the endpoint ... is
    rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/auction_coordinator_cannot_create_program
    """
    res = api.create_program(
        create_program_payload(name="Rogue"),
        make_auction_coordinator_headers("coord-1"))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_claimant_forbidden_before_not_found_on_staff_item_read(api):
    """PRD §2.7: "the server evaluates its checks in a single deterministic
    order, and the earliest failing check determines the error returned" —
    "Authorization and actor-ownership — `ERR_FORBIDDEN`" is ordered before
    "Path-parameter resolution, left to right — `ERR_NOT_FOUND`". PRD §4:
    `GET /items/{item_id}` "Staff item read" is authorized for "All staff",
    which excludes `Claimant`.

    Design: Corner/validations/claimant_forbidden_before_not_found_on_item_read
    """
    claimant = create_claimant()
    res = api.get_item(NON_EXISTENT_UUID, make_claimant_headers(claimant["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
