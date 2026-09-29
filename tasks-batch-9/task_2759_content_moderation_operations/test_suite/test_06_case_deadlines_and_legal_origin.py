"""Review deadlines under congestion, legal-request cases and case reachability."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    expected_sla_minutes,
)
from test_helpers.factories import (
    OMIT,
    create_moderation_case_payload,
    legal_case_payload,
)
from test_helpers.fixtures import (
    build_decided_case,
    build_policy_baseline,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS, LEGAL_HEADERS


def _open_human_review_cases(world, base, count, graphic_weight=1):
    """Open `count` PENDING_ASSIGNMENT cases on one queue, oldest first."""
    cases = []
    for _ in range(count):
        item = world.create_content(base.account_id, graphic_weight=graphic_weight)
        signal = world.submit_signal(item["id"], classifier_confidence=0.7)
        cases.append(world.get_case(signal["resulting_case_id"]))
    return cases


def test_sla_due_at_reads_the_post_increment_queue_depth(api, world):
    """The sixth case counts itself, so it inherits the congested multiplier.

    PRD 3.3: "Step two reads the queue's `open_case_count` **after** that
    increment, so the count includes this case; reading the pre-increment count
    is a different and wrong answer."

    Design: Difficulty/combinatorial_formula/sla_due_at_congestion_post_increment_order
    """
    base = build_policy_baseline(world)
    cases = _open_human_review_cases(world, base, 6)

    assert_instant_equals(cases[4]["sla_due_at"], "2026-08-01T11:00:00Z", "fifth sla_due_at")
    assert_instant_equals(cases[5]["sla_due_at"], "2026-08-01T12:00:00Z", "sixth sla_due_at")
    assert cases[5]["status"] == "PENDING_ASSIGNMENT"
    assert cases[5]["escalation_tier"] == 0

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 6
    assert queue["unassigned_case_count"] == 6


def test_sla_congestion_multiplier_steps_up_at_the_sixth_open_case(api, world):
    """Five cases share the uncongested deadline and only the sixth moves the band.

    PRD 3.3: "Step three converts that depth into a congestion multiplier: a
    queue holding 5 or fewer open cases multiplies by 1.0, a queue holding 6
    through 15 multiplies by 1.5, and a queue holding 16 or more multiplies by
    2.0."

    Design: Difficulty/combinatorial_formula/sla_due_at_congestion_post_increment_order
    """
    assert expected_sla_minutes(240, 5, "T2") == 120
    assert expected_sla_minutes(240, 6, "T2") == 180

    base = build_policy_baseline(world)
    cases = _open_human_review_cases(world, base, 6)

    for index, case in enumerate(cases[:5]):
        assert_instant_equals(
            case["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at case %d" % (index + 1)
        )
    assert_instant_equals(cases[5]["sla_due_at"], "2026-08-01T12:00:00Z", "sixth sla_due_at")

    refreshed = world.get_case(cases[4]["id"])
    assert_instant_equals(
        refreshed["sla_due_at"], "2026-08-01T11:00:00Z", "fifth sla_due_at on re-read"
    )
    assert refreshed["sla_breached"] is False


def test_legal_request_case_opens_escalated_with_the_legal_sla(api, world):
    """A legal request is born escalated, carries the day-long SLA and decides itself.

    PRD 3.5: "A legal case opens directly in `ESCALATED` with `escalation_reason`
    `LEGAL_REQUEST` and `escalation_tier` 2. Its `queue_id` is still selected by
    the queue rule so the work is attributed to the right specialty, and the
    queue's `open_case_count` rises by one — but its `unassigned_case_count` does
    **not**, because an `ESCALATED` case is not queue-assignable. Its
    `sla_due_at` is the current instant plus 1440 minutes."

    Design: Corner/endpoints/legal_request_case_opens_escalated_with_the_legal_sla
    """
    base = build_policy_baseline(world)
    item = world.create_content(base.account_id, graphic_weight=2)

    created = validate_success(
        api.create_moderation_case(
            legal_case_payload(item["id"], legal_jurisdiction="DE", legal_reference="LR-2026-42"),
            headers=LEGAL_HEADERS,
        ),
        201,
    )
    assert_fields(
        created,
        {
            "status": "ESCALATED",
            "escalation_reason": "LEGAL_REQUEST",
            "escalation_tier": 2,
            "origin": "LEGAL_REQUEST",
            "detection_signal_id": None,
            "queue_id": base.queue_id,
            "policy_version_id": base.version_id,
        },
        "legal case",
    )
    assert_instant_equals(created["sla_due_at"], "2026-08-02T09:00:00Z", "sla_due_at")
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0

    decided = validate_success(
        api.decide_case(
            created["id"], {"outcome": "REMOVE", "rationale": "Court order"}, headers=LEGAL_HEADERS
        )
    )
    assert_fields(
        decided,
        {"decision_source": "LEGAL", "decided_by_reviewer_id": None, "sla_breached": False},
        "decided legal case",
    )
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["standing"] == "LIMITED"
    assert world.get_content(item["id"])["visibility_status"] == "REMOVED"

    other_item = world.create_content(base.account_id, graphic_weight=2)
    refused = api.create_moderation_case(
        legal_case_payload(other_item["id"], legal_jurisdiction="DE", legal_reference="LR-2026-43"),
        headers=ADMIN_HEADERS,
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)


def test_legal_case_without_jurisdiction_rejected(api, world):
    """The legal origin makes two otherwise optional inputs mandatory.

    PRD 3.5: "A legal case carries a `legal_jurisdiction` of exactly two
    uppercase letters naming the requesting jurisdiction and a `legal_reference`
    holding the government or court reference string; a `LEGAL_REQUEST` submitted
    without them is rejected with `ERR_LEGAL_CASE_REQUIRES_JURISDICTION` (HTTP
    422)."

    Design: Corner/errors/legal_case_without_jurisdiction_rejected
    """
    base = build_policy_baseline(world)
    item = world.create_content(base.account_id, graphic_weight=2)

    refused = api.create_moderation_case(
        legal_case_payload(item["id"], legal_jurisdiction=OMIT, legal_reference=OMIT),
        headers=LEGAL_HEADERS,
    )
    assert refused.status_code == 422
    validate_error(refused, ApiErrorId.LEGAL_CASE_REQUIRES_JURISDICTION.value)
    _, meta = validate_paginated(api.list_moderation_cases(headers=ADMIN_HEADERS))
    assert meta["total_count"] == 0
    assert world.get_content(item["id"])["review_status"] == "CLEAR"

    accepted = validate_success(
        api.create_moderation_case(
            legal_case_payload(item["id"], legal_jurisdiction="DE", legal_reference="LR-1"),
            headers=LEGAL_HEADERS,
        ),
        201,
    )
    assert accepted["status"] == "ESCALATED"

    manual_item = world.create_content(base.account_id, graphic_weight=2)
    manual = validate_success(
        api.create_moderation_case(
            create_moderation_case_payload(manual_item["id"]), headers=ADMIN_HEADERS
        ),
        201,
    )
    assert manual["origin"] == "MANUAL_REPORT"
    assert manual["legal_jurisdiction"] is None
    assert manual["legal_reference"] is None


def test_moderation_case_reachable_by_every_declared_foreign_key(api, world):
    """Each of the case's references is a working filter on the case collection.

    PRD 3.5: "The case collection is the reverse-reachability channel for work
    created as a side effect of detection, and can be narrowed by
    `content_item_id`, `detection_signal_id`, `policy_version_id`, `queue_id`,
    `assigned_reviewer_id`, `decided_by_reviewer_id`, `status` or `origin`."

    Design: Corner/entities/moderation_case_reachable_by_every_declared_foreign_key
    """
    base = build_workforce_baseline(world)
    scenario = build_decided_case(base, outcome="NO_ACTION")
    case = world.get_case(scenario.case_id)
    assert case["assigned_reviewer_id"] == base.frontline_id
    assert case["decided_by_reviewer_id"] == base.frontline_id

    filters = [
        {"content_item_id": scenario.content_id},
        {"detection_signal_id": case["detection_signal_id"]},
        {"policy_version_id": base.version_id},
        {"queue_id": base.queue_id},
        {"assigned_reviewer_id": base.frontline_id},
        {"decided_by_reviewer_id": base.frontline_id},
    ]
    for narrowing in filters:
        rows, meta = validate_paginated(
            api.list_moderation_cases(headers=ADMIN_HEADERS, **narrowing)
        )
        assert meta["total_count"] == 1, narrowing
        assert [row["id"] for row in rows] == [scenario.case_id], narrowing

    signal_rows, signal_meta = validate_paginated(
        api.list_content_item_detection_signals(scenario.content_id, headers=ADMIN_HEADERS)
    )
    assert signal_meta["total_count"] == 1
    assert signal_rows[0]["id"] == case["detection_signal_id"]
    assert signal_rows[0]["resulting_case_id"] == scenario.case_id

    assert case["decision_outcome"] == "NO_ACTION"
    assert case["strike_points_applied"] == 0
    content = world.get_content(scenario.content_id)
    assert content["review_status"] == "CLEAR"
    assert content["visibility_status"] == "LIVE"
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 0
    assert account["standing"] == "GOOD_STANDING"
