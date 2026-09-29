"""Policy activation cascades, pinned-version reads and the recertification gate."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields, assert_instant_equals, assert_rate_equals
from test_helpers.factories import decide_case_payload, return_case_payload
from test_helpers.fixtures import build_assigned_case, build_workforce_baseline
from test_helpers.test_users import (
    POLICY_MANAGER_ACTIVATOR_ID,
    make_qa_auditor_headers,
    make_reviewer_headers,
)

TEXT_WEIGHT_TWO = {"media_kind": "TEXT", "graphic_weight": 2}


def _activate_successor(base, **version_overrides):
    """Draft, back-test and activate a second version beneath the same category."""
    world = base.world
    successor = world.create_draft_version(base.category_id, **version_overrides)
    world.back_test(successor["id"])
    return world.activate(successor["id"])


def test_policy_activation_cascade_supersedes_decertifies_and_flags_the_case(api, world):
    """One activation propagates through supersession, certifications and open cases.

    PRD 3.2: "Second — and only when the newly activated version's
    `requires_recertification` is true — every reviewer whose
    `certified_policy_version_ids` contains the superseded version's id drops that
    entry and gains the **newly activated** version's id in
    `pending_retraining_version_ids`; no reviewer's `status` is touched by an
    activation."

    Design: Difficulty/transitive_cascade/policy_activation_cascade_supersede_decert_and_case_recert_flag
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )

    activated = _activate_successor(
        base, version_label="v2", auto_action_threshold=0.7, review_floor=0.5
    )
    assert activated["backtest_sample_size"] == 0
    assert_rate_equals(activated["backtest_divergence_rate"], 0.0, "backtest_divergence_rate")
    assert_fields(
        activated,
        {
            "status": "ACTIVE",
            "supersedes_version_id": base.version_id,
            "activated_by_user_id": POLICY_MANAGER_ACTIVATOR_ID,
        },
        "activated successor",
    )
    assert_instant_equals(activated["activated_at"], "2026-08-01T09:00:00Z", "activated_at")

    assert world.get_policy_version(base.version_id)["status"] == "SUPERSEDED"
    category = world.get_category(base.category_id)
    assert category["status"] == "ACTIVE"
    assert category["active_version_id"] == activated["id"]

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["certified_policy_version_ids"] == []
    assert reviewer["pending_retraining_version_ids"] == [activated["id"]]
    assert reviewer["status"] == "ACTIVE"

    case = world.get_case(scenario.case_id)
    assert case["requires_recertified_review"] is True
    assert case["policy_version_id"] == base.version_id
    assert case["status"] == "ASSIGNED"


def test_activation_cascade_stops_at_the_steps_written_down(api, world):
    """The cascade decertifies and flags but never chains further than declared.

    PRD 2.7: "Cascades never chain further than the steps written down — an
    activation, for example, decertifies reviewers and flags cases but does not
    itself move any reviewer's `status`, and only the accuracy gate described in
    §3.8 and the two wellness operations described in §3.6 ever move a reviewer's
    `status`."

    Design: Difficulty/transitive_cascade/policy_activation_cascade_supersede_decert_and_case_recert_flag
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    activated = _activate_successor(
        base, version_label="v2", auto_action_threshold=0.7, review_floor=0.5
    )

    holder = world.get_reviewer(base.frontline_id)
    assert holder["status"] == "ACTIVE"
    assert holder["open_case_count"] == 1
    assert holder["exposure_points_today"] == 2

    case = world.get_case(scenario.case_id)
    assert case["assigned_reviewer_id"] == base.frontline_id
    assert case["policy_version_id"] == base.version_id
    assert_instant_equals(case["sla_due_at"], "2026-08-01T11:00:00Z", "pinned sla_due_at")

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 0
    assert account["standing"] == "GOOD_STANDING"

    for idle_id in (base.senior_id, base.auditor_id):
        idle = world.get_reviewer(idle_id)
        assert idle["certified_policy_version_ids"] == [], idle_id
        assert idle["pending_retraining_version_ids"] == [activated["id"]], idle_id
        assert idle["status"] == "ACTIVE", idle_id


def test_decide_blocked_when_reviewer_certification_voided_by_activation(api, world):
    """A third entity's activation makes the holder's own decision inadmissible.

    PRD 3.4: "Once the flag is true — because the pinned version was superseded by
    an activation that required recertification, or because the holding reviewer
    was demoted to `PENDING_RETRAINING` — the reviewer must instead hold the
    category's **current** `active_version_id`."

    Design: Difficulty/cross_entity_state_dependency/decide_blocked_when_reviewer_certification_voided_by_activation
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    _activate_successor(base, version_label="v2", auto_action_threshold=0.7, review_floor=0.5)
    assert world.get_case(scenario.case_id)["requires_recertified_review"] is True

    validate_error(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        ),
        ApiErrorId.REVIEWER_NOT_CERTIFIED.value,
    )
    blocked = world.get_case(scenario.case_id)
    assert blocked["status"] == "ASSIGNED"
    assert blocked["decision_outcome"] is None
    assert world.get_account(base.account_id)["strike_points"] == 0
    assert world.get_content(scenario.content_id)["visibility_status"] == "LIVE"


def test_decide_succeeds_after_recertification_and_scores_the_pinned_version(api, world):
    """Recertifying on the new version unblocks a decision still scored against the old.

    PRD 2.7: "The confidence thresholds that routed it, the base review allowance
    in minutes that produced its deadline, and the appeal window that produced its
    `appeal_deadline_at` are all read from that pinned row."

    Design: Difficulty/cross_entity_state_dependency/decide_blocked_when_reviewer_certification_voided_by_activation
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    activated = _activate_successor(
        base, version_label="v2", auto_action_threshold=0.7, review_floor=0.5
    )

    recertified = world.certify(base.frontline_id, activated["id"])
    assert recertified["certified_policy_version_ids"] == [activated["id"]]
    assert recertified["pending_retraining_version_ids"] == []

    decided = validate_success(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert_fields(
        decided,
        {
            "status": "DECIDED",
            "decision_source": "HUMAN",
            "decided_by_reviewer_id": base.frontline_id,
            "policy_version_id": base.version_id,
            "strike_points_applied": 4,
        },
        "decided case",
    )
    assert_instant_equals(
        decided["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at"
    )
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["standing"] == "LIMITED"
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0


def test_pinned_policy_version_governs_decide_after_a_non_recert_activation(api, world):
    """A non-recertifying activation touches nothing the pinned decision depends on.

    PRD 3.2: "When `requires_recertification` is false, neither certifications nor
    case flags are touched at all."

    Design: Corner/cross_cutting_complexity_layers/pinned_policy_version_governs_decide_after_a_non_recert_activation
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    activated = _activate_successor(
        base,
        version_label="v2",
        appeal_window_hours=24,
        review_sla_minutes=60,
        requires_recertification=False,
    )
    assert activated["backtest_sample_size"] == 0
    assert_rate_equals(activated["backtest_divergence_rate"], 0.0, "backtest_divergence_rate")
    assert world.get_policy_version(base.version_id)["status"] == "SUPERSEDED"
    assert world.get_category(base.category_id)["active_version_id"] == activated["id"]

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["certified_policy_version_ids"] == [base.version_id]
    assert reviewer["pending_retraining_version_ids"] == []
    assert reviewer["status"] == "ACTIVE"
    assert world.get_case(scenario.case_id)["requires_recertified_review"] is False

    decided = validate_success(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert decided["policy_version_id"] == base.version_id
    assert decided["strike_points_applied"] == 4
    assert decided["sla_breached"] is False
    assert_instant_equals(
        decided["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at from v1"
    )
    assert_instant_equals(decided["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at from v1")
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["standing"] == "LIMITED"


def test_sla_recompute_uses_pinned_version_minutes_not_current_active(api, world):
    """The return-to-queue recompute reads the pinned allowance, not the live one.

    PRD 3.5: "The queue's `unassigned_case_count` rises by one and its
    `open_case_count` is untouched, and `sla_due_at` is recomputed by the
    congestion-and-severity procedure of §3.3 against the queue's post-return
    `open_case_count`."

    Design: Corner/calculations/sla_recompute_uses_pinned_version_minutes_not_current_active
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )
    assert_instant_equals(scenario.case["sla_due_at"], "2026-08-01T11:00:00Z", "queue sla_due_at")
    world.set_clock("2026-08-01T09:20:00Z")
    escalated = world.escalate(
        scenario.case_id, base.frontline_id, escalation_reason="CALIBRATION"
    )
    assert_instant_equals(escalated["sla_due_at"], "2026-08-01T09:50:00Z", "escalation sla_due_at")

    world.set_clock("2026-08-01T09:30:00Z")
    activated = _activate_successor(
        base, version_label="v2", review_sla_minutes=60, requires_recertification=False
    )
    world.set_clock("2026-08-01T10:00:00Z")

    returned = validate_success(
        api.return_case_to_queue(
            scenario.case_id,
            return_case_payload(reason="de-escalated after calibration"),
            headers=make_qa_auditor_headers(base.auditor_id),
        )
    )
    assert_fields(
        returned,
        {
            "status": "PENDING_ASSIGNMENT",
            "escalation_tier": 1,
            "escalation_reason": "CALIBRATION",
            "policy_version_id": base.version_id,
            "requires_recertified_review": False,
        },
        "returned case",
    )
    assert_instant_equals(returned["sla_due_at"], "2026-08-01T12:00:00Z", "recomputed sla_due_at")
    assert world.get_category(base.category_id)["active_version_id"] == activated["id"]

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["certified_policy_version_ids"] == [base.version_id]
    assert reviewer["status"] == "ACTIVE"
