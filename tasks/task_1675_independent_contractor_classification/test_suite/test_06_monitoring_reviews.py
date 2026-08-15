"""Monitoring reviews: 30-day spacing rule and findings-count close outcomes."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_review,
    create_audit,
    create_remediation_action,
    finalize_audit,
    setup_engagement_at_state,
    validate_error,
    validate_paginated,
    validate_success,
)

_OFFICER = TEST_USERS["compliance_officer_headers"]


class TestReviewSpacing:
    def test_review_gap_29_days_rejected(self, api, compliance_officer_headers):
        """PRD §3.7: "Reviews of the same engagement must be spaced at least 30 days
        apart: the new `scheduled_date` must differ from every other review's
        `scheduled_date`, in either direction and regardless of the other review's
        status, by no less than 30 calendar days. Exactly 30 days is allowed; 29 days
        is rejected with `ERR_REVIEW_INTERVAL_TOO_SHORT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rto_review_minimum_gap_30_days
        """
        setup = setup_engagement_at_state("ACTIVE")
        engagement = setup["engagement"]
        validate_success(
            api.create_review(engagement["id"], {"scheduled_date": "2026-09-01"},
                              compliance_officer_headers),
            201,
        )
        # 2026-09-29 is 28 days after 2026-09-01: inside the 30-day buffer.
        res = api.create_review(engagement["id"], {"scheduled_date": "2026-09-29"},
                                compliance_officer_headers)
        validate_error(res, ApiErrorId.ERR_REVIEW_INTERVAL_TOO_SHORT.value)

    def test_review_gap_exactly_30_days_allowed(self, api, compliance_officer_headers):
        """PRD §3.7: "Exactly 30 days is allowed; 29 days is rejected with
        `ERR_REVIEW_INTERVAL_TOO_SHORT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rto_review_minimum_gap_30_days
        """
        setup = setup_engagement_at_state("ACTIVE")
        engagement = setup["engagement"]
        validate_success(
            api.create_review(engagement["id"], {"scheduled_date": "2026-09-01"},
                              compliance_officer_headers),
            201,
        )
        # 2026-10-01 is exactly 30 days after 2026-09-01: at the allowed boundary.
        res = api.create_review(engagement["id"], {"scheduled_date": "2026-10-01"},
                                compliance_officer_headers)
        review = validate_success(res, 201)
        assert_review(review)
        assert review["status"] == "SCHEDULED"


class TestReviewCloseOutcomes:
    def _setup_active_with_review(self):
        setup = setup_engagement_at_state("ACTIVE")
        return setup

    def test_review_close_zero_findings_cleared(self, api, compliance_officer_headers):
        """PRD §3.7: "At close, `findings_count` records the number of findings
        supplied, and the review's `outcome` is set to `CLEARED` when that count is
        zero and `FINDINGS_FILED` when it is one or more."
        PRD §3.7: closing takes "`findings` — a list of entries each pairing a
        `severity` of `LOW`, `MEDIUM`, or `HIGH` with a `description`, which may be an
        empty list".

        Design: Difficulty/boundary_precision_check/bpc_zero_findings_cleared_vs_one_finding
        """
        setup = self._setup_active_with_review()
        review = validate_success(
            api.create_review(setup["engagement"]["id"], {"scheduled_date": "2026-09-01"},
                              compliance_officer_headers),
            201,
        )
        closed = validate_success(
            api.close_review(review["id"], {"findings": [], "remediation_action_ids": []},
                             compliance_officer_headers),
            200,
        )
        assert closed["status"] == "CLOSED"
        assert closed["outcome"] == "CLEARED"
        assert closed["findings_count"] == 0

    def test_review_close_one_finding_filed(self, api, compliance_officer_headers):
        """PRD §3.7: "the review's `outcome` is set to `CLEARED` when that count is
        zero and `FINDINGS_FILED` when it is one or more."
        PRD §3.7: "When findings are present, `remediation_action_ids` must be
        non-empty and every referenced remediation action must be in `OPEN` status and
        belong to a risk audit of the same contractor as the review's engagement".

        Design: Difficulty/boundary_precision_check/bpc_zero_findings_cleared_vs_one_finding
        """
        setup = self._setup_active_with_review()
        engagement = setup["engagement"]
        contractor = setup["contractor"]
        review = validate_success(
            api.create_review(engagement["id"], {"scheduled_date": "2026-10-01"},
                              compliance_officer_headers),
            201,
        )
        # OPEN remediation action on a finalized audit of the same contractor.
        audit = create_audit(contractor["id"], engagement_id=engagement["id"])
        finalize_audit(audit["id"], [], "Minor documentation gap only")
        action = create_remediation_action(
            audit["id"], description="Collect updated W-9", severity="LOW",
            due_date="2026-10-15",
        )

        closed = validate_success(
            api.close_review(
                review["id"],
                {
                    "findings": [
                        {"severity": "MEDIUM", "description": "Contractor using company laptop"}
                    ],
                    "remediation_action_ids": [action["id"]],
                },
                compliance_officer_headers,
            ),
            200,
        )
        assert closed["status"] == "CLOSED"
        assert closed["outcome"] == "FINDINGS_FILED"
        assert closed["findings_count"] == 1

    def test_review_close_findings_without_actions_rejected(self, api, compliance_officer_headers):
        """PRD §3.7: "When findings are present, `remediation_action_ids` must be
        non-empty and every referenced remediation action must be in `OPEN` status and
        belong to a risk audit of the same contractor as the review's engagement;
        otherwise the close is rejected with `ERR_REVIEW_NOT_CLOSABLE` (HTTP 422)."

        Design: Corner/validations/val_review_close_findings_without_actions_rejected
        """
        setup = self._setup_active_with_review()
        review = validate_success(
            api.create_review(setup["engagement"]["id"], {"scheduled_date": "2026-09-01"},
                              compliance_officer_headers),
            201,
        )
        res = api.close_review(
            review["id"],
            {
                "findings": [
                    {"severity": "HIGH", "description": "Contractor embedded in standups"}
                ],
                "remediation_action_ids": [],
            },
            compliance_officer_headers,
        )
        validate_error(res, ApiErrorId.ERR_REVIEW_NOT_CLOSABLE.value)

        reviews, _ = validate_paginated(
            api.list_reviews(setup["engagement"]["id"], TEST_USERS["platform_admin_headers"])
        )
        remaining = [r for r in reviews if r["id"] == review["id"]]
        assert remaining and remaining[0]["status"] == "SCHEDULED"
