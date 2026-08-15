"""Shelf-life studies: chamber-position capacity over closed intervals,
texture pull windows, and the strict hardness projection failure rule
(PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    assert_2dp,
    fixtures,
    record_pull_payload,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

LT = TEST_USERS["lab_technician_headers"]


class TestHardnessProjectionStrictThreshold:
    def test_projection_exactly_at_limit_passes(self, api):
        """PRD §3.9: "With two or more, the study's recorded pulls are ordered
        chronologically by `recorded_utc` with ties broken by `pull_index`;
        the growth rate is the change in hardness between the first and last
        recorded pulls divided by the elapsed days between their two readings,
        counted fractionally; and the projection is the first pull's hardness
        plus that rate multiplied by the study's full shelf length — the
        fractional day span from `start_utc` to `expiry_utc` — rounded half-up
        to two decimal places."
        PRD §3.9: "The failure rule is strict: the study automatically moves
        from `ACTIVE` to `FAILED` the moment a recorded pull pushes the
        projection strictly greater than `hardness_limit_n`, while a
        projection exactly equal to the limit passes."

        Design: Difficulty/boundary_precision_check/hardness_projection_strict_threshold
        """
        ns = fixtures.setup_study_pair(limit_a=152.86, limit_b=150.0)
        validate_success(
            client.record_pull(ns.st1["id"], record_pull_payload(
                hardness_n=58.0, recorded_utc="2026-08-08T00:00:00Z"), LT),
            201,
        )
        # 50.0 + (58.0-50.0)/7 * 90 = 152.8571... -> 152.86, exactly the limit.
        projection = validate_success(client.get_projection(ns.st1["id"], LT), 200)
        assert_2dp(projection["projected_hardness_at_expiry_n"], 152.86,
                   "projected_hardness_at_expiry_n")
        assert projection["will_fail"] is False
        assert projection["pulls_used"] == 2
        study = validate_success(client.get_shelf_life_study(ns.st1["id"], LT), 200)
        assert study["status"] == "ACTIVE"

    def test_projection_above_limit_auto_fails_study(self, api):
        """PRD §3.9: "The failure rule is strict: the study automatically
        moves from `ACTIVE` to `FAILED` the moment a recorded pull pushes the
        projection strictly greater than `hardness_limit_n`, while a
        projection exactly equal to the limit passes."

        Design: Difficulty/boundary_precision_check/hardness_projection_strict_threshold
        """
        ns = fixtures.setup_study_pair(limit_a=152.86, limit_b=150.0)
        validate_success(
            client.record_pull(ns.st2["id"], record_pull_payload(
                hardness_n=58.0, recorded_utc="2026-08-08T00:00:00Z"), LT),
            201,
        )
        # Identical pulls project 152.86 > 150.00 limit -> auto-FAILED.
        study = validate_success(client.get_shelf_life_study(ns.st2["id"], LT), 200)
        assert study["status"] == "FAILED"


class TestChamberPositionCapacity:
    def test_start_equal_to_other_expiry_collides(self, api):
        """PRD §3.9: "Chamber capacity is positional: at most one `ACTIVE`
        study may occupy a given chamber-and-shelf pair, and occupancy is
        measured over the closed interval from `start_utc` through
        `expiry_utc`, so a new study whose start exactly equals another active
        study's expiry still collides and is rejected with
        `ERR_CHAMBER_POSITION_OCCUPIED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/chamber_position_closed_interval_capacity
        """
        ns = fixtures.setup_approved_revision_for_study()
        fixtures.create_study(ns.r1["id"], chamber_id="CH1", shelf_position="P1")
        resp = client.create_shelf_life_study(
            {
                "revision_id": ns.r1["id"], "chamber_id": "CH1",
                "shelf_position": "P1", "start_utc": "2026-10-30T00:00:00Z",
                "expiry_utc": "2026-12-31T00:00:00Z", "hardness_limit_n": 200.0,
            },
            LT,
        )
        # Closed interval: 2026-10-30 is inside [2026-08-01, 2026-10-30].
        validate_error(resp, ApiErrorId.ERR_CHAMBER_POSITION_OCCUPIED, 409)

    def test_different_position_and_later_start_are_accepted(self, api):
        """PRD §3.9: "Chamber capacity is positional: at most one `ACTIVE`
        study may occupy a given chamber-and-shelf pair, and occupancy is
        measured over the closed interval from `start_utc` through
        `expiry_utc`, so a new study whose start exactly equals another active
        study's expiry still collides and is rejected with
        `ERR_CHAMBER_POSITION_OCCUPIED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/chamber_position_closed_interval_capacity
        """
        ns = fixtures.setup_approved_revision_for_study()
        fixtures.create_study(ns.r1["id"], chamber_id="CH1", shelf_position="P1")
        # Same instant on a different position: capacity is per position.
        other_position = validate_success(
            client.create_shelf_life_study(
                {
                    "revision_id": ns.r1["id"], "chamber_id": "CH1",
                    "shelf_position": "P2", "start_utc": "2026-10-30T00:00:00Z",
                    "expiry_utc": "2026-12-31T00:00:00Z", "hardness_limit_n": 200.0,
                },
                LT,
            ),
            201,
        )
        assert other_position["status"] == "ACTIVE"
        # One day after the inclusive end on the same position: no overlap.
        later = validate_success(
            client.create_shelf_life_study(
                {
                    "revision_id": ns.r1["id"], "chamber_id": "CH1",
                    "shelf_position": "P1", "start_utc": "2026-10-31T00:00:00Z",
                    "expiry_utc": "2027-01-15T00:00:00Z", "hardness_limit_n": 200.0,
                },
                LT,
            ),
            201,
        )
        assert later["status"] == "ACTIVE"

