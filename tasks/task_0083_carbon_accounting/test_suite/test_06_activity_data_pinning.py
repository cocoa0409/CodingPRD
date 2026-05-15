"""Activity data entry, factor pinning, GWP calculation, validation
ordering (PRD §3.5)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GWP_TABLE,
    assert_activity_data,
    assert_emission_record,
    assert_emissions_precision,
    create_activity_data,
    create_activity_data_payload,
    create_approved_factor,
    create_organization,
    create_source,
    setup_one_source_one_factor,
    setup_org_facility_period,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Successful entry + EmissionRecord materialization (PRD §3.5)
# ---------------------------------------------------------------------------
def test_activity_data_creates_emission_record(api, data_steward_headers):
    """PRD §3.5: "Entering activity data ... becomes a quantified
    contribution to the ledger." and "emission record is computed in
    the same transaction" (PRD §4).
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(
        org, fac, gas_type="CO2", kg_per_unit=2.687000,
    )
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            data_source="METER_READING",
            quantity=1000.0000,
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    act = validate_success(res, expected_status=201)
    assert_activity_data(act)

    # EmissionRecord must exist for the period
    res_recs = api.list_emission_records(
        org["id"], period["id"], data_steward_headers, params={"limit": 100},
    )
    body = res_recs.json()
    matches = [r for r in body["data"]
               if r.get("activity_data_id") == act["id"]]
    assert len(matches) == 1, (
        "Exactly one EmissionRecord should be created per ActivityData "
        "(PRD §3.5)"
    )
    rec = matches[0]
    assert_emission_record(rec)
    assert rec["status"] == "FRESH"
    # quantity * kg_per_unit * GWP(CO2=1) = 1000 * 2.687 * 1 = 2687.0000
    assert rec["kg_co2e"] == pytest.approx(2687.0000, abs=1e-4)


# ---------------------------------------------------------------------------
# GWP per gas (PRD §3.5)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("gas_type,gwp_expected", [
    ("CO2", 1),
    ("CH4", 28),
    ("N2O", 265),
    ("HFC", 1430),
    ("PFC", 7390),
    ("SF6", 23500),
    ("NF3", 16100),
])
def test_gwp_applied_per_gas_type(api, data_steward_headers, gas_type,
                                  gwp_expected):
    """PRD §3.5: "gwp_factor is the GWP-100 value for that gas (CO2 = 1,
    CH4 = 28, N2O = 265, HFC = 1430, PFC = 7390, SF6 = 23500,
    NF3 = 16100)."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(
        org, fac, gas_type=gas_type, kg_per_unit=0.001000,
        category="PROCESS",
    )
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"], quantity=500.0000,
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    act = validate_success(res, expected_status=201)
    res_recs = api.list_emission_records(
        org["id"], period["id"], data_steward_headers, params={"limit": 100},
    )
    rec = next(r for r in res_recs.json()["data"]
               if r["activity_data_id"] == act["id"])
    assert rec["gwp_factor"] == gwp_expected, (
        f"GWP({gas_type}) must equal {gwp_expected} (PRD §3.5)"
    )
    # kg_co2e = 500.0000 * 0.001000 * gwp
    expected_kg = round(500.0000 * 0.001000 * gwp_expected, 4)
    assert rec["kg_co2e"] == pytest.approx(expected_kg, abs=1e-4)


# ---------------------------------------------------------------------------
# Data-quality score derivation (PRD §3.5)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("data_source,expected_score,needs_basis", [
    ("METER_READING", 1.00, False),
    ("INVOICE", 0.80, False),
    ("SUPPLIER_DATA", 0.65, False),
    ("ESTIMATION", 0.40, True),
])
def test_data_quality_score_derived_from_data_source(
        api, data_steward_headers, data_source, expected_score, needs_basis):
    """PRD §3.5: "The data_quality_score is derived from data_source:
    METER_READING scores 1.00, INVOICE scores 0.80, SUPPLIER_DATA scores
    0.65, and ESTIMATION scores 0.40."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    payload_kwargs = {"data_source": data_source}
    if needs_basis:
        payload_kwargs["estimation_basis"] = "Engineering estimate based on benchmark data."
    act = create_activity_data(
        org["id"], period["id"], src["id"], **payload_kwargs,
    )
    assert float(act["data_quality_score"]) == pytest.approx(expected_score)


# ---------------------------------------------------------------------------
# Estimation basis rule (PRD §3.5)
# ---------------------------------------------------------------------------
def test_estimation_basis_required_when_estimation(api, data_steward_headers):
    """PRD §3.5: "when data_source is ESTIMATION, estimation_basis must
    be a non-null 5-to-500-character string."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            data_source="ESTIMATION",
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
            # NO estimation_basis
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ESTIMATION_BASIS_REQUIRED.value)


def test_estimation_basis_forbidden_when_not_estimation(api,
                                                       data_steward_headers):
    """PRD §3.5: "when data_source is anything else, estimation_basis
    must be null. A violation in either direction is rejected with
    ERR_ESTIMATION_BASIS_REQUIRED."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            data_source="INVOICE",
            estimation_basis="Some unused estimation basis text",
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ESTIMATION_BASIS_REQUIRED.value)


# ---------------------------------------------------------------------------
# Activity window inside period (PRD §3.5)
# ---------------------------------------------------------------------------
def test_activity_outside_period_rejected(api, data_steward_headers):
    """PRD §3.5: "Temporal validity requires activity_end to be strictly
    greater than activity_start, with both lying inside the parent
    reporting period's half-open [start_date, end_date) interval ... a
    window outside the period or with a non-positive duration is
    rejected with ERR_ACTIVITY_OUTSIDE_PERIOD."
    """
    org, fac, period = setup_org_facility_period(
        period_start="2025-01-01T00:00:00.000Z",
        period_end="2026-01-01T00:00:00.000Z",
    )
    factor, src = setup_one_source_one_factor(org, fac)
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"], quantity=1.0,
            activity_start="2024-06-01T00:00:00.000Z",
            activity_end="2024-07-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ACTIVITY_OUTSIDE_PERIOD.value)


def test_activity_end_at_period_end_allowed(api, data_steward_headers):
    """PRD §3.5: "activity_end <= end_date" — equality is allowed."""
    org, fac, period = setup_org_facility_period(
        period_start="2025-01-01T00:00:00.000Z",
        period_end="2026-01-01T00:00:00.000Z",
    )
    factor, src = setup_one_source_one_factor(org, fac)
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"], quantity=1.0,
            activity_start="2025-12-01T00:00:00.000Z",
            activity_end="2026-01-01T00:00:00.000Z",  # equals period.end_date
        ),
        data_steward_headers,
    )
    validate_success(res, expected_status=201)


# ---------------------------------------------------------------------------
# Activity interval overlap on same source (PRD §3.5)
# ---------------------------------------------------------------------------
def test_activity_interval_overlap_rejected(api, data_steward_headers):
    """PRD §3.5: "two activity rows of the same source must not overlap
    on their half-open intervals [activity_start, activity_end), and a
    second writer is rejected with ERR_ACTIVITY_INTERVAL_OVERLAP."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    create_activity_data(
        org["id"], period["id"], src["id"],
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-03-15T00:00:00.000Z",
            activity_end="2025-04-15T00:00:00.000Z",  # overlaps mid-window
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_ACTIVITY_INTERVAL_OVERLAP.value)


def test_activity_touching_intervals_allowed(api, data_steward_headers):
    """PRD §3.5 (half-open `[activity_start, activity_end)`): touching at
    the boundary is allowed — record1 [a,b) and record2 [b,c) are
    non-overlapping."""
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(org, fac)
    create_activity_data(
        org["id"], period["id"], src["id"],
        activity_start="2025-03-01T00:00:00.000Z",
        activity_end="2025-04-01T00:00:00.000Z",
    )
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-04-01T00:00:00.000Z",  # touches at boundary
            activity_end="2025-05-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_success(res, expected_status=201)


# ---------------------------------------------------------------------------
# No-applicable-factor (PRD §3.5)
# ---------------------------------------------------------------------------
def test_no_applicable_factor_when_effective_from_after_start(api,
                                                              data_steward_headers):
    """PRD §3.5: "the server picks the EmissionFactor whose ...
    effective_from is less than or equal to activity_start ... If no
    such factor exists, the request is rejected with
    ERR_NO_APPLICABLE_FACTOR."
    """
    org, fac, period = setup_org_facility_period()
    factor, src = setup_one_source_one_factor(
        org, fac, factor_effective_from="2025-06-01T00:00:00.000Z",
    )
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-03-01T00:00:00.000Z",  # before effective_from
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_APPLICABLE_FACTOR.value)


# ---------------------------------------------------------------------------
# Period must be OPEN at entry time (PRD §3.5)
# ---------------------------------------------------------------------------
def test_activity_entry_blocked_when_period_closed(api, data_steward_headers):
    """PRD §3.5: "A DataSteward posts an activity record into the
    activity-data collection of a reporting_period_id that must be
    currently OPEN."
    """
    from test_helpers import advance_clock_to
    org, fac, period = setup_org_facility_period(
        period_end="2025-06-01T00:00:00.000Z",
    )
    factor, src = setup_one_source_one_factor(org, fac)
    advance_clock_to("2025-06-01T00:00:01.000Z")
    api.close_reporting_period(org["id"], period["id"], data_steward_headers)
    res = api.create_activity_data(
        org["id"], period["id"],
        create_activity_data_payload(
            emission_source_id=src["id"],
            activity_start="2025-03-01T00:00:00.000Z",
            activity_end="2025-04-01T00:00:00.000Z",
        ),
        data_steward_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
