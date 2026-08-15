"""Tier-matrix publication cascade: overlapping severity ranges supersede."""
from test_helpers import (
    validate_success, get_success_data,
    create_program, create_published_matrix,
    create_tier_matrix_payload,
)


class TestMatrixSeverityIntervalOverlapOnPublish:
    def test_touching_boundary_counts_as_overlap(self, api, program_admin_headers):
        """PRD §3.1: "Publishing a row moves it from `DRAFT` to `PUBLISHED` and, as a cascade, supersedes any prior `PUBLISHED` row of the same `injury_category` whose severity range overlaps the newly published row — the displaced row's `matrix_state` becomes `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/matrix_severity_interval_overlap_on_publish
        """
        program = create_program(program_code="MT-OVL1")
        pid = program["id"]
        row_a = create_published_matrix(pid, severity_score_min=0, severity_score_max=49,
                                        base_award_cents=3_000_000)
        row_b = get_success_data(api.create_tier_matrix(
            pid, create_tier_matrix_payload(severity_score_min=49, severity_score_max=100,
                                            base_award_cents=8_000_000),
            program_admin_headers,
        ))
        validate_success(api.publish_tier_matrix(pid, row_b["id"], program_admin_headers))
        a_after = validate_success(api.get_tier_matrix(pid, row_a["id"], program_admin_headers))
        b_after = validate_success(api.get_tier_matrix(pid, row_b["id"], program_admin_headers))
        assert a_after["matrix_state"] == "SUPERSEDED", (
            f"Row A [0,49] overlaps row B [49,100] at boundary 49; expected SUPERSEDED, got {a_after['matrix_state']}"
        )
        assert b_after["matrix_state"] == "PUBLISHED"

    def test_non_overlapping_range_leaves_prior_row_published(self, api, program_admin_headers):
        """PRD §3.1: "Publishing a row moves it from `DRAFT` to `PUBLISHED` and, as a cascade, supersedes any prior `PUBLISHED` row of the same `injury_category` whose severity range overlaps the newly published row — the displaced row's `matrix_state` becomes `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/matrix_severity_interval_overlap_on_publish
        """
        program = create_program(program_code="MT-OVL1B")
        pid = program["id"]
        row_a = create_published_matrix(pid, severity_score_min=0, severity_score_max=49,
                                        base_award_cents=3_000_000)
        row_b = create_published_matrix(pid, severity_score_min=50, severity_score_max=100,
                                        base_award_cents=8_000_000)
        a_after = validate_success(api.get_tier_matrix(pid, row_a["id"], program_admin_headers))
        b_after = validate_success(api.get_tier_matrix(pid, row_b["id"], program_admin_headers))
        assert a_after["matrix_state"] == "PUBLISHED", (
            f"Row A [0,49] does not overlap row B [50,100]; expected PUBLISHED, got {a_after['matrix_state']}"
        )
        assert b_after["matrix_state"] == "PUBLISHED"

    def test_matrix_published_flag_flips_true(self, api, program_admin_headers):
        """PRD §3.1: "Once at least one row reaches `PUBLISHED`, the program's `matrix_published` flag reads `true`."

        Design: Difficulty/resource_temporal_overlap/matrix_severity_interval_overlap_on_publish
        """
        program = create_program(program_code="MT-OVL1C")
        pid = program["id"]
        before = validate_success(api.get_program(pid, program_admin_headers))
        assert before["matrix_published"] is False
        create_published_matrix(pid, severity_score_min=0, severity_score_max=49,
                                base_award_cents=3_000_000)
        after = validate_success(api.get_program(pid, program_admin_headers))
        assert after["matrix_published"] is True
