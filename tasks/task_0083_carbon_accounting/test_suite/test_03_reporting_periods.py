"""Reporting period lifecycle, overlap, denominators, and close cascade
(PRD §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_reporting_period,
    create_organization,
    create_reporting_period,
    create_reporting_period_payload,
    setup_org_facility_period,
    setup_period_close_cascade_dataset,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Create + denominators (PRD §3.2)
# ---------------------------------------------------------------------------
def test_create_reporting_period_returns_open(api, data_steward_headers):
    """PRD §3.2: "The status begins at OPEN."
    """
    org = create_organization()
    res = api.create_reporting_period(
        org["id"], create_reporting_period_payload(), data_steward_headers,
    )
    data = validate_success(res, expected_status=201)
    assert_reporting_period(data)
    assert data["status"] == "OPEN"


@pytest.mark.parametrize("bad", [{"revenue": -1.00},
                                 {"headcount": -1},
                                 {"unit_output": -0.0001}])
def test_negative_denominators_rejected(api, data_steward_headers, bad):
    """PRD §3.2: "revenue, headcount, and unit_output must each be at
    least zero ... a negative value or a wrong-precision value is
    rejected with ERR_DENOMINATOR_INVALID."
    """
    org = create_organization()
    res = api.create_reporting_period(
        org["id"], create_reporting_period_payload(**bad), data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_DENOMINATOR_INVALID.value)


def test_end_date_must_exceed_start_date(api, data_steward_headers):
    """PRD §3.2: "end_date must be strictly greater than start_date."
    """
    org = create_organization()
    res = api.create_reporting_period(
        org["id"],
        create_reporting_period_payload(
            start_date="2025-06-01T00:00:00.000Z",
            end_date="2025-06-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    body = res.json()
    # PRD does not commit to a specific error_id for this; accept any 4xx
    # validation. Use generic validator.
    assert res.status_code >= 400


# ---------------------------------------------------------------------------
# Period overlap (PRD §3.2)
# ---------------------------------------------------------------------------
def test_overlapping_period_rejected(api, data_steward_headers):
    """PRD §3.2: "Two reporting periods of the same organization whose
    status is anything other than CANCELLED must not overlap on their
    half-open intervals; a violating create or update is rejected with
    ERR_PERIOD_OVERLAP."
    """
    org = create_organization()
    p1 = create_reporting_period(
        org["id"],
        start_date="2025-01-01T00:00:00.000Z",
        end_date="2026-01-01T00:00:00.000Z",
    )
    # Second period overlaps in the middle of p1
    res = api.create_reporting_period(
        org["id"],
        create_reporting_period_payload(
            start_date="2025-06-01T00:00:00.000Z",
            end_date="2026-06-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_PERIOD_OVERLAP.value)


def test_adjacent_periods_allowed_half_open(api, data_steward_headers):
    """PRD §3.2: half-open `[start_date, end_date)` — touching at the
    boundary is allowed."""
    org = create_organization()
    create_reporting_period(
        org["id"],
        start_date="2024-01-01T00:00:00.000Z",
        end_date="2025-01-01T00:00:00.000Z",
    )
    # Next period starts exactly at first period's end — half-open
    res = api.create_reporting_period(
        org["id"],
        create_reporting_period_payload(
            start_date="2025-01-01T00:00:00.000Z",
            end_date="2026-01-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_success(res, expected_status=201)


# ---------------------------------------------------------------------------
# Close — requires end_date passed (PRD §3.2)
# ---------------------------------------------------------------------------
def test_close_before_end_date_rejected(api, data_steward_headers):
    """PRD §3.2: "the close request is rejected with ERR_INVALID_STATE
    ... if the server clock has not yet reached the period's end_date."
    """
    org = create_organization()
    period = create_reporting_period(
        org["id"],
        start_date="2030-01-01T00:00:00.000Z",
        end_date="2031-01-01T00:00:00.000Z",
    )
    res = api.close_reporting_period(
        org["id"], period["id"], data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_close_after_clock_passes_end_date_succeeds(api, data_steward_headers):
    """PRD §3.2 + §3.8: closing is legal once /_clock/advance moves the
    clock past end_date."""
    org = create_organization()
    period = create_reporting_period(
        org["id"],
        start_date="2025-01-01T00:00:00.000Z",
        end_date="2025-06-01T00:00:00.000Z",
    )
    advance_clock_to("2025-06-01T00:00:01.000Z")
    res = api.close_reporting_period(
        org["id"], period["id"], data_steward_headers,
    )
    data = validate_success(res)
    assert data["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Close cascade (PRD §3.2)
# ---------------------------------------------------------------------------
def test_close_archives_activity_emission_and_auto_reverts_report(
        api, data_steward_headers):
    """PRD §3.2: "Closing a period mass-archives every ActivityData row
    whose reporting_period_id matches (status RECORDED becomes ARCHIVED),
    then mass-archives every EmissionRecord of the period (both FRESH
    and STALE become ARCHIVED), and finally auto-transitions any Report
    still in DRAFT or UNDER_REVIEW for that period to REVISIONS_REQUIRED."
    """
    base = setup_period_close_cascade_dataset()
    res = api.close_reporting_period(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
    )
    closed_period = validate_success(res)
    assert closed_period["status"] == "CLOSED"

    # Hop 1: ActivityData ARCHIVED
    res_acts = api.list_activity_data(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    )
    acts_body = res_acts.json()
    for act in acts_body["data"]:
        assert act["status"] == "ARCHIVED", (
            f"ActivityData {act['id']} should be ARCHIVED after close "
            "(PRD §3.2 hop 1)"
        )

    # Hop 2: EmissionRecord ARCHIVED
    res_recs = api.list_emission_records(
        base["org"]["id"], base["period"]["id"], data_steward_headers,
        params={"limit": 100},
    )
    recs_body = res_recs.json()
    assert len(recs_body["data"]) >= 1
    for rec in recs_body["data"]:
        assert rec["status"] == "ARCHIVED", (
            f"EmissionRecord {rec['id']} should be ARCHIVED after close "
            "(PRD §3.2 hop 2)"
        )

    # Hop 3: Report auto-transitioned from UNDER_REVIEW to REVISIONS_REQUIRED
    res_rep = api.get_report(
        base["org"]["id"], base["report"]["id"], data_steward_headers,
    )
    rep_data = validate_success(res_rep)
    assert rep_data["status"] == "REVISIONS_REQUIRED", (
        "Report status should be REVISIONS_REQUIRED after period close "
        "(PRD §3.2 hop 3)"
    )


# ---------------------------------------------------------------------------
# Cancel — admin-only, OPEN required (PRD §3.2)
# ---------------------------------------------------------------------------
def test_cancel_open_period_succeeds(api, platform_admin_headers):
    """PRD §3.2: "Cancellation of a period is restricted to PlatformAdmin:
    the period must be OPEN, no PUBLISHED Report may reference it."
    """
    org, _fac, period = setup_org_facility_period()
    res = api.cancel_reporting_period(
        org["id"], period["id"], platform_admin_headers,
    )
    data = validate_success(res)
    assert data["status"] == "CANCELLED"


def test_cancel_period_forbidden_for_steward(api, data_steward_headers):
    """PRD §3.2 / §4: cancel is PlatformAdmin-only — DataSteward gets 403."""
    org, _fac, period = setup_org_facility_period()
    res = api.cancel_reporting_period(
        org["id"], period["id"], data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
