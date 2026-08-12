"""Temporal overlap — half-open custody intervals and strict staffing-plan
overlap (difficulty rule resource_temporal_overlap)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_call_center_staffing_plan_payload,
    create_custody_log_payload,
    create_evidence_item_payload,
    create_incident,
    create_incident_confirmed,
    get_success_data,
    validate_error,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
FL = TEST_USERS["forensic_lead_headers"]


class TestCustodyLogHalfOpenInterval:
    def test_touching_edges_allowed_strict_overlap_rejected(self, api):
        """PRD §3.2: "Custody intervals are half-open `[start_at, end_at)`,
        so an existing interval may not be overlapped by a new one for the
        same `evidence_item_id`; an overlap is rejected with
        `ERR_CUSTODY_OVERLAP` (409)."

        Touching edges (new.start == prior.end) do not overlap under
        half-open semantics and are allowed.

        Design: Difficulty/resource_temporal_overlap/custody_log_half_open_interval_no_overlap
        """
        inc = create_incident()
        ev = validate_success(
            api.create_evidence_item(
                inc["id"], create_evidence_item_payload(), FL
            ),
            expected_status=201,
        )
        # Existing custody: [10:00, 12:00).
        log1_resp = api.create_custody_log(
            inc["id"],
            create_custody_log_payload(
                ev["id"],
                custodian_user_id="u1",
                start_at="2026-05-01T10:00:00Z",
                end_at="2026-05-01T12:00:00Z",
                purpose="intake",
            ),
            FL,
        )
        validate_success(log1_resp, expected_status=201)

        # Touching edge [12:00, 14:00): allowed under half-open semantics.
        log2_resp = api.create_custody_log(
            inc["id"],
            create_custody_log_payload(
                ev["id"],
                custodian_user_id="u2",
                start_at="2026-05-01T12:00:00Z",
                end_at="2026-05-01T14:00:00Z",
                purpose="handoff",
            ),
            FL,
        )
        log2 = validate_success(log2_resp, expected_status=201)
        assert log2["custodian_user_id"] == "u2"

        # Strict overlap [13:00, 15:00) against [12:00, 14:00): rejected.
        overlap_resp = api.create_custody_log(
            inc["id"],
            create_custody_log_payload(
                ev["id"],
                custodian_user_id="u3",
                start_at="2026-05-01T13:00:00Z",
                end_at="2026-05-01T15:00:00Z",
                purpose="overlap attempt",
            ),
            FL,
        )
        validate_error(
            overlap_resp, ApiErrorId.ERR_CUSTODY_OVERLAP.value, expected_status=409
        )


class TestStaffingPlanStrictOverlap:
    def test_touching_edge_allowed_strict_overlap_rejected(self, api):
        """PRD §3.10: "its interval must not partially overlap the interval
        of any other `ACTIVE` plan for the same incident — half-open
        `[effective_from, effective_until)` semantics, with touching edges
        permitted; violations are rejected with `ERR_STAFFING_PLAN_OVERLAP`
        (409)."

        Design: Difficulty/resource_temporal_overlap/staffing_plan_overlap_strict_only
        """
        ctx = create_incident_confirmed()
        inc = ctx["incident"]
        # Existing ACTIVE plan [2026-05-02, 2026-06-02).
        plan1 = validate_success(
            api.create_call_center_staffing_plan(
                inc["id"],
                create_call_center_staffing_plan_payload(
                    effective_from="2026-05-02T00:00:00Z",
                    effective_until="2026-06-02T00:00:00Z",
                    languages_supported=["en"],
                ),
                IC,
            ),
            expected_status=201,
        )
        # Touching-edge plan [2026-06-02, 2026-07-02): permitted.
        plan2_resp = api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                effective_from="2026-06-02T00:00:00Z",
                effective_until="2026-07-02T00:00:00Z",
                languages_supported=["en"],
            ),
            IC,
        )
        plan2 = validate_success(plan2_resp, expected_status=201)
        assert plan2["status"] == "ACTIVE"

        # Strict overlap [2026-06-01, 2026-07-15) with [2026-05-02, 2026-06-02)
        # and [2026-06-02, 2026-07-02): rejected.
        overlap_resp = api.create_call_center_staffing_plan(
            inc["id"],
            create_call_center_staffing_plan_payload(
                effective_from="2026-06-01T00:00:00Z",
                effective_until="2026-07-15T00:00:00Z",
                languages_supported=["en"],
            ),
            IC,
        )
        validate_error(
            overlap_resp,
            ApiErrorId.ERR_STAFFING_PLAN_OVERLAP.value,
            expected_status=409,
        )
