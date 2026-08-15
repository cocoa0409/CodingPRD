"""Circulation audit records: period sanity and the single-draft rule."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    assert_circulation_audit_record,
    create_publication,
    set_clock,
    CM,
)

CM_H = TEST_USERS["circulation_manager_headers"]


class TestAuditPeriodValidation:
    def test_audit_period_end_before_start_rejected(self, api):
        """The audit window's end must be strictly later than its start.

        PRD §3.8: "A `CirculationManager` opens a **CirculationAuditRecord** on a publication by giving the six-month audit window's `audit_period_start` and `audit_period_end`; the end must be strictly later than the start (`ERR_INVALID_AUDIT_PERIOD` otherwise), and only one audit per publication may sit in `DRAFT` at a time (`ERR_DRAFT_AUDIT_EXISTS`)."

        Design: Corner/validations/invalid_audit_period_end_before_start_rejected
        """
        set_clock()
        pub = create_publication()
        resp = api.create_circulation_audit(
            pub["id"],
            {
                "audit_period_start": "2026-06-30T00:00:00Z",
                "audit_period_end": "2026-01-01T00:00:00Z",
            },
            CM_H,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_AUDIT_PERIOD, 422)


class TestSingleDraftAudit:
    def test_second_draft_audit_rejected(self, api):
        """While one audit sits in DRAFT, opening a second — even with a
        well-formed period — is rejected with ERR_DRAFT_AUDIT_EXISTS.

        PRD §3.8: "A `CirculationManager` opens a **CirculationAuditRecord** on a publication by giving the six-month audit window's `audit_period_start` and `audit_period_end`; the end must be strictly later than the start (`ERR_INVALID_AUDIT_PERIOD` otherwise), and only one audit per publication may sit in `DRAFT` at a time (`ERR_DRAFT_AUDIT_EXISTS`)."

        Design: Difficulty/resource_temporal_overlap/audit_period_overlap_exclusive_boundary
        """
        set_clock()
        pub = create_publication()
        first = validate_success(
            api.create_circulation_audit(
                pub["id"],
                {
                    "audit_period_start": "2026-01-01T00:00:00Z",
                    "audit_period_end": "2026-06-30T23:59:59Z",
                },
                CM_H,
            ), 201,
        )
        assert_circulation_audit_record(first)
        assert first["status"] == "DRAFT"

        resp = api.create_circulation_audit(
            pub["id"],
            {
                "audit_period_start": "2026-06-01T00:00:00Z",
                "audit_period_end": "2026-11-30T23:59:59Z",
            },
            CM_H,
        )
        validate_error(resp, ApiErrorId.ERR_DRAFT_AUDIT_EXISTS, 422)

    def test_new_draft_allowed_after_prior_audit_filed(self, api):
        """The single-DRAFT rule binds only while the earlier audit is still
        DRAFT: once it is FILED (no issues in the window, so nothing blocks
        filing), a fresh audit opens cleanly in DRAFT with qualification
        PENDING. The filed audit's figures compute over an empty period: zero
        distribution, zero paid share, hence NON_QUALIFIED for a PAID title.

        PRD §3.8: "A `CirculationManager` opens a **CirculationAuditRecord** on a publication by giving the six-month audit window's `audit_period_start` and `audit_period_end`; the end must be strictly later than the start (`ERR_INVALID_AUDIT_PERIOD` otherwise), and only one audit per publication may sit in `DRAFT` at a time (`ERR_DRAFT_AUDIT_EXISTS`). While drafted, the record's `qualification_result` is `PENDING`."
        PRD §3.8: "Filing the audit — a `CirculationManager` action moving it from `DRAFT` to `FILED` — requires every issue whose `mail_date` falls within the period, start and end inclusive, to be `FINALIZED`; an unfiled pipeline issue in the window is rejected with `ERR_UNFILED_ISSUES_IN_PERIOD`."
        PRD §3.8: "Filing computes the record's figures: `total_distribution`, the sum of issues mailed during the period; `paid_distribution`, the portion served to `PAID_QUALIFIED` subscribers; `controlled_distribution`, the portion served to `CONTROLLED_QUALIFIED` subscribers; the `paid_percentage_bps` under the truncation rule of §3.4; and the `qualification_result` under the standard qualification rule — a `PAID` publication qualifies when its paid share is at least seventy percent (7000 basis points, the boundary itself qualifying), a `CONTROLLED` publication qualifies when its paid share is at most thirty percent (3000 basis points, again inclusively), and a `MIXED` publication qualifies when its paid share lies between thirty and seventy percent inclusive; anything else is `NON_QUALIFIED`."

        Design: Difficulty/resource_temporal_overlap/audit_period_overlap_exclusive_boundary
        """
        set_clock()
        pub = create_publication()
        first = validate_success(
            api.create_circulation_audit(
                pub["id"],
                {
                    "audit_period_start": "2026-01-01T00:00:00Z",
                    "audit_period_end": "2026-06-30T23:59:59Z",
                },
                CM_H,
            ), 201,
        )

        filed = validate_success(api.file_circulation_audit(pub["id"], first["id"], CM_H))
        assert filed["status"] == "FILED"
        assert filed["total_distribution"] == 0
        assert filed["paid_percentage_bps"] == 0
        assert filed["qualification_result"] == "NON_QUALIFIED", (
            "a PAID publication qualifies only at seventy percent paid or better; "
            f"zero paid share cannot qualify, got {filed['qualification_result']}"
        )

        second = validate_success(
            api.create_circulation_audit(
                pub["id"],
                {
                    "audit_period_start": "2026-07-01T00:00:00Z",
                    "audit_period_end": "2026-12-31T23:59:59Z",
                },
                CM_H,
            ), 201,
        )
        assert_circulation_audit_record(second)
        assert second["status"] == "DRAFT"
        assert second["qualification_result"] == "PENDING"
