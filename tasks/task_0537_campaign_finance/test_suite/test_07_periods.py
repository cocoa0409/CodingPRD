"""Reporting-period overlap semantics: half-open (campaign finance) vs closed (lobbying)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_reporting_period_payload, create_lobbying_period_payload,
    TEST_USERS,
    create_reporting_period, create_closed_reporting_period, create_lobbying_period,
)

REGULATOR = TEST_USERS["regulator_headers"]


# --------------------------------------------------------------------------- #
# Campaign-finance reporting period — half-open [start, end)
# --------------------------------------------------------------------------- #
def test_cf_period_adjacent_start_equals_prior_end_accepted(api):
    """PRD §2.11: "Because the interval is half-open, one period ending exactly where the
    next begins do not overlap."

    Design: Difficulty/resource_temporal_overlap/cf_reporting_period_halfopen_overlap
    """
    create_reporting_period(api, period_label="Q1", period_start="2026-01-01T00:00:00Z",
                            period_end="2026-04-01T00:00:00Z", filing_deadline="2026-04-15T00:00:00Z")
    adjacent = validate_success(
        api.create_reporting_period(
            create_reporting_period_payload(period_label="Q2", period_start="2026-04-01T00:00:00Z",
                                            period_end="2026-07-01T00:00:00Z", filing_deadline="2026-07-15T00:00:00Z"),
            REGULATOR,
        ),
        expected_status=201,
    )
    assert adjacent["status"] == "OPEN", "adjacency at the shared endpoint is not overlap for half-open CF periods"


def test_cf_period_interior_overlap_rejected(api):
    """PRD §2.11: "two periods conflict when their half-open intervals share any instant ...
    A conflicting create is rejected with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/cf_reporting_period_halfopen_overlap
    """
    create_reporting_period(api, period_label="Q1", period_start="2026-01-01T00:00:00Z",
                            period_end="2026-04-01T00:00:00Z", filing_deadline="2026-04-15T00:00:00Z")
    resp = api.create_reporting_period(
        create_reporting_period_payload(period_label="Bad", period_start="2026-03-01T00:00:00Z",
                                        period_end="2026-06-01T00:00:00Z", filing_deadline="2026-06-15T00:00:00Z"),
        REGULATOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)


# --------------------------------------------------------------------------- #
# Lobbying reporting period — closed [start, end]
# --------------------------------------------------------------------------- #
def test_lobbying_period_adjacent_start_equals_prior_end_rejected(api):
    """PRD §2.11: "Under closed-interval semantics, adjacency counts as a conflict: a period
    ending exactly where the next begins overlaps at that shared endpoint. A conflicting
    create is likewise rejected with ERR_PERIOD_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/lobbying_period_closed_adjacency_overlap
    """
    create_lobbying_period(api, period_label="LP1", period_start="2026-01-01T00:00:00Z",
                           period_end="2026-04-01T00:00:00Z", filing_deadline="2026-04-15T00:00:00Z")
    resp = api.create_lobbying_period(
        create_lobbying_period_payload(period_label="adj", period_start="2026-04-01T00:00:00Z",
                                       period_end="2026-07-01T00:00:00Z", filing_deadline="2026-07-15T00:00:00Z"),
        REGULATOR,
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_lobbying_period_disjoint_after_prior_end_accepted(api):
    """PRD §2.11: "A lobbying reporting period spans a closed interval from period_start
    through period_end, both endpoints inclusive, and its overlap scope is jurisdiction alone."

    Design: Difficulty/resource_temporal_overlap/lobbying_period_closed_adjacency_overlap
    """
    create_lobbying_period(api, period_label="LP1", period_start="2026-01-01T00:00:00Z",
                           period_end="2026-04-01T00:00:00Z", filing_deadline="2026-04-15T00:00:00Z")
    ok = validate_success(
        api.create_lobbying_period(
            create_lobbying_period_payload(period_label="ok", period_start="2026-04-02T00:00:00Z",
                                           period_end="2026-07-01T00:00:00Z", filing_deadline="2026-07-15T00:00:00Z"),
            REGULATOR,
        ),
        expected_status=201,
    )
    assert ok["status"] == "OPEN", "a period starting strictly after the prior end does not overlap"


# --------------------------------------------------------------------------- #
# Close precondition (corner)
# --------------------------------------------------------------------------- #
def test_close_already_closed_period_rejected(api):
    """PRD §3.5: "When the agency later closes it, the period moves from OPEN to CLOSED;
    closing requires the period to be OPEN and is otherwise rejected with ERR_PERIOD_NOT_OPEN."

    Design: Corner/state_machines/period_close_twice_rejected
    """
    period = create_closed_reporting_period(api)
    validate_error(api.close_reporting_period(period["id"], REGULATOR), ApiErrorId.ERR_PERIOD_NOT_OPEN.value)
