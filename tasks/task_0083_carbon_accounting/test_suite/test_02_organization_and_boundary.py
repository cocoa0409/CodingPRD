"""Organization and Facility CRUD, boundary resolver, boundary-change log
(PRD §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_facility,
    assert_organization,
    create_facility_payload,
    create_organization,
    create_organization_payload,
    create_facility,
    create_boundary_change_payload,
    setup_org_with_in_boundary_facility,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Organization create + materiality bounds (PRD §3.1)
# ---------------------------------------------------------------------------
def test_create_organization_returns_default_materiality(
        api, platform_admin_headers):
    """PRD §3.1: "an optional materiality_threshold_pct that defaults to
    1.0 percent."
    """
    payload = create_organization_payload()
    payload.pop("materiality_threshold_pct", None)
    res = api.create_organization(payload, platform_admin_headers)
    data = validate_success(res, expected_status=201)
    assert_organization(data)
    assert float(data["materiality_threshold_pct"]) == pytest.approx(1.0)


@pytest.mark.parametrize("bad_pct", [-0.01, 5.01, 10.0])
def test_organization_materiality_out_of_range(api, platform_admin_headers,
                                               bad_pct):
    """PRD §3.1: "a value outside that band is rejected with
    ERR_MATERIALITY_OUT_OF_RANGE."
    """
    res = api.create_organization(
        create_organization_payload(materiality_threshold_pct=bad_pct),
        platform_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_MATERIALITY_OUT_OF_RANGE.value)


@pytest.mark.parametrize("good_pct", [0.00, 1.00, 5.00])
def test_organization_materiality_at_boundaries(api, platform_admin_headers,
                                                good_pct):
    """PRD §3.1: "must lie between 0.0 and 5.0 percent inclusive"."""
    res = api.create_organization(
        create_organization_payload(materiality_threshold_pct=good_pct),
        platform_admin_headers,
    )
    data = validate_success(res, expected_status=201)
    assert float(data["materiality_threshold_pct"]) == pytest.approx(good_pct)


def test_organization_status_defaults_active(api, platform_admin_headers):
    """PRD §3.1: "The organization profile carries a system-managed
    status that begins at ACTIVE."""
    org = create_organization()
    assert org["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Facility boundary resolver — three approaches (PRD §3.1)
# ---------------------------------------------------------------------------
def test_facility_in_boundary_under_financial_control(api):
    """PRD §3.1: "under FINANCIAL_CONTROL, inclusion follows the
    financial_control flag and ownership_share_pct is ignored."""
    org, fac = setup_org_with_in_boundary_facility(
        consolidation_approach="FINANCIAL_CONTROL",
        financial_control=True, operational_control=False,
        ownership_share_pct=0.00,
    )
    assert fac["included_in_boundary"] is True


def test_facility_excluded_under_financial_control_when_flag_false(api):
    """PRD §3.1: under FINANCIAL_CONTROL, a facility with
    financial_control=false is excluded regardless of share or
    operational_control."""
    org = create_organization(consolidation_approach="FINANCIAL_CONTROL")
    fac = create_facility(
        org["id"],
        ownership_share_pct=100.00,
        financial_control=False,
        operational_control=True,
    )
    assert fac["included_in_boundary"] is False


def test_facility_in_boundary_under_operational_control(api):
    """PRD §3.1: "under OPERATIONAL_CONTROL, inclusion follows the
    operational_control flag."""
    org = create_organization(consolidation_approach="OPERATIONAL_CONTROL")
    fac = create_facility(
        org["id"],
        ownership_share_pct=0.00,
        financial_control=False,
        operational_control=True,
    )
    assert fac["included_in_boundary"] is True


def test_facility_under_equity_share_strict_greater_than_zero(api):
    """PRD §3.1: "under EQUITY_SHARE, a facility is in boundary when its
    ownership_share_pct is strictly greater than zero — a facility with
    0.00 percent share is excluded even if financial_control is true."
    """
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"],
        ownership_share_pct=0.00,
        financial_control=True,
        operational_control=True,
    )
    assert fac["included_in_boundary"] is False


def test_facility_under_equity_share_smallest_positive_share_included(api):
    """PRD §3.1: under EQUITY_SHARE the comparison is strict '>': a
    facility at 0.01 percent IS included."""
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"],
        ownership_share_pct=0.01,
        financial_control=False,
        operational_control=False,
    )
    assert fac["included_in_boundary"] is True


# ---------------------------------------------------------------------------
# Facility PATCH triggers boundary resolver (PRD §3.1)
# ---------------------------------------------------------------------------
def test_patch_facility_share_to_zero_under_equity_share_excludes(api,
                                                                  platform_admin_headers):
    """PRD §3.1: "The boundary resolver is rerun on every facility
    creation, every facility update, and every boundary-change
    recording."
    Under EQUITY_SHARE, dropping share to 0.00 must flip
    included_in_boundary to false (strict '>')."""
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"], ownership_share_pct=50.00,
        financial_control=True, operational_control=True,
    )
    assert fac["included_in_boundary"] is True

    res = api.update_facility(
        org["id"], fac["id"], {"ownership_share_pct": 0.00},
        platform_admin_headers,
    )
    updated = validate_success(res)
    assert updated["included_in_boundary"] is False


# ---------------------------------------------------------------------------
# Boundary change log (PRD §3.1)
# ---------------------------------------------------------------------------
def test_boundary_change_facility_id_null_only_for_approach_switch(
        api, platform_admin_headers):
    """PRD §3.1: "the affected facility_id (which must be null exactly
    when change_type is APPROACH_SWITCH)."
    """
    org, fac = setup_org_with_in_boundary_facility()
    # ADD_FACILITY with facility_id supplied succeeds.
    res = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="ADD_FACILITY",
            effective_date="2025-01-15T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    data = validate_success(res, expected_status=201)
    assert data["facility_id"] == fac["id"]
    assert data["change_type"] == "ADD_FACILITY"


def test_boundary_change_effective_date_strictly_increasing(api,
                                                            platform_admin_headers):
    """PRD §3.1: "The new event's effective_date must be strictly greater
    than the latest existing change's effective_date for the same
    organization; a violation is rejected with ERR_BOUNDARY_CHANGE_ORDER."
    """
    org, fac = setup_org_with_in_boundary_facility()
    # First change at 2025-01-10
    res1 = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="ADD_FACILITY",
            effective_date="2025-01-10T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    validate_success(res1, expected_status=201)
    # Second change at exactly 2025-01-10 (NOT strictly greater) fails
    res2 = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="OWNERSHIP_ADJUSTMENT",
            effective_date="2025-01-10T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    validate_error(res2, ApiErrorId.ERR_BOUNDARY_CHANGE_ORDER.value)


def test_boundary_change_earlier_date_rejected(api, platform_admin_headers):
    """PRD §3.1: a strictly-greater effective_date is required; an earlier
    date is also rejected with ERR_BOUNDARY_CHANGE_ORDER."""
    org, fac = setup_org_with_in_boundary_facility()
    res1 = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="ADD_FACILITY",
            effective_date="2025-06-01T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    validate_success(res1, expected_status=201)
    res2 = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="OWNERSHIP_ADJUSTMENT",
            effective_date="2025-03-01T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    validate_error(res2, ApiErrorId.ERR_BOUNDARY_CHANGE_ORDER.value)


def test_boundary_change_has_no_updated_at_or_version(api,
                                                     platform_admin_headers):
    """PRD §2.4: "BoundaryChange and AuditLog carry only id and
    created_at — neither has updated_at nor version, because both are
    append-only event records that are never edited after they are
    written."""
    org, fac = setup_org_with_in_boundary_facility()
    res = api.create_boundary_change(
        org["id"],
        create_boundary_change_payload(
            change_type="ADD_FACILITY",
            effective_date="2025-04-01T00:00:00.000Z",
            facility_id=fac["id"],
        ),
        platform_admin_headers,
    )
    data = validate_success(res, expected_status=201)
    assert "updated_at" not in data, (
        "BoundaryChange must NOT carry updated_at (PRD §2.4)"
    )
    assert "version" not in data, (
        "BoundaryChange must NOT carry version (PRD §2.4)"
    )


# ---------------------------------------------------------------------------
# Functional currency format (PRD §3.1)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["us", "usd", "USDD", "U1D", "US"])
def test_functional_currency_must_be_three_upper(api, platform_admin_headers,
                                                 bad):
    """PRD §3.1: "an ISO-4217 functional_currency consisting of exactly
    three uppercase letters."
    """
    res = api.create_organization(
        create_organization_payload(functional_currency=bad),
        platform_admin_headers,
    )
    body = res.json()
    # No dedicated error code — falls back to ERR_VALIDATION_FAILED
    assert body["data"]["error_id"] == ApiErrorId.ERR_VALIDATION_FAILED.value
    assert res.status_code == 422
