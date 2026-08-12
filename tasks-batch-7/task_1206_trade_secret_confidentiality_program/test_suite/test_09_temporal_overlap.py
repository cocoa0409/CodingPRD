"""Temporal-overlap rules: NDA closed-interval windows and the clean-desk
audit seven-day department buffer (PRD §3.2, §3.9)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_nda_payload,
    create_clean_desk_audit_payload,
    make_counterparty_rep_headers,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestNdaClosedIntervalOverlap:
    def test_endpoint_touching_windows_conflict(self, api):
        """PRD §3.2: "Windows are closed intervals: the new window may not
        overlap any other non-terminal NDA of the same counterparty — one in
        `DRAFT`, `SENT`, `EXECUTED`, `ACTIVE`, or `BREACH_ALLEGED` — with
        touching boundary dates counting as overlap, otherwise
        `ERR_NDA_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/nda_closed_interval_touch_conflicts
        """
        cp = create_counterparty(legal_name="Lambda Warehousing", counterparty_type="VENDOR")
        validate_success(api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t10", governing_law="NV",
                effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
                survival_months=6, classification_ceiling="INTERNAL",
            ), IP
        ), expected_status=201)
        resp = api.create_nda(
            create_nda_payload(
                cp["id"], template_version="t10b", governing_law="NV",
                effective_date="2026-12-31T00:00:00Z", expiry_date="2027-06-30T00:00:00Z",
                survival_months=6, classification_ceiling="INTERNAL",
            ), IP
        )
        validate_error(resp, ApiErrorId.ERR_NDA_WINDOW_OVERLAP)

    def test_amendment_may_overlap_superseded_nda_and_activation_supersedes(self, api):
        """PRD §3.2: "The new agreement starts in `DRAFT` with its
        `supersedes_id` pointing at the target; the superseded agreement's
        `version` increments by one, since amendment linkage is itself a
        mutation of the parent; and the amendment's window may overlap the
        agreement it supersedes, though no other non-terminal NDA of the same
        counterparty."
        PRD §3.2: "Activation is counsel's step, and activating an amendment
        cascades: the agreement named by `supersedes_id` moves to `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/nda_closed_interval_touch_conflicts
        """
        cp = create_counterparty(legal_name="Lambda Warehousing", counterparty_type="VENDOR")
        nda1 = create_active_nda(
            cp["id"], template_version="t10", governing_law="NV",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
            survival_months=6, classification_ceiling="INTERNAL",
        )
        nda1_v = validate_success(api.get_nda(nda1["id"], IP))["version"]
        resp = api.create_nda_amendment(
            nda1["id"],
            {
                "template_version": "t11", "governing_law": "NV",
                "effective_date": "2026-06-01T00:00:00Z",
                "expiry_date": "2027-05-31T00:00:00Z",
                "survival_months": 12, "classification_ceiling": "CONFIDENTIAL",
                "expected_superseded_nda_version": nda1_v,
            },
            IP,
        )
        nda2 = validate_success(resp, expected_status=201)
        assert nda2["supersedes_id"] == nda1["id"]
        validate_success(api.transition_nda(nda2["id"], {"to_status": "SENT"}, IP))
        validate_success(api.transition_nda(
            nda2["id"], {"to_status": "EXECUTED"}, make_counterparty_rep_headers(cp["id"])
        ))
        validate_success(api.transition_nda(nda2["id"], {"to_status": "ACTIVE"}, IP))
        old = validate_success(api.get_nda(nda1["id"], IP))
        assert old["status"] == "SUPERSEDED"
        new = validate_success(api.get_nda(nda2["id"], IP))
        assert new["status"] == "ACTIVE"


class TestDepartmentAuditSevenDayBuffer:
    def test_six_day_gap_conflicts(self, api):
        """PRD §3.9: "Departments are buffered resources: a new audit is
        rejected with `ERR_AUDIT_WINDOW_CONFLICT` when the department already
        has a non-terminal audit — one in `SCHEDULED`, `CONDUCTED`, `REPORTED`,
        or `REMEDIATING` — within the required seven-day buffer."

        Design: Difficulty/resource_temporal_overlap/department_audit_seven_day_buffer
        """
        validate_success(api.create_clean_desk_audit(
            create_clean_desk_audit_payload(
                department="PLANT",
                window_start="2026-06-01T00:00:00Z",
                window_end="2026-06-02T00:00:00Z",
            ), SEC
        ), expected_status=201)
        resp = api.create_clean_desk_audit(
            create_clean_desk_audit_payload(
                department="PLANT",
                window_start="2026-06-08T00:00:00Z",
                window_end="2026-06-09T00:00:00Z",
            ), SEC
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_CONFLICT)

    def test_exactly_seven_day_gap_allowed_and_buffer_is_per_department(self, api):
        """PRD §3.9: "Departments are buffered resources: a new audit is
        rejected with `ERR_AUDIT_WINDOW_CONFLICT` when the department already
        has a non-terminal audit — one in `SCHEDULED`, `CONDUCTED`, `REPORTED`,
        or `REMEDIATING` — within the required seven-day buffer."

        Design: Difficulty/resource_temporal_overlap/department_audit_seven_day_buffer
        """
        validate_success(api.create_clean_desk_audit(
            create_clean_desk_audit_payload(
                department="PLANT",
                window_start="2026-06-01T00:00:00Z",
                window_end="2026-06-02T00:00:00Z",
            ), SEC
        ), expected_status=201)
        # Exactly 7 clear days after the 06-02 window end
        resp = api.create_clean_desk_audit(
            create_clean_desk_audit_payload(
                department="PLANT",
                window_start="2026-06-09T00:00:00Z",
                window_end="2026-06-10T00:00:00Z",
            ), SEC
        )
        validate_success(resp, expected_status=201)
        # A different department is unaffected by PLANT's audits
        resp = api.create_clean_desk_audit(
            create_clean_desk_audit_payload(
                department="LAB",
                window_start="2026-06-03T00:00:00Z",
                window_end="2026-06-04T00:00:00Z",
            ), SEC
        )
        validate_success(resp, expected_status=201)
