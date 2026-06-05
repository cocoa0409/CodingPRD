"""Validation precedence, cross-entity state dependencies, temporal/interval edges,
and compensating invariants (queue A)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_submitted_application,
    setup_determined_application,
    setup_enrollment,
    create_household_with_primary,
    create_application,
    create_sep_request,
    household_version,
    make_applicant_headers,
    set_clock,
    register_benchmark_plan,
    register_plan,
    create_enrollment,
    submit_application,
    determine_application,
)
from test_helpers.api_client import api_client


# ───────────── priority_pair_validation_conflict ─────────────

def test_invalid_state_beats_aptc_exceeds_max(api):
    """PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."
    PRD §3.8: "Only after these structural checks do the domain-specific business rules apply: the single-`PRIMARY` rule (`ERR_DUPLICATE_PRIMARY`), the plan area-and-year match (`ERR_PLAN_AREA_MISMATCH`), the SEP filing-window check (`ERR_SEP_WINDOW_CLOSED`), the SEP-approval-before-submit check (`ERR_SEP_NOT_APPROVED`), the benchmark-plan requirement (`ERR_NO_BENCHMARK_PLAN`), the overlapping-coverage check (`ERR_OVERLAPPING_COVERAGE`), and the elected-APTC ceiling (`ERR_APTC_EXCEEDS_MAX`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_aptc_exceeds_max
    """
    # Application is SUBMITTED (not DETERMINED): the create-enrollment state check fails
    # before the APTC ceiling check even though elected APTC is wildly above any max.
    ctx = setup_submitted_application("app-9", income_cents=3_000_000, benchmark_gross=50_000)
    v = household_version(ctx["household"]["id"], "app-9")
    res = api.create_enrollment(
        {"application_id": ctx["application"]["id"], "plan_id": ctx["plan"]["id"],
         "elected_aptc_monthly_cents": 999999, "expected_household_version": v},
        make_applicant_headers("app-9"))
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_invalid_state_enrollment_on_draft_application(api):
    """PRD §3.5: "The application must currently be `DETERMINED`."
    PRD §3.8: "For a state-transition action, the system then confirms the target is in a state from which the transition is defined (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_aptc_exceeds_max
    """
    # Application still DRAFT (never submitted): enrollment create fails ERR_INVALID_STATE.
    set_clock("2026-01-10T00:00:00Z")
    plan = register_benchmark_plan()
    hh, _ = create_household_with_primary("app-9b", income_cents=3_000_000)
    app = create_application(hh["id"], "app-9b", enrollment_window="OEP")
    v = household_version(hh["id"], "app-9b")
    res = api.create_enrollment(
        {"application_id": app["id"], "plan_id": plan["id"],
         "elected_aptc_monthly_cents": 999999, "expected_household_version": v},
        make_applicant_headers("app-9b"))
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_sep_window_closed_on_approve(api):
    """PRD §3.2: "when the current clock date falls on or before the request's `window_close_date` — that is, the filing window is still open. If approval is attempted after the window has closed, it is rejected with `ERR_SEP_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/sep_window_closed_beats_sep_not_approved
    """
    # event 2026-03-01 -> window_close 2026-04-30; approve at 2026-05-01 (past close).
    set_clock("2026-03-02T00:00:00Z")
    hh, _ = create_household_with_primary("app-10", income_cents=3_000_000)
    app = create_application(hh["id"], "app-10", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "app-10",
                             qualifying_event_type="LOSS_OF_COVERAGE", event_date="2026-03-01")
    set_clock("2026-05-01T00:00:00Z")
    res = api.approve_sep_request(sep["id"], __admin())
    validate_error(res, "ERR_SEP_WINDOW_CLOSED")
    assert res.status_code == 409


def test_sep_window_open_on_exact_boundary_approves(api):
    """PRD §3.2: "the system computes its `window_close_date`: the last date on which the applicant may still file under this SEP, equal to the `event_date` plus 60 calendar days."
    PRD §3.2: "Approval moves the request from `PENDING` to `APPROVED` and is permitted only when the request is still `PENDING`, when the linked application is still in `DRAFT` (the SEP must be resolved before the application is submitted), and when the current clock date falls on or before the request's `window_close_date` — that is, the filing window is still open."

    Design: Difficulty/priority_pair_validation_conflict/sep_window_closed_beats_sep_not_approved
    """
    # event 2026-03-01 + 60 days = 2026-04-30; approve ON 2026-04-30 (inclusive) succeeds.
    set_clock("2026-03-02T00:00:00Z")
    hh, _ = create_household_with_primary("app-10b", income_cents=3_000_000)
    app = create_application(hh["id"], "app-10b", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "app-10b",
                             qualifying_event_type="LOSS_OF_COVERAGE", event_date="2026-03-01")
    assert sep["window_close_date"] == "2026-04-30"
    set_clock("2026-04-30T00:00:00Z")
    approved = validate_success(api.approve_sep_request(sep["id"], __admin()), 200)
    assert approved["status"] == "APPROVED"


# ───────────── boundary_precision: aptc elected vs max ─────────────

def test_elected_aptc_one_cent_over_max_rejected(api):
    """PRD §3.5: "The elected APTC must not exceed the determination's `max_aptc_monthly_cents`; an election above that ceiling is rejected with `ERR_APTC_EXCEEDS_MAX` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/aptc_elected_exceeds_max_by_one_cent
    """
    ctx = setup_determined_application("app-12", income_cents=3_000_000, benchmark_gross=50_000)
    # max_aptc = 45000; electing 45001 (max + 1) rejected.
    v = household_version(ctx["household"]["id"], "app-12")
    res = api.create_enrollment(
        {"application_id": ctx["application"]["id"], "plan_id": ctx["plan"]["id"],
         "elected_aptc_monthly_cents": 45001, "expected_household_version": v},
        make_applicant_headers("app-12"))
    validate_error(res, "ERR_APTC_EXCEEDS_MAX")
    assert res.status_code == 409


def test_elected_aptc_exactly_at_max_succeeds(api):
    """PRD §3.5: "The elected APTC must not exceed the determination's `max_aptc_monthly_cents`; an election above that ceiling is rejected with `ERR_APTC_EXCEEDS_MAX` (HTTP 409)."
    PRD §3.5: "The **applied APTC** in `applied_aptc_monthly_cents` is the smallest of three figures: the elected amount, the determination's `max_aptc_monthly_cents`, and the plan's `gross_premium_cents`."

    Design: Difficulty/boundary_precision_check/aptc_elected_exceeds_max_by_one_cent
    """
    ctx = setup_determined_application("app-12b", income_cents=3_000_000, benchmark_gross=50_000)
    enr = create_enrollment(ctx["application"]["id"], ctx["household"]["id"],
                            ctx["plan"]["id"], "app-12b", elected_aptc_monthly_cents=45_000)
    assert enr["applied_aptc_monthly_cents"] == 45000
    assert enr["net_premium_monthly_cents"] == 5000


# ───────────── cross_entity_state_dependency ─────────────

def test_submit_sep_application_without_approved_sep_rejected(api):
    """PRD §3.2: "for `SEP`-window applications only — when an `APPROVED` `SepRequest` exists for this application; an `OEP` application skips that SEP precondition entirely. A `SEP` application submitted without an approved request is rejected with `ERR_SEP_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_approved_sep
    """
    set_clock("2026-06-18T00:00:00Z")
    hh, _ = create_household_with_primary("app-13", income_cents=3_000_000)
    app = create_application(hh["id"], "app-13", enrollment_window="SEP")
    # SepRequest filed but left PENDING (not approved).
    create_sep_request(app["id"], "app-13", qualifying_event_type="BIRTH",
                       event_date="2026-06-16")
    v = household_version(hh["id"], "app-13")
    res = api.submit_application(app["id"], {"expected_household_version": v},
                                 make_applicant_headers("app-13"))
    validate_error(res, "ERR_SEP_NOT_APPROVED")
    assert res.status_code == 409


def test_submit_sep_application_succeeds_after_sep_approved(api):
    """PRD §3.2: "Submission is permitted only when the application is currently `DRAFT`, when the referenced household has a `countable_size` of at least 1 (meaning at least one `PRIMARY` member exists), and — for `SEP`-window applications only — when an `APPROVED` `SepRequest` exists for this application; an `OEP` application skips that SEP precondition entirely."
    PRD §3.2: "On a successful submit the server sets `submitted_at` to the current UTC clock, sets the application's `sep_request_id` to the `id` of the approved `SepRequest` when the window is `SEP`, increments the household's `version` by 1, and increments the application's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/application_submit_requires_approved_sep
    """
    set_clock("2026-06-18T00:00:00Z")
    register_benchmark_plan()
    hh, _ = create_household_with_primary("app-13b", income_cents=3_000_000)
    app = create_application(hh["id"], "app-13b", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "app-13b", qualifying_event_type="BIRTH",
                             event_date="2026-06-16")
    from test_helpers import approve_sep_request
    approve_sep_request(sep["id"])
    v = household_version(hh["id"], "app-13b")
    submitted = validate_success(
        api.submit_application(app["id"], {"expected_household_version": v},
                               make_applicant_headers("app-13b")), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["sep_request_id"] == sep["id"]


def test_effectuate_requires_paid_binder(api):
    """PRD §3.6: "effectuation is permitted only when `lifecycle_status` is `PENDING_EFFECTUATION` and is gated on the payment dimension — the binder must already be paid, so `payment_status` must be `PAID` at that moment."

    Design: Difficulty/cross_entity_state_dependency/enrollment_effectuate_requires_paid_binder
    """
    ctx = setup_enrollment("app-14", income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                           benchmark_gross=50_000)
    # payment_status still AWAITING_BINDER -> effectuate rejected.
    res = api.effectuate(ctx["enrollment"]["id"], __admin())
    validate_error(res, "ERR_INVALID_STATE")
    assert res.status_code == 409


def test_effectuate_succeeds_once_binder_paid(api):
    """PRD §3.6: "A `MarketplaceAdmin` effectuates coverage, moving `lifecycle_status` from `PENDING_EFFECTUATION` to `ACTIVE`; effectuation is permitted only when `lifecycle_status` is `PENDING_EFFECTUATION` and is gated on the payment dimension — the binder must already be paid, so `payment_status` must be `PAID` at that moment."

    Design: Difficulty/cross_entity_state_dependency/enrollment_effectuate_requires_paid_binder
    """
    ctx = setup_enrollment("app-14b", income_cents=3_000_000, elected_aptc_monthly_cents=45_000,
                           benchmark_gross=50_000)
    h = make_applicant_headers("app-14b")
    validate_success(api.pay_binder(ctx["enrollment"]["id"], h), 200)
    active = validate_success(api.effectuate(ctx["enrollment"]["id"], __admin()), 200)
    assert active["lifecycle_status"] == "ACTIVE"
    assert active["payment_status"] == "PAID"


# ───────────── resource_temporal_overlap ─────────────

def test_second_overlapping_enrollment_same_year_rejected(api):
    """PRD §3.5: "The household must have no existing non-terminated enrollment — that is, no enrollment whose `lifecycle_status` is `PENDING_EFFECTUATION` or `ACTIVE` — whose coverage interval overlaps the new one for the same coverage year; coverage intervals run from the effective date to the end of the coverage year and are closed on both ends, so any shared day collides, and a collision is rejected with `ERR_OVERLAPPING_COVERAGE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/second_enrollment_overlaps_active_coverage_same_year
    """
    set_clock("2026-01-10T00:00:00Z")
    silver = register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000)
    gold = register_plan(rating_area="RA01", coverage_year=2026, metal_tier="GOLD",
                         gross_premium_cents=60_000)
    hh, _ = create_household_with_primary("app-15", income_cents=3_000_000)
    # first enrollment (full-year 2026 coverage)
    app1 = create_application(hh["id"], "app-15", enrollment_window="OEP")
    submit_application(app1["id"], hh["id"], "app-15")
    determine_application(app1["id"])
    create_enrollment(app1["id"], hh["id"], silver["id"], "app-15",
                      elected_aptc_monthly_cents=45_000)
    # second determined application for the same household
    app2 = create_application(hh["id"], "app-15", enrollment_window="OEP")
    submit_application(app2["id"], hh["id"], "app-15")
    determine_application(app2["id"])
    v = household_version(hh["id"], "app-15")
    res = api.create_enrollment(
        {"application_id": app2["id"], "plan_id": gold["id"],
         "elected_aptc_monthly_cents": 0, "expected_household_version": v},
        make_applicant_headers("app-15"))
    validate_error(res, "ERR_OVERLAPPING_COVERAGE")
    assert res.status_code == 409


def test_terminated_enrollment_does_not_block_new_coverage(api):
    """PRD §3.5: "The household must have no existing non-terminated enrollment — that is, no enrollment whose `lifecycle_status` is `PENDING_EFFECTUATION` or `ACTIVE` — whose coverage interval overlaps the new one for the same coverage year; coverage intervals run from the effective date to the end of the coverage year and are closed on both ends, so any shared day collides, and a collision is rejected with `ERR_OVERLAPPING_COVERAGE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/second_enrollment_overlaps_active_coverage_same_year
    """
    set_clock("2026-01-10T00:00:00Z")
    silver = register_benchmark_plan(rating_area="RA01", coverage_year=2026, gross_premium_cents=50_000)
    gold = register_plan(rating_area="RA01", coverage_year=2026, metal_tier="GOLD",
                         gross_premium_cents=60_000)
    hh, _ = create_household_with_primary("app-15b", income_cents=3_000_000)
    app1 = create_application(hh["id"], "app-15b", enrollment_window="OEP")
    submit_application(app1["id"], hh["id"], "app-15b")
    determine_application(app1["id"])
    enr1 = create_enrollment(app1["id"], hh["id"], silver["id"], "app-15b",
                             elected_aptc_monthly_cents=45_000)
    # terminate the first enrollment -> no non-terminated enrollment remains
    validate_success(api.terminate_enrollment(enr1["id"], make_applicant_headers("app-15b")), 200)
    app2 = create_application(hh["id"], "app-15b", enrollment_window="OEP")
    submit_application(app2["id"], hh["id"], "app-15b")
    determine_application(app2["id"])
    v = household_version(hh["id"], "app-15b")
    enr2 = validate_success(api.create_enrollment(
        {"application_id": app2["id"], "plan_id": gold["id"],
         "elected_aptc_monthly_cents": 0, "expected_household_version": v},
        make_applicant_headers("app-15b")), 201)
    assert enr2["lifecycle_status"] == "PENDING_EFFECTUATION"


def test_sep_filing_window_closed_inclusive_boundary(api):
    """PRD §3.2: "the system computes its `window_close_date`: the last date on which the applicant may still file under this SEP, equal to the `event_date` plus 60 calendar days."
    PRD §3.2: "If approval is attempted after the window has closed, it is rejected with `ERR_SEP_WINDOW_CLOSED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/sep_filing_window_closed_inclusive_boundary
    """
    # event 2026-04-01 + 60 = 2026-05-31; approve at 2026-06-01 (one day past) -> rejected.
    set_clock("2026-04-02T00:00:00Z")
    hh, _ = create_household_with_primary("app-16", income_cents=3_000_000)
    app = create_application(hh["id"], "app-16", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "app-16",
                             qualifying_event_type="MARRIAGE", event_date="2026-04-01")
    assert sep["window_close_date"] == "2026-05-31"
    set_clock("2026-06-01T00:00:00Z")
    res = api.approve_sep_request(sep["id"], __admin())
    validate_error(res, "ERR_SEP_WINDOW_CLOSED")
    assert res.status_code == 409


def test_sep_window_close_date_is_event_plus_sixty_days(api):
    """PRD §3.2: "the system computes its `window_close_date`: the last date on which the applicant may still file under this SEP, equal to the `event_date` plus 60 calendar days."

    Design: Difficulty/resource_temporal_overlap/sep_filing_window_closed_inclusive_boundary
    """
    set_clock("2026-04-02T00:00:00Z")
    hh, _ = create_household_with_primary("app-16b", income_cents=3_000_000)
    app = create_application(hh["id"], "app-16b", enrollment_window="SEP")
    sep = create_sep_request(app["id"], "app-16b",
                             qualifying_event_type="MARRIAGE", event_date="2026-04-01")
    # 2026-04-01 + 60 days = 2026-05-31
    assert sep["window_close_date"] == "2026-05-31"


# ───────────── compensating_invariant ─────────────

def test_determine_then_reopen_leaves_zero_determinations(api):
    """PRD §3.3: "creates an **EligibilityDetermination** linked to the `application_id` (one active determination per application)."
    PRD §3.3: "Reopening deletes the application's `EligibilityDetermination` as a compensating action, clears `submitted_at` back to null, and increments the application's `version`."

    Design: Difficulty/compensating_invariant/reopen_compensates_determination_count_invariant
    """
    ctx = setup_determined_application("app-17", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-17")
    # exactly one determination after determine
    dets = validate_success(api.get_determination(ctx["application"]["id"], h), 200)
    assert len(dets) == 1
    reopened = validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    assert reopened["status"] == "DRAFT"
    dets_after = validate_success(api.get_determination(ctx["application"]["id"], h), 200)
    assert isinstance(dets_after, list) and len(dets_after) == 0


def test_redetermine_after_reopen_creates_single_determination(api):
    """PRD §3.3: "creates an **EligibilityDetermination** linked to the `application_id` (one active determination per application)."
    PRD §3.3: "This branching-with-revert path is what forces a fresh determination after
    a member's income is corrected."

    Design: Difficulty/compensating_invariant/reopen_compensates_determination_count_invariant
    """
    ctx = setup_determined_application("app-17b", income_cents=3_000_000, benchmark_gross=50_000)
    h = make_applicant_headers("app-17b")
    validate_success(api.reopen_application(ctx["application"]["id"], h), 200)
    # re-submit and re-determine: the count returns to exactly one, no orphan drift
    submit_application(ctx["application"]["id"], ctx["household"]["id"], "app-17b")
    determine_application(ctx["application"]["id"])
    dets = validate_success(api.get_determination(ctx["application"]["id"], h), 200)
    assert len(dets) == 1


def test_magi_conserved_after_raise_then_lower_member_income(api):
    """PRD §3.1: "The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs."
    PRD §2.5: "all of which begin at 0 before any member exists and are recomputed every
    time a member is added, updated, or removed."

    Design: Difficulty/compensating_invariant/magi_recompute_conserves_sum_of_member_countable_income
    """
    hh, mem = create_household_with_primary("app-18", income_cents=3_000_000)
    h = make_applicant_headers("app-18")
    validate_success(api.update_member(hh["id"], mem["id"],
                                       {"annual_income_cents": 3_500_000}, h), 200)
    # compensating edit back to original
    restored = validate_success(api.update_member(hh["id"], mem["id"],
                                                   {"annual_income_cents": 3_000_000}, h), 200)
    got = validate_success(api.get_household(hh["id"], h), 200)
    assert got["household_magi_cents"] == 3000000
    assert restored["annual_income_cents"] == 3000000


def test_magi_equals_member_sum_at_intermediate_step(api):
    """PRD §3.1: "The household's `household_magi_cents` is the sum of `annual_income_cents` across the countable members; because all operands are integer cents, no rounding occurs."

    Design: Difficulty/compensating_invariant/magi_recompute_conserves_sum_of_member_countable_income
    """
    hh, mem = create_household_with_primary("app-18b", income_cents=3_000_000)
    h = make_applicant_headers("app-18b")
    raised = validate_success(api.update_member(hh["id"], mem["id"],
                                                {"annual_income_cents": 3_500_000}, h), 200)
    got = validate_success(api.get_household(hh["id"], h), 200)
    # after the raise (before any compensation), MAGI tracks the single countable member
    assert raised["annual_income_cents"] == 3500000
    assert got["household_magi_cents"] == 3500000


def __admin():
    from test_helpers import TEST_USERS
    return TEST_USERS["admin_headers"]
