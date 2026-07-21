"""Role-based access denials, unauthenticated access, and optimistic-concurrency on booking create."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_published_retreat, setup_booking, new_guest,
)
from test_helpers.factories import create_retreat_payload, create_booking_payload
from test_helpers.test_users import make_guest_headers, make_anonymous_headers

_OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Corner: rbac / corner_guest_cannot_create_retreat
# ---------------------------------------------------------------------------
def test_guest_cannot_create_retreat(api):
    """PRD §2.1: "A recognized caller who attempts an operation their role is not permitted to perform — or an ownership-scoped caller acting on a resource they do not own — is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_guest_cannot_create_retreat
    """
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    resp = api.create_retreat(create_retreat_payload(capacity=10), gh)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: rbac / corner_operator_cannot_create_booking
# ---------------------------------------------------------------------------
def test_operator_cannot_create_booking(api):
    """PRD §2.1: "A recognized caller who attempts an operation their role is not permitted to
    perform ... is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/corner_operator_cannot_create_booking
    """
    base = setup_published_retreat(api, room_overrides={"bed_count": 4})
    guest = new_guest(api)
    payload = create_booking_payload(base["retreat"]["id"], guest["id"], base["room"]["id"], 2, base["version"])
    resp = api.create_booking(payload, _OP)  # Operator attempting a Guest-exclusive op
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---------------------------------------------------------------------------
# Corner: rbac / corner_anonymous_cannot_read_booking_unauthenticated
# ---------------------------------------------------------------------------
def test_anonymous_cannot_read_booking(api):
    """PRD §2.1: "When X-User-Role is Anonymous, the caller is unauthenticated and may only
    self-register as a guest. This is the sole operation that does not require prior
    authentication."

    Design: Corner/rbac/corner_anonymous_cannot_read_booking_unauthenticated
    """
    ctx = setup_booking(api, party_size=2, retreat_overrides={"base_price_cents": 150000})
    resp = api.get_booking(ctx["booking"]["id"], make_anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / corner_occ_stale_retreat_version_rejected
# ---------------------------------------------------------------------------
def test_stale_retreat_version_on_second_booking_rejected(api):
    """PRD §2.7: "a client whose expected_retreat_version no longer equals the retreat's
    current version is working from a stale view of capacity. When the two values differ, the
    booking create is rejected with ERR_STALE_RETREAT_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/corner_occ_stale_retreat_version_rejected
    """
    base = setup_published_retreat(api, retreat_overrides={"capacity": 10},
                                   room_overrides={"bed_count": 4})
    guest = new_guest(api)
    gh = make_guest_headers(guest["id"])
    stale_version = base["version"]
    # First booking succeeds and advances the retreat's version.
    b1 = create_booking_payload(base["retreat"]["id"], guest["id"], base["room"]["id"], 1, stale_version)
    validate_success(api.create_booking(b1, gh), 201)
    # Second booking still carries the pre-first-booking (now stale) version.
    b2 = create_booking_payload(base["retreat"]["id"], guest["id"], base["room"]["id"], 1, stale_version)
    resp = api.create_booking(b2, gh)
    validate_error(resp, ApiErrorId.ERR_STALE_RETREAT_VERSION.value)
