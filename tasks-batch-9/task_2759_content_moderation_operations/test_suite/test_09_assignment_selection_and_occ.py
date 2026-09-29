"""Server-chosen assignment, reassignment authority and the case version guard."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import assign_case_payload
from test_helpers.fixtures import (
    build_assigned_case,
    build_decided_case,
    build_pending_case,
    build_workforce_baseline,
)
from test_helpers.assertions import assert_fields
from test_helpers.test_users import (
    ADMIN_HEADERS,
    POLICY_AUTHOR_HEADERS,
    headers_without_role,
    make_qa_auditor_headers,
    make_reviewer_headers,
)

TEXT_WEIGHT_TWO = {"media_kind": "TEXT", "graphic_weight": 2}


def test_reviewer_selection_waterfall_honours_exclusions_then_ranking(api, world):
    """An exclusion removes the tie-break winner; the next case goes back to her.

    PRD 3.4: "And the reviewer must be neither a member of `exclude_reviewer_ids`
    nor the case's current `assigned_reviewer_id`, which is what makes a
    reassignment always move the case to somebody new."

    Design: Corner/calculations/reviewer_selection_waterfall_honours_exclusions_then_ranking
    """
    base = build_workforce_baseline(world)
    first = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    second = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)

    excluded = validate_success(
        api.assign_case(
            first.case_id,
            assign_case_payload(first.case["version"], exclude_reviewer_ids=[base.frontline_id]),
            headers=ADMIN_HEADERS,
        )
    )
    assert excluded["assigned_reviewer_id"] == base.senior_id
    assert excluded["version"] == 2
    assert excluded["reassignment_count"] == 0

    open_choice = validate_success(
        api.assign_case(
            second.case_id,
            assign_case_payload(second.case["version"]),
            headers=make_qa_auditor_headers(base.auditor_id),
        )
    )
    assert open_choice["assigned_reviewer_id"] == base.frontline_id
    assert open_choice["version"] == 2
    assert open_choice["reassignment_count"] == 0

    for reviewer_id in (base.frontline_id, base.senior_id):
        reviewer = world.get_reviewer(reviewer_id)
        assert reviewer["open_case_count"] == 1, reviewer_id
        assert reviewer["exposure_points_today"] == 2, reviewer_id

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 2
    assert queue["unassigned_case_count"] == 0


def test_auto_assignment_tie_broken_by_created_at_then_ranked_by_open_case_count(api, world):
    """A dead-heat resolves by creation order, and the next case follows the workload.

    PRD 3.4: "Surviving candidates are ranked by `open_case_count` ascending, then
    by `accuracy_score_blended` descending with a null score treated as `1.0000`
    so that an unmeasured reviewer ranks with the best, and ties are broken by
    `created_at` ascending; the reviewer's `id` is never a tie-breaker."

    Design: Corner/cross_cutting_complexity_layers/auto_assignment_tie_broken_by_created_at_then_ranked_by_open_case_count
    """
    base = build_workforce_baseline(world)
    first = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    second = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    for reviewer_id in (base.frontline_id, base.senior_id):
        reviewer = world.get_reviewer(reviewer_id)
        assert reviewer["open_case_count"] == 0
        assert reviewer["accuracy_score_blended"] is None

    tie = validate_success(
        api.assign_case(
            first.case_id, assign_case_payload(first.case["version"]), headers=ADMIN_HEADERS
        )
    )
    assert tie["assigned_reviewer_id"] == base.frontline_id

    ranked = validate_success(
        api.assign_case(
            second.case_id, assign_case_payload(second.case["version"]), headers=ADMIN_HEADERS
        )
    )
    assert ranked["assigned_reviewer_id"] == base.senior_id

    assert world.get_reviewer(base.frontline_id)["exposure_points_today"] == 2
    assert world.get_reviewer(base.senior_id)["exposure_points_today"] == 2
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 2
    assert queue["unassigned_case_count"] == 0


def test_stale_expected_case_version_on_reassign_rejected(api, world):
    """A reassignment that is otherwise perfect still fails on a spent version.

    PRD 2.9: "Case assignment requires `expected_case_version`, carrying the
    client's last observed `version` of the target `ModerationCase`. If that
    number does not equal the case's current `version`, the assignment is
    rejected with `ERR_STALE_CASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_case_version_on_reassign_rejected
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    spent_version = scenario.case["version"]
    world.assign(scenario.case_id, target_reviewer_id=base.frontline_id, expected_case_version=spent_version)

    validate_error(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(spent_version, target_reviewer_id=base.senior_id),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.STALE_CASE_VERSION.value,
    )
    unchanged = world.get_case(scenario.case_id)
    assert_fields(
        unchanged,
        {
            "assigned_reviewer_id": base.frontline_id,
            "reassignment_count": 0,
            "version": spent_version + 1,
        },
        "case after refusal",
    )
    senior = world.get_reviewer(base.senior_id)
    assert senior["open_case_count"] == 0
    assert senior["exposure_points_today"] == 0
    frontline = world.get_reviewer(base.frontline_id)
    assert frontline["open_case_count"] == 1
    assert frontline["exposure_points_today"] == 2

    retried = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(unchanged["version"], target_reviewer_id=base.senior_id),
            headers=ADMIN_HEADERS,
        )
    )
    assert retried["assigned_reviewer_id"] == base.senior_id


def test_assign_by_reviewer_on_missing_case_is_unauthorized_before_not_found(api, world):
    """The role gate answers first, so an outsider learns nothing about which ids exist.

    PRD 2.8: "A request can fail for several reasons at once, and the reported
    `error_id` is not arbitrary — it is the first failure in the fixed evaluation
    order below."

    Design: Corner/validations/assign_by_reviewer_on_missing_case_is_unauthorized_before_not_found
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    payload = assign_case_payload(
        scenario.case["version"], target_reviewer_id=base.frontline_id
    )

    refused = api.assign_case(
        NON_EXISTENT_UUID, payload, headers=make_reviewer_headers(base.frontline_id)
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)

    unauthenticated = api.assign_case(NON_EXISTENT_UUID, payload, headers=headers_without_role())
    assert unauthenticated.status_code == 401
    validate_error(unauthenticated, ApiErrorId.UNAUTHENTICATED.value)

    validate_error(
        api.assign_case(NON_EXISTENT_UUID, payload, headers=ADMIN_HEADERS),
        ApiErrorId.CASE_NOT_FOUND.value,
    )
    still_pending = world.get_case(scenario.case_id)
    assert still_pending["status"] == "PENDING_ASSIGNMENT"
    assert still_pending["version"] == 1


def test_policy_manager_cannot_assign_a_case(api, world):
    """The policy manager's write surface stops at the taxonomy.

    PRD 2.8: "**Authorization.** The acting role is permitted on the requested
    operation, else `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/policy_manager_cannot_assign_a_case
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)

    refused = api.assign_case(
        scenario.case_id,
        assign_case_payload(scenario.case["version"], target_reviewer_id=base.frontline_id),
        headers=POLICY_AUTHOR_HEADERS,
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)

    unchanged = world.get_case(scenario.case_id)
    assert_fields(
        unchanged,
        {"status": "PENDING_ASSIGNMENT", "assigned_reviewer_id": None, "version": 1},
        "case after refusal",
    )
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 0


def test_qa_auditor_and_trust_safety_admin_share_case_reassignment(api, world):
    """Both authorised roles drive the same reassignment machinery.

    PRD 3.4: "On a reassignment the outgoing reviewer's `open_case_count` falls by
    one and their `exposure_points_today` is reduced by exactly the case's
    `exposure_points_charged`, the incoming reviewer's counters rise by the same
    amounts, and the case's `reassignment_count` — which counts assignments after
    the first — rises by one."

    Design: Corner/rbac/qa_auditor_and_trust_safety_admin_share_case_reassignment
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    assigned_version = scenario.case["version"]
    assert assigned_version == 2

    reassigned = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(assigned_version, target_reviewer_id=base.senior_id),
            headers=make_qa_auditor_headers(base.auditor_id),
        )
    )
    assert_fields(
        reassigned,
        {
            "status": "ASSIGNED",
            "assigned_reviewer_id": base.senior_id,
            "reassignment_count": 1,
            "version": assigned_version + 1,
        },
        "reassigned case",
    )
    outgoing = world.get_reviewer(base.frontline_id)
    assert outgoing["open_case_count"] == 0
    assert outgoing["exposure_points_today"] == 0
    incoming = world.get_reviewer(base.senior_id)
    assert incoming["open_case_count"] == 1
    assert incoming["exposure_points_today"] == 2

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0


def test_decided_case_state_beats_uncertified_target_on_one_assign(api, world):
    """State and safety fail together on one request and the lifecycle error wins.

    PRD 2.8: "**Lifecycle state**, evaluated in this inner order:
    `ERR_CASE_ALREADY_DECIDED`; `ERR_CASE_NOT_ASSIGNED`;
    `ERR_INVALID_CASE_TRANSITION`; `ERR_POLICY_VERSION_NOT_DRAFT`;
    `ERR_POLICY_VERSION_NOT_BACKTESTED`; `ERR_CASE_NOT_DECIDED`;
    `ERR_APPEAL_NOT_UNDER_REVIEW`; `ERR_AUDIT_NOT_AUDITABLE` and
    `ERR_AUDIT_NOT_DISPUTABLE`; `ERR_REPORT_NOT_COMPUTED`;
    `ERR_REPORT_ALREADY_PUBLISHED`; `ERR_REVIEWER_NOT_ACTIVE` and
    `ERR_REVIEWER_NOT_ON_BREAK`; `ERR_CONTENT_NOT_LIVE`;
    `ERR_NO_ACTIVE_POLICY_VERSION`; `ERR_ACCOUNT_BANNED`;
    `ERR_POLICY_VERSION_NOT_CERTIFIABLE`."

    Design: Difficulty/priority_pair_validation_conflict/decided_case_state_beats_uncertified_reviewer_safety
    """
    base = build_workforce_baseline(world)
    scenario = build_decided_case(
        base, reviewer_id=base.frontline_id, outcome="REMOVE", content_overrides=TEXT_WEIGHT_TWO
    )
    decided = world.get_case(scenario.case_id)
    assert decided["status"] == "DECIDED"
    uncertified = world.create_reviewer(
        display_name="Nora Newcomer",
        role_class="FRONTLINE",
        languages=[base.queue["language"]],
        specialties=[base.queue["specialty"]],
    )
    assert uncertified["certified_policy_version_ids"] == []
    assert uncertified["status"] == "ACTIVE"

    validate_error(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(decided["version"], target_reviewer_id=uncertified["id"]),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.CASE_ALREADY_DECIDED.value,
    )
    unchanged = world.get_case(scenario.case_id)
    assert unchanged["status"] == "DECIDED"
    assert unchanged["assigned_reviewer_id"] == base.frontline_id
    assert unchanged["version"] == decided["version"]
    assert world.get_reviewer(uncertified["id"])["open_case_count"] == 0


def test_case_already_decided_and_not_certified_are_both_live_rules(api, world):
    """Each rule fires on its own, so the paired request really did violate both.

    PRD 3.4: "Either way, a reviewer without the required certification is
    rejected with `ERR_REVIEWER_NOT_CERTIFIED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/decided_case_state_beats_uncertified_reviewer_safety
    """
    base = build_workforce_baseline(world)
    uncertified = world.create_reviewer(
        display_name="Nora Newcomer",
        role_class="FRONTLINE",
        languages=[base.queue["language"]],
        specialties=[base.queue["specialty"]],
    )

    pending = build_pending_case(base, content_overrides=TEXT_WEIGHT_TWO)
    validate_error(
        api.assign_case(
            pending.case_id,
            assign_case_payload(pending.case["version"], target_reviewer_id=uncertified["id"]),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.REVIEWER_NOT_CERTIFIED.value,
    )
    assert world.get_case(pending.case_id)["status"] == "PENDING_ASSIGNMENT"

    decided_scenario = build_decided_case(
        base, reviewer_id=base.frontline_id, outcome="REMOVE", content_overrides=TEXT_WEIGHT_TWO
    )
    decided = world.get_case(decided_scenario.case_id)
    validate_error(
        api.assign_case(
            decided_scenario.case_id,
            assign_case_payload(decided["version"], target_reviewer_id=base.senior_id),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.CASE_ALREADY_DECIDED.value,
    )
    assert world.get_reviewer(base.senior_id)["open_case_count"] == 0
    assert world.get_case(decided_scenario.case_id)["status"] == "DECIDED"
