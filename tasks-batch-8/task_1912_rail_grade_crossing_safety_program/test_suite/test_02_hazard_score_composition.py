"""Hazard score tiered composition and the exposure review-threshold boundary
(PRD §3.1)."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_crossing,
    create_crossing_payload,
    create_locality,
    get_success_data,
    setup_locality_and_crossing,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestHazardScoreTieredComposition:
    def test_high_band_composes_with_device_factor(self, api, admin_headers):
        """PRD §3.1: "an exposure band multiplier applied to the snapshot
        `exposure_index` — 1.40 (`SEVERE`) when exposure is at least 25, 1.20
        (`HIGH`) when at least 10, 1.10 (`MEDIUM`) when at least 3, and 1.00 (`LOW`)
        below 3 ... The raw score is the sum of exposure times its band multiplier,
        the incident term, and the bus term, all multiplied by the device factor
        and the sight multiplier; the final `hazard_score` is that raw score capped
        at 100 and rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/hazard_score_tiered_composition
        """
        locality = create_locality(locality_name="Hazardville")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-300001",
                road_authority_locality_id=locality["id"],
                highway_functional_class="COLLECTOR",
                annual_train_count=730,
                train_speed_max_mph=30,
                aadt=5000,
                school_bus_count=0,
                sight_distance_rating=3,
                warning_device_class="PASSIVE_CROSSBUCK",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["exposure_index"] == pytest.approx(10.00, abs=1e-9)
        # (10.00*1.20 + 0 + 0) * 1.50 * 1.00 = 18.00
        assert data["hazard_score"] == pytest.approx(18.00, abs=1e-9)

    def test_severe_band_composes_with_bus_term_and_sight_multiplier(
        self, api, admin_headers
    ):
        """PRD §3.1: "an incident term equal to the crossing's five-year incident
        count capped at 5 and then multiplied by 8; a bus term equal to the
        `school_bus_count` capped at 20 and then multiplied by 0.5; and a sight
        multiplier of 1.15 when the `sight_distance_rating` is 2 or worse,
        otherwise 1.00."

        Design: Difficulty/combinatorial_formula/hazard_score_tiered_composition
        """
        locality = create_locality(locality_name="Hazardville")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-300002",
                road_authority_locality_id=locality["id"],
                highway_functional_class="COLLECTOR",
                annual_train_count=1825,
                train_speed_max_mph=30,
                aadt=5000,
                school_bus_count=20,
                sight_distance_rating=1,
                warning_device_class="GATES",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["exposure_index"] == pytest.approx(25.00, abs=1e-9)
        # (25.00*1.40 + 0 + 20*0.5) * 1.00 * 1.15 = (35 + 10) * 1.15 = 51.75
        assert data["hazard_score"] == pytest.approx(51.75, abs=1e-9)


class TestExposureReviewThresholdBoundary:
    def test_exposure_999_does_not_trigger_review_due(self, api, admin_headers):
        """PRD §3.1: "A crossing's `diagnostic_review_due` flag is `true` when its
        snapshot `exposure_index` reaches 10.00 or higher, and it also becomes
        `true` the moment any incident at the crossing is assigned to a field
        investigation (§3.3)".

        Design: Difficulty/boundary_precision_check/exposure_threshold_exact_vs_below
        """
        locality = create_locality(locality_name="Boundary City")
        resp = api.create_crossing(
            create_crossing_payload(
                dot_crossing_number="DOT-600001",
                road_authority_locality_id=locality["id"],
                annual_train_count=730,
                aadt=4995,
                school_bus_count=0,
                sight_distance_rating=3,
                warning_device_class="GATES",
            ),
            admin_headers,
        )
        data = validate_success(resp, expected_status=201)
        # (730/365)*4995/1000 = 9.99
        assert data["exposure_index"] == pytest.approx(9.99, abs=1e-9)
        assert data["diagnostic_review_due"] is False

    def test_exposure_exactly_10_triggers_review_due_at_creation_and_after_patch(
        self, api, admin_headers
    ):
        """PRD §3.1: "A crossing's `diagnostic_review_due` flag is `true` when its
        snapshot `exposure_index` reaches 10.00 or higher". PRD §3.1: "A successful
        patch increments the crossing's `version` by exactly 1 and recomputes
        `exposure_index`, `projected_exposure_index`, `hazard_score`, and
        `diagnostic_review_due` from the new inputs."

        Design: Difficulty/boundary_precision_check/exposure_threshold_exact_vs_below
        """
        locality = create_locality(locality_name="Boundary City")
        below = get_success_data(
            api.create_crossing(
                create_crossing_payload(
                    dot_crossing_number="DOT-600011",
                    road_authority_locality_id=locality["id"],
                    annual_train_count=730,
                    aadt=4995,
                    school_bus_count=0,
                    sight_distance_rating=3,
                    warning_device_class="GATES",
                ),
                admin_headers,
            )
        )
        at = get_success_data(
            api.create_crossing(
                create_crossing_payload(
                    dot_crossing_number="DOT-600012",
                    road_authority_locality_id=locality["id"],
                    annual_train_count=730,
                    aadt=5000,
                    school_bus_count=0,
                    sight_distance_rating=3,
                    warning_device_class="GATES",
                ),
                admin_headers,
            )
        )
        # Equality at creation triggers (>= semantics).
        assert at["exposure_index"] == pytest.approx(10.00, abs=1e-9)
        assert at["diagnostic_review_due"] is True

        # Patching the below-threshold crossing up to exactly 10.00 flips the flag.
        patched = get_success_data(
            api.patch_crossing_inventory(
                below["id"],
                {"expected_crossing_version": below["version"], "aadt": 5000},
                admin_headers,
            )
        )
        assert patched["exposure_index"] == pytest.approx(10.00, abs=1e-9)
        assert patched["diagnostic_review_due"] is True
