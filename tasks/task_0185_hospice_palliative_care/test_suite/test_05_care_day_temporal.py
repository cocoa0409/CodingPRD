"""Posting days of care: the bind / days-used / cap-ledger cascade, the respite consecutive-run
limit and its adjacency semantics, the duplicate-day point collision, the service-date range,
the intensity-flag agreement, and days-used conservation. PRD §3.6, §3.7.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_care_day,
    setup_provider_and_election,
    setup_respite_run_of_5,
    post_care_day,
    post_respite_run,
    post_gip_days,
    get_election,
    set_clock,
    create_care_day_payload,
    TEST_USERS,
)

CLINICAL = TEST_USERS["clinical_headers"]
BILLING = TEST_USERS["billing_headers"]


# ─── Transitive cascade: post → bind → days_used → cap ledger ─────────

def test_post_care_day_binds_period_and_reconciles_days_used(api):
    """PRD §3.6: "The server binds the day to its benefit period — the benefit_period_id is
    resolved from the service_date ... reconciles the election's days_used_in_period, and
    recomputes the provider's cap ledger."

    Design: Difficulty/transitive_cascade/careday_post_cascade_period_bind_daysused_capledger
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=200000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    cd = post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    assert_care_day(cd)
    assert cd["benefit_period_id"] is not None, "the posting binds a benefit_period_id"
    after = get_election(election["id"])
    assert after["days_used_in_period"] == 1, "days_used_in_period recounts to 1"


def test_post_care_day_recomputes_provider_cap_ledger(api):
    """PRD §3.6: "reconciles the election's days_used_in_period, and recomputes the provider's
    cap ledger."

    Design: Difficulty/transitive_cascade/careday_post_cascade_period_bind_daysused_capledger
    """
    provider, election = setup_provider_and_election(
        per_beneficiary_cap_cents=200000, election_date="2026-01-02T00:00:00Z",
        clock="2026-01-02T00:00:00Z")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    summary = validate_success(api.get_cap_summary(provider["id"], BILLING), 200)
    assert summary["total_paid_cents"] == 110000
    # allowance = 200000 * 1 = 200000 → liability = max(0, 110000 - 200000) = 0.
    assert summary["cap_liability_cents"] == 0


# ─── Boundary precision: respite run at 5 inclusive vs 6 ──────────────

def test_fifth_consecutive_respite_day_run_length_5(api):
    """PRD §3.7: "the count of consecutive respite days ending on that day, counting the day
    itself as 1 and walking backward one calendar day at a time so long as the immediately
    preceding calendar day also has a RESPITE care day for the same election..."

    Design: Difficulty/boundary_precision_check/respite_consecutive_run_boundary_at_5
    """
    provider, election, day5 = setup_respite_run_of_5(election_date="2026-01-01T00:00:00Z",
                                                      clock="2026-01-10T00:00:00Z")
    assert day5["respite_run_length"] == 5, (
        f"5th consecutive respite day has run length 5, got {day5['respite_run_length']}")


def test_sixth_consecutive_respite_day_rejected(api):
    """PRD §3.7: "Respite care is capped at 5 consecutive days: a RESPITE posting that would
    produce a run longer than 5 days is rejected with ERR_RESPITE_LIMIT_EXCEEDED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/respite_consecutive_run_boundary_at_5
    """
    provider, election, day5 = setup_respite_run_of_5(election_date="2026-01-01T00:00:00Z",
                                                      clock="2026-01-10T00:00:00Z")
    payload = create_care_day_payload(election["id"], "2026-01-06T00:00:00Z", "RESPITE",
                                      high_intensity=False)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_RESPITE_LIMIT_EXCEEDED")


# ─── Resource temporal overlap: duplicate same-day care day ───────────

def test_duplicate_care_day_same_service_date_rejected(api):
    """PRD §3.7: "At most one care day may exist per calendar day per election; a second posting
    on a service_date already used by that election is rejected with ERR_DUPLICATE_CARE_DAY
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_care_day_same_service_date
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    payload = create_care_day_payload(election["id"], "2026-01-02T00:00:00Z", "ROUTINE",
                                      high_intensity=True)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_DUPLICATE_CARE_DAY")


def test_distinct_service_dates_do_not_collide(api):
    """PRD §3.7: "At most one care day may exist per calendar day per election; a second posting
    on a service_date already used by that election is rejected with ERR_DUPLICATE_CARE_DAY
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_care_day_same_service_date
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    cd1 = post_care_day(election["id"], "2026-01-02T00:00:00Z", "GIP", high_intensity=False)
    cd2 = post_care_day(election["id"], "2026-01-03T00:00:00Z", "GIP", high_intensity=False)
    assert cd1["id"] != cd2["id"], "two distinct dates each get their own care day"


# ─── Resource temporal overlap: non-adjacent respite resets run ───────

def test_non_adjacent_respite_day_resets_run_to_1(api):
    """PRD §3.7: "the count of consecutive respite days ending on that day, counting the day
    itself as 1 and walking backward one calendar day at a time so long as the immediately
    preceding calendar day also has a RESPITE care day for the same election; the run is broken
    by any non-respite day or any calendar gap."

    Design: Difficulty/resource_temporal_overlap/respite_run_adjacency_overlap_window
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    set_clock("2026-01-20T00:00:00Z")
    post_respite_run(election["id"], [
        "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z",
        "2026-01-04T00:00:00Z", "2026-01-05T00:00:00Z",
    ])
    # A respite day on Jan 8 has a calendar gap (Jan 6/7 absent) → run resets to 1.
    newrun = post_care_day(election["id"], "2026-01-08T00:00:00Z", "RESPITE", high_intensity=False)
    assert newrun["respite_run_length"] == 1, (
        f"a non-adjacent respite day resets the run to 1, got {newrun['respite_run_length']}")
    assert newrun["level_of_care"] == "RESPITE"


def test_adjacent_respite_day_continues_run(api):
    """PRD §3.7: "counting the day itself as 1 and walking backward one calendar day at a time
    so long as the immediately preceding calendar day also has a RESPITE care day for the same
    election..."

    Design: Difficulty/resource_temporal_overlap/respite_run_adjacency_overlap_window
    """
    provider, election = setup_provider_and_election(election_date="2026-01-01T00:00:00Z",
                                                     clock="2026-01-01T00:00:00Z")
    set_clock("2026-01-20T00:00:00Z")
    days = post_respite_run(election["id"],
                            ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"])
    assert days[0]["respite_run_length"] == 1
    assert days[1]["respite_run_length"] == 2
    assert days[2]["respite_run_length"] == 3, "adjacent respite days extend the run"


# ─── Compensating invariant: days_used == current-period care-day count ─

def test_days_used_equals_care_day_count_in_period(api):
    """PRD §2.5: "The days_used_in_period equals the count of care days bound to the current
    benefit period; it is reconciled on every care-day posting and again on revoke and discharge."

    Design: Difficulty/compensating_invariant/days_used_conserved_equals_current_period_careday_count
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    set_clock("2026-01-05T00:00:00Z")
    post_care_day(election["id"], "2026-01-02T00:00:00Z", "ROUTINE", high_intensity=True)
    post_care_day(election["id"], "2026-01-03T00:00:00Z", "ROUTINE", high_intensity=True)
    post_care_day(election["id"], "2026-01-04T00:00:00Z", "ROUTINE", high_intensity=True)
    after = get_election(election["id"])
    assert after["days_used_in_period"] == 3, (
        f"days_used must equal the 3 care days in period 1, got {after['days_used_in_period']}")
    assert after["current_period_number"] == 1


def test_days_used_no_drift_after_two_postings(api):
    """PRD §2.5: "The days_used_in_period equals the count of care days bound to the current
    benefit period; it is reconciled on every care-day posting and again on revoke and discharge."

    Design: Difficulty/compensating_invariant/days_used_conserved_equals_current_period_careday_count
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    post_gip_days(election["id"], ["2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"])
    after = get_election(election["id"])
    assert after["days_used_in_period"] == 2


# ─── Corner: service date before election rejected ───────────────────

def test_service_date_before_election_rejected(api):
    """PRD §3.7: "The service_date must be on or after the election_date and strictly before any
    revocation or discharge date; a date before the election begins, or on or after the day the
    election terminates, is rejected with ERR_SERVICE_DATE_OUT_OF_RANGE (HTTP 422)."

    Design: Corner/validations/service_date_before_election_rejected
    """
    provider, election = setup_provider_and_election(election_date="2026-01-10T00:00:00Z",
                                                     clock="2026-01-10T00:00:00Z")
    payload = create_care_day_payload(election["id"], "2026-01-05T00:00:00Z", "GIP",
                                      high_intensity=False)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_SERVICE_DATE_OUT_OF_RANGE")


# ─── Corner: intensity flag mismatch rejected ─────────────────────────

def test_routine_high_window_with_false_flag_rejected(api):
    """PRD §3.6: "A high_intensity of true is valid only when the elapsed-day index is less than
    60; a high_intensity of false on a ROUTINE day is valid only when the elapsed-day index is
    60 or greater ... Any disagreement ... is rejected with ERR_INTENSITY_FLAG_MISMATCH
    (HTTP 422)."

    Design: Corner/validations/intensity_flag_mismatch_rejected
    """
    provider, election = setup_provider_and_election(election_date="2026-01-02T00:00:00Z",
                                                     clock="2026-01-02T00:00:00Z")
    # elapsed index 0 is in the high window, but high_intensity=false on a ROUTINE day → mismatch.
    payload = create_care_day_payload(election["id"], "2026-01-02T00:00:00Z", "ROUTINE",
                                      high_intensity=False)
    res = api.create_care_day(payload, CLINICAL)
    validate_error(res, "ERR_INTENSITY_FLAG_MISMATCH")
