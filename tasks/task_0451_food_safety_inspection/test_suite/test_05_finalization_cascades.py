"""Finalization and its downstream cascades: closure creation + suspension, passing-
reinspection resolution + lift + reinstatement, manual closure lift, dismissed-ruling
vacate, derived open_critical_count reconciliation, OCC, and immediate promotion.

Queue A (Difficulty): transitive_cascade, compensating_invariant.
Queue B (Corner): calculations (closure trigger), state_machines (dismissed vacate),
                   cross_cutting_complexity_layers (OCC, derived field, clock default),
                   consistency_model (immediate promotion).
"""
from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_code, create_inspector, create_permitted_establishment,
    setup_completed_inspection, setup_finalized_inspection,
    setup_suspended_via_closed_grade, issue_manual_closure, lift_closure,
    schedule_inspection, start_inspection, complete_inspection, finalize_inspection,
    setup_case_hearing_scheduled, set_clock,
    TEST_USERS, make_inspector_headers,
)

CLERK = TEST_USERS["permit_clerk_headers"]
DIRECTOR = TEST_USERS["health_director_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


# ─── transitive_cascade / tc_finalize_closed_grade_creates_closure_suspends ──
def test_finalize_closed_grade_creates_closure_and_suspends(api):
    """PRD §3.7 (Closure cascade): "If the resulting grade is `CLOSED`, the system creates
    a `ClosureOrder` whose `reason_code` is set per the closure-trigger rule of §3.6,
    moves the establishment from `PERMITTED` to `SUSPENDED`, and sets the establishment's
    `next_reinspection_due_index` to the current clock index plus 14 days."
    PRD §3.6: "if the critical count is at least 3, the reason is `CRITICAL_THRESHOLD`".

    Three uncorrected CRITICAL base 5 (final_score 85, critical_count 3 -> grade CLOSED):
    finalize creates a CRITICAL_THRESHOLD closure and suspends the establishment.

    Design: Difficulty/transitive_cascade/tc_finalize_closed_grade_creates_closure_suspends_establishment
    """
    set_clock(40)
    est, _, finalized, _ = setup_suspended_via_closed_grade(scheduled_index=40)
    assert finalized["grade"] == "CLOSED", f"3 criticals -> CLOSED, got {finalized['grade']}"
    assert est["status"] == "SUSPENDED", f"establishment suspended, got {est['status']}"
    assert est["current_grade"] == "CLOSED", f"promoted current_grade CLOSED, got {est['current_grade']}"
    assert est["active_closure_order_id"] is not None, "active_closure_order_id must be set"

    closure = validate_success(api.get_closure_order(est["active_closure_order_id"], OFFICER), 200)
    assert closure["reason_code"] == "CRITICAL_THRESHOLD", (
        f"3 criticals -> CRITICAL_THRESHOLD, got {closure['reason_code']}")
    assert closure["status"] == "ACTIVE", f"new closure is ACTIVE, got {closure['status']}"


def test_closed_grade_promotes_current_grade_onto_establishment(api):
    """PRD §3.7: "the inspection's `final_score`, `grade`, and `placard_color` are promoted
    onto the establishment's `current_score`, `current_grade`, and `current_placard_color`".

    Design: Difficulty/transitive_cascade/tc_finalize_closed_grade_creates_closure_suspends_establishment
    """
    set_clock(40)
    est, _, finalized, _ = setup_suspended_via_closed_grade(scheduled_index=40)
    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["current_grade"] == "CLOSED", f"expected CLOSED, got {refetched['current_grade']}"
    assert refetched["current_placard_color"] == "RED", (
        f"CLOSED pairs with RED placard, got {refetched['current_placard_color']}")


# ─── transitive_cascade / tc_reinspection_pass_resolves_violations_lifts ─────
def test_passing_reinspection_resolves_lifts_and_reinstates(api):
    """PRD §3.7 (Passing reinspection cascade): "If this inspection's `inspection_type` is
    `REINSPECTION`, its grade is `A` or `B`, and it carries zero critical violations, then
    the system marks the matching prior `OPEN` violations as `RESOLVED`; and if the
    establishment is currently `SUSPENDED`, it lifts the establishment's active closure
    order (moving that closure order to `LIFTED`, clearing `active_closure_order_id`) and
    returns the establishment to `PERMITTED`."

    A SUSPENDED establishment (3 open criticals, active closure) gets a clean REINSPECTION
    finalized (grade A): the criticals resolve, the closure lifts, the establishment is
    reinstated to PERMITTED.

    Design: Difficulty/transitive_cascade/tc_reinspection_pass_resolves_violations_lifts_closure_reinstates
    """
    set_clock(50)
    est, inspector, routine = setup_suspended_via_closed_grade(scheduled_index=50)[:3]
    closure_id = est["active_closure_order_id"]
    # Clean REINSPECTION referencing the CLOSED routine.
    reins = schedule_inspection(est["id"], inspector["id"], 55, "REINSPECTION",
                                reinspection_of_id=routine["id"])
    start_inspection(reins["id"], inspector["id"])
    completed = complete_inspection(reins["id"], inspector["id"])
    finalized = finalize_inspection(reins["id"], inspector["id"], completed["version"])
    assert finalized["grade"] == "A", f"clean reinspection is grade A, got {finalized['grade']}"

    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["status"] == "PERMITTED", f"reinstated to PERMITTED, got {refetched['status']}"
    assert refetched["open_critical_count"] == 0, f"open criticals resolved, got {refetched['open_critical_count']}"
    assert refetched["active_closure_order_id"] is None, "active_closure_order_id cleared to null"
    closure = validate_success(api.get_closure_order(closure_id, OFFICER), 200)
    assert closure["status"] == "LIFTED", f"closure lifted, got {closure['status']}"


def test_passing_reinspection_marks_prior_violations_resolved(api):
    """PRD §3.7: "the system marks the matching prior `OPEN` violations as `RESOLVED`".

    Design: Difficulty/transitive_cascade/tc_reinspection_pass_resolves_violations_lifts_closure_reinstates
    """
    set_clock(50)
    est, inspector, routine = setup_suspended_via_closed_grade(scheduled_index=50)[:3]
    reins = schedule_inspection(est["id"], inspector["id"], 55, "REINSPECTION",
                                reinspection_of_id=routine["id"])
    start_inspection(reins["id"], inspector["id"])
    completed = complete_inspection(reins["id"], inspector["id"])
    finalize_inspection(reins["id"], inspector["id"], completed["version"])

    prior_violations, _ = api.list_violations(CLERK, params={"inspection_id": routine["id"]}).json()["data"], None
    assert len(prior_violations) == 3, f"the routine had 3 violations, got {len(prior_violations)}"
    for v in prior_violations:
        assert v["resolution_status"] == "RESOLVED", (
            f"prior OPEN violation must resolve, got {v['resolution_status']}")


# ─── compensating_invariant / ci_closure_lift_conserves_permitted_state ──────
def test_manual_closure_then_lift_restores_baseline(api):
    """PRD §3.8: "A manually issued closure order begins `ACTIVE`, records its
    `issued_index` at the current clock index, moves the establishment from `PERMITTED` to
    `SUSPENDED`, sets the establishment's `active_closure_order_id`".
    PRD §3.8: "Lifting moves the closure order from `ACTIVE` to `LIFTED`, returns the
    establishment from `SUSPENDED` to `PERMITTED`, and clears the establishment's
    `active_closure_order_id` to null."

    Forward (issue closure) + compensating (lift) leaves status PERMITTED and
    active_closure_order_id null.

    Design: Difficulty/compensating_invariant/ci_closure_lift_conserves_establishment_permitted_state
    """
    set_clock(100)
    est, inspector, finalized = setup_finalized_inspection(scheduled_index=100, violations=[])
    closure = issue_manual_closure(est["id"], finalized["id"], "IMMINENT_HEALTH_HAZARD")
    suspended = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert suspended["status"] == "SUSPENDED", f"closure suspends, got {suspended['status']}"

    lifted = lift_closure(closure["id"])
    assert lifted["status"] == "LIFTED", f"lift -> LIFTED, got {lifted['status']}"
    restored = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert restored["status"] == "PERMITTED", f"restored to PERMITTED, got {restored['status']}"
    assert restored["active_closure_order_id"] is None, "active_closure_order_id restored to null"


def test_closure_lift_returns_active_closure_id_to_null(api):
    """PRD §3.8: "Lifting moves the closure order from `ACTIVE` to `LIFTED`, returns the
    establishment from `SUSPENDED` to `PERMITTED`, and clears the establishment's
    `active_closure_order_id` to null."

    Design: Difficulty/compensating_invariant/ci_closure_lift_conserves_establishment_permitted_state
    """
    set_clock(100)
    est, inspector, finalized = setup_finalized_inspection(scheduled_index=100, violations=[])
    closure = issue_manual_closure(est["id"], finalized["id"], "IMMINENT_HEALTH_HAZARD")
    after_close = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert after_close["active_closure_order_id"] == closure["id"], "active closure id points at the new order"
    lift_closure(closure["id"])
    after_lift = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert after_lift["active_closure_order_id"] is None, "active_closure_order_id cleared"


# ─── compensating_invariant / ci_reinspection_resolution_conserves_count ─────
def test_open_critical_count_returns_to_zero_after_passing_reinspection(api):
    """PRD §3.7: "the establishment's `open_critical_count` is recomputed across all of its
    finalized inspections."
    PRD §3.7: "the system marks the matching prior `OPEN` violations as `RESOLVED`".

    A finalized routine with 2 uncorrected CRITICAL base 5 (final_score 90, grade C via the
    2-critical cap) leaves open_critical_count 2; a clean passing REINSPECTION resolves them
    back to 0.

    Design: Difficulty/compensating_invariant/ci_reinspection_resolution_conserves_open_critical_count
    """
    set_clock(110)
    c1 = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    c2 = create_code("CRITICAL", 5, code="3-501.17", title="Date marking")
    inspector = create_inspector()
    est, _, _ = create_permitted_establishment()
    _, _, routine = setup_finalized_inspection(
        scheduled_index=110, violations=[(c1["id"], False), (c2["id"], False)],
        inspector=inspector, establishment=est)
    assert routine["grade"] == "C", f"final_score 90 capped at C by 2 criticals, got {routine['grade']}"
    after_routine = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert after_routine["open_critical_count"] == 2, f"2 open criticals, got {after_routine['open_critical_count']}"

    reins = schedule_inspection(est["id"], inspector["id"], 112, "REINSPECTION",
                                reinspection_of_id=routine["id"])
    start_inspection(reins["id"], inspector["id"])
    completed = complete_inspection(reins["id"], inspector["id"])
    finalized = finalize_inspection(reins["id"], inspector["id"], completed["version"])
    assert finalized["grade"] == "A", f"clean reinspection is A, got {finalized['grade']}"
    after_reins = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert after_reins["open_critical_count"] == 0, (
        f"open_critical_count conserved back to 0, got {after_reins['open_critical_count']}")


def test_grade_c_routine_does_not_suspend_but_tallies_criticals(api):
    """PRD §3.7: "the establishment's `open_critical_count` is recomputed across all of its
    finalized inspections."

    A finalized ROUTINE with 2 uncorrected CRITICAL base 5 grades C (not CLOSED) and does
    not suspend, but open_critical_count reconciles to 2.

    Design: Difficulty/compensating_invariant/ci_reinspection_resolution_conserves_open_critical_count
    """
    set_clock(110)
    c1 = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    c2 = create_code("CRITICAL", 5, code="3-501.17", title="Date marking")
    _, _, routine = setup_finalized_inspection(
        scheduled_index=110, violations=[(c1["id"], False), (c2["id"], False)])
    est = validate_success(api.get_establishment(routine["establishment_id"], CLERK), 200)
    assert routine["grade"] == "C", f"2-critical cap on band A(90) is C, got {routine['grade']}"
    assert est["status"] == "PERMITTED", f"grade C does not suspend, got {est['status']}"
    assert est["open_critical_count"] == 2, f"open_critical_count 2, got {est['open_critical_count']}"


# ─── Corner / calc_closure_trigger_score_below_sixty ─────────────────────────
def test_closure_reason_grade_c_autoclose_when_score_below_60(api):
    """PRD §3.6: "if the critical count is at least 3, the reason is `CRITICAL_THRESHOLD`;
    otherwise, if the final score is below 60, the reason is `GRADE_C_AUTOCLOSE`".
    PRD §3.6: "a closure override is applied: the grade becomes `CLOSED` if the critical
    count is at least 3, or if the final score is below 60."

    One CRITICAL base 25 + one NON_CRITICAL base 20 (both uncorrected, critical_count 1):
    final_score 55 (<60) -> grade CLOSED, closure reason GRADE_C_AUTOCLOSE (criticals < 3).

    Design: Corner/calculations/calc_closure_trigger_score_below_sixty
    """
    set_clock(130)
    c_big = create_code("CRITICAL", 25, code="5-202.11", title="Sewage")
    nc_big = create_code("NON_CRITICAL", 20, code="6-501.11", title="Floors")
    est, inspector, finalized = setup_finalized_inspection(
        scheduled_index=130, violations=[(c_big["id"], False), (nc_big["id"], False)])
    assert finalized["final_score"] == 55, f"100-(25+20)=55, got {finalized['final_score']}"
    assert finalized["grade"] == "CLOSED", f"score 55 (<60) forces CLOSED, got {finalized['grade']}"
    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["status"] == "SUSPENDED", f"CLOSED grade suspends, got {refetched['status']}"
    closure = validate_success(api.get_closure_order(refetched["active_closure_order_id"], OFFICER), 200)
    assert closure["reason_code"] == "GRADE_C_AUTOCLOSE", (
        f"score cause (criticals<3) -> GRADE_C_AUTOCLOSE, got {closure['reason_code']}")


# ─── Corner / sm_enforcement_dismissed_ruling_vacates_closure_reinstates ─────
def test_dismissed_ruling_vacates_closure_and_reinstates(api):
    """PRD §3.10: "When the ruling is `DISMISSED` and the case names a `closure_order_id`,
    that closure order is moved to `VACATED`, and if the establishment is `SUSPENDED` with
    no other active closure it returns to `PERMITTED`."
    PRD §3.10: "a `DISMISSED` ruling assesses 0 cents".

    A SUSPENDED establishment (manual closure) is contested by an enforcement case ruled
    DISMISSED: the closure VACATES, the establishment reinstates, penalty assessed 0.

    Design: Corner/state_machines/sm_enforcement_dismissed_ruling_vacates_closure_reinstates
    """
    set_clock(200)
    est, inspector, finalized = setup_finalized_inspection(scheduled_index=200, violations=[])
    closure = issue_manual_closure(est["id"], finalized["id"], "IMMINENT_HEALTH_HAZARD")
    est_susp, case = setup_case_hearing_scheduled(
        alleged_penalty_cents=30000, hearing_index=205, open_index=200,
        establishment=est, closure_order_id=closure["id"])
    set_clock(205)
    ruled = validate_success(api.rule_enforcement_case(case["id"], {"ruling": "DISMISSED"}, DIRECTOR), 200)
    assert ruled["assessed_penalty_cents"] == 0, f"DISMISSED assesses 0, got {ruled['assessed_penalty_cents']}"
    vacated = validate_success(api.get_closure_order(closure["id"], OFFICER), 200)
    assert vacated["status"] == "VACATED", f"contested closure VACATED, got {vacated['status']}"
    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["status"] == "PERMITTED", f"establishment reinstated, got {refetched['status']}"


# ─── Corner / occ_finalize_correct_version_succeeds_then_increments ──────────
def test_finalize_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "Before any finalize business logic runs, the server compares
    `expected_inspection_version` against the inspection's current `version`; if they do
    not match, the request is rejected with `ERR_STALE_INSPECTION_VERSION` (HTTP 412)."
    PRD §3.7: "The inspection's `version` is then incremented by one."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_correct_version_succeeds_then_increments
    """
    _, inspector, completed = setup_completed_inspection(scheduled_index=0, violations=[])
    version_pre = completed["version"]
    res = api.finalize_inspection(
        completed["id"], {"expected_inspection_version": version_pre},
        make_inspector_headers(inspector["id"]))
    finalized = validate_success(res, 200)
    assert finalized["status"] == "FINALIZED", f"finalize -> FINALIZED, got {finalized['status']}"
    assert finalized["version"] == version_pre + 1, (
        f"finalize increments version: {version_pre} -> {finalized['version']}")


# ─── Corner / occ_finalize_stale_version_after_reopen_rejected ───────────────
def test_finalize_stale_version_after_reopen_rejected(api):
    """PRD §2.8: "a `COMPLETED` inspection can be reopened to `AMENDING` and re-completed —
    each reopen increments the inspection's `version` — which legitimately supersedes the
    score the finalizing client last read. A finalize still carrying the pre-amendment
    version is therefore stale and must be rejected rather than allowed to overwrite work
    it never saw."

    Design: Corner/cross_cutting_complexity_layers/occ_finalize_stale_version_after_reopen_rejected
    """
    _, inspector, completed = setup_completed_inspection(scheduled_index=0, violations=[])
    stale_version = completed["version"]
    ihdr = make_inspector_headers(inspector["id"])
    validate_success(api.reopen_inspection(completed["id"], ihdr), 200)
    validate_success(api.complete_inspection(completed["id"], ihdr), 200)
    res = api.finalize_inspection(completed["id"], {"expected_inspection_version": stale_version}, ihdr)
    validate_error(res, "ERR_STALE_INSPECTION_VERSION", expected_status=412)
    after = validate_success(api.get_inspection(completed["id"], CLERK), 200)
    assert after["status"] == "COMPLETED", f"rejected finalize leaves status COMPLETED, got {after['status']}"


# ─── Corner / derived_open_critical_count_after_finalize ─────────────────────
def test_open_critical_count_reconciles_to_two_after_finalize(api):
    """PRD §3.7: "the establishment's `open_critical_count` is recomputed across all of its
    finalized inspections."
    PRD §3.3: "`current_score`, the integer score from its most recent finalized inspection".

    Two uncorrected CRITICAL base 5 (final_score 90, grade C via 2-critical cap, not CLOSED):
    open_critical_count reconciles to 2, current_score 90, establishment stays PERMITTED.

    Design: Corner/cross_cutting_complexity_layers/derived_open_critical_count_after_finalize
    """
    set_clock(160)
    c1 = create_code("CRITICAL", 5, code="3-501.16", title="Cold holding")
    c2 = create_code("CRITICAL", 5, code="3-501.17", title="Date marking")
    est, _, finalized = setup_finalized_inspection(
        scheduled_index=160, violations=[(c1["id"], False), (c2["id"], False)])
    assert finalized["grade"] == "C", f"band A(90) capped at C by 2 criticals, got {finalized['grade']}"
    assert finalized["placard_color"] == "YELLOW", f"C pairs with YELLOW, got {finalized['placard_color']}"
    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["open_critical_count"] == 2, f"expected 2, got {refetched['open_critical_count']}"
    assert refetched["current_score"] == 90, f"current_score promoted to 90, got {refetched['current_score']}"
    assert refetched["status"] == "PERMITTED", f"grade C does not suspend, got {refetched['status']}"


# ─── Corner / scheduled_clock_default_index_zero ─────────────────────────────
def test_clock_default_index_is_zero(api, health_director_headers):
    """PRD §2.7: "On server startup the clock is fixed at index 0, which corresponds to
    2026-01-01T00:00:00Z; before any explicit set call the clock reads exactly index 0 and
    never falls back to the host's wall-clock time."

    Design: Corner/cross_cutting_complexity_layers/scheduled_clock_default_index_zero
    """
    res = api.get_clock(health_director_headers)
    data = validate_success(res, 200)
    assert data["current_index"] == 0, f"fresh-server clock reads 0, got {data['current_index']}"


# ─── Corner / immediate_finalize_promotes_grade_in_same_response_chain ───────
def test_finalize_promotes_grade_immediately_on_establishment(api):
    """PRD §2.10: "The system maintains consistency immediately: when a finalized inspection
    changes an establishment's grade, the establishment's promoted score, grade, and placard
    fields, its open-critical tally, its closure linkage, and its status are all reconciled
    within the same operation".
    PRD §3.7: "the inspection's `final_score`, `grade`, and `placard_color` are promoted onto
    the establishment's `current_score`, `current_grade`, and `current_placard_color`".

    A clean ROUTINE finalize (grade A): a subsequent GET shows the promoted current_grade A,
    current_score 100, current_placard_color GREEN with no lag.

    Design: Corner/consistency_model/immediate_finalize_promotes_grade_in_same_response_chain
    """
    est, inspector, finalized = setup_finalized_inspection(scheduled_index=0, violations=[])
    refetched = validate_success(api.get_establishment(est["id"], CLERK), 200)
    assert refetched["current_grade"] == "A", f"promoted current_grade A, got {refetched['current_grade']}"
    assert refetched["current_score"] == 100, f"promoted current_score 100, got {refetched['current_score']}"
    assert refetched["current_placard_color"] == "GREEN", (
        f"promoted current_placard_color GREEN, got {refetched['current_placard_color']}")
