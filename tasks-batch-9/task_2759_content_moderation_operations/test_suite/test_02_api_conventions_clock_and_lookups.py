"""Envelope conventions, identity headers, the logical clock and lookup failures."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_immutable_signal_shape,
    assert_instant_equals,
    assert_rate_equals,
    assert_request_id,
)
from test_helpers.constants import CLOCK_T0, UNKNOWN_UUID
from test_helpers.factories import create_content_item_payload
from test_helpers.fixtures import build_pending_case, build_policy_baseline
from test_helpers.test_users import (
    ADMIN_HEADERS,
    headers_without_role,
    make_headers,
)


def test_unknown_ids_return_entity_specific_not_found(api, world, clock_at_t0):
    """The same unknown UUID answers with a different 404 id on each read path.

    PRD 2.8: "**Path identifiers**, resolved strictly left to right, each with
    its own not-found code: `ERR_ACCOUNT_NOT_FOUND`, `ERR_CONTENT_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_POLICY_VERSION_NOT_FOUND`,
    `ERR_REVIEWER_NOT_FOUND`, `ERR_QUEUE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_DETECTION_SIGNAL_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_AUDIT_SAMPLE_NOT_FOUND` and `ERR_REPORT_NOT_FOUND`."

    Design: Corner/errors/unknown_ids_return_entity_specific_not_found
    """
    probes = [
        (api.get_account(UNKNOWN_UUID, headers=ADMIN_HEADERS), ApiErrorId.ACCOUNT_NOT_FOUND),
        (api.get_content_item(UNKNOWN_UUID, headers=ADMIN_HEADERS), ApiErrorId.CONTENT_NOT_FOUND),
        (api.get_review_queue(UNKNOWN_UUID, headers=ADMIN_HEADERS), ApiErrorId.QUEUE_NOT_FOUND),
        (
            api.get_transparency_report(UNKNOWN_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.REPORT_NOT_FOUND,
        ),
        (
            api.get_audit_sample(UNKNOWN_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.AUDIT_SAMPLE_NOT_FOUND,
        ),
        (
            api.get_detection_signal(UNKNOWN_UUID, headers=ADMIN_HEADERS),
            ApiErrorId.DETECTION_SIGNAL_NOT_FOUND,
        ),
    ]
    for response, error_id in probes:
        assert response.status_code == 404
        validate_error(response, error_id.value)
        body = response.json()
        assert body["response_type"] == "error"
        assert_request_id(body["meta"])
        assert body["data"]["message"]


def test_request_without_role_header_is_unauthenticated(api, world, clock_at_t0):
    """Identity is checked before authorisation, so a missing role is a 401.

    PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of the
    six role names below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/errors/request_without_role_header_is_unauthenticated
    """
    world.create_reviewer(display_name="Rita Frontline")

    validate_error(
        api.list_reviewers(headers=headers_without_role()),
        ApiErrorId.UNAUTHENTICATED.value,
    )
    validate_error(
        api.list_reviewers(headers=make_headers("ts-ops", "SuperModerator")),
        ApiErrorId.UNAUTHENTICATED.value,
    )
    rows, meta = validate_paginated(api.list_reviewers(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_moderation_case_get_with_unknown_id_returns_not_found(api, world, clock_at_t0):
    """A well-formed but unresolvable case id is a per-entity 404, not an empty 200.

    PRD 2.8: "**Path identifiers**, resolved strictly left to right, each with
    its own not-found code: `ERR_ACCOUNT_NOT_FOUND`, `ERR_CONTENT_NOT_FOUND`,
    `ERR_CATEGORY_NOT_FOUND`, `ERR_POLICY_VERSION_NOT_FOUND`,
    `ERR_REVIEWER_NOT_FOUND`, `ERR_QUEUE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
    `ERR_DETECTION_SIGNAL_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`,
    `ERR_AUDIT_SAMPLE_NOT_FOUND` and `ERR_REPORT_NOT_FOUND`."

    Design: Corner/entities/moderation_case_get_with_unknown_id_returns_not_found
    """
    case_read = api.get_moderation_case(UNKNOWN_UUID, headers=ADMIN_HEADERS)
    assert case_read.status_code == 404
    assert case_read.json()["response_type"] == "error"
    validate_error(case_read, ApiErrorId.CASE_NOT_FOUND.value)

    appeal_read = api.get_appeal(UNKNOWN_UUID, headers=ADMIN_HEADERS)
    validate_error(appeal_read, ApiErrorId.APPEAL_NOT_FOUND.value)


def test_reviewer_listing_paginates_with_total_count_and_has_more(api, world, clock_at_t0):
    """Two pages over three rows report the unpaginated total and the remainder flag.

    PRD 2.3: "`total_count` is the number of records that match the filter before
    pagination is applied, and `has_more` is true when records remain beyond the
    returned page."

    Design: Corner/entities/reviewer_listing_paginates_with_total_count_and_has_more
    """
    rita = world.create_reviewer(display_name="Rita Frontline", role_class="FRONTLINE")
    quinn = world.create_reviewer(display_name="Quinn Quality", role_class="QA")
    sven = world.create_reviewer(display_name="Sven Senior", role_class="SENIOR")

    page_one, meta_one = validate_paginated(
        api.list_reviewers(headers=ADMIN_HEADERS, limit=2, offset=0)
    )
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert [row["id"] for row in page_one] == [rita["id"], quinn["id"]]

    page_two, meta_two = validate_paginated(
        api.list_reviewers(headers=ADMIN_HEADERS, limit=2, offset=2)
    )
    assert meta_two["limit"] == 2
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert [row["id"] for row in page_two] == [sven["id"]]

    qa_rows, qa_meta = validate_paginated(
        api.list_reviewers(headers=ADMIN_HEADERS, role_class="QA")
    )
    assert qa_meta["total_count"] == 1
    assert [row["id"] for row in qa_rows] == [quinn["id"]]


def test_reviewer_system_fields_are_server_minted(api, world):
    """A later mutation advances version and updated_at while created_at holds still.

    PRD 2.5: "**`version`** (integer): a counter that starts at 1 when the record
    is created and increases by one on every mutation of that record, including
    server-initiated cascades."

    Design: Corner/entities/reviewer_system_fields_are_server_minted
    """
    base = build_policy_baseline(world)
    reviewer = world.create_reviewer(display_name="Rita Frontline")
    assert reviewer["version"] == 1
    assert_instant_equals(reviewer["created_at"], CLOCK_T0, "created_at")
    assert_instant_equals(reviewer["updated_at"], CLOCK_T0, "updated_at")

    world.set_clock("2026-08-01T10:00:00Z")
    granted = world.certify(reviewer["id"], base.version_id, reviewer["version"])
    assert granted["id"] == reviewer["id"]
    assert granted["version"] == 2
    assert granted["certified_policy_version_ids"] == [base.version_id]
    assert_instant_equals(granted["created_at"], CLOCK_T0, "created_at")
    assert_instant_equals(granted["updated_at"], "2026-08-01T10:00:00Z", "updated_at")


def test_detection_signal_is_immutable_with_no_version_field(api, world):
    """The signal row carries only the two system fields an immutable record needs.

    PRD 2.5: "A signal is immutable once written: it carries `id` and
    `created_at` only, and it has neither an `updated_at` field nor a `version`
    field."

    Design: Corner/entities/detection_signal_is_immutable_with_no_version_field
    """
    base = build_policy_baseline(world)
    scenario = build_pending_case(base)

    signal = validate_success(
        api.get_detection_signal(scenario.signal["id"], headers=ADMIN_HEADERS)
    )
    assert signal["id"] == scenario.signal["id"]
    assert signal["created_at"]
    assert_immutable_signal_shape(signal)
    assert_rate_equals(signal["effective_confidence"], 0.7, "effective_confidence")
    assert signal["disposition"] == "HUMAN_REVIEW"
    assert signal["pinned_policy_version_label"] == "v1"
    assert signal["resulting_case_id"] == scenario.case_id


def test_clock_cannot_move_backwards(api, world):
    """The clock comparison is at-or-after, so equal is accepted and earlier is not.

    PRD 2.4: "The clock is monotonic: the supplied instant must be at or after
    the clock's current value, and an earlier instant is rejected with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422). Setting the clock to the value it
    already holds is permitted."

    Design: Corner/validations/clock_cannot_move_backwards
    """
    world.set_clock("2026-08-01T12:00:00Z")

    validate_error(
        api.set_clock("2026-08-01T11:59:59Z", headers=ADMIN_HEADERS),
        ApiErrorId.CLOCK_NOT_MONOTONIC.value,
    )
    same = validate_success(api.set_clock("2026-08-01T12:00:00Z", headers=ADMIN_HEADERS))
    assert_instant_equals(same["current_utc"], "2026-08-01T12:00:00Z", "current_utc")
    forward = validate_success(api.set_clock("2026-08-01T12:00:01Z", headers=ADMIN_HEADERS))
    assert_instant_equals(forward["current_utc"], "2026-08-01T12:00:01Z", "current_utc")

    account = world.create_account(external_handle="acct_clock")
    item = validate_success(
        api.create_content_item(
            create_content_item_payload(account["id"]), headers=ADMIN_HEADERS
        ),
        201,
    )
    assert_instant_equals(item["posted_at"], "2026-08-01T12:00:01Z", "posted_at")
