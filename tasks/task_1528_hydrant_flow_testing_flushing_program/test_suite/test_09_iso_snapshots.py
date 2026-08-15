"""ISO rating snapshots: draft metrics, dual weighting profiles, publication
gates, and one-shot publish."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_iso_snapshot,
    api_client,
    TEST_USERS,
    create_program,
    create_iso_snapshot_payload,
    create_and_publish_snapshot,
    setup_iso_scenario,
    tag_hydrant_out,
    setup_program_zone_hydrant,
)

ADMIN = TEST_USERS["admin_headers"]
OP1 = TEST_USERS["operator_headers"]


class TestDraftSnapshot:
    def test_iso_snapshot_draft_metrics_null(self, api):
        """PRD §3.8: "The new snapshot starts in `DRAFT` with all four metric
        fields — `total_hydrants_in_scope`, `flow_coverage_pct`,
        `inspection_compliance_pct`, and `iso_points` — null until publish."

        Design: Corner/entities/iso_snapshot_draft_metrics_null
        """
        program, zone, hydrant = setup_program_zone_hydrant(
            hydrant_overrides={"required_fire_flow_gpm": 1500}
        )
        resp = api.create_iso_snapshot(
            program["id"], create_iso_snapshot_payload(weighting_profile="MUNICIPAL_ONLY"), ADMIN
        )
        snap = validate_success(resp, expected_status=201)
        assert_iso_snapshot(snap)
        assert snap["status"] == "DRAFT"
        for field in ("total_hydrants_in_scope", "flow_coverage_pct",
                      "inspection_compliance_pct", "iso_points"):
            assert snap.get(field) is None, (
                f"{field} must be null until publish, got {snap.get(field)}"
            )
        assert snap.get("published_at") is None


class TestWeightingProfiles:
    def test_iso_points_municipal_only_profile(self, api):
        """PRD §3.8: "Under `MUNICIPAL_ONLY`, a `MUNICIPAL` hydrant carries
        weight 1.0 and a `PRIVATE` hydrant is excluded entirely from both
        numerator and denominator."
        PRD §3.8: "The composite `iso_points` is 100 multiplied by the
        quantity: 0.6 times the flow coverage plus 0.4 times the inspection
        compliance, rounded half up to 1 decimal place. `total_hydrants_in_scope`
        is the sum of the weights."
        PRD §3.8: "A successful publish pins these metrics onto the snapshot,
        records `published_at` from the logical clock, moves the snapshot to
        `PUBLISHED`, and supersedes any other `PUBLISHED` snapshot for the same
        program — the prior snapshot moves to `SUPERSEDED` automatically."

        Design: Difficulty/dual_variant_calc/iso_points_municipal_only_vs_half_private
        """
        built = setup_iso_scenario()
        program_id = built["program"]["id"]

        snap_a = create_and_publish_snapshot(program_id, "MUNICIPAL_ONLY")
        snap_b = create_and_publish_snapshot(program_id, "ALL_HYDRANTS_HALF_PRIVATE")

        snap_a_after = validate_success(api.get_iso_snapshot(snap_a["id"], ADMIN))
        # municipal-only: flow 2/3, inspection 1/3 -> 100*(0.6*2/3 + 0.4*1/3) = 53.3
        assert snap_a_after["iso_points"] == 53.3, (
            f"municipal-only iso_points must be 53.3, got {snap_a_after['iso_points']}"
        )
        assert snap_a_after["total_hydrants_in_scope"] == 3
        assert snap_a_after["status"] == "SUPERSEDED", (
            "the first publish must be superseded by the second"
        )

    def test_iso_points_half_private_profile(self, api):
        """PRD §3.8: "Under `ALL_HYDRANTS_HALF_PRIVATE`, a `MUNICIPAL` hydrant
        carries weight 1.0 and a `PRIVATE` hydrant carries weight 0.5.
        Identical program data yields different scores under the two profiles."

        Design: Difficulty/dual_variant_calc/iso_points_municipal_only_vs_half_private
        """
        built = setup_iso_scenario()
        program_id = built["program"]["id"]

        snap_a = create_and_publish_snapshot(program_id, "MUNICIPAL_ONLY")
        snap_b = create_and_publish_snapshot(program_id, "ALL_HYDRANTS_HALF_PRIVATE")

        snap_b_after = validate_success(api.get_iso_snapshot(snap_b["id"], ADMIN))
        # half-private: flow 2.5/3.5, inspection 1.5/3.5
        # -> 100*(0.6*2.5/3.5 + 0.4*1.5/3.5) = 60.0
        assert snap_b_after["iso_points"] == 60.0, (
            f"half-private iso_points must be 60.0, got {snap_b_after['iso_points']}"
        )
        assert snap_b_after["total_hydrants_in_scope"] == 3.5
        assert snap_b_after["status"] == "PUBLISHED"


class TestPublishGates:
    def test_snapshot_publish_blocked_by_unacknowledged_notification(self, api):
        """PRD §3.8: "And the program's `unacknowledged_notification_count`
        must be zero — publication is blocked while any fire-department
        notification is still pending (else `ERR_UNACKNOWLEDGED_NOTIFICATIONS`)."

        Design: Corner/validations/snapshot_publish_blocked_by_unacknowledged_notification
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        tag_hydrant_out(hydrant["id"], reason="LEAK")  # notification PENDING
        snap = validate_success(api.create_iso_snapshot(
            program["id"], create_iso_snapshot_payload(weighting_profile="MUNICIPAL_ONLY"), ADMIN
        ), expected_status=201)

        resp = api.publish_iso_snapshot(snap["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNACKNOWLEDGED_NOTIFICATIONS, 409)

        after = validate_success(api.get_iso_snapshot(snap["id"], ADMIN))
        assert after["status"] == "DRAFT", "blocked publish must leave the snapshot DRAFT"

    def test_snapshot_publish_empty_program_rejected(self, api):
        """PRD §3.8: "The program must have at least one hydrant not in
        `DECOMMISSIONED` status (else `ERR_NO_HYDRANTS_IN_SCOPE`, HTTP 422)."

        Design: Corner/validations/snapshot_publish_empty_program_rejected
        """
        program = create_program()
        snap = validate_success(api.create_iso_snapshot(
            program["id"], create_iso_snapshot_payload(weighting_profile="MUNICIPAL_ONLY"), ADMIN
        ), expected_status=201)

        resp = api.publish_iso_snapshot(snap["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_HYDRANTS_IN_SCOPE, 422)

    def test_snapshot_republish_rejected(self, api):
        """PRD §3.8: "The snapshot must be `DRAFT` (else
        `ERR_SNAPSHOT_NOT_DRAFT`)."

        Design: Corner/validations/snapshot_republish_rejected
        """
        program, zone, hydrant = setup_program_zone_hydrant()
        snap = create_and_publish_snapshot(program["id"], "MUNICIPAL_ONLY")
        assert snap["status"] == "PUBLISHED"

        resp = api.publish_iso_snapshot(snap["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_NOT_DRAFT, 409)
