"""Probate filings and the CONTESTED branching/revert workflow.

Coverage targets (PRD §3.7, §3.8):
- Filing SUBMITTED on create.
- Non-PETITION filings require CONFIRMED EXECUTOR fiduciary
  (ERR_FILING_NOT_PERMITTED).
- ACCEPTED/REJECTED/REVISION_REQUESTED court rulings + reason
  required.
- ERR_FILING_ALREADY_PENDING — second SUBMITTED of same type.
- CONTESTED cascade: SUBMITTED filings → REVISION_REQUESTED with
  reason 'estate_contested', estate.contested_at set.
- CONTESTED → IN_PROBATE requires no REVISION_REQUESTED filings.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_filing_payload,
    estate_state_payload,
    filing_state_payload,
    get_success_data,
    nominate_fiduciary,
    re_get_estate,
    setup_in_probate,
    setup_in_probate_for_contested_filing_cascade,
    setup_inventory_report_submitted,
    submit_filing,
    transition_filing,
    validate_error,
    validate_success,
)


class TestFilingSubmit:

    def test_non_petition_filing_requires_confirmed_executor(self, api):
        """PRD §3.7: "For every non-petition filing type, the
        submitting fiduciary must be a Fiduciary with scope_type
        EXECUTOR and status CONFIRMED; if not, the filing is
        rejected with ERR_FILING_NOT_PERMITTED."

        Claim: non-PETITION filing by a NOMINATED (not CONFIRMED)
        EXECUTOR -> ERR_FILING_NOT_PERMITTED.
        """
        from test_helpers import create_estate_with_executor
        estate, executor, exec_h = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        # Executor is NOMINATED, not CONFIRMED.
        resp = api_client.create_filing(
            estate["id"],
            create_filing_payload(
                filing_type="INVENTORY_REPORT",
                filed_by_fiduciary_id=executor["id"],
            ),
            exec_h,
        )
        validate_error(resp,
                       ApiErrorId.ERR_FILING_NOT_PERMITTED.value)

    def test_petition_filing_is_exempt_from_confirm_first(self, api):
        """PRD §3.7: "Petitions to probate are exempt from that
        confirm-first rule because they precede confirmation."

        Claim: PETITION_TO_PROBATE submitted by NOMINATED (not
        CONFIRMED) executor succeeds.
        """
        from test_helpers import create_estate_with_executor
        estate, executor, exec_h = create_estate_with_executor(
            bond_amount_cents=25_000,
        )
        resp = api_client.create_filing(
            estate["id"],
            create_filing_payload(
                filing_type="PETITION_TO_PROBATE",
                filed_by_fiduciary_id=executor["id"],
            ),
            exec_h,
        )
        filing = validate_success(resp, expected_status=201)
        assert filing["status"] == "SUBMITTED"


class TestFilingAlreadyPending:

    def test_second_submitted_same_type_rejected(self, api):
        """PRD §3.7: "Two distinct filings of the same type cannot
        both sit in SUBMITTED at the same time on the same estate.
        If an executor attempts to create a second INVENTORY_REPORT
        (for instance) while the first is still SUBMITTED, the
        second create races against the first; the loser receives
        ERR_FILING_ALREADY_PENDING with HTTP 409."

        Claim: second INVENTORY_REPORT while first is SUBMITTED ->
        ERR_FILING_ALREADY_PENDING.
        """
        bundle = setup_inventory_report_submitted()
        estate = bundle["estate"]
        executor = bundle["executor"]
        exec_h = bundle["executor_headers"]
        resp = api_client.create_filing(
            estate["id"],
            create_filing_payload(
                filing_type="INVENTORY_REPORT",
                filed_by_fiduciary_id=executor["id"],
            ),
            exec_h,
        )
        validate_error(
            resp, ApiErrorId.ERR_FILING_ALREADY_PENDING.value,
        )


class TestFilingCourtTransitions:

    def test_reject_without_reason_rejected(self, api):
        """PRD §3.7: "reject it outright (moving it to REJECTED with
        a required rejection_reason) ... a missing reason on either
        of the last two yields ERR_BAD_REQUEST."

        Claim: REJECTED without rejection_reason -> ERR_BAD_REQUEST.
        """
        bundle = setup_inventory_report_submitted()
        estate = bundle["estate"]
        filing = bundle["inventory_filing"]
        resp = api_client.transition_filing(
            estate["id"], filing["id"],
            filing_state_payload("REJECTED"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_revision_requested_without_reason_rejected(self, api):
        """PRD §3.7: same — REVISION_REQUESTED also requires a
        rejection_reason; missing it yields ERR_BAD_REQUEST.

        Claim: REVISION_REQUESTED without rejection_reason ->
        ERR_BAD_REQUEST.
        """
        bundle = setup_inventory_report_submitted()
        estate = bundle["estate"]
        filing = bundle["inventory_filing"]
        resp = api_client.transition_filing(
            estate["id"], filing["id"],
            filing_state_payload("REVISION_REQUESTED"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


class TestContestedCascade:

    def test_contested_marks_submitted_filings_revision_requested(
        self, api,
    ):
        """PRD §3.8: "On entering CONTESTED, the estate's
        contested_at is set to the current clock, and every
        ProbateFiling for the estate currently in SUBMITTED is moved
        to REVISION_REQUESTED with rejection_reason set to
        'estate_contested'."

        Claim: after CONTESTED, any SUBMITTED filing -> status
        REVISION_REQUESTED with rejection_reason='estate_contested'.
        """
        bundle = setup_in_probate_for_contested_filing_cascade()
        estate = bundle["estate"]
        filing = bundle["inventory_filing"]
        # CourtClerk advances IN_PROBATE -> CONTESTED.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("CONTESTED"),
            TEST_USERS["court_clerk_headers"],
        )
        estate_after = validate_success(resp)
        assert estate_after["admin_phase"] == "CONTESTED"
        assert estate_after.get("contested_at"), (
            "contested_at must be set on CONTESTED"
        )
        # Re-read filing.
        f_after = get_success_data(
            api_client.get_filing(
                estate["id"], filing["id"],
                TEST_USERS["court_clerk_headers"],
            ),
        )
        assert f_after["status"] == "REVISION_REQUESTED", (
            f"filing must be REVISION_REQUESTED after estate "
            f"contested, got {f_after['status']!r}"
        )
        assert f_after.get("rejection_reason") == "estate_contested", (
            f"rejection_reason must be 'estate_contested', got "
            f"{f_after.get('rejection_reason')!r}"
        )

    def test_contested_to_in_probate_requires_no_revision_pending(
        self, api,
    ):
        """PRD §3.8: "The clerk may later resolve the contest by
        transitioning the estate back from CONTESTED to IN_PROBATE;
        the resolution is conditional — no ProbateFiling may remain
        in REVISION_REQUESTED, otherwise ERR_FILINGS_PENDING."

        Claim: with at least one REVISION_REQUESTED filing,
        CONTESTED -> IN_PROBATE -> ERR_FILINGS_PENDING.
        """
        bundle = setup_in_probate_for_contested_filing_cascade()
        estate = bundle["estate"]
        # CONTEST the estate (creates REVISION_REQUESTED filing).
        api_client.transition_estate(
            estate["id"], estate_state_payload("CONTESTED"),
            TEST_USERS["court_clerk_headers"],
        )
        # Attempt to resolve.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"),
            TEST_USERS["court_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FILINGS_PENDING.value)

    def test_contested_clears_when_resolved(self, api):
        """PRD §3.8: "On successful resolution, Estate.contested_at
        is cleared back to null."

        Claim: after re-submit + accept of the REVISION_REQUESTED
        filing, CONTESTED -> IN_PROBATE succeeds and clears
        contested_at.
        """
        bundle = setup_in_probate_for_contested_filing_cascade()
        estate = bundle["estate"]
        executor = bundle["executor"]
        exec_h = bundle["executor_headers"]
        filing = bundle["inventory_filing"]
        # CONTEST.
        api_client.transition_estate(
            estate["id"], estate_state_payload("CONTESTED"),
            TEST_USERS["court_clerk_headers"],
        )
        # Re-submit the filing (executor: REVISION_REQUESTED ->
        # SUBMITTED).
        transition_filing(
            estate["id"], filing["id"], to_status="SUBMITTED",
            headers=exec_h,
        )
        # Accept the filing — but wait, accepting an
        # INVENTORY_REPORT (PRD §3.7) requires every asset
        # INVENTORIED/APPRAISED/EXCLUDED. We have no assets, so the
        # vacuous "every" is satisfied. Accept should succeed.
        transition_filing(
            estate["id"], filing["id"], to_status="ACCEPTED",
            headers=TEST_USERS["court_clerk_headers"],
        )
        # Resolve.
        resp = api_client.transition_estate(
            estate["id"], estate_state_payload("IN_PROBATE"),
            TEST_USERS["court_clerk_headers"],
        )
        estate_after = validate_success(resp)
        assert estate_after["admin_phase"] == "IN_PROBATE"
        assert estate_after.get("contested_at") in (None, ""), (
            f"contested_at must clear to null on resolution, got "
            f"{estate_after.get('contested_at')!r}"
        )
