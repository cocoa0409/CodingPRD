"""Tariffs: publication state gate and half-open window overlap (PRD 2.8, 3.1)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_tariff,
    create_draft_tariff,
    create_published_tariff,
    get_success_data,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["van_line_admin_headers"]


def test_tariff_publish_twice_rejected(api):
    """PRD section 3.1: "A tariff is created in `DRAFT` and moves to `PUBLISHED`
    through publication, which enforces the window-overlap discipline of §2.8 and
    bumps the tariff's `version`; only `PUBLISHED` tariffs may back new orders."
    PRD section 2.10: "Lifecycle-state gates — from-state and sub-state
    preconditions on the target resource, endpoint by endpoint (HTTP 409)."

    Design: Corner/state_machines/tariff_publish_twice_rejected
    """
    tariff = create_published_tariff()
    assert tariff["status"] == "PUBLISHED"
    published_version = tariff["version"]

    resp = api.publish_tariff(tariff["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRANSITION_NOT_ALLOWED)

    after = get_success_data(api.get_tariff(tariff["id"], ADMIN))
    assert after["status"] == "PUBLISHED"
    assert after["version"] == published_version, (
        "the rejected re-publish must not bump the tariff version"
    )


def test_tariff_window_overlap_with_adjacency_allowed(api):
    """PRD section 2.8: "Publishing a tariff is rejected with
    `ERR_TARIFF_WINDOW_OVERLAP` (HTTP 409) when its window intersects the window
    of any other already-published tariff, with one exception: pure adjacency,
    where the existing tariff's `effective_end` equals the new tariff's
    `effective_start`, is allowed."

    Design: Corner/validations/tariff_window_overlap_with_adjacency_allowed
    """
    published = create_published_tariff(
        effective_start="2026-01-01T00:00:00Z", effective_end="2027-01-01T00:00:00Z"
    )
    assert_tariff(published)

    overlapping = create_draft_tariff(
        effective_start="2026-06-01T00:00:00Z", effective_end="2027-06-01T00:00:00Z"
    )
    resp = api.publish_tariff(overlapping["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_TARIFF_WINDOW_OVERLAP)
    after = get_success_data(api.get_tariff(overlapping["id"], ADMIN))
    assert after["status"] == "DRAFT", "the overlapping tariff must remain DRAFT"

    adjacent = create_draft_tariff(
        effective_start="2027-01-01T00:00:00Z", effective_end="2028-01-01T00:00:00Z"
    )
    ok = api.publish_tariff(adjacent["id"], ADMIN)
    result = validate_success(ok)
    assert result["status"] == "PUBLISHED", (
        "adjacency (start == prior end) is not an overlap and must publish"
    )
