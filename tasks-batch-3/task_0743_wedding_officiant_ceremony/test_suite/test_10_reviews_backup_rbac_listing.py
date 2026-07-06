"""Review eligibility, backup-officiant selection fallback, role-based access
control, and list/pagination semantics (PRD Sections 2.1, 2.3, 2.10, 3.7, 3.8, 3.9).
"""
from test_helpers import (
    fixtures as fx,
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NO_AUTH_HEADERS,
    make_coordinator_headers, make_couple_headers, make_officiant_headers,
    create_officiant_payload,
)

COORD = make_coordinator_headers()


def test_review_before_booking_completed_rejected(api):
    """PRD §3.9: "a review submitted for a booking that is not `COMPLETED` is
    rejected with `ERR_REVIEW_NOT_ALLOWED`."

    Design: Corner/validations/review_before_completion_returns_review_not_allowed
    """
    ctx = fx.setup_confirmed_booking(api)  # CONFIRMED, not COMPLETED
    resp = api.create_review(
        {"booking_id": ctx.booking["id"], "rating": 5, "text": "Early"},
        make_couple_headers(ctx.couple["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_ALLOWED.value)


def test_assign_backup_with_empty_pool_rejected(api):
    """PRD §3.7: "If no candidate is eligible, the request is rejected with
    `ERR_NO_BACKUP_AVAILABLE` and the booking remains in `BACKUP_PENDING`."

    Design: Corner/validations/assign_backup_empty_pool_returns_no_backup
    """
    ctx = fx.setup_backup_pending_booking(api)  # only officiant suspended; no eligible replacement
    resp = api.assign_backup(ctx.booking["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_BACKUP_AVAILABLE.value)
    after = fx.get_success_data(api.get_booking(ctx.booking["id"], COORD))
    assert after["status"] == "BACKUP_PENDING"


def test_couple_cannot_transition_officiant(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation — or an ownership check fails —
    the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/couple_cannot_approve_officiant_returns_unauthorized
    """
    officiant = fx.create_officiant(api)  # PENDING_REVIEW
    couple = fx.create_couple(api)
    resp = api.transition_officiant(officiant["id"], {"to_state": "ACTIVE"}, make_couple_headers(couple["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_officiant_cannot_moderate_review(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation — or an ownership check fails —
    the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/officiant_cannot_moderate_review_returns_unauthorized
    """
    ctx = fx.setup_completed_booking(api)
    review = fx.create_review(api, ctx.booking, ctx.couple, rating=5, text="Great")
    resp = api.moderate_review(
        review["id"], {"decision": "PUBLISH"}, make_officiant_headers(ctx.officiant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "Every request must be authenticated through two mandatory HTTP
    headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`,
    which declares the capacity in which they act. If either header is missing or
    malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_create_officiant_returns_401
    """
    resp = api.create_officiant(create_officiant_payload(full_name="No Auth"), NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_bookings_filtered_by_officiant(api):
    """PRD §3.8: "Bookings can be listed and filtered by `officiant_id`,
    `backup_officiant_id`, `couple_id`, `package_id`, `venue_id`, and `status`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_bookings_by_officiant_reverse_reachability
    """
    ref = fx.setup_reference(api)
    booking = fx.create_booking(api, ref.officiant, ref.couple, ref.package, ref.venue)
    resp = api.list_bookings(COORD, params={"officiant_id": ref.officiant["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert data[0]["id"] == booking["id"]


def test_list_officiants_pagination_limit_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_officiants_pagination_limit_and_has_more
    """
    fx.create_officiant(api, full_name="Off One", email="o1@x.com")
    fx.create_officiant(api, full_name="Off Two", email="o2@x.com",
                        styles=["RELIGIOUS"], denomination="CHRISTIAN", certified_jurisdictions=["NY"])
    resp = api.list_officiants(COORD, params={"limit": 1})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
