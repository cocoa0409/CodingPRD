"""Outbreak claims: the rolling 168-hour threshold (boundary 2 vs 3), auto-open
emergency pool debit, the ACTIVE/CONTAINED/ACTIVE cycle, manual lifecycle error
matrix, and unresolved-case close gating (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_outbreak_investigation,
    assert_timestamp_prefix,
    create_confirmed_case,
    get_pool_by_term,
    list_outbreaks,
    make_pool,
    make_provider,
    set_clock,
    setup_active_outbreak,
    validate_error,
    validate_success,
)

MEASLES = "MEASLES"


def _confirm_three_at(clock, provider, refs, times, disease_code=MEASLES):
    """Confirm one case per (ref, time) at the already-set clock."""
    cases = []
    for ref, (start, end) in zip(refs, times):
        cases.append(create_confirmed_case(
            provider["id"], ref, f"Case {ref}", start, end,
            disease_code=disease_code,
        ))
    return cases


# ---------------------------------------------------------------------------
# Depth probes: rolling 168h window drives auto-open, not the ISO week
# ---------------------------------------------------------------------------

def test_two_confirms_inside_rolling_window_open_nothing(api):
    """PRD §3.7: "the system counts every disease case sharing the same
    `disease_code` whose status is `CONFIRMED` or `REPORTED` — `SUSPECTED` and
    `RESOLVED` cases are excluded — and whose `confirmed_at` falls within the
    trailing 168 hours up to and including the current moment, both bounds
    inclusive. When that count reaches three or more, one of two cascades
    fires." A count of two stays below the threshold, so nothing opens.

    Design: Difficulty/dual_variant_calc/outbreak_rolling_vs_calendar_week_count
    """
    set_clock("2026-05-11T22:00:00Z")
    provider = make_provider("Dr C")
    create_confirmed_case(provider["id"], "S201", "Case One",
                          "2026-05-11T23:00:00Z", "2026-05-11T23:30:00Z")
    set_clock("2026-05-17T00:30:00Z")
    create_confirmed_case(provider["id"], "S202", "Case Two",
                          "2026-05-17T01:00:00Z", "2026-05-17T01:30:00Z")

    investigations = list_outbreaks(MEASLES)
    assert investigations == [], (
        f"two confirmations (< 3) must not open an investigation, got {investigations}"
    )


def test_third_confirm_auto_opens_under_rolling_not_iso_week(api):
    """PRD §3.7: "When that count reaches three or more ... a new
    `OutbreakInvestigation` is created in `ACTIVE` with `opened_at` stamped and
    `opened_case_count` set to the triggering count".
    PRD §3.7: "A separate **ISO calendar-week** count ... is maintained purely
    as a surveillance reporting metric and never drives auto-open or
    auto-reopen". Confirms at Mon 22:00, Sun 00:30, and next Mon 00:30 fall
    inside one trailing 168-hour window (count 3) yet only one lands in the ISO
    week of the final confirm — the auto-open proves the rolling variant drives.

    Design: Difficulty/dual_variant_calc/outbreak_rolling_vs_calendar_week_count
    """
    set_clock("2026-05-11T22:00:00Z")
    provider = make_provider("Dr C")
    create_confirmed_case(provider["id"], "S201", "Case One",
                          "2026-05-11T23:00:00Z", "2026-05-11T23:30:00Z")
    set_clock("2026-05-17T00:30:00Z")
    create_confirmed_case(provider["id"], "S202", "Case Two",
                          "2026-05-17T01:00:00Z", "2026-05-17T01:30:00Z")
    set_clock("2026-05-18T00:30:00Z")
    create_confirmed_case(provider["id"], "S203", "Case Three",
                          "2026-05-18T01:00:00Z", "2026-05-18T01:30:00Z")

    investigations = list_outbreaks(MEASLES)
    assert len(investigations) == 1, (
        f"rolling window [2026-05-11T00:30, 2026-05-18T00:30] holds all three "
        f"confirms; expected exactly one investigation, got {investigations}"
    )
    investigation = investigations[0]
    assert_outbreak_investigation(investigation)
    assert investigation["status"] == "ACTIVE"
    assert investigation["opened_case_count"] == 3
    assert_timestamp_prefix(investigation["opened_at"], "2026-05-18T00:30",
                            label="opened_at")


# ---------------------------------------------------------------------------
# Depth probes: exactly three is the auto-open boundary
# ---------------------------------------------------------------------------

def test_two_confirmed_cases_is_below_threshold(api):
    """PRD §3.7: "When that count reaches three or more, one of two cascades
    fires." Two confirmed cases do not reach the threshold, so no investigation
    exists.

    Design: Difficulty/boundary_precision_check/outbreak_third_case_is_the_boundary
    """
    set_clock("2026-05-11T12:00:00Z")
    provider = make_provider("Dr N")
    _confirm_three_at(
        None, provider, ["S701", "S702"],
        [("2026-05-11T13:00:00Z", "2026-05-11T13:30:00Z"),
         ("2026-05-11T14:00:00Z", "2026-05-11T14:30:00Z")],
    )
    assert list_outbreaks(MEASLES) == []


def test_third_confirmed_case_crosses_threshold(api):
    """PRD §3.7: "When that count reaches three or more ... a new
    `OutbreakInvestigation` is created in `ACTIVE` with `opened_at` stamped and
    `opened_case_count` set to the triggering count".

    Design: Difficulty/boundary_precision_check/outbreak_third_case_is_the_boundary
    """
    set_clock("2026-05-11T12:00:00Z")
    provider = make_provider("Dr N")
    _confirm_three_at(
        None, provider, ["S701", "S702", "S703"],
        [("2026-05-11T13:00:00Z", "2026-05-11T13:30:00Z"),
         ("2026-05-11T14:00:00Z", "2026-05-11T14:30:00Z"),
         ("2026-05-11T15:00:00Z", "2026-05-11T15:30:00Z")],
    )
    investigations = list_outbreaks(MEASLES)
    assert len(investigations) == 1
    assert investigations[0]["status"] == "ACTIVE"
    assert investigations[0]["opened_case_count"] == 3, (
        "the third confirm crosses the >= 3 boundary"
    )


# ---------------------------------------------------------------------------
# Depth probes: cyclic state machine ACTIVE -> CONTAINED -> ACTIVE -> CLOSED
# ---------------------------------------------------------------------------

def test_outbreak_contain_reopen_cycle_revisits_active(api, health_admin_headers):
    """PRD §3.7: "An `ACTIVE` investigation may be marked contained
    (`ACTIVE → CONTAINED`...)" and "A `CONTAINED` investigation may be reopened
    manually (`CONTAINED → ACTIVE`)" — the cycle revisits ACTIVE, unlike a
    linear pipeline.

    Design: Difficulty/non_linear_state_machine/outbreak_contain_reopen_cycle
    """
    _, investigation, _ = setup_active_outbreak()
    oid = investigation["id"]

    contained = validate_success(api.contain_outbreak(oid, health_admin_headers), 200)
    assert contained["status"] == "CONTAINED"

    reopened = validate_success(api.reopen_outbreak(oid, health_admin_headers), 200)
    assert reopened["status"] == "ACTIVE", "CONTAINED -> ACTIVE revisits the state"

    contained_again = validate_success(
        api.contain_outbreak(oid, health_admin_headers), 200
    )
    assert contained_again["status"] == "CONTAINED", (
        "second pass through the same transition must succeed identically"
    )


def test_outbreak_closes_after_all_cases_resolved(api, health_admin_headers,
                                                  clinician_headers):
    """PRD §3.7: "a `CONTAINED` investigation may be closed (`CONTAINED →
    CLOSED`) only when no disease case for its `disease_code` remains in any of
    `SUSPECTED`, `CONFIRMED`, or `REPORTED`".
    PRD §3.7: "a `Clinician` may resolve a case from either `CONFIRMED` or
    `REPORTED`".

    Design: Difficulty/non_linear_state_machine/outbreak_contain_reopen_cycle
    """
    _, investigation, cases = setup_active_outbreak()
    oid = investigation["id"]
    validate_success(api.contain_outbreak(oid, health_admin_headers), 200)
    for case in cases:
        resolved = validate_success(
            api.resolve_disease_case(case["id"], clinician_headers), 200
        )
        assert resolved["status"] == "RESOLVED"
    closed = validate_success(api.close_outbreak(oid, health_admin_headers), 200)
    assert closed["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: manual lifecycle error matrix + unresolved close
# ---------------------------------------------------------------------------

def test_outbreak_invalid_transitions_and_unresolved_close(api, health_admin_headers,
                                                           clinician_headers):
    """PRD §3.7: "both the manual reopen and the close action require
    `CONTAINED` status (`ERR_OUTBREAK_NOT_CONTAINED`)".
    PRD §3.7: "An `ACTIVE` investigation may be marked contained
    (`ACTIVE → CONTAINED`; anything else is rejected with
    `ERR_OUTBREAK_NOT_ACTIVE`)".
    PRD §3.7: "closing over unresolved cases is rejected with
    `ERR_OUTBREAK_UNRESOLVED_CASES`."

    Design: Corner/state_machines/outbreak_invalid_transitions_and_unresolved_close
    """
    _, investigation, cases = setup_active_outbreak()
    oid = investigation["id"]

    # Close requires CONTAINED; the investigation is ACTIVE.
    res1 = api.close_outbreak(oid, health_admin_headers)
    validate_error(res1, ApiErrorId.ERR_OUTBREAK_NOT_CONTAINED, expected_status=409)

    contained = validate_success(api.contain_outbreak(oid, health_admin_headers), 200)
    assert contained["status"] == "CONTAINED"

    # Contain requires ACTIVE.
    res2 = api.contain_outbreak(oid, health_admin_headers)
    validate_error(res2, ApiErrorId.ERR_OUTBREAK_NOT_ACTIVE, expected_status=409)

    # Three CONFIRMED cases remain unresolved.
    res3 = api.close_outbreak(oid, health_admin_headers)
    validate_error(res3, ApiErrorId.ERR_OUTBREAK_UNRESOLVED_CASES, expected_status=409)

    # Resolving every case unlocks the close.
    for case in cases:
        validate_success(api.resolve_disease_case(case["id"], clinician_headers), 200)
    closed = validate_success(api.close_outbreak(oid, health_admin_headers), 200)
    assert closed["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: auto-open debits the emergency pool exactly once
# ---------------------------------------------------------------------------

def test_outbreak_auto_open_debits_emergency_pool(api):
    """PRD §3.7: "If no investigation exists for the disease in `ACTIVE` or
    `CONTAINED` status, a new `OutbreakInvestigation` is created in `ACTIVE`
    with `opened_at` stamped and `opened_case_count` set to the triggering
    count, and the `OPEN` health-fee pool (if one exists) is debited an
    emergency 25000 cents."

    Design: Corner/calculations/outbreak_auto_open_debits_emergency_pool
    """
    set_clock("2026-05-11T12:00:00Z")
    make_pool(term_code="SP26", budget_cents=100000)
    provider = make_provider("Dr S")
    _confirm_three_at(
        None, provider, ["S43", "S44", "S45"],
        [("2026-05-11T13:00:00Z", "2026-05-11T13:30:00Z"),
         ("2026-05-11T14:00:00Z", "2026-05-11T14:30:00Z"),
         ("2026-05-11T15:00:00Z", "2026-05-11T15:30:00Z")],
    )
    pool = get_pool_by_term("SP26")
    assert pool["spent_cents"] == 25000, (
        f"exactly one emergency debit of 25000 on auto-open, got {pool['spent_cents']}"
    )
