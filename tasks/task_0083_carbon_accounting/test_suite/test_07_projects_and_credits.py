"""Reduction projects and carbon credit lifecycles (PRD §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    activate_project,
    assert_carbon_credit,
    assert_reduction_project,
    create_active_project,
    create_credit,
    create_credit_payload,
    create_project,
    create_project_payload,
    create_organization,
    retire_credit,
    setup_credit_lifecycle_dataset,
    setup_org_facility_period,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Project create — facility_id pairing rule (PRD §3.6)
# ---------------------------------------------------------------------------
def test_internal_reduction_requires_facility_id(api, data_steward_headers):
    """PRD §3.6: "The facility_id must be supplied when project_type is
    INTERNAL_REDUCTION and must be null otherwise."
    """
    org, fac, period = setup_org_facility_period()
    res = api.create_project(
        org["id"],
        create_project_payload(
            reporting_period_id=period["id"],
            project_type="INTERNAL_REDUCTION",
            reduction_kg_co2e=100.0000,
            # NO facility_id
        ),
        data_steward_headers,
    )
    # PRD does not name a specific error_id here — falls under generic
    # input shape validation (PRD §5).
    body = res.json()
    assert res.status_code >= 400, "INTERNAL_REDUCTION without facility_id must fail"
    assert body["data"]["error_id"] == ApiErrorId.ERR_VALIDATION_FAILED.value


def test_external_offset_must_omit_facility_id(api, data_steward_headers):
    """PRD §3.6: "facility_id ... must be null" for non-INTERNAL_REDUCTION.
    """
    org, fac, period = setup_org_facility_period()
    res = api.create_project(
        org["id"],
        create_project_payload(
            reporting_period_id=period["id"],
            project_type="EXTERNAL_OFFSET",
            reduction_kg_co2e=100.0000,
            facility_id=fac["id"],  # FORBIDDEN
        ),
        data_steward_headers,
    )
    body = res.json()
    assert res.status_code >= 400
    assert body["data"]["error_id"] == ApiErrorId.ERR_VALIDATION_FAILED.value


def test_project_starts_in_planned(api):
    """PRD §3.6: "The project status begins at PLANNED."
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    assert_reduction_project(proj)
    assert proj["status"] == "PLANNED"


# ---------------------------------------------------------------------------
# Project activate / complete (PRD §3.6)
# ---------------------------------------------------------------------------
def test_activate_planned_project(api):
    """PRD §3.6: "Activation moves it from PLANNED to ACTIVE and requires
    the parent reporting period to be OPEN."
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    activated = activate_project(org["id"], proj["id"])
    assert activated["status"] == "ACTIVE"


def test_complete_external_offset_requires_all_credits_retired(
        api, data_steward_headers):
    """PRD §3.6: "Completion moves it from ACTIVE to COMPLETED ... and
    for external-offset projects every linked CarbonCredit must have
    status RETIRED before completion is allowed."
    """
    base = setup_credit_lifecycle_dataset()
    # Two PURCHASED credits — neither retired; complete must fail.
    res = api.complete_project(
        base["org"]["id"], base["project"]["id"], data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Carbon credit lifecycle (PRD §3.6)
# ---------------------------------------------------------------------------
def test_create_carbon_credit_starts_purchased(api, discloser_headers):
    """PRD §3.6: "The status begins at PURCHASED."
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    res = api.create_credit(
        org["id"],
        create_credit_payload(
            reporting_period_id=period["id"],
            linked_reduction_project_id=proj["id"],
            quantity_kg_co2e=200.0000, vintage_year=2024,
        ),
        discloser_headers,
    )
    data = validate_success(res, expected_status=201)
    assert_carbon_credit(data)
    assert data["status"] == "PURCHASED"
    assert data["retired_at"] is None, (
        "retired_at must be null while PURCHASED (PRD §3.6)"
    )


def test_duplicate_serial_rejected_across_orgs(api, discloser_headers,
                                               platform_admin_headers):
    """PRD §3.6: "a serial_number ... that is globally unique across
    every CarbonCredit row of every organization — a duplicate is
    rejected with ERR_CREDIT_DOUBLE_COUNTED, even across tenants."
    """
    # Org A: create credit with serial S
    org_a, _, p_a = setup_org_facility_period()
    proj_a = create_active_project(
        org_a["id"], p_a["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    serial = "GLOBAL-SN-12345-UNIQUE"
    create_credit(
        org_a["id"], p_a["id"], proj_a["id"],
        serial_number=serial, quantity_kg_co2e=1.0, vintage_year=2024,
    )
    # Org B (different org): attempt to create credit with SAME serial
    org_b, _, p_b = setup_org_facility_period()
    proj_b = create_active_project(
        org_b["id"], p_b["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    res = api.create_credit(
        org_b["id"],
        create_credit_payload(
            reporting_period_id=p_b["id"],
            linked_reduction_project_id=proj_b["id"],
            quantity_kg_co2e=1.0, vintage_year=2024,
            serial_number=serial,
        ),
        discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_DOUBLE_COUNTED.value)


def test_vintage_year_above_period_end_year_rejected(api, discloser_headers):
    """PRD §3.6: "a vintage_year between 1990 and the year of the parent
    reporting period's end_date inclusive."
    """
    from test_helpers import create_reporting_period
    org = create_organization()
    period = create_reporting_period(
        org["id"],
        start_date="2025-01-01T00:00:00.000Z",
        end_date="2026-01-01T00:00:00.000Z",
    )
    proj = create_active_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    res = api.create_credit(
        org["id"],
        create_credit_payload(
            reporting_period_id=period["id"],
            linked_reduction_project_id=proj["id"],
            quantity_kg_co2e=1.0, vintage_year=2027,  # > 2026 end-year
        ),
        discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_CREDIT_DOUBLE_COUNTED.value)


# ---------------------------------------------------------------------------
# Retire (PRD §3.6) — requires ACTIVE project, PURCHASED status
# ---------------------------------------------------------------------------
def test_retire_credit_succeeds(api, discloser_headers):
    """PRD §3.6: "A Discloser retires a credit by transitioning it from
    PURCHASED to RETIRED and supplying a retirement_certificate_url."
    """
    base = setup_credit_lifecycle_dataset()
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        base["org"]["id"], base["credit_a"]["id"],
        retire_credit_payload(), discloser_headers,
    )
    data = validate_success(res)
    assert data["status"] == "RETIRED"
    assert data["retired_at"] is not None


def test_retire_credit_already_retired_rejected(api, discloser_headers):
    """PRD §3.6: PURCHASED→RETIRED requires CarbonCredit.status ==
    PURCHASED; second retire fails ERR_INVALID_STATE."""
    base = setup_credit_lifecycle_dataset()
    retire_credit(base["org"]["id"], base["credit_a"]["id"])
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        base["org"]["id"], base["credit_a"]["id"],
        retire_credit_payload(), discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_retire_credit_blocked_when_project_planned(api, discloser_headers):
    """PRD §3.6: "the linked reduction project must be in ACTIVE
    status ... otherwise the call is rejected with ERR_INVALID_STATE."
    """
    org, _fac, period = setup_org_facility_period()
    proj = create_project(
        org["id"], period["id"], project_type="EXTERNAL_OFFSET",
        reduction_kg_co2e=100.0000,
    )
    # Project is still PLANNED (not activated).
    credit = create_credit(
        org["id"], period["id"], proj["id"],
        quantity_kg_co2e=100.0, vintage_year=2024,
    )
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        org["id"], credit["id"],
        retire_credit_payload(), discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Transfer (PRD §3.6)
# ---------------------------------------------------------------------------
def test_transfer_credit_succeeds(api, discloser_headers):
    """PRD §3.6: "a Discloser may transfer a credit out, moving it from
    PURCHASED to TRANSFERRED; transfer is only allowed when the parent
    reporting period is OPEN."
    """
    base = setup_credit_lifecycle_dataset()
    res = api.transfer_credit(
        base["org"]["id"], base["credit_b"]["id"], discloser_headers,
    )
    data = validate_success(res)
    assert data["status"] == "TRANSFERRED"
    assert data["retired_at"] is None


def test_transfer_credit_blocks_subsequent_retire(api, discloser_headers):
    """PRD §3.6: terminal-state branching — once TRANSFERRED, retire is
    blocked (status must be PURCHASED for retire)."""
    base = setup_credit_lifecycle_dataset()
    api.transfer_credit(
        base["org"]["id"], base["credit_b"]["id"], discloser_headers,
    )
    from test_helpers import retire_credit_payload
    res = api.retire_credit(
        base["org"]["id"], base["credit_b"]["id"],
        retire_credit_payload(), discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_retire_credit_blocks_subsequent_transfer(api, discloser_headers):
    """PRD §3.6: terminal-state branching — once RETIRED, transfer is
    blocked (status must be PURCHASED for transfer)."""
    base = setup_credit_lifecycle_dataset()
    retire_credit(base["org"]["id"], base["credit_a"]["id"])
    res = api.transfer_credit(
        base["org"]["id"], base["credit_a"]["id"], discloser_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
