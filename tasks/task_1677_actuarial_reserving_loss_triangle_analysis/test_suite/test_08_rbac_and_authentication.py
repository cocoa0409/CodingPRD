"""Authentication and role-based access control (PRD §2.1, §4): anonymous
requests are unauthenticated, and each role is denied the operations outside
its desk.
"""
import pytest

from test_helpers import (
    ANONYMOUS_HEADERS,
    ApiErrorId,
    create_claim,
    create_opinion,
    create_segment,
    create_segment_payload,
    create_study,
    make_actuarial_analyst_headers,
    make_appointed_actuary_headers,
    make_peer_reviewer_headers,
    payment_payload,
    validate_error,
)


class TestAuthentication:
    @pytest.mark.parametrize(
        "headers",
        [
            pytest.param(ANONYMOUS_HEADERS, id="no_role_no_user"),
            pytest.param(
                {"X-User-Role": "AppointedActuary", "Content-Type": "application/json"},
                id="role_without_user_id",
            ),
        ],
    )
    def test_unauthenticated_request_rejected(self, api, headers):
        """PRD §2.1: "A request arriving without a valid role header — or, for
        any mutating request, without `X-User-ID` — is rejected with
        `ERR_UNAUTHENTICATED` (401)."
        PRD §2.1: "A fifth name, `Anonymous`, is a pseudo-role used only to
        describe requests sent without valid authentication headers."

        Design: Corner/validations/unauthenticated_request_rejected
        """
        resp = api.create_segment(
            create_segment_payload(
                name="Anon Book",
                line_of_business="PROPERTY",
                large_loss_threshold_cents=250000,
                max_range_width_pct=0.8,
                benchmark_open_severity_cents=30000,
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleDenial:
    def test_claims_examiner_cannot_create_reserve_run(self, api, claims_examiner_headers):
        """PRD §2.1: "When the role is valid but is not among the roles
        authorized for the target endpoint (see §4), the request is rejected
        with `ERR_FORBIDDEN` (403)."
        PRD §2.1: "An `ActuarialAnalyst` is the reserving preparer: triangles,
        development patterns, reserve runs, studies, and roll-forwards."

        Design: Corner/rbac/claims_examiner_cannot_create_reserve_run
        """
        segment = create_segment(
            name="RB Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        resp = api.create_reserve_run(
            {
                "segment_id": segment["id"],
                "valuation_quarter": "2025-Q1",
                "method": "CHAIN_LADDER",
                "basis": "PAID",
            },
            claims_examiner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_actuarial_analyst_cannot_sign_opinion(self, api):
        """PRD §2.1: "When the role is valid but is not among the roles
        authorized for the target endpoint (see §4), the request is rejected
        with `ERR_FORBIDDEN` (403)."
        PRD §2.1: "An `AppointedActuary` administers segments and catastrophe
        events, drafts and signs opinions, and sets the logical clock."

        Design: Corner/rbac/actuarial_analyst_cannot_sign_opinion
        """
        opinion = create_opinion(statement_date="2025-09-30", actuary_user_id="aa-1")
        resp = api.sign_opinion(
            opinion["id"], make_actuarial_analyst_headers("analyst-9")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_peer_reviewer_cannot_create_study(self, api):
        """PRD §2.1: "When the role is valid but is not among the roles
        authorized for the target endpoint (see §4), the request is rejected
        with `ERR_FORBIDDEN` (403)."
        PRD §2.1: "A `PeerReviewer` provides the independent review of
        submitted studies."

        Design: Corner/rbac/peer_reviewer_cannot_create_study
        """
        segment = create_segment(
            name="RB Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        resp = api.create_study(
            {
                "segment_id": segment["id"],
                "valuation_quarter": "2025-Q1",
                "selected_method": "CHAIN_LADDER",
                "selected_basis": "PAID",
            },
            make_peer_reviewer_headers("reviewer-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_appointed_actuary_cannot_post_claim_transactions(self, api):
        """PRD §2.1: "When the role is valid but is not among the roles
        authorized for the target endpoint (see §4), the request is rejected
        with `ERR_FORBIDDEN` (403)."
        PRD §2.1: "A `ClaimsExaminer` owns the claims desk: claim registration,
        financial transactions, claim lifecycle transitions, and catastrophe
        assignment."

        Design: Corner/rbac/appointed_actuary_cannot_post_claim_transactions
        """
        segment = create_segment(
            name="RB Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        claim = create_claim(
            segment["id"],
            claim_number="C-R",
            accident_date="2025-01-15",
            report_date="2025-01-20",
        )
        resp = api.post_claim_transaction(
            claim["id"],
            payment_payload(
                transaction_date="2025-02-01T00:00:00Z", amount_cents=1000
            ),
            make_appointed_actuary_headers("aa-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_actuarial_analyst_cannot_review_study(self, api):
        """PRD §2.1: "When the role is valid but is not among the roles
        authorized for the target endpoint (see §4), the request is rejected
        with `ERR_FORBIDDEN` (403)."
        PRD §2.1: "A `PeerReviewer` provides the independent review of
        submitted studies."

        Design: Corner/rbac/actuarial_analyst_cannot_review_study
        """
        segment = create_segment(
            name="RB Book",
            line_of_business="PROPERTY",
            large_loss_threshold_cents=250000,
            max_range_width_pct=0.8,
            benchmark_open_severity_cents=30000,
        )
        study = create_study(
            segment["id"], "2025-Q1", "CHAIN_LADDER", "PAID"
        )
        # Even an analyst who did not prepare the study is denied at the role layer.
        resp = api.review_study(
            study["id"],
            {"decision": "APPROVE"},
            make_actuarial_analyst_headers("analyst-2"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
