"""Emissions and fuel sulfur compliance: scrubber branches, ECA boundary
precision, input range validation, and terminal-state lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_emissions_record,
    create_emissions_record,
    evaluate_emissions_ok,
    find_noncompliance,
    setup_voyage_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client


class TestScrubberBranches:
    def test_scrubber_with_eca_hours_yields_exempt_scrubber(self, api, shore_officer_headers):
        """PRD section 3.8: "When a scrubber is installed, the record is
        `EXEMPT_SCRUBBER` provided the EGCS operated for at least 95 percent of
        `inside_eca_hours` (and if no ECA hours were logged, the record is simply
        `COMPLIANT`)."

        Design: Difficulty/combinatorial_formula/sulfur_scrubber_nested_branch_selection
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000003", vessel_name="MV Corral", voyage_number="V2001"
        )
        record = create_emissions_record(
            vessel["id"], voyage["id"], fuel_type="VLSFO", sulfur_content_pct=4.9,
            consumed_volume_mt=800, inside_eca_hours=12, outside_eca_hours=6,
            scrubber_installed=True,
        )
        resp = api.evaluate_emissions(vessel["id"], voyage["id"], record["id"],
                                      shore_officer_headers)
        evaluated = validate_success(resp, 200)
        # Scrubber branch with ECA hours logged exempts the 4.9% sulfur reading.
        assert evaluated["compliance_status"] == "EXEMPT_SCRUBBER"

    def test_scrubber_without_eca_hours_yields_compliant(self, api, shore_officer_headers):
        """PRD section 3.8: "When a scrubber is installed, the record is
        `EXEMPT_SCRUBBER` provided the EGCS operated for at least 95 percent of
        `inside_eca_hours` (and if no ECA hours were logged, the record is simply
        `COMPLIANT`)."

        Design: Difficulty/combinatorial_formula/sulfur_scrubber_nested_branch_selection
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000003", vessel_name="MV Corral", voyage_number="V2001"
        )
        record = create_emissions_record(
            vessel["id"], voyage["id"], fuel_type="MGO", sulfur_content_pct=0.08,
            consumed_volume_mt=500, inside_eca_hours=0, outside_eca_hours=30,
            scrubber_installed=True,
        )
        resp = api.evaluate_emissions(vessel["id"], voyage["id"], record["id"],
                                      shore_officer_headers)
        evaluated = validate_success(resp, 200)
        # The nested no-ECA-hours branch degrades to COMPLIANT, not EXEMPT_SCRUBBER.
        assert evaluated["compliance_status"] == "COMPLIANT"


class TestSulfurEcaBoundary:
    def test_sulfur_exactly_at_eca_limit_is_compliant(self, api, shore_officer_headers):
        """PRD section 3.8: "The record is compliant when either no ECA hours were
        logged or the sulfur content is at most 0.10 percent — and in all cases the
        sulfur content is at most 0.50 percent. A boundary reading of exactly 0.10
        percent is compliant."
        PRD section 2.6: "Sulfur boundary comparisons are inclusive: a reading of
        exactly 0.10 percent inside an Emission Control Area is compliant."

        Design: Difficulty/boundary_precision_check/sulfur_eca_exactly_at_limit_compliant
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000016", vessel_name="MV Petrel", voyage_number="V7002"
        )
        record = create_emissions_record(
            vessel["id"], voyage["id"], fuel_type="VLSFO", sulfur_content_pct=0.10,
            consumed_volume_mt=600, inside_eca_hours=10, outside_eca_hours=5,
            scrubber_installed=False,
        )
        resp = api.evaluate_emissions(vessel["id"], voyage["id"], record["id"],
                                      shore_officer_headers)
        evaluated = validate_success(resp, 200)
        assert evaluated["compliance_status"] == "COMPLIANT"

    def test_sulfur_above_eca_limit_is_noncompliant_and_spawns_record(
            self, api, shore_officer_headers):
        """PRD section 3.8: "The record is compliant when either no ECA hours were
        logged or the sulfur content is at most 0.10 percent — and in all cases the
        sulfur content is at most 0.50 percent."
        PRD section 3.8: "A compliant evaluation increments the vessel's `version`; a
        noncompliant evaluation creates a noncompliance record with `source_type`
        `DETERMINATION_NONCOMPLIANT` and recomputes the vessel's posture."
        PRD section 3.10: "a noncompliant determination 25"
        PRD section 3.10: "A score of at least 70 yields `CRITICAL`; at least 40
        yields `MAJOR`; otherwise `MINOR`."

        Design: Difficulty/boundary_precision_check/sulfur_eca_exactly_at_limit_compliant
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9000016", vessel_name="MV Petrel", voyage_number="V7002"
        )
        record = create_emissions_record(
            vessel["id"], voyage["id"], fuel_type="VLSFO", sulfur_content_pct=0.101,
            consumed_volume_mt=600, inside_eca_hours=10, outside_eca_hours=5,
            scrubber_installed=False,
        )
        resp = api.evaluate_emissions(vessel["id"], voyage["id"], record["id"],
                                      shore_officer_headers)
        evaluated = validate_success(resp, 200)
        assert evaluated["compliance_status"] == "NONCOMPLIANT"

        record = find_noncompliance(vessel["id"], voyage["id"],
                                    source_type="DETERMINATION_NONCOMPLIANT")
        # Score 25 (noncompliant determination), posture OPEN, no prior escalations.
        assert record["severity"] == "MINOR"


class TestSulfurInputRange:
    def test_sulfur_out_of_range_returns_422(self, api, vessel_master_headers,
                                             shore_officer_headers):
        """PRD section 3.8: "The `VesselMaster` records fuel consumption for a voyage,
        supplying `fuel_type` (one of `HFO`, `VLSFO`, `MGO`, `MDO`, `LNG`, or
        `BIOFUEL_BLEND`), `sulfur_content_pct` (at least 0 and at most 5.0 — outside
        that range the request is rejected with `ERR_SULFUR_OUT_OF_RANGE`, HTTP 422),
        `consumed_volume_mt` (greater than 0), `inside_eca_hours` and
        `outside_eca_hours` (both at least 0), and `scrubber_installed`."

        Design: Corner/validations/sulfur_out_of_range_returns_422
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100048", vessel_name="MV Teal", voyage_number="V9506"
        )
        too_high = api.create_emissions_record(
            vessel["id"], voyage["id"],
            {"fuel_type": "HFO", "sulfur_content_pct": 5.001, "consumed_volume_mt": 700,
             "inside_eca_hours": 0, "outside_eca_hours": 40, "scrubber_installed": False},
            vessel_master_headers,
        )
        validate_error(too_high, ApiErrorId.ERR_SULFUR_OUT_OF_RANGE)

        at_bound = api.create_emissions_record(
            vessel["id"], voyage["id"],
            {"fuel_type": "HFO", "sulfur_content_pct": 5.0, "consumed_volume_mt": 700,
             "inside_eca_hours": 0, "outside_eca_hours": 40, "scrubber_installed": True},
            vessel_master_headers,
        )
        data = validate_success(at_bound, 201)
        assert_emissions_record(data)


class TestEmissionsTerminalLockdown:
    def test_emissions_evaluate_after_terminal_returns_409(self, api, shore_officer_headers):
        """PRD section 3.8: "Evaluation by a `ShoreComplianceOfficer` resolves the
        record to `COMPLIANT`, `NONCOMPLIANT`, or `EXEMPT_SCRUBBER`."
        PRD section 2.5: "An attempt to invoke a state transition that the target
        entity's current state does not permit is rejected with `ERR_INVALID_STATE`
        (HTTP 409)"

        Design: Corner/state_machines/emissions_evaluate_after_terminal_returns_409
        """
        vessel, plan, voyage = setup_voyage_in_progress(
            imo_number="9100026", vessel_name="MV Quail", voyage_number="V9306"
        )
        record = create_emissions_record(
            vessel["id"], voyage["id"], fuel_type="MGO", sulfur_content_pct=0.05,
            consumed_volume_mt=400, inside_eca_hours=8, outside_eca_hours=20,
            scrubber_installed=False,
        )
        first = evaluate_emissions_ok(vessel["id"], voyage["id"], record["id"])
        assert first["compliance_status"] == "COMPLIANT"

        resp = api.evaluate_emissions(vessel["id"], voyage["id"], record["id"],
                                      shore_officer_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        records = api.list_emissions_records(vessel["id"], voyage["id"], shore_officer_headers)
        current = [r for r in validate_success(records, 200) if r["id"] == record["id"]][0]
        assert current["compliance_status"] == "COMPLIANT", (
            "rejected re-evaluation must leave the record COMPLIANT"
        )
