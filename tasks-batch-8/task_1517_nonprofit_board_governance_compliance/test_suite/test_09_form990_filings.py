"""Form 990 filings: derived fields, deadlines, review coverage, amendments."""
import pytest

import test_helpers as th
from test_helpers import fixtures as fx

ADMIN = th.TEST_USERS["governance_admin_headers"]


def _org_with_officers(api, ein, num_directors=1):
    """Org + bylaws + CHAIR + TREASURER + plain directors, all ACTIVE."""
    officers = ("CHAIR", "TREASURER")
    return fx.setup_org_with_board(num_directors=num_directors, officers=officers,
                                   ein=ein, receipts=1_000_000)


class TestFilingCreation:
    def test_form990_duplicate_root_filing_rejected(self, api):
        """PRD §3.8: "One root filing exists per nonprofit and fiscal year — a
        second root is rejected with `ERR_DUPLICATE_FILING` — while amendment
        filings carry a `supersedes_filing_id` pointing at the filing they replace,
        whose status must be `FILED` or `PUBLIC_DISCLOSED`, and are exempt from the
        uniqueness rule."

        Design: Corner/entities/form990_duplicate_root_filing_rejected
        """
        sc = _org_with_officers(api, "EIN-FD-1", num_directors=0)
        np_id = sc["nonprofit"]["id"]
        treasurer = sc["treasurer"]
        fx.create_filing(np_id, treasurer, 2025)

        resp = api.create_filing(
            th.create_filing_payload(np_id, 2025, total_revenue_cents=1,
                                     total_expenses_cents=1, contributions_cents=1,
                                     program_service_revenue_cents=0,
                                     preparer_user_id="staff-1"),
            th.headers_for_member(treasurer))
        th.validate_error(resp, th.ApiErrorId.ERR_DUPLICATE_FILING)

    def test_public_support_ratio_zero_revenue(self, api):
        """PRD §3.8: "At creation the system derives three fields:
        `net_change_cents` as total revenue minus total expenses;
        `public_support_ratio` as contributions divided by total revenue rounded
        half-up to 4 decimal places, defined as 0 when total revenue is zero; and
        `filing_due_date` from the fiscal calendar — the last day of the
        `fiscal_year_end_month` in the filing's fiscal year, then the first day of
        the following month, then four months and fourteen days forward, so a
        December year-end yields a May 15 deadline and a June year-end yields
        November 15."

        Design: Corner/calculations/public_support_ratio_zero_revenue
        """
        sc = _org_with_officers(api, "EIN-ZR-1", num_directors=0)
        np_id = sc["nonprofit"]["id"]
        treasurer = sc["treasurer"]
        filing = fx.create_filing(np_id, treasurer, 2026,
                                  total_revenue_cents=0, total_expenses_cents=50_000,
                                  contributions_cents=0,
                                  program_service_revenue_cents=0)
        assert filing["public_support_ratio"] == 0, (
            f"zero-revenue ratio is defined as 0, got {filing['public_support_ratio']}")
        assert filing["net_change_cents"] == -50_000, (
            f"net_change_cents = revenue - expenses = 0 - 50,000, got {filing['net_change_cents']}")


class TestFilingDeadlineAndLateFlag:
    def test_filing_deadline_and_late_flag(self, api):
        """PRD §3.8: "`filing_due_date` from the fiscal calendar — the last day of
        the `fiscal_year_end_month` in the filing's fiscal year, then the first day
        of the following month, then four months and fourteen days forward, so a
        December year-end yields a May 15 deadline and a June year-end yields
        November 15."
        PRD §3.8: "Marking the filing as filed with the IRS — by the `Treasurer` or
        `GovernanceAdmin` — stamps `filed_on` from the clock, computes `filed_late`
        as true only when the filing date falls strictly after the
        `filing_due_date` (filing exactly on the due date is timely), and moves the
        filing to `FILED`"

        Design: Corner/calculations/filing_deadline_and_late_flag
        """
        sc = _org_with_officers(api, "EIN-FL-1", num_directors=1)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer, d1 = sc["chair"], sc["treasurer"], sc["members"][2]

        f25 = fx.setup_filing_approved(np_id, treasurer, chair, [d1, treasurer], 2025)
        th.assert_instant_eq(f25["filing_due_date"], "2026-05-15T00:00:00Z",
            f"December FYE yields a May 15 deadline for FY2025, got {f25['filing_due_date']}")
        f26 = fx.setup_filing_approved(np_id, treasurer, chair, [d1, treasurer], 2026)
        th.assert_instant_eq(f26["filing_due_date"], "2027-05-15T00:00:00Z")

        filed25 = th.validate_success(api.mark_filed(
            f25["id"], th.headers_for_member(treasurer)))
        assert filed25["filed_late"] is True, (
            "filed 2026-08-01, strictly after the 2026-05-15 due date")
        filed26 = th.validate_success(api.mark_filed(
            f26["id"], th.headers_for_member(treasurer)))
        assert filed26["filed_late"] is False, (
            "filed 2026-08-01, before the 2027-05-15 due date")


class TestReviewCoverage:
    def test_review_coverage_exact_boundary_and_duplicate_review(self, api):
        """PRD §3.8: "Routing the draft to the board — a `Treasurer` or
        `GovernanceAdmin` act — requires an `ADOPTED` bylaws to measure coverage
        against (`ERR_BYLAWS_NOT_ADOPTED`), fixes the `review_required_count` as the
        ceiling of the bylaws' `quorum_pct` fraction of the `ACTIVE` member count on
        the `SEATED` basis regardless of the bylaws' own `quorum_basis`, and moves
        the filing to `IN_BOARD_REVIEW`."
        PRD §3.8: "Approval is the `BoardChair`'s act under two gates: the approver
        must differ from the `preparer_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and
        the count of recorded reviews must be at least the `review_required_count`
        (`ERR_REVIEW_COVERAGE_INSUFFICIENT`) — where reviews count only from members
        still `ACTIVE` at approve time, reviews by since-departed members being
        dropped from the count."
        PRD §3.8: "Directors then record their reviews as themselves: each review
        appends the caller's `X-User-ID` to `reviewed_by_member_ids`, the reviewer
        must be an `ACTIVE` member, and a member reviews a filing at most once
        (`ERR_DUPLICATE_REVIEW`)."

        Design: Corner/calculations/review_coverage_exact_boundary_and_duplicate_review
        """
        sc = _org_with_officers(api, "EIN-RC2-1", num_directors=1)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer, d1 = sc["chair"], sc["treasurer"], sc["members"][2]
        chair_headers = th.make_board_chair_headers(chair["id"])
        filing = fx.setup_filing_in_review(np_id, treasurer, 2026)
        # 3 ACTIVE members at quorum_pct 50 -> ceil(1.5) == 2
        assert filing["review_required_count"] == 2, (
            f"ceil(0.5 * 3) == 2 on the SEATED basis, got {filing['review_required_count']}")

        fx.record_review(filing["id"], d1)
        resp_cov = api.approve_filing(filing["id"], chair_headers)
        th.validate_error(resp_cov, th.ApiErrorId.ERR_REVIEW_COVERAGE_INSUFFICIENT)

        resp_dup = api.record_review(filing["id"], th.headers_for_member(d1))
        th.validate_error(resp_dup, th.ApiErrorId.ERR_DUPLICATE_REVIEW)

        fx.record_review(filing["id"], treasurer)
        approved = th.validate_success(api.approve_filing(filing["id"], chair_headers))
        assert approved["status"] == "APPROVED", (
            "coverage == required passes on >= (2 distinct reviews)")


class TestApprovePriorityPair:
    """Difficulty: priority_pair_validation_conflict / sod_safety_beats_review_coverage_aggregate."""

    def test_preparer_chair_approve_blocked_by_sod_before_coverage(self, api):
        """PRD §2.7: "When a request fails several rules at once, the error the
        caller receives is determined by a fixed order of precedence, evaluated from
        first to last:"
        PRD §2.7: "10. **Segregation of duties.** Same-user prohibitions —
        `ERR_SEGREGATION_OF_DUTIES`, `ERR_REVIEWER_MISMATCH`,
        `ERR_EVALUATION_RECORDER_MISMATCH` — each a 409 detailed in §3."
        PRD §2.7: "21. **Aggregate participation thresholds** at action time:
        `ERR_QUORUM_NOT_MET` and `ERR_REVIEW_COVERAGE_INSUFFICIENT` (409)."
        PRD §3.8: "Approval is the `BoardChair`'s act under two gates: the approver
        must differ from the `preparer_user_id` (`ERR_SEGREGATION_OF_DUTIES`), and
        the count of recorded reviews must be at least the `review_required_count`
        (`ERR_REVIEW_COVERAGE_INSUFFICIENT`)"

        Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_review_coverage_aggregate
        """
        sc = _org_with_officers(api, "EIN-PRIO-3", num_directors=1)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        # preparer_user_id IS the chair; zero reviews recorded -> both gates fail
        filing = fx.setup_filing_in_review(np_id, sc["treasurer"], 2026,
                                           preparer=chair["id"])
        resp = api.approve_filing(filing["id"],
                                  th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        after = th.validate_success(api.get_filing(filing["id"], ADMIN))
        assert after["status"] == "IN_BOARD_REVIEW", (
            "the rejected approval leaves the filing IN_BOARD_REVIEW")

    def test_coverage_gate_applies_when_sod_satisfied(self, api):
        """PRD §3.8: "Approval is the `BoardChair`'s act under two gates: the
        approver must differ from the `preparer_user_id`
        (`ERR_SEGREGATION_OF_DUTIES`), and the count of recorded reviews must be at
        least the `review_required_count` (`ERR_REVIEW_COVERAGE_INSUFFICIENT`) —
        where reviews count only from members still `ACTIVE` at approve time,
        reviews by since-departed members being dropped from the count."

        Design: Difficulty/priority_pair_validation_conflict/sod_safety_beats_review_coverage_aggregate
        """
        sc = _org_with_officers(api, "EIN-PRIO-3B", num_directors=1)
        np_id = sc["nonprofit"]["id"]
        chair = sc["chair"]
        # preparer is staff-1 (not the chair) -> only the coverage gate can fail
        filing = fx.setup_filing_in_review(np_id, sc["treasurer"], 2026,
                                           preparer="staff-1")
        assert filing["review_required_count"] == 2
        resp = api.approve_filing(filing["id"],
                                  th.make_board_chair_headers(chair["id"]))
        th.validate_error(resp, th.ApiErrorId.ERR_REVIEW_COVERAGE_INSUFFICIENT)


class TestPairedAmendments:
    """Difficulty: compensating_invariant / form990_net_position_conserved_across_paired_amendments."""

    def _setup_filed_root(self, api):
        sc = _org_with_officers(api, "EIN-990-1", num_directors=1)
        np_id = sc["nonprofit"]["id"]
        chair, treasurer, d1 = sc["chair"], sc["treasurer"], sc["members"][2]
        root = fx.setup_filing_filed(np_id, treasurer, chair, [d1, treasurer], 2025,
                                     preparer="staff-prep-1")
        return sc, chair, treasurer, d1, root

    def _file_amendment(self, api, sc, supersedes_id, **amounts):
        np_id = sc["nonprofit"]["id"]
        chair, treasurer, d1 = sc["chair"], sc["treasurer"], sc["members"][2]
        return fx.setup_filing_filed(np_id, treasurer, chair, [d1, treasurer], 2025,
                                     preparer="staff-prep-1",
                                     supersedes_filing_id=supersedes_id, **amounts)

    def test_amendment_supersedes_predecessor_chain(self, api):
        """PRD §3.8: "Marking the filing as filed with the IRS — by the `Treasurer`
        or `GovernanceAdmin` — stamps `filed_on` from the clock, computes
        `filed_late` as true only when the filing date falls strictly after the
        `filing_due_date` (filing exactly on the due date is timely), and moves the
        filing to `FILED`; when the filing is an amendment, its superseded target
        moves from `FILED` or `PUBLIC_DISCLOSED` to `SUPERSEDED` in the same act."

        Design: Difficulty/compensating_invariant/form990_net_position_conserved_across_paired_amendments
        """
        sc, _c, _t, _d, root = self._setup_filed_root(api)
        a2 = self._file_amendment(api, sc, root["id"],
                                  total_revenue_cents=110_000_000,
                                  contributions_cents=80_000_000)
        a3 = self._file_amendment(api, sc, a2["id"])
        assert a3["status"] == "FILED"

        root_after = th.validate_success(api.get_filing(root["id"], ADMIN))
        assert root_after["status"] == "SUPERSEDED", (
            "each supersession retires exactly one predecessor")
        a2_after = th.validate_success(api.get_filing(a2["id"], ADMIN))
        assert a2_after["status"] == "SUPERSEDED"

    def test_paired_amendments_conserve_net_position(self, api):
        """PRD §3.8: "At creation the system derives three fields:
        `net_change_cents` as total revenue minus total expenses;
        `public_support_ratio` as contributions divided by total revenue rounded
        half-up to 4 decimal places, defined as 0 when total revenue is zero; and
        `filing_due_date` from the fiscal calendar — the last day of the
        `fiscal_year_end_month` in the filing's fiscal year, then the first day of
        the following month, then four months and fourteen days forward, so a
        December year-end yields a May 15 deadline and a June year-end yields
        November 15."

        Design: Difficulty/compensating_invariant/form990_net_position_conserved_across_paired_amendments
        """
        sc, _c, _t, _d, root = self._setup_filed_root(api)
        assert root["net_change_cents"] == 40_000_000, (
            "100,000,000 - 60,000,000 reported net on the original filing")
        a2 = self._file_amendment(api, sc, root["id"],
                                  total_revenue_cents=110_000_000,
                                  contributions_cents=80_000_000)
        a3 = self._file_amendment(api, sc, a2["id"])
        assert a3["net_change_cents"] == 40_000_000, (
            "the paired +10,000,000 / -10,000,000 round trip conserves the net position")
        assert a3["status"] == "FILED", "the counter-amendment is the live filing of record"
