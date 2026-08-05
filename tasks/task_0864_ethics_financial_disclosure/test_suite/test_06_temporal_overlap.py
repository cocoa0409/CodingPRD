"""Temporal-overlap rules: half-open recusal intervals and closed filing-period intervals.

Queue A: resource_temporal_overlap (recusal half-open, filing-period closed).
Queue B: recusal_adjacent_half_open_allowed.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_filer_headers,
    register_jurisdiction, register_filer, open_filing_period,
    setup_filer_with_recusal, declare_recusal, get_filer,
    create_filing_period_payload, api_client,
)


def test_overlapping_recusals_same_matter_rejected(api):
    """PRD 3.7: "a new recusal conflicts with an existing `DECLARED` recusal on the same
    `filer_id` and `matter_id` only if their half-open intervals overlap".
    PRD 3.7: "A genuine overlap is rejected with `ERR_RECUSAL_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/recusal_overlap_half_open
    """
    filer, rec1 = setup_filer_with_recusal(
        matter_id="M1", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z")
    res = declare_recusal(filer["id"], matter_id="M1",
                          effective_start="2026-06-05T00:00:00Z",
                          effective_end="2026-06-15T00:00:00Z", reason="overlap")
    validate_error(res, "ERR_RECUSAL_OVERLAP")


def test_recusal_overlap_does_not_add_second_declaration(api):
    """PRD 3.7: "A recusal's `status` is `DECLARED` on creation, and declaring it increments the
    owning filer's `open_recusal_count` by 1."

    Design: Difficulty/resource_temporal_overlap/recusal_overlap_half_open
    """
    filer, rec1 = setup_filer_with_recusal(
        matter_id="M1", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z")
    declare_recusal(filer["id"], matter_id="M1",
                    effective_start="2026-06-05T00:00:00Z",
                    effective_end="2026-06-15T00:00:00Z", reason="overlap")
    # Only the first (accepted) recusal counts.
    assert get_filer(filer["id"])["open_recusal_count"] == 1


def test_touching_filing_periods_closed_interval_conflict(api, registrar_headers):
    """PRD 3.2: "two periods conflict if their closed `coverage_start`-through-`coverage_end`
    ranges share any instant, including a shared endpoint where one period ends exactly when
    another begins."
    PRD 3.2: "An attempt to open a period whose closed coverage interval overlaps an existing
    period of the same `jurisdiction_id` and `statement_type` is rejected with
    `ERR_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/filing_period_overlap_closed
    """
    jur = register_jurisdiction()
    open_filing_period(jur["id"], statement_type="ANNUAL",
                       coverage_start="2025-01-01T00:00:00Z",
                       coverage_end="2025-12-31T00:00:00Z",
                       due_at="2026-04-15T00:00:00Z", label="CY2025")
    res = api.create_filing_period(create_filing_period_payload(
        jur["id"], statement_type="ANNUAL",
        coverage_start="2025-12-31T00:00:00Z", coverage_end="2026-12-31T00:00:00Z",
        due_at="2027-04-15T00:00:00Z", label="CY2026"), registrar_headers)
    validate_error(res, "ERR_PERIOD_OVERLAP")


def test_period_overlap_only_within_same_statement_type(api, registrar_headers):
    """PRD 3.2: "Coverage intervals for the same jurisdiction and statement type may not
    overlap."

    Design: Difficulty/resource_temporal_overlap/filing_period_overlap_closed
    """
    jur = register_jurisdiction()
    open_filing_period(jur["id"], statement_type="ANNUAL",
                       coverage_start="2025-01-01T00:00:00Z",
                       coverage_end="2025-12-31T00:00:00Z",
                       due_at="2026-04-15T00:00:00Z", label="CY2025")
    # A TRANSACTIONAL period sharing an instant does NOT conflict (different type).
    ok = api.create_filing_period(create_filing_period_payload(
        jur["id"], statement_type="TRANSACTIONAL",
        coverage_start="2025-06-01T00:00:00Z", coverage_end="2025-06-30T00:00:00Z",
        due_at="2025-07-15T00:00:00Z", label="TX"), registrar_headers)
    validate_success(ok, 201)
    # But another ANNUAL sharing the endpoint conflicts.
    res = api.create_filing_period(create_filing_period_payload(
        jur["id"], statement_type="ANNUAL",
        coverage_start="2025-12-31T00:00:00Z", coverage_end="2026-12-31T00:00:00Z",
        due_at="2027-04-15T00:00:00Z", label="CY2026"), registrar_headers)
    validate_error(res, "ERR_PERIOD_OVERLAP")


def test_adjacent_recusals_allowed(api):
    """PRD 3.7: "two recusals that merely touch at an endpoint (one ending exactly where the next
    begins) do not conflict."

    Design: Corner/validations/recusal_adjacent_half_open_allowed
    """
    filer, rec1 = setup_filer_with_recusal(
        matter_id="M1", effective_start="2026-06-01T00:00:00Z",
        effective_end="2026-06-10T00:00:00Z")
    rec2 = validate_success(declare_recusal(
        filer["id"], matter_id="M1",
        effective_start="2026-06-10T00:00:00Z",
        effective_end="2026-06-20T00:00:00Z"), 201)
    assert rec2["status"] == "DECLARED"
    assert get_filer(filer["id"])["open_recusal_count"] == 2
