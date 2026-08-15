"""Special allocations: half-open window overlap, segregation of duties at
approval, request well-formedness, and the aggregate bound at lock time."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, PREPARER_USER_ID, REVIEWER_USER_ID,
    make_tax_preparer_headers, make_tax_reviewer_headers,
    create_fund, create_partner, create_tax_year, close_books,
    create_allocation_run, create_special_allocation_payload,
    create_and_approve_special_allocation, get_allocation_run,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]


def _fund_partner_year(api):
    fund = create_fund()
    partner = create_partner(fund["id"], legal_name="LP")
    ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
    return fund, partner, ty


def _propose(api, ty_id, partner_id, user_id=PREPARER_USER_ID, **overrides):
    resp = api.create_special_allocation(
        create_special_allocation_payload(ty_id, partner_id, **overrides),
        make_tax_preparer_headers(user_id),
    )
    return resp


class TestHalfOpenAdjacency:
    def _scenario(self, api):
        fund, partner, ty = _fund_partner_year(api)
        sa1 = create_and_approve_special_allocation(
            ty["id"], partner["id"], category="ORDINARY", target_pct_bps=4000,
            effective_from="2025-01-01", effective_to="2025-07-01",
        )
        sa2 = create_and_approve_special_allocation(
            ty["id"], partner["id"], category="ORDINARY", target_pct_bps=4000,
            effective_from="2025-07-01", effective_to="2026-01-01",
        )
        sa3 = validate_success(
            _propose(
                api, ty["id"], partner["id"], category="ORDINARY", target_pct_bps=1000,
                effective_from="2025-06-01", effective_to="2025-08-01",
            ),
            201,
        )
        return sa1, sa2, sa3

    def test_touching_half_open_windows_both_approve(self, api):
        """PRD §3.4: "Approval by a `TaxReviewer` enforces three conditions: the
        approver’s `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; the half-open window must not intersect
        any other `PROPOSED` or `APPROVED` special allocation with the same tax
        year, partner, and category — windows that merely touch, one’s
        `effective_to` equal to the other’s `effective_from`, do not overlap —
        else `ERR_SPECIAL_ALLOCATION_OVERLAP`; and the tax year must be `OPEN`
        or `BOOKS_CLOSED`, approval after the year is `ALLOCATED` being
        rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/special_allocation_half_open_adjacency
        """
        sa1, sa2, sa3 = self._scenario(api)
        assert sa1["status"] == "APPROVED", "SA1 [01-01, 07-01) must approve"
        assert sa2["status"] == "APPROVED", (
            "SA2 [07-01, 2026-01-01) touches SA1 at 2025-07-01 and must approve"
        )

    def test_intersecting_window_rejected(self, api):
        """PRD §3.4: "Approval by a `TaxReviewer` enforces three conditions: the
        approver’s `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; the half-open window must not intersect
        any other `PROPOSED` or `APPROVED` special allocation with the same tax
        year, partner, and category — windows that merely touch, one’s
        `effective_to` equal to the other’s `effective_from`, do not overlap —
        else `ERR_SPECIAL_ALLOCATION_OVERLAP`; and the tax year must be `OPEN`
        or `BOOKS_CLOSED`, approval after the year is `ALLOCATED` being
        rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`."

        Design: Difficulty/resource_temporal_overlap/special_allocation_half_open_adjacency
        """
        sa1, sa2, sa3 = self._scenario(api)
        resp = api.approve_special_allocation(sa3["id"], make_tax_reviewer_headers(REVIEWER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SPECIAL_ALLOCATION_OVERLAP)
        after = validate_success(api.get_special_allocation(sa3["id"], REVIEWER), 200)
        assert after["status"] == "PROPOSED"


class TestSpecialAllocationRules:
    def test_special_allocation_inverted_window_returns_invalid_request(self, api):
        """PRD §2.8: "Request well-formedness — required fields are present,
        enum values are valid, and integer and date ranges are sane:
        basis-point shares between one and ten thousand inclusive, quarter
        between one and four, event amounts non-zero, `effective_from` strictly
        before `effective_to`, and `settlement_date` on or after
        `effective_date`, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/special_allocation_inverted_window_returns_invalid_request
        """
        fund, partner, ty = _fund_partner_year(api)
        resp = _propose(
            api, ty["id"], partner["id"], category="ORDINARY", target_pct_bps=1000,
            effective_from="2025-07-01", effective_to="2025-07-01",
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_special_allocation_approve_by_proposer_rejected_sod(self, api):
        """PRD §3.4: "Approval by a `TaxReviewer` enforces three conditions:
        the approver’s `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SEGREGATION_OF_DUTIES`; the half-open window must not intersect
        any other `PROPOSED` or `APPROVED` special allocation with the same tax
        year, partner, and category — windows that merely touch, one’s
        `effective_to` equal to the other’s `effective_from`, do not overlap —
        else `ERR_SPECIAL_ALLOCATION_OVERLAP`; and the tax year must be `OPEN`
        or `BOOKS_CLOSED`, approval after the year is `ALLOCATED` being
        rejected with `ERR_TAX_YEAR_WINDOW_CLOSED`."

        Design: Corner/validations/special_allocation_approve_by_proposer_rejected_sod
        """
        fund, partner, ty = _fund_partner_year(api)
        sa = validate_success(
            _propose(api, ty["id"], partner["id"], target_pct_bps=4000), 201,
        )
        assert sa["proposed_by_user_id"] == PREPARER_USER_ID
        # a TaxReviewer header carrying the proposer's user id is still the proposer
        resp = api.approve_special_allocation(sa["id"], make_tax_reviewer_headers(PREPARER_USER_ID))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        after = validate_success(api.get_special_allocation(sa["id"], REVIEWER), 200)
        assert after["status"] == "PROPOSED"

    def test_special_allocation_overflow_at_lock(self, api):
        """PRD §3.5: "And for each category, the sum of `target_pct_bps` across
        the tax year’s `APPROVED` special allocations must not exceed ten
        thousand basis points, else `ERR_SPECIAL_ALLOCATION_OVERFLOW`."

        Design: Corner/validations/special_allocation_overflow_at_lock
        """
        fund, partner, ty = _fund_partner_year(api)
        close_books(ty["id"])
        create_and_approve_special_allocation(
            ty["id"], partner["id"], category="ORDINARY", target_pct_bps=6000,
            effective_from="2025-01-01", effective_to="2025-07-01",
        )
        create_and_approve_special_allocation(
            ty["id"], partner["id"], category="ORDINARY", target_pct_bps=6000,
            effective_from="2025-07-01", effective_to="2026-01-01",
        )
        run = create_allocation_run(ty["id"], run_kind="FINAL")
        resp = api.lock_allocation_run(run["id"], REVIEWER)
        validate_error(resp, ApiErrorId.ERR_SPECIAL_ALLOCATION_OVERFLOW)
        assert get_allocation_run(run["id"])["status"] == "COMPUTED", (
            "a lock rejected in aggregate must leave the run COMPUTED"
        )
