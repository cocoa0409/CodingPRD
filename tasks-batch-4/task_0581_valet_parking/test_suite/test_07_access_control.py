"""Role-based access control: role authorization, shift-tips ownership, and authentication."""
from test_helpers import (
    validate_error, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID, make_attendant_headers,
)
from test_helpers.fixtures import (
    setup_checked_in_ticket, setup_open_damage_claim,
    create_venue, create_attendant, create_shift,
)

SUP = TEST_USERS["supervisor_headers"]
CASHIER = TEST_USERS["cashier_headers"]


def test_attendant_cannot_checkout_ticket(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not permitted
    to perform, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `Cashier` handles money (checkout, validation grants, reversals)".

    Design: Corner/rbac/attendant_cannot_checkout_ticket
    """
    env = setup_checked_in_ticket()
    res = api.checkout_ticket(
        env["ticket"]["id"], {"checkout_at": "2026-06-01T12:30:00Z"},
        make_attendant_headers(env["attendant"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_cashier_cannot_approve_damage_claim(api):
    """PRD §2.1: "When an authenticated caller invokes an operation their role is not permitted
    to perform, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §2.1: "A `Supervisor` configures venues, events, lots, lanes, attendants, and shifts;
    drives every lifecycle transition on those configuration entities; adjudicates damage
    claims; and runs reconciliation."

    Design: Corner/rbac/cashier_cannot_approve_damage_claim
    """
    env = setup_open_damage_claim(claimed_amount_cents=400)
    res = api.approve_damage_claim(env["claim"]["id"], {}, CASHIER)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


def test_tips_by_non_owner_attendant_forbidden(api):
    """PRD §2.1: "Concretely, when an attendant records tips into a shift, the system requires
    that `X-User-ID` equal the `attendant_id` of that shift; a mismatch is rejected with
    `ERR_FORBIDDEN_OWNERSHIP`."

    Design: Corner/rbac/tips_by_non_owner_attendant_forbidden_ownership
    """
    venue = create_venue()
    a1 = create_attendant(venue["id"], name="Ana")
    a2 = create_attendant(venue["id"], name="Bob")
    s1 = create_shift(a1["id"], "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z")
    res = api.record_tips(
        s1["id"], {"declared_tips_cents": 500}, make_attendant_headers(a2["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.7: "(1) authentication of the `X-User-ID` / `X-User-Role` headers, failing with
    `ERR_UNAUTHENTICATED`".

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    res = api.get_venue(NON_EXISTENT_UUID, TEST_USERS["unknown_role_headers"])
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
