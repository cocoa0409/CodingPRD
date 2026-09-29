"""The overturned arm of an appeal: ledger restoration, credit refunds and cascades."""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_rate_equals,
    expected_strike_points,
)
from test_helpers.fixtures import (
    build_assigned_case,
    build_pending_case,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS


def _ledger_with_a_removal_and_a_warning(world):
    """Two decided cases on one account — a REMOVE worth 4 points and a WARN worth 2."""
    base = build_workforce_baseline(world)
    removal = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 1}
    )
    world.decide(removal.case_id, base.frontline_id, outcome="REMOVE")
    warning = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 1}
    )
    world.decide(warning.case_id, base.frontline_id, outcome="WARN")
    appeal = world.file_appeal(removal.case_id, base.account_id)
    world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    return base, removal, warning, appeal["id"]


def test_overturn_recomputes_the_strike_ledger_over_the_surviving_cases(api, world):
    """The ledger becomes the sum of what survives, not the old total minus a delta.

    PRD 3.7: "Third, also following from the overturn, the author is made whole:
    `lifetime_removed_count` falls by one when the reversed `decision_outcome`
    was `REMOVE`, `strike_points` is recomputed in full over the account's
    remaining decided non-overturned cases, and `appeal_credits_remaining` rises
    by one as a refund."

    Design: Difficulty/compensating_invariant/strike_point_ledger_restored_by_appeal_overturn
    """
    assert expected_strike_points("T2", "REMOVE", 0) == 4
    assert expected_strike_points("T2", "WARN", 1) == 2

    base, removal, warning, appeal_id = _ledger_with_a_removal_and_a_warning(world)
    assert world.get_case(removal.case_id)["strike_points_applied"] == 4
    assert world.get_case(warning.case_id)["strike_points_applied"] == 2
    before = world.get_account(base.account_id)
    assert_fields(
        before,
        {
            "strike_points": 6,
            "standing": "SUSPENDED",
            "lifetime_removed_count": 1,
            "appeal_credits_remaining": 2,
        },
        "account before the overturn",
    )

    world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Rhetorical, not a threat",
    )

    after = world.get_account(base.account_id)
    assert_fields(
        after,
        {
            "strike_points": 2,
            "standing": "GOOD_STANDING",
            "lifetime_removed_count": 0,
            "appeal_credits_remaining": 3,
        },
        "account after the overturn",
    )


def test_overturned_case_row_is_excluded_from_the_ledger_not_rewritten(api, world):
    """The reversed case keeps its stored points and simply stops counting.

    PRD 3.7: "First, `resolved_at` is stamped and the case's `is_overturned`
    becomes true, which permanently excludes that case from the strike ledger and
    from restated transparency volumes."

    Design: Difficulty/compensating_invariant/strike_point_ledger_restored_by_appeal_overturn
    """
    base, removal, warning, appeal_id = _ledger_with_a_removal_and_a_warning(world)

    resolved = world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Rhetorical, not a threat",
    )
    assert resolved["reinstated_content"] is True
    assert_instant_equals(resolved["resolved_at"], "2026-08-01T09:00:00Z", "resolved_at")

    overturned = world.get_case(removal.case_id)
    assert overturned["is_overturned"] is True
    assert overturned["strike_points_applied"] == 4
    assert overturned["decision_outcome"] == "REMOVE"
    surviving = world.get_case(warning.case_id)
    assert surviving["is_overturned"] is False
    assert surviving["strike_points_applied"] == 2

    reinstated = world.get_content(removal.content_id)
    assert reinstated["visibility_status"] == "REINSTATED"
    assert reinstated["review_status"] == "CLEAR"
    assert_instant_equals(reinstated["reinstated_at"], "2026-08-01T09:00:00Z", "reinstated_at")
    untouched = world.get_content(warning.content_id)
    assert untouched["visibility_status"] == "LIVE"
    assert untouched["review_status"] == "ACTIONED"
    assert untouched["reinstated_at"] is None

    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 0
    assert decider["accuracy_score_audit_only"] is None
    assert_rate_equals(decider["accuracy_score_blended"], 0.0, "accuracy_score_blended")
    assert decider["status"] == "ACTIVE"
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0


def _sibling_appeals_awaiting_resolution(world):
    """Two accounts with identical REMOVE histories, each holding one routed appeal."""
    base = build_workforce_baseline(world)
    sigma = world.create_account(external_handle="acct_sigma")

    rho_case = build_pending_case(base, content_overrides={"graphic_weight": 1})
    world.assign(rho_case.case_id, target_reviewer_id=base.frontline_id)
    world.decide(rho_case.case_id, base.frontline_id, outcome="REMOVE")

    sigma_case = build_pending_case(
        base, content_overrides={"graphic_weight": 1}, account_id=sigma["id"]
    )
    world.assign(sigma_case.case_id, target_reviewer_id=base.frontline_id)
    world.decide(sigma_case.case_id, base.frontline_id, outcome="REMOVE")

    rho_appeal = world.file_appeal(rho_case.case_id, base.account_id)
    sigma_appeal = world.file_appeal(sigma_case.case_id, sigma["id"])
    world.route_appeal(rho_appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    world.route_appeal(sigma_appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    return base, sigma, rho_case, sigma_case, rho_appeal["id"], sigma_appeal["id"]


def test_appeal_credit_is_refunded_only_on_the_overturned_arm(api, world):
    """Two identical histories diverge on credits because only one appeal won.

    PRD 3.7: "The content item returns to `review_status` `ACTIONED` with
    `visibility_status` unchanged, and the account's `appeal_credits_remaining`
    is **not** refunded — a losing appeal costs a credit."

    Design: Difficulty/compensating_invariant/appeal_credit_refunded_only_on_overturn
    """
    (
        base,
        sigma,
        rho_case,
        sigma_case,
        rho_appeal_id,
        sigma_appeal_id,
    ) = _sibling_appeals_awaiting_resolution(world)
    assert world.get_account(base.account_id)["appeal_credits_remaining"] == 2
    assert world.get_account(sigma["id"])["appeal_credits_remaining"] == 2

    upheld = world.resolve_appeal(
        rho_appeal_id,
        base.senior_id,
        resolution="UPHELD",
        resolution_note="Threat was explicit",
    )
    overturned = world.resolve_appeal(
        sigma_appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Newsworthy quotation",
    )
    assert upheld["reinstated_content"] is False
    assert overturned["reinstated_content"] is True

    loser = world.get_account(base.account_id)
    assert_fields(
        loser,
        {
            "appeal_credits_remaining": 2,
            "strike_points": 4,
            "standing": "LIMITED",
            "lifetime_removed_count": 1,
        },
        "account whose appeal was upheld",
    )
    loser_item = world.get_content(rho_case.content_id)
    assert loser_item["visibility_status"] == "REMOVED"
    assert loser_item["review_status"] == "ACTIONED"
    assert loser_item["reinstated_at"] is None

    winner = world.get_account(sigma["id"])
    assert_fields(
        winner,
        {
            "appeal_credits_remaining": 3,
            "strike_points": 0,
            "standing": "GOOD_STANDING",
            "lifetime_removed_count": 0,
        },
        "account whose appeal was overturned",
    )
    winner_item = world.get_content(sigma_case.content_id)
    assert winner_item["visibility_status"] == "REINSTATED"
    assert winner_item["review_status"] == "CLEAR"
    assert_instant_equals(
        winner_item["reinstated_at"], "2026-08-01T09:00:00Z", "reinstated_at"
    )

    granted = 3 + 3
    remaining = loser["appeal_credits_remaining"] + winner["appeal_credits_remaining"]
    assert granted - remaining == 1, "exactly one credit is permanently consumed"

    rows, meta = validate_paginated(api.list_appeals(headers=ADMIN_HEADERS, status="UPHELD"))
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [rho_appeal_id]


def test_second_terminal_appeal_takes_the_decider_through_the_accuracy_gate(api, world):
    """One upheld and one overturned appeal make a blended score that suspends.

    PRD 3.7: "Fifth, again following from the overturn, the original decider's
    `appealed_count` rises by one while `upheld_appeal_count` is left unchanged,
    both accuracy variants are recomputed, and the accuracy gate may transition
    that reviewer `ACTIVE → PENDING_RETRAINING` or `ACTIVE → SUSPENDED`."

    Design: Difficulty/compensating_invariant/appeal_credit_refunded_only_on_overturn
    """
    (
        base,
        sigma,
        rho_case,
        sigma_case,
        rho_appeal_id,
        sigma_appeal_id,
    ) = _sibling_appeals_awaiting_resolution(world)

    world.resolve_appeal(
        rho_appeal_id,
        base.senior_id,
        resolution="UPHELD",
        resolution_note="Threat was explicit",
    )
    after_one = world.get_reviewer(base.frontline_id)
    assert after_one["appealed_count"] == 1
    assert after_one["upheld_appeal_count"] == 1
    assert_rate_equals(after_one["accuracy_score_blended"], 1.0, "blended after one appeal")
    assert after_one["status"] == "ACTIVE"

    world.resolve_appeal(
        sigma_appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Newsworthy quotation",
    )
    decider = world.get_reviewer(base.frontline_id)
    assert decider["appealed_count"] == 2
    assert decider["upheld_appeal_count"] == 1
    assert decider["accuracy_score_audit_only"] is None
    assert_rate_equals(decider["accuracy_score_blended"], 0.5, "accuracy_score_blended")
    assert decider["status"] == "SUSPENDED"
    assert decider["open_case_count"] == 0
    assert decider["exposure_points_today"] == 0

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0
    assert world.get_case(rho_case.case_id)["status"] == "DECIDED"
    assert world.get_case(sigma_case.case_id)["status"] == "DECIDED"


def _audited_decision_with_a_second_case_in_hand(world):
    """A decided and audited case under appeal, while the decider still holds another."""
    base = build_workforce_baseline(world)
    first = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 2}
    )
    world.decide(first.case_id, base.frontline_id, outcome="REMOVE")
    sample = world.draw_sample(first.case_id, base.auditor_id)
    world.audit(sample["id"], base.auditor_id, verdict="AGREE")
    second = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 3}
    )
    appeal = world.file_appeal(first.case_id, base.account_id)
    world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    return base, first, second, appeal["id"]


def test_overturn_chains_through_the_blended_score_into_a_suspension(api, world):
    """One agreeing audit plus one overturned appeal halve the blended score and suspend.

    PRD 3.8: "Given that, a gate score strictly below 0.6000 transitions the
    reviewer `ACTIVE → SUSPENDED`, and a gate score at or above 0.6000 but
    strictly below 0.8500 transitions them `ACTIVE → PENDING_RETRAINING`."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_to_reviewer_suspension_and_queue_return
    """
    base, first, second, appeal_id = _audited_decision_with_a_second_case_in_hand(world)
    before = world.get_reviewer(base.frontline_id)
    assert before["audited_count"] == 1
    assert before["agree_count"] == 1
    assert_rate_equals(before["accuracy_score_audit_only"], 1.0, "audit-only before")
    assert before["status"] == "ACTIVE"

    world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Educational context",
    )

    assert world.get_case(first.case_id)["is_overturned"] is True
    restored = world.get_content(first.content_id)
    assert restored["visibility_status"] == "REINSTATED"
    assert restored["review_status"] == "CLEAR"
    assert_instant_equals(restored["reinstated_at"], "2026-08-01T09:00:00Z", "reinstated_at")
    assert_fields(
        world.get_account(base.account_id),
        {
            "strike_points": 0,
            "standing": "GOOD_STANDING",
            "lifetime_removed_count": 0,
            "appeal_credits_remaining": 3,
        },
        "account after the overturn",
    )

    decider = world.get_reviewer(base.frontline_id)
    assert_rate_equals(decider["accuracy_score_audit_only"], 1.0, "accuracy_score_audit_only")
    assert_rate_equals(decider["accuracy_score_blended"], 0.5, "accuracy_score_blended")
    assert decider["audited_count"] == 1
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 0
    assert decider["status"] == "SUSPENDED"


def test_suspension_returns_the_other_held_case_to_its_queue(api, world):
    """The suspension releases work the appealed case never touched.

    PRD 3.7: "Sixth, following from whichever demotion the gate chose: on the
    `PENDING_RETRAINING` arm every case still held by that reviewer in `ASSIGNED`
    has `requires_recertified_review` set to true and stays assigned to them; on
    the `SUSPENDED` arm those cases instead transition `ASSIGNED →
    PENDING_ASSIGNMENT` with `assigned_reviewer_id` cleared, the reviewer's
    `open_case_count` and `exposure_points_today` are both set to 0, and each
    affected queue's `unassigned_case_count` rises by one per returned case."

    Design: Difficulty/transitive_cascade/appeal_overturn_cascade_to_reviewer_suspension_and_queue_return
    """
    base, first, second, appeal_id = _audited_decision_with_a_second_case_in_hand(world)
    held = world.get_case(second.case_id)
    assert held["status"] == "ASSIGNED"
    assert held["assigned_reviewer_id"] == base.frontline_id
    assert_instant_equals(held["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at while held")
    holder = world.get_reviewer(base.frontline_id)
    assert holder["open_case_count"] == 1
    assert holder["exposure_points_today"] == 5

    world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Educational context",
    )

    returned = world.get_case(second.case_id)
    assert returned["status"] == "PENDING_ASSIGNMENT"
    assert returned["assigned_reviewer_id"] is None
    assert returned["requires_recertified_review"] is False
    assert_instant_equals(
        returned["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at after the return"
    )

    suspended = world.get_reviewer(base.frontline_id)
    assert suspended["status"] == "SUSPENDED"
    assert suspended["open_case_count"] == 0
    assert suspended["exposure_points_today"] == 0

    queue = world.get_queue(base.queue_id)
    assert queue["unassigned_case_count"] == 1
    assert queue["open_case_count"] == 1
    assert world.get_case(first.case_id)["status"] == "DECIDED"
