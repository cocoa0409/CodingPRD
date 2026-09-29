"""
Status graphs: legal advances, refused advances, terminal states and the cascades
that fire when a status moves.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    INSURANCE_EXAMINER_HEADERS,
    fixtures as fx,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_system_fields,
    assert_two_decimal_places,
)
from test_helpers.factories import (
    advance_payload,
    exam_result_payload,
    filing_decision_payload,
    regulatory_filing_payload,
    vendor_advance_payload,
)
from test_helpers.types import (
    AUTHORITY_CHARTERING,
    BLOCKED_REASON_EXAM_DEFICIENT,
    BLOCKED_REASON_NONE,
    DECISION_CONDITIONALLY_APPROVED,
    EXAM_DEFICIENT,
    EXAM_OUTCOME_DEFICIENT,
    FILING_CONDITIONALLY_APPROVED,
    FILING_DRAFT,
    PLAN_DRAFT,
    PLAN_PINNED,
    PLAN_SUBMITTED,
    RAISE_ESCROW_LOCKED,
    STAGE_ABANDONED,
    STAGE_CONDITIONALLY_APPROVED,
    STAGE_FILING_READY,
    STAGE_OPEN,
    STAGE_ORGANIZING,
    STAGE_PRE_OPENING,
    STAGE_UNDER_REVIEW,
    VENDOR_SELECTED,
    VENDOR_TERMINATED,
    WINDOW_CANCELLED,
)


# ---------------------------------------------------------------------------
# Corner / state_machines
# ---------------------------------------------------------------------------
def test_selecting_a_critical_vendor_scoring_88_moves_it_out_of_evaluation(api):
    """
    A critical core-processing contract rated 88 is the first of its domain, so both extra
    gates on selection are satisfied and the advance goes through: the status moves on, the
    row is at its second version, its diligence rating is untouched and its conversion
    calendar is still empty. Choosing a vendor is not a project milestone, so the group is
    left where it was.

    PRD: "`SELECTED` is reachable only from `EVALUATING`, and carries two extra gates: no other contract of the same group and the same `service_domain` may already be `SELECTED` or `SIGNED` — a second core provider is refused with `ERR_VENDOR_DOMAIN_ALREADY_SELECTED` — and a contract whose `criticality` is `CRITICAL` must have a `due_diligence_score` of at least 70, with a score of 69 on a critical vendor refused by `ERR_DUE_DILIGENCE_INSUFFICIENT` while the same score on a `SIGNIFICANT` or `ROUTINE` vendor passes untouched."
    PRD: "Every advance increments the contract's `version` by one."

    Design: Corner/state_machines/state_vendor_contract_advances_evaluating_to_selected
    """
    world = fx.open_group(api)
    contract_id = fx.add_vendor_contract(api, world)

    selected = validate_success(
        api.advance_vendor_contract(
            contract_id, vendor_advance_payload(VENDOR_SELECTED), COUNSEL_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        selected,
        status=VENDOR_SELECTED,
        version=2,
        active_window_count=0,
        due_diligence_score=88,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_ORGANIZING)


def test_a_filing_is_prepared_as_a_draft_with_no_condition_posture_yet(api):
    """
    Preparing an application does not put it in front of anybody: it begins as a draft with
    no information rounds, no filed or decided instant, and a condition posture computed
    against an empty condition set. Clearance is false even so, because clearance speaks
    about an approved filing rather than an empty list. The group and the plan it names are
    both untouched — nothing is pinned until an approval pins it.

    PRD: "A new filing begins in `DRAFT` with `info_request_round` 0, `filed_at` null and `decision_at` null; the condition posture is run against its empty condition set, so `condition_total_count`, `open_blocking_condition_count` and `settled_condition_count` are all 0 and `pre_opening_clearance` is false."
    PRD: "`pre_opening_clearance` is true exactly when the filing's own `status` is `CONDITIONALLY_APPROVED` or `FINAL_APPROVED` **and** `open_blocking_condition_count` is 0; a filing sitting in `FILED` with no conditions at all has zero open blockers and still has `pre_opening_clearance` false, because clearance is a statement about an approved filing, not about an empty condition list."

    Design: Corner/state_machines/state_regulatory_filing_created_in_draft_status
    """
    world = fx.filing_ready_group(api)

    filing = get_success_data(
        api.create_regulatory_filing(
            regulatory_filing_payload(
                world["group_id"], world["plan_id"], AUTHORITY_CHARTERING
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_system_fields(filing, expected_version=1)
    assert_fields_equal(
        filing,
        status=FILING_DRAFT,
        info_request_round=0,
        filed_at=None,
        decision_at=None,
        condition_total_count=0,
        open_blocking_condition_count=0,
        settled_condition_count=0,
        pre_opening_clearance=False,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_FILING_READY)
    assert_fields_equal(fx.read_plan(api, world["plan_id"]), status=PLAN_SUBMITTED)


def test_jumping_from_organizing_straight_to_open_is_refused_by_the_stage_graph(api):
    """
    Opening day is reachable only from pre-opening, so an empty file asking to open is not
    merely ungated but off the graph entirely. The refusal is the transition error and not
    the readiness-examination gate that guards a legitimate opening, because the graph check
    runs first. Supervision has not begun.

    PRD: "A `target_stage` the current stage cannot reach at all is refused with `ERR_STAGE_TRANSITION_NOT_ALLOWED`, which is evaluated before any gate specific to the target."
    PRD: "Advancing `PRE_OPENING` to `OPEN` is opening day."

    Design: Corner/state_machines/state_advance_group_from_organizing_to_open_is_rejected
    """
    world = fx.open_group(api)

    error = validate_error(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_OPEN), COUNSEL_HEADERS
        ),
        "ERR_STAGE_TRANSITION_NOT_ALLOWED",
        expected_status=409,
    )
    assert error["error_id"] != "ERR_READINESS_EXAM_NOT_PASSED", (
        "the stage-graph check outranks the gates specific to the target stage"
    )
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_ORGANIZING,
        supervision_started_at=None,
    )


def test_locking_an_already_locked_escrow_is_refused_rather_than_repeated(api):
    """
    The lock is not idempotent. A second attempt on a raise that already committed its
    escrow fails the very first of the three gates, which asks for an open offering, and the
    money is left exactly as the first lock left it: the whole cleared basis still in escrow
    and nothing released, since the released figure stays at zero until a release happens.

    PRD: "Three gates apply in this order: the raise must be `OPEN` (`ERR_RAISE_NOT_LOCKABLE`); at least one subscription of the raise must have `counts_toward_escrow` true, so an empty cleared set cannot be locked even in the degenerate case where `minimum_gross_cents` happens to be zero (`ERR_NO_CLEARED_SUBSCRIPTIONS`); and `cleared_escrow_cents` must be at least `minimum_gross_cents`, measured on the cleared basis only — `pledged_gross_cents` is never accepted here (`ERR_ESCROW_BELOW_MINIMUM`)."
    PRD: "A third field, the capital raise's `released_net_cents`, is a snapshot: it is 0 until escrow is released and thereafter holds the value `projected_net_release_cents` had at the instant of release."

    Design: Corner/state_machines/state_second_lock_escrow_is_rejected_as_not_lockable
    """
    world = fx.escrow_ready_group(api)
    locked = fx.lock_escrow(api, world)
    assert_fields_equal(locked, status=RAISE_ESCROW_LOCKED)

    validate_error(
        api.lock_escrow(world["raise_id"], ESCROW_AGENT_HEADERS),
        "ERR_RAISE_NOT_LOCKABLE",
        expected_status=409,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        status=RAISE_ESCROW_LOCKED,
        cleared_escrow_cents=4_150_000_000,
        released_net_cents=0,
    )


def test_an_abandoned_project_cannot_be_walked_back_onto_the_board(api):
    """
    Abandonment is the end of the road: an abandoned file asking to go back to filing-ready
    is off the stage graph in the same way any impossible target is, and the refusal leaves
    the file abandoned.

    PRD: "Advancing to `ABANDONED` is permitted from `ORGANIZING`, `FILING_READY`, `UNDER_REVIEW` or `CONDITIONALLY_APPROVED` and from nowhere else, so a group that has reached pre-opening or has opened cannot be abandoned through this surface."
    PRD: "A `target_stage` the current stage cannot reach at all is refused with `ERR_STAGE_TRANSITION_NOT_ALLOWED`, which is evaluated before any gate specific to the target."

    Design: Corner/state_machines/state_abandoned_group_refuses_any_further_advance
    """
    world = fx.open_group(api)
    abandoned = get_success_data(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_ABANDONED), COUNSEL_HEADERS
        )
    )
    assert_fields_equal(abandoned, stage=STAGE_ABANDONED)

    validate_error(
        api.advance_group(
            world["group_id"], advance_payload(STAGE_FILING_READY), COUNSEL_HEADERS
        ),
        "ERR_STAGE_TRANSITION_NOT_ALLOWED",
        expected_status=409,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_ABANDONED)


def test_a_plan_carrying_no_overlay_at_all_cannot_be_submitted(api):
    """
    A board of five cleared organizers and a composite well over the floor get the plan past
    the first three gates, but a plan with no stress overlay is stopped at the fourth. The
    missing-overlay refusal is reported ahead of any capital arithmetic, so neither the
    stress floor nor the adequacy verdict is what is named, and the plan stays a draft with
    its rolled-up stress figures still at zero.

    PRD: "The plan's `stress_scenario_count` must be at least 1, so a plan with no overlay at all cannot be submitted (`ERR_STRESS_SCENARIO_REQUIRED`)."
    PRD: "The ordering matters in practice: a plan with no scenarios *and* an inadequate verdict reports the missing-scenario error, and a group whose composition is deficient reports that before any capital arithmetic is attempted."

    Design: Corner/state_machines/state_submit_plan_without_stress_scenario_is_rejected
    """
    world = fx.composition_met_group(api)
    plan_id = fx.add_business_plan(api, world)

    error = validate_error(
        api.submit_business_plan(plan_id, world["lead_headers"]),
        "ERR_STRESS_SCENARIO_REQUIRED",
        expected_status=409,
    )
    assert error["error_id"] not in (
        "ERR_CAPITAL_INADEQUATE",
        "ERR_STRESS_CAPITAL_SHORTFALL",
    ), "the missing-overlay gate is reached before any capital arithmetic"

    assert_fields_equal(
        fx.read_plan(api, plan_id),
        status=PLAN_DRAFT,
        stress_scenario_count=0,
        worst_governing_min_leverage_ratio_bps=0,
    )
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_ORGANIZING)


def test_the_first_conditional_approval_pins_the_plan_and_the_second_moves_the_project(api):
    """
    The chartering authority's conditional approval is the moment the plan becomes the fixed
    supervisory benchmark, and with no conditions attached that filing is already clear for
    pre-opening. The project itself does not move, because the group's stage is compound and
    one approval is only half of it. The deposit insurer's approval completes the pair, lifts
    the group and clears the blocking reason, and pins nothing of its own — the plan is
    pinned once and only once.

    PRD: "`CONDITIONALLY_APPROVED` is legal only from `FILED` and is the pivot of the whole project."
    PRD: "When the filing's `authority` is `CHARTERING_AUTHORITY`, its pinned business plan moves from `SUBMITTED` to `PINNED` and that plan's `version` increments by one — this is the moment the plan becomes the fixed benchmark for heightened supervision."
    PRD: "And because the group's stage is compound, the group advances only when **both** filings are `CONDITIONALLY_APPROVED` at the same instant: on that second approval the group moves from `UNDER_REVIEW` to `CONDITIONALLY_APPROVED` with `opening_blocked_reason` reset to `NONE` and its `version` incremented by one."
    PRD: "Only the examiner of that filing's own authority may decide it, and every decision sets `decision_at` to the current logical clock and increments the filing's `version` by one."

    Design: Corner/state_machines/state_conditional_approval_pins_plan_and_advances_group
    """
    world = fx.filing_ready_group(api)
    fx.both_filings_filed(api, world)

    chartering = validate_success(
        api.record_filing_decision(
            world["f_ca"],
            filing_decision_payload(DECISION_CONDITIONALLY_APPROVED),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(
        chartering, status=FILING_CONDITIONALLY_APPROVED, pre_opening_clearance=True
    )
    assert chartering["decision_at"].startswith("2026-08-01T00:00:00"), (
        f"decision_at must carry the logical clock: {chartering['decision_at']!r}"
    )
    pinned = fx.read_plan(api, world["plan_id"])
    assert_fields_equal(pinned, status=PLAN_PINNED)
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_UNDER_REVIEW)

    insurer = validate_success(
        api.record_filing_decision(
            world["f_di"],
            filing_decision_payload(DECISION_CONDITIONALLY_APPROVED),
            INSURANCE_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(insurer, status=FILING_CONDITIONALLY_APPROVED)
    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_CONDITIONALLY_APPROVED,
        opening_blocked_reason=BLOCKED_REASON_NONE,
    )
    assert_fields_equal(
        fx.read_plan(api, world["plan_id"]),
        status=PLAN_PINNED,
        version=pinned["version"],
    )


def test_terminating_a_vendor_cancels_every_slot_it_was_holding(api):
    """
    Two reserved migration slots occupy the contract's calendar. Dropping the vendor while
    the project is still organizing is allowed, and it cascades: both slots are cancelled and
    the occupancy count falls to nothing, while each cancelled slot keeps the twenty-four
    hour span it was booked for, because a cancellation releases the interval without
    rewriting it.

    PRD: "Termination cascades: every conversion window of that contract whose `status` is `RESERVED` or `CONFIRMED` becomes `CANCELLED` with its own `version` bumped by one, and because those windows released their intervals the contract's `active_window_count` is recomputed to 0."
    PRD: "`TERMINATED` is reachable from `EVALUATING`, `SELECTED` or `SIGNED`, and is terminal, but it is barred once the group's `stage` is `OPEN`: a live bank may not drop a vendor through this surface, and the attempt is refused with `ERR_VENDOR_TERMINATION_BLOCKED_AFTER_OPENING`."

    Design: Corner/state_machines/state_cascade_down_vendor_termination_cancels_reserved_windows
    """
    world = fx.open_group(api)
    contract_id = fx.add_vendor_contract(api, world)
    fx.advance_vendor(api, contract_id, VENDOR_SELECTED)
    w1 = fx.reserve_window(
        api, contract_id, "2026-09-01T08:00:00Z", "2026-09-02T08:00:00Z"
    )
    w2 = fx.reserve_window(
        api, contract_id, "2026-09-03T08:00:00Z", "2026-09-04T08:00:00Z"
    )
    assert_fields_equal(fx.read_contract(api, contract_id), active_window_count=2)

    terminated = validate_success(
        api.advance_vendor_contract(
            contract_id, vendor_advance_payload(VENDOR_TERMINATED), COUNSEL_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        terminated, status=VENDOR_TERMINATED, active_window_count=0
    )

    first = fx.read_window(api, w1)
    assert_fields_equal(first, status=WINDOW_CANCELLED)
    assert_two_decimal_places(first["duration_hours"], 24.00, "duration_hours")
    assert_fields_equal(fx.read_window(api, w2), status=WINDOW_CANCELLED)
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_ORGANIZING)


def test_a_deficient_examination_knocks_the_project_out_of_pre_opening(api):
    """
    Reported at exactly the instant its window opens, a nine-finding deficiency is recorded
    rather than refused, and it drags the group back a stage with the reason naming the
    examination rather than a filing. The visit keeps its two-day report-writing tail, so the
    slot it occupied is not released. Nothing else is disturbed: the filings stay
    conditionally approved and the escrow stays committed, because an examination result
    speaks only about readiness.

    PRD: "The group falls from `PRE_OPENING` to `CONDITIONALLY_APPROVED` with `opening_blocked_reason` set to `EXAM_DEFICIENT` — distinguishing this regression from a filing-driven one — every *other* examination of the group whose `status` is `SCHEDULED` becomes `CANCELLED` with its version bumped, and the group's `version` increments by one."
    PRD: "There is no such limit on a `DEFICIENT` result."
    PRD: "Each examination's `buffer_end_utc` is derived as its `window_end_utc` plus 48 hours — two full days of report-writing time — and the interval it occupies runs from `window_start_utc` inclusive to `buffer_end_utc` exclusive."

    Design: Corner/state_machines/state_cross_entity_exam_deficient_reverts_group_stage
    """
    world = fx.pre_opening_group(api)
    exam_id = fx.schedule_exam(api, world)
    assert_fields_equal(fx.read_group(api, world["group_id"]), stage=STAGE_PRE_OPENING)
    fx.set_clock(api, "2026-10-05T09:00:00Z")

    resolved = validate_success(
        api.record_exam_result(
            exam_id,
            exam_result_payload(EXAM_OUTCOME_DEFICIENT, 9),
            CHARTERING_EXAMINER_HEADERS,
        ),
        expected_status=200,
    )
    assert_fields_equal(resolved, status=EXAM_DEFICIENT, finding_count=9)
    assert resolved["buffer_end_utc"].startswith("2026-10-09T17:00:00"), (
        f"the 48-hour tail must land on 2026-10-09T17:00:00Z, got "
        f"{resolved['buffer_end_utc']!r}"
    )

    assert_fields_equal(
        fx.read_group(api, world["group_id"]),
        stage=STAGE_CONDITIONALLY_APPROVED,
        opening_blocked_reason=BLOCKED_REASON_EXAM_DEFICIENT,
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]), status=FILING_CONDITIONALLY_APPROVED
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]), status=RAISE_ESCROW_LOCKED
    )
