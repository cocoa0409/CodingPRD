"""Resource temporal overlap: inspector buffer-window conflicts and policy
coverage-period overlaps. Queue A — rule resource_temporal_overlap.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_underwriter_headers,
    ApiErrorId,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestInspectorBufferOverlap:
    def test_second_window_inside_buffer_conflicts(self, api):
        """PRD §3.3: "the system rejects a window that falls within the inspector's
        buffer of any other `SCHEDULED`, `COMPLETED`, or `PASSED` inspection already
        on that inspector's calendar, surfacing `ERR_INSPECTION_WINDOW_CONFLICT`. Two
        windows conflict when, after expanding each by the buffer gap, the half-open
        intervals would touch or overlap; the buffer is applied as a minutes gap
        between the end of one window and the start of the next."

        Design: Difficulty/resource_temporal_overlap/inspection_window_buffer_overlap_on_inspector
        """
        inspector = fx.create_inspector(buffer_minutes=60, full_name="Buff Insp")
        prop_a = fx.create_property(street_address="15 First St", square_footage=1800, roof_age_years=4)
        prop_b = fx.create_property(street_address="16 Second St", square_footage=1900, roof_age_years=6)
        # First inspection over [1750800000, 1750803600)
        fx.schedule_inspection(prop_a["id"], inspector["id"], 1750800000, 1750803600)
        # Second starts 1750805400 = 30 min after first end (1750803600), inside 60-min buffer.
        resp = api.create_inspection(
            f.create_inspection_payload(prop_b["id"], inspector["id"], 1750805400, 1750809000),
            UW,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_WINDOW_CONFLICT.value)

    def test_window_outside_buffer_succeeds(self, api):
        """PRD §3.3: "a `buffer_minutes` value that defaults to 60 minutes and that
        must separate two inspections by the same inspector. ... the buffer is applied
        as a minutes gap between the end of one window and the start of the next."

        Design: Difficulty/resource_temporal_overlap/inspection_window_buffer_overlap_on_inspector
        """
        inspector = fx.create_inspector(buffer_minutes=60, full_name="Buff Insp")
        prop_a = fx.create_property(street_address="15 First St", square_footage=1800, roof_age_years=4)
        prop_b = fx.create_property(street_address="16 Second St", square_footage=1900, roof_age_years=6)
        fx.schedule_inspection(prop_a["id"], inspector["id"], 1750800000, 1750803600)
        # Second starts 1750807800 = 70 min after first end -> outside the 60-min buffer.
        resp = api.create_inspection(
            f.create_inspection_payload(prop_b["id"], inspector["id"], 1750807800, 1750811400),
            UW,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "SCHEDULED"


class TestPolicyCoveragePeriodOverlap:
    def test_overlapping_coverage_on_same_property_rejected(self, api):
        """PRD §3.7: "no other `ACTIVE` or `REINSTATED` policy may already cover the
        same `property_id` over an overlapping coverage period, otherwise
        `ERR_COVERAGE_PERIOD_OVERLAP`. Coverage periods run from `effective_date` to
        `expiration_date` as a closed interval inclusive of both ends, and two such
        intervals overlap when they share any instant."

        Design: Difficulty/resource_temporal_overlap/policy_coverage_period_overlap_on_property
        """
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property(prop_overrides={"street_address": "17 Overlap Ave"})
        fx.setup_passed_inspection(prop["id"])

        # First policy -> ACTIVE over [1751000000, 1782536000].
        app1 = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        app1 = fx.submit_application(app1["id"])
        app1 = fx.take_review(app1["id"], uw["id"])
        app1 = fx.bind_application(app1["id"], app1["version"], uw["id"], 1751000000, 1782536000)
        pol1 = fx.get_policy_for_application(app1["id"])
        fx.pay_binding(pol1["id"], pol1["annual_premium"])

        # Second policy bound PENDING_PAYMENT over an overlapping [1760000000, 1791000000].
        app2 = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        app2 = fx.submit_application(app2["id"])
        app2 = fx.take_review(app2["id"], uw["id"])
        app2 = fx.bind_application(app2["id"], app2["version"], uw["id"], 1760000000, 1791000000)
        pol2 = fx.get_policy_for_application(app2["id"])

        resp = api.create_payment(
            f.create_payment_payload(pol2["id"], "BINDING", pol2["annual_premium"]), AGENT
        )
        validate_error(resp, ApiErrorId.ERR_COVERAGE_PERIOD_OVERLAP.value)
        assert fx.get_policy(pol2["id"])["status"] == "PENDING_PAYMENT"

    def test_non_overlapping_coverage_on_same_property_activates(self, api):
        """PRD §3.7: "no other `ACTIVE` or `REINSTATED` policy may already cover the
        same `property_id` over an overlapping coverage period, otherwise
        `ERR_COVERAGE_PERIOD_OVERLAP`. Coverage periods run from `effective_date` to
        `expiration_date` as a closed interval inclusive of both ends, and two such
        intervals overlap when they share any instant."

        Design: Difficulty/resource_temporal_overlap/policy_coverage_period_overlap_on_property
        """
        uw = fx.create_underwriter()
        prop, ra = fx.setup_estimated_property(prop_overrides={"street_address": "17b Gap Ave"})
        fx.setup_passed_inspection(prop["id"])

        # First policy -> ACTIVE over [1751000000, 1760000000].
        app1 = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        app1 = fx.submit_application(app1["id"])
        app1 = fx.take_review(app1["id"], uw["id"])
        app1 = fx.bind_application(app1["id"], app1["version"], uw["id"], 1751000000, 1760000000)
        pol1 = fx.get_policy_for_application(app1["id"])
        fx.pay_binding(pol1["id"], pol1["annual_premium"])

        # Second policy over a disjoint [1760000001, 1791000000] (no shared instant).
        app2 = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        app2 = fx.submit_application(app2["id"])
        app2 = fx.take_review(app2["id"], uw["id"])
        app2 = fx.bind_application(app2["id"], app2["version"], uw["id"], 1760000001, 1791000000)
        pol2 = fx.get_policy_for_application(app2["id"])
        activated = validate_success(
            api.create_payment(
                f.create_payment_payload(pol2["id"], "BINDING", pol2["annual_premium"]), AGENT
            ),
            201,
        )
        assert fx.get_policy(pol2["id"])["status"] == "ACTIVE", (
            "disjoint coverage periods on the same property must not conflict"
        )
