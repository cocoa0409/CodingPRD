"""Account registration and content intake."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_bare_uuid, assert_instant_equals, assert_fields
from test_helpers.constants import CLOCK_T0
from test_helpers.factories import (
    OMIT,
    create_account_payload,
    create_content_item_payload,
)
from test_helpers.fixtures import build_workforce_baseline, drive_account_to_banned
from test_helpers.test_users import ADMIN_HEADERS


def test_account_defaults_when_optional_inputs_omitted(api, world, clock_at_t0):
    """Omitted tier and credit seed fall back to the documented account defaults.

    PRD 3.1: "An admin may also seed `appeal_credits_remaining`, which must not
    be negative; when the field is omitted the account opens with three credits."

    Design: Corner/entities/account_defaults_applied_when_optional_inputs_omitted
    """
    payload = create_account_payload(
        external_handle="acct_defaults", region_code="DE", tier=OMIT
    )
    assert "tier" not in payload
    assert "appeal_credits_remaining" not in payload
    created = validate_success(api.create_account(payload, headers=ADMIN_HEADERS), 201)
    assert_fields(
        created,
        {
            "tier": "STANDARD",
            "appeal_credits_remaining": 3,
            "strike_points": 0,
            "lifetime_removed_count": 0,
            "standing": "GOOD_STANDING",
        },
        "account",
    )

    explicit = validate_success(
        api.create_account(
            create_account_payload(external_handle="acct_vip", tier="HIGH_PROFILE"),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    assert explicit["tier"] == "HIGH_PROFILE"


def test_content_item_creation_returns_all_declared_fields(api, world, account):
    """Ingestion answers with every stored field of the content item.

    PRD 3.1: "The server stamps `posted_at` from the logical clock."

    Design: Corner/entities/content_item_creation_returns_all_declared_fields
    """
    payload = create_content_item_payload(
        account["id"], language="EN", media_kind="VIDEO", graphic_weight=4
    )
    response = api.create_content_item(payload, headers=ADMIN_HEADERS)
    assert response.json()["response_type"] == "object"
    item = validate_success(response, 201)
    assert_fields(
        item,
        {
            "account_id": account["id"],
            "language": "EN",
            "media_kind": "VIDEO",
            "graphic_weight": 4,
            "visibility_status": "LIVE",
            "review_status": "CLEAR",
            "open_case_count": 0,
            "reinstated_at": None,
            "version": 1,
        },
        "content item",
    )
    assert_bare_uuid(item["id"], "content item id")
    assert_instant_equals(item["posted_at"], CLOCK_T0, "posted_at")
    assert_instant_equals(item["created_at"], CLOCK_T0, "created_at")
    assert_instant_equals(item["updated_at"], CLOCK_T0, "updated_at")


def test_content_item_missing_required_account_id_rejected(api, world, clock_at_t0):
    """A missing required input fails well-formedness before any lookup runs.

    PRD 2.8: "Every required input present, types correct, enum members
    recognised, numeric ranges respected, arrays that must be non-empty
    non-empty, confidence and threshold values inside 0.0000 to 1.0000,
    `break_minutes` positive, and `correct_outcome` supplied whenever an audit
    verdict is a disagreement."

    Design: Corner/entities/content_item_missing_required_account_id_rejected
    """
    validate_error(
        api.create_content_item(
            {"language": "EN", "media_kind": "TEXT"}, headers=ADMIN_HEADERS
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )
    rows, meta = validate_paginated(api.list_content_items(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert rows == []


def test_content_item_starts_live_and_clear(api, world, account):
    """A fresh item occupies the initial value of both status dimensions.

    PRD 3.1: "`visibility_status` is what the public sees and takes the values
    `LIVE`, `AGE_GATED`, `REMOVED` and `REINSTATED`, starting at `LIVE`."

    Design: Corner/state_machines/content_item_starts_live_and_clear
    """
    created = validate_success(
        api.create_content_item(
            create_content_item_payload(account["id"], graphic_weight=2),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    fetched = validate_success(api.get_content_item(created["id"], headers=ADMIN_HEADERS))
    for row in (created, fetched):
        assert row["visibility_status"] == "LIVE"
        assert row["review_status"] == "CLEAR"
        assert row["open_case_count"] == 0
        assert row["reinstated_at"] is None

    live_rows, live_meta = validate_paginated(
        api.list_content_items(headers=ADMIN_HEADERS, visibility_status="LIVE")
    )
    assert live_meta["total_count"] == 1
    assert [row["id"] for row in live_rows] == [created["id"]]
    _, review_meta = validate_paginated(
        api.list_content_items(headers=ADMIN_HEADERS, review_status="UNDER_REVIEW")
    )
    assert review_meta["total_count"] == 0


def test_duplicate_external_handle_rejected(api, world, clock_at_t0):
    """The account handle is a natural key, so a repeat registration is refused.

    PRD 3.1: "Registration supplies an `external_handle` of between 1 and 64
    characters, which must be unique across all accounts — a collision is
    rejected with `ERR_DUPLICATE_HANDLE` — and a `region_code` of exactly two
    uppercase letters identifying the registration region."

    Design: Corner/errors/duplicate_external_handle_rejected
    """
    first = validate_success(
        api.create_account(
            create_account_payload(external_handle="acct_dup", region_code="US"),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    validate_error(
        api.create_account(
            create_account_payload(
                external_handle="acct_dup", region_code="DE", tier="HIGH_PROFILE"
            ),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.DUPLICATE_HANDLE.value,
    )
    unchanged = validate_success(api.get_account(first["id"], headers=ADMIN_HEADERS))
    assert unchanged["region_code"] == "US"
    assert unchanged["tier"] == "STANDARD"


def test_content_ingestion_for_banned_account_rejected(api, world):
    """A banned posture is a hard block on further ingestion.

    PRD 3.1: "A `BANNED` account is a hard block on ingestion: attempting to
    ingest new content for an author whose `standing` is `BANNED` fails with
    `ERR_ACCOUNT_BANNED` (HTTP 403), and that block lifts by itself as soon as a
    reversal moves the posture off `BANNED`."

    Design: Corner/errors/content_ingestion_for_banned_account_rejected
    """
    base = build_workforce_baseline(world)
    account = drive_account_to_banned(base)
    assert account["strike_points"] == 15
    assert account["lifetime_removed_count"] == 3
    assert account["standing"] == "BANNED"

    _, before_meta = validate_paginated(
        api.list_content_items(headers=ADMIN_HEADERS, account_id=base.account_id)
    )
    assert before_meta["total_count"] == 3
    validate_error(
        api.create_content_item(
            create_content_item_payload(base.account_id, graphic_weight=1),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.ACCOUNT_BANNED.value,
    )
    _, after_meta = validate_paginated(
        api.list_content_items(headers=ADMIN_HEADERS, account_id=base.account_id)
    )
    assert after_meta["total_count"] == 3
