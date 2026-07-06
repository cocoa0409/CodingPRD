"""Licensing a registered work: registration gating, half-open exclusivity
overlap, and date-range validation.

Covers Difficulty queue instances license_requires_work_registered and
exclusive_license_overlap_half_open, plus the license date-range corner instance.
"""
from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers import factories as fac
from test_helpers import fixtures as fx


# ==========================================================================
# Difficulty — license_requires_work_registered
# ==========================================================================
def test_license_on_unregistered_work_rejected(api, rightsholder_headers):
    """PRD §3.5: "A license may only be created for a work whose registration_status
    is REGISTERED; a license against an unregistered or merely pending work is
    rejected with ERR_WORK_NOT_REGISTERED."

    Design: Difficulty/cross_entity_state_dependency/license_requires_work_registered
    """
    work = fx.create_work()  # registration_status == UNREGISTERED
    resp = api.create_license(fac.create_license_payload(work["id"]), rightsholder_headers)
    validate_error(resp, ApiErrorId.ERR_WORK_NOT_REGISTERED)


def test_license_on_pending_work_rejected(api, rightsholder_headers):
    """PRD §3.5: "a license against an unregistered or merely pending work is
    rejected with ERR_WORK_NOT_REGISTERED."
    PRD §3.1: registration_status "becomes PENDING when the application is submitted."

    Design: Difficulty/cross_entity_state_dependency/license_requires_work_registered
    """
    work, _app = fx.setup_application_submitted()  # work -> PENDING
    resp = api.create_license(fac.create_license_payload(work["id"]), rightsholder_headers)
    validate_error(resp, ApiErrorId.ERR_WORK_NOT_REGISTERED)


# ==========================================================================
# Difficulty — exclusive_license_overlap_half_open
# ==========================================================================
def test_overlapping_exclusive_licenses_rejected(api, rightsholder_headers):
    """PRD §3.5: "a new EXCLUSIVE license must not overlap an existing EXCLUSIVE
    license — one that is ACTIVE or UNDER_REVIEW — that covers the same work, the
    same right_type, and the same territory, where overlap is measured over the
    half-open start_date-to-end_date interval. A conflicting exclusive grant is
    rejected with ERR_EXCLUSIVE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/exclusive_license_overlap_half_open
    """
    work, _lic = fx.setup_registered_work_with_license(license_overrides={
        "license_type": "EXCLUSIVE", "right_type": "REPRODUCTION", "territory": "US",
        "start_date": "2026-01-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z",
        "grant_date": "2026-01-01T00:00:00Z", "royalty_rate_bps": 1000,
    })
    conflict = fac.create_license_payload(
        work["id"], licensee_name="L2", license_type="EXCLUSIVE", right_type="REPRODUCTION",
        territory="US", start_date="2026-05-01T00:00:00Z", end_date="2026-09-01T00:00:00Z",
        grant_date="2026-05-01T00:00:00Z", royalty_rate_bps=1000,
    )
    validate_error(api.create_license(conflict, rightsholder_headers), ApiErrorId.ERR_EXCLUSIVE_CONFLICT)


def test_adjacent_exclusive_licenses_allowed(api, rightsholder_headers):
    """PRD §3.5: "The license term is a half-open interval that runs from start_date
    inclusive to end_date exclusive" and overlap "is measured over the half-open
    start_date-to-end_date interval."

    Design: Difficulty/resource_temporal_overlap/exclusive_license_overlap_half_open
    """
    work, _lic = fx.setup_registered_work_with_license(license_overrides={
        "license_type": "EXCLUSIVE", "right_type": "REPRODUCTION", "territory": "US",
        "start_date": "2026-01-01T00:00:00Z", "end_date": "2026-06-01T00:00:00Z",
        "grant_date": "2026-01-01T00:00:00Z", "royalty_rate_bps": 1000,
    })
    # start_date == prior end_date: half-open intervals touch but do not overlap.
    adjacent = fac.create_license_payload(
        work["id"], licensee_name="L2", license_type="EXCLUSIVE", right_type="REPRODUCTION",
        territory="US", start_date="2026-06-01T00:00:00Z", end_date="2026-09-01T00:00:00Z",
        grant_date="2026-06-01T00:00:00Z", royalty_rate_bps=1000,
    )
    data = validate_success(api.create_license(adjacent, rightsholder_headers), 201)
    assert data["status"] == "ACTIVE"


# ==========================================================================
# Corner — license invalid date range
# ==========================================================================
def test_license_start_not_before_end_rejected(api, rightsholder_headers):
    """PRD §3.5: "start_date must fall strictly before end_date, otherwise
    ERR_INVALID_DATE_RANGE."

    Design: Corner/validations/license_invalid_date_range_returns_error
    """
    work, _app = fx.setup_registered_work()
    bad = fac.create_license_payload(
        work["id"], start_date="2027-01-01T00:00:00Z", end_date="2026-01-01T00:00:00Z",
        grant_date="2026-01-01T00:00:00Z",
    )
    validate_error(api.create_license(bad, rightsholder_headers), ApiErrorId.ERR_INVALID_DATE_RANGE)
