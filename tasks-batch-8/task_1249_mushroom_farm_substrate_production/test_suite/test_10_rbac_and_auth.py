"""Authentication, identity resolution, and role-based access control."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_buyer,
    create_buyer_commitment_payload,
    create_room_payload,
    get_success_data,
    make_buyer_portal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

FARM = TEST_USERS["farm_manager_headers"]
SALES = TEST_USERS["sales_manager_headers"]
ANY = TEST_USERS["any_headers"]


def test_request_missing_auth_headers_returns_400(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`
    identifying the acting user, and `X-User-Role` naming their role. A
    request missing either header, or carrying an empty value for either, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/request_missing_auth_header_returns_400
    """
    resp = api.create_room(create_room_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_request_missing_auth_headers_persists_nothing(api):
    """PRD §2.1: "A request missing either header, or carrying an empty value
    for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    A request rejected at priority 1 creates no resource.

    Design: Corner/validations/request_missing_auth_header_returns_400
    """
    resp = api.create_room(create_room_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    rooms, meta = validate_paginated(api.list_rooms(ANY))
    assert rooms == [], "rejected request must persist no room"


def test_room_create_forbidden_for_sales_manager(api):
    """PRD §2.1: "A request whose role is not permitted for the attempted
    operation is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §2.1: "A
    `FarmManager` runs the growing side: rooms, room cycles, flush recording,
    packaging, worker administration, the logical clock, the daily sweep, and
    spent-substrate disposal." Room creation is FarmManager-only; the §4
    endpoint table lists `POST /api/rooms` under FarmManager.

    Design: Corner/validations/room_create_forbidden_for_sales_manager
    """
    resp = api.create_room(create_room_payload(), SALES)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_pieces_log_identity_unresolved_returns_403(api):
    """PRD §2.1: "When `X-User-Role` is `HarvestCrewLead`, `X-User-ID` is the
    `id` of the acting `Worker`; ownership checks compare against that
    entity. If no `Worker` with that id exists, the request is rejected with
    `ERR_IDENTITY_NOT_RESOLVED` (HTTP 403)."
    PRD §2.8: "identity resolution for entity-backed roles (priority 2) ...
    Existence follows: path resource ids must exist and are validated left to
    right along the URL (priority 4)." Identity resolution therefore precedes
    path-existence validation.

    Design: Corner/validations/pieces_log_identity_unresolved_returns_403
    """
    from test_helpers import make_harvest_crew_lead_headers
    ghost_worker_id = "33333333-3333-3333-3333-333333333333"
    headers = make_harvest_crew_lead_headers(ghost_worker_id)
    resp = api.log_piece(
        "44444444-4444-4444-4444-444444444444",
        {"worker_id": ghost_worker_id, "kg_picked": 10.0},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_IDENTITY_NOT_RESOLVED)


def test_buyerportal_cannot_create_for_other_buyer(api):
    """PRD §2.1: "A `BuyerPortal` caller may create commitments only for
    itself: the `buyer_id` of the new commitment must equal its `X-User-ID`,
    otherwise the request is rejected with `ERR_BUYER_MISMATCH` (HTTP 403)."

    Design: Corner/validations/buyerportal_cannot_create_for_other_buyer
    """
    b1 = create_buyer(name="Acme Grocery")
    b2 = create_buyer(name="Other Market")
    headers = make_buyer_portal_headers(b1["id"])
    resp = api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=b2["id"], reference="PO-999"),
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_BUYER_MISMATCH)
    commitments, _meta = validate_paginated(
        api.list_buyer_commitments(ANY, params={"buyer_id": b2["id"]})
    )
    assert commitments == [], "rejected create must persist no commitment for b2"


def test_buyerportal_creates_own_draft_commitment(api):
    """PRD §2.1: "A `BuyerPortal` caller may create commitments only for
    itself: the `buyer_id` of the new commitment must equal its `X-User-ID`."
    PRD §3.6: "A buyer commitment begins life in `DRAFT`."

    Design: Corner/rbac/buyerportal_creates_own_draft_commitment
    """
    buyer = create_buyer(name="Acme Grocery")
    headers = make_buyer_portal_headers(buyer["id"])
    resp = api.create_buyer_commitment(
        create_buyer_commitment_payload(buyer_id=buyer["id"], reference="PO-SELF-1"),
        headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    assert data["buyer_id"] == buyer["id"]
    assert data["total_committed_kg"] == 0.0
    assert data["total_delivered_kg"] == 0.0


def test_clock_regression_rejected(api):
    """PRD §2.5: "A `FarmManager`-only test-driving capability advances the
    logical clock to a supplied `to_iso8601` instant; the new value must be
    greater than or equal to the current logical time, and a target before it
    is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409)."

    Design: Corner/validations/clock_regression_rejected
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-05-03T00:00:00Z"}, FARM))
    resp = api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, FARM)
    validate_error(resp, ApiErrorId.ERR_CLOCK_REGRESSION)
    # Equality is not regression.
    ok = api.set_clock({"to_iso8601": "2026-05-03T00:00:00Z"}, FARM)
    validate_success(ok, expected_status=200)


def test_clock_equality_is_not_regression(api):
    """PRD §2.5: "the new value must be greater than or equal to the current
    logical time, and a target before it is rejected with
    `ERR_CLOCK_REGRESSION` (HTTP 409)."

    Design: Corner/validations/clock_regression_rejected
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-05-03T00:00:00Z"}, FARM))
    same = api.set_clock({"to_iso8601": "2026-05-03T00:00:00Z"}, FARM)
    validate_success(same, expected_status=200)
    backward = api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, FARM)
    validate_error(backward, ApiErrorId.ERR_CLOCK_REGRESSION)
