"""Policy taxonomy authoring: categories, drafts, queues and their guard rails."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields
from test_helpers.constants import UNKNOWN_UUID
from test_helpers.factories import (
    create_policy_category_payload,
    create_policy_version_payload,
    create_review_queue_payload,
)
from test_helpers.fixtures import build_policy_baseline
from test_helpers.test_users import (
    ADMIN_HEADERS,
    POLICY_AUTHOR_HEADERS,
    make_qa_auditor_headers,
    make_reviewer_headers,
)


def test_policy_category_retrieval_returns_stored_row(api, world, clock_at_t0):
    """A category with no activated version reads back as DRAFT with a null back-reference.

    PRD 3.2: "A newly created category opens with `status` `DRAFT` and a null
    `active_version_id`; both are computed, and the category's `status` reaches
    `ACTIVE` only by bubble-up when one of its own versions reaches `ACTIVE`, at
    which point `active_version_id` points at that version."

    Design: Corner/entities/policy_category_retrieval_returns_stored_row
    """
    quinn = world.create_reviewer(display_name="Quinn Quality", role_class="QA")
    created = world.create_category(
        code="HATE_SPEECH", name="Hate Speech", severity_tier="T3", specialty="HATE"
    )

    fetched = validate_success(
        api.get_policy_category(created["id"], headers=make_qa_auditor_headers(quinn["id"]))
    )
    assert_fields(
        fetched,
        {
            "id": created["id"],
            "code": "HATE_SPEECH",
            "name": "Hate Speech",
            "severity_tier": "T3",
            "specialty": "HATE",
            "status": "DRAFT",
            "active_version_id": None,
            "parent_category_id": None,
            "version": 1,
        },
        "policy category",
    )


def test_policy_version_threshold_order_invalid_request_rejected(api, world, clock_at_t0):
    """An inverted threshold pair is its own 422, while a bad enum stays a 400.

    PRD 3.2: "The floor may not sit above the ceiling: `review_floor` must be
    less than or equal to `auto_action_threshold`, and a draft that inverts them
    is rejected with `ERR_THRESHOLD_ORDER_INVALID` (HTTP 422), both when the
    draft is written and again after any revision."

    Design: Corner/entities/policy_version_threshold_order_invalid_request_rejected
    """
    category = world.create_category()

    validate_error(
        api.create_policy_version(
            create_policy_version_payload(
                category["id"],
                version_label="bad",
                auto_action_threshold=0.4,
                review_floor=0.9,
            ),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.THRESHOLD_ORDER_INVALID.value,
    )
    validate_error(
        api.create_policy_category(
            create_policy_category_payload(
                code="OTHER_CODE", name="Bad Tier", severity_tier="T9", specialty="VIOLENCE"
            ),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.INVALID_REQUEST.value,
    )

    unchanged = validate_success(
        api.get_policy_category(category["id"], headers=ADMIN_HEADERS)
    )
    assert unchanged["active_version_id"] is None
    assert unchanged["status"] == "DRAFT"
    _, version_meta = validate_paginated(api.list_policy_versions(headers=ADMIN_HEADERS))
    assert version_meta["total_count"] == 0
    _, category_meta = validate_paginated(api.list_policy_categories(headers=ADMIN_HEADERS))
    assert category_meta["total_count"] == 1


def test_policy_version_with_unknown_parent_category_rejected(api, world, clock_at_t0):
    """The body foreign key resolves before any business rule on the same payload.

    PRD 2.8: "**Body-referenced identifiers and natural keys**, resolved in the
    order the operation's input list declares them: `account_id`, then
    `content_item_id`, then `policy_category_id`, then `policy_category_code`,
    then `policy_version_id`, then `case_id`, then `target_reviewer_id`, then
    each member of `exclude_reviewer_ids`."

    Design: Corner/entities/policy_version_with_unknown_parent_category_rejected
    """
    response = api.create_policy_version(
        create_policy_version_payload(
            UNKNOWN_UUID,
            version_label="v1",
            auto_action_threshold=0.4,
            review_floor=0.9,
        ),
        headers=POLICY_AUTHOR_HEADERS,
    )
    assert response.status_code == 404
    validate_error(response, ApiErrorId.CATEGORY_NOT_FOUND.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.THRESHOLD_ORDER_INVALID.value


def test_queue_specialty_mismatch_rejected(api, world, clock_at_t0):
    """A queue may not serve a specialty its own category does not declare.

    PRD 3.4: "The queue's `specialty` must be identical to the specialty declared
    on its category; a mismatch is rejected with `ERR_QUEUE_SPECIALTY_MISMATCH`
    (HTTP 422)."

    Design: Corner/errors/queue_specialty_mismatch_rejected
    """
    category = world.create_category(specialty="VIOLENCE")

    validate_error(
        api.create_review_queue(
            create_review_queue_payload(
                category["id"], name="EN Hate", language="EN", specialty="HATE"
            ),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.QUEUE_SPECIALTY_MISMATCH.value,
    )
    _, empty_meta = validate_paginated(api.list_review_queues(headers=ADMIN_HEADERS))
    assert empty_meta["total_count"] == 0

    accepted = validate_success(
        api.create_review_queue(
            create_review_queue_payload(
                category["id"], name="EN Hate", language="EN", specialty="VIOLENCE"
            ),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    assert accepted["specialty"] == "VIOLENCE"


def test_review_queue_create_then_read_and_filter(api, world, clock_at_t0):
    """Two queues on one category read back individually and narrow by language.

    PRD 3.4: "Queues have no lifecycle state of their own — they are always
    available — but they carry two live depth counters that both start at 0:
    `open_case_count`, the number of cases on the queue in `PENDING_ASSIGNMENT`,
    `ASSIGNED` or `ESCALATED`, and `unassigned_case_count`, the number sitting
    specifically in `PENDING_ASSIGNMENT`."

    Design: Corner/endpoints/review_queue_create_then_read_and_filter
    """
    rita = world.create_reviewer(display_name="Rita Frontline")
    category = world.create_category()

    first = validate_success(
        api.create_review_queue(
            create_review_queue_payload(category["id"], name="EN Violence", language="EN"),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    second = validate_success(
        api.create_review_queue(
            create_review_queue_payload(category["id"], name="DE Violence", language="DE"),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    for queue in (first, second):
        assert queue["open_case_count"] == 0
        assert queue["unassigned_case_count"] == 0
        assert queue["version"] == 1

    read = validate_success(
        api.get_review_queue(first["id"], headers=make_reviewer_headers(rita["id"]))
    )
    assert_fields(
        read,
        {
            "name": "EN Violence",
            "language": "EN",
            "specialty": "VIOLENCE",
            "policy_category_id": category["id"],
        },
        "review queue",
    )

    de_rows, de_meta = validate_paginated(
        api.list_review_queues(headers=ADMIN_HEADERS, language="DE")
    )
    assert de_meta["total_count"] == 1
    assert de_meta["has_more"] is False
    assert [row["id"] for row in de_rows] == [second["id"]]

    all_rows, all_meta = validate_paginated(
        api.list_review_queues(headers=ADMIN_HEADERS, policy_category_id=category["id"])
    )
    assert all_meta["total_count"] == 2
    assert [row["id"] for row in all_rows] == [first["id"], second["id"]]


def test_reviewer_cannot_create_policy_category(api, world):
    """Taxonomy authorship is closed to the reviewer role even with a real reviewer id.

    PRD 2.8: "**Authorization.** The acting role is permitted on the requested
    operation, else `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/reviewer_cannot_create_policy_category
    """
    build_policy_baseline(world)
    rita = world.create_reviewer(display_name="Rita Frontline")
    payload = create_policy_category_payload(
        code="SPAM_LINK", name="Spam Link", severity_tier="T3", specialty="SPAM"
    )

    refused = api.create_policy_category(payload, headers=make_reviewer_headers(rita["id"]))
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)
    _, meta = validate_paginated(api.list_policy_categories(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 1

    allowed = validate_success(
        api.create_policy_category(payload, headers=POLICY_AUTHOR_HEADERS), 201
    )
    assert allowed["status"] == "DRAFT"
    assert allowed["code"] == "SPAM_LINK"


def test_child_severity_beats_duplicate_code_on_one_create(api, world, clock_at_t0):
    """One payload breaks the severity rule and the uniqueness rule; severity is reported.

    PRD 2.8: "`ERR_CHILD_SEVERITY_EXCEEDS_PARENT`; `ERR_QUEUE_SPECIALTY_MISMATCH`;
    then the uniqueness and clock rules `ERR_DUPLICATE_CATEGORY_CODE`,
    `ERR_DUPLICATE_HANDLE` and `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Difficulty/priority_pair_validation_conflict/child_severity_safety_beats_duplicate_code_referential
    """
    parent = world.create_category(
        code="DUPE_CODE", name="Dupe Root", severity_tier="T3", specialty="VIOLENCE"
    )

    response = api.create_policy_category(
        create_policy_category_payload(
            code="DUPE_CODE",
            name="Credible Threat",
            severity_tier="T1",
            specialty="VIOLENCE",
            parent_category_id=parent["id"],
        ),
        headers=POLICY_AUTHOR_HEADERS,
    )
    assert response.status_code == 422
    validate_error(response, ApiErrorId.CHILD_SEVERITY_EXCEEDS_PARENT.value)
    assert response.json()["data"]["error_id"] != ApiErrorId.DUPLICATE_CATEGORY_CODE.value

    unchanged = validate_success(api.get_policy_category(parent["id"], headers=ADMIN_HEADERS))
    assert_fields(
        unchanged,
        {"status": "DRAFT", "active_version_id": None, "severity_tier": "T3"},
        "parent category",
    )
    _, child_meta = validate_paginated(
        api.list_policy_categories(headers=ADMIN_HEADERS, parent_category_id=parent["id"])
    )
    assert child_meta["total_count"] == 0


def test_child_severity_and_duplicate_code_are_both_live_rules(api, world, clock_at_t0):
    """Each rule fires on its own, so the paired conflict is a genuine ordering test.

    PRD 3.2: "Severity may only soften as the tree deepens: a child's tier must
    be equal to or less severe than its parent's, so a child of a `T2` parent may
    be `T2`, `T3` or `T4` but never `T1`, and a violation is rejected with
    `ERR_CHILD_SEVERITY_EXCEEDS_PARENT` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/child_severity_safety_beats_duplicate_code_referential
    """
    parent = world.create_category(
        code="DUPE_CODE", name="Dupe Root", severity_tier="T3", specialty="VIOLENCE"
    )

    severity_only = api.create_policy_category(
        create_policy_category_payload(
            code="FRESH_CODE",
            name="Credible Threat",
            severity_tier="T1",
            specialty="VIOLENCE",
            parent_category_id=parent["id"],
        ),
        headers=POLICY_AUTHOR_HEADERS,
    )
    assert severity_only.status_code == 422
    validate_error(severity_only, ApiErrorId.CHILD_SEVERITY_EXCEEDS_PARENT.value)

    duplicate_only = api.create_policy_category(
        create_policy_category_payload(
            code="DUPE_CODE",
            name="Softer Child",
            severity_tier="T4",
            specialty="VIOLENCE",
            parent_category_id=parent["id"],
        ),
        headers=POLICY_AUTHOR_HEADERS,
    )
    assert duplicate_only.status_code == 409
    validate_error(duplicate_only, ApiErrorId.DUPLICATE_CATEGORY_CODE.value)

    accepted = validate_success(
        api.create_policy_category(
            create_policy_category_payload(
                code="SOFTER_CHILD",
                name="Softer Child",
                severity_tier="T4",
                specialty="VIOLENCE",
                parent_category_id=parent["id"],
            ),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        201,
    )
    assert accepted["parent_category_id"] == parent["id"]
    assert accepted["severity_tier"] == "T4"
    _, child_meta = validate_paginated(
        api.list_policy_categories(headers=ADMIN_HEADERS, parent_category_id=parent["id"])
    )
    assert child_meta["total_count"] == 1
