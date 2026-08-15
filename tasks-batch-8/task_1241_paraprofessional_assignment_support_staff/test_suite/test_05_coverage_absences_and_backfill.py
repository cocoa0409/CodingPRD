"""Coverage plans, absence reports, the backfill selector, and backfill answers
(PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_absence_payload,
    create_coverage_plan_payload,
    create_para,
    get_plan_version,
    make_para_headers,
    setup_absence_scenario,
    setup_offered_backfill,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]
TEACHER = TEST_USERS["teacher_headers"]


def test_coverage_reopen_cycle_bumps_version(api):
    """PRD §3.6: "Publication moves it from `DRAFT` to `PUBLISHED` and increments its `version`. Reopening returns a `PUBLISHED` plan to `DRAFT`, and locking moves a `PUBLISHED` plan to `LOCKED` with `coverage_posture` becoming `FROZEN`; both reopen and lock require the posture to be `OPEN` — no linked absence in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — else `ERR_COVERAGE_GAPS_OPEN`, and both increment the plan’s `version` by one."

    Design: Corner/state_machines/coverage_reopen_cycle
    """
    plan, building, _ = create_active_plan()
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan["id"], building["id"], "2026-05-06"), COORD
        ),
        201,
    )
    assert cp["status"] == "DRAFT"
    assert cp["coverage_posture"] == "OPEN"

    validate_success(api.publish_coverage_plan(cp["id"], COORD))
    reopened = validate_success(api.reopen_coverage_plan(cp["id"], COORD))
    assert reopened["status"] == "DRAFT"
    republished = validate_success(api.publish_coverage_plan(cp["id"], COORD))
    assert republished["status"] == "PUBLISHED"
    assert republished["version"] == 4  # create v1 + publish (v2) + reopen (v3) + publish (v4)


def test_coverage_lock_blocked_until_absence_cancelled(api):
    """PRD §3.6: "Reopening returns a `PUBLISHED` plan to `DRAFT`, and locking moves a `PUBLISHED` plan to `LOCKED` with `coverage_posture` becoming `FROZEN`; both reopen and lock require the posture to be `OPEN` — no linked absence in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — else `ERR_COVERAGE_GAPS_OPEN`, and both increment the plan’s `version` by one."

    Design: Difficulty/cross_entity_state_dependency/coverage_lock_gated_by_absence_states
    """
    scenario = setup_absence_scenario()
    cp, absence = scenario["cp"], scenario["absence"]

    # Absence REPORTED blocks the lock
    resp = api.lock_coverage_plan(cp["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_GAPS_OPEN)

    # Cancelling the absence clears the gap; the same lock then succeeds
    validate_success(api.cancel_absence(absence["id"], COORD))
    locked = validate_success(api.lock_coverage_plan(cp["id"], COORD))
    assert locked["status"] == "LOCKED"
    assert locked["coverage_posture"] == "FROZEN"


def test_coverage_posture_returns_to_open_after_absence_cancel(api):
    """PRD §3.6: "The `coverage_posture` itself is derived: `OPEN` when no linked non-terminal absence exists, `GAPS_OPEN` when at least one linked absence sits in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED`, and `FROZEN` whenever the plan is `LOCKED` or `RECONCILED`. Posture recomputes whenever a linked absence is created, covered, or cancelled."

    Design: Corner/state_machines/coverage_posture_returns_to_open_after_cancel
    """
    scenario = setup_absence_scenario()
    cp, absence = scenario["cp"], scenario["absence"]

    mid = validate_success(api.get_coverage_plan(cp["id"], ANY))
    assert mid["coverage_posture"] == "GAPS_OPEN"
    validate_success(api.cancel_absence(absence["id"], COORD))
    end = validate_success(api.get_coverage_plan(cp["id"], ANY))
    assert end["coverage_posture"] == "OPEN"


def test_absence_double_cancel_returns_invalid_state(api):
    """PRD §3.6: "Cancelling an absence — from `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — moves it to `CANCELLED`, cancels any `OFFERED` backfill, and recomputes the coverage posture, which may return to `OPEN`. Absence transitions attempted from a state that does not declare them are rejected with `ERR_ABSENCE_INVALID_STATE`."

    Design: Corner/state_machines/absence_double_cancel_returns_invalid_state
    """
    scenario = setup_absence_scenario()
    absence = scenario["absence"]
    cancelled = validate_success(api.cancel_absence(absence["id"], COORD))
    assert cancelled["status"] == "CANCELLED"
    resp = api.cancel_absence(absence["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_ABSENCE_INVALID_STATE)


def test_absence_escalate_cancels_offered_backfill(api):
    """PRD §3.6: "Escalation by a coordinator moves a `REPORTED` or `BACKFILL_PENDING` absence to `ESCALATED` and cancels any `OFFERED` backfill attached to it."

    Design: Corner/state_machines/absence_escalate_cancels_offered_backfill
    """
    scenario = setup_offered_backfill()
    absence, bf = scenario["absence"], scenario["bf"]

    escalated = validate_success(api.escalate_absence(absence["id"], COORD))
    assert escalated["status"] == "ESCALATED"
    bf_after = validate_success(api.get_backfill(bf["id"], ANY))
    assert bf_after["status"] == "CANCELLED"


def test_backfill_selector_ranks_least_loaded_first(api):
    """PRD §3.6: "Survivors are ranked ascending by `weekly_scheduled_minutes` (least-loaded first), then by `base_hourly_wage_cents` (cheapest first), then by `hire_date` (earliest hire first), then by `created_at` as the final deterministic fallback — the record `id` is never used as a tie-break."

    Design: Corner/calculations/selector_ranking_least_loaded_first
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para")
    # P2: loaded with 600 min/wk, hired EARLIER than P3 — load beats hire date
    p2 = create_para(plan_id, b1, full_name="Loaded Lee", hire_date="2025-08-01")
    p3 = create_para(plan_id, b1, full_name="Idle Ida", hire_date="2025-09-01")
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=600, student_ref="STU-002")
    create_active_assignment(
        plan_id, s2["id"], p2["id"], b1,
        daily_start_minute=800, daily_end_minute=920,  # 120 min/day * 5 = 600
    )
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    cp = validate_success(api.publish_coverage_plan(cp["id"], COORD))
    # report absence against P1's ACTIVE assignment
    a1 = validate_success(
        api.list_assignments(ANY, params={"plan_id": plan_id, "para_id": p1["id"]})
    )[0]
    absence = validate_success(
        api.create_absence(
            create_absence_payload(a1["id"], "2026-05-06", cp["version"]), TEACHER
        ),
        201,
    )
    validate_success(api.run_backfill_offers(absence["id"], COORD), 201)
    offers = validate_success(
        api.list_backfills(ANY, params={"absence_id": absence["id"]})
    )
    assert isinstance(offers, list) and len(offers) == 1
    assert offers[0]["substitute_para_id"] == p3["id"]


def test_backfill_selector_excludes_declined_paras_on_retry(api):
    """PRD §3.6: "Declining moves the offer to `DECLINED`, appends the substitute’s id to the absence’s `declined_para_ids` — excluding them from all future selector runs for that absence — and leaves the absence in `BACKFILL_PENDING`."
    PRD §3.6: "An empty pool creates no offer and moves the absence to `ESCALATED` instead; a later selector run from `ESCALATED` retries the same logic, still excluding paras recorded in `declined_para_ids`."

    Design: Corner/calculations/selector_decline_excludes_and_reranks
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para", hire_date="2025-08-15")
    # Both substitutes idle with same wage; tie broken by earlier hire_date
    p2 = create_para(plan_id, b1, full_name="Early Ed", hire_date="2025-08-01")
    p3 = create_para(plan_id, b1, full_name="Late Lou", hire_date="2025-09-01")
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    cp = validate_success(api.publish_coverage_plan(cp["id"], COORD))
    absence = validate_success(
        api.create_absence(
            create_absence_payload(a1["id"], "2026-05-06", cp["version"]), TEACHER
        ),
        201,
    )

    # First run: earlier-hired idle P2 wins the tie
    validate_success(api.run_backfill_offers(absence["id"], COORD), 201)
    first = validate_success(api.list_backfills(ANY, params={"absence_id": absence["id"]}))
    assert len(first) == 1
    assert first[0]["substitute_para_id"] == p2["id"]

    # P2 declines -> escalated -> retry excludes P2 and picks P3
    validate_success(api.decline_backfill(first[0]["id"], make_para_headers(p2["id"])))
    validate_success(api.escalate_absence(absence["id"], COORD))
    retry = validate_success(api.run_backfill_offers(absence["id"], COORD), 201)
    assert retry["status"] == "BACKFILL_PENDING"
    offered = validate_success(
        api.list_backfills(ANY, params={"absence_id": absence["id"], "status": "OFFERED"})
    )
    assert len(offered) == 1
    assert offered[0]["substitute_para_id"] == p3["id"]


def test_backfill_offer_empty_pool_escalates_without_offer(api):
    """PRD §3.6: "The candidate pool keeps only paras who are `ACTIVE`; who are not the absent assignment’s own para; whose `id` does not appear in the absence’s `declined_para_ids`; who hold the assignment’s `required_qualification_snapshot` current as of the `absence_date` — completed on or before it, `expires_on` null or after it, not revoked, with a snapshot of `NONE` satisfied by everyone; who have no time conflict, meaning no `ACTIVE` assignment sharing the absence weekday whose window violates the travel-buffer overlap rule against the absent assignment’s window and buildings; and whose `weekly_scheduled_minutes` plus the absence’s `absence_minutes` stays within their `contracted_max_weekly_minutes`."
    PRD §3.6: "An empty pool creates no offer and moves the absence to `ESCALATED` instead; a later selector run from `ESCALATED` retries the same logic, still excluding paras recorded in `declined_para_ids`."

    Design: Corner/endpoints/backfill_offer_empty_pool_escalates
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para")
    p2 = create_para(plan_id, b1, full_name="Away Amy", hire_date="2025-09-01")
    # ON_LEAVE paras are excluded from the candidate pool
    validate_success(api.set_para_status(p2["id"], {"status": "ON_LEAVE"}, ADMIN))
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    cp = validate_success(api.publish_coverage_plan(cp["id"], COORD))
    absence = validate_success(
        api.create_absence(
            create_absence_payload(a1["id"], "2026-05-06", cp["version"]), TEACHER
        ),
        201,
    )

    result = validate_success(api.run_backfill_offers(absence["id"], COORD), 201)
    assert result["status"] == "ESCALATED"
    offers = validate_success(api.list_backfills(ANY, params={"absence_id": absence["id"]}))
    assert offers == []


def test_backfill_accept_after_decline_returns_invalid_state(api):
    """PRD §3.6: "The offered para answers personally: both acceptance and decline require `X-User-ID` to equal the offer’s `substitute_para_id`, else `ERR_BACKFILL_NOT_OWN`, and any other backfill transition from a wrong state is `ERR_BACKFILL_INVALID_STATE`."

    Design: Corner/state_machines/backfill_accept_after_decline_returns_invalid_state
    """
    scenario = setup_offered_backfill()
    bf, p2 = scenario["bf"], scenario["p2"]

    declined = validate_success(api.decline_backfill(bf["id"], make_para_headers(p2["id"])))
    assert declined["status"] == "DECLINED"
    resp = api.accept_backfill(bf["id"], make_para_headers(p2["id"]))
    validate_error(resp, ApiErrorId.ERR_BACKFILL_INVALID_STATE)


def test_accepted_backfill_cancel_restores_minutes_and_reopens_absence(api):
    """PRD §3.6: "A coordinator may also cancel a backfill outright: from `OFFERED` the offer simply becomes `CANCELLED`; from `ACCEPTED` the cancellation additionally subtracts the `coverage_minutes` back out of the substitute’s `weekly_scheduled_minutes`, recomputes their `benefit_eligible`, and re-opens the absence by moving it from `COVERED` back to `BACKFILL_PENDING`."
    PRD §3.6: "Acceptance moves the offer from `OFFERED` to `ACCEPTED`, the absence to `COVERED`, adds the `coverage_minutes` to the substitute’s `weekly_scheduled_minutes`, recomputes the substitute’s `benefit_eligible`, and recomputes the coverage posture, which may return to `OPEN`."

    Design: Difficulty/compensating_invariant/substitute_minutes_round_trip_no_drift
    """
    scenario = setup_offered_backfill(set_clock_iso="2026-05-04T00:00:00Z")
    bf, p2, absence = scenario["bf"], scenario["p2"], scenario["absence"]

    accepted = validate_success(api.accept_backfill(bf["id"], make_para_headers(p2["id"])))
    assert accepted["status"] == "ACCEPTED"
    # coverage_minutes = assignment daily minutes = 780 - 480 = 300
    assert accepted["coverage_minutes"] == 300
    para_mid = validate_success(api.get_para(p2["id"], ANY))
    assert para_mid["weekly_scheduled_minutes"] == 300
    absence_mid = validate_success(api.get_absence(absence["id"], ANY))
    assert absence_mid["status"] == "COVERED"

    validate_success(api.cancel_backfill(bf["id"], COORD))
    para_end = validate_success(api.get_para(p2["id"], ANY))
    assert para_end["weekly_scheduled_minutes"] == 0
    absence_end = validate_success(api.get_absence(absence["id"], ANY))
    assert absence_end["status"] == "BACKFILL_PENDING"


def test_absence_create_requires_published_coverage_plan(api):
    """PRD §3.6: "The server resolves the coverage plan from the assignment’s building and the absence date: a missing plan or one still `DRAFT` rejects with `ERR_COVERAGE_PLAN_NOT_PUBLISHED`, while a `LOCKED` or `RECONCILED` plan rejects with `ERR_COVERAGE_PLAN_FROZEN`."

    Design: Corner/endpoints/absence_create_requires_published_plan
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )  # stays DRAFT (v1)
    resp = api.create_absence(
        create_absence_payload(a1["id"], "2026-05-06", cp["version"], "too early"), TEACHER
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_PLAN_NOT_PUBLISHED)


def test_absence_create_on_locked_plan_returns_frozen(api):
    """PRD §3.6: "The server resolves the coverage plan from the assignment’s building and the absence date: a missing plan or one still `DRAFT` rejects with `ERR_COVERAGE_PLAN_NOT_PUBLISHED`, while a `LOCKED` or `RECONCILED` plan rejects with `ERR_COVERAGE_PLAN_FROZEN`."

    Design: Corner/endpoints/absence_create_on_locked_plan_returns_frozen
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-06"), COORD
        ),
        201,
    )
    validate_success(api.publish_coverage_plan(cp["id"], COORD))
    locked = validate_success(api.lock_coverage_plan(cp["id"], COORD))
    # Even with the current version, the FROZEN plan rejects the absence
    resp = api.create_absence(
        create_absence_payload(a1["id"], "2026-05-06", locked["version"], "late report"),
        TEACHER,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_PLAN_FROZEN)


def test_absence_weekday_outside_days_of_week_rejected(api):
    """PRD §3.6: "The weekday of the absence must be one of the assignment’s `days_of_week` (else `ERR_INVALID_DATE_RANGE`)."

    Design: Corner/validations/absence_weekday_not_scheduled_returns_invalid_date_range
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # Mon-Fri
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan_id, b1, "2026-05-03"), COORD
        ),
        201,
    )
    cp = validate_success(api.publish_coverage_plan(cp["id"], COORD))
    # 2026-05-03 is a Sunday; the assignment runs Mon-Fri only
    resp = api.create_absence(
        create_absence_payload(a1["id"], "2026-05-03", cp["version"], "sunday"), TEACHER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_duplicate_coverage_plan_rejected(api):
    """PRD §3.6: "Each school day’s coverage for a building is organized through a coverage plan, created by a `SpecialEdCoordinator` against an `ACTIVE` staffing plan with a `building_id` and the `coverage_date` it governs; the pairing of building and date must be unique, else `ERR_DUPLICATE_COVERAGE_PLAN`."

    Design: Corner/validations/duplicate_coverage_plan_rejected
    """
    plan, building, _ = create_active_plan()
    validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan["id"], building["id"], "2026-05-06"), COORD
        ),
        201,
    )
    resp = api.create_coverage_plan(
        create_coverage_plan_payload(plan["id"], building["id"], "2026-05-06"), COORD
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COVERAGE_PLAN)


def test_reconcile_sweeps_to_terminal_states(api):
    """PRD §3.6: "Reconciliation moves a `LOCKED` plan to `RECONCILED` and sweeps every linked record to a terminal state: linked absences in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` become `UNCOVERED` while a `COVERED` absence stays `COVERED`; linked backfill assignments in `OFFERED` become `CANCELLED` while `ACCEPTED` ones become `COMPLETED` with the substitute’s minutes untouched because the one-off date has already passed; the plan’s `version` increments by one."

    Design: Corner/endpoints/reconcile_sweeps_accepted_backfill_to_completed
    """
    scenario = setup_offered_backfill()
    cp, bf, p2, absence = (
        scenario["cp"], scenario["bf"], scenario["p2"], scenario["absence"],
    )
    accepted = validate_success(api.accept_backfill(bf["id"], make_para_headers(p2["id"])))
    assert accepted["status"] == "ACCEPTED"

    # A COVERED absence is not a gap, so lock succeeds
    locked = validate_success(api.lock_coverage_plan(cp["id"], COORD))
    assert locked["status"] == "LOCKED"
    reconciled = validate_success(api.reconcile_coverage_plan(cp["id"], COORD))
    assert reconciled["status"] == "RECONCILED"
    bf_after = validate_success(api.get_backfill(bf["id"], ANY))
    assert bf_after["status"] == "COMPLETED"
    absence_after = validate_success(api.get_absence(absence["id"], ANY))
    assert absence_after["status"] == "COVERED"


def test_coverage_reopen_blocked_while_absence_open(api):
    """PRD §3.6: "Reopening returns a `PUBLISHED` plan to `DRAFT`, and locking moves a `PUBLISHED` plan to `LOCKED` with `coverage_posture` becoming `FROZEN`; both reopen and lock require the posture to be `OPEN` — no linked absence in `REPORTED`, `BACKFILL_PENDING`, or `ESCALATED` — else `ERR_COVERAGE_GAPS_OPEN`, and both increment the plan’s `version` by one."

    Design: Difficulty/cross_entity_state_dependency/coverage_lock_gated_by_absence_states
    """
    scenario = setup_absence_scenario()
    cp = scenario["cp"]  # PUBLISHED with a linked REPORTED absence
    resp = api.reopen_coverage_plan(cp["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_GAPS_OPEN)
    after = validate_success(api.get_coverage_plan(cp["id"], ANY))
    assert after["status"] == "PUBLISHED"
    assert after["coverage_posture"] == "GAPS_OPEN"


def test_decline_keeps_absence_pending_and_records_exclusion(api):
    """PRD §3.6: "Declining moves the offer to `DECLINED`, appends the substitute’s id to the absence’s `declined_para_ids` — excluding them from all future selector runs for that absence — and leaves the absence in `BACKFILL_PENDING`."

    Design: Difficulty/compensating_invariant/substitute_minutes_round_trip_no_drift
    """
    scenario = setup_offered_backfill(set_clock_iso="2026-05-04T00:00:00Z")
    bf, p2, absence = scenario["bf"], scenario["p2"], scenario["absence"]

    declined = validate_success(api.decline_backfill(bf["id"], make_para_headers(p2["id"])))
    assert declined["status"] == "DECLINED"
    # Declining never touches the substitute's load — minutes stay at zero
    para = validate_success(api.get_para(p2["id"], ANY))
    assert para["weekly_scheduled_minutes"] == 0
    absence_after = validate_success(api.get_absence(absence["id"], ANY))
    assert absence_after["status"] == "BACKFILL_PENDING"
    assert p2["id"] in absence_after["declined_para_ids"]
