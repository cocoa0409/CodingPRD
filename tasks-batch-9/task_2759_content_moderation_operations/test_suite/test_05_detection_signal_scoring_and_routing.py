"""Classifier signals: effective confidence, the routing chain and queue selection."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_rate_equals,
    expected_effective_confidence,
)
from test_helpers.constants import CLOCK_T0
from test_helpers.factories import (
    create_detection_signal_payload,
    create_moderation_case_payload,
)
from test_helpers.fixtures import (
    build_decided_case,
    build_pending_case,
    build_policy_baseline,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_signal_below_review_floor_is_discarded_without_a_case(api, world):
    """Below the floor the signal row survives but nothing else moves.

    PRD 3.3: "If the effective confidence is strictly below the pinned version's
    `review_floor`, the disposition is `DISCARDED`: no case is created,
    `resulting_case_id` and `pinned_policy_version_label` stay null, and the
    content item is untouched."

    Design: Corner/calculations/signal_below_review_floor_is_discarded_without_a_case
    """
    base = build_policy_baseline(world)
    item = world.create_content(base.account_id)

    discarded = validate_success(
        api.create_detection_signal(
            create_detection_signal_payload(item["id"], classifier_confidence=0.3),
            headers=ADMIN_HEADERS,
        ),
        201,
    )
    assert_rate_equals(discarded["effective_confidence"], 0.3, "effective_confidence")
    assert discarded["disposition"] == "DISCARDED"
    assert discarded["resulting_case_id"] is None
    assert discarded["pinned_policy_version_label"] is None

    _, case_meta = validate_paginated(
        api.list_moderation_cases(headers=ADMIN_HEADERS, content_item_id=item["id"])
    )
    assert case_meta["total_count"] == 0
    content = world.get_content(item["id"])
    assert_fields(
        content,
        {"review_status": "CLEAR", "visibility_status": "LIVE", "open_case_count": 0},
        "content item",
    )
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0
    signal_rows, signal_meta = validate_paginated(
        api.list_content_item_detection_signals(item["id"], headers=ADMIN_HEADERS)
    )
    assert signal_meta["total_count"] == 1
    assert [row["id"] for row in signal_rows] == [discarded["id"]]

    at_floor = world.submit_signal(item["id"], classifier_confidence=0.4)
    assert at_floor["disposition"] == "HUMAN_REVIEW"
    assert at_floor["resulting_case_id"] is not None


def test_queue_selection_prefers_least_loaded_then_oldest_queue(api, world):
    """Three signals alternate between two identical queues by backlog then age.

    PRD 3.3: "Candidates are ranked by `unassigned_case_count` ascending — the
    shallowest backlog wins — and ties are broken by `created_at` ascending, that
    is, the older queue wins; the queue's `id` is never used as a tie-breaker."

    Design: Corner/calculations/queue_selection_prefers_least_loaded_then_oldest_queue
    """
    base = build_policy_baseline(world)
    second_queue = world.create_queue(base.category_id, name="EN Violence B")
    items = [world.create_content(base.account_id) for _ in range(3)]

    cases = []
    for item in items:
        signal = world.submit_signal(item["id"], classifier_confidence=0.7)
        cases.append(world.get_case(signal["resulting_case_id"]))

    assert cases[0]["queue_id"] == base.queue_id
    assert cases[1]["queue_id"] == second_queue["id"]
    assert cases[2]["queue_id"] == base.queue_id
    for case in cases:
        assert_instant_equals(case["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at")

    older = world.get_queue(base.queue_id)
    newer = world.get_queue(second_queue["id"])
    assert older["open_case_count"] == 2
    assert older["unassigned_case_count"] == 2
    assert newer["open_case_count"] == 1
    assert newer["unassigned_case_count"] == 1


def test_signal_without_a_matching_queue_is_rejected_and_fully_rolled_back(api, world):
    """An empty queue pool rolls back the signal itself, unlike the discard path.

    PRD 3.3: "If the candidate set is empty the entire request fails with
    `ERR_NO_ELIGIBLE_QUEUE` (HTTP 422) and nothing is persisted, not even the
    detection signal that provoked it."

    Design: Corner/validations/signal_without_a_matching_queue_is_rejected_and_fully_rolled_back
    """
    base = build_policy_baseline(world)
    german_item = world.create_content(base.account_id, language="DE")

    refused = api.create_detection_signal(
        create_detection_signal_payload(german_item["id"], classifier_confidence=0.7),
        headers=ADMIN_HEADERS,
    )
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.NO_ELIGIBLE_QUEUE.value)

    _, signal_meta = validate_paginated(
        api.list_content_item_detection_signals(german_item["id"], headers=ADMIN_HEADERS)
    )
    assert signal_meta["total_count"] == 0
    _, case_meta = validate_paginated(api.list_moderation_cases(headers=ADMIN_HEADERS))
    assert case_meta["total_count"] == 0
    content = world.get_content(german_item["id"])
    assert content["review_status"] == "CLEAR"
    assert content["open_case_count"] == 0
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0

    german_queue = world.create_queue(base.category_id, name="DE Violence", language="DE")
    routed = world.submit_signal(german_item["id"], classifier_confidence=0.7)
    assert routed["disposition"] == "HUMAN_REVIEW"
    assert world.get_case(routed["resulting_case_id"])["queue_id"] == german_queue["id"]


def test_signal_on_removed_content_rejected(api, world):
    """Removed content is closed to further scanning through either intake path.

    PRD 3.3: "Content whose `visibility_status` is already `REMOVED` cannot be
    scanned again: such a submission is rejected with `ERR_CONTENT_NOT_LIVE`
    (HTTP 409)."

    Design: Corner/errors/signal_on_removed_content_rejected
    """
    base = build_workforce_baseline(world)
    scenario = build_decided_case(base, outcome="REMOVE")
    assert world.get_content(scenario.content_id)["visibility_status"] == "REMOVED"

    refused = api.create_detection_signal(
        create_detection_signal_payload(
            scenario.content_id, classifier_id="clf-violence-2", classifier_confidence=0.95
        ),
        headers=ADMIN_HEADERS,
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.CONTENT_NOT_LIVE.value)

    _, signal_meta = validate_paginated(
        api.list_content_item_detection_signals(scenario.content_id, headers=ADMIN_HEADERS)
    )
    assert signal_meta["total_count"] == 1
    _, case_meta = validate_paginated(
        api.list_moderation_cases(headers=ADMIN_HEADERS, content_item_id=scenario.content_id)
    )
    assert case_meta["total_count"] == 1

    validate_error(
        api.create_moderation_case(
            create_moderation_case_payload(scenario.content_id), headers=ADMIN_HEADERS
        ),
        ApiErrorId.CONTENT_NOT_LIVE.value,
    )


def test_effective_confidence_multiplies_tier_then_adds_repeat_bonus(api, world):
    """The tier discount is multiplicative and the repeat bonus is added afterwards.

    PRD 3.3: "take the confidence multiplier for the author account's `tier` —
    1.00 for `STANDARD`, 0.85 for `HIGH_PROFILE`, 0.80 for `GOVERNMENT` — and
    multiply the `classifier_confidence` by it; then add a repeat-offender bonus
    of 0.01 for each of the account's current `strike_points`, counting at most
    ten points, so the bonus is at most 0.10; then clamp the result so it can
    never exceed 1.0; and only then round half up to four decimal places, exactly
    once."

    Design: Difficulty/combinatorial_formula/effective_confidence_tier_and_repeat_nonlinear
    """
    base = build_workforce_baseline(
        world, account_overrides={"external_handle": "acct_vip", "tier": "HIGH_PROFILE"}
    )
    first = build_pending_case(base, classifier_confidence=0.9)
    assert_rate_equals(first.signal["effective_confidence"], 0.765, "effective_confidence")
    world.assign(first.case_id, target_reviewer_id=base.senior_id)
    world.decide(first.case_id, base.senior_id, outcome="REMOVE")
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["standing"] == "LIMITED"
    assert account["lifetime_removed_count"] == 1

    second_item = world.create_content(base.account_id, graphic_weight=1)
    signal = world.submit_signal(second_item["id"], classifier_confidence=0.95)
    expected = expected_effective_confidence(0.95, "HIGH_PROFILE", 4)
    assert_rate_equals(expected, 0.8475, "expected effective_confidence")
    assert_rate_equals(signal["effective_confidence"], 0.8475, "effective_confidence")
    assert abs(signal["effective_confidence"] - 0.8415) > 1e-9
    assert signal["disposition"] == "HUMAN_REVIEW"


def test_high_profile_account_routes_to_human_review_with_flagged_posture(api, world):
    """The tier branch fires ahead of the threshold branch and flags the case.

    PRD 3.3: "Otherwise, if the author account's `tier` is `HIGH_PROFILE` or
    `GOVERNMENT`, the disposition is again `HUMAN_REVIEW`, with `escalation_tier`
    1 and `escalation_reason` `HIGH_PROFILE`."

    Design: Difficulty/combinatorial_formula/effective_confidence_tier_and_repeat_nonlinear
    """
    base = build_workforce_baseline(
        world, account_overrides={"external_handle": "acct_vip", "tier": "HIGH_PROFILE"}
    )
    first = build_pending_case(base, classifier_confidence=0.9)
    world.assign(first.case_id, target_reviewer_id=base.senior_id)
    world.decide(first.case_id, base.senior_id, outcome="REMOVE")

    second_item = world.create_content(base.account_id, graphic_weight=1)
    signal = world.submit_signal(second_item["id"], classifier_confidence=0.95)
    case = world.get_case(signal["resulting_case_id"])
    assert_fields(
        case,
        {
            "status": "PENDING_ASSIGNMENT",
            "escalation_tier": 1,
            "escalation_reason": "HIGH_PROFILE",
            "queue_id": base.queue_id,
            "policy_version_id": base.version_id,
        },
        "moderation case",
    )
    assert_instant_equals(case["sla_due_at"], "2026-08-01T09:30:00Z", "sla_due_at")
    assert_rate_equals(signal["effective_confidence"], 0.8475, "effective_confidence")


def test_effective_confidence_just_below_auto_action_threshold_needs_human_review(api, world):
    """One ten-thousandth under the ceiling still goes to a human and a queue.

    PRD 3.3: "Otherwise, if the effective confidence is at or above the pinned
    version's `auto_action_threshold`, the disposition is `AUTO_ACTION`."

    Design: Difficulty/boundary_precision_check/effective_confidence_exactly_at_auto_action_threshold
    """
    base = build_policy_baseline(world)
    item = world.create_content(base.account_id, graphic_weight=2)

    signal = world.submit_signal(item["id"], classifier_confidence=0.8999)
    assert_rate_equals(signal["effective_confidence"], 0.8999, "effective_confidence")
    assert signal["disposition"] == "HUMAN_REVIEW"

    case = world.get_case(signal["resulting_case_id"])
    assert_fields(
        case,
        {
            "status": "PENDING_ASSIGNMENT",
            "queue_id": base.queue_id,
            "decision_source": None,
            "decision_outcome": None,
        },
        "moderation case",
    )
    assert_instant_equals(case["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at")
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1


def test_effective_confidence_exactly_at_auto_action_threshold_auto_actions(api, world):
    """Exactly on the threshold the case is born DECIDED with no queue at all.

    PRD 3.3: "An `AUTO_ACTION` signal mints a **ModerationCase** that is born in
    `DECIDED`, with `origin` `CLASSIFIER` and `detection_signal_id` pointing back
    at the signal, and the signal records the new case in `resulting_case_id`."

    Design: Difficulty/boundary_precision_check/effective_confidence_exactly_at_auto_action_threshold
    """
    base = build_policy_baseline(world)
    below_item = world.create_content(base.account_id, graphic_weight=2)
    boundary_item = world.create_content(base.account_id, graphic_weight=2)

    below = world.submit_signal(below_item["id"], classifier_confidence=0.8999)
    assert below["disposition"] == "HUMAN_REVIEW"

    boundary = world.submit_signal(boundary_item["id"], classifier_confidence=0.9)
    assert_rate_equals(boundary["effective_confidence"], 0.9, "effective_confidence")
    assert boundary["disposition"] == "AUTO_ACTION"

    case = world.get_case(boundary["resulting_case_id"])
    assert_fields(
        case,
        {
            "status": "DECIDED",
            "origin": "CLASSIFIER",
            "decision_source": "AUTO",
            "decision_outcome": "REMOVE",
            "decided_by_reviewer_id": None,
            "queue_id": None,
            "sla_due_at": None,
            "sla_breached": False,
            "strike_points_applied": 4,
        },
        "moderation case",
    )
    assert_instant_equals(case["decided_at"], CLOCK_T0, "decided_at")
    assert_instant_equals(case["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at")

    content = world.get_content(boundary_item["id"])
    assert content["visibility_status"] == "REMOVED"
    assert content["review_status"] == "ACTIONED"
    account = world.get_account(base.account_id)
    assert_fields(
        account,
        {"strike_points": 4, "standing": "LIMITED", "lifetime_removed_count": 1},
        "account",
    )
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1
