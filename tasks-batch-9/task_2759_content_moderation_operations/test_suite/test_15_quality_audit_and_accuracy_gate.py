"""Quality sampling, the calibration loop and the two-variant accuracy gate."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_fields, assert_rate_equals
from test_helpers.factories import (
    audit_dispute_payload,
    audit_verdict_payload,
    create_audit_sample_payload,
    decide_case_payload,
)
from test_helpers.fixtures import build_assigned_case, build_workforce_baseline
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_qa_auditor_headers,
    make_reviewer_headers,
)


def _decided_cases(base, count, outcome="NO_ACTION", graphic_weight=2):
    """Have the frontline reviewer decide `count` fresh cases the same way."""
    scenarios = []
    for _ in range(count):
        scenario = build_assigned_case(
            base,
            reviewer_id=base.frontline_id,
            content_overrides={"graphic_weight": graphic_weight},
        )
        base.world.decide(scenario.case_id, base.frontline_id, outcome=outcome)
        scenarios.append(scenario)
    return scenarios


def test_dispute_of_unaudited_sample_rejected(api, world):
    """A sample with no verdict yet has nothing to contest.

    PRD 3.8: "A reviewer who believes an audit verdict is wrong may dispute it,
    moving the sample `AUDITED → DISPUTED`; a sample in any other status yields
    `ERR_AUDIT_NOT_DISPUTABLE` (HTTP 409), and only the reviewer who decided the
    underlying case may dispute — `X-User-ID` must equal that case's
    `decided_by_reviewer_id`, else `ERR_NOT_CASE_OWNER`."

    Design: Corner/errors/dispute_of_unaudited_sample_rejected
    """
    base = build_workforce_baseline(world)
    decided = _decided_cases(base, 1)[0]
    sample = world.draw_sample(decided.case_id, base.auditor_id)
    assert sample["status"] == "SAMPLED"

    refused = api.dispute_audit_sample(
        sample["id"],
        audit_dispute_payload(dispute_note="Too early to argue"),
        headers=make_reviewer_headers(base.frontline_id),
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.AUDIT_NOT_DISPUTABLE.value)

    unchanged = world.get_sample(sample["id"])
    assert_fields(
        unchanged,
        {
            "status": "SAMPLED",
            "verdict": None,
            "disputed_at": None,
            "counts_toward_accuracy": True,
        },
        "sample after the refused dispute",
    )
    decider = world.get_reviewer(base.frontline_id)
    assert decider["audited_count"] == 0
    assert decider["accuracy_score_audit_only"] is None

    world.audit(sample["id"], base.auditor_id, verdict="AGREE")
    accepted = validate_success(
        api.dispute_audit_sample(
            sample["id"],
            audit_dispute_payload(dispute_note="Now there is a verdict"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert accepted["status"] == "DISPUTED"
    assert accepted["counts_toward_accuracy"] is False


def test_audit_of_already_audited_sample_rejected(api, world):
    """One decision cannot absorb two verdicts without a dispute in between.

    PRD 3.8: "Any other status is rejected with `ERR_AUDIT_NOT_AUDITABLE` (HTTP
    409)."

    Design: Corner/errors/audit_of_already_audited_sample_rejected
    """
    base = build_workforce_baseline(world)
    decided = _decided_cases(base, 1)[0]
    sample = world.draw_sample(decided.case_id, base.auditor_id)
    world.audit(sample["id"], base.auditor_id, verdict="AGREE")

    refused = api.record_audit_verdict(
        sample["id"],
        audit_verdict_payload(verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"),
        headers=make_qa_auditor_headers(base.auditor_id),
    )
    assert refused.status_code == 409
    validate_error(refused, ApiErrorId.AUDIT_NOT_AUDITABLE.value)

    unchanged = world.get_sample(sample["id"])
    assert unchanged["verdict"] == "AGREE"
    assert unchanged["status"] == "AUDITED"
    assert unchanged["counts_toward_accuracy"] is True
    decider = world.get_reviewer(base.frontline_id)
    assert decider["audited_count"] == 1
    assert decider["agree_count"] == 1
    assert_rate_equals(decider["accuracy_score_audit_only"], 1.0, "accuracy_score_audit_only")
    assert decider["status"] == "ACTIVE"

    world.dispute(sample["id"], base.frontline_id, dispute_note="The call was mine to make")
    recalibrated = world.audit(
        sample["id"], base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"
    )
    assert recalibrated["status"] == "AUDITED"
    assert recalibrated["verdict"] == "DISAGREE_MATERIAL"


def test_qa_reviewer_cannot_sample_their_own_decision(api, world):
    """The QA role gate passes and the same-user gate still refuses the sampling.

    PRD 3.8: "The case must be `DECIDED` (`ERR_CASE_NOT_DECIDED`), the acting
    reviewer's `role_class` must be `QA` (`ERR_UNAUTHORIZED`), and `X-User-ID`
    must differ from the case's `decided_by_reviewer_id` — nobody audits their own
    decision, and an attempt is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/qa_reviewer_cannot_sample_their_own_decision
    """
    base = build_workforce_baseline(world)
    own = build_assigned_case(
        base, reviewer_id=base.auditor_id, content_overrides={"graphic_weight": 2}
    )
    world.decide(own.case_id, base.auditor_id, outcome="NO_ACTION")
    assert world.get_case(own.case_id)["decided_by_reviewer_id"] == base.auditor_id

    refused = api.create_audit_sample(
        create_audit_sample_payload(own.case_id, sampling_reason="RANDOM"),
        headers=make_qa_auditor_headers(base.auditor_id),
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value)
    assert refused.json()["data"]["error_id"] != ApiErrorId.UNAUTHORIZED.value

    rows, meta = validate_paginated(
        api.list_audit_samples(headers=ADMIN_HEADERS, case_id=own.case_id)
    )
    assert meta["total_count"] == 0
    assert rows == []
    auditor = world.get_reviewer(base.auditor_id)
    assert auditor["audited_count"] == 0
    assert auditor["accuracy_score_audit_only"] is None

    other = _decided_cases(base, 1)[0]
    accepted = validate_success(
        api.create_audit_sample(
            create_audit_sample_payload(other.case_id, sampling_reason="RANDOM"),
            headers=make_qa_auditor_headers(base.auditor_id),
        ),
        201,
    )
    assert accepted["auditor_reviewer_id"] == base.auditor_id
    assert accepted["status"] == "SAMPLED"


def test_audit_sample_dispute_then_reaudit_closes_calibration_loop(api, world):
    """One sample row walks SAMPLED to AUDITED to DISPUTED and back to AUDITED.

    PRD 3.8: "Recording a verdict moves the sample `SAMPLED → AUDITED`, and the
    same operation also closes the calibration loop by moving a contested sample
    `DISPUTED → AUDITED`, overwriting the earlier verdict with the calibrated
    one."

    Design: Corner/state_machines/audit_sample_dispute_then_reaudit_closes_calibration_loop
    """
    base = build_workforce_baseline(world)
    removal = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 2}
    )
    world.decide(removal.case_id, base.frontline_id, outcome="REMOVE")
    sample = world.draw_sample(removal.case_id, base.auditor_id)
    sample_id = sample["id"]

    audited = world.audit(
        sample_id, base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="NO_ACTION"
    )
    assert_fields(
        audited,
        {
            "id": sample_id,
            "status": "AUDITED",
            "verdict": "DISAGREE_MATERIAL",
            "correct_outcome": "NO_ACTION",
            "counts_toward_accuracy": True,
        },
        "sample after the first verdict",
    )
    after_verdict = world.get_reviewer(base.frontline_id)
    assert after_verdict["audited_count"] == 1
    assert after_verdict["agree_count"] == 0
    assert_rate_equals(after_verdict["accuracy_score_audit_only"], 0.0, "audit-only after verdict")
    assert after_verdict["status"] == "ACTIVE"

    disputed = world.dispute(
        sample_id, base.frontline_id, dispute_note="The threat was explicit"
    )
    assert disputed["id"] == sample_id
    assert disputed["status"] == "DISPUTED"
    assert disputed["counts_toward_accuracy"] is False
    after_dispute = world.get_reviewer(base.frontline_id)
    assert after_dispute["audited_count"] == 0
    assert after_dispute["agree_count"] == 0
    assert after_dispute["accuracy_score_audit_only"] is None
    assert after_dispute["status"] == "ACTIVE"

    recalibrated = world.audit(sample_id, base.auditor_id, verdict="AGREE")
    assert recalibrated["id"] == sample_id
    assert recalibrated["status"] == "AUDITED"
    assert recalibrated["verdict"] == "AGREE"
    assert recalibrated["counts_toward_accuracy"] is True
    after_reaudit = world.get_reviewer(base.frontline_id)
    assert after_reaudit["audited_count"] == 1
    assert after_reaudit["agree_count"] == 1
    assert_rate_equals(after_reaudit["accuracy_score_audit_only"], 1.0, "audit-only after re-audit")
    assert after_reaudit["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_audit_samples(headers=ADMIN_HEADERS, case_id=removal.case_id)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [sample_id]


def test_accuracy_gate_silent_below_min_gate_sample_then_suspends_at_two(api, world):
    """The first disagreement imposes nothing and the second one suspends.

    PRD 3.8: "The gate only acts once there is enough evidence — the sum of
    `audited_count` and `appealed_count` must be at least 2."

    Design: Corner/cross_cutting_complexity_layers/accuracy_gate_silent_below_min_gate_sample_then_suspends_at_two
    """
    base = build_workforce_baseline(world)
    first = _decided_cases(base, 1)[0]
    first_sample = world.draw_sample(first.case_id, base.auditor_id)
    world.audit(
        first_sample["id"], base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"
    )
    below_gate = world.get_reviewer(base.frontline_id)
    assert below_gate["audited_count"] == 1
    assert below_gate["agree_count"] == 0
    assert_rate_equals(below_gate["accuracy_score_audit_only"], 0.0, "audit-only at sample one")
    assert_rate_equals(below_gate["accuracy_score_blended"], 0.0, "blended at sample one")
    assert below_gate["status"] == "ACTIVE"

    second = _decided_cases(base, 1)[0]
    assert world.get_case(second.case_id)["decided_by_reviewer_id"] == base.frontline_id
    second_sample = world.draw_sample(second.case_id, base.auditor_id)

    world.audit(
        second_sample["id"], base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"
    )
    at_gate = world.get_reviewer(base.frontline_id)
    assert at_gate["audited_count"] == 2
    assert at_gate["agree_count"] == 0
    assert_rate_equals(at_gate["accuracy_score_audit_only"], 0.0, "accuracy_score_audit_only")
    assert at_gate["status"] == "SUSPENDED"
    assert at_gate["open_case_count"] == 0
    assert at_gate["exposure_points_today"] == 0

    assert world.get_case(first.case_id)["status"] == "DECIDED"
    assert world.get_case(second.case_id)["status"] == "DECIDED"
    assert world.get_queue(base.queue_id)["unassigned_case_count"] == 0


def test_suspended_reviewer_not_auto_restored_when_dispute_lifts_accuracy(api, world):
    """A recovered score leaves the suspension standing until a grant lifts it.

    PRD 3.4: "A grant against a reviewer in `SUSPENDED` likewise moves them
    `SUSPENDED → ACTIVE` as a recalibration grant, adding the granted id to their
    certifications."

    Design: Corner/calculations/suspended_reviewer_not_auto_restored_when_dispute_lifts_accuracy
    """
    base = build_workforce_baseline(world)
    first, second = _decided_cases(base, 2)
    first_sample = world.draw_sample(first.case_id, base.auditor_id)
    second_sample = world.draw_sample(second.case_id, base.auditor_id)
    assert world.get_reviewer(base.frontline_id)["exposure_points_today"] == 4

    world.audit(first_sample["id"], base.auditor_id, verdict="AGREE")
    after_one = world.get_reviewer(base.frontline_id)
    assert_rate_equals(after_one["accuracy_score_audit_only"], 1.0, "audit-only at sample one")
    assert after_one["status"] == "ACTIVE"

    world.audit(
        second_sample["id"], base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"
    )
    suspended = world.get_reviewer(base.frontline_id)
    assert suspended["audited_count"] == 2
    assert suspended["agree_count"] == 1
    assert_rate_equals(suspended["accuracy_score_audit_only"], 0.5, "audit-only at sample two")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["open_case_count"] == 0
    assert suspended["exposure_points_today"] == 0

    world.dispute(
        second_sample["id"], base.frontline_id, dispute_note="The clip was newsworthy"
    )
    contested = world.get_sample(second_sample["id"])
    assert contested["status"] == "DISPUTED"
    assert contested["counts_toward_accuracy"] is False
    recovered = world.get_reviewer(base.frontline_id)
    assert recovered["audited_count"] == 1
    assert recovered["agree_count"] == 1
    assert_rate_equals(recovered["accuracy_score_audit_only"], 1.0, "audit-only after the dispute")
    assert recovered["status"] == "SUSPENDED"

    version_before = recovered["version"]
    world.certify(base.frontline_id, base.version_id)
    restored = world.get_reviewer(base.frontline_id)
    assert restored["status"] == "ACTIVE"
    assert restored["certified_policy_version_ids"] == [base.version_id]
    assert restored["version"] == version_before + 1


def test_pending_retraining_gate_keeps_cases_assigned_but_flagged(api, world):
    """The middle band flags the held work instead of returning it.

    PRD 3.8: "`PENDING_RETRAINING` keeps the reviewer's `ASSIGNED` cases assigned
    to them but sets `requires_recertified_review` to true on each, so the work
    waits for a retrained decider rather than returning to the pool; because the
    reviewer is no longer `ACTIVE`, any attempt by them to decide such a case
    fails with `ERR_REVIEWER_NOT_ACTIVE`."

    Design: Corner/state_machines/pending_retraining_gate_keeps_cases_assigned_but_flagged
    """
    base = build_workforce_baseline(world)
    first, second, third = _decided_cases(base, 3)
    held = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 2}
    )
    loaded = world.get_reviewer(base.frontline_id)
    assert loaded["open_case_count"] == 1
    assert loaded["exposure_points_today"] == 8

    for scenario in (first, second):
        sample = world.draw_sample(scenario.case_id, base.auditor_id)
        world.audit(sample["id"], base.auditor_id, verdict="AGREE")
    at_min_sample = world.get_reviewer(base.frontline_id)
    assert at_min_sample["audited_count"] == 2
    assert_rate_equals(at_min_sample["accuracy_score_audit_only"], 1.0, "audit-only at two agrees")
    assert at_min_sample["status"] == "ACTIVE"

    third_sample = world.draw_sample(third.case_id, base.auditor_id)
    world.audit(
        third_sample["id"], base.auditor_id, verdict="DISAGREE_MATERIAL", correct_outcome="REMOVE"
    )
    demoted = world.get_reviewer(base.frontline_id)
    assert demoted["audited_count"] == 3
    assert demoted["agree_count"] == 2
    assert_rate_equals(demoted["accuracy_score_audit_only"], 2 / 3, "accuracy_score_audit_only")
    assert_rate_equals(demoted["accuracy_score_blended"], 2 / 3, "accuracy_score_blended")
    assert demoted["status"] == "PENDING_RETRAINING"
    assert demoted["open_case_count"] == 1
    assert demoted["exposure_points_today"] == 8

    flagged = world.get_case(held.case_id)
    assert flagged["requires_recertified_review"] is True
    assert flagged["status"] == "ASSIGNED"
    assert flagged["assigned_reviewer_id"] == base.frontline_id
    assert world.get_queue(base.queue_id)["unassigned_case_count"] == 0

    blocked = api.decide_case(
        held.case_id,
        decide_case_payload(outcome="NO_ACTION"),
        headers=make_reviewer_headers(base.frontline_id),
    )
    assert blocked.status_code == 409
    validate_error(blocked, ApiErrorId.REVIEWER_NOT_ACTIVE.value)
    assert blocked.json()["data"]["error_id"] != ApiErrorId.REVIEWER_NOT_CERTIFIED.value

    world.certify(base.frontline_id, base.version_id)
    retrained = world.get_reviewer(base.frontline_id)
    assert retrained["status"] == "ACTIVE"
    assert retrained["pending_retraining_version_ids"] == []
    assert retrained["certified_policy_version_ids"] == [base.version_id]

    decided = validate_success(
        api.decide_case(
            held.case_id,
            decide_case_payload(outcome="NO_ACTION"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert decided["status"] == "DECIDED"
    assert decided["decision_outcome"] == "NO_ACTION"
    account = world.get_account(base.account_id)
    assert account["strike_points"] == 0
    assert account["standing"] == "GOOD_STANDING"


def _agreeing_audit_and_a_pending_appeal(world):
    """One AGREE audit and one routed appeal over the same single decision."""
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides={"graphic_weight": 2}
    )
    world.decide(scenario.case_id, base.frontline_id, outcome="REMOVE")
    sample = world.draw_sample(scenario.case_id, base.auditor_id)
    world.audit(sample["id"], base.auditor_id, verdict="AGREE")
    appeal = world.file_appeal(scenario.case_id, base.account_id)
    world.route_appeal(appeal["id"], base.auditor_id, target_reviewer_id=base.senior_id)
    return base, scenario, appeal["id"]


def test_reviewer_accuracy_audit_only_and_blended_diverge_on_one_dataset(api, world):
    """The same evidence scores 1.0000 on one variant and 0.5000 on the other.

    PRD 3.8: "From those four counters: `accuracy_score_audit_only` is
    `agree_count` divided by `audited_count`, rounded half up to four decimal
    places, and is null while `audited_count` is 0; `accuracy_score_blended` is
    the sum of `agree_count` and `upheld_appeal_count` divided by the sum of
    `audited_count` and `appealed_count`, rounded half up to four decimal places,
    and is null while that combined denominator is 0."

    Design: Difficulty/dual_variant_calc/reviewer_accuracy_audit_only_vs_blended_diverge
    """
    base, scenario, appeal_id = _agreeing_audit_and_a_pending_appeal(world)
    before = world.get_reviewer(base.frontline_id)
    assert before["audited_count"] == 1
    assert before["agree_count"] == 1
    assert before["appealed_count"] == 0
    assert_rate_equals(before["accuracy_score_audit_only"], 1.0, "audit-only before resolution")
    assert_rate_equals(before["accuracy_score_blended"], 1.0, "blended before resolution")

    world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Satire, not a threat",
    )

    decider = world.get_reviewer(base.frontline_id)
    assert decider["audited_count"] == 1
    assert decider["agree_count"] == 1
    assert decider["appealed_count"] == 1
    assert decider["upheld_appeal_count"] == 0
    assert_rate_equals(decider["accuracy_score_audit_only"], 1.0, "accuracy_score_audit_only")
    assert_rate_equals(decider["accuracy_score_blended"], 0.5, "accuracy_score_blended")


def test_accuracy_gate_reads_the_blended_variant_once_an_appeal_is_terminal(api, world):
    """With one terminal appeal the gate takes the blended figure and suspends.

    PRD 3.8: "After both variants are stored, the **accuracy gate** runs, and it
    chooses between them: the gate score is `accuracy_score_blended` whenever the
    reviewer has at least one terminal appeal, and `accuracy_score_audit_only`
    otherwise."

    Design: Difficulty/dual_variant_calc/reviewer_accuracy_audit_only_vs_blended_diverge
    """
    base, scenario, appeal_id = _agreeing_audit_and_a_pending_appeal(world)
    assert world.get_reviewer(base.frontline_id)["status"] == "ACTIVE"

    world.resolve_appeal(
        appeal_id,
        base.senior_id,
        resolution="OVERTURNED",
        resolution_note="Satire, not a threat",
    )

    decider = world.get_reviewer(base.frontline_id)
    assert_rate_equals(decider["accuracy_score_audit_only"], 1.0, "accuracy_score_audit_only")
    assert decider["status"] == "SUSPENDED"

    assert world.get_case(scenario.case_id)["is_overturned"] is True
    assert_fields(
        world.get_account(base.account_id),
        {"strike_points": 0, "standing": "GOOD_STANDING", "appeal_credits_remaining": 3},
        "account after the overturn",
    )
