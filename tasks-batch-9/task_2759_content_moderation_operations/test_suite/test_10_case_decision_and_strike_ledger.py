"""Recording decisions, the strike ledger and the posture it drives."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_rate_equals,
    expected_effective_confidence,
    expected_standing,
    expected_strike_points,
)
from test_helpers.factories import decide_case_payload
from test_helpers.fixtures import (
    build_assigned_case,
    build_decided_case,
    build_legal_case,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS, LEGAL_HEADERS, make_reviewer_headers

TEXT_WEIGHT_ONE = {"media_kind": "TEXT", "graphic_weight": 1}
TEXT_WEIGHT_TWO = {"media_kind": "TEXT", "graphic_weight": 2}


def _open_and_assign(base, reviewer_id, **content):
    """Raise a human-review case on fresh content and hand it to one reviewer."""
    world = base.world
    item = world.create_content(base.account_id, language=base.queue["language"], **content)
    signal = world.submit_signal(
        item["id"], policy_category_code=base.category_code, classifier_confidence=0.7
    )
    case = world.get_case(signal["resulting_case_id"])
    world.assign(case["id"], target_reviewer_id=reviewer_id)
    return item, signal, world.get_case(case["id"])


def test_strike_points_take_the_ceiling_of_one_product(api, world):
    """The three factors multiply first and only the single product is ceiled.

    PRD 3.5: "Rounding each factor before multiplying produces a different
    integer and is wrong: base 2 points at weight 0.75 with a multiplier of 1.25
    gives a product of 1.875, whose ceiling is 2 — not the 3 that per-factor
    rounding would yield."

    Design: Difficulty/combinatorial_formula/strike_points_multiply_then_ceil_once
    """
    assert expected_strike_points("T3", "AGE_GATE", 1) == 2
    base = build_workforce_baseline(
        world,
        category_overrides={
            "code": "GRAPHIC_MEDIA",
            "name": "Graphic Media",
            "severity_tier": "T3",
        },
        version_overrides={"enforcement_action": "AGE_GATE"},
    )
    build_decided_case(
        base,
        reviewer_id=base.frontline_id,
        outcome="REMOVE",
        content_overrides=TEXT_WEIGHT_ONE,
    )
    first_ledger = world.get_account(base.account_id)
    assert first_ledger["strike_points"] == 2
    assert first_ledger["lifetime_removed_count"] == 1

    item, signal, case = _open_and_assign(base, base.frontline_id, **TEXT_WEIGHT_ONE)
    assert_rate_equals(signal["effective_confidence"], 0.72, "effective_confidence")
    assert_instant_equals(case["sla_due_at"], "2026-08-01T13:00:00Z", "T3 sla_due_at")

    decided = validate_success(
        api.decide_case(
            case["id"],
            decide_case_payload(outcome="AGE_GATE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert decided["strike_points_applied"] == 2

    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["standing"] == "LIMITED"
    assert account["lifetime_removed_count"] == 1
    assert_fields(
        world.get_content(item["id"]),
        {"visibility_status": "AGE_GATED", "review_status": "ACTIONED"},
        "age-gated item",
    )


def test_repeat_multiplier_reads_the_ledger_before_its_own_increment(api, world):
    """A REMOVE never inflates its own multiplier, and NO_ACTION charges nothing.

    PRD 3.5: "The author's `lifetime_removed_count` is read as it stood
    **immediately before** this decision's own increment, so a `REMOVE` decision
    never inflates its own multiplier."

    Design: Difficulty/combinatorial_formula/strike_points_multiply_then_ceil_once
    """
    assert expected_strike_points("T3", "REMOVE", 0) == 2
    assert expected_strike_points("T3", "NO_ACTION", 1) == 0
    base = build_workforce_baseline(
        world,
        category_overrides={
            "code": "GRAPHIC_MEDIA",
            "name": "Graphic Media",
            "severity_tier": "T3",
        },
        version_overrides={"enforcement_action": "AGE_GATE"},
    )
    first = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_ONE
    )
    removed = validate_success(
        api.decide_case(
            first.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert removed["strike_points_applied"] == 2
    ledger = world.get_account(base.account_id)
    assert ledger["strike_points"] == 2
    assert ledger["lifetime_removed_count"] == 1
    assert ledger["standing"] == "GOOD_STANDING"

    item, _, case = _open_and_assign(base, base.frontline_id, **TEXT_WEIGHT_ONE)
    spared = validate_success(
        api.decide_case(
            case["id"],
            decide_case_payload(outcome="NO_ACTION"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert spared["strike_points_applied"] == 0
    after = world.get_account(base.account_id)
    assert after["strike_points"] == 2
    assert after["lifetime_removed_count"] == 1
    assert after["standing"] == expected_standing(2)
    assert_fields(
        world.get_content(item["id"]),
        {"visibility_status": "LIVE", "review_status": "CLEAR"},
        "untouched item",
    )


def test_strike_ledger_landing_exactly_on_six_suspends_the_account(api, world):
    """Four plus two lands on the inclusive breakpoint and the posture flips.

    PRD 3.1: "`standing` is a posture, not an input. It is recomputed from
    `strike_points` immediately after every ledger recomputation, using inclusive
    breakpoints: an account with 10 or more points is `BANNED`, an account with 6
    through 9 points is `SUSPENDED`, an account with 3 through 5 points is
    `LIMITED`, and an account with 2 or fewer points is `GOOD_STANDING`."

    Design: Difficulty/boundary_precision_check/strike_points_exactly_six_sets_suspended
    """
    assert expected_strike_points("T2", "REMOVE", 0) == 4
    assert expected_strike_points("T2", "WARN", 1) == 2
    base = build_workforce_baseline(world)
    build_decided_case(
        base,
        reviewer_id=base.frontline_id,
        outcome="REMOVE",
        content_overrides=TEXT_WEIGHT_ONE,
    )
    midpoint = world.get_account(base.account_id)
    assert midpoint["strike_points"] == 4
    assert midpoint["standing"] == "LIMITED"

    item, signal, case = _open_and_assign(base, base.frontline_id, **TEXT_WEIGHT_ONE)
    assert_rate_equals(signal["effective_confidence"], 0.74, "effective_confidence")
    assert expected_effective_confidence(0.7, "STANDARD", 4) == 0.74

    warned = validate_success(
        api.decide_case(
            case["id"],
            decide_case_payload(outcome="WARN"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert warned["strike_points_applied"] == 2
    assert warned["decision_source"] == "HUMAN"
    assert warned["decided_by_reviewer_id"] == base.frontline_id
    assert_instant_equals(
        warned["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at"
    )

    account = world.get_account(base.account_id)
    assert account["strike_points"] == 6
    assert account["standing"] == "SUSPENDED"
    assert account["lifetime_removed_count"] == 1
    assert_fields(
        world.get_content(item["id"]),
        {"visibility_status": "LIVE", "review_status": "ACTIONED"},
        "warned item",
    )
    assert world.get_reviewer(base.frontline_id)["status"] == "ACTIVE"
    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0


def test_strike_ledger_stopping_at_five_stays_limited(api, world):
    """One point short of the breakpoint the account is still merely limited.

    PRD 3.1: "Exactly 6 points is `SUSPENDED`; exactly 5 points is `LIMITED`."

    Design: Difficulty/boundary_precision_check/strike_points_exactly_six_sets_suspended
    """
    assert expected_strike_points("T3", "WARN", 1) == 1
    base = build_workforce_baseline(world)
    build_decided_case(
        base,
        reviewer_id=base.frontline_id,
        outcome="REMOVE",
        content_overrides=TEXT_WEIGHT_ONE,
    )
    assert world.get_account(base.account_id)["strike_points"] == 4

    minor = world.create_category(
        code="GRAPHIC_MEDIA", name="Graphic Media", severity_tier="T3", specialty="VIOLENCE"
    )
    minor_version = world.create_active_version(minor["id"])
    minor_queue = world.create_queue(minor["id"], specialty="VIOLENCE")
    world.certify(base.frontline_id, minor_version["id"])

    item = world.create_content(base.account_id, media_kind="TEXT", graphic_weight=1)
    signal = world.submit_signal(
        item["id"], policy_category_code="GRAPHIC_MEDIA", classifier_confidence=0.7
    )
    case = world.get_case(signal["resulting_case_id"])
    assert case["queue_id"] == minor_queue["id"]
    assert case["policy_version_id"] == minor_version["id"]
    world.assign(case["id"], target_reviewer_id=base.frontline_id)

    warned = validate_success(
        api.decide_case(
            case["id"],
            decide_case_payload(outcome="WARN"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert warned["strike_points_applied"] == 1

    account = world.get_account(base.account_id)
    assert account["strike_points"] == 5
    assert account["standing"] == "LIMITED"
    assert account["standing"] == expected_standing(5)
    assert account["lifetime_removed_count"] == 1


def test_decide_on_pending_assignment_case_rejected_as_not_assigned(api, world):
    """A case sitting in PENDING_ASSIGNMENT fails the state guard on the legal arm.

    PRD 3.5: "it must be `ASSIGNED`, or `ESCALATED` with `escalation_reason`
    `LEGAL_REQUEST` for the legal path (`ERR_CASE_NOT_ASSIGNED`)."

    The actor is `LegalCounsel` because PRD 2.8 tier 6 scopes the ownership check
    to "A reviewer acting on a case", and PRD 2.1 says a `LegalCounsel`
    `X-User-ID` "never resolves to an entity row" — so ownership does not apply
    and the request reaches the tier-9 lifecycle check. The case is a legal
    request returned to its queue, which PRD 3.5 says keeps its
    `escalation_reason` ("`escalation_reason` is retained as history rather than
    cleared"), so the tier-2 legal-arm restriction is satisfied while the status
    is `PENDING_ASSIGNMENT` rather than `ESCALATED`.

    Design: Corner/state_machines/decide_on_pending_assignment_case_rejected_as_not_assigned
    """
    base = build_workforce_baseline(world)
    scenario = build_legal_case(base, content_overrides=TEXT_WEIGHT_TWO)
    world.return_case(scenario.case_id)
    returned = world.get_case(scenario.case_id)
    assert returned["status"] == "PENDING_ASSIGNMENT"
    assert returned["escalation_reason"] == "LEGAL_REQUEST"
    assert returned["assigned_reviewer_id"] is None

    validate_error(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=LEGAL_HEADERS,
        ),
        ApiErrorId.CASE_NOT_ASSIGNED.value,
    )
    unchanged = world.get_case(scenario.case_id)
    assert_fields(
        unchanged,
        {
            "status": "PENDING_ASSIGNMENT",
            "decision_outcome": None,
            "version": returned["version"],
        },
        "case after refusal",
    )
    assert world.get_account(base.account_id)["strike_points"] == 0
    assert world.get_content(scenario.content_id)["review_status"] == "UNDER_REVIEW"


def test_second_decide_on_decided_case_rejected_as_already_decided(api, world):
    """DECIDED is terminal, so a replay cannot double-charge the ledger.

    PRD 3.5: "`decision_outcome` holds the supplied outcome and
    `appeal_deadline_at` becomes `decided_at` advanced by the **pinned** version's
    `appeal_window_hours`."

    Design: Corner/state_machines/second_decide_on_decided_case_rejected_as_already_decided
    """
    base = build_workforce_baseline(world)
    scenario = build_decided_case(
        base,
        reviewer_id=base.frontline_id,
        outcome="REMOVE",
        content_overrides=TEXT_WEIGHT_TWO,
    )
    first = world.get_case(scenario.case_id)
    assert first["decision_outcome"] == "REMOVE"
    assert first["strike_points_applied"] == 4

    validate_error(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="NO_ACTION"),
            headers=make_reviewer_headers(base.frontline_id),
        ),
        ApiErrorId.CASE_ALREADY_DECIDED.value,
    )
    replayed = world.get_case(scenario.case_id)
    assert replayed["decision_outcome"] == "REMOVE"
    assert replayed["strike_points_applied"] == 4

    account = world.get_account(base.account_id)
    assert account["strike_points"] == 4
    assert account["lifetime_removed_count"] == 1
    assert account["standing"] == "LIMITED"
    assert world.get_content(scenario.content_id)["visibility_status"] == "REMOVED"
    assert world.get_reviewer(base.frontline_id)["open_case_count"] == 0


def test_decide_cascade_is_visible_on_immediate_reads_without_a_clock_advance(api, world):
    """Every counter the decision touches is correct on the very next read.

    PRD 3.5: "The deciding reviewer's `open_case_count` falls by one, but their
    `exposure_points_today` is deliberately **not** reduced: they saw the
    material, so the wellness charge stands."

    Design: Corner/consistency_model/decide_cascade_is_visible_on_immediate_reads_without_a_clock_advance
    """
    base = build_workforce_baseline(world)
    scenario = build_assigned_case(
        base, reviewer_id=base.frontline_id, content_overrides=TEXT_WEIGHT_TWO
    )

    decided = validate_success(
        api.decide_case(
            scenario.case_id,
            decide_case_payload(outcome="REMOVE"),
            headers=make_reviewer_headers(base.frontline_id),
        )
    )
    assert decided["status"] == "DECIDED"
    assert decided["strike_points_applied"] == 4
    assert_instant_equals(decided["decided_at"], "2026-08-01T09:00:00Z", "decided_at")
    assert_instant_equals(
        decided["appeal_deadline_at"], "2026-08-04T09:00:00Z", "appeal_deadline_at"
    )

    account = validate_success(api.get_account(base.account_id, headers=ADMIN_HEADERS))
    assert_fields(
        account,
        {
            "lifetime_removed_count": 1,
            "strike_points": 4,
            "standing": "LIMITED",
            "appeal_credits_remaining": 3,
        },
        "account read straight after the write",
    )
    content = validate_success(api.get_content_item(scenario.content_id, headers=ADMIN_HEADERS))
    assert_fields(
        content,
        {"visibility_status": "REMOVED", "review_status": "ACTIONED", "open_case_count": 0},
        "content read straight after the write",
    )
    reviewer = validate_success(api.get_reviewer(base.frontline_id, headers=ADMIN_HEADERS))
    assert_fields(
        reviewer,
        {"open_case_count": 0, "exposure_points_today": 2, "status": "ACTIVE"},
        "reviewer read straight after the write",
    )
    queue = validate_success(api.get_review_queue(base.queue_id, headers=ADMIN_HEADERS))
    assert queue["open_case_count"] == 0
    assert queue["unassigned_case_count"] == 0
