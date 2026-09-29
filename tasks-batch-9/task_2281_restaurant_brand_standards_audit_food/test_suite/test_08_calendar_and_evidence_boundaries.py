"""Inclusive boundaries: the unannounced mix floor and the evidence-photo minimum."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    api_client,
    audit_visit_payload,
    attach_action_photo,
    schedule_visit,
    setup_brand_program,
    setup_finalized_visit,
    validate_error,
    validate_paginated,
    validate_success,
)

MIX_WINDOWS = (
    ("UNANNOUNCED", "2026-08-05T09:00:00Z", "2026-08-05T13:00:00Z"),
    ("UNANNOUNCED", "2026-08-25T09:00:00Z", "2026-08-25T13:00:00Z"),
    ("ANNOUNCED", "2026-08-06T09:00:00Z", "2026-08-06T13:00:00Z"),
    ("ANNOUNCED", "2026-08-07T09:00:00Z", "2026-08-07T13:00:00Z"),
)


def _calendar_with_two_of_each():
    program = setup_brand_program()
    for visit_type, start_at, end_at in MIX_WINDOWS:
        schedule_visit(program, start_at, end_at, visit_type=visit_type)
    return program


class TestUnannouncedMixFloor:
    def test_a_resulting_mix_of_exactly_forty_percent_is_accepted(self):
        """A ratio equal to the brand minimum passes rather than failing.

        PRD: "Threshold comparisons throughout the system are inclusive at the boundary
        unless the text explicitly says "strictly": a composite score of exactly 90.00 earns
        `PASS`, a reliability score of exactly 70.00 clears certification, a variance of
        exactly 2.00 points lands in the `EXCELLENT` band, and an unannounced ratio exactly
        equal to the brand minimum passes."

        Design: Difficulty/boundary_precision_check/unannounced_mix_ratio_at_exactly_forty_percent_passes_then_falls_below
        """
        program = _calendar_with_two_of_each()

        candidate = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"],
            program["rubric_version"]["id"],
            "2026-08-08T09:00:00Z", "2026-08-08T13:00:00Z", visit_type="ANNOUNCED",
        )
        created = validate_success(
            api_client.create_audit_visit(candidate, ADMIN_HEADERS), expected_status=201,
        )
        assert created["status"] == "SCHEDULED", \
            "two unannounced of five visits is exactly the 40 percent floor"
        assert created["visit_type"] == "ANNOUNCED"
        assert created["announced_notice_hours"] == pytest.approx(177.00, abs=0.01), \
            "seven days and nine hours between the logical clock and the scheduled start"

        _, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 5

    def test_the_next_announced_visit_falls_below_the_floor(self):
        """One more announced visit dilutes the ratio to 33.33 and is refused.

        PRD: "The denominator is the number of visits so collected plus one for the
        candidate; the numerator is the number of collected visits whose `visit_type` is
        `UNANNOUNCED`, plus one more when the candidate itself is unannounced."

        Design: Difficulty/boundary_precision_check/unannounced_mix_ratio_at_exactly_forty_percent_passes_then_falls_below
        """
        program = _calendar_with_two_of_each()
        schedule_visit(
            program, "2026-08-08T09:00:00Z", "2026-08-08T13:00:00Z", visit_type="ANNOUNCED",
        )

        candidate = audit_visit_payload(
            program["location"]["id"], program["auditor"]["id"],
            program["rubric_version"]["id"],
            "2026-08-09T09:00:00Z", "2026-08-09T13:00:00Z", visit_type="ANNOUNCED",
        )
        validate_error(
            api_client.create_audit_visit(candidate, ADMIN_HEADERS),
            ApiErrorId.ERR_UNANNOUNCED_MIX_BELOW_MINIMUM,
            expected_status=422,
        )

        rows, meta = validate_paginated(api_client.list_audit_visits(ADMIN_HEADERS))
        assert meta["total_count"] == 5, "the sixth booking was not persisted"
        unannounced = [row for row in rows if row["visit_type"] == "UNANNOUNCED"]
        assert len(unannounced) == 2


class TestEvidencePhotoMinimum:
    def test_submitting_a_corrective_action_without_a_photo_is_refused(self):
        """Zero photos blocks the submission and leaves the action assigned.

        PRD: "The acting franchisee must be the action's `assigned_franchisee_id`, or
        `ERR_NOT_RESOURCE_OWNER` fires, and `evidence_photo_count` must be at least 1, or the
        submission is rejected with `ERR_EVIDENCE_REQUIRED`."

        Design: Difficulty/boundary_precision_check/evidence_photo_count_zero_blocks_corrective_action_submit_then_one_passes
        """
        program = setup_finalized_visit()
        action = program["actions"]["BS-1"]
        assert action["status"] == "ASSIGNED"
        assert action["evidence_photo_count"] == 0

        validate_error(
            api_client.submit_corrective_action(
                action["id"], program["franchisee_headers"],
                {"remediation_note": "Fixed, photographs to follow."},
            ),
            ApiErrorId.ERR_EVIDENCE_REQUIRED,
            expected_status=422,
        )

        reread = validate_success(
            api_client.get_corrective_action(action["id"], ADMIN_HEADERS)
        )
        assert reread["status"] == "ASSIGNED", "the refused submission is a no-op"
        assert reread["submission_count"] == 0
        assert reread["submitted_at"] is None
        assert reread["evidence_photo_count"] == 0

    def test_one_photo_is_enough_to_satisfy_the_evidence_requirement(self):
        """A single attached photo takes the count to the inclusive minimum of one.

        PRD: "When the photo names a corrective action, that action's `evidence_photo_count`
        rises by one."

        Design: Difficulty/boundary_precision_check/evidence_photo_count_zero_blocks_corrective_action_submit_then_one_passes
        """
        program = setup_finalized_visit()
        action = program["actions"]["BS-1"]

        photo = attach_action_photo(program, action["id"])
        assert photo["corrective_action_id"] == action["id"]
        assert photo.get("dispute_id") is None

        with_photo = validate_success(
            api_client.get_corrective_action(action["id"], ADMIN_HEADERS)
        )
        assert with_photo["evidence_photo_count"] == 1

        submitted = validate_success(
            api_client.submit_corrective_action(
                action["id"], program["franchisee_headers"],
                {"remediation_note": "Deficiency remediated and photographed."},
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_count"] == 1
        assert submitted["submitted_at"] is not None
