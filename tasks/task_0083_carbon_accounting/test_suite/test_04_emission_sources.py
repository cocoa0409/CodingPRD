"""Emission source create + scope derivation + Scope-3 category rules
(PRD §3.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_emission_source,
    create_approved_factor,
    create_facility,
    create_organization,
    create_source,
    create_source_payload,
    setup_org_with_in_boundary_facility,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Scope derivation (PRD §3.3)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("category,expected_scope", [
    ("STATIONARY_COMBUSTION", "SCOPE_1"),
    ("MOBILE_COMBUSTION", "SCOPE_1"),
    ("PROCESS", "SCOPE_1"),
    ("FUGITIVE", "SCOPE_1"),
    ("PURCHASED_ENERGY", "SCOPE_2"),
])
def test_scope_derived_from_category(api, data_steward_headers, category,
                                     expected_scope):
    """PRD §3.3: "a source whose category is STATIONARY_COMBUSTION,
    MOBILE_COMBUSTION, PROCESS, or FUGITIVE is SCOPE_1; a source whose
    category is PURCHASED_ENERGY is SCOPE_2; a source whose category is
    VALUE_CHAIN is SCOPE_3."
    """
    org, fac = setup_org_with_in_boundary_facility()
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=1.0,
        scope2_method="LOCATION_BASED" if category == "PURCHASED_ENERGY" else None,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    src = create_source(
        org["id"], fac["id"], category=category, gas_type="CO2",
        factor_code=factor["code"],
    )
    assert src["scope"] == expected_scope


def test_value_chain_scope_is_scope_3(api):
    """PRD §3.3: VALUE_CHAIN ⇒ SCOPE_3 with scope3_category required."""
    org, fac = setup_org_with_in_boundary_facility()
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=0.1,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    src = create_source(
        org["id"], fac["id"], category="VALUE_CHAIN", gas_type="CO2",
        factor_code=factor["code"], scope3_category=5,
    )
    assert src["scope"] == "SCOPE_3"
    assert src["scope3_category"] == 5


# ---------------------------------------------------------------------------
# Scope-3 pairing rule (PRD §3.3)
# ---------------------------------------------------------------------------
def test_scope3_category_missing_on_value_chain_rejected(api,
                                                         data_steward_headers):
    """PRD §3.3: "a value-chain source without a category number ... is
    rejected with ERR_SCOPE3_CATEGORY_MISMATCH."
    """
    org, fac = setup_org_with_in_boundary_facility()
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=0.1,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="VALUE_CHAIN", gas_type="CO2",
            factor_code=factor["code"],
        ),  # NO scope3_category
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_SCOPE3_CATEGORY_MISMATCH.value)


def test_scope3_category_on_non_value_chain_rejected(api,
                                                     data_steward_headers):
    """PRD §3.3: "a non-value-chain source carrying one ... is rejected
    with ERR_SCOPE3_CATEGORY_MISMATCH."
    """
    org, fac = setup_org_with_in_boundary_facility()
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=1.0,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="STATIONARY_COMBUSTION",
            gas_type="CO2", factor_code=factor["code"], scope3_category=3,
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_SCOPE3_CATEGORY_MISMATCH.value)


@pytest.mark.parametrize("bad", [0, 16, -1, 100])
def test_scope3_category_out_of_range_rejected(api, data_steward_headers,
                                               bad):
    """PRD §3.3: "a value-chain source whose number falls outside 1..15
    is rejected with ERR_SCOPE3_CATEGORY_MISMATCH."
    """
    org, fac = setup_org_with_in_boundary_facility()
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=0.1,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="VALUE_CHAIN", gas_type="CO2",
            factor_code=factor["code"], scope3_category=bad,
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_SCOPE3_CATEGORY_MISMATCH.value)


# ---------------------------------------------------------------------------
# Facility boundary at source creation (PRD §3.3)
# ---------------------------------------------------------------------------
def test_source_creation_blocked_when_facility_out_of_boundary(
        api, data_steward_headers):
    """PRD §3.3: "At creation, the source's facility must satisfy
    included_in_boundary equal to true and status equal to ACTIVE;
    otherwise the request is rejected with ERR_FACILITY_OUT_OF_BOUNDARY."
    """
    org = create_organization(consolidation_approach="EQUITY_SHARE")
    fac = create_facility(
        org["id"], ownership_share_pct=0.00,
        financial_control=True, operational_control=True,
    )
    assert fac["included_in_boundary"] is False  # set-up sanity
    factor = create_approved_factor(
        org["id"], gas_type="CO2", kg_per_unit=1.0,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_source(
        org["id"],
        create_source_payload(
            facility_id=fac["id"], category="STATIONARY_COMBUSTION",
            gas_type="CO2", factor_code=factor["code"],
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_FACILITY_OUT_OF_BOUNDARY.value)


# ---------------------------------------------------------------------------
# Cross-org reference (PRD §2.7)
# ---------------------------------------------------------------------------
def test_source_creation_cross_org_facility_rejected(api, data_steward_headers):
    """PRD §2.7: "every foreign key embedded in the request body
    (facility_id, ...) must refer to a row in the same organization as
    the URL path; a cross-tenant reference is rejected with
    ERR_CROSS_ORG_REFERENCE."
    """
    org_a, fac_a = setup_org_with_in_boundary_facility()
    org_b, fac_b = setup_org_with_in_boundary_facility()
    # Reference fac_b under org_a's URL.
    factor = create_approved_factor(
        org_a["id"], gas_type="CO2", kg_per_unit=1.0,
        effective_from="2024-12-01T00:00:00.000Z",
    )
    res = api.create_source(
        org_a["id"],
        create_source_payload(
            facility_id=fac_b["id"], category="STATIONARY_COMBUSTION",
            gas_type="CO2", factor_code=factor["code"],
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_CROSS_ORG_REFERENCE.value)
