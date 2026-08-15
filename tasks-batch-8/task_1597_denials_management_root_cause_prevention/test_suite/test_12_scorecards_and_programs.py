"""Department scorecards and prevention programs (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_program_payload,
    create_scorecard_payload,
    get_scorecard,
    make_denial,
    make_scorecard,
    setup_catalog,
    triage_denial,
    validate_error,
    validate_paginated,
    validate_success,
)

SCORE_FORMULA_CITE = (
    'PRD §3.8: "Both variants start from 100 and subtract 50 times the recurrence rate, 30 '
    'times the preventable rate, and 20 times the overdue rate, clamping the result into the '
    '0-to-100 range and rounding half-up to two decimal places; the component rates are '
    'never pre-rounded, and any rate with a zero denominator counts as 0.0."'
)


def _two_denial_scorecard(api):
    """CODING scorecard [2026-08-01, 2026-09-01); CLM-201 preventable (25000),
    CLM-202 not preventable (75000). Returns (scorecard_id, payer, code)."""
    catalog = setup_catalog(levels=())
    scorecard = make_scorecard(period_end_date="2026-09-01")
    d1 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                     claim_number="CLM-201", denied_amount_cents=25000,
                     billed_amount_cents=50000)
    triage_denial(d1["id"], preventable_flag=True)
    d2 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                     claim_number="CLM-202", denied_amount_cents=75000,
                     billed_amount_cents=90000, service_date="2026-07-11")
    triage_denial(d2["id"], preventable_flag=False)
    return scorecard["id"]


def test_prevention_score_incidence_variant(api, director_headers):
    """PRD §3.8: "The **incidence** variant is count-weighted: its recurrence rate is
    `recurrence_count` divided by the sum of `verified_fix_count` and `recurrence_count`; its
    preventable rate is `preventable_denial_count` divided by `denial_count`; its overdue
    rate is the overdue task count divided by the open task count."
    PRD §3.8: "The `score_tier` derives from the incidence score with inclusive lower
    boundaries: `EXCELLENT` at 90.00 or higher, `GOOD` at 75.00 or higher, `WATCH` at 60.00
    or higher, and `CRITICAL` below 60.00."

    Design: Difficulty/dual_variant_calc/prevention_score_incidence_vs_financial
    """
    scorecard_id = _two_denial_scorecard(api)
    finalized = validate_success(api.finalize_scorecard(scorecard_id, director_headers))
    assert finalized["status"] == "FINALIZED"
    # 100 - (50*0 + 30*(1/2) + 20*0) = 85.00
    assert finalized["prevention_score_incidence"] == 85.00
    assert finalized["score_tier"] == "GOOD"


def test_prevention_score_financial_variant(api, director_headers):
    """PRD §3.8: "The **financial** variant is dollar-weighted: its recurrence rate is
    `recurrence_linked_denied_cents` divided by the sum of `verified_linked_denied_cents` and
    `recurrence_linked_denied_cents`; its preventable rate is `preventable_denied_cents`
    divided by `denied_cents`; its overdue rate is the summed denied amounts of denials
    linked to overdue tasks divided by the summed denied amounts of denials linked to open
    tasks — so high-dollar denials dominate and the score can diverge from the incidence
    variant when amounts are skewed."

    Design: Difficulty/dual_variant_calc/prevention_score_incidence_vs_financial
    """
    scorecard_id = _two_denial_scorecard(api)
    finalized = validate_success(api.finalize_scorecard(scorecard_id, director_headers))
    # 100 - (50*0 + 30*(25000/100000) + 20*0) = 92.50
    assert finalized["prevention_score_financial"] == 92.50
    assert finalized["prevention_score_financial"] != finalized["prevention_score_incidence"]


def test_scorecard_finalize_locks_counters(api, director_headers, specialist_headers):
    """PRD §3.8: "**Finalization** — from `OPEN` only, else `ERR_SCORECARD_NOT_OPEN` —
    freezes the counters and computes both score variants using the logical clock's date for
    overdue determination."
    PRD §3.8: "A scorecard begins `OPEN` with every counter at zero, and while `OPEN` its
    counters mutate — but only for events whose logical date falls within the period's
    half-open bounds."

    Design: Corner/state_machines/scorecard_finalize_locks_counters
    """
    catalog = setup_catalog(levels=())
    scorecard = make_scorecard()
    d1 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                     claim_number="CLM-2401", denied_amount_cents=100000,
                     billed_amount_cents=120000)
    triage_denial(d1["id"], preventable_flag=False)
    finalized = validate_success(api.finalize_scorecard(scorecard["id"], director_headers))
    assert finalized["status"] == "FINALIZED"
    resp = api.finalize_scorecard(scorecard["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_SCORECARD_NOT_OPEN, expected_status=409)
    d2 = make_denial(catalog["payer"]["id"], catalog["code"]["id"],
                     claim_number="CLM-2402", denied_amount_cents=100000,
                     billed_amount_cents=120000, service_date="2026-07-12",
                     remittance_received_date="2026-08-02")
    triage_denial(d2["id"], preventable_flag=True)
    sc = get_scorecard(scorecard["id"])
    assert sc["denial_count"] == 1, "counters frozen at finalization"
    assert sc["preventable_denial_count"] == 0


def test_scorecard_duplicate_period_rejected(api, director_headers):
    """PRD §3.8: "One scorecard per department and period start is allowed: a duplicate pair
    fails with `ERR_DUPLICATE_SCORECARD_PERIOD`."

    Design: Corner/errors/scorecard_duplicate_period_rejected
    """
    make_scorecard(period_end_date="2026-09-01")
    resp = api.create_department_scorecard(
        create_scorecard_payload("CODING", period_start_date="2026-08-01",
                                 period_end_date="2026-10-01"),
        director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SCORECARD_PERIOD, expected_status=409)


def test_program_window_touching_endpoints_conflict(api, director_headers):
    """PRD §3.8: "Program windows are closed intervals, and per department they must not
    overlap — unlike appeal policies, touching endpoints do conflict, so a new program whose
    `start_date` equals an existing program's `end_date` is already an overlap and fails with
    `ERR_PROGRAM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/program_window_closed_interval_touch_conflict
    """
    validate_success(
        api.create_prevention_program(
            create_program_payload(name="Coder Roundtables Q1", start_date="2026-03-01",
                                   end_date="2026-05-31", target_reduction_pct=10),
            director_headers,
        ),
        expected_status=201,
    )
    resp = api.create_prevention_program(
        create_program_payload(name="Touching Window", start_date="2026-05-31",
                               end_date="2026-08-31", target_reduction_pct=15),
        director_headers,
    )
    validate_error(resp, ApiErrorId.ERR_PROGRAM_WINDOW_OVERLAP, expected_status=409)


def test_program_window_first_clear_day_succeeds(api, director_headers):
    """PRD §3.8: "Program windows are closed intervals, and per department they must not
    overlap — unlike appeal policies, touching endpoints do conflict, so a new program whose
    `start_date` equals an existing program's `end_date` is already an overlap and fails with
    `ERR_PROGRAM_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/program_window_closed_interval_touch_conflict
    """
    validate_success(
        api.create_prevention_program(
            create_program_payload(name="Coder Roundtables Q1", start_date="2026-03-01",
                                   end_date="2026-05-31", target_reduction_pct=10),
            director_headers,
        ),
        expected_status=201,
    )
    created = validate_success(
        api.create_prevention_program(
            create_program_payload(name="Coder Roundtables Q2", start_date="2026-06-01",
                                   end_date="2026-08-31", target_reduction_pct=15),
            director_headers,
        ),
        expected_status=201,
    )
    assert created["status"] == "PLANNED"
    rows, meta = validate_paginated(
        api.list_prevention_programs(director_headers, params={"department": "CODING"})
    )
    assert meta["total_count"] == 2


def test_program_lifecycle_gating(api, director_headers):
    """PRD §3.8: "A program begins `PLANNED`, the director activates it `PLANNED` → `ACTIVE`,
    and later completes it `ACTIVE` → `COMPLETED`; a transition from any other state is
    `ERR_INVALID_STATE`, and `COMPLETED` is terminal."

    Design: Corner/state_machines/program_lifecycle_gating
    """
    program = validate_success(
        api.create_prevention_program(create_program_payload(), director_headers),
        expected_status=201,
    )
    assert program["status"] == "PLANNED"
    resp = api.complete_program(program["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    activated = validate_success(api.activate_program(program["id"], director_headers))
    assert activated["status"] == "ACTIVE"
    completed = validate_success(api.complete_program(program["id"], director_headers))
    assert completed["status"] == "COMPLETED"
