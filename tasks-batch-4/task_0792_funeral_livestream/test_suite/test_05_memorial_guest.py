"""Memorial page gating, guest-link password lockout, and guestbook moderation.

Queue-A boundary instance for the access lockout threshold, plus queue-B corners
for a single wrong password, donation before publication, and the guestbook
approve count recompute.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error, ApiErrorId,
    setup_draft_order, setup_published_memorial_order,
    create_guestbook_entry, get_order,
    create_donation_payload,
)

ADMIN = TEST_USERS["admin_headers"]
GUEST = TEST_USERS["guest_headers"]


def _password_order():
    return setup_draft_order(
        privacy_mode="PASSWORD", access_password="secret",
        scheduled_start="2026-06-12T10:00:00Z", scheduled_end="2026-06-12T11:00:00Z",
    )


# --- boundary_precision_check: lock at exactly MAX_FAILED_ACCESS_ATTEMPTS -----
def test_failed_access_count_reaches_five_after_five_wrong_attempts(api):
    """PRD §3.9: "The link locks once `failed_access_count` reaches five failed
    attempts: `access_locked` becomes true at exactly the fifth wrong attempt
    (the threshold is met, not exceeded, at five) and the counter stops
    incrementing thereafter."

    Design: Difficulty/boundary_precision_check/guest_link_locks_at_exactly_max_failed_attempts
    """
    base = _password_order()
    for _ in range(5):
        api.access_service_order(base["order"]["id"], {"password": "wrong"}, GUEST)
    assert get_order(base["order"]["id"])["failed_access_count"] == 5


def test_guest_link_locks_at_fifth_wrong_attempt(api):
    """PRD §3.9: "The link locks once `failed_access_count` reaches five failed
    attempts: `access_locked` becomes true at exactly the fifth wrong attempt
    (the threshold is met, not exceeded, at five) and the counter stops
    incrementing thereafter."

    Design: Difficulty/boundary_precision_check/guest_link_locks_at_exactly_max_failed_attempts
    """
    base = _password_order()
    for _ in range(5):
        api.access_service_order(base["order"]["id"], {"password": "wrong"}, GUEST)
    assert get_order(base["order"]["id"])["access_locked"] is True


# --- Queue B: a single wrong password (below the lock threshold) --------------
def test_single_wrong_password_rejected(api):
    """PRD §3.9: "On a wrong password, provided the link is not already locked,
    the order's `failed_access_count` is incremented by one and the attempt is
    rejected with `ERR_INVALID_ACCESS_PASSWORD`."

    Design: Corner/validations/wrong_access_password_single_attempt_returns_403
    """
    base = _password_order()
    resp = api.access_service_order(base["order"]["id"], {"password": "nope"}, GUEST)
    validate_error(resp, ApiErrorId.ERR_INVALID_ACCESS_PASSWORD)


def test_single_wrong_password_increments_count_without_locking(api):
    """PRD §3.9: "On a wrong password, provided the link is not already locked,
    the order's `failed_access_count` is incremented by one and the attempt is
    rejected with `ERR_INVALID_ACCESS_PASSWORD`."

    Design: Corner/validations/wrong_access_password_single_attempt_returns_403
    """
    base = _password_order()
    api.access_service_order(base["order"]["id"], {"password": "nope"}, GUEST)
    order = get_order(base["order"]["id"])
    assert order["failed_access_count"] == 1
    assert order["access_locked"] is False


# --- Queue B: guest donation before memorial is published --------------------
def test_guest_donation_before_memorial_published_rejected(api):
    """PRD §3.9: "the donation requires a `PUBLISHED` memorial, otherwise
    `ERR_MEMORIAL_NOT_PUBLISHED`."

    Design: Corner/validations/guest_donation_before_memorial_published_returns_error
    """
    base = setup_draft_order(
        scheduled_start="2026-06-22T10:00:00Z", scheduled_end="2026-06-22T11:00:00Z",
    )
    payload = create_donation_payload(base["order"]["id"], gross_amount_cents=1000)
    validate_error(api.create_donation(payload, GUEST), ApiErrorId.ERR_MEMORIAL_NOT_PUBLISHED)


# --- Queue B: approving a guestbook entry recomputes the order count ----------
def test_approve_guestbook_entry_recomputes_order_count(api):
    """PRD §3.9: "Approving a pending entry advances its `status` from `PENDING`
    to `APPROVED` and recomputes the order's `guestbook_entry_count`, which
    counts only `APPROVED` entries."

    Design: Corner/cross_cutting_complexity_layers/guestbook_approve_recomputes_order_entry_count
    """
    base = setup_published_memorial_order(
        scheduled_start="2026-06-25T10:00:00Z", scheduled_end="2026-06-25T11:00:00Z",
    )
    entry = create_guestbook_entry(base["order"]["id"], author_name="Guest One",
                                   message="Rest in peace")
    assert get_order(base["order"]["id"])["guestbook_entry_count"] == 0  # PENDING does not count
    approved = validate_success(
        api.moderate_guestbook_entry(entry["id"], {"decision": "APPROVE"}, ADMIN)
    )
    assert approved["status"] == "APPROVED"
    assert get_order(base["order"]["id"])["guestbook_entry_count"] == 1
