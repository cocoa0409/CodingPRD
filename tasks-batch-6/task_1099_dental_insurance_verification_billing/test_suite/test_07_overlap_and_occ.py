"""Temporal overlap semantics (coverage closed vs membership half-open) and OCC.

Difficulty: resource_temporal_overlap (x2).
Corner: verification_occ_stale_coverage_version.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_frontoffice_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as fac


# --------------------------------------------------------------------------
# resource_temporal_overlap / coverage_closed_interval_adjacency_overlaps
# --------------------------------------------------------------------------
def _coverage_a(api):
    """Coverage A spanning 2026-01-01..2026-06-30 (ACTIVE at default clock).
    Returns (patient_id, plan_id)."""
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    fx.new_coverage(api, patient["id"], plan["id"], term_date="2026-06-30")
    return patient["id"], plan["id"]


def test_coverage_adjacent_boundary_overlaps(api):
    """PRD §3.2: "overlap here is judged on closed intervals, so two coverages
    that merely touch at a shared boundary date count as overlapping."

    Design: Difficulty/resource_temporal_overlap/coverage_closed_interval_adjacency_overlaps
    """
    pid, plan_id = _coverage_a(api)
    resp = api.create_coverage(fac.create_coverage_payload(
        pid, plan_id, priority="SECONDARY", effective_date="2026-06-30",
        term_date="2026-12-31"), make_frontoffice_headers())
    validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP.value)


def test_coverage_one_day_gap_accepted(api):
    """PRD §3.2: "Creating a coverage that would overlap an existing active
    coverage for the same patient and plan is rejected with
    `ERR_COVERAGE_OVERLAP`" (a one-day gap does not overlap).

    Design: Difficulty/resource_temporal_overlap/coverage_closed_interval_adjacency_overlaps
    """
    pid, plan_id = _coverage_a(api)
    resp = api.create_coverage(fac.create_coverage_payload(
        pid, plan_id, priority="SECONDARY", effective_date="2026-07-01",
        term_date="2026-12-31"), make_frontoffice_headers())
    validate_success(resp, 201)


# --------------------------------------------------------------------------
# resource_temporal_overlap / membership_half_open_interval_adjacency_allowed
# --------------------------------------------------------------------------
def _membership_m1(api):
    """Membership M1 spanning 2026-05-01..2026-08-01. Returns (patient_id, mp_id)."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    patient = fx.new_patient(api)
    mp = fx.new_membership_plan(api, annual_fee_cents=30000, billing_period="MONTHLY")
    fx.new_membership(api, patient["id"], mp["id"],
                      period_start="2026-05-01", period_end="2026-08-01")
    return patient["id"], mp["id"]


def test_membership_adjacent_boundary_accepted(api):
    """PRD §3.8: "overlap here is judged on half-open intervals, so two
    memberships that meet exactly at a boundary date are allowed."

    Design: Difficulty/resource_temporal_overlap/membership_half_open_interval_adjacency_allowed
    """
    pid, mp_id = _membership_m1(api)
    resp = api.create_membership(fac.create_membership_payload(
        pid, mp_id, period_start="2026-08-01", period_end="2026-11-01"),
        make_frontoffice_headers())
    validate_success(resp, 201)


def test_membership_interior_overlap_rejected(api):
    """PRD §3.8: "any true overlap is rejected with `ERR_MEMBERSHIP_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/membership_half_open_interval_adjacency_allowed
    """
    pid, mp_id = _membership_m1(api)
    resp = api.create_membership(fac.create_membership_payload(
        pid, mp_id, period_start="2026-07-01", period_end="2026-10-01"),
        make_frontoffice_headers())
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_OVERLAP.value)


# --------------------------------------------------------------------------
# cross_cutting_complexity_layers / verification_occ_stale_coverage_version
# --------------------------------------------------------------------------
def test_verification_occ_stale_coverage_version(api):
    """PRD §2.9: "A newly created verification supersedes the coverage's prior
    benefit snapshot ... and this legitimately advances the coverage's `version`
    by one. If another writer has advanced the coverage's `version` since the
    client last read it, so that `expected_coverage_version` no longer equals the
    coverage's current `version`, the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/verification_occ_stale_coverage_version
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    assert cov["version"] == 1
    # First verification supersedes the snapshot and bumps coverage version to 2.
    first = fx.new_verification(api, cov)  # uses expected_coverage_version=1
    assert first["status"] == "VERIFIED"
    refreshed = get_success_data(api.get_coverage(cov["id"], make_frontoffice_headers()))
    assert refreshed["version"] == 2, f"expected 2, got {refreshed['version']}"
    # Second create still carrying stale version 1 is rejected.
    resp = api.create_verification(cov["id"],
        fac.create_verification_payload(1), make_frontoffice_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
