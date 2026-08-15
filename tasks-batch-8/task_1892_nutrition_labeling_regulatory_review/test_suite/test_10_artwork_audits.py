"""Artwork audits: scheduling scope and facility-buffer conflict rules,
finding-driven state transitions, and BINARY vs WEIGHTED conformance
scoring at close."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_artwork_audit,
    create_artwork_audit_payload,
    create_product,
    log_finding,
    schedule_audit,
    setup_released_label_with_audit,
    setup_released_wafer_label,
    setup_wafer_workspace,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestAuditScheduling:
    def test_audit_scope_inconsistent_rejected(self, api):
        """PRD §3.8: "Scope is enforced before scheduling: the product must
        belong to the path client, and the label version must belong to that
        product and currently be `RELEASED`, failing which the request is
        rejected with `ERR_AUDIT_SCOPE_INCONSISTENT`; the scheduled window
        must end strictly after it begins (`ERR_WINDOW_INVALID`); and the
        facility itself is a contended resource — among audits still
        `SCHEDULED` or `FINDINGS_LOGGED` at the same `facility_code`, the new
        window must respect the one-day buffer of §2.7, failing which
        `ERR_FACILITY_SCHEDULE_OVERLAP` is returned."

        Design: Corner/validations/val_audit_scope_inconsistent_rejected
        """
        ws = setup_wafer_workspace()  # label still DRAFT, never released
        resp = api.create_artwork_audit(
            ws["client"]["id"],
            create_artwork_audit_payload(
                ws["product"]["id"], ws["label"]["id"],
                "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_SCOPE_INCONSISTENT,
                       expected_status=422)

    def test_audit_filtered_list(self, api):
        """PRD §3.8: "Audit listings accept `client_id`, `product_id`, and
        `label_version_id` filters."

        Design: Corner/endpoints/ep_audit_filtered_list
        """
        ws = setup_released_label_with_audit()
        other_product = create_product(ws["client"], name="Cracker",
                                       product_category="SNACK", net_weight_g=30,
                                       total_surface_area_sq_in=20.0,
                                       include_household=False)

        data, meta = validate_paginated(
            api.list_artwork_audits(ADMIN,
                                    params={"product_id": ws["product"]["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == ws["audit"]["id"]

        data2, meta2 = validate_paginated(
            api.list_artwork_audits(ADMIN,
                                    params={"product_id": other_product["id"]}))
        assert data2 == []
        assert meta2["total_count"] == 0
        assert meta2["has_more"] is False


class TestFacilityBuffer:
    def test_audit_start_within_one_day_buffer_rejected(self, api):
        """PRD §2.7: "Artwork-audit facility scheduling uses a one-day buffer:
        a new audit window at a facility must begin no earlier than 86,400
        seconds after an existing window ends, or end no later than 86,400
        seconds before the existing window begins, with equality at the
        boundary permitted."

        Design: Difficulty/resource_temporal_overlap/audit_facility_buffer_boundary
        """
        ws = setup_released_label_with_audit(
            facility_code="F1",
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z")

        # Starts 12h after the existing window's end: inside the buffer.
        resp = api.create_artwork_audit(
            ws["client"]["id"],
            create_artwork_audit_payload(
                ws["product"]["id"], ws["label"]["id"],
                "2026-09-12T12:00:00Z", "2026-09-14T00:00:00Z",
                scoring_method="WEIGHTED", facility_code="F1"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FACILITY_SCHEDULE_OVERLAP,
                       expected_status=409)

    def test_audit_start_exactly_one_day_after_end_accepted(self, api):
        """PRD §2.7: "Artwork-audit facility scheduling uses a one-day buffer:
        a new audit window at a facility must begin no earlier than 86,400
        seconds after an existing window ends, or end no later than 86,400
        seconds before the existing window begins, with equality at the
        boundary permitted."
        PRD §3.8: "The audit opens in `SCHEDULED` status, with
        `conformance_score` and `result` empty until close."

        Design: Difficulty/resource_temporal_overlap/audit_facility_buffer_boundary
        """
        ws = setup_released_label_with_audit(
            facility_code="F1",
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z")

        # Starts exactly existing.end + 86400s: the boundary is permitted.
        audit = schedule_audit(ws["client"]["id"], ws["product"]["id"],
                               ws["label"]["id"], facility_code="F1",
                               scheduled_start="2026-09-13T00:00:00Z",
                               scheduled_end="2026-09-14T00:00:00Z",
                               scoring_method="BINARY")
        assert_artwork_audit(audit)
        assert audit["status"] == "SCHEDULED"


class TestConstraintPrecedesReferential:
    def test_facility_conflict_precedes_scope_mismatch(self, api):
        """PRD §2.8: "Every request is validated against a fixed priority
        sequence, and the first failing check determines the error returned."
        PRD §2.8: "6. **Uniqueness and overlap.** Duplicate RACC assignment
        (`ERR_RACC_ALREADY_ASSIGNED`), duplicate market variant
        (`ERR_DUPLICATE_MARKET_VARIANT`), variant window overlap
        (`ERR_MARKET_WINDOW_OVERLAP`), and facility scheduling conflicts
        (`ERR_FACILITY_SCHEDULE_OVERLAP`)."
        PRD §2.8: "8. **Referential and profile completeness.** Ingredient
        nutrient-profile completeness (`ERR_NUTRIENT_PROFILE_INCOMPLETE`),
        validated-lab availability (`ERR_NO_VALIDATED_LAB_ANALYSIS`), RACC
        category coverage (`ERR_RACC_CATEGORY_UNKNOWN`), serving-size
        resolvability (`ERR_SERVING_SIZE_UNRESOLVABLE`), RACC market alignment
        (`ERR_RACC_MARKET_MISMATCH`), distinct-market rule for variants
        (`ERR_SAME_MARKET_VARIANT`), and audit scope consistency
        (`ERR_AUDIT_SCOPE_INCONSISTENT`)."

        Design: Difficulty/priority_pair_validation_conflict/audit_create_constraint_beats_referential_rejected
        """
        ws_a = setup_released_label_with_audit(
            facility_code="F1",
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z")
        ws_b = setup_released_wafer_label()  # a second client's released label

        # Both violated: facility F1 window overlaps A1, and the label
        # version belongs to client B's product, not to product A.
        resp = api.create_artwork_audit(
            ws_a["client"]["id"],
            create_artwork_audit_payload(
                ws_a["product"]["id"], ws_b["label"]["id"],
                "2026-09-11T00:00:00Z", "2026-09-13T00:00:00Z",
                scoring_method="WEIGHTED", facility_code="F1"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FACILITY_SCHEDULE_OVERLAP,
                       expected_status=409)

    def test_scope_mismatch_reported_without_facility_conflict(self, api):
        """PRD §3.8: "Scope is enforced before scheduling: the product must
        belong to the path client, and the label version must belong to that
        product and currently be `RELEASED`, failing which the request is
        rejected with `ERR_AUDIT_SCOPE_INCONSISTENT`; the scheduled window
        must end strictly after it begins (`ERR_WINDOW_INVALID`); and the
        facility itself is a contended resource — among audits still
        `SCHEDULED` or `FINDINGS_LOGGED` at the same `facility_code`, the new
        window must respect the one-day buffer of §2.7, failing which
        `ERR_FACILITY_SCHEDULE_OVERLAP` is returned."

        Design: Difficulty/priority_pair_validation_conflict/audit_create_constraint_beats_referential_rejected
        """
        ws_a = setup_released_label_with_audit(
            facility_code="F1",
            scheduled_start="2026-09-10T00:00:00Z",
            scheduled_end="2026-09-12T00:00:00Z")
        ws_b = setup_released_wafer_label()

        # Control: with no facility conflict (different facility, distant
        # window), the referential scope rule is the one that fires.
        resp = api.create_artwork_audit(
            ws_a["client"]["id"],
            create_artwork_audit_payload(
                ws_a["product"]["id"], ws_b["label"]["id"],
                "2026-10-10T00:00:00Z", "2026-10-12T00:00:00Z",
                scoring_method="WEIGHTED", facility_code="F2"),
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_AUDIT_SCOPE_INCONSISTENT,
                       expected_status=422)


class TestAuditLifecycleAndScoring:
    def test_audit_close_from_scheduled_returns_invalid_state(self, api):
        """PRD §3.8: "Closing the audit is permitted only from
        `FINDINGS_LOGGED` — closing straight from `SCHEDULED` with zero
        findings is rejected with `ERR_INVALID_STATE_TRANSITION` — and it is
        at close that scoring runs."
        PRD §3.8: "The audit opens in `SCHEDULED` status, with
        `conformance_score` and `result` empty until close."

        Design: Corner/state_machines/sm_audit_close_from_scheduled_returns_invalid_state
        """
        ws = setup_released_label_with_audit()  # SCHEDULED, zero findings
        assert ws["audit"]["status"] == "SCHEDULED"
        resp = api.close_artwork_audit(ws["audit"]["id"], AUDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION,
                       expected_status=409)
        audit = validate_success(api.get_artwork_audit(ws["audit"]["id"], ADMIN))
        assert audit["status"] == "SCHEDULED"
        assert audit["conformance_score"] is None
        assert audit["result"] is None

    def test_binary_scoring_any_finding_fails(self, api):
        """PRD §3.8: "Under `BINARY`, the `conformance_score` is 100 when the
        audit has no findings and 0 otherwise, and the `result` is `PASS` only
        at a score of 100."
        PRD §3.8: "The first finding posted moves the audit from `SCHEDULED`
        to `FINDINGS_LOGGED` and increments its `version`; further findings
        may be posted while the audit remains `FINDINGS_LOGGED`."

        Design: Difficulty/dual_variant_calc/audit_scoring_binary_vs_weighted
        """
        ws = setup_released_label_with_audit(scoring_method="BINARY",
                                             facility_code="F1")
        log_finding(ws["audit"]["id"], severity="MAJOR",
                    field_ref="NUTRITION_VALUES",
                    on_pack_text="Calories 360", approved_text="Calories 367")
        mid = validate_success(api.get_artwork_audit(ws["audit"]["id"], ADMIN))
        assert mid["status"] == "FINDINGS_LOGGED", (
            "the first finding moves the audit to FINDINGS_LOGGED"
        )
        log_finding(ws["audit"]["id"], severity="MAJOR", field_ref="SERVING_SIZE",
                    on_pack_text="2 pieces (55g)",
                    approved_text="2 pieces (55.0g)")
        log_finding(ws["audit"]["id"], severity="MINOR", field_ref="FORMAT",
                    on_pack_text="rule hairline 0.5pt",
                    approved_text="rule hairline 0.25pt")

        closed = validate_success(api.close_artwork_audit(ws["audit"]["id"],
                                                          AUDITOR))
        assert closed["status"] == "CLOSED"
        assert closed["conformance_score"] == 0, "BINARY: any finding fails"
        assert closed["result"] == "FAIL"

    def test_weighted_scoring_deductions(self, api):
        """PRD §3.8: "Under `WEIGHTED`, the score starts at 100, deducts 10
        points per `CRITICAL` finding, 4 per `MAJOR`, and 1 per `MINOR`,
        floors at 0, and the `result` is `PASS` when the score is at least
        90."
        PRD §3.8: "The same finding set can therefore pass under the weighted
        method and fail under the binary one — the choice of `scoring_method`
        at scheduling time is a real compliance decision, and closing
        increments the audit's `version` one final time as `CLOSED`, its
        terminal state."

        Design: Difficulty/dual_variant_calc/audit_scoring_binary_vs_weighted
        """
        ws = setup_released_label_with_audit(scoring_method="WEIGHTED",
                                             facility_code="F2")
        log_finding(ws["audit"]["id"], severity="MAJOR",
                    field_ref="NUTRITION_VALUES",
                    on_pack_text="Calories 360", approved_text="Calories 367")
        log_finding(ws["audit"]["id"], severity="MAJOR", field_ref="SERVING_SIZE",
                    on_pack_text="2 pieces (55g)",
                    approved_text="2 pieces (55.0g)")
        log_finding(ws["audit"]["id"], severity="MINOR", field_ref="FORMAT",
                    on_pack_text="rule hairline 0.5pt",
                    approved_text="rule hairline 0.25pt")

        closed = validate_success(api.close_artwork_audit(ws["audit"]["id"],
                                                          AUDITOR))
        assert closed["status"] == "CLOSED"
        assert closed["conformance_score"] == 91, "100 - 4 - 4 - 1"
        assert closed["result"] == "PASS", "91 >= 90"
